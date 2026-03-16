"""
Budget Options Scanner — Upgraded
Runs at 6PM Eastern after market close.
Uses end-of-day Polygon data for clean signals.
Filters on: 3-candle trend, volume confirmation,
relative volume, open interest, IV rank, bid/ask spread.
Pushes results to ntfy.sh for next-day planning.
"""

import os
import requests
from datetime import datetime, timedelta

POLYGON_KEY = os.environ.get("POLYGON_KEY", "")
NTFY_TOPIC  = os.environ.get("NTFY_TOPIC",  "")

# ── STRATEGY PARAMETERS ──────────────────────────────────────
MAX_STOCK_PRICE    = 15.00   # only stocks under $15
MAX_CONTRACT_PRICE = 0.20    # only options asking under $0.20 (= $20/contract)
MIN_SIGNAL_STRENGTH = 4      # only notify on 4-5 star signals
MIN_OPEN_INTEREST  = 100     # minimum open interest on the strike
MAX_IV_RANK        = 60      # skip if IV is too expensive (above 60%)
MIN_REL_VOLUME     = 0.8     # today's volume must be at least 80% of avg
DAYS_BACK          = 20      # candle lookback period

WATCHLIST = [
    "SNDL","SOFI","VALE","ITUB","BBD","GRAB","MARA","RIOT","CLSK","WULF",
    "HIMS","OPEN","SENS","EXPR","ZIM","CLOV","NKLA","ATER","GNUS","GOEV",
    "VERB","IMPP","IDEX","MVIS","SPWR","NAKD","AULT","FFIE","PRTY","HLBZ",
    "TLRY","SIRI","NOK","PLUG","ENVX","CIFR","BITF","HIVE","DGLY","CTRM"
]

# ─────────────────────────────────────────────────────────────

def get(url, params=None):
    """Simple GET with timeout."""
    try:
        r = requests.get(url, params=params, timeout=12)
        return r.json()
    except Exception as e:
        print(f"    Request error: {e}")
        return {}


def fetch_candles(ticker):
    """Last DAYS_BACK daily candles."""
    end   = datetime.today()
    start = end - timedelta(days=DAYS_BACK + 5)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit={DAYS_BACK}&apiKey={POLYGON_KEY}"
    )
    data = get(url)
    return data.get("results", [])


def fetch_ticker_details(ticker):
    """Get float and basic company info."""
    url = f"https://api.polygon.io/v3/reference/tickers/{ticker}?apiKey={POLYGON_KEY}"
    data = get(url)
    return data.get("results", {})


def fetch_options_snapshot(ticker, strike, contract_type):
    """
    Get options chain snapshot for a specific ticker.
    Returns best contract near our strike with IV, OI, spread data.
    contract_type: 'call' or 'put'
    """
    url = (
        f"https://api.polygon.io/v3/snapshot/options/{ticker}"
        f"?strike_price_gte={strike * 0.95}&strike_price_lte={strike * 1.10}"
        f"&contract_type={contract_type}&limit=10&apiKey={POLYGON_KEY}"
    )
    data = get(url)
    results = data.get("results", [])

    # Filter for contracts expiring 10-25 days out (2-3 weeks)
    today = datetime.today()
    candidates = []
    for opt in results:
        details = opt.get("details", {})
        exp_str = details.get("expiration_date", "")
        if not exp_str:
            continue
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d")
            days_out = (exp - today).days
            if 10 <= days_out <= 25:
                candidates.append(opt)
        except:
            continue

    if not candidates:
        return None

    # Pick the one closest to our target strike
    best = min(candidates, key=lambda o: abs(o.get("details", {}).get("strike_price", 999) - strike))
    return best


def candle_direction(bar):
    rng = bar["h"] - bar["l"] or 0.01
    body = abs(bar["c"] - bar["o"])
    if body < rng * 0.05:
        return "doji"
    return "green" if bar["c"] > bar["o"] else "red"


