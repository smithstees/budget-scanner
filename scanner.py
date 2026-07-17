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

import config
try:
    import scanner_quality as sq
except Exception as e:
    print(f"scanner_quality unavailable: {e}")
    sq = None

def _ascii(s):
    # ntfy Title header must be latin-1 safe. Strip fancy unicode.
    return (s.replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u2022", "*").replace("\u00b7", "-")
             .replace("\u2605", "*").replace("\u2606", "*")
             .replace("\u26a1", "!").encode("ascii", "ignore").decode("ascii"))

# CONFIG (values come from config.py; env vars are already respected there)
API_KEY   = os.environ.get('POLYGON_KEY', '')
NTFY_TOPIC = config.NTFY_TOPIC
BASE_URL  = 'https://api.massive.com'

# Watchlist + price band + push threshold all sourced from config.py
WATCHLIST = config.WATCHLIST_TICKERS
DELAY = config.POLYGON_DELAY_SEC
STOCK_PRICE_MIN = config.STOCK_PRICE_MIN
STOCK_PRICE_MAX = config.STOCK_PRICE_MAX
NOTIFY_MIN_SCORE = config.NOTIFY_MIN_SCORE

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

    # Prefer real chain data when available, fall back to ATR estimate
    if sig.get('real_strike'):
        strike     = sig['real_strike']
        expiry     = sig['real_expiry']
        est_contract = sig['real_est_contract']
        delta_info = f" Δ{sig['real_delta']}"
        oi_info    = f" OI={sig['real_oi']}"
        iv_info    = f" IV={sig['real_iv']}"
    else:
        strike     = sig['strike']
        expiry     = "30-45 days out"
        est_contract = round(sig['est_cost'] * 100)
        delta_info = ""
        oi_info    = " OI>=100"
        iv_info    = ""

    ivr_info = f" IVR={sig['iv_rank']}" if sig.get('iv_rank') is not None else ""

    # Delta-exit target: sell when stock is 65% of the way from current to strike
    if sig['trend'] == 'BULLISH':
        sell_zone = round(sig['price'] + 0.65 * (strike - sig['price']), 2)
    else:
        sell_zone = round(sig['price'] - 0.65 * (sig['price'] - strike), 2)
    body = (
        f"${sig['price']:.2f} ({'+' if sig['chg']>0 else ''}{sig['chg']:.2f}%)\n"
        f"Signal: {sig['trend']} | RSI: {sig['rsi']} | Vol: {sig['rel_vol']}x"
        f"{ivr_info}\n"
        f"ATR: {sig['atr_pct']}%\n"
        f"Buy {sig['contract_type']} strike ${strike:.2f}{delta_info}{iv_info}{oi_info}\n"
        f"Expiry {expiry} | est ~${est_contract}/contract\n"
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

def enrich_and_filter(sig, regime, verbose=True):
    """
    Enrich a raw signal with quality data (IV rank, earnings, real strike,
    liquidity) and decide whether it should still be pushed given quality
    filters + SPY regime.

    Returns (sig, should_push_ok, reasons_blocked_list).

    In strict mode (config.QUALITY_STRICT), any block reason → no push.
    In loose mode, reasons are logged into the signal but push proceeds.
    """
    reasons = []
    if sq is None:
        return sig, True, reasons

    ticker = sig['ticker']

    # IV Rank ceiling (skip long premium when IV is elevated)
    ivr = sq.iv_rank(ticker)
    if ivr is not None:
        sig['iv_rank'] = ivr
        if ivr > config.IV_RANK_CEILING:
            reasons.append(f"IV Rank {ivr} > {config.IV_RANK_CEILING} (long options expensive)")

    # Earnings blackout
    earnings_soon = sq.has_earnings_within(ticker, config.EARNINGS_BLACKOUT_DAYS)
    if earnings_soon is True:
        sig['earnings_within_14d'] = True
        reasons.append(f"Earnings within {config.EARNINGS_BLACKOUT_DAYS}d (IV crush risk)")

    # Real delta strike from Nasdaq chain
    direction = sig.get('trend', 'BULLISH')
    # Target ~35 days out (middle of 30-45 window)
    real = sq.target_delta_strike(ticker, sig['price'], 35, direction)
    if real:
        sig['real_strike']       = real['strike']
        sig['real_expiry']       = real['expiry']
        sig['real_tte_days']     = real['tte_days']
        sig['real_delta']        = real['delta']
        sig['real_iv']           = real['iv']
        sig['real_mid']          = real['mid']
        sig['real_bid']          = real['bid']
        sig['real_ask']          = real['ask']
        sig['real_oi']           = real['oi']
        sig['real_spread_pct']   = real['spread_pct']
        sig['real_est_contract'] = round(real['mid'] * 100)
        # Liquidity check
        if not sq.is_liquid(real):
            reasons.append(
                f"Illiquid: OI={real['oi']} spread={int(real['spread_pct']*100)}%"
            )
    else:
        reasons.append("No delta-0.25–0.35 strike found in chain")

    # SPY regime bias
    if regime == 'BEARISH' and direction == 'BULLISH' and sig.get('score', 0) < 65:
        reasons.append("SPY < 200d SMA; CALL below high-conviction score cutoff")
    elif regime == 'BULLISH' and direction == 'BEARISH' and sig.get('score', 0) < 65:
        reasons.append("SPY > 200d SMA; PUT below high-conviction score cutoff")

    sig['quality_blocks'] = reasons
    ok = (not reasons) if config.QUALITY_STRICT else True

    if verbose and reasons:
        for r in reasons:
            print(f"  [quality]  {r}")
    return sig, ok, reasons


def main():
    print(f"\n{'='*50}")
    print(f"Nightly Scanner -- {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    print(f"Tickers: {len(WATCHLIST)} | Delay: {DELAY}s | Free tier")
    print(f"Stock band: ${STOCK_PRICE_MIN}-${STOCK_PRICE_MAX} | Push threshold: score>={NOTIFY_MIN_SCORE}")
    if sq is not None:
        regime = sq.spy_regime()
        det = sq.spy_details()
        print(f"SPY regime: {regime}  (last={det.get('last')}, 200d SMA={det.get('sma')})")
        print(f"Quality filters: IV≤{config.IV_RANK_CEILING} | earnings blackout {config.EARNINGS_BLACKOUT_DAYS}d | "
              f"OI≥{config.MIN_OPEN_INTEREST} | spread≤{int(config.MAX_SPREAD_PCT_OF_MID*100)}% | "
              f"delta {config.TARGET_DELTA_MIN}–{config.TARGET_DELTA_MAX} | "
              f"strict={config.QUALITY_STRICT}")
    else:
        regime = 'NEUTRAL'
        print("Quality module unavailable (running unfiltered)")
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

    # First pass: collect all raw signals (no push yet)
    raw = []
    for i, ticker in enumerate(WATCHLIST):
        print(f"[{i+1}/{len(WATCHLIST)}] {ticker}")
        s = analyze(ticker)
        if s:
            raw.append(s)
        time.sleep(DELAY)

    if not raw:
        push_summary([], 0)
        return

    # Sort by score, then apply quality + sector caps
    raw.sort(key=lambda s: s.get('score', 0), reverse=True)

    sector_cap = sq.SectorCap() if sq is not None else None

    for sig in raw:
        sig, ok, reasons = enrich_and_filter(sig, regime, verbose=False)
        signals.append(sig)

        should_push = ok and sig['score'] >= NOTIFY_MIN_SCORE

        # Sector cap only limits *pushes*, not the log
        if should_push and sector_cap is not None:
            sector = config.sector_of(sig['ticker'])
            if not sector_cap.try_accept(sector):
                sig.setdefault('quality_blocks', []).append(
                    f"Sector cap hit ({sector})"
                )
                should_push = False

        if should_push:
            push_signal(sig)
            pushed += 1
            time.sleep(2)

        if log_signal is not None:
            log_signal('nightly', sig, pushed=should_push)

    push_summary(signals, pushed)

    print(f"\n{'='*50}")
    print(f"Done. {len(signals)} setups found, {pushed} pushed to phone.")
    if signals:
        print("\nTop signals (by score):")
        for s in signals[:8]:
            marker = "PUSH" if s['score'] >= NOTIFY_MIN_SCORE else "----"
            blocks = s.get('quality_blocks', [])
            block_str = f"  [BLOCKED: {'; '.join(blocks)}]" if blocks else ""
            real_str = f" real:${s.get('real_strike',0):.2f}@d{s.get('real_delta',0):.2f}" if s.get('real_strike') else ""
            print(f"  {marker} {s['ticker']:6} {s['trend']:8} score:{s['score']} "
                  f"{s['contract_type']} near ${s['strike']:.2f} est ${round(s['est_cost']*100)}"
                  f"{real_str}{block_str}")
    print(f"{'='*50}\n")

if __name__ == '__main__':
    main()
