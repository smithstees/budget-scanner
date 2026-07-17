#!/usr/bin/env python3
"""
Live Options Scanner — On-Demand Intraday
Trigger manually from GitHub Actions when you want to look for a play RIGHT NOW.

Uses Yahoo Finance's free /v8/finance/chart endpoint (no API key needed) which
returns 5-minute intraday bars with roughly 15-minute delay — that's plenty
good enough to spot pullbacks and momentum in real time. This works AROUND
the free Polygon/Massive tier limitation (which only serves end-of-day data).

Same $20-contract budget constraint as the nightly scanner.
Pushes to ntfy.sh topic: ragebudgetopt
"""

import os, time, math, json, urllib.request
from datetime import datetime, timedelta

def _ascii(s):
    # ntfy Title header must be latin-1 safe. Strip fancy unicode (— ★ ⚡ etc.)
    return (s.replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u2022", "*").replace("\u00b7", "-")
             .replace("\u2605", "*").replace("\u2606", "*")
             .replace("\u26a1", "!").encode("ascii", "ignore").decode("ascii"))

try:
    import config
    NTFY_TOPIC = config.NTFY_TOPIC
    _CFG_MIN = config.STOCK_PRICE_MIN
    _CFG_MAX = config.STOCK_PRICE_MAX
except Exception:
    config = None
    NTFY_TOPIC = os.environ.get('NTFY_TOPIC', 'ragebudgetopt')
    _CFG_MIN = 2.0
    _CFG_MAX = 15.0

try:
    import scanner_quality as sq
except Exception as e:
    print(f"scanner_quality unavailable: {e}")
    sq = None
YAHOO_URL  = 'https://query1.finance.yahoo.com/v8/finance/chart/'

# Same budget-friendly watchlist as the nightly scanner
WATCHLIST = [
  'SOFI','OPEN',
  'JBLU','AAL','CCL','NCLH',
  'RIVN','LCID','JOBY','ACHR','WKHS','NIO','XPEV','LI',
  'MARA','RIOT','CLSK','CIFR','WULF',
  'SNAP','PINS',
  'TLRY','SNDL','CLOV','ATER','IDEX','MVIS',
  'NOK','SIRI','T',
  'SENS','GRAB','F','LYFT','PLUG','SPWR','ENVX',
  'VALE','ITUB','BBD','ZIM',
]

STOCK_PRICE_MIN = _CFG_MIN
STOCK_PRICE_MAX = _CFG_MAX
NOTIFY_MIN_SCORE = 55  # slightly lower than nightly since intraday moves faster


def fetch_intraday(ticker):
    """Return list of 5-minute bars for today's session, plus previous close."""
    url = f"{YAHOO_URL}{ticker}?interval=5m&range=2d&includePrePost=false"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; budget-scanner/1.0)'
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data.get('chart', {}).get('result', [])
        if not result:
            return None, None
        r0 = result[0]
        meta = r0.get('meta', {})
        prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
        timestamps = r0.get('timestamp', [])
        indi = r0.get('indicators', {}).get('quote', [{}])[0]
        opens  = indi.get('open', [])
        highs  = indi.get('high', [])
        lows   = indi.get('low', [])
        closes = indi.get('close', [])
        vols   = indi.get('volume', [])

        bars = []
        for i in range(len(timestamps)):
            if closes[i] is None:
                continue
            bars.append({
                't': timestamps[i],
                'o': opens[i] or closes[i],
                'h': highs[i] or closes[i],
                'l': lows[i]  or closes[i],
                'c': closes[i],
                'v': vols[i] or 0,
            })
        return bars, prev_close
    except Exception as e:
        print(f"  [{ticker}] fetch error: {e}")
        return None, None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = 0, 0
    for i in range(len(closes) - period, len(closes)):
        chg = closes[i] - closes[i-1]
        if chg > 0: gains += chg
        else: losses += abs(chg)
    avg_g = gains / period
    avg_l = losses / period
    if avg_l == 0: return 100
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)))


