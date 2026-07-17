#!/usr/bin/env python3
"""
Nightly Options Scanner — End of Day
Uses Massive.com (Polygon) free tier (/v2/aggs only)
Scoring: RSI + Bollinger Bands + Volume + 3-Candle Confirm
Target: contracts $0.10-$0.30/share ($10-$30/contract), 30-45 day expiry
Pushes to ntfy.sh topic: ragebudgetopt

REVISIONS v4 (2026-07-06):
- Strategy shift: recommend 30-45 day expiries, 3-5 strikes OTM ("runway options")
  instead of 7-14 day / 1-2 OTM. Longer runway = far less theta bleed, better
  win-rate math (35-40% wins can still be profitable when winners run 100%+).
- Exit guidance changed from +40% price target to delta-based: sell when the
  stock is 60-75% of the way to the strike. Avoids gamma trap at expiration.
- Stop loosened from -50% to -60% (longer expiry means more time to recover)
- Est contract cost recalibrated for the further-OTM + longer-dated combo

PRIOR REVISIONS:
- Watchlist pruned to sub-$15 stocks where ATM options typically fit a $30 budget
- Notification threshold raised: only STRONG signals (score >= 60) push
- Delisted/zero-bar tickers (SAVE, GOEV, BITF, PARA) removed
"""

import os, time, math, json, urllib.request, urllib.parse
from datetime import datetime, timedelta

def _ascii(s):
    # ntfy Title header must be latin-1 safe. Strip fancy unicode.
    return (s.replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u2022", "*").replace("\u00b7", "-")
             .replace("\u2605", "*").replace("\u2606", "*")
             .replace("\u26a1", "!").encode("ascii", "ignore").decode("ascii"))

# CONFIG
API_KEY   = os.environ.get('POLYGON_KEY', '')
NTFY_TOPIC = os.environ.get('NTFY_TOPIC', 'ragebudgetopt')
BASE_URL  = 'https://api.massive.com'

# Only stocks whose ATM/near-money 2-4 week options typically trade under
# $0.20/share ($20/contract). Anything priced >$15 rarely fits that budget.
WATCHLIST = [
  # Fintech / lending (cheap end)
  'SOFI','OPEN',
  # Airlines / cruise (low-priced volatile names)
  'JBLU','AAL','CCL','NCLH',
  # EVs / mobility
  'RIVN','LCID','JOBY','ACHR','WKHS','NIO','XPEV','LI',
  # Crypto miners (small-caps only)
  'MARA','RIOT','CLSK','CIFR','WULF',
  # Social / consumer
  'SNAP','PINS',
  # Cannabis / small-cap speculative
  'TLRY','SNDL','CLOV','ATER','IDEX','MVIS',
  # Telecom / media low-priced
  'NOK','SIRI','T',
  # Health / other budget names
  'SENS','GRAB','F','LYFT','PLUG','SPWR','ENVX',
  # Brazilian ADRs / shipping (typically cheap)
  'VALE','ITUB','BBD','ZIM',
]

DELAY = 13  # free tier: 5 calls/min

# Price band for the underlying stock. Below $2 = often delisted/illiquid.
# Above $15 = options usually cost > $20/contract at reasonable strikes.
STOCK_PRICE_MIN = 2.0
STOCK_PRICE_MAX = 15.0

# Only push notifications for signals scoring at least this high.
# Weak/moderate setups are logged but not pinged, so the phone doesn't spam.
NOTIFY_MIN_SCORE = 60

