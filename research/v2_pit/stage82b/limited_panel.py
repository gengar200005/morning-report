"""Freeze a 2017–21 probability sample using only historical membership and session dates."""
import argparse
import csv
import hashlib
import json
import sqlite3
from bisect import bisect_right
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

SALT = 'mr-v2-restricted-2017-21-v1|'
PER_MONTH = 240
READABLE = {'sessions': {'day'}, 'membership': {'day', 'isin', 'code', 'common'}}


def allow_membership(action, table, column, db, trigger):
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if column in READABLE.get(table, set()) else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def candidates(db):
    db.set_authorizer(allow_membership)
    days = [row[0] for row in db.execute(
        "SELECT min(day) FROM sessions WHERE day BETWEEN '20170101' AND '20211231' GROUP BY substr(day,1,6) ORDER BY 1"
    )]
    if len(days) != 60:
        raise ValueError('Incomplete 2017–21 session calendar')
    monthly = []
    for day in days:
        universe = list(db.execute("SELECT isin, code FROM membership WHERE day=? AND common=1 ORDER BY isin", (day,)))
        if len(universe) < PER_MONTH or len(set(isin for isin, _ in universe)) != len(universe):
            raise ValueError('Unusable historical common-stock universe')
        ordered = sorted(universe, key=lambda row: (hashlib.sha256((SALT+row[0]).encode()).digest(), row[0]))
        monthly.append((day, universe, ordered[:PER_MONTH]))
    return monthly


def size_estimate(monthly):
    # Only an enumeration budget for calendar quarters within the 180-day rule.
    # Fiscal year ends, correction versions and publication timing are not inferred here.
    ends = sorted(date(y,m,d) for y in range(2016,2022) for m,d in [(3,31),(6,30),(9,30),(12,31)])
    output = {}
    for index, key in [(1,'all_common'),(2,'limited')]:
        names = set()
        name_quarters = set()
        by_year = Counter()
        sizes = []
        for day, all_common, limited in monthly:
            group = all_common if index==1 else limited
            d = date.fromisoformat(day)
            relevant = ends[bisect_right(ends,d-timedelta(days=181)):bisect_right(ends,d)]
            sizes.append(len(group))
            for isin,_ in group:
                names.add(isin)
                by_year[day[:4]] += 1
                name_quarters.update((isin,q) for q in relevant)
        output[key] = {'distinct_isins':len(names), 'issuer_months':sum(sizes),
                       'minimum_month_size':min(sizes),'maximum_month_size':max(sizes),
                       'issuer_months_by_year':dict(by_year), 'possible_calendar_issuer_quarters':len(name_quarters)}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('members',type=Path)
    args=parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro&immutable=1', uri=True) as db:
        months=candidates(db)
    with args.members.open('w', newline='', encoding='utf-8') as stream:
        writer=csv.writer(stream,lineterminator='\n')
        writer.writerow(['formation','historical_isin','historical_code','sampling_rank','historical_population'])
        for day,all_common,selected in months:
            for rank,(isin,code) in enumerate(selected,1):
                writer.writerow([day,isin,code,rank,len(all_common)])
    result={'algorithm':'lowest SHA256 of fixed salt plus ISIN among each date’s KOSPI ordinary membership',
            'salt':SALT,'n_per_month':PER_MONTH,'months':len(months),'sample_sha256':hashlib.sha256(args.members.read_bytes()).hexdigest(),
            **size_estimate(months)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
