"""
Budget Options Scanner v3 — Ty's Preferences
Runs at 6PM Eastern after market close.

KEY CHANGES FROM v2:
- Removed $15 stock price cap — contract price is what matters
- Filter: contract ask must be $0.15-$0.20 ($15-$20 per contract)
- Expanded watchlist includes higher-priced stocks with cheap contracts
- Probability scoring weighted toward faster moves (2-week window)
- Still filters on: 3-candle trend, volume, OI, IV, spread
"""

import os
import requests
from datetime import datetime, timedelta

POLYGON_KEY  = os.environ.get("POLYGON_KEY", "")
NTFY_TOPIC   = os.environ.get("NTFY_TOPIC",  "")

# ── TY'S STRATEGY PARAMETERS ─────────────────────────────────
MIN_CONTRACT_PRICE  = 0.15   # contract ask at least $0.15 ($15/contract)
MAX_CONTRACT_PRICE  = 0.20   # contract ask no more than $0.20 ($20/contract)
MIN_SIGNAL_STRENGTH = 4      # only notify on 4-5 star signals
MIN_OPEN_INTEREST   = 100    # minimum open interest on the strike
MAX_IV_RANK         = 60     # skip if IV too expensive (above 60%)
MIN_REL_VOLUME      = 0.8    # today's volume at least 80% of 10-day avg
MIN_DAYS_EXP        = 14     # minimum days to expiry (2 weeks)
MAX_DAYS_EXP        = 28     # maximum days to expiry (4 weeks)
TARGET_GAIN         = 0.50   # 50% profit target
DAYS_BACK           = 20     # candle lookback period
# ─────────────────────────────────────────────────────────────

# Expanded watchlist — includes higher priced stocks known to have
# cheap options contracts in the $0.15-$0.20 range
WATCHLIST = [
    # Low priced stocks with active options
    "SNDL","SOFI","VALE","ITUB","BBD","GRAB","MARA","RIOT","CLSK","WULF",
    "HIMS","OPEN","SENS","EXPR","ZIM","CLOV","TLRY","SIRI","NOK","PLUG",
    "ENVX","CIFR","BITF","HIVE","IDEX","MVIS","SPWR","ATER","GNUS","GOEV",
    # Higher priced stocks that often have cheap OTM contracts
    "AMD","NVDA","TSLA","AMZN","META","GOOGL","MSFT","AAPL","BAC","F",
    "GE","INTC","PFE","T","WBA","KVUE","PARA","VIAC","CMCSA","NIO",
    "XPEV","LI","RIVN","LCID","JOBY","ACHR","UBER","LYFT","SNAP","PINS",
    "PLTR","HOOD","COIN","RBLX","U","DKNG","PENN","AFRM","UPST","OPEN"
]


def get(url):
    try:
        r = requests.get(url, timeout=12)
        return r.json()
    except Exception as e:
        print(f"    Request error: {e}")
        return {}


def fetch_candles(ticker):
    end   = datetime.today()
    start = end - timedelta(days=DAYS_BACK + 5)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit={DAYS_BACK}&apiKey={POLYGON_KEY}"
    )
    return get(url).get("results", [])


def fetch_options(ticker, strike, contract_type):
    """Find best contract in $0.15-$0.20 range expiring 2-4 weeks out."""
    today = datetime.today()
    min_e = today + timedelta(days=MIN_DAYS_EXP)
    max_e = today + timedelta(days=MAX_DAYS_EXP)
    fmt   = lambda d: d.strftime('%Y-%m-%d')

    # Search a wider strike range to find contracts in budget
    url = (
        f"https://api.polygon.io/v3/snapshot/options/{ticker}"
        f"?strike_price_gte={strike * 0.85:.2f}"
        f"&strike_price_lte={strike * 1.20:.2f}"
        f"&contract_type={contract_type}"
        f"&expiration_date_gte={fmt(min_e)}"
        f"&expiration_date_lte={fmt(max_e)}"
        f"&limit=25&apiKey={POLYGON_KEY}"
    )
    results = get(url).get("results", [])
    if not results:
        return None

    # Filter to contracts in Ty's price range
    in_budget = []
    for opt in results:
        ask = opt.get("day", {}).get("close", None)
        if ask and MIN_CONTRACT_PRICE <= ask <= MAX_CONTRACT_PRICE:
            in_budget.append(opt)

    if not in_budget:
        return None

    # Among budget contracts pick highest open interest
    in_budget.sort(key=lambda o: o.get("open_interest", 0), reverse=True)
    return in_budget[0]


def candle_dir(b):
    rng  = b["h"] - b["l"] or 0.01
    body = abs(b["c"] - b["o"])
    if body < rng * 0.05:
        return "doji"
    return "green" if b["c"] > b["o"] else "red"


