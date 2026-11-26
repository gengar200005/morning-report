"""Reproduce the historical ordinary-share denominator from the March KRX snapshot."""
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

archive, output = map(Path, sys.argv[1:3])
raw = archive.read_bytes()
month = json.loads(gzip.decompress(raw))
record, = [record for record in month["records"] if record["date"] == "20210331"]
basic = record["basic"]
daily = record["daily"]
codes = {row["ISU_SRT_CD"] for row in basic}
if len(basic) != len(codes) or len(daily) != len(codes) or codes != {row["ISU_CD"] for row in daily}:
    raise ValueError("basic/daily code mismatch")
eligible = sorted(
    (row["ISU_SRT_CD"], row["ISU_CD"], row["ISU_ABBRV"]) for row in basic
    if row["MKT_TP_NM"] == "KOSPI" and row["SECUGRP_NM"] == "주권"
    and row["KIND_STKCERT_TP_NM"] == "보통주"
)
if len({row[1] for row in eligible}) != len(eligible):
    raise ValueError("duplicate eligible ISIN")
with output.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["stock_code", "isin", "issuer_as_of"])
    writer.writerows(eligible)
print("source sha256", hashlib.sha256(raw).hexdigest())
print("all", len(basic), "KOSPI common", len(eligible))
print("universe sha256", hashlib.sha256(output.read_bytes()).hexdigest())
