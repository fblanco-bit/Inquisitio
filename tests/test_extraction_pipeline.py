from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pdfplumber
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle

from inquisitio.engine import extract_facts, build_response, _source_valid
from inquisitio.evidence import extract_pdf
from inquisitio.server import _build_workspace, FORMS

ROOT = Path(__file__).resolve().parents[1]
META = dict(plaintiff='Elena Vega', defendant='Noah Price', responding_party_role='plaintiff', response_date='2026-04-21')


def pdf(path, lines):
    c = canvas.Canvas(str(path))
    for i, line in enumerate(lines):
        c.drawString(50, 750 - i * 22, line)
    c.save()
    return path


def run(paths, form_id='202', metadata=None):
    documents = [extract_pdf(p, f'E-{i:03d}') for i,p in enumerate(paths,1)]
    segs = [s for d in documents for s in d.segments]
    record = dict(form_id=form_id, case_name='Pipeline test', metadata=dict(META if metadata is None else metadata))
    _build_workspace(record, documents, segs)
    record['form'] = FORMS[form_id].to_dict()
    return record, documents, segs


def test_same_packet_produces_byte_identical_answer_payload(tmp_path):
    packet = pdf(tmp_path/'deterministic.pdf', [
        'Patient: Elena Vega',
        'DOB: 03/15/1987',
        'Address: 24 Cedar Lane, Hartford CT 06106',
    ])
    first, _, _ = run([packet])
    second, _, _ = run([packet])
    canonical = lambda record: json.dumps(
        record['answers'], sort_keys=True, separators=(',', ':'), ensure_ascii=True
    ).encode('ascii')
    assert canonical(first) == canonical(second)


def test_label_on_one_line_value_on_next_and_short_date(tmp_path):
    path = pdf(tmp_path/'notes.pdf', ['Patient: Elena Vega','Date of Birth:','03/15/1987','Address:','24 Cedar Lane, Hartford CT 06106'])
    r,_,_ = run([path])
    assert r['answers']['202-1-b']['answer'] == 'Date of birth: 03/15/1987.'
    assert '24 Cedar Lane' in r['answers']['202-1-d']['answer']
    assert r['answers']['202-1-b']['supporting_citations'][0]['quote'] == 'Date of Birth:\n03/15/1987'


def test_two_column_table_with_label_value_pairs(tmp_path):
    path=tmp_path/'table.pdf'
    c=canvas.Canvas(str(path))
    t=Table([['Patient Name','Elena Vega'],['DOB','03/15/1987'],['Operator License No.','CT 123-456-7890'],['Address','24 Cedar Lane, Hartford CT 06106']], colWidths=[150,320])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),1,'black'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    t.wrapOn(c,500,500);t.drawOn(c,45,550);c.save()
    r,docs,_=run([path])
    assert '03/15/1987' in r['answers']['202-1-b']['answer']
    assert '123-456-7890' in r['answers']['202-1-c']['answer']
    assert any(s.cells for s in docs[0].segments)


@pytest.mark.parametrize('name',['E. Vega','Vega, Elena','Vega, Elena M.','Elena Marisol Vega','the Respondent'])
def test_name_variants_are_bound_without_repeating_full_name(tmp_path,name):
    line = name if name=='the Respondent' else 'Patient: '+name
    p=pdf(tmp_path/'notes.pdf',[line,'DOB: 03/15/1987','Address: 24 Cedar Lane, Hartford CT 06106'])
    r,_,_=run([p])
    assert r['answers']['202-1-b']['status']=='DRAFT'
    assert '24 Cedar Lane' in r['answers']['202-1-d']['answer']


def test_dob_conflict_keeps_both_dates_and_inserts_nothing(tmp_path):
    p=pdf(tmp_path/'one.pdf',['Patient: Elena Vega','DOB: 03/15/1987'])
    q=pdf(tmp_path/'two.pdf',['Patient: Vega, E.','DOB: 03/15/1988'])
    r,_,_=run([p,q]);a=r['answers']['202-1-b']
    assert a['status']=='POTENTIAL_CONFLICT'
    assert a['answer']==''
    assert {f['value'] for f in a['conflicts'][0]['facts']}=={'03/15/1987','03/15/1988'}
    assert {c['filename'] for c in a['supporting_citations']}=={'one.pdf','two.pdf'}


def test_equivalent_addresses_are_not_a_conflict(tmp_path):
    p=pdf(tmp_path/'a.pdf',['Patient: Elena Vega','Address: 24 Cedar Avenue, Apartment 2, Hartford, Connecticut 06106'])
    q=pdf(tmp_path/'b.pdf',['Patient: E. Vega','Address: 24 Cedar Ave Apt 2 Hartford CT 06106'])
    r,_,_=run([p,q]);a=r['answers']['202-1-d']
    assert a['status']=='DRAFT'
    assert len(a['supporting_citations'])==2