def fetch_candles(ticker):
    end = datetime.now()
    start = end - timedelta(days=60)
    fmt = lambda d: d.strftime('%Y-%m-%d')
    url = (f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/"
           f"{fmt(start)}/{fmt(end)}"
           f"?adjusted=true&sort=asc&limit=50&apiKey={API_KEY}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'scanner/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get('results', [])
    except Exception as e:
        print(f"  [{ticker}] fetch error: {e}")
        return []

def calc_rsi(bars, period=14):
    if len(bars) < period + 1:
        return None
    closes = [b['c'] for b in bars]
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

def calc_bollinger(bars, period=20, mult=2):
    if len(bars) < period:
        return None
    closes = [b['c'] for b in bars[-period:]]
    mean = sum(closes) / period
    variance = sum((c - mean)**2 for c in closes) / period
    std = math.sqrt(variance)
    upper = mean + mult * std
    lower = mean - mult * std
    width = (upper - lower) / mean
    last = bars[-1]['c']
    pct = (last - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return {'upper': upper, 'lower': lower, 'mid': mean, 'width': width, 'pct': pct}

def calc_atr(bars, period=5):
    if len(bars) < period + 1:
        return None
    slice_ = bars[-(period+1):]
    atrs = []
    for i in range(1, len(slice_)):
        p, b = slice_[i-1], slice_[i]
        atrs.append(max(b['h']-b['l'], abs(b['h']-p['c']), abs(b['l']-p['c'])))
    return sum(atrs) / len(atrs)

def candle_dir(b):
    rng = b['h'] - b['l'] or 0.01
    body = abs(b['c'] - b['o'])
    if body < rng * 0.05: return 'd'
    return 'g' if b['c'] > b['o'] else 'r'

def est_contract_cost(price, atr_pct):
    """
    Rough estimate of a 30-45 day, 3-5 strikes OTM contract premium as $/share.
    Longer runway costs more than 2-week ATM but decays FAR slower.
    Multiply result by 100 for $/contract.
    """
    # 30-45 day, 3-5 strikes OTM: roughly 1.5-3% of underlying for low-vol names,
    # scaling with realized volatility.
    base = 0.02 * price
    vol_boost = (atr_pct / 100) * price * 0.8
    return round(base + vol_boost, 2)

def suggest_strike(price, direction):
    """3-5 strikes OTM. Assumes $0.50 strike increments under $10, $1 above."""
    step = 0.50 if price < 10 else 1.00
    otm_strikes = 4  # split-the-middle of 3-5
    if direction == 'BULLISH':
        # Round up to next step, then go 4 more steps OTM
        target = math.ceil(price / step) * step + otm_strikes * step
    else:
        target = math.floor(price / step) * step - otm_strikes * step
    return round(target, 2)

def analyze(ticker):
    bars = fetch_candles(ticker)
    if len(bars) < 22:
        print(f"  [{ticker}] not enough bars ({len(bars)})")
        return None

    last = bars[-1]
    prev = bars[-2]
    price = last['c']

    if price < STOCK_PRICE_MIN or price > STOCK_PRICE_MAX:
        print(f"  [{ticker}] price ${price:.2f} out of ${STOCK_PRICE_MIN}-${STOCK_PRICE_MAX} budget range")
        return None

    chg = round(((price - prev['c']) / prev['c']) * 10000) / 100

    vol_bars = [b['v'] for b in bars[-11:-1]]
    avg_vol = sum(vol_bars) / len(vol_bars) if vol_bars else 1
    rel_vol = round((last.get('v', 0) / avg_vol) * 10) / 10
    vol_up = (bars[-1].get('v',0) > bars[-2].get('v',0) and
              bars[-2].get('v',0) > bars[-3].get('v',0))

    rsi = calc_rsi(bars, 14)
    bb  = calc_bollinger(bars, 20, 2)
    atr = calc_atr(bars, 5)
    atr_pct = round((atr / price) * 1000) / 10 if atr else 0

    last5 = bars[-5:]
    dirs = [candle_dir(b) for b in last5[-3:]]
    gc = dirs.count('g')
    rc = dirs.count('r')
    candle_conf = 'bull' if gc == 3 else 'bear' if rc == 3 else None

    res = round(max(b['h'] for b in last5) * 100) / 100
    sup = round(min(b['l'] for b in last5) * 100) / 100

    bull_score, bear_score = 0, 0

    if rsi is not None:
        if rsi < 35:   bull_score += 30
        elif rsi < 45: bull_score += 15
        elif rsi > 65: bear_score += 30
        elif rsi > 55: bear_score += 15

    if bb:
        if bb['pct'] < 0.2 and bb['width'] < 0.08:  bull_score += 25
        elif bb['pct'] < 0.25:                        bull_score += 15
        elif bb['pct'] > 0.8 and bb['width'] < 0.08: bear_score += 25
        elif bb['pct'] > 0.75:                        bear_score += 15

    if rel_vol >= 2.5:   bull_score += 15; bear_score += 15
    elif rel_vol >= 1.5: bull_score += 8;  bear_score += 8
    elif rel_vol < 0.7:  bull_score -= 10; bear_score -= 10
    if vol_up:           bull_score += 8;  bear_score += 5

    if candle_conf == 'bull':   bull_score += 20
    elif candle_conf == 'bear': bear_score += 20

    if 2 <= atr_pct <= 10: bull_score += 5; bear_score += 5
    elif atr_pct < 2:      bull_score -= 5; bear_score -= 5

    if bull_score > bear_score and bull_score >= 30:
        trend = 'BULLISH'
        score = min(95, max(5, bull_score))
        contract_type = 'CALL'
        strike = suggest_strike(price, 'BULLISH')
    elif bear_score > bull_score and bear_score >= 30:
        trend = 'BEARISH'
        score = min(95, max(5, bear_score))
        contract_type = 'PUT'
        strike = suggest_strike(price, 'BEARISH')
    else:
        print(f"  [{ticker}] no clear signal (bull:{bull_score} bear:{bear_score})")
        return None

    tier = 'STRONG' if score >= 65 else 'MODERATE' if score >= 45 else 'WEAK'
    est_cost = est_contract_cost(price, atr_pct)

    print(f"  [{ticker}] ${price:.2f} {trend} score:{score} RSI:{rsi} vol:{rel_vol}x "
          f"BB:{round(bb['pct']*100) if bb else 'n/a'}% est_prem:${est_cost}")

    return {
        'ticker': ticker,
        'price': price,
        'chg': chg,
        'trend': trend,
        'score': score,
        'tier': tier,
        'rsi': rsi,
        'rel_vol': rel_vol,
        'vol_up': vol_up,
        'atr_pct': atr_pct,
        'contract_type': contract_type,
        'strike': strike,
        'res': res,
        'sup': sup,
        'est_cost': est_cost,
    }

def push_signal(sig):
    direction = 'CALL' if sig['trend'] == 'BULLISH' else 'PUT'
    vol_tag = 'HIGH VOL' if sig['rel_vol'] >= 2.0 else 'vol+' if sig['rel_vol'] >= 1.5 else ''
    title = f"[{direction}] {sig['ticker']} - {sig['tier']} {sig['score']}% {vol_tag}"

    est_contract = round(sig['est_cost'] * 100)
    # Delta-exit target: sell when stock is 65% of the way from current to strike
    if sig['trend'] == 'BULLISH':
        sell_zone = round(sig['price'] + 0.65 * (sig['strike'] - sig['price']), 2)
    else:
        sell_zone = round(sig['price'] - 0.65 * (sig['price'] - sig['strike']), 2)
    body = (
        f"${sig['price']:.2f} ({'+' if sig['chg']>0 else ''}{sig['chg']:.2f}%)\n"
        f"Signal: {sig['trend']} | RSI: {sig['rsi']} | Vol: {sig['rel_vol']}x\n"
        f"ATR: {sig['atr_pct']}%\n"
        f"Buy {sig['contract_type']} strike ${sig['strike']:.2f} (3-5 OTM)\n"
        f"Expiry 30-45 days | est ~${est_contract}/contract | OI > 50\n"
        f"SELL when stock hits ~${sell_zone:.2f} (likely +80-200% gain)\n"
        f"Stop: -60% on contract"
    )

    try:
        data = body.encode('utf-8')
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=data,
            headers={
                'Title': _ascii(title),
                'Priority': 'high' if sig['score'] >= 65 else 'default',
                'Tags': 'chart_with_upwards_trend' if sig['trend']=='BULLISH' else 'chart_with_downwards_trend',
                'Content-Type': 'text/plain; charset=utf-8',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        print(f"  Pushed: {title}")
    except Exception as e:
        print(f"  Push error: {e}")

def push_summary(signals, pushed_count):
    if not signals:
        try:
            data = "No setups met scoring threshold tonight. Try again tomorrow.".encode('utf-8')
            req = urllib.request.Request(
                f"https://ntfy.sh/{NTFY_TOPIC}", data=data,
                headers={
                    'Title': 'Nightly Scan - No Signals',
                    'Priority': 'low',
                    'Content-Type': 'text/plain; charset=utf-8',
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10): pass
        except: pass
        return

    strong = [s for s in signals if s['score'] >= NOTIFY_MIN_SCORE]
    top_names = ', '.join([s['ticker'] for s in signals[:5]]) or 'none'
    summary = (
        f"Scanned {len(WATCHLIST)} tickers\n"
        f"Total setups: {len(signals)} | Pushed (score>={NOTIFY_MIN_SCORE}): {pushed_count}\n"
        f"Top 5 by score: {top_names}"
    )
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=summary.encode('utf-8'),
            headers={
                'Title': _ascii(f"Nightly Scan Complete - {pushed_count} pushed"),
                'Priority': 'default',
                'Content-Type': 'text/plain; charset=utf-8',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10): pass
    except: pass

def main():
    print(f"\n{'='*50}")
    print(f"Nightly Scanner -- {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    print(f"Tickers: {len(WATCHLIST)} | Delay: {DELAY}s | Free tier")
    print(f"Stock band: ${STOCK_PRICE_MIN}-${STOCK_PRICE_MAX} | Push threshold: score>={NOTIFY_MIN_SCORE}")
    print(f"{'='*50}\n")

    if not API_KEY:
        print("ERROR: POLYGON_KEY secret not set in GitHub Actions")
        return

    signals = []
    pushed = 0

    # Signal history log (for weekly backtest_review.py)
    try:
        from signal_log import log_signal
    except Exception:
        log_signal = None

    for i, ticker in enumerate(WATCHLIST):
        print(f"[{i+1}/{len(WATCHLIST)}] {ticker}")
        sig = analyze(ticker)
        if sig:
            signals.append(sig)
            did_push = sig['score'] >= NOTIFY_MIN_SCORE
            if did_push:
                push_signal(sig)
                pushed += 1
                time.sleep(2)
            if log_signal is not None:
                log_signal('nightly', sig, pushed=did_push)
        time.sleep(DELAY)

    signals.sort(key=lambda s: s['score'], reverse=True)
    push_summary(signals, pushed)

    print(f"\n{'='*50}")
    print(f"Done. {len(signals)} setups found, {pushed} pushed to phone.")
    if signals:
        print("\nTop signals (by score):")
        for s in signals[:8]:
            marker = "PUSH" if s['score'] >= NOTIFY_MIN_SCORE else "----"
            print(f"  {marker} {s['ticker']:6} {s['trend']:8} score:{s['score']} "
                  f"{s['contract_type']} near ${s['strike']:.2f} est ${round(s['est_cost']*100)}")
    print(f"{'='*50}\n")

if __name__ == '__main__':
    main()
