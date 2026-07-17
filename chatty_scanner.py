"""
Chatty Morning Scanner - chatty_scanner.py
Runs at 10:30 AM ET via GitHub Actions
Checks SNAP, F, JBLU (+ IWM optional) for options setups
Sends notifications to ntfy.sh topic: ragebudgetopt

v4 CHANGES (2026-07-06):
- Strategy shift to "runway options": 30-45 day expiries, 3-5 strikes OTM
- Delta-exit guidance: sell when stock is ~65% of way to strike
- Stop widened to -60% (longer expiry = more forgiving)

v3 CHANGES:
- Loosened dip filter from -1%/-3% (rarely hit) to -0.3%/-4% (realistic)
- Added "flat/red" fallback: also accepts stocks flat-to-slightly-red near support
- Fixed DST bug: is_market_hours() now uses zoneinfo instead of hardcoded UTC-4
- Consistent scoring: only pushes when probability >= 55
"""

import os
import time
import requests
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None  # fallback below

# ── Config ────────────────────────────────────────────────────────────────────
MASSIVE_KEY = os.environ.get("POLYGON_KEY", "")
try:
    import config
    NTFY_TOPIC  = config.NTFY_TOPIC
except Exception:
    NTFY_TOPIC  = os.environ.get("NTFY_TOPIC", "ragebudgetopt")
BASE_URL    = "https://api.massive.com"

# Tickers per Chatty parameters
TICKERS = {
    "SNAP": {"type": "fast mover",   "required": True},
    "F":    {"type": "steady mover", "required": True},
    "JBLU": {"type": "burst mover",  "required": True},
    "IWM":  {"type": "ETF optional", "required": False},
}

# Contract criteria — runway options: 30-45 day expiry, 3-5 OTM.
# Slightly higher premium than 7-14 day ATM but much less theta bleed.
CONTRACT_MIN    = 0.10
CONTRACT_MAX    = 0.30
# Loosened dip band. Previous -1% to -3% window was so narrow that almost
# every scan came back empty. This catches flat-to-modestly-red days too.
DIP_MIN         = -0.04   # up to -4% pullback still qualifies
DIP_MAX         =  0.003  # allow slightly green (+0.3%) if near support
STOP_LOSS       = 0.60   # loosened: longer expiry gives room
EXPIRY_DAYS_MIN = 30
EXPIRY_DAYS_MAX = 45
NOTIFY_MIN_PROB = 55  # don't spam on weak setups

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
    """Check if we're currently during regular market hours (ET).
    Handles DST correctly via zoneinfo."""
    if ET is not None:
        now = datetime.now(ET)
    else:
        # Fallback assumes EDT (UTC-4). Off by an hour Nov-Mar.
        now = datetime.utcnow() - timedelta(hours=4)
    if now.weekday() > 4:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


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


def est_contract_cost(price, atr):
    """Rough $/share estimate for a 7-14 day near-ATM call."""
    base = 0.015 * price
    vol_boost = (atr / 100) * price * 0.5
    return round(base + vol_boost, 2)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze(ticker, meta):
    bars = get_bars(ticker)
    if len(bars) < 6:
        print(f"    {ticker} — not enough bars ({len(bars)})")
        return None

    in_market = is_market_hours()
    closed_bars = bars[:-1] if in_market else bars

    if len(closed_bars) < 5:
        print(f"    {ticker} — not enough closed bars")
        return None

    live_bar    = bars[-1]
    price       = live_bar["c"]

    prev_close  = closed_bars[-2]["c"] if in_market else closed_bars[-1]["c"]
    if not in_market:
        # Yesterday vs the day before
        prev_close = closed_bars[-2]["c"]
    change_pct  = round(((price - prev_close) / prev_close) * 100, 2)

    # ── Loosened dip check: -4% to +0.3% qualifies ──────────────────────────
    if not (DIP_MIN <= change_pct / 100 <= DIP_MAX):
        print(f"    {ticker} — outside dip band ({change_pct}%) — want {DIP_MIN*100}% to {DIP_MAX*100}%")
        return None

    # ── 3-candle trend on closed bars ───────────────────────────────────────
    dirs = [candle_dir(b) for b in closed_bars[-3:]]
    gc   = dirs.count("green")
    rc   = dirs.count("red")

    if gc == 3 and change_pct > 0:
        print(f"    {ticker} — 3 green + rising, not a dip setup")
        return None

    trend = "bearish" if rc >= 2 else "neutral_dip"

    vol_bars = [b["v"] for b in closed_bars[-11:] if "v" in b]
    avg_vol  = sum(vol_bars) / len(vol_bars) if vol_bars else 1
    today_vol = live_bar.get("v", 0)
    rel_vol   = round(today_vol / avg_vol, 1) if avg_vol > 0 else 0

    support    = round(min(b["l"] for b in closed_bars[-10:]), 2)
    near_sup   = price <= support * 1.03

    atr        = atr_pct(closed_bars, price)
    good_vol   = 2 < atr < 8

    strength = 1
    if near_sup:           strength += 1
    if rel_vol >= 1.5:     strength += 1
    if rc >= 2:            strength += 1
    if good_vol:           strength += 1
    strength = min(5, strength)

    score = 20
    if DIP_MIN <= change_pct / 100 <= -0.005:  # actually dipping (>0.5% red)
        score += 20
    if near_sup:    score += 20
    if rc >= 2:     score += 15
    if rel_vol >= 2.0: score += 15
    elif rel_vol >= 1.5: score += 10
    elif rel_vol >= 1.0: score += 5
    if good_vol:    score += 10
    probability = min(95, max(5, score))

    # 3-5 strikes OTM (~4 strikes)
    step = 0.50 if price < 10 else 1.00
    otm_strike = round((round(price / step) * step) + 4 * step, 2)
    est_cost   = est_contract_cost(price, atr)
    sell_zone  = round(price + 0.65 * (otm_strike - price), 2)

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
        "sell_zone":   sell_zone,
        "probability": probability,
        "strength":    strength,
        "est_cost":    est_cost,
    }


