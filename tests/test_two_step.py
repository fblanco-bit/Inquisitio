"""WR-009 sequence acceptance: evidence first, questionnaire second.

Freddy's workflow, locked as a test (1 Nov 2026): step 1, evidence alone
builds the form with gaps shown; step 2, the filled client questionnaire is
added to the existing matter and reprocessed - the gaps fill, cited and
client-marked, evidence answers and attorney edits survive, and only the
documented items stay empty. Extraction here uses pdfplumber segments; the
packaged app extracts with its own backend, same text for these fixtures.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

import pdfplumber

try:
    from inquisitio import server
except ModuleNotFoundError as exc:  # fitz is unavailable in some environments
    server = None
    _skip_reason = f"server import failed: {exc}"
else:
    _skip_reason = ""
from inquisitio.evidence import EvidenceDocument, EvidenceSegment

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "tests" / "fixtures" / "FORM_202_PLUS_205_ALL_EVIDENCE_COMBINED.pdf"
QUESTIONNAIRE = ROOT / "tests" / "fixtures" / "Rivera_Client_Questionnaire_FILLED.pdf"
DOCUMENTED_EMPTY = {
    "202-26", "202-27",
    "202-31-a", "202-31-b", "202-31-c", "202-31-d", "202-31-e",
    "202-32-b", "202-32-c", "202-32-d", "202-32-e",
}


def _segments(path: Path, source_id: str):
    segments = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            segments.append(EvidenceSegment(
                f"{source_id}-{number}", source_id, path.name, number,
                page.extract_text() or "", "paragraph",
            ))
    return segments


def _record():
    return {
        "case_id": "c" * 32, "case_name": "Rivera v. Meridian Cargo Services", "form_id": "202",
        "metadata": {
            "docket_number": "CV-TEST-202-0042", "plaintiff": "Elena Sofia Rivera",
            "defendant": "Meridian Cargo Services LLC", "responding_party_role": "plaintiff",
            "interrogating_party": "Meridian Cargo Services LLC", "court": "Superior Court",
            "judicial_district": "New Haven at New Haven", "response_date": "2026-10-12",
        },
        "revision": 1, "answers": {},
    }


@unittest.skipIf(server is None, _skip_reason)
class TwoStepTests(unittest.TestCase):
    def test_evidence_then_questionnaire_completes_the_form(self) -> None:
        evidence_segments = _segments(EVIDENCE, "E-001")
        questionnaire_segments = _segments(QUESTIONNAIRE, "E-002")
        evidence_doc = EvidenceDocument("E-001", EVIDENCE.name, "a" * 64, len(evidence_segments), "TEXT_OK", tuple(evidence_segments))
        questionnaire_doc = EvidenceDocument("E-002", QUESTIONNAIRE.name, "b" * 64, len(questionnaire_segments), "TEXT_OK", tuple(questionnaire_segments))

        # Step 1: evidence only.
        record = _record()
        server._build_workspace(record, [evidence_doc], evidence_segments)
        self.assertEqual(record["matter_integrity"]["status"], "PASS")
        answered_step1 = {i for i, a in record["answers"].items() if str(a.get("answer", "")).strip()}
        self.assertGreaterEqual(len(answered_step1), 4)
        self.assertLess(len(answered_step1), 20)

        # An attorney edit between the steps must survive the reprocess.
        record["answers"]["202-1-b"]["answer"] = "June 18, 1984 (attorney confirmed)"
        record["answers"]["202-1-b"]["status"] = "EDITED"

        # Step 2: questionnaire added to the existing matter (reprocess path).
        previous = copy.deepcopy(record)
        rebuilt = _record()
        server._build_workspace(rebuilt, [evidence_doc, questionnaire_doc],
                                evidence_segments + questionnaire_segments, previous)
        answers = rebuilt["answers"]
        answered = {i for i, a in answers.items() if str(a.get("answer", "")).strip()}
        from_questionnaire = {i for i, a in answers.items() if a.get("evidence_outcome") == "CLIENT_QUESTIONNAIRE"}
        self.assertGreaterEqual(len(answered), 65)
        self.assertGreaterEqual(len(from_questionnaire), 55)
        empty = {i for i, a in answers.items() if not str(a.get("answer", "")).strip()}
        self.assertEqual(empty, DOCUMENTED_EMPTY)
        self.assertEqual(answers["202-1-b"]["answer"], "June 18, 1984 (attorney confirmed)")
        self.assertEqual(answers["202-1-b"]["status"], "EDITED")
        citation = answers["202-4"]["supporting_citations"][0]
        self.assertEqual(citation["citation_kind"], "client_questionnaire")


if __name__ == "__main__":
    unittest.main()
