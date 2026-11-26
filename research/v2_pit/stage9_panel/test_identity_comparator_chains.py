from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from identity_comparator_chains import prove


class ComparatorChainTest(unittest.TestCase):
    def test_both_sources_must_select_their_own_receipt_and_verify_same_day_order(self):
        with TemporaryDirectory() as temporary:
            work=Path(temporary)
            (work/'raw').mkdir()
            original='20151116000001';amended='20151116000002'
            common=dict(period_end='20150930',report_type='11013',isin='isin',corp_code='12345678',filing_date='20151116',
                        dart_published='20151116',source_kind_sha256='h1',source_kind_export_sha256='h2',source_dart_sha256='h3')
            orig=dict(common,receipt=original,kind_receipt='k1',ordering_timestamp='2015-11-16 10:02')
            new=dict(common,receipt=amended,kind_receipt='k2',ordering_timestamp='2015-11-16 10:36')
            def write(receipt,selected):
                content='''<span onclick="openCorpInfoNew('12345678')"></span><select id="family">'''
                for rid,title in [(original,'분기보고서'),(amended,'[정정] 분기보고서')]:
                    chosen=' selected' if rid==selected else ''
                    content+=f'<option value="rcpNo={rid}"{chosen}>2015.11.16 {title}</option>'
                (work/'raw'/('fss-comparator-'+receipt+'-menu.html')).write_text(content+'</select>')
            write(original,original)
            self.assertEqual(prove(work,new,orig)['status'],'BLOCKED')
            write(amended,original)
            self.assertEqual(prove(work,new,orig)['status'],'BLOCKED')
            write(amended,amended)
            self.assertEqual(prove(work,new,orig)['status'],'PASS')
            self.assertEqual(prove(work,{**new,'ordering_timestamp':''},orig)['status'],'BLOCKED')
            self.assertEqual(prove(work,{**new,'corp_code':'00000001'},orig)['status'],'BLOCKED')

if __name__=='__main__':unittest.main()