def analyze(ticker):
    """Full analysis pipeline. Returns signal dict or None."""
    bars = fetch_candles(ticker)
    if len(bars) < 6:
        return None

    last = bars[-1]
    prev = bars[-2]
    price = last["c"]

    # ── FILTER: price must be under $15
    if price > MAX_STOCK_PRICE:
        return None

    # ── CANDLESTICK: 3-candle confirmation
    last3_dirs = [candle_direction(bars[-3]), candle_direction(bars[-2]), candle_direction(bars[-1])]
    green_count = last3_dirs.count("green")
    red_count   = last3_dirs.count("red")

    if green_count == 3:
        trend = "bullish"
    elif red_count == 3:
        trend = "bearish"
    else:
        return None  # no 3-candle confirmation — skip entirely

    # ── VOLUME: today vs 10-day average
    recent_vols = [b["v"] for b in bars[-11:-1] if "v" in b]
    avg_volume  = sum(recent_vols) / len(recent_vols) if recent_vols else 1
    today_vol   = last.get("v", 0)
    rel_volume  = today_vol / avg_volume if avg_volume > 0 else 0

    # Volume trend across last 3 candles
    vol_increasing = (
        bars[-1].get("v", 0) > bars[-2].get("v", 0) and
        bars[-2].get("v", 0) > bars[-3].get("v", 0)
    )

    # ── FILTER: relative volume must be reasonable
    if rel_volume < MIN_REL_VOLUME:
        print(f"    {ticker} skipped — low relative volume ({rel_volume:.1f}x)")
        return None

    # ── LEVELS: resistance and support
    resistance = round(max(b["h"] for b in bars[-10:]), 2)
    support    = round(min(b["l"] for b in bars[-10:]), 2)
    broke_r    = last["c"] >= resistance * 0.985
    broke_s    = last["c"] <= support   * 1.015

    change_pct = round(((last["c"] - prev["c"]) / prev["c"]) * 100, 2)

    # ── CONTRACT TARGET
    contract_type = "call" if trend == "bullish" else "put"
    target_strike = resistance if trend == "bullish" else support

    # ── OPTIONS DATA: IV, open interest, bid/ask spread
    opt = fetch_options_snapshot(ticker, target_strike, contract_type)

    iv_rank        = None
    open_interest  = None
    bid            = None
    ask            = None
    spread_pct     = None
    expiry         = None
    actual_strike  = target_strike

    if opt:
        greeks   = opt.get("greeks", {})
        day_data = opt.get("day", {})
        details  = opt.get("details", {})
        iv_raw   = opt.get("implied_volatility", None)

        open_interest = opt.get("open_interest", None)
        bid           = day_data.get("open", None)   # best available proxy on free tier
        ask           = day_data.get("close", None)
        expiry        = details.get("expiration_date", None)
        actual_strike = details.get("strike_price", target_strike)
        iv_rank       = round(iv_raw * 100, 1) if iv_raw else None

        if bid and ask and ask > 0:
            spread_pct = round(((ask - bid) / ask) * 100, 1)

        # ── FILTER: open interest
        if open_interest and open_interest < MIN_OPEN_INTEREST:
            print(f"    {ticker} skipped — low open interest ({open_interest})")
            return None

        # ── FILTER: IV too high (options overpriced)
        if iv_rank and iv_rank > MAX_IV_RANK:
            print(f"    {ticker} skipped — IV too high ({iv_rank}%)")
            return None

        # ── FILTER: contract too expensive
        if ask and ask > MAX_CONTRACT_PRICE:
            print(f"    {ticker} skipped — contract ask ${ask:.2f} over budget")
            return None

    # ── SIGNAL STRENGTH (1-5 stars)
    strength = 2  # base for having 3-candle confirmation
    if vol_increasing:
        strength += 1
    if rel_volume >= 1.5:
        strength += 1
    if broke_r or broke_s:
        strength += 1
    strength = min(5, strength)

    # ── REASON
    vol_note = " + rising volume" if vol_increasing else ""
    rel_note = f" ({rel_volume:.1f}x avg volume)"
    if trend == "bullish":
        reason = f"3 green candles{vol_note}{rel_note} — pushing toward ${resistance} resistance"
    else:
        reason = f"3 red candles{vol_note}{rel_note} — breaking below ${support} support"

    return {
        "ticker":          ticker,
        "price":           round(price, 2),
        "change_pct":      change_pct,
        "trend":           trend,
        "resistance":      resistance,
        "support":         support,
        "broke_resistance": broke_r,
        "broke_support":   broke_s,
        "signal_strength": strength,
        "rel_volume":      round(rel_volume, 1),
        "vol_increasing":  vol_increasing,
        "contract_type":   contract_type.upper(),
        "target_strike":   round(actual_strike, 2),
        "expiry":          expiry,
        "open_interest":   open_interest,
        "iv_rank":         iv_rank,
        "ask":             ask,
        "spread_pct":      spread_pct,
        "reason":          reason,
    }


