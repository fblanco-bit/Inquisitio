from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class FormItem:
    item_id: str
    number: int
    label: str
    prompt: str
    text: str


@dataclass(frozen=True)
class FormTemplate:
    form_id: str
    title: str
    court: str
    response_party: str
    deadline_text: str
    items: tuple[FormItem, ...]
    source_sha256: str
    source_pages: str

    def to_dict(self) -> dict:
        return asdict(self)


FORM_SPECS = {
    "202": {
        "title": "Defendant's Interrogatories",
        "court": "Superior Court",
        "response_party": "Plaintiff",
        "pages": (613, 619),
        "deadline_text": "Answers are due under oath within sixty (60) days of filing.",
    },
    "205": {
        "title": "Defendant's Requests for Production",
        "court": "Superior Court",
        "response_party": "Plaintiff",
        "pages": (625, 626),
        "deadline_text": "Official Form 205 states production not later than sixty (60) days after service; counsel must verify applicable deadlines and orders.",
    },
    "207": {
        "title": "Interrogatories - Actions To Establish, Enforce or Modify Child Support Orders",
        "court": "Superior Court - Family Support Magistrate Division",
        "response_party": "Defendant/Plaintiff",
        "pages": (630, 634),
        "deadline_text": "Answers are due within sixty (60) days of filing.",
    },
}

_QUESTION = re.compile(r"^\s*\((\d+)\)\s+(.*)$")
_SUBPART = re.compile(r"(?:^|\n)\s*\(([a-z])\)\s+(.*?)(?=(?:\n\s*\([a-z]\)\s+)|\Z)", re.S)
_PAGE_ONLY = re.compile(r"^\d{1,4}$")


def _normalize(text: str) -> str:
    # A hyphen at the physical end of a PDF line is a layout artifact, not part
    # of the source word (for example, "infor-\nmation").
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _usable_lines(page_text: str, form_id: str) -> list[str]:
    lines: list[str] = []
    for raw in page_text.splitlines():
        stripped = raw.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped in {"APPENDIX OF FORMS", f"Form {form_id}"}:
            continue
        if stripped.startswith("(c) Copyrighted by") or stripped.startswith("© Copyrighted by"):
            continue
        if _PAGE_ONLY.fullmatch(stripped):
            continue
        cleaned = re.sub(rf"\bForm {form_id}\s+APPENDIX OF FORMS\b", "", raw)
        cleaned = re.sub(rf"\bAPPENDIX OF FORMS\s+Form {form_id}\b", "", cleaned)
        lines.append(cleaned.rstrip())
    return lines


def _extract_questions(pdf_path: Path, form_id: str) -> tuple[FormItem, ...]:
    first, last = FORM_SPECS[form_id]["pages"]
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) < last:
            raise ValueError(f"Practice Book is missing PDF page {last} required by Form {form_id}.")
        for page_number in range(first, last + 1):
            page_text = pdf.pages[page_number - 1].extract_text(layout=True) or ""
            lines.extend(_usable_lines(page_text, form_id))

    questions: list[tuple[int, str]] = []
    current_number: int | None = None
    current_lines: list[str] = []
    started = False
    skipping_comment = False
    for line in lines:
        match = _QUESTION.match(line)
        if match:
            if current_number is not None:
                questions.append((current_number, "\n".join(current_lines)))
            current_number = int(match.group(1))
            current_lines = [match.group(2)]
            started = True
            skipping_comment = False
            continue
        if not started:
            continue
        stripped = line.strip()
        if stripped in {"DEFENDANT,", "PLAINTIFF,"} or stripped.startswith("BY __________________"):
            break
        if stripped.startswith("COMMENT:"):
            skipping_comment = True
            continue
        if skipping_comment:
            continue
        current_lines.append(line)
    if current_number is not None:
        questions.append((current_number, "\n".join(current_lines)))

    expected = {"202": 38, "205": 13, "207": 12}[form_id]
    if [number for number, _ in questions] != list(range(1, expected + 1)):
        raise ValueError(f"Form {form_id} question sequence was not extracted completely.")

    items: list[FormItem] = []
    for number, raw in questions:
        subparts = list(_SUBPART.finditer(raw))
        if not subparts:
            text = _normalize(raw)
            items.append(FormItem(f"{form_id}-{number}", number, "", "", text))
            continue
        prompt = _normalize(raw[: subparts[0].start()])
        for part in subparts:
            label = part.group(1)
            text = _normalize(part.group(2))
            items.append(FormItem(f"{form_id}-{number}-{label}", number, label, prompt, text))
    return tuple(items)


@lru_cache(maxsize=4)
def load_form(pdf_path: str, form_id: str) -> FormTemplate:
    if form_id not in FORM_SPECS:
        raise ValueError("Only Connecticut Practice Book Forms 202, 205 and 207 are supported.")
    path = Path(pdf_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = FORM_SPECS[form_id]
    first, last = spec["pages"]
    return FormTemplate(
        form_id=form_id,
        title=str(spec["title"]),
        court=str(spec["court"]),
        response_party=str(spec["response_party"]),
        deadline_text=str(spec["deadline_text"]),
        items=_extract_questions(path, form_id),
        source_sha256=digest,
        source_pages=f"PDF pages {first}-{last}",
    )


def _template_from_dict(value: dict) -> FormTemplate:
    return FormTemplate(
        form_id=value["form_id"],
        title=value["title"],
        court=value["court"],
        response_party=value["response_party"],
        deadline_text=value["deadline_text"],
        items=tuple(FormItem(**item) for item in value["items"]),
        source_sha256=value["source_sha256"],
        source_pages=value["source_pages"],
    )


def load_forms(pdf_path: str, cache_path: str | None = None) -> dict[str, FormTemplate]:
    path = Path(pdf_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = Path(cache_path) if cache_path else None
    if cache and cache.is_file():
        try:
            value = json.loads(cache.read_text(encoding="utf-8"))
            if value.get("schema") == 1 and value.get("source_sha256") == digest and set(value.get("forms", {})) == {"202", "207"}:
                return {form_id: _template_from_dict(form) for form_id, form in value["forms"].items()}
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass

    forms = {form_id: load_form(str(path), form_id) for form_id in ("202", "207")}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "schema": 1,
            "source_sha256": digest,
            "forms": {form_id: form.to_dict() for form_id, form in forms.items()},
        }, ensure_ascii=False)
        descriptor, temporary = tempfile.mkstemp(prefix="forms-", suffix=".json", dir=cache.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, cache)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return forms
