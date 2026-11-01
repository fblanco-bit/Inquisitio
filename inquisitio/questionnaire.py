"""WR-009: read the firm's client questionnaire and fill what evidence cannot.

The questionnaire (Client_Questionnaire_Form202) is a fixed document of
labeled lines, one "Label: value" per client-knowledge item. When a filled
copy is uploaded with the evidence packet, this module parses those lines
and fills only the answer slots the evidence left empty. Every fill carries
a citation to the questionnaire page and exact line, is marked
client-provided, and remains subject to attorney review. Evidence-backed
answers are never overwritten: agreement adds a corroborating citation;
disagreement adds a conflict and flags the slot. Deterministic text
processing only; no model, no network.
"""
from __future__ import annotations

import re

HEADER = "CLIENT QUESTIONNAIRE - FORM 202 INTERROGATORIES"

# Exact labels as the questionnaire prints them. Apostrophes are normalized.
LABELS = {
    "Client full legal name": "cq_name",
    "Other names you have been known by": "other_names",
    "Date of birth": "dob",
    "Driver's license": "license",
    "Home address": "home_address",
    "Business address": "business_address",
    "Vehicle owner or lessor": "vehicle_owner",
    "Injuries claimed": "injuries",
    "Present complaints": "present_complaints",
    "Full recovery date": "recovery",
    "First treatment - Date": "ft_date",
    "First treatment - Provider": "ft_provider",
    "First treatment - Location": "ft_location",
    "Hospital - Name": "hosp_name",
    "Hospital - Location": "hosp_location",
    "Hospital - Admission date": "hosp_admission",
    "Hospital - Discharge date": "hosp_discharge",
    "Treating providers": "providers",
    "Last treatment - Date": "lt_date",
    "Last treatment - Provider": "lt_provider",
    "Currently treating": "currently_treating",
    "Current providers": "current_providers",
    "Home or bed confinement dates": "confinement",
    "Medical reports received": "medical_reports",
    "Present disability claimed": "present_disability",
    "Nature of present disability": "present_disability_nature",
    "Permanent disability claimed": "permanent_disability",
    "Permanent disability - Body parts": "pd_parts",
    "Permanent disability - Lost activities": "pd_activities",
    "Permanent disability - Percentage of loss": "pd_percentage",
    "Permanent disability - Prognosis by": "pd_prognosis_by",
    "Permanent disability - Prognosis date": "pd_prognosis_date",
    "Other permanent disability assessments": "other_pd",
    "Expenses claimed": "expenses",
    "Insurer reimbursement": "reimbursement",
    "Other expenses or losses": "other_expenses",
    "Employer at incident - Name and address": "employer",
    "Occupation and job duties": "occupation",
    "Average weekly earnings": "weekly_earnings",
    "Work resumption date": "resumption_date",
    "Lost income claimed": "lost_income",
    "Lost work dates": "lost_work_dates",
    "Employers, prior three years": "prior_employers",
    "Earning capacity impairment claimed": "earning_capacity",
    "Prior related conditions": "prior_conditions",
    "Prior incidents with similar injuries": "prior_incidents",
    "Incidents since this one": "subsequent_incidents",
    "Workers' compensation claims since the incident": "wc_since",
    "Workers' comp claim from this incident": "wc_claim",
    "Workers' comp benefits received": "wc_benefits",
    "Statements you made": "statements",
    "Witnesses": "witnesses",
    "Photographs or recordings": "photos",
    "Surveillance material": "surveillance",
    "Alcohol, drugs or medications before": "alcohol_before",
    "Testing after": "testing_after",
    "Cell phone use": "cell_phone",
}

# Section headings and boilerplate to ignore while parsing.
_IGNORE = re.compile(
    r"^(\d+\. (About you|Your injuries|Treatment|Disability|Money and work|History|"
    r"Statements, witnesses, recordings|The incident)|FICTIONAL TEST DOCUMENT.*|"
    r"CLIENT QUESTIONNAIRE.*|Matter name:.*|Date completed:.*|Client signature:.*|"
    r"Answer every item.*|More than one hospital.*|Signing confirms.*|"
    r"Connecticut personal injury.*)$"
)

_NONEISH = {"none", "none.", "n/a", "n/a.", "no", "no.", "unknown", "unknown."}


def _norm_label(text: str) -> str:
    return text.replace("’", "'").strip()