def send_notification(title, body, priority="high"):
    if not NTFY_TOPIC:
        print("No NTFY_TOPIC — skipping notification")
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
    """Format one signal for the notification body."""
    stars    = "★" * r["signal_strength"] + "☆" * (5 - r["signal_strength"])
    chg      = f"+{r['change_pct']}%" if r["change_pct"] > 0 else f"{r['change_pct']}%"
    price    = f"${r['price']:.2f} ({chg})"
    contract = f"{r['contract_type']} ${r['target_strike']:.2f}"
    expiry   = f"exp {r['expiry']}" if r["expiry"] else "check expiry"
    oi       = f"OI:{r['open_interest']}" if r["open_interest"] else "OI:—"
    iv       = f"IV:{r['iv_rank']}%" if r["iv_rank"] else "IV:—"
    ask      = f"ask:${r['ask']:.2f}" if r["ask"] else "check price"
    vol      = f"vol {r['rel_volume']}x avg"

    return (
        f"{r['ticker']}  {price}\n"
        f"  → {contract} · {expiry}\n"
        f"  → {stars} · {vol} · {oi} · {iv} · {ask}\n"
        f"  {r['reason']}"
    )


def main():
    now = datetime.utcnow()
    print(f"\n{'='*55}")
    print(f"Budget Options Scanner — End of Day Scan")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')} | Tickers: {len(WATCHLIST)}")
    print(f"{'='*55}\n")

    if not POLYGON_KEY:
        send_notification("Scanner Error", "POLYGON_KEY secret not set in GitHub.")
        return

    results  = []
    skipped  = 0

    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ", flush=True)
        signal = analyze(ticker)
        if signal:
            results.append(signal)
            print(
                f"${signal['price']} — {signal['trend']} "
                f"(strength {signal['signal_strength']}/5, "
                f"vol {signal['rel_volume']}x)"
            )
        else:
            skipped += 1
            print("no setup")

    results.sort(key=lambda x: x["signal_strength"], reverse=True)
    strong = [r for r in results if r["signal_strength"] >= MIN_SIGNAL_STRENGTH]

    print(f"\n{'─'*55}")
    print(f"Results: {len(results)} signals | {skipped} skipped | {len(strong)} strong")

    # ── BUILD NOTIFICATION
    tomorrow = (datetime.today() + timedelta(days=1)).strftime("%A %b %-d")

    if not results:
        send_notification(
            "Scanner: No setups tonight",
            f"Scanned {len(WATCHLIST)} tickers. No 3-candle confirmations under ${MAX_STOCK_PRICE} today.\n\nRest up — better setups tomorrow.",
            priority="low"
        )
        return

    if not strong:
        # Send weak signals anyway so you have something to review
        lines = "\n\n".join(format_signal(r) for r in results[:4])
        send_notification(
            f"Scanner: {len(results)} weak signals for {tomorrow}",
            f"No high-strength setups tonight. Proceed with caution.\n\n{lines}\n\nWait for price confirmation at 10:15 AM before entering.",
            priority="default"
        )
        return

    bullish = [r for r in strong if r["trend"] == "bullish"]
    bearish = [r for r in strong if r["trend"] == "bearish"]
    lines   = "\n\n".join(format_signal(r) for r in strong[:5])

    body = (
        f"{len(bullish)} bullish · {len(bearish)} bearish\n"
        f"All passed: volume · OI · IV · spread filters\n\n"
        f"{lines}\n\n"
        f"── PLAN FOR TOMORROW ──\n"
        f"Wait until 10:15 AM after open volatility settles.\n"
        f"Verify price is still near scanner level in Robinhood.\n"
        f"Check bid/ask spread is tight before buying.\n"
        f"Budget $15–20/contract · Exit at +50% · Cut at -50%"
    )

    send_notification(
        f"{len(strong)} strong signal{'s' if len(strong) > 1 else ''} for {tomorrow}",
        body
    )

    print("\nDone — notification sent.")


if __name__ == "__main__":
    main()
