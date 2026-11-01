from __future__ import annotations

import unittest
from pathlib import Path

from inquisitio.forms import load_forms, load_form


ROOT = Path(__file__).resolve().parents[1]


class FormExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.forms = load_forms(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"))

    def test_form_202_is_complete(self) -> None:
        form = self.forms["202"]
        self.assertEqual(len({item.number for item in form.items}), 38)
        self.assertEqual(len(form.items), 81)
        self.assertEqual(form.items[0].item_id, "202-1-a")
        self.assertIn("full name", form.items[0].text)
        self.assertEqual(form.items[-1].item_id, "202-38")
        self.assertIn("cell phone", form.items[-1].text)

    def test_form_205_is_complete_and_official(self) -> None:
        form = load_form(str(ROOT / "assets" / "CT_Practice_Book_2026.pdf"), "205")
        self.assertEqual(len(form.items), 13)
        self.assertEqual(form.items[0].item_id, "205-1")
        self.assertIn("All hospital records", form.items[0].text)
        self.assertEqual(form.items[-1].item_id, "205-13")
        self.assertIn("surveillance material", form.items[-1].text)

    def test_form_207_is_complete(self) -> None:
        form = self.forms["207"]
        self.assertEqual(len({item.number for item in form.items}), 12)
        self.assertEqual(len(form.items), 55)
        self.assertEqual(form.items[0].item_id, "207-1-a")
        self.assertIn("present residence", form.items[0].prompt)
        self.assertEqual(form.items[-1].item_id, "207-12-b")
        self.assertIn("distribution", form.items[-1].text)

    def test_every_item_has_exact_text_and_unique_id(self) -> None:
        for form in self.forms.values():
            ids = [item.item_id for item in form.items]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(item.text.strip() for item in form.items))
            self.assertTrue(all("APPENDIX OF FORMS" not in item.text for item in form.items))

    def test_line_break_hyphenation_is_removed(self) -> None:
        form = self.forms["202"]
        text = " ".join(f"{item.prompt} {item.text}" for item in form.items)
        self.assertIn("information", text)
        self.assertIn("statements", text)
        self.assertNotIn("infor-mation", text)
        self.assertNotIn("state-ments", text)


if __name__ == "__main__":
    unittest.main()
