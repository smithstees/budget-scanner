"""
Chatty Morning Scanner - chatty_scanner.py
Runs at 10:30 AM ET via GitHub Actions
Checks SNAP, F, JBLU (+ IWM optional) for options setups
Sends notifications to ntfy.sh topic: ragebudgetopt
"""

import os
import time
import requests
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
POLYGON_KEY = os.environ.get("POLYGON_KEY", "")
NTFY_TOPIC  = "ragebudgetopt"
BASE_URL    = "https://api.polygon.io"

# Tickers per Chatty parameters
TICKERS = {
    "SNAP": {"type": "fast mover",   "required": True},
    "F":    {"type": "steady mover", "required": True},
    "JBLU": {"type": "burst mover",  "required": True},
    "IWM":  {"type": "ETF optional", "required": False},
}

# Contract criteria
CONTRACT_MIN   = 0.20   # $0.20 per share = $20 per contract
CONTRACT_MAX   = 0.60   # $0.60 per share = $60 per contract
DIP_MIN        = -0.03  # -3% pullback threshold
DIP_MAX        = -0.01  # -1% minimum dip to qualify
PROFIT_TARGET  = 0.40   # 40% profit target
STOP_LOSS      = 0.30   # 30% stop loss
EXPIRY_DAYS_MIN = 7
EXPIRY_DAYS_MAX = 14

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_bars(ticker, days=5):
    """Fetch recent daily bars from /v2/aggs (free tier endpoint)."""
    end   = datetime.now()
    start = end - timedelta(days=days + 4)  # buffer for weekends/holidays

    url = (
        f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit=10&apiKey={POLYGON_KEY}"
    )

    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("resultsCount", 0) >= 2:
            return data["results"]
        return None
    except Exception as e:
        print(f"  [ERROR] {ticker}: {e}")
        return None


def analyze_ticker(ticker, bars):
    """
    Apply Chatty entry rules to the latest bars.
    Returns a setup dict if valid, or None.
    """
    if not bars or len(bars) < 2:
        return None

    prev  = bars[-2]
    today = bars[-1]

    prev_close  = prev["c"]
    today_open  = today["o"]
    today_close = today["c"]
    today_high  = today["h"]
    today_low   = today["l"]

    # % change from previous close to today's close
    pct_change = (today_close - prev_close) / prev_close

    # Rule 1: Stock must be red/pulling back (-1% to -3%)
    if not (DIP_MIN <= pct_change <= DIP_MAX):
        print(f"  {ticker}: pct_change={pct_change:.2%} — not in dip range, skip")
        return None

    # Rule 2: NOT after a big green candle on previous day
    prev_change = (prev["c"] - prev["o"]) / prev["o"]
    if prev_change > 0.02:  # prev day was +2% or more green
        print(f"  {ticker}: prev candle was big green ({prev_change:.2%}), skip")
        return None

    # Rule 3: Estimate if near support (today low is within 1.5% of recent low)
    recent_low = min(b["l"] for b in bars[-5:])
    near_support = today_low <= recent_low * 1.015

    # Estimate strike and contract cost
    # For a CALL: 1-2 strikes OTM (approx $0.50–$1.00 increments for low-price stocks)
    if today_close < 5:
        strike_increment = 0.50
    elif today_close < 20:
        strike_increment = 1.00
    else:
        strike_increment = 2.00

    otm_strike = round(today_close + strike_increment, 2)

    # Rough contract cost estimate based on % OTM and DTE
    # Conservative: ~1–2% of stock price per $1 OTM for 7–14 DTE
    otm_pct = (otm_strike - today_close) / today_close
    estimated_premium = today_close * max(0.02, 0.05 - otm_pct)
    estimated_contract_cost = round(estimated_premium * 100, 2)

    # Rule 4: Contract must be in $20–$60 range
    if not (CONTRACT_MIN * 100 <= estimated_contract_cost <= CONTRACT_MAX * 100):
        print(f"  {ticker}: estimated contract ${estimated_contract_cost:.0f} out of range, skip")
        return None

    # Expiry date (find next Friday 7–14 days out)
    today_date = datetime.now()
    days_until_friday = (4 - today_date.weekday()) % 7
    if days_until_friday < EXPIRY_DAYS_MIN:
        days_until_friday += 7
    expiry = today_date + timedelta(days=days_until_friday)
    dte = days_until_friday

    if dte > EXPIRY_DAYS_MAX:
        # Try closer Friday
        dte = days_until_friday - 7 if days_until_friday - 7 >= EXPIRY_DAYS_MIN else days_until_friday

    return {
        "ticker":           ticker,
        "type":             TICKERS[ticker]["type"],
        "price":            today_close,
        "pct_change":       pct_change,
        "near_support":     near_support,
        "strike":           otm_strike,
        "est_premium":      round(estimated_premium, 2),
        "est_contract":     estimated_contract_cost,
        "expiry":           expiry.strftime("%m/%d"),
        "dte":              dte,
        "profit_target":    f"+{int(PROFIT_TARGET*100)}%",
        "stop_loss":        f"-{int(STOP_LOSS*100)}%",
    }


