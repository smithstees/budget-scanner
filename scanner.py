#!/usr/bin/env python3
"""
Nightly Options Scanner — End of Day
Uses Massive.com free tier (/v2/aggs only)
Scoring: RSI + Bollinger Bands + Volume + 3-Candle Confirm
Target: contracts $0.02–$0.25/share, 2–4 week expiry
Pushes to ntfy.sh topic: ragebudgetopt
"""

import os, time, math, json, urllib.request, urllib.parse
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────
API_KEY   = os.environ.get('POLYGON_KEY', '')
NTFY_TOPIC = 'ragebudgetopt'
BASE_URL  = 'https://api.massive.com'

# 62 tickers — $3–$25 stock price range, liquid options, 
# contracts naturally land in $0.02–$0.25/share range
WATCHLIST = [
  # Fintech / Retail favorites
  'SOFI','HOOD','AFRM','UPST','OPEN',
  # Travel / Airlines
  'JBLU','AAL','SAVE','CCL','NCLH',
  # EV / Mobility
  'RIVN','LCID','JOBY','ACHR','GOEV','WKHS',
  # Crypto adjacent
  'MARA','RIOT','CLSK','CIFR','WULF','BITF','COIN',
  # China EV
  'NIO','XPEV','LI',
  # Tech / Social
  'SNAP','PINS','RBLX','U','PLTR',
  # Gaming / Betting
  'DKNG','PENN',
  # Energy / Green
  'PLUG','SPWR','ENVX',
  # Telecom / Old guard
  'SIRI','NOK','T','PARA','CMCSA',
  # Healthcare
  'HIMS','SENS',
  # Finance / Auto
  'BAC','F',
  # Asia / Emerging
  'GRAB','VALE','ITUB','BBD','ZIM',
  # Cannabis
  'TLRY','SNDL',
  # Speculative
  'CLOV','EXPR','ATER','IDEX','MVIS','GNUS',
  # Others
  'KVUE','LYFT','UBER'
]

DELAY = 13  # seconds between calls — stays under 5/min free tier limit

# ─── FETCH CANDLES ─────────────────────────────────────────
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

# ─── INDICATORS ────────────────────────────────────────────
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

# ─── ANALYZE ───────────────────────────────────────────────
def analyze(ticker):
    bars = fetch_candles(ticker)
    if len(bars) < 22:
        print(f"  [{ticker}] not enough bars ({len(bars)})")
        return None

    last = bars[-1]
    prev = bars[-2]
    price = last['c']

    # Price filter
    if price < 2 or price > 60:
        print(f"  [{ticker}] price ${price:.2f} out of range")
        return None

    chg = round(((price - prev['c']) / prev['c']) * 10000) / 100

    # Volume
    vol_bars = [b['v'] for b in bars[-11:-1]]
    avg_vol = sum(vol_bars) / len(vol_bars) if vol_bars else 1
    rel_vol = round((last.get('v', 0) / avg_vol) * 10) / 10
    vol_up = (bars[-1].get('v',0) > bars[-2].get('v',0) and
              bars[-2].get('v',0) > bars[-3].get('v',0))

    # Indicators
    rsi = calc_rsi(bars, 14)
    bb  = calc_bollinger(bars, 20, 2)
    atr = calc_atr(bars, 5)
    atr_pct = round((atr / price) * 1000) / 10 if atr else 0

    # 3-candle confirmation
    last5 = bars[-5:]
    dirs = [candle_dir(b) for b in last5[-3:]]
    gc = dirs.count('g')
    rc = dirs.count('r')
    candle_conf = 'bull' if gc == 3 else 'bear' if rc == 3 else None

    # Support / Resistance
    res = round(max(b['h'] for b in last5) * 100) / 100
    sup = round(min(b['l'] for b in last5) * 100) / 100

    # ── SCORING ──
    bull_score, bear_score = 0, 0

    # RSI
    if rsi is not None:
        if rsi < 35:   bull_score += 30
        elif rsi < 45: bull_score += 15
        elif rsi > 65: bear_score += 30
        elif rsi > 55: bear_score += 15

    # Bollinger
    if bb:
        if bb['pct'] < 0.2 and bb['width'] < 0.08:  bull_score += 25
        elif bb['pct'] < 0.25:                        bull_score += 15
        elif bb['pct'] > 0.8 and bb['width'] < 0.08: bear_score += 25
        elif bb['pct'] > 0.75:                        bear_score += 15

    # Volume
    if rel_vol >= 2.5:   bull_score += 15; bear_score += 15
    elif rel_vol >= 1.5: bull_score += 8;  bear_score += 8
    elif rel_vol < 0.7:  bull_score -= 10; bear_score -= 10
    if vol_up:           bull_score += 8;  bear_score += 5

    # Candle confirm
    if candle_conf == 'bull':   bull_score += 20
    elif candle_conf == 'bear': bear_score += 20

    # ATR
    if 2 <= atr_pct <= 10: bull_score += 5; bear_score += 5
    elif atr_pct < 2:      bull_score -= 5; bear_score -= 5

    # Determine direction
    if bull_score > bear_score and bull_score >= 30:
        trend = 'BULLISH'
        score = min(95, max(5, bull_score))
        contract_type = 'CALL'
        strike = res
    elif bear_score > bull_score and bear_score >= 30:
        trend = 'BEARISH'
        score = min(95, max(5, bear_score))
        contract_type = 'PUT'
        strike = sup
    else:
        print(f"  [{ticker}] no clear signal (bull:{bull_score} bear:{bear_score})")
        return None

    tier = 'STRONG' if score >= 65 else 'MODERATE' if score >= 45 else 'WEAK'

    print(f"  [{ticker}] ✓ ${price:.2f} {trend} score:{score} RSI:{rsi} vol:{rel_vol}x BB:{round(bb['pct']*100) if bb else 'n/a'}%")

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
    }

