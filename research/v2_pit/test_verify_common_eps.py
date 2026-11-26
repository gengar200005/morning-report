import unittest
from copy import deepcopy

from verify_common_eps import verify


def table(lines):
    return {'rows': [[{'text': value} for value in line] for line in lines],
            'preceding_paragraph': ''}


class VerifyCommonEpsTests(unittest.TestCase):
    def setUp(self):
        self.facts = {'receipt': '20210517000001', 'document': '121', 'corp': '00000001',
                      'archive_sha256': 'a' * 64,
                      'periods': {'current': ['2021-01-01','2021-03-31'],
                                  'prior_as_reported': ['2020-01-01','2020-03-31']}, 'fields': {}}
        for key, value in [('current','-7'), ('prior_as_reported','0')]:
            self.facts['fields'][key] = {'basic_common_eps': {
                'reason': 'common_share_class_requires_notes+per_share_unit_unverified',
                'candidates': [{'raw': value, 'nil': False, 'unit': 'shares'}]}}
        heading = table([['연결 포괄손익계산서'], ['제 4 기 1분기 2021.01.01 부터 2021.03.31 까지'],
                         ['제 3 기 1분기 2020.01.01 부터 2020.03.31 까지'], ['(단위 : 백만원)']])
        self.fs = table([['','제 4 기 1분기','제 3 기 1분기'], ['3개월','누적','3개월','누적'],
                         ['기본주당이익(손실) (단위 : 원)','(7)','(7)','0','0']])
        self.fs['rows'][0][1]['colspan'] = self.fs['rows'][0][2]['colspan'] = '2'
        self.note = table([['구 분','당분기','전분기'], ['가중평균 유통보통주식수','20','30'],
                           ['기본 보통주 주당이익(원)','(7)','0']])
        url = 'https://dart.fss.or.kr/report/viewer.do?rcpNo=20210517000001&dcmNo=121'
        self.display = {'receipt': self.facts['receipt'], 'source': 'public_dart_display',
                        'sections': [{'section': label, 'url': url, 'sha256': 'b'*64, 'tables': tables}
                                     for label,tables in [('2. 연결재무제표',[heading,self.fs]),
                                                          ('3. 연결재무제표 주석',[self.note])]]}

    def test_sign_zero_unit_source_and_timing(self):
        result = verify(self.facts, self.display)
        self.assertEqual((result['status'],result['current'],result['prior_as_reported']), ('PASS','-7','0'))
        self.assertEqual(result['xbrl_units'], ['shares'])
        self.assertEqual(result['first_publication'], 'UNASSESSED')
        self.assertIn('보통주', result['note_evidence'][0]['basis'])

    def test_rejects_other_measures_and_missing_currency(self):
        for label in ['우선주기본주당이익(원)', '기본및희석주당이익(원)', '희석주당이익(원)',
                      '계속영업보통주기본주당이익(원)', '중단영업보통주기본주당이익(원)', '기본주당이익']:
            with self.subTest(label=label):
                self.note['rows'][2][0]['text'] = label
                self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')

    def test_rejects_cross_period_or_ambiguous_comparison(self):
        for replacement in ['전기말','전년누적','직전분기','2020년2분기']:
            self.note['rows'][0][2]['text'] = replacement
            self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')
        self.note['rows'][0][2]['text'] = '전분기'
        self.fs['rows'][1][0]['text'] = '누적'
        self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')

    def test_rejects_conflicting_note_even_if_another_matches(self):
        bad = deepcopy(self.note)
        bad['rows'][2][2]['text'] = '12'
        self.display['sections'][1]['tables'].append(bad)
        self.assertEqual(verify(self.facts,self.display)['reason'], 'display_note_or_statement_differs_from_xbrl')

    def test_rejects_mismatched_scope_date_and_source(self):
        bad = deepcopy(self.display)
        bad['sections'][0]['tables'][0]['rows'][1][0]['text'] = '제4기1분기2020.01.01부터2020.03.31까지'
        self.assertEqual(verify(self.facts,bad)['status'], 'BLOCKED')
        for attribute,value in [('section','4. 재무제표 주석'), ('url',self.display['sections'][1]['url']+'2')]:
            bad = deepcopy(self.display)
            bad['sections'][1][attribute] = value
            self.assertEqual(verify(self.facts,bad)['status'], 'BLOCKED')

    def test_rejects_unknown_unit_nil_and_conflicting_xbrl(self):
        field = self.facts['fields']['current']['basic_common_eps']
        for item in [{'unit':'unrecognized','nil':False,'raw':'-7'}, {'unit':'shares','nil':True,'raw':'-7'},
                     {'unit':'shares','nil':False,'raw':'-8'}, {'unit':'shares','nil':False,'raw':'NaN'}]:
            field['candidates'].append(item)
            self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')
            field['candidates'].pop()

    def test_rejects_notes_based_on_continuing_operations_or_alien_denominator(self):
        self.note['preceding_paragraph'] = '당분기의 계속영업 기본주당이익'
        self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')
        self.note['preceding_paragraph'] = ''
        self.note['rows'][1][0]['text'] = '가중평균유통우선주식수'
        self.assertEqual(verify(self.facts,self.display)['status'], 'BLOCKED')
