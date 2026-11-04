import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import collect_actions as c

class ProbeTests(unittest.TestCase):
    def test_identity_allowlist_and_year(self):
        x=c.identity(dict(kind='rev_split',ticker='005930',year=2018))
        self.assertEqual(x['params']['F_DT'],'20180101')
        self.assertEqual(x['params']['T_DT'],'20181231')
        self.assertEqual(x['params']['MARKET_GB'],'0')
        with self.assertRaises(ValueError):c.identity(dict(kind='orders',ticker='005930',year=2018))
        with self.assertRaises(ValueError):c.identity(dict(kind='dividend',ticker='ALL',year=2018))

    def test_empty_response_is_coverage_gap(self):
        for data in ([],{},None,''):
            x=c.classify(200,dict(rt_cd='0',output1=data),{})
            self.assertEqual(x['status'],'empty_response_no_event_proof')
            self.assertFalse(x['coverage_complete'])
        self.assertEqual(c.classify(200,dict(rt_cd='0'),{})['status'],'malformed_output1')

    def test_protocol_exit_status(self):
        for status in ('blocked','http_or_application_error','malformed_output1'):
            self.assertEqual(c.exit_status({'requests':[{'status':status}]}),2)
        for status in ('empty_response_no_event_proof','incomplete_continuation_not_followed','metadata_returned_unverified','unrecognized_continuation_state'):
            self.assertEqual(c.exit_status({'requests':[{'status':status}]}),0)

    def test_bad_raw_hash_and_identity_fail_closed(self):
        item=dict(kind='rev_split',ticker='005930',year=2018);ident=c.identity(item)
        name='rev_split_005930_2018'
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);raw=out/(name+'_attempt_1.json')
            record=dict(identity=ident,http_status=200,body=dict(rt_cd='0',output1=[]),headers={},attempt=1)
            raw_sha=c.atomic(raw,record)
            result=dict(**c.classify(200,record['body'],{}),attempts=[dict(file=raw.name,sha256=raw_sha,http_status=200)])
            sha=c.atomic(out/(name+'.json'),dict(identity=ident,result=result))
            (out/(name+'.sha256')).write_text(sha)
            raw.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Raw attempt SHA'):c.reuse_checkpoint(out,name,ident)
            record['identity']=c.identity(dict(kind='rev_split',ticker='000660',year=2018))
            result['attempts'][0]['sha256']=c.atomic(raw,record)
            sha=c.atomic(out/(name+'.json'),dict(identity=ident,result=result))
            (out/(name+'.sha256')).write_text(sha)
            with self.assertRaisesRegex(ValueError,'Raw attempt identity'):c.reuse_checkpoint(out,name,ident)

    def test_orphan_raw_preserved(self):
        plan=json.loads((c.ROOT/'plan.json').read_text());first=plan[0]
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);raw=out/(f"{first['kind']}_{first['ticker']}_{first['year']}_attempt_1.json")
            raw.write_text('orphan preserved')
            with self.assertRaisesRegex(ValueError,'Orphan raw'):
                c.collect(plan,out,pause=lambda n:None)
            self.assertEqual(raw.read_text(),'orphan preserved')

    def test_nonzero_application_error(self):
        x=c.classify(200,dict(rt_cd='1',output1=[dict(cash='999')]),{})
        self.assertEqual(x['status'],'http_or_application_error')
        self.assertEqual(x['row_count'],0)

    def test_continuation_is_incomplete_for_dict_or_list(self):
        for flag in ('M','F'):
            for data in ({'x':'1'},[{'x':'1'}]):
                x=c.classify(200,dict(rt_cd='0',output1=data),{'tr_cont':flag})
                self.assertEqual(x['status'],'incomplete_continuation_not_followed')
                self.assertEqual(x['row_count'],1)
        self.assertEqual(c.classify(200,dict(rt_cd='0',output1=[]),{'tr_cont':'UNKNOWN'})['status'],'unrecognized_continuation_state')

    def test_redaction_and_header_allowlist(self):
        class Response:
            status_code=200
            headers={'tr_cont':'M','authorization':'Bearer TOKEN','appsecret':'SECRET'}
            def json(self):return dict(rt_cd='0',output1=[dict(note='KEY SECRET TOKEN')],access_token='TOKEN')
        class Session:
            def get(self,*args,**kwargs):return Response()
        class Client:
            session=Session();key='KEY';secret='SECRET';token='TOKEN'
        status,body,headers=c.request_once(Client(),c.identity(dict(kind='dividend',ticker='030200',year=2026)))
        self.assertEqual(headers,{'tr_cont':'M'})
        self.assertNotIn('access_token',body)
        for value in ('KEY','SECRET','TOKEN'):self.assertNotIn(value,json.dumps(body))

    def test_checkpoint_integrity_and_auth_once(self):
        plan=json.loads((c.ROOT/'plan.json').read_text());calls=[]
        class Client:
            def __init__(self,*args):pass
            def authenticate(self):calls.append('auth')
        with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',KIS_APP_KEY='key',KIS_APP_SECRET='secret'),patch.object(c,'request_once',return_value=(200,dict(rt_cd='0',output1=[]),{})) as request:
            out=Path(temp);r=c.collect(plan,out,Client,pause=lambda n:None)
            self.assertEqual(calls,['auth']);self.assertEqual(request.call_count,len(plan))
            self.assertFalse(r['data_ready'])
            c.collect(plan,out,Client,pause=lambda n:None)
            self.assertEqual(request.call_count,len(plan))
            first=out/(f"{plan[0]['kind']}_{plan[0]['ticker']}_{plan[0]['year']}.json")
            first.write_text('{}')
            with self.assertRaises(ValueError):c.collect(plan,out,Client,pause=lambda n:None)

    def test_plan_extension_reuses_twenty_and_queries_only_forty_six(self):
        plan=json.loads((c.ROOT/'plan.json').read_text());auth=[]
        self.assertEqual(len(plan),66)
        class Client:
            def __init__(self,*args):pass
            def authenticate(self):auth.append('auth')
        with tempfile.TemporaryDirectory() as temp,patch.dict('os.environ',KIS_APP_KEY='key',KIS_APP_SECRET='secret'),patch.object(c,'request_once',return_value=(200,dict(rt_cd='0',output1=[]),{})) as request:
            out=Path(temp)
            c.collect(plan[:20],out,Client,pause=lambda n:None)
            before={p.name:p.read_bytes() for p in out.glob('*_attempt_*.json')}
            request.reset_mock();auth.clear()
            result=c.collect(plan,out,Client,pause=lambda n:None)
            self.assertEqual(request.call_count,46);self.assertEqual(auth,['auth'])
            self.assertEqual(sum(bool(x.get('reused_response')) for x in result['requests']),20)
            for name,data in before.items():self.assertEqual((out/name).read_bytes(),data)

if __name__=='__main__':unittest.main()
