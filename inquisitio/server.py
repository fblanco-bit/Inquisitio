from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__
from .case_record import apply_case_record, metadata_from_case_record, validate_case_record_bytes
from .evidence import EvidenceSegment, extract_pdf
from .engine import ENGINE_STATUSES, _same_person, answer_fingerprint, build_response, extract_facts, infer_metadata
from .exporter import export_case, export_case_pdf, export_traceability
from .forms import load_forms, load_form
from .storage import CaseStore
from .production import build_production_review, PRODUCTION_STATUSES


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
WEB_ROOT = ROOT / "web"
PRACTICE_BOOK = ROOT / "assets" / "CT_Practice_Book_2026.pdf"


def default_data_root() -> Path:
    configured = os.environ.get("INQUISITIO_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Inquisitio" / "cases"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Inquisitio" / "cases"
    return Path.home() / ".local" / "share" / "Inquisitio" / "cases"


DATA_ROOT = default_data_root()
STORE = CaseStore(DATA_ROOT)
FORM_CACHE = DATA_ROOT.parent / "forms_cache.json"
PACKAGED_FORM_CACHE = ROOT / "data" / "forms_cache.json"
if not FORM_CACHE.exists() and PACKAGED_FORM_CACHE.is_file():
    FORM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PACKAGED_FORM_CACHE, FORM_CACHE)
    os.chmod(FORM_CACHE, 0o600)
FORMS = load_forms(str(PRACTICE_BOOK), str(FORM_CACHE))
PRODUCTION_FORM = load_form(str(PRACTICE_BOOK), "205")
MAX_UPLOAD = 250_000_000
CASE_PATH = re.compile(r"^/api/cases/([a-f0-9]{32})(?:/(answers|export|pdf|traceability|evidence))?$")
METADATA_FIELDS = {
    "court", "docket_number", "response_date", "plaintiff", "defendant",
    "judicial_district", "responding_party_role", "interrogating_party", "incident_date",
}
CASE_WRITE_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, dict]]:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Evidence intake requires multipart form data.")
    envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    message = BytesParser(policy=policy.default).parsebytes(envelope)
    if not message.is_multipart():
        raise ValueError("The upload could not be parsed.")
    values: list[tuple[str, dict]] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        values.append((str(name), {
            "filename": part.get_filename(),
            "data": part.get_payload(decode=True) or b"",
        }))
    return values


def _field(parts: list[tuple[str, dict]], name: str, default: str = "") -> str:
    for field_name, item in parts:
        if field_name == name and item.get("filename") is None:
            return bytes(item["data"]).decode("utf-8", errors="strict")
    return default


def _safe_filename(value: str) -> str:
    name = Path(value).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "evidence.pdf"


def _public_case(record: dict) -> dict:
    value = json.loads(json.dumps(record))
    value.pop("facts", None)
    legacy_statuses = {
        "DRAFTED_FROM_EVIDENCE": "DRAFT", "SUPPORTED_DRAFT": "DRAFT",
        "PARTIAL_DRAFT": "DRAFT", "NOT_APPLICABLE": "DRAFT",
        "CLIENT_CONFIRMATION_REQUIRED": "REQUIRES_CLIENT", "CLIENT_CONFIRMATION": "REQUIRES_CLIENT",
        "EVIDENCE_CONFLICT": "POTENTIAL_CONFLICT", "REVIEW_REQUIRED": "EMPTY",
        "ATTORNEY_REVIEW": "EMPTY", "NO_RESPONSIVE_EVIDENCE": "EMPTY",
    }
    counts: dict[str, int] = {}
    approved = 0
    for answer in value.get("answers", {}).values():
        raw_status = answer.get("status") or answer.get("engine_status") or "EMPTY"
        if raw_status == "COMPLETE":
            status = "APPROVED" if str(answer.get("answer", "")).strip() else "EMPTY"
        else:
            status = raw_status if raw_status in ENGINE_STATUSES else legacy_statuses.get(raw_status, "EMPTY")
        if answer.get("workflow_status") == "APPROVED" and str(answer.get("answer", "")).strip():
            status = "APPROVED"
        answer["engine_status"] = status
        answer["status"] = status
        answer.pop("workflow_status", None)
        answer.setdefault("evidence_outcome", raw_status if raw_status not in ENGINE_STATUSES else "")
        answer.setdefault("reason_code", "NOT_IN_EVIDENCE" if status == "EMPTY" else "")
        answer.setdefault("generated_answer", "")
        answer.setdefault("supporting_citations", [])
        answer.setdefault("candidate_passages", list(answer.get("evidence", [])))
        answer.setdefault("missing_information", [])
        answer.setdefault("required_follow_up", "Attorney review required for this legacy response.")
        answer.setdefault("conflicts", [])
        answer.setdefault("edit_history", [])
        answer.setdefault("requires_revalidation", bool(answer.get("answer")))
        answer.setdefault("approval", None)
        counts[status] = counts.get(status, 0) + 1
        approved += status == "APPROVED"
    if "summary" in value:
        value["summary"]["status_counts"] = counts
        value["summary"]["approved"] = approved
    return value