def _label_key(text: str) -> str:
    """Matching form of a label: case-insensitive, inner whitespace collapsed."""
    return re.sub(r"\s+", " ", _norm_label(text)).lower()


_LABELS_BY_KEY = {_label_key(label): key for label, key in LABELS.items()}


def _clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    lower = value.lower()
    if lower in {"yes", "no", "none", "n/a", "unknown", "not recovered"}:
        value = value[0].upper() + value[1:].lower()
    if not value.endswith((".", "?", "!")):
        value += "."
    return value


def parse_questionnaire(segments, documents) -> dict:
    """Return {key: field} for the first questionnaire found in the packet.

    A field is {"value", "source_id", "filename", "page", "quote", "sha256"}.
    Returns {} when no document in the packet carries the questionnaire header.
    """
    sha_by_source = {doc.source_id: doc.sha256 for doc in documents}
    name_by_source = {doc.source_id: doc.filename for doc in documents}
    pages: dict[tuple[str, int], list[str]] = {}
    for segment in segments:
        pages.setdefault((segment.source_id, segment.page), []).append(segment.text)
    questionnaire_sources = {
        source_id for (source_id, _page), texts in pages.items()
        if HEADER in "\n".join(texts)
    }
    if not questionnaire_sources:
        return {}
    source_id = sorted(questionnaire_sources)[0]
    fields: dict[str, dict] = {}
    current_key = None
    for (src, page) in sorted((key for key in pages if key[0] == source_id), key=lambda k: k[1]):
        for raw_line in "\n".join(pages[(src, page)]).splitlines():
            line = _norm_label(raw_line)
            if not line or _IGNORE.match(line):
                continue
            matched = False
            if ":" in line:
                label, _, value = line.partition(":")
                key = _LABELS_BY_KEY.get(_label_key(label))
                if key:
                    fields[key] = {
                        "value": value.strip(), "source_id": source_id,
                        "filename": name_by_source.get(source_id, ""), "page": page,
                        "quote": line, "sha256": sha_by_source.get(source_id, ""),
                    }
                    current_key = key
                    matched = True
            if not matched and current_key:
                # Wrapped continuation of the previous labeled line.
                fields[current_key]["value"] = (fields[current_key]["value"] + " " + line).strip()
                fields[current_key]["quote"] = (fields[current_key]["quote"] + " " + line).strip()
    return fields


# item_id -> the questionnaire keys that compose its answer, in order.
COMPOSE = {
    "202-1-a": ["cq_name", "other_names"],
    "202-1-b": ["dob"], "202-1-c": ["license"], "202-1-d": ["home_address"],
    "202-1-e": ["business_address"], "202-1-f": ["vehicle_owner"],
    "202-2": ["injuries"],
    "202-3": ["ft_date", "ft_provider", "ft_location"],
    "202-4": ["hosp_name", "hosp_location", "hosp_admission", "hosp_discharge"],
    "202-5": ["providers"],
    "202-6": ["lt_date", "lt_provider"],
    "202-7": ["recovery"], "202-8": ["present_complaints"],
    "202-9": ["currently_treating"], "202-10": ["current_providers"],
    "202-11": ["present_disability"], "202-12": ["present_disability_nature"],
    "202-13": ["permanent_disability"],
    "202-14-a": ["pd_parts"], "202-14-b": ["pd_activities"], "202-14-c": ["pd_percentage"],
    "202-14-d": ["pd_prognosis_by"], "202-14-e": ["pd_prognosis_date"],
    "202-15": ["confinement"], "202-16": ["medical_reports"],
    "202-17": ["expenses"], "202-18": ["reimbursement"],
    "202-19": ["prior_conditions"],
    "202-20-a": ["prior_incidents"],
    "202-21-a": ["subsequent_incidents"],
    "202-22-a": ["other_pd"],
    "202-23-a": ["employer"], "202-23-b": ["occupation"], "202-23-c": ["weekly_earnings"],
    "202-23-d": ["resumption_date"], "202-23-e": ["lost_income"],
    "202-23-f": ["lost_work_dates"], "202-23-g": ["prior_employers"],
    "202-24": ["earning_capacity"], "202-25": ["other_expenses"],
    "202-28": ["wc_since"], "202-29": ["statements"], "202-30": ["witnesses"],
    "202-32-a": ["photos"], "202-33": ["alcohol_before"],
    "202-34-a": ["testing_after"], "202-35": ["surveillance"],
    "202-36": ["wc_claim"], "202-37": ["wc_benefits"], "202-38": ["cell_phone"],
}