def build_notification(setups, skipped):
    """Build the ntfy.sh notification title + body."""
    timestamp = datetime.now().strftime("%I:%M %p ET")

    if not setups:
        title = f"[CHATTY] No setups found - {timestamp}"
        body  = "SNAP, F, JBLU, IWM scanned. No qualifying dips today.\n\nCheck again tomorrow or watch for intraday moves."
        return title, body

    # Title: name first setup found
    first = setups[0]
    title = (
        f"[CHATTY] {first['ticker']} CALL setup — "
        f"${first['strike']}c {first['expiry']} | "
        f"~${first['est_contract']:.0f}/contract"
    )

    lines = [f"Morning scan complete — {timestamp}\n"]

    for s in setups:
        support_note = "near support" if s["near_support"] else "watch support level"
        lines.append(
            f"{'='*30}\n"
            f"TICKER:   {s['ticker']} ({s['type']})\n"
            f"PRICE:    ${s['price']:.2f}  ({s['pct_change']:+.1%} pullback)\n"
            f"SETUP:    CALL {support_note}\n"
            f"STRIKE:   ${s['strike']} CALL\n"
            f"DTE:      {s['dte']} days (exp {s['expiry']})\n"
            f"DELTA:    target 0.30–0.45\n"
            f"EST COST: ~${s['est_contract']:.0f}/contract\n"
            f"TARGET:   {s['profit_target']} profit | {s['stop_loss']} stop\n"
            f"ACTION:   Verify ask + OI > 50 in broker\n"
        )

    if skipped:
        lines.append(f"\nNo setup: {', '.join(skipped)}")

    lines.append("\nRemember: Buy weakness, not strength. No hoping, no praying.")

    return title, "\n".join(lines)


def send_ntfy(title, body):
    """Push notification to ntfy.sh."""
    try:
        r = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": "high",
                "Tags":     "chart_with_upwards_trend,moneybag",
            },
            timeout=10,
        )
        if r.status_code == 200:
            print(f"[OK] Notification sent: {title}")
        else:
            print(f"[WARN] ntfy returned {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[ERROR] Failed to send ntfy notification: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*40}")
    print(f"CHATTY SCANNER — {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")
    print(f"{'='*40}")

    if not POLYGON_KEY:
        print("[ERROR] POLYGON_KEY not set. Check GitHub Secrets.")
        return

    setups  = []
    skipped = []

    for ticker, info in TICKERS.items():
        print(f"\nScanning {ticker} ({info['type']})...")
        bars = get_bars(ticker)
        time.sleep(13)  # stay well under 5 calls/minute (one every ~12s)

        if bars is None:
            print(f"  {ticker}: no data returned")
            skipped.append(ticker)
            continue

        result = analyze_ticker(ticker, bars)
        if result:
            print(f"  {ticker}: SETUP FOUND — {result['pct_change']:+.1%}, strike ${result['strike']}")
            setups.append(result)
        else:
            skipped.append(ticker)

    print(f"\nSetups found: {len(setups)} | Skipped: {len(skipped)}")

    title, body = build_notification(setups, skipped)
    print(f"\nSending notification...")
    print(f"Title: {title}")
    send_ntfy(title, body)
    print("\nDone.")


if __name__ == "__main__":
    main()