def _document_summary(document, uploaded_at: str, party_names: list[str] | None = None, identity_status: str = "IDENTITY_NOT_FOUND") -> dict:
    return {
        "source_id": document.source_id,
        "filename": document.filename,
        "sha256": document.sha256,
        "pages": document.pages,
        "extraction_status": document.extraction_status,
        "segment_count": len(document.segments),
        "extraction_errors": list(document.extraction_errors),
        "page_methods": list(document.page_methods),
        "uploaded_at": uploaded_at,
        "party_names": party_names or [],
        "identity_status": identity_status,
    }


def _build_workspace(record: dict, documents: list, segments: list[EvidenceSegment], previous: dict | None = None) -> None:
    old_documents = {item.get("sha256"): item for item in (previous or {}).get("documents", [])}
    provisional = [
        _document_summary(document, old_documents.get(document.sha256, {}).get("uploaded_at", utc_now()))
        for document in documents
    ]
    record["metadata"] = infer_metadata(segments, record["metadata"], record["form_id"])
    facts = extract_facts(segments, record["metadata"], provisional, FORMS[record["form_id"]].items)
    respondent = str(record["metadata"].get(record["metadata"].get("responding_party_role", ""), "")).strip()
    names_by_source: dict[str, list[str]] = {}
    for fact in facts:
        if fact.attribute == "full_name" and fact.value not in names_by_source.setdefault(fact.source_id, []):
            names_by_source[fact.source_id].append(fact.value)
    summaries = []
    packet_has_match = False
    packet_has_identity = False
    for document, summary in zip(documents, provisional):
        names = names_by_source.get(document.source_id, [])
        matched = bool(respondent and any(_same_person(name, respondent) for name in names))
        packet_has_match = packet_has_match or matched
        packet_has_identity = packet_has_identity or bool(names)
        identity_status = "MATCHED_RESPONDING_PARTY" if matched else "NO_RESPONDING_PARTY_MATCH" if names else "IDENTITY_NOT_FOUND"
        summaries.append(_document_summary(document, summary["uploaded_at"], names, identity_status))
    blocked = bool(respondent and packet_has_identity and not packet_has_match)
    record["matter_integrity"] = {
        "status": "BLOCKED" if blocked else "PASS" if packet_has_match else "WARNING",
        "responding_party": respondent,
        "packet_identity_found": packet_has_identity,
        "message": (
            "Uploaded evidence identifies other people but does not identify the responding party. Automatic drafting is blocked."
            if blocked else "Responding party identity matched in the uploaded evidence."
            if packet_has_match else "No affirmative party identity was found; review the packet before approval."
        ),
    }
    status_counts: dict[str, int] = {}
    answers: dict[str, dict] = {}
    old_answers = (previous or {}).get("answers", {})
    for item in FORMS[record["form_id"]].items:
        answer = build_response(item, segments, facts, record["metadata"], summaries)
        old = old_answers.get(item.item_id, {})
        prior_text = str(old.get("answer", ""))
        prior_generated = str(old.get("generated_answer", ""))
        if prior_text and prior_text != prior_generated and answer["status"] == "POTENTIAL_CONFLICT":
            answer["edit_history"] = list(old.get("edit_history", [])) + [{
                "previous_answer": prior_text,
                "reason": "Conflicting evidence; prior manual text retained in history, response left blank.",
            }]
        elif prior_text and prior_text != prior_generated:
            answer["answer"] = prior_text
            answer["edit_history"] = list(old.get("edit_history", []))
            answer["requires_revalidation"] = True
            answer["required_follow_up"] = "Revalidate the attorney-edited response against the newly processed evidence."
            answer["status"] = "EDITED"
            answer["engine_status"] = "EDITED"
        answer["approval"] = None
        answers[item.item_id] = answer
    apply_case_record(record, answers)
    if blocked:
        for answer in answers.values():
            answer["candidate_passages"] = answer.get("supporting_citations", []) or answer.get("candidate_passages", [])
            answer["answer"] = ""
            answer["generated_answer"] = ""
            answer["status"] = "REQUIRES_CLIENT"
            answer["engine_status"] = "REQUIRES_CLIENT"
            answer["evidence_outcome"] = "MATTER_IDENTITY_BLOCK"
            answer["reason_code"] = "MATERIAL_IDENTITY_CONTRADICTION"
            answer["required_follow_up"] = record["matter_integrity"]["message"]
    for answer in answers.values():
        status_counts[answer["status"]] = status_counts.get(answer["status"], 0) + 1
    if record["form_id"] == "202":
        record["production"] = build_production_review(
            PRODUCTION_FORM.items, documents, (previous or {}).get("production")
        )
    record["documents"] = summaries
    record["facts"] = [fact.to_dict() for fact in facts]
    record["answers"] = answers
    record["summary"] = {
        "documents": len(documents),
        "pages": sum(document.pages for document in documents),
        "segments": len(segments),
        "facts": len(facts),
        "items": len(FORMS[record["form_id"]].items),
        "status_counts": status_counts,
        "approved": 0,
        "ocr_required": [document.source_id for document in documents if document.extraction_status == "NO_TEXT_OCR_REQUIRED"],
    }


