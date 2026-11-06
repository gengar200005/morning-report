from decimal import Decimal as D
import unittest

from economic_account import Account, reconcile_journal
from nav_lifecycle_audit import issue_history


class NavLifecycleTests(unittest.TestCase):
    def test_mark_recovery_preserves_unrelated_right_and_later_recovers_nav(self):
        a = Account(100)
        a.post('20190102','missing',block='mark')
        a.post('20190102','pending',block='right')
        day1 = a.snapshot('20190102',{})
        a.resolve_issue('20190103','mark','price observed')
        day2 = a.snapshot('20190103',{})
        a.resolve_issue('20190104','right','settlement confirmed',cash=D(3))
        day3 = a.snapshot('20190104',{})
        rows = [day1,day2,day3]
        self.assertEqual([r['nav'] for r in rows],[None,None,D(103)])
        reconcile_journal(100,a.log,rows,{r['day']:{} for r in rows})
        result = issue_history(dict(journal=a.log,daily=rows))
        self.assertEqual(result['continuation_only_null_days'],1)
        self.assertEqual([e['blocked_sessions'] for e in result['episodes']],[1,2])

    def test_invalid_resolution_does_not_change_cash(self):
        a = Account(100)
        with self.assertRaises(ValueError):
            a.resolve_issue('20190102','missing','payment',cash=D(5))
        self.assertEqual(a.cash,100)
        a.post('20190102','pending',block='right')
        with self.assertRaises(ValueError):
            a.resolve_issue('20190102','right',' ',cash=D(5))
        self.assertIn('right',a.unknown)


if __name__=='__main__':
    unittest.main()
