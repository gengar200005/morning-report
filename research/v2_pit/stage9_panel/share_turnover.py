"""Read only formation-date traded shares and listed shares for turnover-rate matching."""
import argparse
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path


def run(context, sources, archives, output):
    manifest = json.loads(sources.read_bytes())
    with context.open(newline='') as stream:
        selected = {}
        for row in csv.DictReader(stream):
            if row['sampled'] == '1':
                selected.setdefault(row['formation'], {})[row['code']] = row['isin']
    with output.open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['formation', 'isin', 'traded_shares', 'listed_shares'])
        for day, names in sorted(selected.items()):
            ref = manifest[day]
            raw = (archives / ref['krx']).read_bytes()
            if sha256(raw).hexdigest() != ref['sha256']:
                raise ValueError('Historical KRX archive has changed')
            snapshot, = (r for r in json.loads(gzip.decompress(raw))['records'] if r['date'] == day)
            rates = {}
            for r in snapshot['daily']:
                code = r['ISU_CD']
                if code not in names:
                    continue
                volume = int(r['ACC_TRDVOL'].replace(',', ''))
                shares = int(r['LIST_SHRS'].replace(',', ''))
                if code in rates or volume < 0 or shares <= 0:
                    raise ValueError('Invalid turnover inputs')
                rates[code] = (volume, shares)
            if rates.keys() != names.keys():
                raise ValueError('Missing formation holdings')
            for code, isin in sorted(names.items(), key=lambda kv: kv[1]):
                writer.writerow([day, isin, *rates[code]])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('context', 'sources', 'archives', 'output'):
        parser.add_argument(key, type=Path)
    run(**vars(parser.parse_args()))
