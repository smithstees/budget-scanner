"""
Budget Options Scanner v4 — Ty's Preferences
Runs at 6PM Eastern after market close.

KEY CHANGES FROM v3:
- Switched to api.massive.com (Polygon.io rebrand)
- Removed fetch_options() — snapshot/options endpoint requires paid plan
- Signal only: ticker + direction + probability + suggested strike from candles
- Contract price range corrected: $0.05-$0.25/share = $5-$25/contract
- Find the actual contract in your broker after signal fires
"""

import os
import requests
from datetime import datetime, timedelta

MASSIVE_KEY  = os.environ.get("POLYGON_KEY", "")   # reuse existing secret
NTFY_TOPIC   = os.environ.get("NTFY_TOPIC",  "")

# ── TY'S STRATEGY PARAMETERS ─────────────────────────────────
MIN_SIGNAL_STRENGTH = 4      # only notify on 4-5 star signals
MIN_REL_VOLUME      = 0.8    # today's volume at least 80% of 10-day avg
DAYS_BACK           = 25     # candle lookback period
TARGET_GAIN         = 0.50   # 50% profit target
# Contract to look for in broker after signal:
CONTRACT_MIN        = 0.05   # $0.05/share = $5/contract
CONTRACT_MAX        = 0.25   # $0.25/share = $25/contract
# ─────────────────────────────────────────────────────────────

WATCHLIST = [
    # Low priced stocks with active options
    "SNDL","SOFI","VALE","ITUB","BBD","GRAB","MARA","RIOT","CLSK","WULF",
    "HIMS","OPEN","SENS","EXPR","ZIM","CLOV","TLRY","SIRI","NOK","PLUG",
    "ENVX","CIFR","BITF","HIVE","IDEX","MVIS","SPWR","ATER","GNUS","GOEV",
    # Higher priced stocks that often have cheap OTM contracts
    "AMD","NVDA","TSLA","AMZN","META","GOOGL","MSFT","AAPL","BAC","F",
    "GE","INTC","PFE","T","WBA","KVUE","PARA","CMCSA","NIO","XPEV",
    "LI","RIVN","LCID","JOBY","ACHR","UBER","LYFT","SNAP","PINS","PLTR",
    "HOOD","COIN","RBLX","U","DKNG","PENN","AFRM","UPST","WISH","WKHS"
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
        f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit={DAYS_BACK}&apiKey={MASSIVE_KEY}"
    )
    return get(url).get("results", [])


def candle_dir(b):
    rng  = b["h"] - b["l"] or 0.01
    body = abs(b["c"] - b["o"])
    if body < rng * 0.05:
        return "doji"
    return "green" if b["c"] > b["o"] else "red"


def calc_probability(trend, rel_vol, vol_increasing, broke_level,
                     change_pct, atr_pct):
    score = 20

    # Volume — most important speed indicator
    if rel_vol >= 2.5:   score += 25
    elif rel_vol >= 2.0: score += 20
    elif rel_vol >= 1.5: score += 15
    elif rel_vol >= 1.0: score += 8
    else:                score -= 10

    # Rising volume across 3 candles
    if vol_increasing:   score += 12

    # Broke key level
    if broke_level:      score += 15

    # Price momentum today
    if trend == "bullish" and change_pct > 3:    score += 8
    elif trend == "bullish" and change_pct > 1:  score += 4
    elif trend == "bearish" and change_pct < -3: score += 8
    elif trend == "bearish" and change_pct < -1: score += 4

    # ATR — reward moderate volatility, penalize erratic
    if 2 < atr_pct < 8:  score += 5
    elif atr_pct >= 8:   score -= 8

    return min(95, max(5, score))


