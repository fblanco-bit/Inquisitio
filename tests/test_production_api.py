from __future__ import annotations
import json
from tests.test_server import ServerSecurityTests


class ProductionAPITests(ServerSecurityTests):
    def test_form_205_is_paired_and_requires_real_review(self):
        data = self._pdf('Elena Rivera hospital medical bill and hospital record, February 2026.')
        meta = json.dumps({'plaintiff':'Elena Rivera','defendant':'Meridian Cargo Services',
                           'responding_party_role':'plaintiff','interrogating_party':'Meridian Cargo Services'})
        status, record = self.post_case(metadata=meta,data=data,filename='Elena_Hospital_Record.pdf')
        self.assertEqual(status,201)
        self.assertEqual(len(record['production']),13)
        self.assertEqual(len(record['answers']),81)
        target=record['production']['205-1']
        self.assertEqual(target['status'],'REVIEW_REQUIRED')
        self.assertEqual(target['selected_sources'],[])
        self.assertEqual(target['response'],'')
        self.assertTrue(target['candidates'])
        # Cannot claim actual production without manual response, source and Bates.
        payload={'answers':{},'production':{'205-1': {'status':'PRODUCED_CONFIRMED', 'response':'Produced.'}},'revision':record['revision']}
        code,result=self._put_payload(record['case_id'],payload)
        self.assertEqual(code,400)
        self.assertIn('Bates',result['error'])
        payload['production']['205-1'].update({'bates_range':'PLTF_TEST_0001','selected_sources':['E-001'],
                                               'reviewer_notes':'Verified manually for this mock test'})
        code,result=self._put_payload(record['case_id'],payload)
        self.assertEqual(code,200)
        self.assertEqual(result['production']['205-1']['status'],'PRODUCED_CONFIRMED')
        code,result=self.append_evidence(record['case_id'],'more.pdf',self._pdf('New medical bill'),result['revision'])
        self.assertEqual(code,200)
        self.assertEqual(result['production']['205-1']['status'],'REVIEW_REQUIRED')
        self.assertTrue(result['production']['205-1']['review_reset'])
        self.assertEqual(result['production']['205-1']['selected_sources'],[])
        self.assertEqual(result['production']['205-1']['reviewer_notes'],'Verified manually for this mock test')

    def _put_payload(self,case_id,payload):
        import http.client
        raw=json.dumps(payload).encode()
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        client.request('PUT',f'/api/cases/{case_id}/answers',body=raw,headers={'Content-Type':'application/json','Content-Length':str(len(raw))})
        response=client.getresponse();data=json.loads(response.read());client.close()
        return response.status,data
