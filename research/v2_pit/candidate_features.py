"""Stage 4 price-only PIT signals, shared by all economic scenarios."""
from collections import deque
from decimal import Decimal as D
import numpy as np

NAMES = ('A','B','C','D')


def ma200_pair(closes, i):
    """Two exact 200-session averages, with the latter lagged by 22 sessions."""
    if i<222 or i>=len(closes):
        raise ValueError('Insufficient history or missing signal close')
    return np.mean(closes[i-200:i]),np.mean(closes[i-222:i-22])


def build_features(db, days, market, end, candidates=NAMES):
    histories = {}
    out = {}
    market_history = deque(maxlen=61)
    for day in days:
        if day>end:
            break
        market_history.append(market[day])
        scores, entries, exits = [],{k:[] for k in candidates},{k:set() for k in candidates}
        for isin,code,index,momentum,link,volume in db.execute("""
            SELECT m.isin,p.code,m.price_index,m.momentum_252,m.link_status,p.volume
            FROM economic_momentum m JOIN execution_bars p USING(day,isin)
            WHERE m.day=? AND m.price_index IS NOT NULL""",(day,)):
            h = histories.setdefault(isin,deque(maxlen=253))
            if link!='CONTIGUOUS_RAW_RETURN':
                h.clear()
            h.append((index,volume))
            if len(h)<51:
                continue
            arr = np.asarray(h)
            c = arr[:,0]
            i = len(c)-1
            cur = c[i]
            ma50 = c[i-50:i].mean()
            ma150 = c[i-150:i].mean() if i>=150 else None
            ma200 = c[i-200:i].mean() if i>=200 else None
            for key,average in [('B',ma50),('C',ma150),('D',ma200)]:
                if key in exits and average is not None and cur<average:
                    exits[key].add(isin)
            if momentum is None or i!=252:
                continue
            blend = ((cur/c[i-126]-1)+momentum)/2
            scores.append((blend,isin,code))
            if 'B' in entries:
                high = c[:i].max()
                if cur>=high and volume>=1.5*arr[i-20:i,1].mean():
                    entries['B'].append((cur/high-1,isin,code))
            if 'C' in entries or 'D' in entries:
                now,lag = ma200_pair(c,i)
                if 'C' in entries and cur>ma50>ma150>now>lag:
                    entries['C'].append((momentum,isin,code))
                if 'D' in entries and cur>now>lag and blend>0:
                    entries['D'].append((blend,isin,code))
        if 'A' in entries or 'D' in entries:
            scores.sort(key=lambda x:(-x[0],x[2]))
        if 'A' in entries:
            entries['A'] = [r for r in scores[:5] if r[0]>0]
        if 'D' in entries:
            top = {r[1] for r in scores[:(len(scores)+4)//5]}
            gate = len(market_history)==61 and market_history[-1]>sum(list(market_history)[:-1])/60
            entries['D'] = [r for r in entries['D'] if gate and r[1] in top]
        if day>='20170110':
            out[day] = {k:([(isin,code) for _,isin,code in sorted(entries[k],key=lambda x:(-x[0],x[2]))],
                            exits[k]) for k in candidates}
    return out


class Policy:
    def __init__(self, name, features):
        self.name = name
        self.features = features
        self.month = None
        self.ordered_targets = ()
        self.targets = set()

    def entry_rows(self, day):
        return self.features[day][self.name][0]

    def prepare(self, day):
        if self.name!='A':
            return
        month = day[:6]
        if self.month!=month:
            self.month = month
            self.ordered_targets = self.entry_rows(day)
            self.targets = {t for t,_ in self.ordered_targets}

    def entries(self, day):
        if self.name=='A':
            self.prepare(day)
            return self.ordered_targets
        return self.entry_rows(day)

    def exit(self, day, isin, close, entry):
        if self.name=='A':
            self.prepare(day)
            return isin not in self.targets
        stop = D('.88') if self.name=='D' else D('.90')
        return isin in self.features[day][self.name][1] or close<=entry*stop