# ── Notification ──────────────────────────────────────────────────────────────

def _ascii(s):
    # ntfy Title header must be latin-1 safe. Strip fancy unicode (— ★ ⚡ etc.)
    return (s.replace("\u2014", "-").replace("\u2013", "-")
             .replace("\u2022", "*").replace("\u00b7", "-")
             .replace("\u2605", "*").replace("\u2606", "*")
             .replace("\u26a1", "!").encode("ascii", "ignore").decode("ascii"))

def send_notification(title, body, priority="high"):
    if not NTFY_TOPIC:
        print("No NTFY_TOPIC set")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title":    _ascii(title),
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
    est_ct  = round(r['est_cost'] * 100)
    action  = (
        f"In broker: CALL strike ${r['otm_strike']} (3-5 OTM) · "
        f"{EXPIRY_DAYS_MIN}-{EXPIRY_DAYS_MAX} day expiry · "
        f"~${est_ct}/contract · OI > 50"
    )
    return (
        f"{r['ticker']} ({r['type']})  ${r['price']}  ({chg})  {r['probability']}% prob\n"
        f"  → {stars} · vol:{r['rel_vol']}x · ATR:{r['atr_pct']}%{sup}\n"
        f"  → {action}\n"
        f"  SELL when stock hits ~${r['sell_zone']} · stop -60% on contract"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"Chatty Morning Scanner v3")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')} | Market hours: {is_market_hours()}")
    print(f"Tickers: {', '.join(TICKERS.keys())}")
    print(f"Strategy: Buy dips {DIP_MIN*100:.1f}% to {DIP_MAX*100:.1f}%, near support, CALL 3-5 OTM")
    print(f"Contract target: ${CONTRACT_MIN}–${CONTRACT_MAX}/share · {EXPIRY_DAYS_MIN}-{EXPIRY_DAYS_MAX} day expiry")
    print(f"{'='*60}\n")

    if not MASSIVE_KEY:
        send_notification(
            "Chatty Scanner Error",
            "POLYGON_KEY secret not set in GitHub.",
            priority="urgent"
        )
        return

    try:
        from signal_log import log_signal
    except Exception:
        log_signal = None

    results = []
    for ticker, meta in TICKERS.items():
        print(f"Checking {ticker} ({meta['type']})...", end=" ", flush=True)
        sig = analyze(ticker, meta)
        if sig:
            results.append(sig)
            print(f"${sig['price']} {sig['change_pct']}% — {sig['probability']}% prob ✓")
            if log_signal is not None:
                # Normalize field names to shared schema
                normalized = {
                    'ticker':        sig.get('ticker'),
                    'trend':         sig.get('trend'),
                    'score':         sig.get('probability'),
                    'price':         sig.get('price'),
                    'strike':        sig.get('otm_strike'),
                    'contract_type': 'CALL',
                    'est_cost':      sig.get('est_cost'),
                    'rel_vol':       sig.get('rel_vol'),
                    'atr_pct':       sig.get('atr_pct'),
                }
                did_push = sig.get('probability', 0) >= NOTIFY_MIN_PROB
                log_signal('chatty', normalized, pushed=did_push)
        else:
            print("no setup")
        time.sleep(0.5)

    results.sort(key=lambda x: x["probability"], reverse=True)

    print(f"\n{'─'*60}")
    print(f"Setups found: {len(results)} / {len(TICKERS)}")

    strong = [r for r in results if r["probability"] >= NOTIFY_MIN_PROB]

    if not results:
        send_notification(
            "Chatty: no setups at 10:30 AM",
            f"Checked {', '.join(TICKERS.keys())}.\n"
            f"None fit the dip/near-support pattern right now.\n"
            f"Try the live scanner (Actions → Live Scanner → Run) later today.",
            priority="low"
        )
        return

    if not strong:
        # Log-only summary, no phone push for weak setups
        print(f"Only weak setups (top prob {results[0]['probability']}%). Not notifying.")
        send_notification(
            f"Chatty: {len(results)} weak setup(s), no push",
            f"Nothing scored >= {NOTIFY_MIN_PROB}% today.\n"
            f"Top: {results[0]['ticker']} @ {results[0]['probability']}% prob.",
            priority="low"
        )
        return

    lines = "\n\n".join(format_signal(r) for r in strong)

    title = (
        f"Chatty: {len(strong)} dip setup{'s' if len(strong) != 1 else ''} — buy weakness"
    )

    body = (
        f"Runway options · sell into strength · -60% stop\n\n"
        f"{lines}\n\n"
        f"── RULES ──\n"
        f"✅ Dip in band ({DIP_MIN*100:.1f}% to {DIP_MAX*100:.1f}%) ✓\n"
        f"✅ Near support = better entry\n"
        f"✅ CALL 3–5 strikes OTM, {EXPIRY_DAYS_MIN}–{EXPIRY_DAYS_MAX} days out (30+ = less theta bleed)\n"
        f"✅ Contract ${CONTRACT_MIN}–${CONTRACT_MAX}/share (~${int(CONTRACT_MIN*100)}–${int(CONTRACT_MAX*100)})\n"
        f"🚪 Exit: sell as stock approaches strike (65% of the way) OR -60% stop\n"
        f"💡 Take HALF off at +50% — lock the win"
    )

    send_notification(title, body, "high")
    print("\nDone.")


if __name__ == "__main__":
    main()
