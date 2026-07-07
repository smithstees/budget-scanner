#!/usr/bin/env python3
"""
Wheel / Cash-Secured Put Scanner
Finds stocks in your budget where selling a cash-secured put makes sense:
  - Stock price low enough that 100 shares fits your account (<$10)
  - Trading near recent support (higher chance the put expires worthless)
  - Enough volatility that the put actually pays meaningful premium
  - Not in a death spiral (recent RSI not below 20, price not down >15% in a week)

The strategy in plain English:
  1. Pick a strike a bit BELOW current price (5-10% OTM)
  2. Sell the put, collect ~$15-$40 premium immediately
  3. If stock stays above strike -> keep the money, no assignment (best case)
  4. If stock drops below strike -> you buy 100 shares at strike price
     (which was already below today's price, and net of premium, even lower)
  5. Once you own 100 shares, sell covered calls against them for more income

Uses Yahoo Finance intraday (no API key). Trigger from GitHub Actions
manually or on a Sunday-evening schedule.

Pushes to ntfy.sh topic: ragebudgetopt
"""

import os, time, math, json, urllib.request
from datetime import datetime, timedelta

NTFY_TOPIC = os.environ.get('NTFY_TOPIC', 'ragebudgetopt')
YAHOO_URL  = 'https://query1.finance.yahoo.com/v8/finance/chart/'

# Stocks that make reasonable wheel candidates: sub-$10 (so 100 shares
# is <$1000 collateral), reasonable volume, well-known company you'd
# actually be OK holding for weeks if assigned.
WHEEL_WATCHLIST = [
  # Sub-$10 names you'd genuinely hold if assigned
  'SOFI','JBLU','F','NIO','SNAP','GRAB','PLUG','NOK',
  'RIVN','LCID','JOBY','ACHR','SIRI',
  'OPEN','TLRY','HIMS','SENS','MARA','RIOT','CLSK',
  'PINS','SNDL','WKHS','LYFT','ENVX','VALE','ITUB','BBD',
  'CIFR','WULF','XPEV','LI',
]

# Max collateral you'd want to lock up per position (100 shares * price)
MAX_COLLATERAL = 1000  # so max stock price = $10
MIN_PRICE      = 2.00
MAX_PRICE      = MAX_COLLATERAL / 100

# Only flag when the CSP would collect at least this premium (annualized)
MIN_ANNUAL_YIELD = 0.15  # 15% annualized on collateral


def fetch_daily(ticker, days=45):
    """Get daily bars via Yahoo (public, no key)."""
    url = f"{YAHOO_URL}{ticker}?interval=1d&range=3mo"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; wheel-scanner/1.0)'
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data.get('chart', {}).get('result', [])
        if not result:
            return [], None
        r0 = result[0]
        meta = r0.get('meta', {})
        prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
        ts = r0.get('timestamp', [])
        q  = (r0.get('indicators', {}).get('quote', [{}])[0])
        bars = []
        for i in range(len(ts)):
            if q.get('close', [None])[i] is None:
                continue
            bars.append({
                't': ts[i],
                'o': q['open'][i]  or q['close'][i],
                'h': q['high'][i]  or q['close'][i],
                'l': q['low'][i]   or q['close'][i],
                'c': q['close'][i],
                'v': (q.get('volume') or [0])[i] or 0,
            })
        return bars, prev_close
    except Exception as e:
        print(f"  [{ticker}] fetch error: {e}")
        return [], None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    g, l = 0, 0
    for i in range(len(closes) - period, len(closes)):
        c = closes[i] - closes[i-1]
        if c > 0: g += c
        else:     l += abs(c)
    ag, al = g / period, l / period
    if al == 0: return 100
    rs = ag / al
    return round(100 - (100 / (1 + rs)))


