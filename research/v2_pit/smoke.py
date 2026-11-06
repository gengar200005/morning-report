"""One fixed, offline DB-to-V1 replay. Outputs are plumbing diagnostics."""
import argparse
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from foundation import digest

ENGINE_HASH = {
    'execution.py': '9c05e6d2d87f95623581b18d524613caffb922967e39bbac37f8330a03571ec3',
    'replay.py': '37cf6f84a2839baa01f1d5704e0e0e5661e0b2e452390af7fcd380d5d0e68658',
}
BANDS = ((0, 1), (2000, 5), (5000, 10), (20000, 50),
         (50000, 100), (200000, 500), (500000, 1000))
RISK = dict(stop_loss=.07, trail_stop=.10, max_hold_days=3, max_positions=1)


def run(database, engine):
    for name, sha in ENGINE_HASH.items():
        if digest(engine / name) != sha:
            raise ValueError('Preserved engine hash mismatch')
    sys.path.insert(0, str(engine.resolve()))
    from execution import QuoteRule
    from replay import Day, Quote, Replay

    # Predetermined issuer and window. The one candidate is observed at the first close.
    code = '005930'
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute(
            """SELECT s.day, p.isin, p.open, p.close, p.state FROM expected_sessions s
               LEFT JOIN execution_bars p ON p.day=s.day AND p.code=?
               WHERE s.day BETWEEN '20261001' AND '20261030' ORDER BY s.day""", (code,)
        ).fetchall()
    if not rows or len({r[1] for r in rows}) != 1 or rows[0][1] is None:
        raise ValueError('Smoke security not continuously identified')
    if any(r[4] != 'POSITIVE_VOLUME_VALID_BAR' for r in rows):
        raise ValueError('Smoke window requires valid raw bars')

    result = {}
    for mode in ('D1', 'D2'):
        account = Replay(mode, RISK, cooldown=0)
        for i, (day, isin, opening, close, _) in enumerate(rows):
            candidates = (SimpleNamespace(ticker=isin, rs=100, signal_i=0, extra={}),) if i == 1 else ()
            quotes = {}
            if i > 0:
                # Bounds are permissive for this integration check. The D2 cap comes from
                # yesterday's close. Actual auction bands and queue priority are separate.
                quotes[isin] = Quote(QuoteRule(1, 10**9, BANDS), rows[i-1][3], opening, close, True)
            account.step(Day(i, date.fromisoformat(day), quotes, candidates))
        fills = [e for e in account.book.log if e['event'] == 'filled']
        if [e['side'] for e in fills] != ['BUY', 'SELL'] or account.book.positions:
            raise ValueError(f'{mode}: expected one round trip')
        for fill in fills:
            fill_day = fill['time'].split()[0].replace('-', '')
            expected = next(r[2] for r in rows if r[0] == fill_day)
            if fill_day <= rows[0][0] or expected != fill['price'] or type(fill['quantity']) is not int:
                raise ValueError('Fill violated session, raw opening, or integer shares')
        result[mode] = {'signal_day': rows[0][0], 'sessions': len(rows), 'fills': fills}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('engine', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.database, args.engine), default=str, indent=2))
