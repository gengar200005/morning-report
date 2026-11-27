"""Measure the portion of retained raw displays supporting an explicit absence of consolidation."""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

def run(archive, source, output):
    sys.path.insert(0, str(source.resolve()))
    from stage9_panel.coverage_limits import consolidated_amount_table
    from stage9_panel.pit_display import confirmed_absence
    source_types = {"kind_html", "dart_html"}
    examined = Counter()
    absent = defaultdict(list)
    conflicting = set()
    with ZipFile(archive) as stored:
        for member in stored.namelist():
            receipt, file = member.split("/")
            kind, fragment = file.split("-")
            if kind not in source_types:
                continue
            body = stored.read(member)
            digest = hashlib.sha256(body).hexdigest()
            if not digest.startswith(fragment.split(".")[0]):
                raise ValueError(f"Archive digest mismatch for {member}")
            examined[kind] += 1
            if confirmed_absence(body):
                absent[receipt].append((kind, digest))
            if consolidated_amount_table(body):
                conflicting.add(receipt)
    candidates = sorted(set(absent)-conflicting)
    rows = [(receipt, kind, digest) for receipt in candidates for kind,digest in absent[receipt]]
    output.mkdir(exist_ok=True, parents=True)
    with (output/"retained_explicit_no_cfs.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["receipt_from_member_path","display_kind","body_sha256"])
        writer.writerows(rows)
    result = dict(
        scope="Source-count only. Archive lacks the original full filing timeline, DART main menu provenance and 2018 final monthly PIT ledger. No firm-month status is inferred.",
        examined_displays=examined, receipts_with_absence=len(candidates), explicit_displays=len(rows),
        excluded_conflicting_receipts=sorted(set(absent)&conflicting),
        eligible_receipts_by_receipt_year=dict(sorted(Counter(r[:4] for r in candidates).items())),
        source_rows_by_kind=dict(Counter(kind for _,kind,_ in rows)),
        archive_last_receipt=max(s.split("/")[0] for s in stored.namelist()),
    )
    (output/"retained_structural.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("archive","source","output"):
        parser.add_argument(name,type=Path)
    run(**vars(parser.parse_args()))
