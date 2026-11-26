import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from stage82b.census_ledger import row_result


class CensusLedgerTest(unittest.TestCase):
    def setUp(self):
        self.r = dict(stock_code='123450', isin='KR-example', issuer_as_of='example', identity_status='PASS',
                      reason='checked', corp_code_candidate='00111111', receipt_candidate='20210517000001',
                      kind_receipt='20210517000099', filing_date='20210517')
        self.context = dict(sector_code='G1', sector_name='non-financial', financial='false')
        self.report = dict(receipt='20210517000001', corp_code='00111111', isin='KR-example',
                           kind_receipt='20210517000099', source_sha256='a'*64, source_url='official-source',
                           fields={f:dict(observed=True, current=v[0], prior=v[1])
                                   for f,v in [('revenue',(10,6)),('operating_profit',(-2,0))]})
        self.versions = {'00111111':[dict(type='original',receipt='20210517000001',filed='20210517')]}

    def evaluate(self, displays=None):
        return row_result(self.r,self.context,None,[self.report] if displays is None else displays,
                          {},['20210517','20210518','20210520'],self.versions)

    def test_later_amendment_preserves_original_and_same_day_is_withheld(self):
        self.versions['00111111'].append(dict(type='amendment_or_other',receipt='20210519000001',filed='20210519'))
        result=self.evaluate()
        self.assertEqual(result['F2_original_pair_QC'],'PASS')
        self.assertEqual(result['next_krx_session'],'20210518')
        self.assertEqual(result['first_next_filing_date_in_window'],'20210519')
        self.versions['00111111'][1]['filed']='20210517'
        self.assertNotEqual(self.evaluate()['F3_original_pair_QC'],'PASS')

    def test_disagreement_or_missing_keeps_null(self):
        alt={**self.report,'fields':{**self.report['fields'],'revenue':dict(observed=True,current=100,prior=6)}}
        result=self.evaluate([self.report,alt])
        self.assertEqual(result['revenue_raw_status'],'source_disagreement')
        self.assertIsNone(result['revenue_current_KRW'])
        self.assertIsNone(self.evaluate([])['revenue_current_KRW'])

    def test_nonpositive_and_unknown_financial_status(self):
        self.report['fields']['revenue']['current']=0
        self.assertEqual(self.evaluate()['F3_original_pair_QC'],'PASS')
        self.assertNotEqual(self.evaluate()['F2_original_pair_QC'],'PASS')
        self.context['financial']=''
        self.assertEqual(self.evaluate()['F3_original_pair_QC'],'industry_unknown')
        self.assertEqual(self.evaluate()['revenue_current_KRW'],0)

    def test_issuer_join_is_checked_even_for_existing_display(self):
        self.report['corp_code']='99999999'
        with self.assertRaisesRegex(ValueError,'another security'):
            self.evaluate()


class JuneAsOfTest(unittest.TestCase):
    def test_future_correction_no_carryback_and_missing_latest_no_fallback(self):
        from stage82b.census_asof import build
        with TemporaryDirectory() as directory:
            d=Path(directory)
            rows=[]
            for i in range(782):
                row=dict(isin=f'ISIN{i}',stock_code=str(i),issuer_as_of='issuer',corp_code=str(i),
                         identity_status='PASS',industry_group='nonfinancial',receipt='20210517000001',
                         next_krx_session='20210518',verified_original_version='True',original_filed='20210517',
                         xbrl_source_sha256='a'*64,display_source_sha256='')
                for f,v in [('revenue',100),('operating_profit',0)]:
                    row.update({f+'_current_KRW':v,f+'_prior_KRW':v,f+'_source_urls':'official',f+'_raw_status':'PASS'})
                rows.append(row)
            p=d/'ledger.csv'
            with p.open('w',newline='') as out:
                w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            versions=[
                dict(isin='ISIN0',receipt='20210517000001',start_session='20210518',stop_session_exclusive='20210602',version='original'),
                dict(isin='ISIN0',receipt='20210601000001',start_session='20210602',stop_session_exclusive=None,version='amendment_or_other'),
                dict(isin='ISIN1',receipt='20210531000001',filed='20210531',start_session='20210601',stop_session_exclusive=None,
                     version='amendment_or_other',sha256='b'*64,source='official',revenue=None,operating_profit=None)]
            (d/'updates.json').write_text(json.dumps({'bounded_version_rows':versions}))
            build(p,d/'updates.json',d/'observed.csv')
            with (d/'observed.csv').open() as f:obs=list(csv.DictReader(f))
            self.assertEqual(obs[0]['receipt'],'20210517000001')
            self.assertEqual(obs[0]['F2_status'],'PASS')
            self.assertEqual(obs[1]['receipt'],'20210531000001')
            self.assertEqual(obs[1]['F2_status'],'missing_revenue_pair')
            self.assertEqual(obs[1]['revenue_current_KRW'],'')
