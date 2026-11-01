from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path

import pdfplumber
from docx import Document

from inquisitio.exporter import export_case, export_case_pdf, export_traceability
from inquisitio.forms import load_form


ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def test_export_contains_every_form_202_item(self) -> None:
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "202").to_dict()
        answers = {item["item_id"]: {"status": "EMPTY", "answer": "", "evidence": []}
                   for item in form["items"]}
        record = {
            "case_name": "Test Matter", "form_id": "202", "form": form, "answers": answers,
            "metadata": {"docket_number": "CV-123", "plaintiff": "A", "defendant": "B"},
        }
        document = Document(BytesIO(export_case(record)))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("cell phone", text)
        self.assertEqual(text.count("ANSWER:"), 81)
        self.assertEqual(text.count("REQUESTS FOR PRODUCTION"), 2)
        self.assertNotIn("[NO_RESPONSIVE_EVIDENCE]", text)
        # Firm profile installed (data/firm_profile_202.json): unfilled slots carry
        # the firm's Filevine merge fields and stock answers, never the generic bracket.
        self.assertIn("Practice Book", text)
        self.assertIn("{{client.birthDate}}", text)
        self.assertIn("Keith Anthony Esq., 426171", text)
        self.assertNotIn("[No response entered - attorney review required.]", text)

    def test_export_without_firm_profile_keeps_generic_fallback(self) -> None:
        import inquisitio.exporter as exporter_module
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "202").to_dict()
        record = {
            "case_name": "Test Matter", "form_id": "202", "form": form, "answers": {},
            "metadata": {"docket_number": "CV-123", "plaintiff": "A", "defendant": "B"},
        }
        original = exporter_module._load_firm_profile
        exporter_module._load_firm_profile = lambda form_id: None
        try:
            document = Document(BytesIO(export_case(record)))
        finally:
            exporter_module._load_firm_profile = original
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Form 202", text)
        self.assertIn("[No response entered - attorney review required.]", text)
        self.assertNotIn("{{client.birthDate}}", text)

    def test_non_string_metadata_does_not_break_export(self) -> None:
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "207").to_dict()
        record = {"case_name": "Test", "form_id": "207", "form": form, "answers": {},
                  "metadata": {"docket_number": 123, "plaintiff": None}}
        document = Document(BytesIO(export_case(record)))
        self.assertEqual(document.tables[0].cell(0, 0).text, "DOCKET NO.: 123")

    def test_review_export_and_traceability_preserve_status_and_exact_citation(self) -> None:
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "207").to_dict()
        quote = "Jordan Moss currently earns gross weekly income of $1,450.00 per week."
        citation = {
            "fact_id": "F-123", "source_id": "E-001", "filename": "payroll_record.pdf", "page": 2,
            "quote": quote, "document_sha256": "a" * 64, "evidence_classification": "THIRD_PARTY_RECORD",
        }
        answers = {item["item_id"]: {
            "status": "EMPTY", "answer": "",
            "supporting_citations": [], "missing_information": ["responsive evidence"], "conflicts": [],
        } for item in form["items"]}
        answers["207-3-c"] = {
            "status": "DRAFT", "evidence_outcome": "SUPPORTED_DRAFT",
            "answer": "The responding party's current gross weekly employment income is $1,450.00.",
            "supporting_citations": [citation], "missing_information": [], "conflicts": [], "edit_history": [],
        }
        record = {
            "case_name": "Moss v. Bright", "form_id": "207", "form": form, "answers": answers,
            "metadata": {"docket_number": "FA-26-1", "plaintiff": "Jordan Moss", "defendant": "Casey Bright"},
        }
        response_doc = Document(BytesIO(export_case(record)))
        response_text = "\n".join(paragraph.text for paragraph in response_doc.paragraphs)
        self.assertIn("RESPONDING PARTY'S RESPONSES TO", response_text)
        self.assertIn("ANSWER:\tThe responding party's current gross weekly employment income is $1,450.00.", response_text)
        self.assertIn("[No response entered - attorney review required.]", response_text)
        self.assertNotIn("Slot status:", response_text)
        self.assertNotIn("Exact source:", response_text)

        trace_doc = Document(BytesIO(export_traceability(record)))
        trace_text = "\n".join(paragraph.text for paragraph in trace_doc.paragraphs)
        self.assertIn(quote, trace_text)
        self.assertIn("PDF page 2", trace_text)
        self.assertIn("a" * 64, trace_text)
        self.assertIn("Not approved", trace_text)

    def test_short_acceptance_answers_use_reference_format_for_both_forms(self) -> None:
        for form_id, answer in (("202", "yes"), ("207", "no.")):
            form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), form_id).to_dict()
            item_id = form["items"][0]["item_id"]
            record = {
                "case_name": "Test Matter", "form_id": form_id, "form": form,
                "answers": {item_id: {"status": "APPROVED", "answer": answer}},
                "metadata": {"docket_number": "CV-123", "plaintiff": "A", "defendant": "B"},
            }
            document = Document(BytesIO(export_case(record)))
            answer_paragraphs = [p for p in document.paragraphs if p.text.startswith("ANSWER:")]
            self.assertEqual(answer_paragraphs[0].text, f"ANSWER:\t{'Yes.' if form_id == '202' else 'No.'}")
            self.assertEqual(answer_paragraphs[0].style.name, "Interrogatory Answer")
            self.assertTrue(all(run.bold for run in answer_paragraphs[0].runs))

    def test_completed_form_pdf_contains_caption_questions_responses_and_verification(self) -> None:
        for form_id, expected_items in (("202", 81), ("207", 55)):
            form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), form_id).to_dict()
            answers = {item["item_id"]: {
                "status": "EMPTY",
                "answer": "", "missing_information": ["responsive evidence"],
            } for item in form["items"]}
            first_id = form["items"][0]["item_id"]
            answers[first_id] = {
                "status": "DRAFT", "evidence_outcome": "SUPPORTED_DRAFT",
                "answer": "Jordan Moss.", "missing_information": [],
            }
            record = {
                "case_name": "Moss v. Bright", "form_id": form_id, "form": form, "answers": answers,
                "metadata": {
                    "docket_number": "CV-2026-001", "plaintiff": "Jordan Moss", "defendant": "Casey Bright",
                    "judicial_district": "Hartford", "court": "Superior Court", "response_date": "2026-10-19",
                },
            }
            with pdfplumber.open(BytesIO(export_case_pdf(record))) as pdf:
                self.assertGreater(len(pdf.pages), 2)
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            # WR-012: the Completed-form PDF is the final filing document.
            self.assertIn("ATTORNEY REVIEW DRAFT - NOT FOR SERVICE", text)  # not all approved
            self.assertIn("CV-2026-001", text)
            self.assertIn("JORDAN MOSS", text)
            self.assertEqual(text.count("ANSWER:"), expected_items)
            self.assertEqual(text.count("RESPONSE:"), 13 if form_id == "202" else 0)
            self.assertIn("VERIFICATION", text)
            self.assertIn("CERTIFICATION", text)
            self.assertIn("STATE OF CONNECTICUT", text)
            # No review apparatus in the final paper.
            self.assertNotIn("Slot status", text)
            self.assertNotIn("[REVIEW", text)
            self.assertNotIn("Source:", text)

    def test_completed_form_pdf_clean_when_fully_approved(self) -> None:
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "202").to_dict()
        answers = {item["item_id"]: {"status": "APPROVED", "answer": "None."} for item in form["items"]}
        record = {
            "case_name": "Moss v. Bright", "form_id": "202", "form": form, "answers": answers,
            "metadata": {"docket_number": "CV-2026-001", "plaintiff": "Jordan Moss", "defendant": "Casey Bright",
                         "judicial_district": "Hartford", "court": "Superior Court", "response_date": "2026-10-19"},
        }
        with pdfplumber.open(BytesIO(export_case_pdf(record))) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        self.assertNotIn("ATTORNEY REVIEW DRAFT", text)
        self.assertNotIn("DRAFT - ATTORNEY REVIEW PENDING", text)
        self.assertNotIn("[", text.replace("[W", ""))


if __name__ == "__main__":
    unittest.main()
