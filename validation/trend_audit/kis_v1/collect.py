"""KIS historical quote sampler. No imports from the production report."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parent
BASE = "https://openapi.koreainvestment.com:9443"
PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR = "FHKST03010100"
FIELDS = {"open":"stck_oprc","high":"stck_hgpr","low":"stck_lwpr",
          "close":"stck_clpr","volume":"acml_vol"}
REPO_REF = "f686f604587d6b98e13b1d0cbe6b50f7cadadb77"
CREDENTIALS = ("KIS_APP_KEY","KIS_APP_SECRET")


def params(sample):
    return dict(FID_COND_MRKT_DIV_CODE="J",FID_INPUT_ISCD=sample["ticker"],
                FID_INPUT_DATE_1=sample["start"],FID_INPUT_DATE_2=sample["end"],
                FID_PERIOD_DIV_CODE="D",FID_ORG_ADJ_PRC="1")


def number(value):
    if type(value) not in (str,int) or not re.fullmatch(r"[0-9]+",str(value)):
        raise ValueError("Expected unsigned integer")
    return int(value)


def auth_error(status, payload):
    if status in (401,403):
        return True
    if not isinstance(payload,dict):
        return False
    if payload.get("rt_cd") in ("0",0):
        return False
    message = str(payload.get("msg1",payload.get("error_description",""))).lower()
    return any(word in message for word in ("token","appkey","app key","unauthorized","forbidden","토큰","권한","인증"))


def normalize(sample,status,payload):
    if status != 200 or not isinstance(payload,dict) or payload.get("rt_cd") not in ("0",0):
        return [],["HTTP or KIS application error"]
    header = payload.get("output1") or {}
    if not isinstance(header,dict):
        return [],["Invalid symbol metadata"]
    for key in ("stck_shrn_iscd","mksc_shrn_iscd"):
        if header.get(key) and header[key] != sample["ticker"]:
            return [],["Response symbol mismatch"]
    data = payload.get("output2")
    if not isinstance(data,list) or not data:
        return [],["No daily rows"]
    issues, rows, seen, conflicts = [], {}, {}, set()
    for raw in data:
        if not raw:  # KIS can pad a short response with empty objects.
            continue
        if not isinstance(raw,dict):
            issues.append("Malformed daily row")
            continue
        try:
            day = raw["stck_bsop_date"]
            if not isinstance(day,str) or not re.fullmatch(r"[0-9]{8}",day):
                raise ValueError("Invalid trading date")
            datetime.strptime(day,"%Y%m%d")
            if not sample["start"] <= day <= sample["end"]:
                issues.append(f"{day}: outside request")
                continue
            if day not in sample["expected"]:
                issues.append(f"{day}: outside frozen trading calendar")
                continue
            if any(raw.get(k) and raw[k]!=sample["ticker"] for k in ("stck_shrn_iscd","mksc_shrn_iscd")):
                conflicts.add(day)
                issues.append(f"{day}: response symbol mismatch")
                continue
            row = {name:number(raw[field]) for name,field in FIELDS.items()}
            if day in seen:
                if seen[day] != row:
                    issues.append(f"{day}: conflicting duplicate")
                    conflicts.add(day)
                else:
                    issues.append(f"{day}: duplicate")
            seen[day] = row
            if not all(row[k]>0 for k in ("open","high","low","close","volume")):
                issues.append(f"{day}: zero price or volume; suspension/listing status unverified")
                continue
            if not row["low"]<=min(row["open"],row["close"])<=max(row["open"],row["close"])<=row["high"]:
                issues.append(f"{day}: invalid OHLC")
                continue
            rows[day] = dict(ticker=sample["ticker"],date=day,**row,grade="KIS original-price response")
        except (ValueError,KeyError):
            issues.append("Invalid date or missing/malformed OHLCV field")
    for day in conflicts:
        rows.pop(day,None)
    missing = set(sample["expected"])-rows.keys()
    if missing:
        issues.append("Missing expected sessions: "+",".join(sorted(missing)))
    return [rows[day] for day in sorted(rows)],issues


def redact(value,secrets):
    if isinstance(value,dict):
        sensitive = {"authorization","appkey","appsecret","access_token","refresh_token","token"}
        return {k:redact(v,secrets) for k,v in value.items()
                if re.sub(r"[^a-z0-9_]","",k.lower()) not in sensitive}
    if isinstance(value,list):
        return [redact(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                value = value.replace(secret,"[redacted]")
    return value


class KIS:
    """Reuse kr_report's client-credentials endpoint and quote headers in memory."""
    def __init__(self,key,secret):
        import requests
        self.requests = requests
        self.session = requests.Session()
        self.key,self.secret = key,secret
        self.token = None

    def authenticate(self):
        response = self.session.post(BASE+"/oauth2/tokenP",json=dict(
            grant_type="client_credentials",appkey=self.key,appsecret=self.secret),
            timeout=10,allow_redirects=False)
        body = response.json()
        if response.status_code != 200 or not isinstance(body,dict) or not body.get("access_token"):
            raise ValueError("KIS token issuance unsuccessful")
        self.token = body["access_token"]

    def quote(self,sample):
        for attempt in range(2):
            try:
                response = self.session.get(BASE+PATH,headers={
                    "Content-Type":"application/json","authorization":"Bearer "+self.token,
                    "appkey":self.key,"appsecret":self.secret,"tr_id":TR,"custtype":"P"},
                    params=params(sample),timeout=15,allow_redirects=False)
                if attempt==0 and response.status_code in (429,500,502,503,504):
                    time.sleep(2)
                    continue
                try:
                    body = response.json()
                except ValueError:
                    body = {"non_json_body":response.text}
                return response.status_code,redact(body,(self.key,self.secret,self.token))
            except (self.requests.Timeout,self.requests.ConnectionError):
                if attempt:
                    return None,{"msg1":"KIS network connection or timeout"}
                time.sleep(2)
            except self.requests.RequestException:
                return None,{"msg1":"KIS request failed"}
        raise AssertionError("Unreachable retry state")


