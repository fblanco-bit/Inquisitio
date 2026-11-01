"""Opt-in local mock acceptance smoke, never executed on live files."""
from pathlib import Path
from io import BytesIO
import tempfile
import json
from docx import Document
from pypdf import PdfReader

import inquisitio.server as server
from inquisitio.storage import CaseStore
from inquisitio.evidence import extract_pdf
from inquisitio.exporter import export_case,export_case_pdf,export_traceability

mock=Path(__file__).resolve().parents[1] / 'MOCK_TEST_SUITE'
files=sorted((mock/'FORM202_UPLOAD_ONLY').glob('*.pdf'))+sorted((mock/'FORM205_UPLOAD_ONLY').glob('*.pdf'))
assert len(files)==14,len(files)
with tempfile.TemporaryDirectory() as td:
    server.STORE=CaseStore(Path(td)/'cases')
    case_id=server.STORE.new_id()
    rec={'case_id':case_id,'case_name':'Rivera v. Meridian Cargo Services',
        'form_id':'202','schema_version':3,'revision':1,
        'metadata':{'plaintiff':'Elena Sofia Rivera','defendant':'Meridian Cargo Services LLC and Parker Moss',
                    'responding_party_role':'plaintiff','interrogating_party':'Meridian Cargo Services LLC and Parker Moss',
                    'docket_number':'CV-TEST-202-0042','response_date':'2026-10-12',
                    'court':'Superior Court','judicial_district':'New Haven at New Haven'},
        'form':server.FORMS['202'].to_dict(),'answers':{},'summary':{},'documents':{}}
    docs=[];segs=[]
    for i,p in enumerate(files,1):
        doc=extract_pdf(p,f'E-{i:03d}',p.name)
        docs.append(doc);segs.extend(doc.segments)
    server._build_workspace(rec,docs,segs)
    assert len(rec['answers'])==81
    assert len(rec['production'])==13
    assert rec['production']['205-1']['candidates']
    assert rec['production']['205-3']['candidates']
    assert rec['production']['205-5']['candidates']
    assert rec['production']['205-13']['status']=='REVIEW_REQUIRED'
    assert not any(item['selected_sources'] or item['bates_range'] or item['response'] for item in rec['production'].values())
    dest=Path("verification/0.5.1")
    dest.mkdir(parents=True, exist_ok=True)
    word_bytes=export_case(rec)
    (dest/"Rivera_Forms202_205_Review_Draft.docx").write_bytes(word_bytes)
    word=Document(BytesIO(word_bytes))
    text='\n'.join(p.text for p in word.paragraphs)
    assert text.count('ANSWER:')==81
    assert text.count('RESPONSE:')==13
    pdf_bytes=export_case_pdf(rec)
    (dest/"Rivera_Forms202_205_Review_Draft.pdf").write_bytes(pdf_bytes)
    with PdfReader(BytesIO(pdf_bytes)) as pdf:
        pdf_pages=len(pdf.pages)
    trace_bytes=export_traceability(rec)
    (dest/"Rivera_Traceability.docx").write_bytes(trace_bytes)
    report=Document(BytesIO(trace_bytes))
    report_text='\n'.join(p.text for p in report.paragraphs)
    assert 'Form 205 - Document Production Review' in report_text
    print(json.dumps({'form202_slots':len(rec['answers']),'form205_slots':len(rec['production']),
                      'forms207_slots':len(server.FORMS['207'].items),
                      'PDFs_uploaded':len(files),'total_pages':sum(d.pages for d in docs),
                      'suggestion_counts':{i:len(p['candidates']) for i,p in rec['production'].items()},
                      'pdf_export_pages':pdf_pages,'word_paragraphs':len(word.paragraphs)},indent=2))
