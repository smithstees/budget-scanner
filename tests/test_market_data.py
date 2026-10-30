import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import market_data as data
import paper_trial as trial
import live_scanner as live
import scanner_quality as quality
from test_paper_trial import NOW, candidate

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = patch.object(data, 'CACHE', Path(self.temp.name)); self.cache.start()
        self.addCleanup(self.cache.stop)
        self.sleep = patch.object(data.time, 'sleep'); self.sleep.start(); self.addCleanup(self.sleep.stop)
        data.reset_events()

    def response(self, payload):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return response

    def test_rate_limit_retries_and_cache(self):
        err = urllib.error.HTTPError('https://example.com', 429, 'limited', {'Retry-After':'1'}, None)
        with patch.object(data.urllib.request, 'urlopen', side_effect=[err, self.response({'ok':True})]) as request:
            self.assertEqual(data.get_json('https://example.com', ttl=60), {'ok':True})
            self.assertEqual(data.get_json('https://example.com', ttl=60), {'ok':True})
            self.assertEqual(request.call_count, 2)
        self.assertEqual(data.health(), {'http_429':1,'success':1,'cache_hit':1})

    def test_auth_error_not_retried_or_cached(self):
        err = urllib.error.HTTPError('https://example.com', 401, 'auth', {}, None)
        with patch.object(data.urllib.request, 'urlopen', side_effect=err) as request:
            self.assertIsNone(data.get_json('https://example.com', ttl=60))
            self.assertEqual(request.call_count, 1)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_rate_limit_bounded(self):
        err = urllib.error.HTTPError('https://example.com', 429, 'limited', {}, None)
        with patch.object(data.urllib.request, 'urlopen', side_effect=err) as request:
            self.assertIsNone(data.get_json('https://example.com'))
            self.assertEqual(request.call_count, 3)

    def test_expired_cache_never_used_as_fallback(self):
        with patch.object(data.urllib.request, 'urlopen', return_value=self.response({'ok':True})):
            data.get_json('https://example.com', ttl=60)
        with patch.object(data.time, 'time', return_value=data.time.time()+3600), patch.object(data.urllib.request,'urlopen',side_effect=OSError):
            self.assertIsNone(data.get_json('https://example.com', ttl=60))

class EvidenceTests(unittest.TestCase):
    def test_missing_stale_future_or_naive_option_time_blocks(self):
        for stamp in (None, '2026-10-28T15:00:00', (NOW-timedelta(hours=1)).isoformat(), (NOW+timedelta(seconds=1)).isoformat()):
            c = candidate(); c['quote_as_of'] = stamp
            s = trial.new_state(NOW); trial.accept_candidates(s,[c],NOW)
            self.assertEqual(s['signals'], [])

    def test_stale_exit_does_not_close_or_mark(self):
        s=trial.new_state(NOW); trial.accept_candidates(s,[candidate()],NOW)
        trial.close_positions(s,{'TEST':[dict(strike=5,expiry='2026-12-04',is_call=True,bid=.4,ask=.42,quote_as_of=NOW.isoformat())]},NOW+timedelta(hours=1))
        self.assertEqual(s['signals'][0]['status'],'OPEN')
        self.assertIsNone(trial.update_status(s,NOW+timedelta(hours=1)))

    def test_outside_window_records_attempt_not_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            with patch.object(trial,'STATE_PATH',path),patch.object(trial,'datetime') as clock:
                clock.now.return_value=NOW.replace(hour=23)
                trial.main()
            self.assertFalse(path.exists())
            self.assertEqual(json.loads((Path(temp)/'attempts.json').read_text())[0]['status'],'outside_market_window')

    def test_session_low_uses_new_york_open_in_summer_and_winter(self):
        for now in (NOW,datetime(2026,12,1,16,tzinfo=timezone.utc)):
            start=now.astimezone(trial.ET).replace(hour=9,minute=30,second=0,microsecond=0).timestamp()
            bars=[dict(t=start-3600,c=5,o=5,h=10,l=1,v=100)]
            bars += [dict(t=start+i*300,c=4.5,o=4.6,h=5,l=4,v=100) for i in range(25)]
            sig=live.analyze('TEST',bars,5,now=now)
            self.assertIsNotNone(sig)
            self.assertEqual(sig['day_low'],4)
            self.assertEqual(sig['day_high'],5)

    def test_chain_failure_distinct_from_no_contract(self):
        with patch.object(quality,'has_earnings_within',return_value=False),patch.object(quality,'iv_rank',return_value=30),patch.object(quality,'target_delta_strike',return_value=None):
            quality.CHAIN_HEALTH['TEST']={'status':'request_failed'}
            _,ok,reasons=quality.evaluate_long_signal(dict(candidate(),price=4),'BULLISH')
            self.assertFalse(ok)
            self.assertIn('Option-chain request failed',reasons)
            quality.CHAIN_HEALTH.clear()

if __name__=='__main__': unittest.main()
