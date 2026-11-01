from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
import shutil
from pathlib import Path


CASE_ID = re.compile(r"^[a-f0-9]{32}$")


class CaseStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._lock = threading.RLock()

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def case_dir(self, case_id: str) -> Path:
        if not CASE_ID.fullmatch(case_id):
            raise ValueError("Invalid case identifier.")
        return self.root / case_id

    def create(self, case_id: str, record: dict) -> None:
        with self._lock:
            directory = self.case_dir(case_id)
            directory.mkdir(parents=True, exist_ok=False)
            os.chmod(directory, 0o700)
            (directory / "evidence").mkdir()
            os.chmod(directory / "evidence", 0o700)
            self.save(case_id, record)

    def delete(self, case_id: str) -> None:
        with self._lock:
            directory = self.case_dir(case_id)
            if not directory.is_dir():
                raise FileNotFoundError("Case not found.")
            shutil.rmtree(directory)

    def load(self, case_id: str) -> dict:
        path = self.case_dir(case_id) / "case.json"
        if not path.is_file():
            raise FileNotFoundError("Case not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        records: list[dict] = []
        with self._lock:
            for path in self.root.glob("*/case.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    records.append({
                        "case_id": record["case_id"],
                        "case_name": record["case_name"],
                        "form_id": record["form_id"],
                        "updated_at": record.get("updated_at", ""),
                        "summary": record.get("summary", {}),
                    })
                except (OSError, KeyError, json.JSONDecodeError):
                    continue
        return sorted(records, key=lambda record: record["updated_at"], reverse=True)

    def save(self, case_id: str, record: dict) -> None:
        with self._lock:
            directory = self.case_dir(case_id)
            directory.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(record, indent=2, ensure_ascii=False)
            descriptor, temporary = tempfile.mkstemp(prefix="case-", suffix=".json", dir=directory)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, directory / "case.json")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
