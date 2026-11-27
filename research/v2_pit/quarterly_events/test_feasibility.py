"""Regression tests for chronology, cutoffs, and the optimistic collection bound."""
import unittest
from datetime import date, timedelta

from feasibility import coverage_envelope, get_roster, schedule, signal_pair, standard_deadline


class EventPreflightTests(unittest.TestCase):
    def test_legal_roll_is_distinct_from_exchange_closure(self):
        self.assertEqual(standard_deadline(date(2020,6,30)), '20200814')
        self.assertEqual(standard_deadline(date(2021,6,30)), '20210817')
        self.assertEqual(standard_deadline(date(2021,3,31)), '20210517')

    def test_next_session_entry_and_end_censoring(self):
        start = date(2017,1,1)
        dates = [start+timedelta(days=i) for i in range((date(2022,1,1)-start).days)]
        sessions = [t.strftime('%Y%m%d') for t in dates if t.weekday()<5]
        all_forms = list(schedule(sessions))
        self.assertEqual(len(all_forms), 15)
        first = all_forms[0]
        self.assertEqual(first[3:5], ('20170516','20170517'))
        self.assertEqual(first[5][120], sessions[sessions.index(first[4])+119])
        self.assertIsNone(all_forms[-1][5][120])

    def test_actual_zero_and_missing_remain_distinct(self):
        self.assertEqual(signal_pair([0, 20], [0, 0]), ('-1',''))
        self.assertEqual(signal_pair([20, 20], [0, 0]), ('0','0'))
        self.assertEqual(signal_pair([20, 20], ['', '0']), ('0',''))
        self.assertEqual(signal_pair([20, 0], [0, 0]), ('',''))

    def test_no_new_receipt_can_supply_two_stock_quarters(self):
        actual=coverage_envelope(12,213)
        self.assertEqual(actual['marginal_cost_with_proxy'],159)
        self.assertEqual(actual['largest_denominator_at_80pct'],140)
        self.assertEqual(coverage_envelope(300,220)['potential_after_100'],240)

    def test_roster_is_independent_of_input_order_and_security_group(self):
        basic=[dict(ISU_CD=str(i),MKT_TP_NM='KOSPI',SECUGRP_NM='주권',KIND_STKCERT_TP_NM='보통주')
               for i in range(242)]
        preferred=dict(basic[0],ISU_CD='P',KIND_STKCERT_TP_NM='우선주')
        universe, chosen=get_roster(basic+[preferred])
        self.assertEqual(len(universe),242)
        self.assertEqual(len(chosen),240)
        self.assertEqual(chosen,get_roster(list(reversed(basic)))[1])