def test_different_addresses_are_a_conflict(tmp_path):
    p=pdf(tmp_path/'a.pdf',['Patient: Elena Vega','Address: 24 Cedar Lane, Hartford CT 06106'])
    q=pdf(tmp_path/'b.pdf',['Patient: E. Vega','Address: 25 Cedar Lane, Hartford CT 06106'])
    r,_,_=run([p,q]);a=r['answers']['202-1-d']
    assert a['status']=='POTENTIAL_CONFLICT' and not a['answer']


def test_date_normalization_preserves_original_string(tmp_path):
    p=pdf(tmp_path/'a.pdf',['Patient: Elena Vega','Date of Birth: March 15, 1987'])
    r,_,_=run([p]);c=r['answers']['202-1-b']['supporting_citations'][0]
    assert c['original_value']=='March 15, 1987'
    assert c['normalized_value']=='1987-03-15'


def test_horizontal_operator_table_does_not_mix_people(tmp_path):
    path=tmp_path/'crash.pdf';c=canvas.Canvas(str(path))
    t=Table([['Operator Name','DOB','License'],['VEGA, ELENA','03/15/1987','CT 111-111'],['PRICE, NOAH','01/02/1991','CT 999-999']],colWidths=[170,120,120])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),1,'black')]))
    t.wrapOn(c,500,500);t.drawOn(c,50,600);c.save()
    r,_,_=run([path]);a=r['answers']
    assert '111-111' in a['202-1-c']['answer']
    assert '999-999' not in str(a)
    assert not a['202-1-b']['conflicts']


def test_generic_filename_does_not_discard_explicit_facts(tmp_path):
    p=pdf(tmp_path/'notes.pdf',['Patient: Elena Vega','DOB: 03/15/1987'])
    r,_,_=run([p])
    assert r['answers']['202-1-b']['status']=='DRAFT'
    assert r['answers']['202-1-b']['supporting_citations'][0]['confidence'] < 1


def test_latest_treatment_excludes_dob_and_future_scheduled_date(tmp_path):
    p=pdf(tmp_path/'medical.pdf',['METRO REHABILITATION CLINIC','12 Park Street, Hartford CT 06106','Patient: Elena Vega','DOB: 03/15/1987','Therapist: Dana West, PT','VISIT LOG','03/02/2026 Initial visit','04/10/2026 Last visit to date. Continuing therapy.','Scheduled 05/10/2026'])
    r,_,_=run([p]);a=r['answers']['202-6']
    assert '04/10/2026' in a['answer'] and 'Dana West' in a['answer']
    assert '05/10/2026' not in a['answer']


def test_interactive_field_values_are_read(tmp_path):
    path=tmp_path/'interactive.pdf';c=canvas.Canvas(str(path))
    c.drawString(50,750,'Patient: Elena Vega')
    c.acroForm.textfield(name='Date of Birth',tooltip='Date of Birth',x=50,y=650,width=200,height=25,value='03/15/1987')
    c.showPage();c.save()
    r,docs,_=run([path]);a=r['answers']['202-1-b']
    assert '03/15/1987' in a['answer']
    assert any(s.extraction_method=='pypdf_form' for s in docs[0].segments)


def image_pdf(path):
    image=Image.new('RGB',(1800,1200),'white');d=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(ROOT/'assets/InquisitioSans.ttf'),48)
    for i,line in enumerate(['Patient: Elena Vega','DOB: 03/15/1987','Address: 24 Cedar Lane, Hartford CT 06106']):
        d.text((100,150+i*140),line,font=font,fill='black')
    c=canvas.Canvas(str(path));c.drawImage(ImageReader(image),0,200,width=600,height=400);c.save()
    return path


def test_image_only_page_runs_real_ocrmypdf_and_flags_citation(tmp_path):
    r,docs,_=run([image_pdf(tmp_path/'scan.pdf')]);a=r['answers']['202-1-b']
    assert '03/15/1987' in a['answer']
    assert a['supporting_citations'][0]['ocr_sourced'] is True
    assert docs[0].page_methods[0] in {'ocrmypdf', 'pytesseract'}
    if docs[0].page_methods == ('pytesseract',):
        assert any(error['method'] == 'ocrmypdf' for error in docs[0].extraction_errors)
    from inquisitio.exporter import export_case
    from docx import Document
    document=Document(BytesIO(export_case(r)))
    assert 'OCR-sourced' in '\n'.join(p.text for p in document.paragraphs)


