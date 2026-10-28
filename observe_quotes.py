"""Observe eligible exact contracts for forward paper review; no trading or alerts.

Free source quote timestamps may be delayed. ts is retrieval time, not exchange
execution time. Missing or expired quotes are left missing, never reconstructed.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from backtest_review import signal_id, timestamp
from scanner_quality import _fetch_nasdaq_chain
from signal_log import read_signals

ROOT = Path(__file__).resolve().parent


def collect(signals, fetch_chain=_fetch_nasdaq_chain, now=None):
    now = now or datetime.now(timezone.utc)
    groups = defaultdict(list)
    for sig in signals:
        if not sig.get('pushed') or not sig.get('contract_verified') or sig.get('contract_type') not in ('CALL','PUT'):
            continue
        try:
            age = now - timestamp(sig['ts'])
            expiry = datetime.fromisoformat(sig['expiry']).date()
        except (KeyError, ValueError, TypeError):
            continue
        if timedelta(0) < age <= timedelta(days=10) and expiry >= now.date():
            groups[sig['ticker']].append(sig)
    rows = []
    for ticker, entries in groups.items():
        chain = fetch_chain(ticker, 45) or []
        for sig in entries:
            match = next((c for c in chain if c['expiry'] == sig['expiry'] and
                          c['strike'] == sig['strike'] and c['is_call'] == (sig['contract_type']=='CALL')), None)
            if match:
                rows.append(dict(signal_id=signal_id(sig), ts=now.isoformat(),
                    bid=match['bid'], ask=match['ask'], strike=sig['strike'], expiry=sig['expiry'],
                    contract_type=sig['contract_type'], source='Nasdaq public chain',
                    timestamp_basis='retrieval_time_may_be_delayed'))
    return rows


if __name__ == '__main__':
    rows = collect(read_signals())
    if rows:
        with (ROOT/'option_quotes.jsonl').open('a') as f:
            for row in rows:
                f.write(json.dumps(row)+'\n')
    print(f'Recorded {len(rows)} quote observations. No reconstructed prices or orders.')
