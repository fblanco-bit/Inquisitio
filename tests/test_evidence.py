from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reportlab.pdfgen import canvas

from inquisitio.evidence import extract_pdf


class EvidenceExtractionTests(unittest.TestCase):
    def test_page_and_exact_text_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.pdf"
            pdf = canvas.Canvas(str(path))
            pdf.drawString(72, 720, "Medical Record")
            pdf.drawString(72, 690, "The patient was diagnosed with a cervical strain on June 3, 2025.")
            pdf.save()
            result = extract_pdf(path, "E-001")
            self.assertEqual(result.extraction_status, "TEXT_EXTRACTED")
            self.assertTrue(any(segment.page == 1 for segment in result.segments))
            self.assertTrue(any("cervical strain" in segment.text for segment in result.segments))


if __name__ == "__main__":
    unittest.main()