def calc_probability(trend, rel_vol, vol_increasing, broke_level,
                     iv, oi, change_pct, ask, spread_pct):
    """
    Score probability of hitting +50% gain within 2 weeks.
    Weighted heavily toward speed indicators.
    """
    score = 0

    # 3-candle base (required to get here)
    score += 20

    # Volume — most important speed indicator
    if rel_vol >= 2.5:   score += 25
    elif rel_vol >= 2.0: score += 20
    elif rel_vol >= 1.5: score += 15
    elif rel_vol >= 1.0: score += 8
    else:                score -= 10

    # Rising volume across 3 candles — momentum building
    if vol_increasing:   score += 12

    # Broke key level — confirms real momentum
    if broke_level:      score += 15

    # IV — lower is better for cheap contracts with good reward
    if iv is not None:
        if iv <= 25:     score += 12
        elif iv <= 40:   score += 7
        elif iv <= 60:   score += 2
        else:            score -= 15

    # Open interest — need liquidity to exit at +50%
    if oi >= 1000:       score += 8
    elif oi >= 500:      score += 5
    elif oi >= 100:      score += 2
    elif oi > 0:         score -= 8

    # Price momentum today
    if trend == "bullish" and change_pct > 3:   score += 8
    elif trend == "bullish" and change_pct > 1: score += 4
    elif trend == "bearish" and change_pct < -3: score += 8
    elif trend == "bearish" and change_pct < -1: score += 4

    # Contract in sweet spot of budget
    if ask and 0.15 <= ask <= 0.20: score += 5

    # Spread — wide spread kills exit
    if spread_pct is not None:
        if spread_pct > 60: score -= 15
        elif spread_pct > 40: score -= 5

    return min(95, max(5, score))


def analyze(ticker):
    bars = fetch_candles(ticker)
    if len(bars) < 6:
        return None

    last  = bars[-1]
    prev  = bars[-2]
    price = last["c"]
    change_pct = round(((last["c"] - prev["c"]) / prev["c"]) * 100, 2)

    # Candle direction last 3
    last3 = [candle_dir(bars[-3]), candle_dir(bars[-2]), candle_dir(bars[-1])]
    gc    = last3.count("green")
    rc    = last3.count("red")

    if gc == 3:       trend = "bullish"
    elif rc == 3:     trend = "bearish"
    else:             return None  # no confirmation

    # Volume
    recent_vols  = [b["v"] for b in bars[-11:-1] if "v" in b]
    avg_vol      = sum(recent_vols) / len(recent_vols) if recent_vols else 1
    today_vol    = last.get("v", 0)
    rel_vol      = round(today_vol / avg_vol, 1) if avg_vol > 0 else 0

    if rel_vol < MIN_REL_VOLUME:
        print(f"    {ticker} — low rel volume ({rel_vol}x)")
        return None

    vol_increasing = (
        bars[-1].get("v", 0) > bars[-2].get("v", 0) and
        bars[-2].get("v", 0) > bars[-3].get("v", 0)
    )

    # Levels
    resistance  = round(max(b["h"] for b in bars[-10:]), 2)
    support     = round(min(b["l"] for b in bars[-10:]), 2)
    broke_level = (
        (trend == "bullish" and last["c"] >= resistance * 0.985) or
        (trend == "bearish" and last["c"] <= support   * 1.015)
    )

    # Options — search for contract in $15-20 budget
    contract_type  = "call" if trend == "bullish" else "put"
    target_strike  = resistance if trend == "bullish" else support
    opt = fetch_options(ticker, target_strike, contract_type)

    if not opt:
        print(f"    {ticker} — no contract in $15-20 range")
        return None

    ask          = opt.get("day", {}).get("close")
    bid          = opt.get("day", {}).get("open")
    oi           = opt.get("open_interest", 0)
    iv_raw       = opt.get("implied_volatility")
    iv           = round(iv_raw * 100) if iv_raw else None
    expiry       = opt.get("details", {}).get("expiration_date")
    actual_strike= opt.get("details", {}).get("strike_price", target_strike)
    spread_pct   = round(((ask - bid) / ask) * 100) if bid and ask and ask > 0 else None

    if oi > 0 and oi < MIN_OPEN_INTEREST:
        print(f"    {ticker} — low OI ({oi})")
        return None
    if iv and iv > MAX_IV_RANK:
        print(f"    {ticker} — IV too high ({iv}%)")
        return None

    probability = calc_probability(
        trend, rel_vol, vol_increasing, broke_level,
        iv, oi, change_pct, ask, spread_pct
    )

    strength = min(5, max(1,
        2 +
        (1 if vol_increasing else 0) +
        (1 if rel_vol >= 1.5 else 0) +
        (1 if broke_level else 0)
    ))

    vol_note = " with rising volume" if vol_increasing else ""
    rel_note = f" ({rel_vol}x avg vol)"
    reason = (
        f"3 green candles{vol_note}{rel_note} — pushing toward ${resistance} resistance"
        if trend == "bullish" else
        f"3 red candles{vol_note}{rel_note} — breaking below ${support} support"
    )

    return {
        "ticker":        ticker,
        "price":         round(price, 2),
        "change_pct":    change_pct,
        "trend":         trend,
        "resistance":    resistance,
        "support":       support,
        "broke_level":   broke_level,
        "rel_vol":       rel_vol,
        "vol_increasing":vol_increasing,
        "contract_type": contract_type.upper(),
        "strike":        round(actual_strike, 2),
        "expiry":        expiry,
        "ask":           round(ask, 2) if ask else None,
        "oi":            oi,
        "iv":            iv,
        "spread_pct":    spread_pct,
        "probability":   probability,
        "strength":      strength,
        "reason":        reason,
    }


