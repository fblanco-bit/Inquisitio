"""WR-009 acceptance tests: the filled Rivera questionnaire completes the form.

Segments are built from the real filled questionnaire PDF with pdfplumber
(the same extraction family the app uses), so the parser is exercised against
genuine wrapped lines, not hand-made strings.
"""
from __future__ import annotations

import copy
import unittest
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from inquisitio.forms import load_form
from inquisitio.questionnaire import COMPOSE, apply_questionnaire, parse_questionnaire

ROOT = Path(__file__).resolve().parents[1]
FILLED = ROOT / "tests" / "fixtures" / "Rivera_Client_Questionnaire_FILLED.pdf"


@dataclass
class Seg:
    segment_id: str
    source_id: str
    filename: str
    page: int
    text: str
    kind: str = "paragraph"


@dataclass
class Doc:
    source_id: str
    filename: str
    sha256: str
    pages: int = 3


def _load_segments():
    segments = []
    with pdfplumber.open(FILLED) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            segments.append(Seg(f"S-{number}", "E-009", FILLED.name, number, page.extract_text() or ""))
    return segments, [Doc("E-009", FILLED.name, "f" * 64)]


def _empty_answers():
    form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "202")
    return {
        item.item_id: {
            "answer": "", "generated_answer": "", "status": "EMPTY", "engine_status": "EMPTY",
            "supporting_citations": [], "missing_information": ["x"], "conflicts": [],
            "evidence_outcome": "", "reason_code": "", "required_follow_up": "",
            "requires_revalidation": False, "approval": None, "edit_history": [],
        }
        for item in form.items
    }


class QuestionnaireTests(unittest.TestCase):
    def test_parser_reads_the_filled_pdf(self) -> None:
        segments, documents = _load_segments()
        fields = parse_questionnaire(segments, documents)
        self.assertGreaterEqual(len(fields), 40)
        self.assertEqual(fields["dob"]["value"], "06/18/1984")
        # Wrapped line is reassembled.
        self.assertIn("post-traumatic", fields["injuries"]["value"])
        self.assertIn("headaches", fields["injuries"]["value"])

    def test_filled_questionnaire_completes_empty_slots_with_citations(self) -> None:
        segments, documents = _load_segments()
        answers = _empty_answers()
        filled = apply_questionnaire(answers, segments, documents)
        self.assertGreaterEqual(filled, 55)
        hospital = answers["202-4"]
        self.assertIn("Harborlight General Hospital", hospital["answer"])
        self.assertEqual(hospital["status"], "DRAFT")
        self.assertEqual(hospital["evidence_outcome"], "CLIENT_QUESTIONNAIRE")
        self.assertEqual(hospital["missing_information"], [])
        self.assertTrue(hospital["supporting_citations"])
        citation = hospital["supporting_citations"][0]
        self.assertEqual(citation["citation_kind"], "client_questionnaire")
        self.assertIn("Hospital - Name:", citation["quote"])
        self.assertGreaterEqual(citation["page"], 1)
        # NONE answers fan out to dependent subparts.
        self.assertEqual(answers["202-20-a"]["answer"], "None.")
        self.assertEqual(answers["202-20-i"]["answer"], "None.")
        # Every composed slot the questionnaire covers is no longer empty.
        untouched = [item_id for item_id in COMPOSE if not answers[item_id]["answer"]]
        self.assertEqual(untouched, [])

    def test_evidence_draft_is_never_overwritten(self) -> None:
        segments, documents = _load_segments()
        answers = _empty_answers()
        agreeing = "Date of birth: 06/18/1984."
        answers["202-1-b"].update(answer=agreeing, generated_answer=agreeing, status="DRAFT")
        disagreeing = "Date first treated: 03/01/2026 at Memorial Clinic."
        answers["202-3"].update(answer=disagreeing, generated_answer=disagreeing, status="DRAFT")
        edited = "Attorney wrote this by hand."
        answers["202-5"].update(answer=edited, generated_answer="engine text", status="EDITED")
        apply_questionnaire(answers, segments, documents)
        self.assertEqual(answers["202-1-b"]["answer"], agreeing)            # kept
        self.assertEqual(answers["202-1-b"]["status"], "DRAFT")             # corroborated, not conflicted
        self.assertTrue(answers["202-1-b"]["supporting_citations"])         # corroborating citation added
        self.assertEqual(answers["202-3"]["answer"], disagreeing)           # kept, not replaced
        self.assertEqual(answers["202-3"]["status"], "POTENTIAL_CONFLICT")  # disagreement surfaced
        self.assertTrue(answers["202-3"]["conflicts"])
        self.assertEqual(answers["202-5"]["answer"], edited)                # attorney text untouched
        self.assertEqual(answers["202-5"]["status"], "EDITED")
        self.assertEqual(answers["202-5"]["conflicts"], [])

    def test_identical_input_gives_identical_output(self) -> None:
        segments, documents = _load_segments()
        first = _empty_answers()
        second = copy.deepcopy(first)
        apply_questionnaire(first, segments, documents)
        apply_questionnaire(second, segments, documents)
        self.assertEqual(first, second)

    def test_packet_without_questionnaire_changes_nothing(self) -> None:
        segments = [Seg("S-1", "E-001", "police_report.pdf", 1, "Operator: RIVERA, ELENA SOFIA. DOB: 06/18/1984.")]
        documents = [Doc("E-001", "police_report.pdf", "a" * 64, 1)]
        answers = _empty_answers()
        before = copy.deepcopy(answers)
        filled = apply_questionnaire(answers, segments, documents)
        self.assertEqual(filled, 0)
        self.assertEqual(answers, before)


if __name__ == "__main__":
    unittest.main()