def test_real_pytesseract_fallback_reports_ocrmypdf_failure(tmp_path):
    from types import SimpleNamespace
    import sys
    with patch.dict(sys.modules, {'ocrmypdf': SimpleNamespace(ocr=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('deliberate OCRmyPDF failure')))}):
        r,docs,_=run([image_pdf(tmp_path/'scan.pdf')])
    assert '03/15/1987' in r['answers']['202-1-b']['answer']
    assert docs[0].page_methods==('pytesseract',)
    assert 'deliberate OCRmyPDF failure' in docs[0].extraction_errors[0]['error']


def test_fragmented_pdfplumber_page_uses_pymupdf_layout(tmp_path):
    p=pdf(tmp_path/'fragmented.pdf',['Patient: Elena Vega','DOB: 03/15/1987'])
    with patch('pdfplumber.page.Page.extract_text',return_value='P\na\nt\ni\ne\nn\nt'):
        r,docs,_=run([p])
    assert docs[0].page_methods==('pymupdf_layout',)
    assert '03/15/1987' in r['answers']['202-1-b']['answer']


def test_hash_or_quote_tampering_prevents_a_validated_answer(tmp_path):
    p=pdf(tmp_path/'notes.pdf',['Patient: Elena Vega','DOB: 03/15/1987'])
    r,_,segs=run([p])
    facts=extract_facts(segs,META,r['documents'],FORMS['202'].items)
    from dataclasses import replace
    wrong=[replace(f,quote='DOB: 03/15/1988') for f in facts]
    item=next(i for i in FORMS['202'].items if i.item_id=='202-1-b')
    assert not build_response(item,segs,wrong,META,r['documents'])['answer']
    docs=[dict(r['documents'][0],sha256='f'*64)]
    assert not build_response(item,segs,facts,META,docs)['answer']


def test_every_official_field_has_targets_and_no_placeholder():
    for form in FORMS.values():
        from inquisitio.engine import requirement_for
        for item in form.items:
            attrs=requirement_for(item).attributes
            assert attrs and not any(a.startswith('question_') for a in attrs)


def test_provided_packet_identity_conflict_treatment_and_wrong_actor():
    paths=sorted((ROOT/'tests/fixtures/okonkwo').glob('*.pdf'))
    assert len(paths)==2
    r,_,_=run(paths,metadata={'plaintiff':'Terrence Okonkwo','defendant':'Brightline Logistics, Inc. and Sofia Marques','responding_party_role':'plaintiff','response_date':'2026-04-21'})
    a=r['answers']
    assert r['summary']['pages']==9
    assert 'TERRENCE JAMES OKONKWO' in a['202-1-a']['answer']
    assert '071-442-8830' in a['202-1-c']['answer']
    assert '312 Quinnipiac' in a['202-1-d']['answer']
    assert a['202-1-b']['status']=='POTENTIAL_CONFLICT' and a['202-1-b']['answer']==''
    assert {f['value'] for f in a['202-1-b']['conflicts'][0]['facts']}=={'05/30/1979','05/03/1979'}
    for word in ['Concussion','clavicle','Lumbar strain','Scalp laceration','Bilateral knee']:
        assert word in a['202-2']['answer']
    assert '01/09/2026' in a['202-3']['answer']
    assert 'AMERICAN MEDICAL RESPONSE' in a['202-3']['answer']
    assert a['202-3']['evidence_outcome']=='PARTIAL_DRAFT'
    assert '01/11/2026' in a['202-4']['answer']
    for name in ['Feldstein','Voss','Reyes-Okafor','Castellano']:
        assert name in a['202-5']['answer']
    assert '04/16/2026' in a['202-6']['answer']
    assert '40 hours per week' in a['202-23-c']['answer']
    assert '1060' not in a['202-23-c']['answer'] and a['202-23-c']['evidence_outcome']=='PARTIAL_DRAFT'
    assert a['202-15']['answer']==''  # hospital confinement is not home/bed confinement
    assert a['202-16']['evidence_outcome']=='PARTIAL_DRAFT'
    assert 'Voss' in a['202-16']['answer'] and '04/16/2026' in a['202-16']['answer']
    assert 'not established' in a['202-16']['answer']
    assert a['202-38']['answer']==''
    answers='\n'.join(x['answer'] for x in a.values())
    for wrong in ['155-019-7702','11/02/1994','Wheelers Farms','tablet']:
        assert wrong not in answers
    for response in a.values():
        if response['answer']:
            assert response['supporting_citations']
            assert all(c['citation_validated'] for c in response['supporting_citations'])


