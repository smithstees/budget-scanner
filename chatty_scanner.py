"""
Chatty Morning Scanner - chatty_scanner.py
Runs at 10:30 AM ET via GitHub Actions
Checks SNAP, F, JBLU (+ IWM optional) for options setups
Sends notifications to ntfy.sh topic: ragebudgetopt

v2 CHANGES:
- Switched to api.massive.com (Polygon.io rebrand)
- Removed options endpoint (paid tier only)
- Fixed incomplete candle issue: strips today's open bar before pattern check
- Contract details now come from broker after signal fires
"""

import os
import time
import requests
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
MASSIVE_KEY = os.environ.get("POLYGON_KEY", "")   # reuse existing secret
NTFY_TOPIC  = "ragebudgetopt"
BASE_URL    = "https://api.massive.com"

# Tickers per Chatty parameters
TICKERS = {
    "SNAP": {"type": "fast mover",   "required": True},
    "F":    {"type": "steady mover", "required": True},
    "JBLU": {"type": "burst mover",  "required": True},
    "IWM":  {"type": "ETF optional", "required": False},
}

# Contract criteria (to look for in broker after signal)
CONTRACT_MIN    = 0.20   # $0.20/share = $20/contract
CONTRACT_MAX    = 0.60   # $0.60/share = $60/contract
DIP_MIN         = -0.03  # -3% max pullback
DIP_MAX         = -0.01  # -1% minimum dip to qualify
PROFIT_TARGET   = 0.40   # 40% profit target
STOP_LOSS       = 0.30   # 30% stop loss
EXPIRY_DAYS_MIN = 7
EXPIRY_DAYS_MAX = 14

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_bars(ticker, days=20):
    """Fetch recent daily bars from /v2/aggs (free tier endpoint)."""
    end   = datetime.today()
    start = end - timedelta(days=days + 10)
    url = (
        f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit=30&apiKey={MASSIVE_KEY}"
    )
    try:
        r = requests.get(url, timeout=12)
        return r.json().get("results", [])
    except Exception as e:
        print(f"    Error fetching {ticker}: {e}")
        return []


def is_market_hours():
    """Check if we're currently during market hours (ET)."""
    now = datetime.utcnow()
    # EDT = UTC-4, EST = UTC-5. 10:30 AM ET runs during EDT so use -4
    et_hour = (now.hour - 4) % 24
    et_min  = now.minute
    weekday = now.weekday()  # 0=Mon, 4=Fri
    if weekday > 4:
        return False
    market_open  = (et_hour > 9) or (et_hour == 9 and et_min >= 30)
    market_close = (et_hour >= 16)
    return market_open and not market_close


def candle_dir(b):
    rng  = b["h"] - b["l"] or 0.01
    body = abs(b["c"] - b["o"])
    if body < rng * 0.05:
        return "doji"
    return "green" if b["c"] > b["o"] else "red"


def atr_pct(bars, price):
    """Average true range as % of price over last 5 closed bars."""
    if len(bars) < 2:
        return 0
    last5 = bars[-5:]
    atrs  = []
    for i in range(1, len(last5)):
        b = last5[i]; p = last5[i-1]
        atrs.append(max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])))
    avg = sum(atrs) / len(atrs) if atrs else 0
    return round((avg / price) * 100, 1)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze(ticker, meta):
    bars = get_bars(ticker)
    if len(bars) < 6:
        print(f"    {ticker} — not enough bars ({len(bars)})")
        return None

    # Strip today's incomplete candle during market hours
    in_market = is_market_hours()
    closed_bars = bars[:-1] if in_market else bars

    if len(closed_bars) < 5:
        print(f"    {ticker} — not enough closed bars")
        return None

    last_closed = closed_bars[-1]
    live_bar    = bars[-1]
    price       = live_bar["c"]  # current price from live bar

    # Change % vs previous close
    prev_close  = closed_bars[-2]["c"]
    change_pct  = round(((price - prev_close) / prev_close) * 100, 2)

    # ── Chatty dip check: stock must be red/pulling back 1–3% ──────────────
    if not (DIP_MIN <= change_pct / 100 <= DIP_MAX):
        print(f"    {ticker} — not dipping ({change_pct}%) — Chatty wants -1% to -3%")
        return None

    # ── 3-candle trend on closed bars ──────────────────────────────────────
    dirs = [candle_dir(b) for b in closed_bars[-3:]]
    gc   = dirs.count("green")
    rc   = dirs.count("red")

    # Chatty: buy weakness — want red candles or mixed pulling back
    # Accept: 3 red (strong bear), or 2 red (pullback), or mixed with dip
    if gc == 3:
        print(f"    {ticker} — 3 green candles, not a dip setup")
        return None

    trend = "bearish" if rc >= 2 else "neutral_dip"

    # ── Volume ──────────────────────────────────────────────────────────────
    vol_bars = [b["v"] for b in closed_bars[-11:] if "v" in b]
    avg_vol  = sum(vol_bars) / len(vol_bars) if vol_bars else 1
    today_vol = live_bar.get("v", 0)
    rel_vol   = round(today_vol / avg_vol, 1) if avg_vol > 0 else 0

    # ── Support level ───────────────────────────────────────────────────────
    support    = round(min(b["l"] for b in closed_bars[-10:]), 2)
    near_sup   = price <= support * 1.03  # within 3% of support

    # ── ATR ─────────────────────────────────────────────────────────────────
    atr        = atr_pct(closed_bars, price)
    good_vol   = 2 < atr < 8

    # ── Signal strength ─────────────────────────────────────────────────────
    strength = 1
    if near_sup:           strength += 1
    if rel_vol >= 1.5:     strength += 1
    if rc == 3:            strength += 1
    if good_vol:           strength += 1
    strength = min(5, strength)

    # ── Probability score ───────────────────────────────────────────────────
    score = 20
    if DIP_MIN <= change_pct / 100 <= DIP_MAX: score += 20  # clean dip
    if near_sup:    score += 20
    if rc >= 2:     score += 15
    if rel_vol >= 2.0: score += 15
    elif rel_vol >= 1.5: score += 10
    elif rel_vol >= 1.0: score += 5
    if good_vol:    score += 10
    probability = min(95, max(5, score))

    # ── Suggested strike ────────────────────────────────────────────────────
    # Chatty: 1–2 strikes OTM on a call (buy the dip = expect bounce)
    # Nearest round number 1-2% above current price
    otm_strike = round(price * 1.015, 0)  # ~1.5% OTM

    return {
        "ticker":      ticker,
        "type":        meta["type"],
        "price":       round(price, 2),
        "change_pct":  change_pct,
        "trend":       trend,
        "support":     support,
        "near_sup":    near_sup,
        "rel_vol":     rel_vol,
        "atr_pct":     atr,
        "otm_strike":  otm_strike,
        "probability": probability,
        "strength":    strength,
    }