def _ensure_production(case_id: str, record: dict) -> dict:
    """Upgrade an existing Form 202 matter without altering its Form 202 answers."""
    if record.get("form_id") != "202" or "production" in record:
        return record
    with CASE_WRITE_LOCK:
        record = STORE.load(case_id)
        if "production" in record:
            return record
        documents = []
        try:
            evidence_paths = sorted((STORE.case_dir(case_id) / "evidence").glob("*.pdf"))
            for i, evidence_path in enumerate(evidence_paths, 1):
                name = re.sub(r"^\d{3}_", "", evidence_path.name)
                documents.append(extract_pdf(evidence_path, f"E-{i:03d}", name))
        except Exception:
            # An old case with unreadable source evidence still opens. It must
            # be reprocessed before 205 search-lead matching can be relied on.
            documents = []
        record["production"] = build_production_review(PRODUCTION_FORM.items, documents)
        if not documents:
            for item in record["production"].values():
                item["review_warning"] = "Legacy case evidence could not be reindexed; upload and reprocess the PDFs before review."
        record["revision"] = int(record.get("revision", 1)) + 1
        record["updated_at"] = utc_now()
        STORE.save(case_id, record)
        return record


class InquisitioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    server_version = f"Inquisitio/{__version__}"

    def log_message(self, format: str, *args: object) -> None:
        # Log request metadata only. Evidence and response text never enter logs.
        sys.stderr.write(f"INQUISITIO {self.address_string()} {format % args}\n")

    def _send(self, status: int, content_type: str, body: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: object) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode())

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length <= 0 or length > MAX_UPLOAD:
            raise ValueError("Upload must be between 1 byte and 250 MB.")
        return self.rfile.read(length)

    def _request_is_local(self) -> bool:
        host = self.headers.get("Host", "")
        try:
            parsed = urlparse(f"//{host}")
            expected_port = self.server.server_address[1]
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
            if parsed.port is not None and parsed.port != expected_port:
                return False
            origin = self.headers.get("Origin")
            if origin:
                source = urlparse(origin)
                if source.scheme not in {"http", "https"} or source.hostname not in {"127.0.0.1", "localhost", "::1"}:
                    return False
                if source.port is not None and source.port != expected_port:
                    return False
            return True
        except ValueError:
            return False

    def _authorize_request(self) -> bool:
        if self._request_is_local():
            return True
        self._json(421, {"error": "Request host or origin is not permitted."})
        return False

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"/", "/index.html"} else unquote(path.lstrip("/"))
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents or not candidate.is_file():
            self._json(404, {"error": "Not found."})
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._send(200, content_type, candidate.read_bytes())

    def do_GET(self) -> None:
        if not self._authorize_request():
            return
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, {"status": "ok", "service": "Inquisitio", "version": __version__, "forms": ["202", "205", "207"], "production_paired_with": "202"})
            return
        if path == "/api/forms":
            self._json(200, {"forms": [{
                "form_id": form.form_id,
                "title": form.title,
                "court": form.court,
                "item_count": len(form.items),
                "question_count": len({item.number for item in form.items}),
                "source_pages": form.source_pages,
                "source_sha256": form.source_sha256,
            } for form in (*FORMS.values(), PRODUCTION_FORM)], "production_paired_with": "202"})
            return
        if path == "/api/cases":
            self._json(200, {"cases": STORE.list()})
            return
        match = CASE_PATH.fullmatch(path)
        if match:
            case_id, action = match.groups()
            try:
                record = STORE.load(case_id)
                record = _ensure_production(case_id, record)
            except FileNotFoundError:
                self._json(404, {"error": "Case not found."})
                return
            if action == "export":
                try:
                    body = export_case(record)
                    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(record.get("case_name", "case"))).strip("_") or "case"
                    self._send(200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", body, {
                        "Content-Disposition": f'attachment; filename="{name}_Form_{record["form_id"]}_responses.docx"'
                    })
                except Exception:
                    self._json(500, {"error": "The Word draft could not be generated. Review the matter data and try again."})
            elif action == "pdf":
                try:
                    body = export_case_pdf(record)
                    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(record.get("case_name", "case"))).strip("_") or "case"
                    self._send(200, "application/pdf", body, {
                        "Content-Disposition": f'attachment; filename="{name}_Form_{record["form_id"]}_responses.pdf"'
                    })
                except Exception:
                    self._json(500, {"error": "The completed-form PDF could not be generated."})
            elif action == "traceability":
                try:
                    body = export_traceability(record)
                    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(record.get("case_name", "case"))).strip("_") or "case"
                    self._send(200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", body, {
                        "Content-Disposition": f'attachment; filename="{name}_evidence_traceability.docx"'
                    })
                except Exception:
                    self._json(500, {"error": "The evidence report could not be generated."})
            elif action:
                self._json(404, {"error": "Not found."})
            else:
                self._json(200, _public_case(record))
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "API endpoint not found."})
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        if not self._authorize_request():
            return
        path = urlparse(self.path).path
        match = CASE_PATH.fullmatch(path)
        if path != "/api/cases" and (not match or match.group(2) != "evidence"):
            self._json(404, {"error": "API endpoint not found."})
            return
        if match and match.group(2) == "evidence":
            self._append_evidence(match.group(1))
            return
        case_id: str | None = None
        try:
            body = self._read_body()
            parts = parse_multipart(self.headers.get("Content-Type", ""), body)
            form_id = _field(parts, "form_id")
            case_name = _field(parts, "case_name").strip()
            if form_id not in FORMS:
                raise ValueError("Select Form 202 or Form 207.")
            if not case_name or len(case_name) > 160:
                raise ValueError("Case name is required and must be 160 characters or fewer.")
            try:
                metadata = json.loads(_field(parts, "metadata", "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError("Case metadata is not valid JSON.") from exc
            if not isinstance(metadata, dict):
                raise ValueError("Case metadata must be a JSON object.")
            if set(metadata) - METADATA_FIELDS:
                raise ValueError("Case metadata contains unsupported fields.")
            if any(not isinstance(value, str) or len(value) > 500 for value in metadata.values()):
                raise ValueError("Case metadata values must be strings of 500 characters or fewer.")
            role = str(metadata.get("responding_party_role", "")).lower()
            if role and role not in {"plaintiff", "defendant"}:
                raise ValueError("Responding party must be plaintiff or defendant.")
            if form_id == "202" and role != "plaintiff":
                if role:
                    raise ValueError("Form 202 is the defendant's interrogatories to the plaintiff; confirm the plaintiff as responding party.")
            uploads = [item for name, item in parts if name == "evidence" and item.get("filename")]
            if not uploads:
                raise ValueError("Upload at least one evidence PDF.")
            if len(uploads) > 50:
                raise ValueError("Upload no more than 50 PDFs in one case.")
            filenames = [_safe_filename(str(upload["filename"])) for upload in uploads]
            invalid = next((name for name in filenames if Path(name).suffix.lower() != ".pdf"), None)
            if invalid:
                raise ValueError(f"{invalid} is not a PDF.")
            record_uploads = [item for name, item in parts if name == "case_record" and item.get("filename")]
            other_uploads = [item for name, item in parts if item.get("filename") and name not in {"evidence", "case_record"}]
            if other_uploads:
                raise ValueError("Only evidence PDFs and one case_record.json file are accepted.")
            if len(record_uploads) > 1:
                raise ValueError("Upload no more than one case_record.json file.")
            case_record = None
            case_record_sha256 = ""
            if record_uploads:
                record_name = _safe_filename(str(record_uploads[0]["filename"]))
                if record_name != "case_record.json":
                    raise ValueError("The optional case record file must be named case_record.json.")
                case_record, case_record_sha256 = validate_case_record_bytes(bytes(record_uploads[0]["data"]))
                for key, value in metadata_from_case_record(case_record).items():
                    if value and not str(metadata.get(key, "")).strip():
                        metadata[key] = value
            if role and not str(metadata.get(role, "")).strip():
                raise ValueError("Enter the responding party's name or provide it in case_record.json before building the workspace.")

            case_id = STORE.new_id()
            form = FORMS[form_id]
            record = {
                "case_id": case_id,
                "case_name": case_name,
                "form_id": form_id,
                "schema_version": 3,
                "revision": 1,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "metadata": metadata,
                "form": form.to_dict(),
                "documents": [],
                "answers": {},
                "summary": {},
                "case_record": case_record,
                "case_record_sha256": case_record_sha256,
            }
            STORE.create(case_id, record)
            if case_record is not None:
                case_record_path = STORE.case_dir(case_id) / "case_record.json"
                case_record_path.write_bytes(bytes(record_uploads[0]["data"]))
                os.chmod(case_record_path, 0o600)
            directory = STORE.case_dir(case_id) / "evidence"
            documents = []
            segments: list[EvidenceSegment] = []
            for index, (upload, filename) in enumerate(zip(uploads, filenames), start=1):
                stored_name = f"{index:03d}_{filename}"
                path_on_disk = directory / stored_name
                path_on_disk.write_bytes(bytes(upload["data"]))
                os.chmod(path_on_disk, 0o600)
                try:
                    document = extract_pdf(path_on_disk, f"E-{index:03d}", filename)
                except Exception as exc:
                    raise ValueError(f"{filename} could not be read as a PDF.") from exc
                documents.append(document)
                segments.extend(document.segments)

            _build_workspace(record, documents, segments)
            record["updated_at"] = utc_now()
            STORE.save(case_id, record)
            self._json(201, _public_case(record))
        except ValueError as exc:
            if case_id:
                try:
                    STORE.delete(case_id)
                except (FileNotFoundError, OSError):
                    pass
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            if case_id:
                try:
                    STORE.delete(case_id)
                except (FileNotFoundError, OSError):
                    pass
            self._json(500, {"error": "Evidence processing failed.", "detail": type(exc).__name__})

    def _append_evidence(self, case_id: str) -> None:
        stage_directory: Path | None = None
        backup_directory: Path | None = None
        try:
            record = STORE.load(case_id)
            body = self._read_body()
            parts = parse_multipart(self.headers.get("Content-Type", ""), body)
            uploads = [item for name, item in parts if name == "evidence" and item.get("filename")]
            if not uploads:
                raise ValueError("Upload at least one evidence PDF.")
            mode = _field(parts, "mode", "append")
            if mode not in {"append", "replace"}:
                raise ValueError("Evidence update mode must be append or replace.")
            try:
                expected_revision = int(_field(parts, "revision"))
            except ValueError as exc:
                raise ValueError("A matter revision is required before reprocessing evidence.") from exc
            current_revision = int(record.get("revision", 1))
            if expected_revision != current_revision:
                self._json(409, {
                    "error": "This matter changed in another browser tab. Reload before reprocessing evidence.",
                    "current_revision": current_revision,
                })
                return
            evidence_directory = STORE.case_dir(case_id) / "evidence"
            stage_directory = STORE.case_dir(case_id) / f".evidence-stage-{STORE.new_id()}"
            stage_directory.mkdir(mode=0o700)
            existing = sorted(evidence_directory.glob("*.pdf")) if mode == "append" else []
            next_index = len(existing) + 1
            if mode == "append":
                for path in existing:
                    staged_copy = stage_directory / path.name
                    shutil.copyfile(path, staged_copy)
                    os.chmod(staged_copy, 0o600)
            for offset, upload in enumerate(uploads):
                filename = _safe_filename(str(upload["filename"]))
                if Path(filename).suffix.lower() != ".pdf":
                    raise ValueError(f"{filename} is not a PDF.")
                staged_path = stage_directory / f"{next_index + offset:03d}_{filename}"
                staged_path.write_bytes(bytes(upload["data"]))
                os.chmod(staged_path, 0o600)
                try:
                    extract_pdf(staged_path, "VALIDATE", filename)
                except Exception as exc:
                    raise ValueError(f"{filename} could not be read as a PDF.") from exc
            documents = []
            segments: list[EvidenceSegment] = []
            for index, path_on_disk in enumerate(sorted(stage_directory.glob("*.pdf")), start=1):
                display_name = re.sub(r"^\d{3}_", "", path_on_disk.name)
                document = extract_pdf(path_on_disk, f"E-{index:03d}", display_name)
                documents.append(document)
                segments.extend(document.segments)
            previous = json.loads(json.dumps(record))
            candidate = json.loads(json.dumps(record))
            _build_workspace(candidate, documents, segments, previous if mode == "append" else None)
            candidate["revision"] = current_revision + 1
            candidate["updated_at"] = utc_now()
            with CASE_WRITE_LOCK:
                latest = STORE.load(case_id)
                if int(latest.get("revision", 1)) != current_revision:
                    self._json(409, {
                        "error": "This matter changed while evidence was processing. Reload and try again.",
                        "current_revision": int(latest.get("revision", 1)),
                    })
                    return
                backup_directory = STORE.case_dir(case_id) / f".evidence-backup-{STORE.new_id()}"
                os.replace(evidence_directory, backup_directory)
                os.replace(stage_directory, evidence_directory)
                stage_directory = None
                try:
                    STORE.save(case_id, candidate)
                except Exception:
                    os.replace(evidence_directory, stage_directory := STORE.case_dir(case_id) / f".evidence-failed-{STORE.new_id()}")
                    os.replace(backup_directory, evidence_directory)
                    backup_directory = None
                    raise
            if backup_directory:
                shutil.rmtree(backup_directory)
                backup_directory = None
            record = candidate
            self._json(200, _public_case(record))
        except FileNotFoundError:
            self._json(404, {"error": "Case not found."})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": "Evidence reprocessing failed.", "detail": type(exc).__name__})
        finally:
            for directory in (stage_directory, backup_directory):
                if directory and directory.exists():
                    shutil.rmtree(directory, ignore_errors=True)

    def do_PUT(self) -> None:
        if not self._authorize_request():
            return
        path = urlparse(self.path).path
        match = CASE_PATH.fullmatch(path)
        if not match or match.group(2) != "answers":
            self._json(404, {"error": "API endpoint not found."})
            return
        case_id = match.group(1)
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
            updates = payload.get("answers")
            if not isinstance(updates, dict):
                raise ValueError("answers must be an object.")
            with CASE_WRITE_LOCK:
                record = STORE.load(case_id)
                expected_revision = payload.get("revision")
                if not isinstance(expected_revision, int):
                    self._json(428, {"error": "A matter revision is required before saving."})
                    return
                current_revision = int(record.get("revision", 1))
                if expected_revision != current_revision:
                    self._json(409, {
                        "error": "This matter changed in another browser tab. Reload before saving.",
                        "current_revision": current_revision,
                    })
                    return
                allowed = set(record["answers"])
                for item_id, update in updates.items():
                    if item_id not in allowed or not isinstance(update, dict):
                        raise ValueError(f"Unknown answer item: {item_id}")
                    current = record["answers"][item_id]
                    answer_text = str(update.get("answer", current.get("answer", "")))
                    requested_status = str(update.get("status", current.get("status", "EMPTY")))
                    if requested_status == "COMPLETE":
                        requested_status = "APPROVED" if answer_text.strip() else "EMPTY"
                    if len(answer_text) > 50_000:
                        raise ValueError(f"Answer {item_id} exceeds 50,000 characters.")
                    if requested_status not in ENGINE_STATUSES:
                        raise ValueError(f"Invalid workflow status for {item_id}.")
                    previous_text = str(current.get("answer", ""))
                    if answer_text != previous_text:
                        current.setdefault("edit_history", []).append({
                            "edited_at": utc_now(), "previous_answer": previous_text, "new_answer": answer_text,
                        })
                        current["answer"] = answer_text
                        current["requires_revalidation"] = answer_text != str(current.get("generated_answer", ""))
                        current["approval"] = None
                        requested_status = "EDITED"
                    if update.get("revalidated") is True:
                        current["requires_revalidation"] = False
                        current.setdefault("edit_history", []).append({"revalidated_at": utc_now()})
                    if requested_status == "APPROVED":
                        if current.get("status") in {"POTENTIAL_CONFLICT", "REQUIRES_CLIENT", "EMPTY"}:
                            raise ValueError(f"Resolve the engine finding before approving {item_id}.")
                        if not str(current.get("answer", "")).strip():
                            raise ValueError(f"A response is required before approving {item_id}.")
                        if current.get("requires_revalidation"):
                            raise ValueError(f"Revalidate the edited response before approving {item_id}.")
                        current["approval"] = {"approved_at": utc_now(), "content_sha256": answer_fingerprint(current)}
                    else:
                        current["approval"] = None
                    current["status"] = requested_status
                    current["engine_status"] = requested_status
                production_updates = payload.get("production", {})
                if not isinstance(production_updates, dict):
                    raise ValueError("Production updates must be an object.")
                if production_updates and record.get("form_id") != "202":
                    raise ValueError("Form 205 review applies only to Form 202 cases.")
                known_documents = {doc["source_id"] for doc in record.get("documents", [])}
                for item_id, update in production_updates.items():
                    if item_id not in record.get("production", {}) or not isinstance(update, dict):
                        raise ValueError(f"Unknown production request: {item_id}")
                    current = record["production"][item_id]
                    status = str(update.get("status", current["status"]))
                    if status not in PRODUCTION_STATUSES:
                        raise ValueError(f"Invalid production status for {item_id}.")
                    response_text = update.get("response", current.get("response", ""))
                    notes = update.get("reviewer_notes", current.get("reviewer_notes", ""))
                    bates = update.get("bates_range", current.get("bates_range", ""))
                    selected = update.get("selected_sources", current.get("selected_sources", []))
                    if not all(isinstance(v, str) for v in (response_text, notes, bates)):
                        raise ValueError("Production text fields must contain strings.")
                    if len(response_text) > 50000 or len(notes) > 10000 or len(bates) > 300:
                        raise ValueError("Production response field exceeds its length limit.")
                    if not isinstance(selected, list) or len(selected) != len(set(selected)) or any(
                            not isinstance(source, str) or source not in known_documents for source in selected):
                        raise ValueError("Production selections must reference uploaded evidence files.")
                    if status == "PRODUCED_CONFIRMED" and (not response_text.strip() or not bates.strip() or not selected):
                        raise ValueError("Confirm a written response, selected uploaded documents and Bates range before marking produced.")
                    if status == "NO_RESPONSIVE_CONFIRMED" and (not response_text.strip() or selected):
                        raise ValueError("A reviewer explanation and no selected documents are required to confirm no responsive records.")
                    current.update({"status": status, "response": response_text,
                                    "reviewer_notes": notes, "bates_range": bates,
                                    "selected_sources": selected, "review_reset": False})
                counts: dict[str, int] = {}
                for answer in record["answers"].values():
                    status = answer.get("status", "EMPTY")
                    if status not in ENGINE_STATUSES:
                        status = "EMPTY"
                    counts[status] = counts.get(status, 0) + 1
                record["summary"]["status_counts"] = counts
                record["summary"]["approved"] = sum(answer.get("status") == "APPROVED" for answer in record["answers"].values())
                record["revision"] = current_revision + 1
                record["updated_at"] = utc_now()
                STORE.save(case_id, record)
            self._json(200, _public_case(record))
        except FileNotFoundError:
            self._json(404, {"error": "Case not found."})
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})

    def do_DELETE(self) -> None:
        if not self._authorize_request():
            return
        path = urlparse(self.path).path
        match = CASE_PATH.fullmatch(path)
        if not match or match.group(2):
            self._json(404, {"error": "API endpoint not found."})
            return
        try:
            STORE.delete(match.group(1))
            self._json(200, {"deleted": True})
        except FileNotFoundError:
            self._json(404, {"error": "Case not found."})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Inquisitio workspace.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Inquisitio binds to loopback only.")
    try:
        server = InquisitioServer((args.host, args.port), Handler)
    except OSError as exc:
        parser.error(f"Port {args.port} is unavailable: {exc}")
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(f"Inquisitio {__version__} running at {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
