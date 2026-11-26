from datetime import date
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from stage9_panel.pit_facts import dates_for
from stage9_panel.pit_ledger import filing_versions, one_row, receipt_amounts, derived_quarter


class AsOfLedgerTests(unittest.TestCase):
    days=['20181115','20190401','20191115','20200401','20201116','20210331','20210401','20210402',
          '20210503','20210504','20210517','20210518','20210601','20210701','20210702','20210802','20211001']
    member=dict(formation='20210601',historical_isin='A',historical_code='000111')
    good=dict(complete='1',stock_code='000111',start_date='20150101',end_date='20211201')
    def filing(self, receipt, end, filed, report='11013', origin=''):
        return dict(receipt=receipt,stock_code='000111',period_end=end,filing_date=filed,
                    version='amendment' if origin else 'original',original_receipt=origin or receipt,
                    identity_status='PASS',corp_code='00000001',report_type=report,document='123')
    def evidence(self, row, duration, rev, op, hashid='a'):
        fs={}
        for field,pair in [('revenue',rev),('operating_profit',op)]:
            for side,value in zip(('current','prior'),pair):
                fs[field+'_'+side]={'value':value}
        meta=dict(kind='xbrl',period=row['period_end'],doc='123',corp=row['corp_code'],sha=hashid*64)
        return meta,{str(duration):fs}
    def test_no_future_amendment_no_backfill_and_same_day_lag(self):
        orig=self.filing('orig','20210331','20210517')
        amend=self.filing('am','20210331','20210701',origin='orig')
        last=self.filing('ann','20201231','20210331','11011')
        old_edit=self.filing('a2','20201231','20210517','11011','ann')
        rows=[last,old_edit,orig,amend]
        cache={'orig':[self.evidence(orig,3,(200,100),(0,-10))]}
        record=one_row(self.member,'nonfinancial',rows,self.good,self.days,cache,{})
        self.assertEqual((record['receipt'],record['available_session'],record['F2'],record['F3']),('orig','20210518','10.0','1'))
        self.assertEqual(filing_versions(rows,'20210701',sessions=self.days)[0]['receipt'],'orig')
        late=one_row({**self.member,'formation':'20210802'},'nonfinancial',rows,self.good,self.days,cache,{})
        self.assertEqual((late['receipt'],late['F2'],late['F3']),('am','',''))
    def test_financial_stale_incomplete_and_field_independence(self):
        r=self.filing('r','20210331','20210517')
        sample={r['receipt']:[self.evidence(r,3,(0,50),(3,5))]}
        v=one_row(self.member,'nonfinancial',[r],self.good,self.days,sample,{})
        self.assertEqual((v['F2'],v['F3']),('','-1'))
        for grp in ['financial','unknown']:
            self.assertEqual(one_row(self.member,grp,[r],self.good,self.days,sample,{})['F3'],'')
        self.assertEqual(one_row(self.member,'nonfinancial',[r],{**self.good,'complete':'0'},self.days,sample,{})['identity_pass'],0)
        stale=one_row({**self.member,'formation':'20211001'},'nonfinancial',[r],self.good,self.days,sample,{})
        self.assertEqual(stale['reason'],'stale_latest_quarter')
        r.update(comparison_basis_status='BLOCKED',comparison_basis_reason='issuer_not_yet_established_for_full_prior_three_months')
        recent=one_row(self.member,'nonfinancial',[r],self.good,self.days,sample,{})
        self.assertEqual((recent['identity_pass'],recent['F3'],recent['F3_reason']),(1,'',r['comparison_basis_reason']))
    def test_uncertain_same_day_order_and_unlinked_amendment(self):
        orig=self.filing('o','20210331','20210517')
        first=self.filing('a','20210331','20210701',origin='o'); second={**first,'receipt':'b'}
        self.assertIsNone(filing_versions([orig,first,second],'20210802',sessions=self.days)[0])
        first['kind_timestamp']='2021-07-01 10:05';second['kind_timestamp']='2021-07-01 15:31'
        self.assertEqual(filing_versions([orig,first,second],'20210802',sessions=self.days)[0]['receipt'],'b')
        bad={**second,'original_receipt':'other'}
        self.assertEqual(filing_versions([orig,bad],'20210802',sessions=self.days)[1],'unlinked_amendment')
    def test_attachment_only_scope_requires_proven_parent(self):
        original=self.filing('main','20210331','20210517')
        attachment={**self.filing('annex','20210331','20210518',origin='main'),
                    'amendment_scope':'nonfinancial_attachment_only','main_receipts_at_event':'main',
                    'source_fss_viewer_sha256':'b'*64}
        version,status=filing_versions([original,attachment],'20210601',sessions=self.days)
        self.assertEqual((status,version['receipt'],version['nonfinancial_attachment_receipts']),('PASS','main','annex'))
        attachment['amendment_scope']='financial_attachment_only'
        result=one_row(self.member,'nonfinancial',[original,attachment],self.good,self.days,{}, {})
        self.assertEqual((result['identity_pass'],result['receipt'],result['reason']),(1,'annex','financial_attachment_comparison_unverified'))

    def test_precalendar_evidence_only_for_prior_component(self):
        r={**self.filing('r','20150930','20151112'),'identity_status':'BLOCKED',
           'comparator_identity_status':'PASS','comparator_identity_basis':'cross-index plus historical security'}
        self.assertEqual(filing_versions([r],'20210601',sessions=self.days)[1],'unverified_receipt_identity')
        self.assertEqual(filing_versions([r],'20210601',sessions=self.days,reference_only=True)[1],'PASS')
        # FY comparators may finish before the master begins but be filed during the verified calendar.
        r.update(period_end='20151231',filing_date='20160330')
        self.assertEqual(filing_versions([r],'20210601',sessions=['20160104',*self.days],reference_only=True)[1],'PASS')

    def test_reference_amendment_needs_explicit_original_and_cross_indexes(self):
        base=self.filing('o','20151231','20160330');base.update(identity_status='BLOCKED',
            comparator_identity_status='PASS',comparator_identity_basis='confirmed historical comparator')
        amendment={**base,'receipt':'a','version':'amendment','filing_date':'20160524','original_receipt':'',
            'dart_title':'[기재정정]사업보고서 (2015.12)','kind_title':'[정정]사업보고서(2015.12)',
            'source_kind_sha256':'a'*64,'source_dart_sha256':'b'*64}
        args=([base,amendment],'20210601')
        self.assertNotEqual(filing_versions(*args,sessions=self.days,reference_only=True)[1],'PASS')
        amendment.update(comparator_original_receipt='o',comparator_chain_basis='confirmed original in both sources')
        chosen,status=filing_versions(*args,sessions=self.days,reference_only=True)
        self.assertEqual((status,chosen['receipt'],chosen['original_receipt']),('PASS','a','o'))
        self.assertNotEqual(filing_versions(*args,sessions=self.days)[1],'PASS')
        amendment['dart_title']='[첨부정정]사업보고서 (2015.12)'
        self.assertNotEqual(filing_versions(*args,sessions=self.days,reference_only=True)[1],'PASS')

    def test_multiple_sources_cannot_override_disagreement(self):
        r=self.filing('r','20210331','20210517')
        cache={'r':[self.evidence(r,3,(110,100),(2,1)),self.evidence(r,3,(111,100),(2,1),'b')]}
        self.assertEqual(receipt_amounts(cache,r,3,'revenue')[2],'source_disagreement')
        self.assertEqual(receipt_amounts(cache,r,3,'operating_profit')[0],(2,1))
        cache['r'][1][1]['3']['revenue_prior'].clear()
        self.assertEqual(receipt_amounts(cache,r,3,'revenue')[2],'source_disagreement')
        cache['r'][1][1]['3']['revenue_current']['value']=110
        self.assertEqual(receipt_amounts(cache,r,3,'revenue')[0],(110,100))
    def test_q4_delta_both_years_and_sources_versions(self):
        rows=[self.filing('annual','20201231','20210331','11011'),
              self.filing('nine','20200930','20201115'),
              self.filing('prevannual','20191231','20200331','11011'),
              self.filing('prevnine','20190930','20191114')]
        cache={}
        for r,months,pair in zip(rows,[12,9,12,9],[(120,100),(85,70),(100,90),(70,65)]):
            cache[r['receipt']]=[self.evidence(r,months,pair,(1,1))]
        # The previously filed annual and nine-month originals need only that year's current amount.
        cache['prevannual'][0][1]['12'].pop('revenue_prior')
        cache['prevnine'][0][1]['9'].pop('revenue_prior')
        args=rows,rows[0],'20210601',self.days,cache,{},'revenue'
        value,detail,why=derived_quarter(*args)
        self.assertEqual((value,detail['arithmetic_pair'],why),(None,(35,30),'arithmetic_only_basis_unverified'))
        cache['annual'][0][1]['first9']=cache['nine'][0][1]['9']
        self.assertEqual(derived_quarter(*args)[0],(35,30))
        cache['nine'][0][1]['9']['revenue_prior']['value']=69
        self.assertEqual(derived_quarter(*args)[2],'prior_comparator_restated_or_inconsistent')
    def test_cumulative_display_dates_column_and_units(self):
        from stage9_panel.pit_display import cumulative_facts
        from test_display_fields import viewer
        raw=viewer(date1='2020.07.01',date2='2019.07.01')
        intervals=((date(2020,7,1),date(2021,3,31)),(date(2019,7,1),date(2020,3,31)))
        out=cumulative_facts(raw,9,intervals)
        self.assertEqual((out['revenue_current']['value'],out['operating_profit_prior']['value']),(9900000,222000))
        self.assertFalse(cumulative_facts(raw,12,intervals))
        self.assertFalse(cumulative_facts(viewer(),9,intervals))
        named=raw.decode().replace('3개월','당3분기',1).replace('3개월','전3분기(검토받지 않은 재무제표)',1).encode()
        quarters=((date(2021,1,1),date(2021,3,31)),(date(2020,1,1),date(2020,3,31)))
        self.assertEqual(cumulative_facts(named,3,quarters)['revenue_current']['value'],1200000)
        self.assertEqual(cumulative_facts(named,9,intervals)['revenue_current']['value'],9900000)
        self.assertFalse(cumulative_facts(named.replace('당3분기'.encode(),'당2분기'.encode()),3,quarters))

    def test_explicit_whole_section_absence_rejects_future_and_conflicting_narrative(self):
        from stage9_panel.pit_display import confirmed_absence
        def viewer(sentence):
            return ('<html><body><p><a name="toc1">2. 연결재무제표</a></p><p>'+sentence+'</p></body></html>').encode()
        exact='회사는 한국채택국제회계기준에 의한 연결대상이 없어 연결재무제표를 작성하지 않습니다.'
        self.assertTrue(confirmed_absence(viewer(exact)))
        self.assertTrue(confirmed_absence(viewer('▶ 해당사항 없음.')))
        for text in ('-', '', '연결재무제표를 작성하지 않을 예정입니다.',exact+' 단, 전년도 연결실적은 아래 표와 같습니다.'):
            self.assertFalse(confirmed_absence(viewer(text)))

    def test_quarantine_revokes_cached_source(self):
        import csv
        import sqlite3
        from stage9_panel.pit_facts import index_facts
        from test_display_fields import viewer
        raw=viewer()
        with tempfile.TemporaryDirectory() as workspace:
            root=Path(workspace); packages=root/'raw.db'; facts=root/'facts.db'; filings=root/'filings.csv'
            with sqlite3.connect(packages) as db:
                db.execute('CREATE TABLE packages(receipt TEXT,kind TEXT,corp TEXT,document TEXT,sha256 TEXT,source TEXT,body BLOB)')
                db.execute('INSERT INTO packages VALUES (?,?,?,?,?,?,?)',('r','kind_html','1','22',sha256(raw).hexdigest(),'official',raw))
            with filings.open('w',newline='') as output:
                writer=csv.writer(output);writer.writerow(['receipt','corp_code','period_end','document'])
                writer.writerow(['r','1','20210331',''])
            self.assertEqual(index_facts(packages,filings,facts)['new'],1)
            with sqlite3.connect(packages) as db:
                db.execute('CREATE TABLE quarantine(receipt TEXT,kind TEXT,reason TEXT)')
                db.execute("INSERT INTO quarantine VALUES ('r','kind_html','unreconciled source conflict')")
            self.assertEqual(index_facts(packages,filings,facts)['quarantined'],1)
            with sqlite3.connect(facts) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM facts').fetchone()[0],0)

    def test_calendar_periods_cross_year_and_leap_day(self):
        self.assertEqual(dates_for(date(2020,2,29),3,True),('2018-12-01','2019-02-28'))
        self.assertEqual(dates_for(date(2021,3,31),9),('2020-07-01','2021-03-31'))
