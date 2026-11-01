from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from inquisitio.storage import CaseStore


class StorageTests(unittest.TestCase):
    def test_case_records_are_isolated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CaseStore(Path(temporary))
            first, second = store.new_id(), store.new_id()
            store.create(first, {"case_id": first, "case_name": "One", "form_id": "202", "value": "one"})
            store.create(second, {"case_id": second, "case_name": "Two", "form_id": "207", "value": "two"})
            self.assertEqual(store.load(first)["value"], "one")
            self.assertEqual(store.load(second)["value"], "two")
            self.assertEqual({record["case_id"] for record in store.list()}, {first, second})

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CaseStore(Path(temporary))
            with self.assertRaises(ValueError):
                store.load("../outside")

    def test_records_are_private_and_case_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CaseStore(Path(temporary) / "cases")
            case_id = store.new_id()
            store.create(case_id, {"case_id": case_id, "case_name": "Private", "form_id": "202"})
            record = store.case_dir(case_id) / "case.json"
            self.assertEqual(os.stat(record).st_mode & 0o777, 0o600)
            store.delete(case_id)
            self.assertFalse(store.case_dir(case_id).exists())


if __name__ == "__main__":
    unittest.main()