def analyze(ticker):
    bars = fetch_candles(ticker)
    if len(bars) < 6:
        print(f"    {ticker} — not enough bars ({len(bars)})")
        return None

    last       = bars[-1]
    prev       = bars[-2]
    price      = last["c"]
    change_pct = round(((last["c"] - prev["c"]) / prev["c"]) * 100, 2)

    # 3-candle confirmation
    last3 = [candle_dir(bars[-3]), candle_dir(bars[-2]), candle_dir(bars[-1])]
    gc    = last3.count("green")
    rc    = last3.count("red")

    if gc == 3:   trend = "bullish"
    elif rc == 3: trend = "bearish"
    else:
        print(f"    {ticker} — no 3-candle ({gc}g {rc}r)")
        return None

    # Volume
    recent_vols = [b["v"] for b in bars[-11:-1] if "v" in b]
    avg_vol     = sum(recent_vols) / len(recent_vols) if recent_vols else 1
    today_vol   = last.get("v", 0)
    rel_vol     = round(today_vol / avg_vol, 1) if avg_vol > 0 else 0

    if rel_vol < MIN_REL_VOLUME:
        print(f"    {ticker} — low rel volume ({rel_vol}x)")
        return None

    vol_increasing = (
        bars[-1].get("v", 0) > bars[-2].get("v", 0) and
        bars[-2].get("v", 0) > bars[-3].get("v", 0)
    )

    # Support / resistance from last 10 bars
    last10     = bars[-10:]
    resistance = round(max(b["h"] for b in last10), 2)
    support    = round(min(b["l"] for b in last10), 2)
    broke_level = (
        (trend == "bullish" and last["c"] >= resistance * 0.985) or
        (trend == "bearish" and last["c"] <= support    * 1.015)
    )

    # ATR % (avg true range as % of price, last 5 bars)
    last5 = bars[-5:]
    atrs  = []
    for i in range(1, len(last5)):
        b = last5[i]; p = last5[i-1]
        atrs.append(max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])))
    atr     = sum(atrs) / len(atrs) if atrs else 0
    atr_pct = round((atr / price) * 100, 1)

    probability = calc_probability(
        trend, rel_vol, vol_increasing, broke_level, change_pct, atr_pct
    )

    strength = min(5, max(1,
        2 +
        (1 if vol_increasing else 0) +
        (1 if rel_vol >= 1.5 else 0) +
        (1 if broke_level else 0)
    ))

    contract_type  = "CALL" if trend == "bullish" else "PUT"
    target_strike  = resistance if trend == "bullish" else support
    vol_note       = " with rising volume" if vol_increasing else ""
    rel_note       = f" ({rel_vol}x avg vol)"

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
        "contract_type": contract_type,
        "target_strike": round(target_strike, 2),
        "atr_pct":       atr_pct,
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
    prob   = f"{r['probability']}% prob"
    vol    = f"vol:{r['rel_vol']}x"
    atr    = f"ATR:{r['atr_pct']}%"
    broke  = " ⚡broke level" if r["broke_level"] else ""
    action = (
        f"In broker: {r['contract_type']} near ${r['target_strike']} strike · "
        f"2-4 wk expiry · find $0.05-$0.25/share contract · OI > 50"
    )

    return (
        f"{r['ticker']}  ${r['price']}  ({chg})  {prob}\n"
        f"  → {stars} · {vol} · {atr}{broke}\n"
        f"  → {action}\n"
        f"  {r['reason']}"
    )


def main():
    now = datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"Budget Options Scanner v4 — Ty's Preferences")
    print(f"UTC: {now.strftime('%Y-%m-%d %H:%M')} | Tickers: {len(WATCHLIST)}")
    print(f"Contract to find in broker: ${CONTRACT_MIN}-${CONTRACT_MAX}/share "
          f"(${int(CONTRACT_MIN*100)}-${int(CONTRACT_MAX*100)}/contract)")
    print(f"No stock price cap — contract price is what matters")
    print(f"Data: api.massive.com (free tier — candles only)")
    print(f"{'='*60}\n")

    if not MASSIVE_KEY:
        send_notification("Scanner Error", "POLYGON_KEY secret not set in GitHub.")
        return

    results = []
    for ticker in WATCHLIST:
        print(f"Checking {ticker}...", end=" ", flush=True)
        sig = analyze(ticker)
        if sig:
            results.append(sig)
            print(f"${sig['price']} — {sig['trend']} — {sig['probability']}% prob — vol {sig['rel_vol']}x")
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
            f"No 3-candle confirmations with sufficient volume.\n"
            f"Rest up — better setups tomorrow.",
            priority="low"
        )
        return

    if not strong:
        lines = "\n\n".join(format_signal(r) for r in results[:4])
        send_notification(
            f"Scanner: {len(results)} weak signal(s) for {tomorrow}",
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
        f"{len(bullish)} bullish · {len(bearish)} bearish\n"
        f"Filtered: 3-candle confirm · volume · ATR\n\n"
        f"{lines}\n\n"
        f"── PLAN FOR TOMORROW ──\n"
        f"Wait until 10:15 AM — let open volatility settle.\n"
        f"In broker: find {contract_type_hint(strong)} near suggested strike.\n"
        f"Look for $0.05-$0.25/share ($5-$25/contract), OI > 50, 2-4 wk expiry.\n"
        f"Target: +50% exit · Stop: -50% cut"
    )

    send_notification(
        f"{len(strong)} strong signal{'s' if len(strong) > 1 else ''} for {tomorrow}",
        body
    )
    print("\nDone.")


def contract_type_hint(signals):
    types = set(r["contract_type"] for r in signals)
    if types == {"CALL"}:   return "CALLs"
    if types == {"PUT"}:    return "PUTs"
    return "CALLs/PUTs"


if __name__ == "__main__":
    main()
