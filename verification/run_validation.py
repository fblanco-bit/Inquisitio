"""Run the supplied regression packet through the real local HTTP API."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, sys, threading, uuid
from collections import Counter
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=PROJECT/'verification/rerun');args=p.parse_args()
OUT=args.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
os.environ['INQUISITIO_DATA_DIR']=str(OUT/'runtime/cases')
import pdfplumber
from docx import Document
from inquisitio import server
from inquisitio.engine import extract_facts
from inquisitio.evidence import extract_pdf
from inquisitio.storage import CaseStore
server.STORE=CaseStore(OUT/'runtime/cases')
http=server.InquisitioServer(('127.0.0.1',0),server.Handler)
thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{http.server_address[1]}'


def get(path):
    with urlopen(base+path,timeout=90) as r:return r.read()


def create(name,form_id,metadata,paths):
    boundary='InquisitioValidation'+uuid.uuid4().hex;parts=[]
    for key,value in {'case_name':name,'form_id':form_id,'metadata':json.dumps(metadata)}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for path in paths:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="evidence"; filename="{path.name}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()+path.read_bytes()+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request=Request(base+'/api/cases',data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
    with urlopen(request,timeout=90) as r:
        assert r.status==201
        response=json.load(r)
    record=server.STORE.load(response['case_id'])
    return record


def verify(record, paths, prefix):
    docs=[extract_pdf(path,f'E-{i:03d}') for i,path in enumerate(paths,1)]
    segs=[s for d in docs for s in d.segments]
    trace=[]
    extract_facts(segs,record['metadata'],record['documents'],server.FORMS[record['form_id']].items,trace)
    for block in trace:
        used=[q for q,a in record['answers'].items() if any(block['segment_id'] in c.get('source_segment_ids',[c['segment_id']]) or block['segment_id']==c.get('attribution_segment_id') for c in a['supporting_citations'])]
        block['accepted_into_responses']=used
        if used:block['decision']='ACCEPTED';block['reason']='Validated source or party attribution for '+', '.join(used)
        elif block['facts']:
            block['decision']='NOT_INSERTED'
            respondent=record['metadata'][record['metadata']['responding_party_role']]
            subjects={f['subject'] for f in block['facts']}
            if all(s.casefold()!=respondent.casefold() for s in subjects):
                block['reason']='Facts belong to '+', '.join(sorted(subjects))+', not the responding party'
            else:
                target_questions=[q for q,a in record['answers'].items() if any(f['attribute'] in a['requirement']['attributes'] for f in block['facts'])]
                block['reason']='; '.join(q+': '+record['answers'][q]['status']+'; '+record['answers'][q]['required_follow_up'] for q in target_questions) if target_questions else 'Supporting context only: '+', '.join(sorted({f['attribute'] for f in block['facts']}))
        else:block['decision']='NO_TARGET_FACT';block['reason']='No explicit selected-question fact established in this block; raw text retained'
    (OUT/(prefix+'_blocks.json')).write_text(json.dumps(trace,indent=2))
    flat=lambda t:re.sub(r'\s+','',t)
    pages={}
    for i,path in enumerate(paths,1):
        with pdfplumber.open(path) as pdf:
            for n,page in enumerate(pdf.pages,1):pages[(f'E-{i:03d}',n)]=flat(page.extract_text() or '')
    sourcehash={f'E-{i:03d}':hashlib.sha256(path.read_bytes()).hexdigest() for i,path in enumerate(paths,1)}
    refs=0;unique=set()
    for a in record['answers'].values():
        if a['answer']:assert a['supporting_citations'], 'Populated answer without citation'
        for c in a['supporting_citations']:
            assert c['document_sha256']==sourcehash[c['source_id']]
            assert flat(c['quote']) in pages[(c['source_id'],c['page'])], (c['filename'],c['page'],c['quote'])
            if c.get('attribution_quote'):assert flat(c['attribution_quote']) in pages[(c['source_id'],c['page'])]
            assert c['citation_validated']
            refs+=1;unique.add((c['source_id'],c['page'],c['quote']))
    counts=dict(documents=len(paths),pages=sum(d.pages for d in docs),facts_extracted=len(record['facts']),
        responses_populated=sum(bool(a['answer']) for a in record['answers'].values()),
        citation_references_validated=refs,distinct_source_passages_validated=len(unique),
        questions_left_for_review=sum(a['status'] != 'APPROVED' for a in record['answers'].values()),
        status_counts=dict(Counter(a['status'] for a in record['answers'].values())),
        evidence_outcomes=dict(Counter(a['evidence_outcome'] for a in record['answers'].values())))
    (OUT/(prefix+'_counts.json')).write_text(json.dumps(counts,indent=2))
    (OUT/(prefix+'_workspace.json')).write_text(json.dumps(record,indent=2))
    caseid=record['case_id']
    for route,ext in [('pdf','pdf'),('export','docx')]:
        content=get(f'/api/cases/{caseid}/{route}')
        target=OUT/f'{prefix}_Form_{record["form_id"]}_responses.{ext}';target.write_bytes(content)
        if ext=='pdf':
            with pdfplumber.open(BytesIO(content)) as doc:
                text='\n'.join(page.extract_text() or '' for page in doc.pages)
                print('EXPORT',target.name,'pages',len(doc.pages),'responses',text.count('RESPONSE:'))
                assert text.count('RESPONSE:')==len(record['answers'])
        else:
            doc=Document(BytesIO(content));text='\n'.join(x.text for x in doc.paragraphs)
            assert text.count('Response:')==len(record['answers'])
        assert 'Source:' in text
        if prefix=='Okonkwo':
            assert '05/30/1979' in text and '05/03/1979' in text
            assert '04/16/2026' in text
    rows=[]
    for item in record['form']['items']:
        a=record['answers'][item['item_id']]
        rows.append({'field':str(item['number'])+(f'({item["label"]})' if item['label'] else ''),
            'question':' '.join(x for x in (item['prompt'],item['text']) if x),
            'status':a['status'],'evidence_outcome':a['evidence_outcome'],'value_inserted':a['answer'],
            'sources':'; '.join(sorted({f'{c["filename"]}, p. {c["page"]}' for c in a['supporting_citations']})),
            'review_reason':'; '.join([c['description'] for c in a['conflicts']] or a['missing_information'])})
    with (OUT/(prefix+'_all_fields.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return counts

try:
    from inquisitio import __version__
    health=json.loads(get('/api/health'));assert health['version']==__version__
    html=get('/').decode();assert 'never inserted' not in html;assert 'populated automatically' in html
    assert 'OCR-sourced' in get('/app.js').decode()
    (OUT/'health.json').write_text(json.dumps(health,indent=2))
    fixture=PROJECT/'tests/fixtures/okonkwo';paths=sorted(fixture.glob('*.pdf'));assert len(paths)==2
    meta={'plaintiff':'Terrence Okonkwo','defendant':'Brightline Logistics, Inc. and Sofia Marques','responding_party_role':'plaintiff',
        'interrogating_party':'Brightline Logistics, Inc. and Sofia Marques','response_date':'2026-04-21',
        'docket_number':'NNH-CV26-6023871-S','court':'Superior Court','judicial_district':'New Haven at New Haven'}
    record=create('Okonkwo v. Brightline Logistics','202',meta,paths)
    a=record['answers'];assert a['202-1-b']['status']=='POTENTIAL_CONFLICT' and not a['202-1-b']['answer']
    assert {f['value'] for f in a['202-1-b']['conflicts'][0]['facts']}=={'05/30/1979','05/03/1979'}
    text='\n'.join(x['answer'] for x in a.values())
    assert all(w not in text for w in ['155-019-7702','11/02/1994','14 Wheelers Farms','tablet'])
    print('FORM202',json.dumps(verify(record,paths,'Okonkwo'),indent=2))
    paths=[PROJECT/'tests/fixtures/form207_validation.pdf']
    second=create('Chen v. Torres validation','207',{},paths)
    assert second['metadata']['responding_party_role']=='defendant'
    assert '$1,200.00' in second['answers']['207-3-c']['answer']
    print('FORM207',json.dumps(verify(second,paths,'Form207_validation'),indent=2))
    print('HTTP_UPLOAD_EXTRACTION_CITATION_EXPORT_CHECKS_PASSED')
finally:
    http.shutdown();http.server_close();thread.join(timeout=5)
