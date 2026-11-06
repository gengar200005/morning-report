from decimal import Decimal as D
import unittest

from economic_account import Account, VALID


class FullReplayTests(unittest.TestCase):
    def test_reserve_priority_release_and_missing_volume(self):
        days = ['20190102','20190103','20190104','20190107']
        book = Account(1000,days)
        book.queue(days[0],'A','BUY',100,6)
        book.queue(days[0],'B','BUY',100,6)
        self.assertEqual([o[-1] for o in book.orders],[6,3])
        self.assertEqual(book.reserved,D('901.8'))
        book.execute(days[1],days[3],{'A':(100,100,'ZERO_VOLUME'),'B':(100,100,VALID)},
                     volume={'A':0,'B':100},participation=D('.01'))
        self.assertEqual(book.reserved,0)
        self.assertEqual(book.buying_power,1000)
        self.assertEqual([x['event'] for x in book.log[-2:]],['opening_unavailable','volume_limit_unfilled'])

    def test_order_expires_after_next_session(self):
        days = ['20190102','20190103','20190104','20190107','20190108']
        book = Account(1000,days)
        book.queue(days[0],'A','BUY',100,5)
        book.execute(days[2],days[4],{'A':(90,90,VALID)})
        self.assertEqual(book.log[-1]['event'],'order_expired')
        self.assertEqual(book.reserved,0)
        self.assertFalse(book.shares)

    def test_tax_applied_on_actual_settlement_boundary(self):
        fixtures = [
            (['20190528','20190529','20190530','20190531','20190603'],'.30','.25'),
            (['20241224','20241226','20241227','20241230','20250102'],'.18','.15'),
            (['20251224','20251226','20251229','20251230','20260102'],'.15','.20'),
        ]
        for days,old,new in fixtures:
            for i,expected in ((0,old),(1,new)):
                with self.subTest(days=days,i=i):
                    book = Account(1000,days)
                    book.post(days[i],'starting_position',isin='A',shares=1)
                    book.queue(days[i],'A','SELL',1,1)
                    book.execute(days[i+1],days[i+3],{'A':(100,100,VALID)})
                    self.assertEqual(book.log[-1]['sell_tax'],D(expected))


if __name__=='__main__':
    unittest.main()
