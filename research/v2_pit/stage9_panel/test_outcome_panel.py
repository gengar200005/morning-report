import csv
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

from outcome_summary import analyze, calendar, name_diagnostics
from outcome_run import build_market, csv_member, load_input, raw_etf
from types import SimpleNamespace


def weekdays(start,end):
    return [(start+timedelta(days=i)).strftime('%Y%m%d') for i in range((end-start).days+1)
            if (start+timedelta(days=i)).weekday()<5]


class PanelOutcomeTests(unittest.TestCase):
    def test_partial_and_overlapping_horizons_are_calendar_decisions(self):
        days=weekdays(date(2020,1,1),date(2021,12,31))
        months=['20200102','20210401','20210601','20211201']
        got=calendar(days,months)
        self.assertEqual([r['june_overlap'] for r in got],[False,True,True,False])
        self.assertIsNone(got[-1]['exits']['120'])
        self.assertEqual(got[-1]['entry'],'20211202')

    def test_reader_only_emits_training_dates_inside_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.zip'
            with ZipFile(path,'w') as z:
                z.writestr('rows.gz',gzip.compress(b'day,field\n20161230,pre\n20170102,ready\n20211201,last\n20220103,unused\n'))
            with ZipFile(path) as z:
                self.assertEqual([r['field'] for r in csv_member(z,'rows.gz')],['ready','last'])

    def test_benchmark_uses_same_endpoints_and_excludes_entry_day_distribution(self):
        days=weekdays(date(2016,9,1),date(2021,12,31))
        day='20170102'; ix=days.index(day); period=calendar(days,[day])[0]
        entry=period['entry'];end=period['exits']['20']
        stamps=[int(datetime.strptime(d,'%Y%m%d').replace(tzinfo=timezone.utc).timestamp()) for d in days]
        # Positive dividend on entry ex-date must be excluded; next ex-date belongs to holding.
        primary={'result':{'meta':{'symbol':'069500.KS'},'events':{},'timestamp':stamps,
                 'indicators':{'quote':[dict(open=[100]*len(days),close=[110]*len(days),volume=[100]*len(days))]}}}
        secondary={'code':200,'data':[dict(date=day[:4]+'-'+day[4:6]+'-'+day[6:],symbolCode='A069500',
                                         openingPrice=100,tradePrice=110,accTradeVolume=100)]}
        issuer={'dividList':[dict(stkTicker='069500',basicD=days[ix+2],dividA=9),
                            dict(stkTicker='069500',basicD=days[ix+3],dividA=2)]}
        with tempfile.TemporaryDirectory() as td:
            zpath=Path(td)/'bench.zip';inventory={'stage5':{'expected_input_hashes':{}},'benchmark':{'members':[]}}
            with ZipFile(zpath,'w') as z:
                for name,k,raw in [('inputs/yahoo_069500.json','etf',primary),('inputs/daum.json','secondary',secondary),
                                  ('inputs/issuer1.json',None,issuer)]:
                    b=json.dumps(raw).encode();z.writestr(name,b)
                    if k:inventory['stage5']['expected_input_hashes'][k]=hashlib.sha256(b).hexdigest()
                    rec=z.getinfo(name);inventory['benchmark']['members'].append(dict(member=name,size=rec.file_size,crc32=f'{rec.CRC:08x}'))
            refs=raw_etf(zpath,days,[period],inventory)
        self.assertEqual(refs[day,20][0],'up')
        self.assertAlmostEqual(refs[day,20][1],.1)
        self.assertAlmostEqual(refs[day,20][2],.12)

    def test_unapproved_gate_fails_before_missing_market_files_are_accessed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'gate.json';p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'gates'):
                load_input(SimpleNamespace(gate=p,release_outcomes=False))

    def test_fixed_sets_return_censor_and_full_membership_audit(self):
        days=weekdays(date(2020,12,1),date(2021,12,31))
        d='20210601';cal=calendar(days,[d]);entry=days.index(cal[0]['entry'])
        data={d:{'A':{'F2':1},'B':{'F2':2},'C':{'F2':None}}}
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE corporate_actions(isin,kind,status,effective_date,payment_or_delivery,terms);'
                             'CREATE TABLE exit_audit(isin,delisted);CREATE TABLE membership(day,isin);'
                             'CREATE TABLE execution_bars(day,isin,open,close,state);'
                             'CREATE TABLE krx_return_checks(day,isin,implied_reference_krw,rate_status);')
            for i in ['A','B']:
                for ix,day in enumerate(days[entry:entry+120]):
                    db.execute('INSERT INTO membership VALUES(?,?)',(day,i))
                    if i=='A' or ix>0:
                        db.execute("INSERT INTO execution_bars VALUES(?,?,100,100,'POSITIVE_VOLUME_VALID_BAR')",(day,i))
                        db.execute("INSERT INTO krx_return_checks VALUES(?,?,100,'PASS')",(day,i))
            db.execute("INSERT INTO exit_audit VALUES('B','20210701')")
            old={(d,'A',h):(0.,0.,'observed',0) for h in (20,60,120)}
            refs={(d,h):('up',0.,0.) for h in (20,60,120)}
            market,audit=build_market(db,data,['F2'],days,cal,{d:{'A':1}},old,refs)
        self.assertEqual(audit['checked_stage5_observations'],3)
        self.assertEqual(audit['additional_outside_M4'],3)
        self.assertEqual(market[d]['records'][120]['B'][2],'entry_unavailable')
        self.assertNotIn('C',market[d]['records'][120])
        self.assertEqual(data[d]['B']['subsequent_exit'],'within_development_after_formation')

    def test_analysis_preserves_unavailable_entries_and_inference_input(self):
        cal=[dict(formation='20170102',entry='20170103',exits={'20':'20170131','60':'20170320','120':'20170620'},june_overlap=False)]
        ds=cal[0]['formation'];names=[f'id{i:03d}' for i in range(55)]
        feats={k:{'F2':Decimal(i-3),'corp_code':f'{i:08d}','cap':i+100,'turnover':1000-i,'share_turnover':Decimal(i+1)/100,
                  'sector':'G45','industry_group':'nonfinancial','cap_quartile':'2'} for i,k in enumerate(names)}
        vals={k:(i/100,i/100+.01,'observed',0) if i else (None,None,'entry_unavailable',0) for i,k in enumerate(names)}
        m4={k:i for i,k in enumerate(names) if i%3}
        m={ds:{'signals':['F2'],'m4':m4,'records':{h:vals for h in (20,60,120)},'regime':'up',
               'benchmark':{h:(cal[0]['entry'],cal[0]['exits'][str(h)],0,.01) for h in (20,60,120)}}}
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            analyze(cal,{ds:feats},m,out)
            summary=json.loads((out/'summary.json').read_text())
            item=next(x for x in summary if x['slice']=='overall' and x['contrast']=='top-remainder' and x['horizon']==120)
            self.assertEqual(item['effects']['price']['n_months'],1)
            self.assertGreater(item['effects']['price']['mean'],0.)
            self.assertEqual(item['effects']['price']['positive_month_fraction'],1.)
            self.assertIn('matched_cap_share_turnover',item['effects'])
            joint=next(x for x in summary if x['slice']=='overall' and x['contrast']=='C-A' and x['horizon']==120)
            self.assertEqual(joint['effects']['price']['n_months'],0)
            with gzip.open(out/'inference_rows.csv.gz','rt') as stream: rows=list(csv.DictReader(stream))
            from statistics_panel import assignments
            _,observed,issuers=assignments(rows,{ds})
            self.assertIsNone(observed[ds,'id000'])
            self.assertEqual(issuers[ds,'id001'],'00000001')
            self.assertTrue(all(r['formation']==ds and len(r['corp_code'])==8 for r in rows))
            self.assertEqual(next(r for r in rows if r['isin']=='id000')['price'],'')
            self.assertEqual(json.loads((out/'monthly_detail.json').read_text())[0]['stats']['groups']['top']['n'],11)

    def test_leave_five_uses_original_dates_and_both_signs(self):
        records=[]
        for day in ('20170103','20180103'):
            for i,r in enumerate([.3,.2,.1,.03,.01,.22,.12,.09,.05,.01]):
                records.append({'isin':str(i),'formation':day,'eligible_month':True,'side':'target' if i<5 else 'comparison',
                                'price':r,'economic':r})
        diag=name_diagnostics(records)
        self.assertEqual([d['isin'] for d in diag['removed_by_primary_price']],['0','5','1','6','2'])
        self.assertEqual(diag['price']['after_leave5']['n_months'],2)
        self.assertEqual(diag['price']['leave_one_year']['2017']['n_months'],1)