def test_second_form207_matter_uses_caption_order_and_its_own_targets():
    r,docs,segs=run([ROOT/'tests/fixtures/form207_validation.pdf'],form_id='207',metadata={})
    assert r['metadata']['plaintiff']=='Mira Chen'
    assert r['metadata']['defendant']=='Luca Torres'
    assert r['metadata']['responding_party_role']=='defendant'
    a=r['answers']
    assert len(a)==55 and all(q.startswith('207-') for q in a)
    assert '15 Oak Street' in a['207-1-a']['answer']
    assert 'Harbor Machine' in a['207-3-a']['answer']
    assert '180 Quarry Road' in a['207-3-a']['answer']
    assert '$1,200.00' in a['207-3-c']['answer']
    assert '40 hours' in a['207-3-d']['answer']
    assert a['207-4-a']['evidence_outcome']=='SUPPORTED_NOT_APPLICABLE'
    assert a['207-11-a']['evidence_outcome']=='SUPPORTED_NOT_APPLICABLE'
    for response in a.values():
        if response['answer']:
            assert response['supporting_citations']


def test_wrapped_address_is_preserved_across_nearby_blocks(tmp_path):
    p=pdf(tmp_path/'notes.pdf',['Patient: Elena Vega','Address:','24 Cedar Lane','Hartford, CT 06106'])
    r,_,_=run([p])
    assert '24 Cedar Lane Hartford, CT 06106' in r['answers']['202-1-d']['answer']


def test_multiple_header_fields_on_one_line(tmp_path):
    p=pdf(tmp_path/'notes.pdf',['Patient: Elena Vega  DOB: 03/15/1987','Address: 24 Cedar Lane, Hartford CT 06106'])
    r,_,_=run([p])
    assert '03/15/1987' in r['answers']['202-1-b']['answer']
    assert 'Elena Vega' in r['answers']['202-1-a']['answer']


def test_ambiguous_initial_shared_by_both_parties_does_not_choose_one(tmp_path):
    p=pdf(tmp_path/'notes.pdf',['Patient: E. Vega','DOB: 03/15/1987'])
    meta=dict(META,defendant='Esteban Vega')
    r,_,_=run([p],metadata=meta)
    assert r['answers']['202-1-b']['answer']==''
    assert r['answers']['202-1-b']['status']=='REQUIRES_CLIENT'
    assert 'ambiguous' in r['answers']['202-1-b']['required_follow_up']


def test_form207_role_conflicting_with_order_is_not_silently_used():
    r,_,_=run([ROOT/'tests/fixtures/form207_validation.pdf'],form_id='207',metadata={'plaintiff':'Mira Chen','defendant':'Luca Torres','responding_party_role':'plaintiff'})
    assert r['answers']['207-3-c']['status']=='REQUIRES_CLIENT'
    assert r['answers']['207-3-c']['answer']==''


def test_manual_dob_does_not_survive_reprocessing_a_conflict(tmp_path):
    p=pdf(tmp_path/'one.pdf',['Patient: Elena Vega','DOB: 03/15/1987'])
    q=pdf(tmp_path/'two.pdf',['Patient: Elena Vega','DOB: 03/15/1988'])
    old,_,_=run([p]);old['answers']['202-1-b']['answer']='Manually entered DOB'
    new,docs,segs=run([p,q])
    _build_workspace(new,docs,segs,previous=old)
    a=new['answers']['202-1-b']
    assert a['status']=='POTENTIAL_CONFLICT' and a['answer']==''
    assert a['edit_history'][-1]['previous_answer']=='Manually entered DOB'


def test_out_of_order_column_stream_uses_pymupdf_layout(tmp_path):
    p=tmp_path/'columns.pdf';c=canvas.Canvas(str(p))
    # The PDF content stream draws the whole label column before the values.
    for i,x in enumerate(['Patient Name','DOB','Address']):c.drawString(50,750-i*25,x)
    for i,x in enumerate(['Elena Vega','03/15/1987','24 Cedar Lane, Hartford CT 06106']):c.drawString(210,750-i*25,x)
    c.save()
    r,docs,_=run([p])
    assert docs[0].page_methods==('pymupdf_layout',)
    assert '03/15/1987' in r['answers']['202-1-b']['answer']
    assert '24 Cedar Lane' in r['answers']['202-1-d']['answer']


def test_scanned_entry_beside_printed_blank_label_is_not_skipped(tmp_path):
    image=Image.new('RGB',(600,120),'white');d=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(ROOT/'assets/InquisitioSans.ttf'),48)
    d.text((5,10),'03/15/1987',font=font,fill='black')
    path=tmp_path/'mixed.pdf';c=canvas.Canvas(str(path))
    c.drawString(50,750,'Patient: Elena Vega')
    c.drawString(50,700,'DOB:')
    c.drawImage(ImageReader(image),100,680,width=240,height=48)
    c.save()
    r,docs,_=run([path]);a=r['answers']['202-1-b']
    assert '03/15/1987' in a['answer']
    assert any(c['ocr_sourced'] for c in a['supporting_citations'])
    assert any('+ocrmypdf' in m or '+pytesseract' in m for m in docs[0].page_methods)
