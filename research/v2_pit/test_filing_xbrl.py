import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from filing_xbrl import common_extensions, extract


IFRS = 'http://xbrl.ifrs.org/taxonomy/2019-03-27/ifrs-full'
SCHEME = 'http://dart.fss.or.kr/ifrs/CIK'
AXIS = '<d:explicitMember dimension="i:ConsolidatedAndSeparateFinancialStatementsAxis">i:ConsolidatedMember</d:explicitMember>'


def context(key, start='2021-07-01', end='2021-09-30', axis=AXIS, corp='00126380'):
    return (f'<context id="{key}"><entity><identifier scheme="{SCHEME}">{corp}</identifier></entity>'
            f'<period><startDate>{start}</startDate><endDate>{end}</endDate></period>'
            f'<scenario>{axis}</scenario></context>')


def fact(key, val, unit='currency', tag='i:Revenue', extra=''):
    return f'<{tag} contextRef="{key}" unitRef="{unit}" {extra}>{val}</{tag}>'


class FilingXbrlTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.archive = Path(directory.name) / 'sample.zip'

    def run_extract(self, contexts, facts, bad_hash=False, *, cumulative=False):
        xml = (f'<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:i="{IFRS}" '
               'xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:d="http://xbrl.org/2006/xbrldi" '
               'xmlns:u="urn:extension" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
               + contexts + '<unit id="currency"><measure>iso:KRW</measure></unit>'
               + '<unit id="shares"><measure>shares</measure></unit>'
               + '<unit id="perShare"><divide><unitNumerator><measure>iso:KRW</measure></unitNumerator>'
               + '<unitDenominator><measure>shares</measure></unitDenominator></divide></unit>'
               + facts + '</xbrl>')
        with ZipFile(self.archive, 'w') as z:
            z.writestr('instance.xbrl', xml)
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        return extract(self.archive, '20211115000001', '123', '00126380', 2021, 3,
                       'wrong' if bad_hash else digest, cumulative=cumulative)['fields']

    def test_consolidated_three_months_excludes_ytd_standalone_extra_dimensions(self):
        contexts = (context('quarter') + context('ytd', start='2021-01-01')
                    + context('prior', '2020-07-01', '2020-09-30')
                    + context('s', axis=AXIS.replace('i:ConsolidatedMember', 'i:SeparateMember'))
                    + context('dim', axis=AXIS + '<d:typedMember dimension="u:Class"><u:x/></d:typedMember>'))
        facts = ''.join(fact(c, v) for c, v in [('quarter', 0), ('prior', -2), ('ytd', 7), ('s', 4), ('dim', 5)])
        data = self.run_extract(contexts, facts)
        self.assertEqual(data['current']['revenue']['value'], '0')
        self.assertEqual(data['prior_as_reported']['revenue']['value'], '-2')
        self.assertIsNone(data['current']['operating_profit']['value'])

    def test_cumulative_period_separates_three_month_facts(self):
        contexts = (context('quarter') + context('ytd', start='2021-01-01')
                    + context('prior', '2020-01-01', '2020-09-30')
                    + context('standalone', start='2021-01-01', axis=AXIS.replace('i:ConsolidatedMember', 'i:SeparateMember')))
        amounts = fact('quarter', 11) + fact('ytd', 31) + fact('prior', 28) + fact('standalone', 88)
        data = self.run_extract(contexts, amounts, cumulative=True)
        self.assertEqual(data['current']['revenue']['value'], '31')
        self.assertEqual(data['prior_as_reported']['revenue']['value'], '28')
        self.assertEqual(data['current']['revenue']['reason'], 'exact_consolidated_calendar_ytd_fact')

    def test_duplicate_semantic_contexts_must_agree(self):
        contexts = context('a') + context('b')
        same = self.run_extract(contexts, fact('a', '2') + fact('b', '2.0'))
        self.assertEqual(same['current']['revenue']['status'], 'PASS')
        bad = self.run_extract(contexts, fact('a', '2') + fact('b', '3'))
        self.assertEqual(bad['current']['revenue']['reason'], 'conflicting_values')

    def test_eps_requires_share_class_even_with_proper_unit(self):
        for unit in ('shares', 'perShare'):
            with self.subTest(unit=unit):
                eps = self.run_extract(context('c'), fact('c', 24, unit, 'i:BasicEarningsLossPerShare'))['current']['basic_common_eps']
                self.assertIsNone(eps['value'])
                self.assertIn('common_share_class', eps['reason'])
                self.assertEqual('per_share_unit_unverified' in eps['reason'], unit == 'shares')
                self.assertEqual(eps['candidates'][0]['raw'], '24')

    def test_no_label_guess_missing_unit_or_nil_promotion(self):
        for bad in (fact('c', 11, tag='u:Revenue'), fact('c', 11, unit='missing'),
                    fact('c', 11, unit='shares'), fact('c', '', extra='xsi:nil="true"')):
            with self.subTest(fact=bad):
                self.assertIsNone(self.run_extract(context('c'), bad)['current']['revenue']['value'])

    def test_extension_label_filters_preferred_and_continuing_operations(self):
        labels = {'total': '보통주기본주당순이익(손실)', 'preferred': '우선주기본주당순이익(손실)',
                  'continuing': '계속영업 보통주기본주당순이익(손실)'}
        elements = []
        for key, label in labels.items():
            elements.append(f'<loc x:href="abc.xsd#entity00126380_{key}" x:label="loc_{key}"/>'
                            f'<label x:role="http://www.xbrl.org/2003/role/label" x:label="lab_{key}">{label}</label>'
                            f'<labelArc x:from="loc_{key}" x:to="lab_{key}"/>')
        linkbase = ('<linkbase xmlns="http://www.xbrl.org/2003/linkbase" xmlns:x="http://www.w3.org/1999/xlink">'
                    '<labelLink>' + ''.join(elements) + '</labelLink></linkbase>')
        with ZipFile(self.archive, 'w') as z:
            z.writestr('labels/lab_00126380-ko_2014.xml', linkbase)
        with ZipFile(self.archive) as z:
            self.assertEqual(common_extensions(z, '00126380'), {'total'})

    def test_rejects_wrong_entity_hash_and_duplicate_context(self):
        with self.assertRaisesRegex(ValueError, 'corporate identities'):
            self.run_extract(context('x', corp='00000000'), fact('x', 1))
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.run_extract(context('x'), fact('x', 1), bad_hash=True)
        with self.assertRaisesRegex(ValueError, 'context id'):
            self.run_extract(context('x') + context('x'), fact('x', 1))