def est_contract_cost(price, atr_pct_val):
    base = 0.015 * price
    vol_boost = (atr_pct_val / 100) * price * 0.5
    return round(base + vol_boost, 2)


def analyze(ticker, bars, prev_close):
    if not bars or len(bars) < 20 or not prev_close:
        print(f"  [{ticker}] not enough intraday bars")
        return None

    price = bars[-1]['c']
    if price < STOCK_PRICE_MIN or price > STOCK_PRICE_MAX:
        print(f"  [{ticker}] ${price:.2f} out of ${STOCK_PRICE_MIN}-${STOCK_PRICE_MAX} band")
        return None

    change_pct = round(((price - prev_close) / prev_close) * 100, 2)

    # Today's session only
    today_start = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
    today_bars = [b for b in bars if b['t'] >= today_start] or bars[-40:]

    day_high = max(b['h'] for b in today_bars)
    day_low  = min(b['l'] for b in today_bars)

    closes = [b['c'] for b in bars[-30:]]
    rsi = calc_rsi(closes, 14)

    # Intraday ATR% (last 12 five-minute bars = 1 hour)
    recent = bars[-13:]
    trs = []
    for i in range(1, len(recent)):
        p, b = recent[i-1], recent[i]
        trs.append(max(b['h']-b['l'], abs(b['h']-p['c']), abs(b['l']-p['c'])))
    atr = sum(trs)/len(trs) if trs else 0
    atr_pct_val = round((atr / price) * 100, 2) if price else 0

    # Volume: last hour vs prior hour
    last12 = bars[-12:]
    prior12 = bars[-24:-12] if len(bars) >= 24 else bars[:-12]
    last_vol  = sum(b['v'] for b in last12)
    prior_vol = sum(b['v'] for b in prior12) or 1
    rel_vol = round(last_vol / prior_vol, 1)

    # Position within day range
    if day_high > day_low:
        day_pos = (price - day_low) / (day_high - day_low)
    else:
        day_pos = 0.5

    # Near intraday support?
    near_low = price <= day_low * 1.015
    near_high = price >= day_high * 0.985

    bull_score, bear_score = 0, 0

    if rsi is not None:
        if rsi < 30:   bull_score += 25
        elif rsi < 40: bull_score += 15
        elif rsi > 70: bear_score += 25
        elif rsi > 60: bear_score += 15

    if change_pct <= -2.5 and near_low:  bull_score += 25  # deep dip near LOD
    elif change_pct <= -1.0 and near_low: bull_score += 15
    elif change_pct >= 2.5 and near_high: bear_score += 25 # extended near HOD
    elif change_pct >= 1.0 and near_high: bear_score += 15

    if day_pos < 0.2:      bull_score += 15  # bouncing off bottom of range
    elif day_pos < 0.35:   bull_score += 8
    elif day_pos > 0.8:    bear_score += 15
    elif day_pos > 0.65:   bear_score += 8

    if rel_vol >= 2.0:   bull_score += 12; bear_score += 12
    elif rel_vol >= 1.4: bull_score += 6;  bear_score += 6

    # Last 3 bars direction
    last3 = bars[-3:]
    greens = sum(1 for b in last3 if b['c'] > b['o'])
    reds   = sum(1 for b in last3 if b['c'] < b['o'])
    if greens >= 2 and change_pct < 0:   bull_score += 10  # reversal off dip
    if reds   >= 2 and change_pct > 0:   bear_score += 10  # rejection at top

    # 3-5 strikes OTM (~4 strikes)
    step = 0.50 if price < 10 else 1.00
    if bull_score > bear_score and bull_score >= 25:
        trend = 'BULLISH'
        score = min(95, max(5, bull_score))
        ctype = 'CALL'
        strike = round((round(price / step) * step) + 4 * step, 2)
    elif bear_score > bull_score and bear_score >= 25:
        trend = 'BEARISH'
        score = min(95, max(5, bear_score))
        ctype = 'PUT'
        strike = round((round(price / step) * step) - 4 * step, 2)
    else:
        print(f"  [{ticker}] ${price:.2f} no signal (bull:{bull_score} bear:{bear_score})")
        return None

    tier = 'STRONG' if score >= 65 else 'MODERATE' if score >= 45 else 'WEAK'
    est_cost = est_contract_cost(price, atr_pct_val)

    print(f"  [{ticker}] ${price:.2f} ({change_pct:+.2f}%) {trend} "
          f"score:{score} RSI:{rsi} dayPos:{int(day_pos*100)}% "
          f"vol:{rel_vol}x est_prem:${est_cost}")

    return {
        'ticker': ticker,
        'price': price,
        'change_pct': change_pct,
        'trend': trend,
        'score': score,
        'tier': tier,
        'rsi': rsi,
        'rel_vol': rel_vol,
        'atr_pct': atr_pct_val,
        'day_pos': day_pos,
        'day_high': day_high,
        'day_low': day_low,
        'contract_type': ctype,
        'strike': strike,
        'est_cost': est_cost,
    }