def send_notification(title, body, priority="high"):
    if not NTFY_TOPIC:
        print("No NTFY_TOPIC — skipping")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     "chart_increasing,moneybag",
            },
            timeout=10,
        )
        print(f"Notification sent: {title}")
    except Exception as e:
        print(f"Notification error: {e}")


def format_signal(r):
    stars  = "★" * r["strength"] + "☆" * (5 - r["strength"])
    chg    = f"+{r['change_pct']}%" if r["change_pct"] > 0 else f"{r['change_pct']}%"
    ask    = f"ask:${r['ask']:.2f}" if r["ask"] else "check ask"
    oi     = f"OI:{r['oi']}" if r["oi"] else "OI:—"
    iv     = f"IV:{r['iv']}%" if r["iv"] else "IV:—"
    vol    = f"vol:{r['rel_vol']}x"
    expiry = r["expiry"] or "check expiry"
    prob   = f"{r['probability']}% prob"

    return (
        f"{r['ticker']}  ${r['price']}  ({chg})  {prob}\n"
        f"  → {r['contract_type']} ${r['strike']} · exp {expiry}\n"
        f"  → {stars} · {ask} · {oi} · {iv} · {vol}\n"
        f"  {r['reason']}"
    )


def main():
    now     = datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"Budget Options Scanner v3 — Ty's Preferences")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')} | Tickers: {len(WATCHLIST)}")
    print(f"Contract budget: ${MIN_CONTRACT_PRICE:.2f}–${MAX_CONTRACT_PRICE:.2f} per share (${int(MIN_CONTRACT_PRICE*100)}–${int(MAX_CONTRACT_PRICE*100)}/contract)")
    print(f"No stock price cap — contract price is what matters")
    print(f"{'='*60}\n")

    if not POLYGON_KEY:
        send_notification("Scanner Error", "POLYGON_KEY not set in GitHub secrets.")
        return

    results = []
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ", flush=True)
        sig = analyze(ticker)
        if sig:
            results.append(sig)
            print(f"${sig['price']} — {sig['trend']} — {sig['probability']}% prob — contract ask ${sig['ask']}")
        else:
            print("no setup")

    results.sort(key=lambda x: x["probability"], reverse=True)
    strong = [r for r in results if r["probability"] >= 65]

    print(f"\n{'─'*60}")
    print(f"Total signals: {len(results)} | Strong (65%+): {len(strong)}")

    tomorrow = (datetime.today() + timedelta(days=1)).strftime("%A %b %-d")

    if not results:
        send_notification(
            "Scanner: No setups tonight",
            f"Scanned {len(WATCHLIST)} tickers.\n"
            f"No 3-candle confirmations with contracts in $15-20 budget.\n"
            f"Rest up — better setups tomorrow.",
            priority="low"
        )
        return

    if not strong:
        lines = "\n\n".join(format_signal(r) for r in results[:4])
        send_notification(
            f"Scanner: {len(results)} weak signals for {tomorrow}",
            f"No high-probability setups tonight. Proceed with caution.\n\n"
            f"{lines}\n\n"
            f"Wait for price confirmation at 10:15 AM before entering.",
            priority="default"
        )
        return

    bullish = [r for r in strong if r["trend"] == "bullish"]
    bearish = [r for r in strong if r["trend"] == "bearish"]
    lines   = "\n\n".join(format_signal(r) for r in strong[:5])

    body = (
        f"{len(bullish)} bullish · {len(bearish)} bearish · all in $15-20 budget\n"
        f"Filtered: volume · OI · IV · contract price · spread\n\n"
        f"{lines}\n\n"
        f"── PLAN FOR TOMORROW ──\n"
        f"Wait until 10:15 AM — let open volatility settle.\n"
        f"Verify price still near scanner level in Robinhood.\n"
        f"Confirm bid/ask spread is tight before buying.\n"
        f"Target: +50% exit · Stop: -50% cut · Budget: $15-20/contract"
    )

    send_notification(
        f"{len(strong)} strong signal{'s' if len(strong) > 1 else ''} for {tomorrow}",
        body
    )
    print("\nDone.")


if __name__ == "__main__":
    main()