# ── Notification ──────────────────────────────────────────────────────────────

def send_notification(title, body, priority="high"):
    if not NTFY_TOPIC:
        print("No NTFY_TOPIC set")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     "chart_with_upwards_trend,moneybag",
            },
            timeout=10,
        )
        print(f"Notification sent: {title}")
    except Exception as e:
        print(f"Notification error: {e}")


def format_signal(r):
    stars   = "★" * r["strength"] + "☆" * (5 - r["strength"])
    chg     = f"{r['change_pct']}%"
    sup     = f" ⚡near support ${r['support']}" if r["near_sup"] else ""
    action  = (
        f"In broker: CALL near ${r['otm_strike']} strike · "
        f"7–14 day expiry · find ${CONTRACT_MIN}–${CONTRACT_MAX}/share · OI > 50"
    )
    return (
        f"{r['ticker']} ({r['type']})  ${r['price']}  ({chg})  {r['probability']}% prob\n"
        f"  → {stars} · vol:{r['rel_vol']}x · ATR:{r['atr_pct']}%{sup}\n"
        f"  → {action}\n"
        f"  Buy weakness — dip {chg}, look for bounce to +40%"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"Chatty Morning Scanner v2")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')} | Market hours: {is_market_hours()}")
    print(f"Tickers: {', '.join(TICKERS.keys())}")
    print(f"Strategy: Buy dips -1% to -3%, near support, CALL 1-2 OTM")
    print(f"Contract to find: ${CONTRACT_MIN}–${CONTRACT_MAX}/share · 7–14 day expiry")
    print(f"{'='*60}\n")

    if not MASSIVE_KEY:
        send_notification(
            "Chatty Scanner Error",
            "POLYGON_KEY secret not set in GitHub.",
            priority="urgent"
        )
        return

    results = []
    for ticker, meta in TICKERS.items():
        print(f"Checking {ticker} ({meta['type']})...", end=" ", flush=True)
        sig = analyze(ticker, meta)
        if sig:
            results.append(sig)
            print(f"${sig['price']} {sig['change_pct']}% — {sig['probability']}% prob ✓")
        else:
            print("no setup")
        time.sleep(0.5)  # gentle rate limit

    results.sort(key=lambda x: x["probability"], reverse=True)

    print(f"\n{'─'*60}")
    print(f"Setups found: {len(results)} / {len(TICKERS)}")

    if not results:
        send_notification(
            "Chatty: No dip setups at 10:30 AM",
            f"Checked SNAP, F, JBLU, IWM.\n"
            f"None are dipping -1% to -3% right now.\n"
            f"Check again after 11 AM if market sells off.",
            priority="low"
        )
        return

    lines = "\n\n".join(format_signal(r) for r in results)
    strong = [r for r in results if r["probability"] >= 60]

    title = (
        f"Chatty: {len(strong)} dip setup{'s' if len(strong) != 1 else ''} — buy weakness"
        if strong else
        f"Chatty: {len(results)} weak dip — proceed with caution"
    )

    body = (
        f"Buy weakness not strength · +40% target · -30% stop\n\n"
        f"{lines}\n\n"
        f"── CHATTY RULES ──\n"
        f"✅ Stock dipping -1% to -3% ✓\n"
        f"✅ Near support = better entry\n"
        f"✅ CALL 1–2 strikes OTM, 7–14 days out\n"
        f"✅ Contract $0.20–$0.60/share ($20–$60)\n"
        f"🚪 Exit: +40% profit OR -30% stop, no exceptions"
    )

    priority = "high" if strong else "default"
    send_notification(title, body, priority)
    print("\nDone.")


if __name__ == "__main__":
    main()
