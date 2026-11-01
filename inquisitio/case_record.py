from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


CASE_RECORD_SCHEMA: dict[str, dict[str, type | tuple[type, ...]]] = {
    "matter": {"caption": str, "docket": str, "court": str, "incident_date": str},
    "client": {
        "name": str, "other_names": list, "birthDate": str, "address1": str,
        "business_address": str, "driversLicenseNumber": str,
    },
    "vehicle": {
        "client_was_owner": (bool, type(None)), "owner_name": str, "owner_address": str,
    },
    "employment": {
        "employer_name": str, "employer_address": str, "jobTitle": str, "duties": str,
        "pay_rate": str, "lostWagesStart": str, "lostWagesEnd": str,
    },
    "counsel": {"name": str, "juris_no": str, "firm": str, "address": str},
}


@dataclass(frozen=True)
class RecordDraft:
    item_id: str
    text: str
    paths: tuple[str, ...]
    values: tuple[str, ...]
    missing: tuple[str, ...] = ()


def validate_case_record_bytes(data: bytes) -> tuple[dict[str, Any], str]:
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("case_record.json must be UTF-8 encoded.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"case_record.json is invalid JSON at line {exc.lineno}, column {exc.colno}.") from exc
    if not isinstance(value, dict):
        raise ValueError("case_record.json: root must be an object.")
    unknown_sections = set(value) - set(CASE_RECORD_SCHEMA)
    if unknown_sections:
        raise ValueError(f"case_record.json: unsupported field {sorted(unknown_sections)[0]}.")
    for section, fields in CASE_RECORD_SCHEMA.items():
        section_value = value.get(section)
        if not isinstance(section_value, dict):
            raise ValueError(f"case_record.json: {section} must be an object.")
        unknown = set(section_value) - set(fields)
        if unknown:
            raise ValueError(f"case_record.json: unsupported field {section}.{sorted(unknown)[0]}.")
        for field, expected in fields.items():
            path = f"{section}.{field}"
            if field not in section_value:
                raise ValueError(f"case_record.json: missing field {path}.")
            field_value = section_value[field]
            if not isinstance(field_value, expected):
                expected_name = "boolean or null" if isinstance(expected, tuple) else expected.__name__
                raise ValueError(f"case_record.json: {path} must be {expected_name}.")
            if isinstance(field_value, str) and len(field_value) > 2_000:
                raise ValueError(f"case_record.json: {path} exceeds 2,000 characters.")
            if path == "client.other_names":
                if any(not isinstance(name, str) or len(name) > 500 for name in field_value):
                    raise ValueError("case_record.json: client.other_names must contain strings of 500 characters or fewer.")
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return value, hashlib.sha256(canonical).hexdigest()


def metadata_from_case_record(case_record: dict[str, Any]) -> dict[str, str]:
    matter = case_record["matter"]
    client = case_record["client"]
    return {
        "docket_number": matter["docket"],
        "court": matter["court"],
        "plaintiff": client["name"],
        "incident_date": matter["incident_date"],
    }


def _present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _joined(prefix: str, pairs: list[tuple[str, Any]]) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    parts: list[str] = []
    paths: list[str] = []
    values: list[str] = []
    missing: list[str] = []
    for label, value in pairs:
        path = f"{prefix}.{label}"
        if _present(value):
            paths.append(path)
            values.append(str(value).strip())
            parts.append(str(value).strip())
        else:
            missing.append(path)
    return "; ".join(parts), tuple(paths), tuple(values), tuple(missing)


def form_202_record_drafts(case_record: dict[str, Any]) -> dict[str, RecordDraft]:
    client = case_record["client"]
    vehicle = case_record["vehicle"]
    employment = case_record["employment"]
    drafts: dict[str, RecordDraft] = {}

    if _present(client["name"]):
        names = [client["name"], *client["other_names"]]
        text = f"Full name: {names[0]}."
        paths = ["client.name"]
        if len(names) > 1:
            text += " Other names: " + "; ".join(names[1:]) + "."
            paths.extend(f"client.other_names[{index}]" for index in range(len(names) - 1))
        drafts["202-1-a"] = RecordDraft("202-1-a", text, tuple(paths), tuple(names))

    simple = {
        "202-1-b": ("client.birthDate", client["birthDate"], "Date of birth"),
        "202-1-c": ("client.driversLicenseNumber", client["driversLicenseNumber"], "Motor vehicle operator license"),
        "202-1-d": ("client.address1", client["address1"], "Home address"),
        "202-1-e": ("client.business_address", client["business_address"], "Business address"),
        "202-23-c": ("employment.pay_rate", employment["pay_rate"], "Pay rate"),
    }
    for item_id, (path, value, label) in simple.items():
        if _present(value):
            drafts[item_id] = RecordDraft(item_id, f"{label}: {str(value).strip()}.", (path,), (str(value).strip(),))

    owner = vehicle["client_was_owner"]
    if owner is True:
        drafts["202-1-f"] = RecordDraft(
            "202-1-f", "Not applicable: the client was the owner of the subject vehicle.",
            ("vehicle.client_was_owner",), ("true",),
        )
    elif owner is False:
        value, paths, values, missing = _joined("vehicle", [
            ("owner_name", vehicle["owner_name"]), ("owner_address", vehicle["owner_address"]),
        ])
        text = "Owner or lessor: " + (value or "not identified") + "."
        drafts["202-1-f"] = RecordDraft(
            "202-1-f", text, ("vehicle.client_was_owner", *paths), ("false", *values), missing,
        )

    employer, paths, values, missing = _joined("employment", [
        ("employer_name", employment["employer_name"]),
        ("employer_address", employment["employer_address"]),
    ])
    if paths:
        drafts["202-23-a"] = RecordDraft("202-23-a", "Employer: " + employer + ".", paths, values, missing)

    job, paths, values, missing = _joined("employment", [
        ("jobTitle", employment["jobTitle"]), ("duties", employment["duties"]),
    ])
    if paths:
        drafts["202-23-b"] = RecordDraft("202-23-b", "Occupation and duties: " + job + ".", paths, values, missing)

    dates, paths, values, missing = _joined("employment", [
        ("lostWagesStart", employment["lostWagesStart"]),
        ("lostWagesEnd", employment["lostWagesEnd"]),
    ])
    if paths:
        drafts["202-23-f"] = RecordDraft("202-23-f", "Lost work dates: " + dates + ".", paths, values, missing)
    return drafts


def _normalized(value: str) -> str:
    value = value.casefold().strip()
    for pattern in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return re.sub(r"[^a-z0-9]+", "", value)


def _same_name(left: str, right: str) -> bool:
    left_tokens = re.findall(r"[a-z]+", left.casefold())
    right_tokens = re.findall(r"[a-z]+", right.casefold())
    if not left_tokens or not right_tokens:
        return False
    return left_tokens[-1] == right_tokens[-1] and left_tokens[0][0] == right_tokens[0][0]


def _case_record_citation(path: str, value: str, sha256: str) -> dict[str, Any]:
    return {
        "citation_kind": "case_record",
        "citation_label": f"[Case record: {path}]",
        "field_path": path,
        "source_id": "CASE-RECORD",
        "filename": "case_record.json",
        "page": None,
        "quote": value,
        "document_sha256": sha256,
        "segment_id": f"CASE-RECORD:{path}",
        "fact_id": f"CASE-RECORD:{path}",
        "citation_validated": True,
        "evidence_classification": "CASE_RECORD",
        "ocr_sourced": False,
    }


def apply_case_record(record: dict[str, Any], answers: dict[str, dict[str, Any]]) -> None:
    case_record = record.get("case_record")
    if not case_record or record.get("form_id") != "202":
        return
    sha256 = record["case_record_sha256"]
    for item_id, draft in form_202_record_drafts(case_record).items():
        current = answers[item_id]
        citations = [_case_record_citation(path, value, sha256) for path, value in zip(draft.paths, draft.values)]
        evidence_values = [
            str(citation.get("original_value") or citation.get("normalized_value") or citation.get("quote") or "")
            for citation in current.get("supporting_citations", [])
            if citation.get("citation_kind") != "case_record"
        ]
        normalized_evidence = {_normalized(value) for value in evidence_values}
        def supported_by_evidence(value: str) -> bool:
            normalized = _normalized(value)
            return any(normalized == candidate or normalized in candidate or candidate in normalized for candidate in normalized_evidence)
        if current.get("status") == "POTENTIAL_CONFLICT":
            conflicts = True
        elif item_id == "202-1-a":
            conflicts = bool(evidence_values) and not any(_same_name(draft.values[0], value) for value in evidence_values)
        else:
            conflicts = bool(evidence_values) and any(
                not supported_by_evidence(value)
                for value in draft.values if value.casefold() not in {"true", "false"}
            )
        if conflicts:
            current.update(
                status="POTENTIAL_CONFLICT", engine_status="POTENTIAL_CONFLICT",
                evidence_outcome="CASE_RECORD_CONFLICT", answer="", generated_answer="",
                conflicts=[*current.get("conflicts", []), {
                    "attribute": "case_record",
                    "description": "The case record and uploaded evidence contain different values.",
                    "facts": citations,
                }],
                supporting_citations=[*current.get("supporting_citations", []), *citations],
                evidence=[*current.get("supporting_citations", []), *citations],
                reason_code="CONFLICTING_SOURCES",
                required_follow_up="Resolve the case-record and evidence conflict before drafting an answer.",
            )
            continue
        current.update(
            status="DRAFT", engine_status="DRAFT",
            evidence_outcome="CASE_RECORD_DRAFT" if not draft.missing else "PARTIAL_CASE_RECORD_DRAFT",
            answer=draft.text, generated_answer=draft.text, supporting_citations=citations,
            evidence=citations, missing_information=list(draft.missing), reason_code="",
            required_follow_up="Obtain the specifically missing case-record fields." if draft.missing else "Attorney review and approval required.",
        )
