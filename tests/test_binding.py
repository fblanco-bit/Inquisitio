from __future__ import annotations

import unittest

from inquisitio.binding import build_answer, rank_evidence
from inquisitio.evidence import EvidenceSegment
from inquisitio.forms import FormItem


class BindingTests(unittest.TestCase):
    def test_medical_evidence_is_suggested_but_not_inserted(self) -> None:
        item = FormItem("202-2", 2, "", "", "Identify and list each injury you claim to have sustained.")
        segment = EvidenceSegment("E-001:p2:s1", "E-001", "medical.pdf", 2,
                                  "The patient was diagnosed with a cervical strain.", "text")
        candidates = rank_evidence(item, [segment])
        answer = build_answer(item, candidates)
        self.assertEqual(answer["status"], "REVIEW_REQUIRED")
        self.assertEqual(answer["answer"], "")
        self.assertEqual(answer["evidence"][0]["quote"], segment.text)
        self.assertEqual(answer["evidence"][0]["page"], 2)

    def test_no_evidence_never_creates_factual_answer(self) -> None:
        item = FormItem("207-3-c", 3, "c", "Give the name and address of your employer.",
                        "What is your income per week?")
        answer = build_answer(item, [])
        self.assertEqual(answer["answer"], "")
        self.assertIn(answer["status"], {"CLIENT_CONFIRMATION_REQUIRED", "NO_RESPONSIVE_EVIDENCE"})

    def test_distinct_values_from_two_sources_are_flagged(self) -> None:
        item = FormItem("207-3-c", 3, "c", "", "What is your income per week?")
        segments = [
            EvidenceSegment("E-001:p1:s1", "E-001", "paystub.pdf", 1,
                            "Weekly income paid was $850.00 in wages.", "text"),
            EvidenceSegment("E-002:p1:s1", "E-002", "affidavit.pdf", 1,
                            "Weekly income from wages is $920.00.", "text"),
        ]
        answer = build_answer(item, rank_evidence(item, segments))
        self.assertEqual(answer["status"], "POTENTIAL_CONFLICT")

    def test_explicit_weekly_income_drafted_with_page_citation(self) -> None:
        item = FormItem("207-3-c", 3, "c", "Give the name and address of your employer.",
                        "What is your income per week?")
        segment = EvidenceSegment("E-001:p2:s1", "E-001", "affidavit.pdf", 2,
                                  "Respondent earns weekly income of $850.00 per week.", "text")
        result = build_answer(item, rank_evidence(item, [segment]))
        self.assertEqual(result["status"], "DRAFTED_FROM_EVIDENCE")
        self.assertIn("$850.00", result["answer"])
        self.assertEqual(result["evidence"][0]["page"], 2)

    def test_unattributed_income_is_not_drafted(self) -> None:
        item = FormItem("207-3-c", 3, "c", "", "What is your income per week?")
        segment = EvidenceSegment("E-001:p1:s1", "E-001", "opinion.pdf", 1,
                                  "Weekly income of $850.00 was mentioned in testimony.", "text")
        result = build_answer(item, rank_evidence(item, [segment]))
        self.assertEqual(result["answer"], "")

    def test_unrelated_single_word_match_is_not_suggested(self) -> None:
        item = FormItem("202-33", 33, "", "", "Did the operator consume alcohol or drugs in the eight hours before the incident?")
        segment = EvidenceSegment("E-001:p1:s1", "E-001", "earnings.pdf", 1,
                                  "The employee worked eight hours of overtime.", "text")
        self.assertEqual(rank_evidence(item, [segment]), [])

    def test_relevant_match_survives_large_repetitive_corpus(self) -> None:
        item = FormItem("202-2", 2, "", "", "Identify each injury sustained in the incident.")
        relevant = EvidenceSegment("E-001:p1:s1", "E-001", "medical.pdf", 1,
                                   "The patient was diagnosed with a cervical strain.", "text")
        noise = [EvidenceSegment(f"E-002:p{i}:s1", "E-002", "notes.pdf", i,
                                 "Routine follow up note with no new complaints.", "text") for i in range(1, 9301)]
        candidates = rank_evidence(item, noise + [relevant])
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].segment.segment_id, relevant.segment_id)


if __name__ == "__main__":
    unittest.main()
