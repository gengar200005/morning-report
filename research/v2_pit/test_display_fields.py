import unittest

from stage82b.display_fields import extract_display_fields


def viewer(scope='CFS', date1='2021.01.01', date2='2020.01.01', sub=True, unit='천원'):
    heading = '연결' if scope == 'CFS' else ''
    header = ('<tr><th rowspan="2">과 목</th><th colspan="2">제 14 기 3분기</th>'
              '<th colspan="2">제 13 기 3분기</th></tr>'
              '<tr><th>3개월</th><th>누적</th><th>3개월</th><th>누적</th></tr>') if sub else (
              '<tr><th>과 목</th><th>제 14 기 3분기</th><th>제 13 기 3분기</th></tr>')
    revenue = '<td>1,200</td><td>9,900</td><td>900</td><td>7,300</td>' if sub else '<td>1,200</td><td>900</td>'
    profit = '<td>(1.5)</td><td>111</td><td>0</td><td>222</td>' if sub else '<td>(1.5)</td><td>0</td>'
    return f'''<p><a name="toc1">2. {heading}재무제표</a></p>
    <table><tr><td>{heading} 포괄손익계산서</td></tr>
    <tr><td>제14기 3분기 {date1}부터 2021.03.31까지</td></tr>
    <tr><td>제13기 3분기 {date2}부터 2020.03.31까지</td></tr>
    <tr><td>(단위 : {unit})</td></tr></table>
    <table>{header}<tr><td>수익(매출액)</td>{revenue}</tr>
    <tr><td>영업이익(손실)</td>{profit}</tr></table>'''.encode()


class DisplayFieldsTest(unittest.TestCase):
    def extract(self, raw, **kwargs):
        opts = dict(scope='CFS', period_end='2021-03-31', financial=False)
        return extract_display_fields(raw, **{**opts, **kwargs})['fields']

    def test_quarterly_not_cumulative_nondec_fiscal_and_scaled_loss(self):
        out = self.extract(viewer(date1='2020.07.01', date2='2019.07.01'))
        self.assertEqual(out['revenue']['current'], 1200000)
        self.assertEqual(out['revenue']['prior'], 900000)
        self.assertEqual(out['operating_profit']['current'], -1500)
        self.assertEqual(out['operating_profit']['prior'], 0)
        self.assertEqual(out['revenue']['status'], 'PASS')

    def test_missing_not_zero_and_conflicting_rows(self):
        out = self.extract(viewer().replace(b'<td>0</td>', b'<td>-</td>'))
        self.assertEqual(out['operating_profit']['status'], 'BLOCKED')
        self.assertIsNone(out['operating_profit']['prior'])
        duplicate = viewer()
        duplicate = duplicate[:-8] + '<tr><td>매출액</td><td>33</td></tr></table>'.encode()
        self.assertIsNone(self.extract(duplicate)['revenue']['current'])

    def test_currency_scope_and_fiscal_year_labels_checked(self):
        for raw in [viewer(unit='USD'), viewer(unit='원 / USD'), viewer(date2='2020.02.01'), viewer(scope='OFS'),
                    viewer().replace('제 13 기 3분기'.encode(), '제 12 기 3분기'.encode())]:
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.extract(raw)['revenue']['status'], 'BLOCKED')

    def test_exact_dated_single_columns_and_no_annual_substitution(self):
        self.assertEqual(self.extract(viewer(sub=False))['revenue']['prior'], 900000)
        self.assertIsNone(self.extract(viewer(sub=False, date1='2020.07.01', date2='2019.07.01'))['revenue']['current'])

    def test_standalone_kept_separate_financial_and_unclassified_quarantined(self):
        self.assertIsNone(self.extract(viewer(scope='OFS'), scope='OFS')['revenue']['current'])
        approved = self.extract(viewer(scope='OFS'), scope='OFS', standalone_confirmed=True)
        self.assertEqual(approved['revenue']['status'], 'PASS')
        for group in [True, None]:
            out = self.extract(viewer(), financial=group)
            self.assertEqual(out['revenue']['status'], 'BLOCKED')
            self.assertEqual(out['revenue']['current'], 1200000)

    def test_kind_boundaries_segregate_standalone_and_ignore_notes(self):
        from stage82b.display_fields import no_consolidated_statement

        markup = viewer(scope='OFS').decode().split('</p>', 1)[1]
        raw = f'''<html><body>
            <h3 class="SECTION-2"></h3><p class="SECTION-2">2. 연결재무제표</p>
            <p>당사는 본 보고서 제출 기준일 현재 연결재무제표 작성 대상에 해당되지 않습니다.</p>
            <h3 class="SECTION-2"></h3><p class="SECTION-2">3. 연결재무제표 주석</p>{markup}
            <h3 class="SECTION-2"></h3><p class="SECTION-2">4. 재무제표</p>{markup}
            <h3 class="SECTION-2"></h3><p class="SECTION-2">5. 재무제표 주석</p>{markup}
            </body></html>'''.encode()
        self.assertTrue(no_consolidated_statement(raw))
        self.assertIsNone(self.extract(raw)['revenue']['current'])
        self.assertEqual(self.extract(raw, scope='OFS', standalone_confirmed=True)['revenue']['prior'], 900000)
        # A missing section alone must never qualify for separate-only treatment.
        self.assertFalse(no_consolidated_statement(b'<html><body>empty</body></html>'))
