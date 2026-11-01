from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from io import BytesIO
from unittest.mock import patch

from reportlab.pdfgen import canvas

import inquisitio.server as server_module
from inquisitio.server import Handler, InquisitioServer, default_data_root
from inquisitio.storage import CaseStore


class ServerSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_store = server_module.STORE
        server_module.STORE = CaseStore(Path(self.temporary.name) / "cases")
        self.server = InquisitioServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        server_module.STORE = self.original_store
        self.temporary.cleanup()

    def request(self, method: str, path: str, host: str | None = None) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest(method, path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        connection.endheaders()
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def post_case(self, metadata: str = "{}", filename: str = "evidence.pdf", data: bytes = b"bad", form_id: str = "202", case_record: tuple[str, bytes] | None = None) -> tuple[int, dict]:
        boundary = "INQUISITIO-TEST-BOUNDARY"
        parts = []
        for name, value in (("form_id", form_id), ("case_name", "Test Matter"), ("metadata", metadata)):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"evidence\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/pdf\r\n\r\n".encode() + data + b"\r\n"
        )
        if case_record:
            record_name, record_data = case_record
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"case_record\"; filename=\"{record_name}\"\r\n"
                "Content-Type: application/json\r\n\r\n".encode() + record_data + b"\r\n"
            )
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/api/cases", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        })
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def put_answers(self, case_id: str, answers: dict, revision: int) -> tuple[int, dict]:
        body = json.dumps({"answers": answers, "revision": revision}).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("PUT", f"/api/cases/{case_id}/answers", body=body, headers={
            "Content-Type": "application/json", "Content-Length": str(len(body)),
        })
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def append_evidence(self, case_id: str, filename: str, data: bytes, revision: int, mode: str = "append") -> tuple[int, dict]:
        boundary = "INQUISITIO-APPEND-BOUNDARY"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\n{mode}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"revision\"\r\n\r\n{revision}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"evidence\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", f"/api/cases/{case_id}/evidence", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body)),
        })
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def test_foreign_host_is_rejected(self) -> None:
        status, body = self.request("GET", "/api/cases", "evil.example.com")
        self.assertEqual(status, 421)
        self.assertIn("not permitted", body["error"])

    def test_delete_removes_case_and_returns_json(self) -> None:
        case_id = server_module.STORE.new_id()
        server_module.STORE.create(case_id, {"case_id": case_id, "case_name": "Delete", "form_id": "202"})
        status, body = self.request("DELETE", f"/api/cases/{case_id}")
        self.assertEqual((status, body), (200, {"deleted": True}))
        self.assertFalse(server_module.STORE.case_dir(case_id).exists())

    def test_rejected_uploads_leave_no_case_directory(self) -> None:
        for metadata, filename, data in (("{}", "notes.txt", b"text"), ("[]", "notes.pdf", b"bad"), ("{}", "notes.pdf", b"bad")):
            status, _ = self.post_case(metadata, filename, data)
            self.assertEqual(status, 400)
            self.assertEqual(server_module.STORE.list(), [])

    def test_valid_upload_is_private_and_only_suggests_evidence(self) -> None:
        stream = BytesIO()
        pdf = canvas.Canvas(stream)
        pdf.drawString(72, 720, "The patient was diagnosed with a cervical strain.")
        pdf.save()
        status, record = self.post_case(data=stream.getvalue())
        self.assertEqual(status, 201)
        self.assertEqual(record["answers"]["202-2"]["answer"], "")
        self.assertTrue(record["answers"]["202-2"]["evidence"])
        evidence = next((server_module.STORE.case_dir(record["case_id"]) / "evidence").iterdir())
        self.assertEqual(os.stat(evidence).st_mode & 0o777, 0o600)

    def _pdf(self, line: str = "") -> bytes:
        stream = BytesIO()
        pdf = canvas.Canvas(stream)
        if line:
            pdf.drawString(72, 720, line)
        pdf.save()
        return stream.getvalue()

    def _metadata(self) -> str:
        return json.dumps({
            "court": "Superior Court", "docket_number": "FA-26-1", "response_date": "2026-10-18",
            "plaintiff": "Jordan Moss", "defendant": "Casey Bright", "judicial_district": "Hartford",
            "responding_party_role": "plaintiff", "interrogating_party": "Casey Bright",
        })

    def _case_record(self) -> bytes:
        return json.dumps({
            "matter": {"caption": "Moss v. Bright", "docket": "FA-26-1", "court": "Superior Court", "incident_date": "2026-01-09"},
            "client": {"name": "Jordan Moss", "other_names": [], "birthDate": "03/15/1987", "address1": "24 Cedar Lane", "business_address": "", "driversLicenseNumber": "CT 123-456"},
            "vehicle": {"client_was_owner": True, "owner_name": "", "owner_address": ""},
            "employment": {"employer_name": "Harbor Machine", "employer_address": "180 Quarry Road", "jobTitle": "machinist", "duties": "operate milling equipment", "pay_rate": "$30 per hour", "lostWagesStart": "2026-01-10", "lostWagesEnd": "2026-02-01"},
            "counsel": {"name": "Dana Lee", "juris_no": "123456", "firm": "Lee Law", "address": "1 Main Street"},
        }).encode()

    def test_case_record_drafts_are_field_cited_and_empty_values_are_unknown(self) -> None:
        status, record = self.post_case(
            self._metadata(), "evidence.pdf", self._pdf(), "202", ("case_record.json", self._case_record()),
        )
        self.assertEqual(status, 201)
        dob = record["answers"]["202-1-b"]
        self.assertEqual((dob["status"], dob["answer"]), ("DRAFT", "Date of birth: 03/15/1987."))
        self.assertEqual(dob["supporting_citations"][0]["citation_label"], "[Case record: client.birthDate]")
        self.assertEqual(record["answers"]["202-1-e"]["status"], "EMPTY")
        self.assertEqual(record["answers"]["202-1-e"]["reason_code"], "NOT_IN_EVIDENCE")

    def test_invalid_case_record_reports_field_path_and_creates_no_matter(self) -> None:
        invalid = json.loads(self._case_record())
        invalid["client"]["birthDate"] = 123
        status, result = self.post_case(
            self._metadata(), "evidence.pdf", self._pdf(), "202",
            ("case_record.json", json.dumps(invalid).encode()),
        )
        self.assertEqual(status, 400)
        self.assertIn("client.birthDate", result["error"])
        self.assertEqual(server_module.STORE.list(), [])

    def test_material_identity_mismatch_blocks_all_automatic_drafts(self) -> None:
        status, record = self.post_case(
            self._metadata(), "other_patient.pdf", self._pdf("Patient: Elena Vega    DOB: 03/15/1987"), "202",
        )
        self.assertEqual(status, 201)
        self.assertEqual(record["matter_integrity"]["status"], "BLOCKED")
        self.assertTrue(all(answer["status"] == "REQUIRES_CLIENT" and not answer["answer"] for answer in record["answers"].values()))

    def test_supported_draft_requires_explicit_approval_and_edits_invalidate_it(self) -> None:
        status, record = self.post_case(
            self._metadata(), "payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,450.00 per week."), "207",
        )
        self.assertEqual(status, 201)
        answer = record["answers"]["207-3-c"]
        self.assertEqual(answer["status"], "DRAFT")

        status, approved = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": answer["answer"], "status": "APPROVED"},
        }, record["revision"])
        self.assertEqual(status, 200)
        self.assertIsNotNone(approved["answers"]["207-3-c"]["approval"])

        edited_text = answer["answer"] + " Subject to final payroll verification."
        status, edited = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": edited_text, "status": "APPROVED"},
        }, approved["revision"])
        self.assertEqual(status, 200)
        edited_answer = edited["answers"]["207-3-c"]
        self.assertEqual(edited_answer["status"], "EDITED")
        self.assertTrue(edited_answer["requires_revalidation"])
        self.assertIsNone(edited_answer["approval"])
        self.assertTrue(edited_answer["edit_history"])

        status, reapproved = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": edited_text, "status": "APPROVED", "revalidated": True},
        }, edited["revision"])
        self.assertEqual(status, 200)
        self.assertEqual(reapproved["answers"]["207-3-c"]["status"], "APPROVED")

    def test_reprocessing_new_conflicting_evidence_clears_approval(self) -> None:
        status, record = self.post_case(
            self._metadata(), "payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,450.00 per week."), "207",
        )
        answer = record["answers"]["207-3-c"]
        _, record = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": answer["answer"], "status": "APPROVED"},
        }, record["revision"])
        status, record = self.append_evidence(
            record["case_id"], "second_payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,525.00 per week."), record["revision"],
        )
        self.assertEqual(status, 200)
        result = record["answers"]["207-3-c"]
        self.assertEqual(result["status"], "POTENTIAL_CONFLICT")
        self.assertIsNone(result["approval"])

    def test_rejected_append_does_not_change_evidence_packet(self) -> None:
        status, record = self.post_case(
            self._metadata(), "payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,450.00 per week."), "207",
        )
        directory = server_module.STORE.case_dir(record["case_id"]) / "evidence"
        before = sorted(path.name for path in directory.iterdir())
        status, _ = self.append_evidence(record["case_id"], "broken.pdf", b"not a pdf", record["revision"])
        self.assertEqual(status, 400)
        self.assertEqual(sorted(path.name for path in directory.iterdir()), before)

    def test_image_only_pdf_is_flagged_and_never_drafted(self) -> None:
        status, record = self.post_case(self._metadata(), "scan.pdf", self._pdf(), "207")
        self.assertEqual(status, 201)
        self.assertEqual(record["summary"]["ocr_required"], ["E-001"])
        self.assertFalse(any(answer["answer"] for answer in record["answers"].values()))

    def test_stale_revision_is_rejected_without_silent_loss(self) -> None:
        status, record = self.post_case(
            self._metadata(), "payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,450.00 per week."), "207",
        )
        self.assertEqual(status, 201)
        answer = record["answers"]["207-3-c"]
        status, saved = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": answer["answer"], "status": "APPROVED"},
        }, record["revision"])
        self.assertEqual(status, 200)
        status, conflict = self.put_answers(record["case_id"], {
            "207-3-c": {"answer": "stale tab text", "status": "EDITED"},
        }, record["revision"])
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current_revision"], saved["revision"])

    def test_replacing_packet_removes_old_supported_draft(self) -> None:
        status, record = self.post_case(
            self._metadata(), "payroll_record.pdf",
            self._pdf("Jordan Moss currently earns gross weekly income of $1,450.00 per week."), "207",
        )
        self.assertEqual(record["answers"]["207-3-c"]["status"], "DRAFT")
        status, replaced = self.append_evidence(
            record["case_id"], "empty_record.pdf", self._pdf(), record["revision"], "replace",
        )
        self.assertEqual(status, 200)
        self.assertEqual(replaced["answers"]["207-3-c"]["status"], "EMPTY")
        self.assertEqual(replaced["answers"]["207-3-c"]["answer"], "")
        self.assertEqual(replaced["documents"][0]["filename"], "empty_record.pdf")


class PlatformDataPathTests(unittest.TestCase):
    def test_explicit_data_directory_wins(self) -> None:
        with patch.dict(os.environ, {"INQUISITIO_DATA_DIR": "~/custom-inquisitio"}):
            self.assertEqual(default_data_root(), Path.home() / "custom-inquisitio")

    def test_macos_uses_application_support(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("sys.platform", "darwin"):
            self.assertEqual(default_data_root(), Path.home() / "Library" / "Application Support" / "Inquisitio" / "cases")

    def test_windows_uses_local_app_data(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}, clear=True), patch("sys.platform", "win32"):
            self.assertEqual(default_data_root(), Path("C:/Users/Test/AppData/Local") / "Inquisitio" / "cases")


if __name__ == "__main__":
    unittest.main()
