"""Review chronological option quotes, never infer option P&L from stock moves.

Legacy signals without exact contracts and entry quotes stay UNVERIFIED.
Optional quotes.jsonl rows: signal_id, ts (UTC ISO), bid, ask, expiry, strike,
contract_type. Paper fills assume buying the recorded ask and selling a later
bid; quotes are not proof of execution. No brokerage orders are placed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from signal_log import read_signals

ROOT = Path(__file__).resolve().parent
SCORED_PATH = ROOT / 'signals_scored.jsonl'


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timezone required')
    return dt.astimezone(timezone.utc)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def signal_id(sig):
    return sig.get('signal_id') or hashlib.sha256(
        '|'.join(str(sig.get(k, '')) for k in ('scanner', 'ts', 'ticker', 'contract_type', 'strike')).encode()
    ).hexdigest()[:24]


def evaluate_signal(sig, quotes, *, as_of, horizon_days=7, fee_per_side=0.65):
    result = {'signal_id': signal_id(sig), 'scanner': sig.get('scanner'),
              'ticker': sig.get('ticker'), 'ts': sig.get('ts'),
              'review_outcome': 'UNVERIFIED', 'pnl': None,
              'basis': 'quoted_paper_execution_not_actual_trades'}
    def unverified(reason):
        return dict(result, reason=reason)
    if sig.get('contract_type') not in ('CALL', 'PUT'):
        return unverified('Short puts require assignment-aware accounting; not evaluated as long options')
    if not sig.get('pushed') or not sig.get('contract_verified'):
        return unverified('No eligible, contract-verified entry signal')
    required = ('expiry', 'strike', 'entry_bid', 'entry_ask', 'ts')
    if any(sig.get(k) is None for k in required):
        return unverified('Missing exact contract or entry quote')
    try:
        entry_time = timestamp(sig['ts'])
        # Use exchange local timezone, including DST.
        from zoneinfo import ZoneInfo
        expiry_time = datetime.fromisoformat(sig['expiry'] + 'T16:00:00').replace(
            tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return unverified('Invalid entry timestamp or expiry')
    bid, ask = sig['entry_bid'], sig['entry_ask']
    if not all(finite(x) for x in (bid, ask)) or not 0 < bid <= ask or expiry_time <= entry_time:
        return unverified('Invalid entry quote or expiry')
    end = min(entry_time + timedelta(days=horizon_days), expiry_time)
    valid = []
    for q in quotes:
        if q.get('signal_id') != result['signal_id']:
            continue
        if any(q.get(k) != sig.get(k) for k in ('expiry', 'strike', 'contract_type')):
            continue
        try:
            t = timestamp(q['ts'])
        except (KeyError, TypeError, ValueError):
            continue
        b, a = q.get('bid'), q.get('ask')
        if not all(finite(x) for x in (b, a)) or not 0 <= b <= a:
            continue
        if entry_time < t <= min(as_of, expiry_time):
            valid.append((t, b))
    valid.sort()
    # Stops/targets are tested in time order on observable exit bids.
    # A jump through a stop fills at that bid, not at the stop threshold.
    exit_quote, reason = None, None
    for t, b in valid:
        if t >= end:
            if t - end <= timedelta(hours=24):
                exit_quote, reason = (t, b), 'TIME_EXIT'
            break
        if b <= ask * 0.40:
            exit_quote, reason = (t, b), 'STOP'
            break
        if b >= ask * 1.50:
            exit_quote, reason = (t, b), 'TARGET'
            break
    if exit_quote is None:
        result['review_outcome'] = 'OPEN' if as_of < end else 'UNVERIFIED'
        result['reason'] = 'Awaiting exit quotes' if as_of < end else 'Missing horizon/expiry exit quote; no invented fill'
        return result
    t, exit_bid = exit_quote
    pnl = round((exit_bid - ask) * 100 - 2 * fee_per_side, 2)
    return dict(result, review_outcome='WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'FLAT',
                pnl=pnl, entry_cost=round(ask * 100 + fee_per_side, 2),
                exit_bid=exit_bid, exit_ts=t.isoformat(), exit_reason=reason,
                sampled_quotes_only=True)


def summarize(rows):
    closed = sorted((r for r in rows if r.get('pnl') is not None), key=lambda r: r['exit_ts'])
    cumulative = peak = drawdown = 0.0
    monthly = defaultdict(float)
    by_scanner = defaultdict(lambda: {'closed': 0, 'net_pnl': 0.0})
    for r in closed:
        cumulative += r['pnl']
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        monthly[r['exit_ts'][:7]] += r['pnl']
        group = by_scanner[r.get('scanner') or 'unknown']
        group['closed'] += 1
        group['net_pnl'] = round(group['net_pnl'] + r['pnl'], 2)
    return {'signals_reviewed': len(rows), 'outcomes': dict(Counter(r['review_outcome'] for r in rows)),
            'closed_paper_trades': len(closed), 'net_paper_pnl': round(cumulative, 2) if closed else None,
            'closed_trade_drawdown': round(drawdown, 2) if closed else None,
            'monthly_net_paper_pnl': {k: round(v, 2) for k, v in sorted(monthly.items())},
            'by_scanner': dict(by_scanner), 'proven_monthly_income': False,
            'limitations': ['Quoted paper fills, not actual executions',
                           'Unsampled price moves and open-position losses are not measured',
                           'No account-level capital or simultaneous-position limits are simulated',
                           'Legacy estimated premiums are never treated as real trade prices']}


def review(signals=None, quotes=None, as_of=None, horizon_days=7, fee_per_side=0.65):
    as_of = as_of or datetime.now(timezone.utc)
    seen = set()
    rows = []
    for sig in read_signals() if signals is None else signals:
        key = signal_id(sig)
        if key in seen:
            continue
        seen.add(key)
        rows.append(evaluate_signal(sig, quotes or [], as_of=as_of,
                                   horizon_days=horizon_days, fee_per_side=fee_per_side))
    return {'scored': rows, 'summary': summarize(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quotes', type=Path, help='Local quote observations; never committed by this script')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports')
    parser.add_argument('--horizon-days', type=int, default=7)
    parser.add_argument('--fee-per-side', type=float, default=0.65)
    args = parser.parse_args()
    if args.horizon_days <= 0 or not finite(args.fee_per_side) or args.fee_per_side < 0:
        parser.error('Positive horizon and finite nonnegative fees required')
    quote_path = args.quotes or ROOT / 'option_quotes.jsonl'
    quotes = [json.loads(line) for line in quote_path.read_text().splitlines() if line.strip()] if quote_path.exists() else []
    result = review(quotes=quotes, horizon_days=args.horizon_days, fee_per_side=args.fee_per_side)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Replace derived outputs: reruns cannot append duplicate wins.
    (args.output_dir / 'signals_scored.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in result['scored']))
    (args.output_dir / 'review.json').write_text(json.dumps(result['summary'], indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