# When the lead answer is None/N/A, the dependent subparts inherit it.
FAN_WHEN_NONE = {
    "202-20-a": [f"202-20-{sub}" for sub in "bcdefghi"],
    "202-21-a": [f"202-21-{sub}" for sub in "bcdefghi"],
    "202-22-a": ["202-22-b", "202-22-c"],
    "202-29": [f"202-31-{sub}" for sub in "abcde"],
    "202-32-a": [f"202-32-{sub}" for sub in "bcde"],
    "202-34-a": ["202-34-b", "202-34-c"],
}

_FOLLOW_UP = "Client-provided from the questionnaire; attorney review required."


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _citation(field: dict) -> dict:
    return {
        "citation_kind": "client_questionnaire",
        "citation_label": f"Client questionnaire, PDF page {field['page']} (client-provided)",
        "source_id": field["source_id"], "filename": field["filename"],
        "page": field["page"], "quote": field["quote"],
        "document_sha256": field["sha256"], "ocr_sourced": False,
    }


def _fill(answer: dict, text: str, citations: list[dict]) -> None:
    answer["answer"] = text
    answer["generated_answer"] = text
    answer["status"] = "DRAFT"
    answer["engine_status"] = "DRAFT"
    answer["evidence_outcome"] = "CLIENT_QUESTIONNAIRE"
    answer["reason_code"] = ""
    answer["missing_information"] = []
    answer["required_follow_up"] = _FOLLOW_UP
    answer["requires_revalidation"] = False
    answer["supporting_citations"] = list(answer.get("supporting_citations", [])) + citations


def apply_questionnaire(answers: dict, segments, documents) -> int:
    """Merge questionnaire fields into the built answers. Returns slots filled.

    Rules (WR-009, approved 1 Nov 2026): slots the evidence drafted are never
    overwritten - agreement adds a corroborating citation, disagreement adds a
    conflict and flags the slot. Attorney-edited slots are left entirely alone.
    Only empty slots are filled, cited to the questionnaire.
    """
    fields = parse_questionnaire(segments, documents)
    if not fields:
        return 0
    filled = 0
    for item_id, keys in COMPOSE.items():
        answer = answers.get(item_id)
        if answer is None:
            continue
        present = [fields[key] for key in keys if key in fields and fields[key]["value"].strip()]
        if not present:
            continue
        values = [field["value"].strip() for field in present]
        noneish = all(value.lower().rstrip(".") in {v.rstrip(".") for v in _NONEISH} for value in values)
        if item_id == "202-1-a" and len(values) == 2 and values[1].lower().rstrip(".") not in {v.rstrip(".") for v in _NONEISH}:
            text = _clean_value(f"{values[0]}; also known as {values[1]}")
        elif noneish:
            text = _clean_value(values[0])
        else:
            text = _clean_value("; ".join(values))
        citations = [_citation(field) for field in present]
        existing = str(answer.get("answer", "")).strip()
        edited = str(answer.get("answer", "")) != str(answer.get("generated_answer", "")) or answer.get("status") == "EDITED"
        if existing and edited:
            continue  # attorney text always wins; do not even annotate
        if existing:
            drafted = _normalized(existing)
            offered = _normalized(text)
            if offered and (offered in drafted or drafted in offered):
                answer["supporting_citations"] = list(answer.get("supporting_citations", [])) + citations
            else:
                answer["conflicts"] = list(answer.get("conflicts", [])) + [{
                    "description": f"Client questionnaire gives a different answer: \"{text}\""
                }]
                answer["status"] = "POTENTIAL_CONFLICT"
                answer["engine_status"] = "POTENTIAL_CONFLICT"
                answer["supporting_citations"] = list(answer.get("supporting_citations", [])) + citations
            continue
        _fill(answer, text, citations)
        filled += 1
        if noneish:
            for dependent_id in FAN_WHEN_NONE.get(item_id, []):
                dependent = answers.get(dependent_id)
                if dependent is not None and not str(dependent.get("answer", "")).strip():
                    _fill(dependent, text, citations)
                    filled += 1
    return filled
