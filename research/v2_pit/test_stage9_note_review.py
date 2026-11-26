import unittest
from lxml import html
from stage9_panel.q4_note_review import consolidated_notes, scope, segment


def table(rows, unit='원'):
    body = ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows)
    return html.fromstring(f'<div><p>(단위: {unit})</p><table>{body}</table></div>').xpath('//table')[0]


class ReviewedNotesTest(unittest.TestCase):
    def test_segment_bridge_and_unit(self):
        rows = [['구분', '사업1', '사업2', '조정 및 제거', '합계'], ['영업손익', '86', '17', '(-)3', '100']]
        self.assertEqual(segment(table(rows), 'operating_profit'), ({'사업1':86,'사업2':17,'조정및제거':-3}, 100))
        with self.assertRaisesRegex(ValueError, 'KRW'):
            segment(table(rows, '백만원'), 'operating_profit')
        rows[1][-1] = '101'
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            segment(table(rows), 'operating_profit')

    def test_only_consolidated_note_section_is_available(self):
        doc = html.fromstring('<html><body><p class="SECTION-2">3. 연결재무제표 주석</p>'
                              '<p>연결기업 정책</p><table><tr><td>연결부문</td></tr></table>'
                              '<p class="SECTION-2">4. 재무제표</p><p>별도기업 정책</p></body></html>')
        text, tables = consolidated_notes(doc)
        self.assertIn('연결기업정책', text)
        self.assertNotIn('별도기업정책', text)
        self.assertEqual(len(tables), 1)

    def test_entity_roster_requires_each_identifiable_name(self):
        rows = [['상호','설립일','지배관계 근거'],['회사1','2001.01','의결권 과반수']]
        self.assertEqual(len(scope(table(rows))), 1)
        with self.assertRaisesRegex(ValueError, 'roster'):
            scope(table(rows + rows[1:]))
