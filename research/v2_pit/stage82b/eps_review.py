"""Offline Q1 field QA using receipt-specific evidence from the existing eight-issuer audit."""
import argparse
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlencode

from lxml import html

from public_dart import PARAMS, ROOT, table_rows
from verify_common_eps import compact, rows, verify


def common_only_history(tables, quarter_end):
    """Require lifetime issuance as well as decreases and the quarter-end balance by class."""
    day = date.fromisoformat(quarter_end)
    allowed_dates = {day.strftime("%Y년%m월%d일"), day.strftime("%Y.%m.%d")}
    classes = [("보통주", "우선주"), ("보통주", "종류주식"), ("의결권있는보통주", "의결권없는우선주")]
    matches = []
    for number in range(1, len(tables)):
        body = rows(tables[number])
        header = rows(tables[number-1])
        if len(body) < 4 or body[0] != ["구분", "주식의종류", "비고"]:
            continue
        if (len(header) != 1 or len(header[0]) != 4 or header[0][0] != "(기준일:"
                or header[0][1] not in allowed_dates or header[0][2:] != [")", "(단위:주)"]):
            return None
        if len(body[1]) != 3 or tuple(body[1][:2]) not in classes or body[1][2] != "합계":
            return None
        values = {}
        for name, label in (("issued", "Ⅱ.현재까지발행한주식의총수"),
                            ("reduced", "Ⅲ.현재까지감소한주식의총수"),
                            ("balance", "Ⅳ.발행주식의총수(Ⅱ-Ⅲ)")):
            selected = [r for r in body if r and r[0] == label]
            if len(selected) != 1 or len(selected[0]) != 5:
                return None
            common, preferred, total = selected[0][1:4]
            # A dash in the class column alone proves nothing. Total must reconcile exactly.
            if preferred not in {"0", "-"}:
                return None
            if name == "reduced" and common == total == "-":
                values[name] = 0
                continue
            if not re.fullmatch(r"(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)", common) or common != total:
                return None
            values[name] = int(common.replace(",", ""))
        if values["issued"] <= 0 or values["balance"] <= 0 or values["issued"]-values["reduced"]!=values["balance"]:
            return None
        matches.append({"table":number,"header":body[1],"common_share_counts":values})
    return matches[0] if len(matches) == 1 else None


def shares_in_index(index, receipt, document):
    nodes = []
    for block in re.split(r"var node\d+\s*=\s*\{\s*\}\s*;", index.decode())[1:]:
        node = dict(re.findall(r"""node\d+\['(\w+)'\]\s*=\s*"([^"]*)"\s*;""", block))
        if re.fullmatch(r"\d+\.주식의총수등", compact(node.get("text",""))):
            if node.get("rcpNo") == receipt and node.get("dcmNo") == document:
                nodes.append((node["text"], ROOT+"/report/viewer.do?"+urlencode({k:node[k] for k in PARAMS})))
    if len(nodes) != 1:
        raise ValueError("Ambiguous receipt-specific share section")
    return nodes[0]


def fallback(facts, original, notes_raw, shares, shares_url, shares_label):
    if original["status"] != "BLOCKED" or original["reason"] != "no_eligible_quarterly_statement_and_common_share_note_pair":
        return original
    fs = original.get("statement_evidence", [])
    if not fs:
        return original
    # An unresolved note can contradict the face, including a continuing/discontinued split.
    # No share-table fallback is allowed when the consolidated notes discuss EPS in any form.
    notes = compact(html.fromstring(notes_raw.decode()).text_content())
    if re.search(r"주당|EPS|가중평균(?:유통)?(?:보통)?주식수|earningspershare", notes, re.I):
        return dict(original, reason="per_share_note_present_requires_explicit_reconciliation")
    share_history = common_only_history(table_rows(shares, shares_label), facts["periods"]["current"][1])
    if not share_history:
        return dict(original, reason="lifetime_common_only_issuance_not_proved")
    values = []
    for version in ("current","prior_as_reported"):
        c = facts["fields"][version]["basic_common_eps"]["candidates"]
        # verify() already enforced non-nil, finite, single-valued candidates and comparable units.
        values.append(Decimal(c[0]["raw"]))
    if any([Decimal(v) for v in evidence["values"]] != values for evidence in fs):
        return dict(original,reason="statement_differs_from_xbrl")
    return dict(original,status="PASS",reason="basic_face_and_xbrl_agree_with_lifetime_ordinary_only_issuance",
                current=str(values[0]),prior_as_reported=str(values[1]),economic_unit="KRW/share",
                share_evidence=dict(share_history,url=shares_url,sha256=sha256(shares).hexdigest()))


def replay(directory, facts_path, issuers_path, output):
    import csv
    with issuers_path.open(encoding="utf-8",newline="") as stream:
        issuers=list(csv.DictReader(stream))
    facts={f["receipt"]:f for f in json.loads(facts_path.read_bytes())}
    shares={r[0]:(r[1],r[2]) for r in json.loads((directory/"shares-evidence.json").read_bytes())}
    results=[]
    with sqlite3.connect(f"file:{directory/'pages.sqlite'}?mode=ro", uri=True) as db:
        def raw(url,digest):
            row=db.execute("SELECT body FROM page WHERE url=?",(url,)).fetchone()
            if not row or sha256(row[0]).hexdigest()!=digest:
                raise ValueError("Cached receipt bytes do not match")
            return row[0]
        for issuer in issuers:
            receipt=issuer["original_receipt"]
            if receipt not in facts:
                results.append(dict(receipt=receipt,stock_code=issuer["stock_code"],status="BLOCKED",reason="no_archived_xbrl_facts"))
                continue
            f=facts[receipt]
            d=json.loads((directory/(receipt+".json")).read_bytes())
            index=raw(d["index_url"],d["index_sha256"])
            section_bytes={}
            for section in d["sections"]:
                contents=raw(section["url"],section["sha256"])
                try:
                    generated=table_rows(contents,section["section"])
                except ValueError:
                    if section["tables"] or "해당사항없음" not in compact(html.fromstring(contents.decode()).text_content()):
                        raise
                    generated=[]
                if generated!=section["tables"]:
                    raise ValueError("Display table differs from archived bytes")
                section_bytes[compact(section["section"])]=contents
            original=verify(f,d)
            item=original
            if original.get("reason")=="no_eligible_quarterly_statement_and_common_share_note_pair":
                url,digest=shares[receipt]
                label,index_url=shares_in_index(index,receipt,f["document"])
                sb=(directory/(receipt+".shares.html")).read_bytes()
                if url!=index_url or sha256(sb).hexdigest()!=digest:
                    raise ValueError("Share source differs from original receipt")
                item=fallback(f,original,section_bytes["3.연결재무제표주석"],sb,url,label)
            results.append(dict(item,stock_code=issuer["stock_code"]))
    for row in results:
        row["reported_positive_base"]=row["status"]=="PASS" and Decimal(row["prior_as_reported"])>0
        row["same_receipt_growth"]=str(Decimal(row["current"])/Decimal(row["prior_as_reported"])-1) if row["reported_positive_base"] else None
        row["corporate_action_comparability"]="not_independently_certified"
        row["strategy_eligible"]=False
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("directory","facts","issuers","output"):
        ap.add_argument(arg,type=Path)
    args=ap.parse_args()
    replay(args.directory,args.facts,args.issuers,args.output)
