"""Read-only bounded KSD metadata availability probe. Does not verify entitlements."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
HELPER = ROOT.parent / 'kis_v1' / 'collect.py'
HELPER_SHA = '30c130cee54517fc67b73a3a4600b6b685780bec213ee523b5e67b9011b13a59'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == HELPER_SHA, 'Immutable KIS helper changed'
spec = importlib.util.spec_from_file_location('immutable_kis_sample_helper', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
ENDPOINTS = {
    'rev_split': ('/uapi/domestic-stock/v1/ksdinfo/rev-split', 'HHKDB669105C0'),
    'dividend': ('/uapi/domestic-stock/v1/ksdinfo/dividend', 'HHKDB669102C0'),
    'bonus_issue': ('/uapi/domestic-stock/v1/ksdinfo/bonus-issue', 'HHKDB669101C0'),
}
TRANSIENT_HTTP = {429, 500, 502, 503, 504}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def atomic(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(data)
    os.replace(temp,path)
    return digest(data)

def identity(item):
    if set(item) != {'kind','ticker','year'} or item['kind'] not in ENDPOINTS:
        raise ValueError('Unsupported request identity')
    if not isinstance(item['ticker'],str) or not re.fullmatch('[0-9]{6}',item['ticker']):
        raise ValueError('One six-digit ticker required')
    if type(item['year']) is not int or not 2016 <= item['year'] <= 2026:
        raise ValueError('One evaluation year required')
    path,tr = ENDPOINTS[item['kind']]
    params = dict(SHT_CD=item['ticker'], CTS='', F_DT=f"{item['year']}0101", T_DT=f"{item['year']}1231")
    if item['kind']=='rev_split': params['MARKET_GB']='0'
    if item['kind']=='dividend': params.update(GB1='0',HIGH_GB='')
    return dict(endpoint=helper.BASE+path,tr_id=tr,params=params)

def classify(status,body,headers):
    if status != 200 or not isinstance(body,dict) or body.get('rt_cd') not in ('0',0):
        return dict(status='http_or_application_error',row_count=0,coverage_complete=False)
    if 'output1' not in body:
        return dict(status='malformed_output1',row_count=0,coverage_complete=False)
    data=body['output1']
    if data is None or data=='' or data=={}: rows=[]
    elif isinstance(data,dict): rows=[data]
    elif isinstance(data,list) and all(isinstance(x,dict) for x in data): rows=[x for x in data if x]
    else:return dict(status='malformed_output1',row_count=0,coverage_complete=False)
    continuation=str(headers.get('tr_cont','')).strip().upper()
    if continuation in ('M','F'):
        label='incomplete_continuation_not_followed'
    elif continuation not in ('','D','E'):
        label='unrecognized_continuation_state'
    else: label='metadata_returned_unverified' if rows else 'empty_response_no_event_proof'
    return dict(status=label,row_count=len(rows),coverage_complete=False)

def exit_status(manifest):
    failures={'blocked','http_or_application_error','malformed_output1'}
    return 2 if any(x.get('status') in failures for x in manifest['requests']) else 0

def reuse_checkpoint(out,name,ident):
    checkpoint=out/(name+'.json')
    saved=json.loads(checkpoint.read_text())
    expected_hash=(out/(name+'.sha256')).read_text().strip()
    if digest(checkpoint.read_bytes())!=expected_hash or saved['identity']!=ident:
        raise ValueError('Checkpoint identity or SHA mismatch')
    attempts=saved['result']['attempts']
    if not isinstance(attempts,list) or not attempts:
        raise ValueError('Checkpoint raw attempts missing')
    final=None
    for index,attempt in enumerate(attempts,1):
        filename=f'{name}_attempt_{index}.json'
        if attempt['file']!=filename:
            raise ValueError('Checkpoint raw reference mismatch')
        raw=out/filename
        if digest(raw.read_bytes())!=attempt['sha256']:
            raise ValueError('Raw attempt SHA mismatch')
        record=json.loads(raw.read_text())
        if record['identity']!=ident or record['attempt']!=index or record['http_status']!=attempt['http_status']:
            raise ValueError('Raw attempt identity mismatch')
        final=record
    recomputed=classify(final['http_status'],final['body'],final['headers'])
    if any(saved['result'].get(k)!=v for k,v in recomputed.items()):
        raise ValueError('Checkpoint result differs from raw response')
    return saved['result']

def request_once(client, ident):
    # Paths and TR IDs come only from the fixed allowlist, never response content.
    if (ident['endpoint'],ident['tr_id']) not in {(helper.BASE+p,t) for p,t in ENDPOINTS.values()}:
        raise ValueError('Endpoint outside GET allowlist')
    try:
        response=client.session.get(ident['endpoint'],headers={
            'Content-Type':'application/json','authorization':'Bearer '+client.token,
            'appkey':client.key,'appsecret':client.secret,'tr_id':ident['tr_id'],'custtype':'P'},
            params=ident['params'],timeout=15,allow_redirects=False)
        try: body=response.json()
        except ValueError: body={'non_json_body':response.text}
        headers={'tr_cont':response.headers.get('tr_cont','')}
        return response.status_code,helper.redact(body,(client.key,client.secret,client.token)),headers
    except (client.requests.Timeout,client.requests.ConnectionError):
        return None,{'msg1':'KIS network connection or timeout'},{}
    except client.requests.RequestException:
        return None,{'msg1':'KIS request failed'},{}

def collect(plan,out,client_factory=helper.KIS,pause=time.sleep):
    if not 1 <= len(plan) <= 100 or len({json.dumps(identity(x),sort_keys=True) for x in plan})!=len(plan):
        raise ValueError('Expected one to one hundred unique one-ticker/year requests')
    out.mkdir(parents=True,exist_ok=True)
    creds=[os.getenv(x) for x in helper.CREDENTIALS]
    manifest=dict(schema_version=1,started_at=datetime.now(timezone.utc).isoformat(),
        helper_sha256=HELPER_SHA,collector_sha256=digest(Path(__file__).read_bytes()),
        plan_canonical_sha256=digest(json.dumps(plan,sort_keys=True).encode()),
        plan_file_sha256=digest((ROOT/'plan.json').read_bytes()),requests=[],
        data_ready=False,scope='KIS KSD metadata availability only; no ratio or entitlement approval')
    client=None;blocked=None
    for item in plan:
        ident=identity(item);name=f"{item['kind']}_{item['ticker']}_{item['year']}"
        checkpoint=out/(name+'.json'); entry=dict(**item,identity=ident,attempts=[])
        manifest['requests'].append(entry)
        if checkpoint.exists():
            entry.update(reuse_checkpoint(out,name,ident));entry['reused_response']=True
        elif any(out.glob(name+'_attempt_*.json')) or (out/(name+'.sha256')).exists():
            raise ValueError('Orphan raw attempt or sidecar preserved; use a clean output directory')
        elif blocked or not all(creds): entry.update(status='blocked',reason=blocked or 'credentials unavailable')
        else:
            if client is None:
                try:
                    client=client_factory(*creds);client.authenticate()
                except Exception:
                    blocked='authentication unavailable';entry.update(status='blocked',reason=blocked)
                    atomic(out/'summary.json',manifest);continue
            for attempt in range(3):
                pause(.3)
                status,body,headers=request_once(client,ident)
                record=dict(identity=ident,http_status=status,body=body,headers=headers,
                    collected_at=datetime.now(timezone.utc).isoformat(),attempt=attempt+1)
                raw=out/f'{name}_attempt_{attempt+1}.json'
                raw_sha=atomic(raw,record)
                entry['attempts'].append(dict(file=raw.name,sha256=raw_sha,http_status=status))
                if helper.auth_error(status,body):
                    blocked='authentication or permission error; remaining requests stopped';break
                transient=status is None or status in TRANSIENT_HTTP or (isinstance(body,dict) and body.get('msg_cd')=='EGW00201')
                if not transient or attempt==2:break
                pause(1)
            entry.update(classify(status,body,headers))
            saved=dict(identity=ident,result={k:v for k,v in entry.items() if k not in ('identity','kind','ticker','year')})
            sha=atomic(checkpoint,saved)
            # Sidecar is atomic too; missing sidecar fails closed after interruption.
            tmp=out/(name+'.sha256.tmp');tmp.write_text(sha+'\n');os.replace(tmp,out/(name+'.sha256'))
        manifest['counts']=dict(Counter(x.get('status','unexecuted') for x in manifest['requests']))
        atomic(out/'summary.json',manifest)
    manifest['finished_at']=datetime.now(timezone.utc).isoformat()
    manifest['counts']=dict(Counter(x.get('status','unexecuted') for x in manifest['requests']))
    atomic(out/'summary.json',manifest)
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=collect(json.loads((ROOT/'plan.json').read_text()),args.out)
    print(json.dumps(dict(requests=len(result['requests']),counts=result['counts'],data_ready=False)))
    sys.exit(exit_status(result))