def write_csv(path,rows):
    with path.open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_file(path,body):
    path.write_text(json.dumps(body,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def collect(out,client_factory=KIS):
    out.mkdir(parents=True,exist_ok=True)
    samples = json.loads((ROOT/"samples.json").read_text())
    credentials = [os.getenv(k) for k in CREDENTIALS]
    manifest = {"repository_ref":REPO_REF,"started_at":datetime.now(timezone.utc).isoformat(),
                "frozen_comparison_sha256":sha(ROOT/"frozen_comparison.csv"),"endpoint":BASE+PATH,"tr_id":TR,"collector_sha256":sha(Path(__file__)),
                "sample_calendar_sha256":sha(ROOT/"samples.json"),
                "credential_present":dict(zip(CREDENTIALS,map(bool,credentials))),"requests":[]}
    client, blocked, prices = None, None, {}
    for sample in samples:
        ticker = sample["ticker"]
        request = params(sample)
        entry = {"ticker":ticker,"params":request,"expected":sample["expected"],"status":"조회 실패 또는 자료 미확보"}
        manifest["requests"].append(entry)
        raw = out/f"kis_{ticker}_raw.json"
        if raw.is_file():
            saved = json.loads(raw.read_text())
            if saved["params"]!=request or saved["endpoint"]!=BASE+PATH or saved["tr_id"]!=TR:
                raise ValueError("Cached request identity mismatch")
            entry["reused_response"] = True
        else:
            if blocked or not all(credentials):
                entry["reason"] = blocked or "KIS credentials unavailable"
                continue
            if client is None:
                try:
                    client = client_factory(*credentials)
                    client.authenticate()
                except (ImportError,ValueError,OSError) as exc:
                    blocked = f"KIS authentication unavailable ({type(exc).__name__})"
                    entry["reason"] = blocked
                    continue
            status,body = client.quote(sample)
            saved = dict(params=request,http_status=status,body=body,endpoint=BASE+PATH,tr_id=TR,
                         collected_at=datetime.now(timezone.utc).isoformat())
            json_file(raw,saved)
        rows,issues = normalize(sample,saved["http_status"],saved["body"])
        payload = saved["body"] if isinstance(saved["body"],dict) else {}
        entry.update(http_status=saved["http_status"],rt_cd=payload.get("rt_cd"),msg_cd=payload.get("msg_cd"),
                     msg1=payload.get("msg1"),collected_at=saved["collected_at"],raw_file=raw.name,
                     raw_sha256=sha(raw),actual_dates=[r["date"] for r in rows],issues=issues)
        if rows:
            entry["status"] = "일부 자료만 확보" if issues else "요청 범위 자료 확보"
            for row in rows:
                prices[ticker,row["date"]]=row
        if auth_error(saved["http_status"],payload):
            blocked = "KIS authentication or permission error; remaining live requests stopped"
        if not entry.get("reused_response") and not blocked:
            time.sleep(.25)
    if prices:
        write_csv(out/"kis_normalized.csv",list(prices.values()))
        manifest["normalized_sha256"] = sha(out/"kis_normalized.csv")
    by_ticker = {row["ticker"]:row["status"] for row in manifest["requests"]}
    comparison = []
    with (ROOT/"frozen_comparison.csv").open(encoding="utf-8") as stream:
        for original in csv.DictReader(stream):
            ticker,day = original["ticker"],original["trade_date"]
            candidate = prices.get((ticker,day.replace("-","")))
            fields = original["field"].split("/")
            for field,frozen in zip(fields,original["frozen_provider_krw"].split("/"),strict=True):
                value = candidate[field] if candidate else None
                comparison.append(dict(ticker=ticker,date=day,field=field,frozen_provider_krw=frozen,
                    kis_original_krw="" if value is None else value,
                    difference_krw="" if value is None else value-int(frozen),
                    sample_status=by_ticker[ticker],grade=candidate["grade"] if candidate else "미확보"))
    write_csv(out/"sample_price_comparison.csv",comparison)
    manifest["comparison_sha256"] = sha(out/"sample_price_comparison.csv")
    json_file(out/"run_manifest.json",manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    result = collect(parser.parse_args().out)
    for entry in result["requests"]:
        print(entry["ticker"],entry["status"],entry.get("reason",""))
    raise SystemExit(0 if all(r["status"]=="요청 범위 자료 확보" for r in result["requests"]) else 2)
