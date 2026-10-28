import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import backtest_review as review
import scanner_quality as quality
import scanner
import live_scanner

NOW = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)

def signal(**kw):
    s = dict(signal_id='test', scanner='live', ticker='TEST', contract_type='CALL',
             pushed=True, contract_verified=True, expiry='2026-12-04', strike=5.0,
             entry_bid=.18, entry_ask=.20, ts=NOW.isoformat(), price=4.0, score=70)
    s.update(kw)
    return s


def quote(days, bid, **kw):
    q = dict(signal_id='test', ts=(NOW + timedelta(days=days)).isoformat(),
             bid=bid, ask=bid+.02, expiry='2026-12-04', strike=5.0, contract_type='CALL')
    q.update(kw)
    return q


class ReviewTests(unittest.TestCase):
    def evaluate(self, s=None, quotes=None, **kw):
        return review.evaluate_signal(s or signal(), quotes or [], as_of=NOW+timedelta(days=10), **kw)

    def test_legacy_estimates_not_money(self):
        r = self.evaluate(signal(contract_verified=False, est_cost=.10))
        self.assertEqual(r['review_outcome'], 'UNVERIFIED')
        self.assertIsNone(r['pnl'])

    def test_stop_before_later_winner(self):
        r = self.evaluate(quotes=[quote(1,.07),quote(2,.40)])
        self.assertEqual(r['exit_reason'], 'STOP')
        self.assertAlmostEqual(r['pnl'], -14.30)

    def test_target_first_and_fees(self):
        r = self.evaluate(quotes=[quote(1,.31),quote(2,0)])
        self.assertEqual(r['exit_reason'], 'TARGET')
        self.assertAlmostEqual(r['pnl'], 9.70)

    def test_put_uses_contract_quotes(self):
        r = self.evaluate(signal(contract_type='PUT'), [quote(1,.31,contract_type='PUT')])
        self.assertEqual(r['review_outcome'], 'WIN')

    def test_zero_exit(self):
        self.assertAlmostEqual(self.evaluate(quotes=[quote(1,0)])['pnl'], -21.30)

    def test_mismatched_contract_ignored(self):
        self.assertIsNone(self.evaluate(quotes=[quote(1,.4,strike=6)])['pnl'])

    def test_future_and_prior_quotes_ignored(self):
        self.assertIsNone(self.evaluate(quotes=[quote(-1,.4),quote(11,.4)])['pnl'])

    def test_missing_exit_not_flattering_flat(self):
        self.assertEqual(self.evaluate()['review_outcome'], 'UNVERIFIED')

    def test_immature_stays_open(self):
        r=review.evaluate_signal(signal(),[],as_of=NOW+timedelta(days=1))
        self.assertEqual(r['review_outcome'],'OPEN')

    def test_horizon_uses_observable_bid(self):
        r=self.evaluate(quotes=[quote(3,.19),quote(7,.18)])
        self.assertEqual(r['exit_reason'],'TIME_EXIT')
        self.assertAlmostEqual(r['pnl'],-3.30)

    def test_expired_missing_quote_not_invented_zero(self):
        self.assertIsNone(self.evaluate(signal(expiry='2026-10-30'))['pnl'])

    def test_short_put_not_long_option(self):
        self.assertIsNone(self.evaluate(signal(contract_type='PUT_SELL'))['pnl'])

    def test_invalid_quote(self):
        self.assertIsNone(self.evaluate(quotes=[quote(1,.4,ask=.3),quote(2,float('nan'))])['pnl'])

    def test_duplicate_review_and_drawdown(self):
        r=review.review([signal(),signal()],[quote(1,.31)],NOW+timedelta(days=3))
        self.assertEqual(r['summary']['signals_reviewed'],1)
        rows=[dict(review_outcome='WIN',pnl=10,exit_ts='2026-10-01',scanner='a'),
              dict(review_outcome='LOSS',pnl=-15,exit_ts='2026-10-02',scanner='a')]
        self.assertEqual(review.summarize(rows)['closed_trade_drawdown'],15)


class QualityTests(unittest.TestCase):
    def evaluate(self, earnings=False, real=True):
        contract=dict(strike=5,expiry='2026-12-04',delta=.3,iv=.5,oi=200,
                      mid=.19,bid=.18,ask=.20,spread_pct=.105,tte_days=37)
        with patch.object(quality,'has_earnings_within',return_value=earnings), \
             patch.object(quality,'iv_rank',return_value=40), \
             patch.object(quality,'target_delta_strike',return_value=contract if real else None):
            return quality.evaluate_long_signal(signal(),'BULLISH')

    def test_missing_earnings_blocks(self):
        self.assertFalse(self.evaluate(earnings=None)[1])

    def test_earnings_blackout(self):
        self.assertFalse(self.evaluate(earnings=True)[1])

    def test_missing_chain_blocks(self):
        self.assertFalse(self.evaluate(real=False)[1])

    def test_good_quote_records_exact_contract(self):
        s,ok,_=self.evaluate()
        self.assertTrue(ok)
        self.assertEqual(s['entry_ask'],.20)
        self.assertEqual(s['strike'],5)

    def test_missing_module_blocks(self):
        with patch.object(scanner,'sq',None):
            self.assertFalse(scanner.enrich_and_filter(signal(),'BULLISH')[1])
        with patch.object(live_scanner,'sq',None):
            self.assertFalse(live_scanner._enrich_live(signal(),'BULLISH')[1])

    def test_one_sided_crossed_quotes_not_liquid(self):
        for bid,ask in [(0,.2),(.3,.2),(float('nan'),.2)]:
            self.assertFalse(quality.is_liquid(dict(bid=bid,ask=ask,oi=200,spread_pct=.1)))

    def test_contract_selection_budget_expiry_liquidity(self):
        expiry=(datetime.now(timezone.utc).date()+timedelta(days=35)).isoformat()
        chain=[dict(expiry=expiry,strike=5,is_call=True,bid=.48,ask=.50,oi=200,volume=10),
               dict(expiry=expiry,strike=6,is_call=True,bid=.18,ask=.20,oi=200,volume=10),
               dict(expiry=expiry,strike=7,is_call=True,bid=0,ask=.10,oi=200,volume=10)]
        with patch.object(quality,'_fetch_nasdaq_chain',return_value=chain), \
             patch.object(quality,'_implied_vol',return_value=.5), \
             patch.object(quality,'_bs_delta',return_value=.3):
            self.assertEqual(quality.target_delta_strike('TEST',4,35,'CALL')['strike'],6)


if __name__ == '__main__': unittest.main()
