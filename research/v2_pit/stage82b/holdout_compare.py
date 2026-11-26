"""Compare the preregistered independent manual reads with frozen extractor output."""
import hashlib
import json
from pathlib import Path
import sys

def main():
    manual, automated, output = map(Path, sys.argv[1:4])
    audited = json.loads(manual.read_bytes())["rows"]
    records = json.loads(automated.read_bytes())
    by_isin = {row["isin"]: row for row in records}
    if len(records) != len(by_isin) or set(by_isin) != {row["isin"] for row in audited}:
        raise ValueError("Duplicate or missing holdout identity")
    results = []
    for item in audited:
        result = by_isin[item["isin"]]
        keys = {"stock_code": "stock_code", "sha256":"source_sha256", "kind_receipt":"kind_receipt",
                "dart_receipt_candidate":"receipt", "corp_code":"corp_code", "url":"source_url"}
        if any(item[key] != result[value] for key, value in keys.items()):
            raise ValueError("Source identity mismatch")
        expected_no_cfs = item["treatment"] == "no_consolidated_statement"
        has_facts = any(f.get("observed") for f in result["fields"].values())
        if result.get("explicit_no_cfs") != expected_no_cfs:
            raise ValueError("Incorrect scope or no-statement classification")
        if has_facts and (result["scope"]!="CFS" or result["periods"]!=[["2021-01-01","2021-03-31"],["2020-01-01","2020-03-31"]]):
            raise ValueError("Period or scope differs")
        for expected, field in (("revenue","revenue"),("op","operating_profit")):
            fact = result["fields"][field]
            reference = [item[expected+"_"+suffix] for suffix in ("current","prior")]
            observed = [fact.get(suffix) for suffix in ("current","prior")]
            results.append({"isin":item["isin"],"stock_code":item["stock_code"],"field":field,"expected":reference,
                            "observed":observed,"observed_field_status":fact["status"],"equal":observed==reference})
    unequal=[r for r in results if not r["equal"]]
    numeric=sum(r["expected"][0] is not None for r in results)
    output.write_text(json.dumps({
        "manual_sha256": hashlib.sha256(manual.read_bytes()).hexdigest(),
        "automated_sha256": hashlib.sha256(automated.read_bytes()).hexdigest(),
        "independent_source_confirmation": "same KIND original raw SHA, receipt, official URL, DART candidate and historical ISIN",
        "filings":len(audited),"numeric_pairs":numeric,"numeric_cells":numeric*2,
        "missing_pairs":len(results)-numeric,"mismatched_pairs":len(unequal),"details":results
    },ensure_ascii=False,indent=2)+"\n")
    if unequal:
        raise ValueError(f"{len(unequal)} manual mismatches")

if __name__=="__main__":
    main()