def push_signal(sig):
    direction = sig['contract_type']
    title = f"[LIVE {direction}] {sig['ticker']} {sig['tier']} {sig['score']}%"
    est_ct = round(sig['est_cost'] * 100)
    # Sell zone: 65% of the way from current to strike
    if sig['trend'] == 'BULLISH':
        sell_zone = round(sig['price'] + 0.65 * (sig['strike'] - sig['price']), 2)
    else:
        sell_zone = round(sig['price'] - 0.65 * (sig['price'] - sig['strike']), 2)
    body = (
        f"${sig['price']:.2f} ({sig['change_pct']:+.2f}% today)\n"
        f"Range: ${sig['day_low']:.2f} — ${sig['day_high']:.2f} "
        f"(at {int(sig['day_pos']*100)}%)\n"
        f"RSI(5m): {sig['rsi']} | vol: {sig['rel_vol']}x last hour\n"
        f"Buy {direction} strike ${sig['strike']:.2f} (3-5 OTM)\n"
        f"Expiry 30-45 days | ~${est_ct}/contract | OI>50\n"
        f"SELL when stock hits ~${sell_zone:.2f} · stop -60%\n"
        f"💡 Take HALF off at +50% — lock the win\n"
        f"⚠ Live scan — verify contract price in broker."
    )
    try:
        data = body.encode('utf-8')
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=data,
            headers={
                'Title': _ascii(title),
                'Priority': 'high' if sig['score'] >= 65 else 'default',
                'Tags': 'zap,chart_with_upwards_trend' if sig['trend']=='BULLISH' else 'zap,chart_with_downwards_trend',
                'Content-Type': 'text/plain; charset=utf-8',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10): pass
        print(f"  Pushed: {title}")
    except Exception as e:
        print(f"  Push error: {e}")


def push_summary(signals, pushed):
    total = len(signals)
    if total == 0:
        msg = "No live setups found right now. Try again in 30-60 min."
        title = "Live Scan — No Signals"
    else:
        top = ", ".join(s['ticker'] for s in signals[:5])
        msg = f"Scanned {len(WATCHLIST)} tickers | {total} setups | {pushed} pushed (score>={NOTIFY_MIN_SCORE})\nTop: {top}"
        title = f"Live Scan Done — {pushed} pushed"
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode('utf-8'),
            headers={
                'Title': _ascii(title),
                'Priority': 'default' if pushed else 'low',
                'Content-Type': 'text/plain; charset=utf-8',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10): pass
    except: pass