# ─── PUSH NOTIFICATION ────────────────────────────────────
def push_signal(sig):
    direction = '↑' if sig['trend'] == 'BULLISH' else '↓'
    vol_tag = '🔥' if sig['rel_vol'] >= 2.0 else '📈' if sig['rel_vol'] >= 1.5 else ''

    title = f"{direction} {sig['ticker']} — {sig['tier']} {sig['score']}% {vol_tag}"

    body = (
        f"${sig['price']:.2f} ({'+' if sig['chg']>0 else ''}{sig['chg']:.2f}%)\n"
        f"Signal: {sig['trend']} | RSI: {sig['rsi']} | Vol: {sig['rel_vol']}x\n"
        f"ATR: {sig['atr_pct']}%\n"
        f"→ Buy {sig['contract_type']} near ${sig['strike']:.2f} strike\n"
        f"→ Expiry 2–4 wks · price $0.02–$0.25/sh · OI > 50\n"
        f"→ Exit: +50% profit | −50% stop"
    )

    try:
        data = body.encode('utf-8')
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=data,
            headers={
                'Title': title,
                'Priority': 'high' if sig['score'] >= 65 else 'default',
                'Tags': 'chart_with_upwards_trend' if sig['trend']=='BULLISH' else 'chart_with_downwards_trend',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        print(f"  Pushed: {title}")
    except Exception as e:
        print(f"  Push error: {e}")

# ─── SUMMARY PUSH ──────────────────────────────────────────
def push_summary(signals):
    if not signals:
        try:
            data = "No setups met scoring threshold tonight. Try again tomorrow.".encode()
            req = urllib.request.Request(
                f"https://ntfy.sh/{NTFY_TOPIC}", data=data,
                headers={'Title': 'Nightly Scan — No Signals', 'Priority': 'low'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10): pass
        except: pass
        return

    strong = [s for s in signals if s['score'] >= 65]
    summary = (
        f"Scanned {len(WATCHLIST)} tickers\n"
        f"Signals found: {len(signals)} ({len(strong)} strong ★)\n"
        f"Best: {', '.join([s['ticker'] for s in signals[:3]])}"
    )
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=summary.encode(),
            headers={
                'Title': f"📊 Nightly Scan Complete — {len(signals)} signals",
                'Priority': 'default',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10): pass
    except: pass

# ─── MAIN ──────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"Nightly Scanner — {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    print(f"Tickers: {len(WATCHLIST)} | Delay: {DELAY}s | Free tier")
    print(f"{'='*50}\n")

    if not API_KEY:
        print("ERROR: POLYGON_KEY secret not set in GitHub Actions")
        return

    signals = []

    for i, ticker in enumerate(WATCHLIST):
        print(f"[{i+1}/{len(WATCHLIST)}] {ticker}")
        sig = analyze(ticker)
        if sig:
            signals.append(sig)
            push_signal(sig)
            time.sleep(2)  # small pause between pushes so phone isn't spammed
        time.sleep(DELAY)

    # Sort by score, push summary
    signals.sort(key=lambda s: s['score'], reverse=True)
    push_summary(signals)

    print(f"\n{'='*50}")
    print(f"Done. {len(signals)} signals found.")
    if signals:
        print("\nTop signals:")
        for s in signals[:5]:
            print(f"  {s['ticker']:6} {s['trend']:8} score:{s['score']} {s['contract_type']} near ${s['strike']:.2f}")
    print(f"{'='*50}\n")

if __name__ == '__main__':
    main()
