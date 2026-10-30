import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import paper_trial as trial
NOW=datetime(2026,10,28,15,tzinfo=timezone.utc)
def candidate(ticker='TEST',ask=.2):
 return dict(ticker=ticker,contract_type='CALL',strike=5,expiry='2026-12-04',score=70,
             entry_bid=ask-.02,entry_ask=ask,contract_verified=True,quote_as_of=NOW.isoformat())
class TrialTests(unittest.TestCase):
 def test_fifty_cap_and_cash(self):
  s=trial.new_state(NOW)
  trial.accept_candidates(s,[candidate('X'+str(i)) for i in range(60)],NOW)
  self.assertEqual(len(s['signals']),50)
  self.assertEqual(sum(x['status']=='OPEN' for x in s['signals']),3)
  self.assertEqual(s['cash'],135.05)
  self.assertTrue(s['collection_finished'])
 def test_all_in_cap_and_dedup(self):
  s=trial.new_state(NOW)
  trial.accept_candidates(s,[candidate('BIG',.3),candidate(),candidate()],NOW)
  self.assertEqual(len(s['signals']),2)
  self.assertEqual(s['signals'][0]['reason'],'Above $30 all-in cap')
 def test_skip_insufficient_cash(self):
  s=trial.new_state(NOW);s['cash']=10
  trial.accept_candidates(s,[candidate()],NOW)
  self.assertEqual(s['signals'][0]['reason'],'Insufficient simulated cash')
 def test_exit_loss_and_zero_are_counted(self):
  s=trial.new_state(NOW);trial.accept_candidates(s,[candidate()],NOW)
  trial.close_positions(s,{'TEST':[dict(strike=5,expiry='2026-12-04',is_call=True,bid=0,ask=.01,quote_as_of=(NOW+timedelta(hours=1)).isoformat())]},NOW+timedelta(hours=1))
  self.assertEqual(s['signals'][0]['net_pnl'],-22.30)
  self.assertEqual(s['cash'],177.7)
 def test_missing_quote_not_a_profit(self):
  s=trial.new_state(NOW);trial.accept_candidates(s,[candidate()],NOW)
  trial.close_positions(s,{},NOW+timedelta(hours=1))
  self.assertEqual(s['signals'][0]['status'],'OPEN')
  self.assertIsNone(trial.update_status(s,NOW+timedelta(hours=1)))
 def test_expired_exit_unknown(self):
  s=trial.new_state(NOW);trial.accept_candidates(s,[candidate()],NOW)
  trial.close_positions(s,{},NOW+timedelta(days=45))
  self.assertEqual(s['signals'][0]['status'],'UNVERIFIED_EXIT')
 def test_loss_stop(self):
  s=trial.new_state(NOW)
  s['signals']=[dict(status='CLOSED',net_pnl=-60)]
  trial.update_status(s,NOW)
  self.assertTrue(s['collection_finished'])
 def test_frozen_rules(self):
  s=trial.new_state(NOW);s['rules']['starting_cash']=500
  with self.assertRaises(ValueError):trial.run(s,NOW)
 def test_missing_data_run_honest(self):
  s=trial.new_state(NOW)
  with patch.object(trial.quality,'spy_regime',return_value='BULLISH'),patch.object(trial.live,'WATCHLIST',['TEST']):
   r=trial.run(s,NOW,fetch_bars=lambda _: (None,None))
  self.assertEqual(r['qualifying_signals'],0)
  self.assertEqual(r['diagnostics']['stock_data_missing'],1)
  self.assertIsNone(r['net_realized_paper_pnl'])
if __name__=='__main__':unittest.main()
