"""Reproduce the preregistered March 2021 blind holdout from KRX snapshots and the filing title index."""
import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))

def last_session(path):
    return max(json.loads(gzip.decompress(path.read_bytes()))["records"], key=lambda d: d["date"])

def main():
    march, later, qc, index, output = map(Path, sys.argv[1:])
    day = last_session(march)
    assert day["date"] == "20210331"
    skip = {"005930", "066570", "000660", "117930", "002000"}
    skip.update(r["stock_code"] for r in read_csv(qc))
    surviving = {r["ISU_CD"] for r in last_session(later)["basic"]}
    amended = {r["dart_display_name"] for r in read_csv(index) if r["type"] != "original"}
    caps = {r["ISU_CD"]:int(r["MKTCAP"]) for r in day["daily"]}
    candidates = []
    for row in day["basic"]:
        if (row["MKT_TP_NM"],row["SECUGRP_NM"],row["KIND_STKCERT_TP_NM"])!=("KOSPI","주권","보통주"):
            continue
        isin, code = row["ISU_CD"], row["ISU_SRT_CD"]
        if code in skip:
            continue
        rank = hashlib.sha256(("MR-v2-82b-holdout-1:"+isin).encode()).hexdigest()
        candidates.append(dict(stock_code=code, isin=isin, issuer=row["ISU_ABBRV"], cap=caps[code], rank=rank))
    candidates.sort(key=lambda r:(r["cap"],r["isin"]))
    for i,r in enumerate(candidates):
        r["quartile"] = 1+i*4//len(candidates)
    candidates.sort(key=lambda r:r["rank"])
    draws=[]
    def draw(rows,label,n=1):
        chosen={r["isin"] for r in draws}
        fresh=[r for r in rows if r["isin"] not in chosen][:n]
        assert len(fresh)==n
        draws.extend(dict(r, stratum=label) for r in fresh)
    for quartile in range(1,5):draw([r for r in candidates if r["quartile"]==quartile], f"cap_Q{quartile}",2)
    draw([r for r in candidates if re.search(r"은행|금융|증권|보험|생명|화재|손해",r["issuer"])],"financial_name")
    draw([r for r in candidates if r["isin"] not in surviving],"absent_by_202305")
    draw([r for r in candidates if r["issuer"] in amended],"amendment_index")
    with output.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(draws[0]))
        writer.writeheader();writer.writerows(draws)
    print(len(candidates),len(draws),hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == "__main__":
    main()
