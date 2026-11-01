from __future__ import annotations

import unittest
from unittest.mock import patch

from inquisitio.engine import ENGINE_STATUSES, build_response, extract_facts, requirement_for
from inquisitio.evidence import EvidenceSegment
from inquisitio.forms import FormItem, load_forms


METADATA = {
    "plaintiff": "Jordan Moss",
    "defendant": "Casey Bright",
    "responding_party_role": "plaintiff",
    "interrogating_party": "Casey Bright",
    "response_date": "2026-10-18",
}


def segment(text: str, source: str = "E-001", filename: str = "payroll_record.pdf", page: int = 2, ordinal: int = 1) -> EvidenceSegment:
    return EvidenceSegment(f"{source}:p{page}:s{ordinal}", source, filename, page, text, "text")


def documents(*sources: tuple[str, str]) -> list[dict]:
    return [{"source_id": source, "filename": filename, "sha256": (source[-1] * 64)} for source, filename in sources]


def response(item_id: str, text: str, segments: list[EvidenceSegment], metadata: dict | None = None) -> dict:
    item = FormItem(item_id, 3, "c", "", text)
    docs = documents(*[(value.source_id, value.filename) for value in segments])
    facts = extract_facts(segments, metadata or METADATA, docs)
    return build_response(item, segments, facts, metadata or METADATA, docs)


class EvidenceEngineTests(unittest.TestCase):
    def test_correct_party_current_gross_weekly_income_is_drafted(self) -> None:
        quote = "Jordan Moss currently earns gross weekly income of $1,450.00 per week."
        result = response("207-3-c", "What is your income per week?", [segment(quote)])
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(result["evidence_outcome"], "SUPPORTED_DRAFT")
        self.assertEqual(result["answer"], "The responding party's current gross weekly employment income is $1,450.00.")
        self.assertEqual(result["supporting_citations"][0]["quote"], quote)
        self.assertEqual(result["supporting_citations"][0]["page"], 2)
        self.assertEqual(len(result["supporting_citations"][0]["document_sha256"]), 64)

    def test_wrong_party_net_and_historical_income_do_not_answer(self) -> None:
        values = [
            segment("Casey Bright currently earns gross weekly income of $2,300.00 per week.", "E-001"),
            segment("Jordan Moss currently earns net weekly income of $1,080.00 per week.", "E-002"),
            segment("Jordan Moss earned gross weekly income of $1,200.00 per week in 2024.", "E-003"),
        ]
        result = response("207-3-c", "What is your income per week?", values)
        self.assertEqual(result["answer"], "")
        self.assertEqual(result["status"], "EMPTY")
        self.assertEqual(result["reason_code"], "NOT_IN_EVIDENCE")

    def test_missing_responding_party_blocks_party_dependent_draft(self) -> None:
        metadata = dict(METADATA, responding_party_role="")
        result = response("207-3-c", "What is your income per week?", [segment("Respondent currently earns gross weekly income of $900.00 per week.")], metadata)
        self.assertEqual(result["status"], "REQUIRES_CLIENT")
        self.assertEqual(result["answer"], "")

    def test_corroborating_sources_are_both_cited(self) -> None:
        values = [
            segment("Jordan Moss currently earns gross weekly income of $1,450.00 per week.", "E-001", "payroll_record.pdf"),
            segment("Jordan Moss currently earns gross weekly income of $1,450.00 per week.", "E-002", "sworn_affidavit.pdf"),
        ]
        result = response("207-3-c", "What is your income per week?", values)
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual({item["source_id"] for item in result["supporting_citations"]}, {"E-001", "E-002"})

    def test_current_conflict_preserves_both_sources(self) -> None:
        values = [
            segment("Jordan Moss currently earns gross weekly income of $1,450.00 per week.", "E-001"),
            segment("Jordan Moss currently earns gross weekly income of $1,525.00 per week.", "E-002"),
        ]
        result = response("207-3-c", "What is your income per week?", values)
        self.assertEqual(result["status"], "POTENTIAL_CONFLICT")
        self.assertEqual(result["answer"], "")
        self.assertEqual(len(result["supporting_citations"]), 2)

    def test_narrative_injury_is_drafted_without_discarding_complaint_by_classification(self) -> None:
        medical = segment("Jordan Moss sustained a cervical strain as a result of the incident.", filename="medical_record.pdf")
        result = response("202-2", "Identify each injury sustained in the incident.", [medical])
        self.assertEqual(result["status"], "DRAFT")
        self.assertIn("cervical strain", result["answer"])
        allegation = segment("Jordan Moss sustained a concussion as a result of the incident.", filename="complaint.pdf")
        result = response("202-2", "Identify each injury sustained in the incident.", [allegation])
        self.assertIn("concussion", result["answer"])
        self.assertLess(result["supporting_citations"][0]["confidence"], 1.0)

    def test_partial_answer_lists_each_missing_component(self) -> None:
        value = segment("Fact: subject=Jordan Moss; attribute=first_treatment_provider; value=Dr. Lee.", filename="medical_record.pdf")
        result = response("202-3", "When, where and from whom was first treatment received?", [value])
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(result["evidence_outcome"], "PARTIAL_DRAFT")
        self.assertIn("Dr. Lee", result["answer"])
        self.assertEqual(set(result["missing_information"]), {"first treatment date", "first treatment location"})

    def test_silence_never_proves_nonapplicability(self) -> None:
        result = response("207-11-a", "If rental property is owned, identify its type.", [])
        self.assertEqual(result["status"], "EMPTY")

    def test_affirmative_reliable_negative_can_establish_nonapplicability(self) -> None:
        value = segment("Jordan Moss does not own any rental property.", filename="sworn_affidavit.pdf")
        result = response("207-11-a", "If rental property is owned, identify its type.", [value])
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(result["evidence_outcome"], "SUPPORTED_NOT_APPLICABLE")
        self.assertTrue(result["answer"].startswith("Not applicable:"))
        self.assertEqual(result["supporting_citations"][0]["quote"], value.text)

    def test_explicit_negative_is_not_discarded_for_generic_filename(self) -> None:
        value = segment("Jordan Moss does not own any rental property.", filename="notes.pdf")
        result = response("207-11-a", "If rental property is owned, identify its type.", [value])
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(result["supporting_citations"][0]["quote"], value.text)
        self.assertLess(result["supporting_citations"][0]["confidence"], 1.0)

    def test_every_form_item_has_an_internal_requirement_and_valid_status(self) -> None:
        forms = load_forms("assets/CT_Practice_Book_2026.pdf", "data/forms_cache.json")
        self.assertEqual((len(forms["202"].items), len(forms["207"].items)), (81, 55))
        for form in forms.values():
            for item in form.items:
                requirement = requirement_for(item)
                self.assertEqual(requirement.wording, " ".join(part for part in (item.prompt, item.text) if part))
                self.assertTrue(requirement.attributes)
                result = build_response(item, [], [], METADATA, [])
                self.assertIn(result["status"], ENGINE_STATUSES)
                self.assertEqual(result["answer"], "")

    def test_drafting_engine_operates_with_outbound_network_disabled(self) -> None:
        value = segment("Jordan Moss currently earns gross weekly income of $1,450.00 per week.")
        with patch("socket.socket.connect", side_effect=AssertionError("network access attempted")):
            result = response("207-3-c", "What is your income per week?", [value])
        self.assertEqual(result["status"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
