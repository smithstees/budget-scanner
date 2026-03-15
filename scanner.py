import os
import requests
from datetime import datetime, timedelta

POLYGON_KEY = os.environ.get("POLYGON_KEY", "")
NTFY_TOPIC  = os.environ.get("NTFY_TOPIC", "")

WATCHLIST = [
    "SNDL","SOFI","VALE","ITUB","BBD","GRAB","MARA","RIOT","CLSK","WULF",
    "HIMS","OPEN","SENS","EXPR","ZIM","CLOV","NKLA","ATER","GNUS","GOEV",
    "VERB","IMPP","IDEX","MVIS","SPWR","NAKD","AULT","FFIE","PRTY","HLBZ"
]

MAX_PRICE    = 15.00
MIN_STRENGTH = 4


def fetch_candles(ticker):
    """Pull last 10 days of daily candles from Polygon."""
    end   = datetime.today()
    start = end - timedelta(days=14)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit=10&apiKey={POLYGON_KEY}"
    )
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        return data.get("results", [])
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return []


def analyze(ticker):
    """Return a signal dict or None if no setup found."""
    bars = fetch_candles(ticker)
    if len(bars) < 4:
        return None

    bars = bars[-5:]  # last 5 candles
    last = bars[-1]
    prev = bars[-2]

    price = last["c"]
    if price > MAX_PRICE:
        return None

    change_pct = ((last["c"] - prev["c"]) / prev["c"]) * 100

    # Build candle direction for last 3
    def candle_dir(b):
        rng = b["h"] - b["l"] or 0.01
        body = abs(b["c"] - b["o"])
        if body < rng * 0.05:
            return "doji"
        return "green" if b["c"] > b["o"] else "red"

    last3 = [candle_dir(b) for b in bars[-3:]]
    green_count = last3.count("green")
    red_count   = last3.count("red")

    if green_count == 3:
        trend = "bullish"
    elif red_count == 3:
        trend = "bearish"
    else:
        trend = "neutral"

    resistance = round(max(b["h"] for b in bars), 2)
    support    = round(min(b["l"] for b in bars), 2)

    broke_r = last["c"] >= resistance * 0.99
    broke_s = last["c"] <= support   * 1.01

    # Signal strength: 1-5
    strength = 1
    if trend != "neutral":
        strength += 2
    if green_count == 3 or red_count == 3:
        strength += 1
    if broke_r or broke_s:
        strength += 1
    strength = min(5, strength)

    # Volume trend
    vol_note = ""
    if len(bars) >= 2 and bars[-1].get("v", 0) > bars[-2].get("v", 0):
        vol_note = " with rising volume"

    if trend == "bullish":
        reason = f"3 green candles{vol_note} — buyers near ${resistance} resistance"
    elif trend == "bearish":
        reason = f"3 red candles{vol_note} — sellers near ${support} support"
    else:
        reason = "Mixed signals — no 3-candle confirmation"

    return {
        "ticker":           ticker,
        "price":            round(price, 2),
        "change_pct":       round(change_pct, 2),
        "trend":            trend,
        "resistance":       resistance,
        "support":          support,
        "broke_resistance": broke_r,
        "broke_support":    broke_s,
        "signal_strength":  strength,
        "reason":           reason,
    }


def send_notification(title, body, priority="high"):
    """Push a notification via ntfy.sh."""
    if not NTFY_TOPIC:
        print("No NTFY_TOPIC set — skipping notification")
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


def main():
    now     = datetime.utcnow()
    session = "Morning" if now.hour < 15 else "Afternoon"
    print(f"\n{'='*50}")
    print(f"Budget Options Scanner — {session} scan")
    print(f"Time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if not POLYGON_KEY:
        print("ERROR: POLYGON_KEY secret not set in GitHub")
        send_notification("Scanner Error", "POLYGON_KEY is not configured in GitHub secrets.")
        return

    results = []
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ")
        signal = analyze(ticker)
        if signal:
            results.append(signal)
            print(f"${signal['price']} — {signal['trend']} (strength {signal['signal_strength']}/5)")
        else:
            print("skipped")

    # Sort by signal strength
    results.sort(key=lambda x: x["signal_strength"], reverse=True)

    bullish = [r for r in results if r["trend"] == "bullish"]
    bearish = [r for r in results if r["trend"] == "bearish"]
    strong  = [r for r in results if r["signal_strength"] >= MIN_STRENGTH]

    print(f"\nResults: {len(results)} signals | {len(bullish)} bullish | {len(bearish)} bearish | {len(strong)} strong")

    # Build notification
    if not strong:
        send_notification(
            f"{session} scan: No strong signals",
            f"Scanned {len(WATCHLIST)} tickers under ${MAX_PRICE}.\n"
            f"No high-strength setups found. Check back next scan.",
            priority="low"
        )
        return

    lines = []
    for r in strong[:6]:
        ctype  = "CALL" if r["trend"] == "bullish" else "PUT"
        strike = r["resistance"] if r["trend"] == "bullish" else r["support"]
        stars  = "★" * r["signal_strength"] + "☆" * (5 - r["signal_strength"])
        chg    = f"+{r['change_pct']}%" if r["change_pct"] > 0 else f"{r['change_pct']}%"
        lines.append(f"{r['ticker']}  ${r['price']}  ({chg})  →  {ctype} ${strike}  {stars}")

    body = (
        f"{len(bullish)} bullish · {len(bearish)} bearish · {len(strong)} strong\n\n"
        + "\n".join(lines)
        + f"\n\nBudget $15–20/contract · Exit at +50% · Stop at -50%"
    )

    send_notification(
        f"{session} scan: {len(strong)} strong signal{'s' if len(strong) > 1 else ''}",
        body
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
