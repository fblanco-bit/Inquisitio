from __future__ import annotations

import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from docx import Document
import pdfplumber

from inquisitio.evidence import EvidenceDocument, EvidenceSegment
from inquisitio.exporter import export_case, export_case_pdf, export_traceability
from inquisitio.forms import load_form
from inquisitio.production import build_production_review

ROOT = Path(__file__).resolve().parents[1]


class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.form202 = load_form(str(ROOT / 'assets' / 'CT_Practice_Book_2026.pdf'), '202').to_dict()
        cls.form205 = load_form(str(ROOT / 'assets' / 'CT_Practice_Book_2026.pdf'), '205')

    def specimen(self):
        seg = EvidenceSegment('E-001:p1:s1', 'E-001', 'Hospital_Record.pdf', 1,
                              'The hospital medical report lists Elena Rivera as patient. A medical bill is attached.', 'LINE')
        doc = EvidenceDocument('E-001', 'Hospital_Record.pdf', 'a'*64, 1, 'TEXT_EXTRACTED', (seg,))
        return doc

    def test_candidates_are_not_auto_production(self):
        docs = [self.specimen()]
        production = build_production_review(self.form205.items, docs)
        self.assertEqual(len(production), 13)
        self.assertTrue(production['205-1']['candidates'])
        self.assertTrue(production['205-6']['candidates'])
        self.assertEqual(production['205-1']['status'], 'REVIEW_REQUIRED')
        self.assertEqual(production['205-1']['selected_sources'], [])
        self.assertEqual(production['205-1']['response'], '')
        self.assertFalse(production['205-13']['candidates'])

    def test_reprocess_resets_confirmation_and_keeps_note(self):
        previous = build_production_review(self.form205.items, [self.specimen()])
        previous['205-1'].update(status='PRODUCED_CONFIRMED', response='Produced',
                                  selected_sources=['E-001'], bates_range='TEST_001', reviewer_notes='Verify again')
        next_review = build_production_review(self.form205.items, [self.specimen()], previous)
        self.assertEqual(next_review['205-1']['status'], 'REVIEW_REQUIRED')
        self.assertEqual(next_review['205-1']['selected_sources'], [])
        self.assertEqual(next_review['205-1']['reviewer_notes'], 'Verify again')
        self.assertTrue(next_review['205-1']['review_reset'])

    def test_exports_show_all_thirteen_responses_not_just_requests(self):
        production = build_production_review(self.form205.items, [self.specimen()])
        production['205-1']['response'] = 'Test response entered by reviewer.'
        rec = {'case_name': 'Rivera v Meridian', 'form_id':'202', 'form': self.form202,
               'answers': {}, 'metadata': {'plaintiff':'Elena Rivera', 'defendant':'Meridian'},
               'production': production}
        word = Document(BytesIO(export_case(rec)))
        text = '\n'.join(x.text for x in word.paragraphs)
        self.assertIn('Test response entered by reviewer.', text)
        self.assertEqual(text.count('RESPONSE:'), 13)
        self.assertIn('[Production response not verified', text)
        trace = Document(BytesIO(export_traceability(rec)))
        self.assertIn('205-1:', '\n'.join(p.text for p in trace.paragraphs))
        with pdfplumber.open(BytesIO(export_case_pdf(rec))) as pdf:
            pdf_text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        self.assertIn('Test response entered by reviewer.', pdf_text)
        self.assertIn('205 Defendant Requests for Production', pdf_text)


if __name__ == '__main__':
    unittest.main()