def _enrich_live(sig, regime):
    """
    Same quality checks as nightly, applied only to candidate pushes to keep
    intraday fast. Returns (sig, ok, reasons).
    """
    reasons = []
    ticker = sig['ticker']

    # Earnings blackout (biggest single cause of IV-crush losses on longs)
    if sq.has_earnings_within(ticker, config.EARNINGS_BLACKOUT_DAYS) is True:
        sig['earnings_within_days'] = config.EARNINGS_BLACKOUT_DAYS
        reasons.append(f"Earnings within {config.EARNINGS_BLACKOUT_DAYS}d (IV crush risk)")

    # IV rank ceiling (paying up for premium)
    ivr = sq.iv_rank(ticker)
    if ivr is not None:
        sig['iv_rank'] = ivr
        if ivr > config.IV_RANK_CEILING:
            reasons.append(f"IV Rank {ivr} > {config.IV_RANK_CEILING}")

    # Real delta strike + liquidity
    direction = sig.get('trend', 'BULLISH')
    real = sq.target_delta_strike(ticker, sig['price'], 35, direction)
    if real:
        sig['real_strike']       = real['strike']
        sig['real_expiry']       = real['expiry']
        sig['real_delta']        = real['delta']
        sig['real_iv']           = real['iv']
        sig['real_oi']           = real['oi']
        sig['real_mid']          = real['mid']
        sig['real_spread_pct']   = real['spread_pct']
        sig['real_est_contract'] = round(real['mid'] * 100)
        if not sq.is_liquid(real):
            reasons.append(
                f"Illiquid OI={real['oi']} spread={int(real['spread_pct']*100)}%"
            )

    # SPY regime bias
    score = sig.get('score', 0)
    if regime == 'BEARISH' and direction == 'BULLISH' and score < 65:
        reasons.append("SPY < 200d SMA; CALL below high-conviction cutoff")
    elif regime == 'BULLISH' and direction == 'BEARISH' and score < 65:
        reasons.append("SPY > 200d SMA; PUT below high-conviction cutoff")

    sig['quality_blocks'] = reasons
    ok = (not reasons) if config.QUALITY_STRICT else True
    if reasons:
        for r in reasons:
            print(f"  [quality]  {r}")
    return sig, ok, reasons


def main():
    print(f"\n{'='*60}")
    print(f"Live Scanner — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Source: Yahoo Finance intraday (5m bars, ~15min delay)")
    print(f"Watchlist: {len(WATCHLIST)} tickers, ${STOCK_PRICE_MIN}-${STOCK_PRICE_MAX} band")
    print(f"Push threshold: score >= {NOTIFY_MIN_SCORE}")
    print(f"{'='*60}\n")

    signals = []
    pushed = 0

    try:
        from signal_log import log_signal
    except Exception:
        log_signal = None

    # SPY regime once per run (cached in scanner_quality)
    if sq is not None:
        regime = sq.spy_regime()
        det = sq.spy_details()
        print(f"SPY regime: {regime}  (last={det.get('last')}, 200d SMA={det.get('sma')})")
    else:
        regime = 'NEUTRAL'
        print("Quality module unavailable (running unfiltered)")

    for i, ticker in enumerate(WATCHLIST):
        print(f"[{i+1}/{len(WATCHLIST)}] {ticker}")
        bars, prev = fetch_intraday(ticker)
        sig = analyze(ticker, bars, prev) if bars else None
        if sig:
            # Only enrich signals that could actually push — saves Yahoo calls
            candidate_push = sig['score'] >= NOTIFY_MIN_SCORE
            if candidate_push and sq is not None and config is not None:
                sig, ok, reasons = _enrich_live(sig, regime)
            else:
                ok = True
            signals.append(sig)
            did_push = candidate_push and ok
            if did_push:
                push_signal(sig)
                pushed += 1
                time.sleep(0.5)
            if log_signal is not None:
                log_signal('live', sig, pushed=did_push)
        time.sleep(0.3)  # Yahoo is generous, but be polite

    signals.sort(key=lambda s: s['score'], reverse=True)
    push_summary(signals, pushed)

    print(f"\n{'='*60}")
    print(f"Done. {len(signals)} setups | {pushed} pushed.")
    if signals:
        print("\nTop live setups:")
        for s in signals[:10]:
            marker = "PUSH" if s['score'] >= NOTIFY_MIN_SCORE else "----"
            print(f"  {marker} {s['ticker']:6} ${s['price']:>6.2f} "
                  f"{s['contract_type']} {s['trend']:8} "
                  f"score:{s['score']} est ${round(s['est_cost']*100)}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
