"""Verify the retained market sample and receipt inventory without evaluating returns."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parent))
from stage82b.census_context import SECTORS, get_sectors
from stage82b.limited_panel import SALT, PER_MONTH


def digest(data):
    return sha256(data).hexdigest()


def market_check(archive):
    by_year, by_quarter = defaultdict(Counter), defaultdict(Counter)
    rebuilt = StringIO()
    writer = csv.writer(rebuilt, lineterminator='\n')
    writer.writerow(['formation','historical_isin','historical_code','sampling_rank','historical_population'])
    with ZipFile(archive) as z, TemporaryDirectory() as tmp:
        sources = json.loads(z.read('context_sources.json'))
        saved = z.read('limited_issuer_months.csv')
        context = z.read('context.csv')
        ctx = list(csv.DictReader(StringIO(context.decode())))
        lookup = {(r['formation'], r['isin']): r for r in ctx}
        seen = set()
        for day, meta in sorted(sources.items()):
            month = z.read('krx/' + meta['krx'])
            if digest(month) != meta['sha256']:
                raise ValueError('KRX hash mismatch ' + day)
            records = json.loads(gzip.decompress(month))['records']
            first = min(records, key=lambda r: r['date'])
            if first['date'] != day:
                raise ValueError('Incorrect formation ' + day)
            universe = [r for r in first['basic'] if (r['MKT_TP_NM'],r['SECUGRP_NM'],r['KIND_STKCERT_TP_NM']) == ('KOSPI','주권','보통주')]
            if len(universe) != len({r['ISU_CD'] for r in universe}) or len(universe) != meta['n']:
                raise ValueError('Membership mismatch ' + day)
            sector_path = Path(tmp) / day
            sector_path.mkdir()
            for sector in SECTORS:
                body = z.read(f'wics/{day}/{sector}.data')
                if digest(body) != meta['wics'][sector]:
                    raise ValueError('WICS hash mismatch ' + day + sector)
                (sector_path / (sector + '.data')).write_bytes(body)
            sectors = get_sectors(sector_path, day)
            ranked = sorted(universe, key=lambda r: (digest((SALT+r['ISU_CD']).encode()),r['ISU_CD']))
            for rank, row in enumerate(ranked, 1):
                isin, code = row['ISU_CD'], row['ISU_SRT_CD']
                seen.add((day, isin))
                item = lookup[day, isin]
                sector = sectors.get(code, ('',''))[0]
                industry = 'financial' if sector == 'G40' else ('nonfinancial' if sector else 'unknown')
                selected = rank <= PER_MONTH
                if (item['code'],item['sector_code'],item['industry_group'],int(item['sampled'])) != (code,sector,industry,int(selected)):
                    raise ValueError('Source/context mismatch ' + day + isin)
                if selected:
                    writer.writerow((day,isin,code,rank,len(universe)))
                    by_year[day[:4]][industry] += 1
                    by_quarter[f'{day[:4]}Q{(int(day[4:6])-1)//3+1}'][industry] += 1
        if len(seen) != len(ctx) or rebuilt.getvalue().encode() != saved:
            raise ValueError('Reconstructed sample differs')
        fixed = json.loads((STUDY.parent/'stage82b/limited_panel_summary.json').read_bytes())
        if digest(saved) != fixed['sample_sha256']:
            raise ValueError('Preregistered fingerprint differs')
    return dict(sample_sha256=digest(saved), context_sha256=digest(context), months=len(sources),
                krx_months=len(sources), wics_files=len(sources)*len(SECTORS), universe_firm_months=len(ctx),
                sample_rows=sum(sum(c.values()) for c in by_year.values()), eligible_by_year=by_year,
                eligible_by_formation_quarter=by_quarter)


def raw_check(archive, destination):
    counts = Counter()
    receipts = set()
    keys = set()
    pattern = re.compile(r'(\d{14})/([a-z_]+)-([a-f0-9]{16})\.(zip|html)')
    with ZipFile(archive) as z, destination.open('w', newline='') as out:
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(['receipt','kind','member','bytes','sha256'])
        for name in sorted(z.namelist()):
            match = pattern.fullmatch(name)
            if not match:
                raise ValueError('Unexpected member ' + name)
            receipt, kind, prefix, _ = match.groups()
            body = z.read(name)
            h = digest(body)
            if not h.startswith(prefix) or (receipt,kind) in keys:
                raise ValueError('Ambiguous archive member ' + name)
            keys.add((receipt,kind))
            receipts.add(receipt)
            counts[kind] += 1
            writer.writerow((receipt,kind,name,len(body),h))
    return dict(receipts=len(receipts), files=len(keys), formats=counts, first_receipt=min(receipts),
                last_receipt=max(receipts), manifest_sha256=digest(destination.read_bytes()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('market','raw','manifest','summary'):
        parser.add_argument(arg, type=Path)
    a = parser.parse_args()
    out = {'market':market_check(a.market), 'raw':raw_check(a.raw, a.manifest)}
    for key in ('market','raw'):
        with getattr(a,key).open('rb') as f:
            from hashlib import file_digest
            out[key]['archive_sha256'] = file_digest(f,'sha256').hexdigest()
    a.summary.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