def analyze(ticker):
    bars, _ = fetch_daily(ticker)
    if len(bars) < 22:
        print(f"  [{ticker}] not enough data ({len(bars)} bars)")
        return None

    price = bars[-1]['c']
    if price < MIN_PRICE or price > MAX_PRICE:
        print(f"  [{ticker}] ${price:.2f} outside ${MIN_PRICE:.2f}-${MAX_PRICE:.2f} band")
        return None

    closes = [b['c'] for b in bars]
    rsi = calc_rsi(closes, 14)

    # 5-day and 20-day change
    chg_5d  = ((price - closes[-6])  / closes[-6])  * 100 if len(closes) >= 6 else 0
    chg_20d = ((price - closes[-21]) / closes[-21]) * 100 if len(closes) >= 21 else 0

    # Support: 20-day low
    support_20 = min(b['l'] for b in bars[-20:])
    support_recent = min(b['l'] for b in bars[-5:])

    # Near support means better wheel setup (put more likely to expire worthless)
    near_support = price <= support_20 * 1.10  # within 10% of 20-day low

    # Skip if it's a knife-catch (down >15% in 5 days OR RSI < 20)
    if chg_5d < -15:
        print(f"  [{ticker}] ${price:.2f} down {chg_5d:.1f}% in 5d — knife")
        return None
    if rsi is not None and rsi < 20:
        print(f"  [{ticker}] ${price:.2f} RSI {rsi} — bleeding")
        return None

    # Estimate realized volatility (rough IV proxy)
    returns = []
    for i in range(1, len(closes)):
        returns.append((closes[i] - closes[i-1]) / closes[i-1])
    if len(returns) < 20:
        return None
    mean = sum(returns[-20:]) / 20
    variance = sum((r - mean)**2 for r in returns[-20:]) / 20
    daily_vol = math.sqrt(variance)
    annual_vol = daily_vol * math.sqrt(252)  # rough IV proxy

    # Recommended put strike: 5-10% OTM, snapping to strike ladder
    # $0.50 steps under $10, $1 steps at $10+
    step = 0.50 if price < 10 else 1.00
    target_strike = math.floor((price * 0.93) / step) * step
    if target_strike < MIN_PRICE:
        return None

    # Rough premium estimate for a 30-day put ~7% OTM using annual vol
    # This is a very crude Black-Scholes-lite approximation
    otm_pct = (price - target_strike) / price
    # Premium as % of strike, using time-scaled vol
    days = 30
    t = days / 365
    # Expected premium ~ strike * annual_vol * sqrt(t) * exp(-otm_pct * factor)
    prem_pct = annual_vol * math.sqrt(t) * math.exp(-otm_pct * 5) * 0.4
    prem_pct = max(0.005, min(0.10, prem_pct))  # sanity clamp: 0.5%-10% of strike
    premium_per_share = round(target_strike * prem_pct, 2)
    premium_contract = round(premium_per_share * 100)
    collateral = round(target_strike * 100, 2)

    # Annualized yield on collateral
    annual_yield = (premium_per_share / target_strike) * (365 / days)

    if annual_yield < MIN_ANNUAL_YIELD:
        print(f"  [{ticker}] ${price:.2f} yield only {annual_yield*100:.1f}% ann — skip")
        return None

    # Score the setup
    score = 30
    if near_support:              score += 20
    if rsi is not None and rsi < 40: score += 15
    elif rsi is not None and rsi < 50: score += 8
    if chg_5d < -5:               score += 10  # recent dip = better entry
    if chg_20d > -10:             score += 5   # not in freefall
    if annual_yield > 0.30:       score += 15
    elif annual_yield > 0.20:     score += 8
    if annual_vol > 0.40:         score += 8   # some vol = premium

    score = min(95, max(5, score))
    tier = 'STRONG' if score >= 65 else 'MODERATE' if score >= 50 else 'WEAK'

    print(f"  [{ticker}] ${price:.2f} strike ${target_strike:.2f} "
          f"prem ~${premium_contract} collat ${collateral:.0f} "
          f"yield {annual_yield*100:.0f}% ann · score {score}")

    return {
        'ticker': ticker,
        'price': price,
        'chg_5d': round(chg_5d, 1),
        'chg_20d': round(chg_20d, 1),
        'rsi': rsi,
        'support_20': round(support_20, 2),
        'near_support': near_support,
        'strike': round(target_strike, 2),
        'premium_share': premium_per_share,
        'premium_contract': premium_contract,
        'collateral': collateral,
        'annual_vol_pct': round(annual_vol * 100),
        'annual_yield': annual_yield,
        'days': days,
        'score': score,
        'tier': tier,
    }


def push(title, body, priority='default'):
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode('utf-8'),
            headers={
                'Title': title.encode('utf-8'),
                'Priority': priority,
                'Tags': 'moneybag,seedling',
                'Content-Type': 'text/plain; charset=utf-8',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e:
        print(f"push err: {e}")


def main():
    print(f"\n{'='*60}")
    print(f"Wheel / Cash-Secured Put Scanner")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Watchlist: {len(WHEEL_WATCHLIST)} tickers · budget: <${MAX_PRICE:.2f}/share")
    print(f"Min annual yield: {MIN_ANNUAL_YIELD*100:.0f}%")
    print(f"{'='*60}\n")

    results = []
    for i, t in enumerate(WHEEL_WATCHLIST):
        print(f"[{i+1}/{len(WHEEL_WATCHLIST)}] {t}")
        r = analyze(t)
        if r:
            results.append(r)
        time.sleep(0.3)

    results.sort(key=lambda r: r['score'], reverse=True)

    if not results:
        push("Wheel Scan — no CSP setups",
             "No stocks meet the wheel criteria today. "
             "Market may need to sell off a bit for premiums to be worthwhile.",
             priority='low')
        return

    # Build push body
    top = results[:5]
    lines = []
    for r in top:
        marker = "⭐" if r['tier'] == 'STRONG' else "·"
        lines.append(
            f"{marker} {r['ticker']}  ${r['price']:.2f}  ({r['chg_5d']:+.1f}% 5d)\n"
            f"  Sell {r['days']}d PUT strike ${r['strike']:.2f}\n"
            f"  Collect ~${r['premium_contract']} · Collateral ${r['collateral']:.0f}\n"
            f"  Yield: {r['annual_yield']*100:.0f}% annualized · Score {r['score']}"
        )
    body = (
        "Cash-Secured Put ideas (pick ONE):\n\n" +
        "\n\n".join(lines) +
        "\n\n── HOW TO PLACE ──\n"
        "1. In Robinhood options: pick the ticker\n"
        "2. Choose expiry ~30 days out\n"
        "3. Select the STRIKE shown above\n"
        "4. Action: SELL to OPEN one PUT contract\n"
        "5. Confirm cash collateral is locked (=strike x 100)\n\n"
        "OUTCOMES:\n"
        "✓ Stock stays above strike → keep premium, put expires worthless\n"
        "✓ Stock drops below strike → you're assigned 100 shares at strike\n"
        "  (which is below today's price · net cost even lower with premium)\n\n"
        "Only do this on stocks you'd HAPPILY own for weeks."
    )

    strong = [r for r in results if r['tier'] == 'STRONG']
    title = f"Wheel: {len(strong)} strong CSP idea(s)" if strong else f"Wheel: {len(top)} CSP ideas"
    push(title, body, priority='default' if strong else 'low')

    print(f"\n{'='*60}")
    print(f"Done. {len(results)} candidates ({len(strong)} strong).")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
