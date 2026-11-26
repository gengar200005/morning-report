import unittest

from stage9_panel.q4_basis import annual_basis


def document(**periods):
    return {key: {'revenue_' + side: dict(value=value, status='exact', contexts=[side + key])
                  for side, value in zip(('current', 'prior'), pair) if value is not None}
            for key, pair in periods.items()}


class AnnualBasisTest(unittest.TestCase):
    def evaluate(self, *raw):
        return annual_basis(list(enumerate(raw)), 'revenue', (90, 72), (31, 27))

    def test_distinct_nonoverlapping_components_each_year(self):
        annual = document(first6=(50, None), third3=(40, 22), first3=(None, 25), second3=(None, 25))
        status, evidence = self.evaluate(annual)
        self.assertEqual(status, 'PASS')
        self.assertEqual(evidence['documents'][0]['sides']['current']['proofs'], ['first6+third3'])
        self.assertEqual(evidence['documents'][0]['sides']['prior']['proofs'], ['first3+second3+third3'])
        self.assertEqual(evidence['documents'][0]['sides']['prior']['observations']['first3']['contexts'], ['priorfirst3'])

    def test_separate_documents_cannot_combine_incomplete_annuals(self):
        self.assertEqual(self.evaluate(document(first9=(90, None)), document(first9=(None, 72)))[0], 'INSUFFICIENT')
        self.assertEqual(self.evaluate(document(first6=(60, 50), second3=(30, 22)))[0], 'INSUFFICIENT')

    def test_partial_direct_conflict_blocks_even_when_other_source_passes(self):
        ok = document(first9=(90, 72))
        for period, pair in [('first9', (None, 71)), ('3', (32, None))]:
            with self.subTest(period=period):
                self.assertEqual(self.evaluate(ok, document(**{period: pair}))[0], 'BLOCKED')
        ok['first6'] = {'revenue_prior': {'status': 'conflicting_values'}}
        self.assertEqual(self.evaluate(ok)[0], 'BLOCKED')

    def test_direct_quarter_mixed_with_prior_annual_interim(self):
        annual = document(first9=(None, 72), **{'3': (31, None)})
        self.assertEqual(self.evaluate(annual)[0], 'PASS')
        self.assertEqual(self.evaluate(document(first9=(90, 72)))[0], 'PASS')

    def test_contradictory_half_year_even_if_nine_and_fourth_are_consistent(self):
        annual = document(first9=(90, 72), first6=(50, 50), first3=(26, 24), second3=(28, 26))
        self.assertEqual(self.evaluate(annual)[0], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
