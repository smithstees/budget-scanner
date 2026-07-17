"""
backtest_review.py — weekly retrospective on scanner signals.

Reads signals.jsonl (produced by scanner.py / chatty_scanner.py / live_scanner.py /
wheel_scanner.py) and evaluates each signal against subsequent price action.

For each signal from the past week (default) it:
  1. Looks up the stock price ~7 trading days after the signal (or the most
     recent price if the window hasn't fully closed yet).
  2. Estimates the return the buyer would have gotten on the recommended
     runway contract, given the ATR-based cost estimate and how far price
     moved toward the strike.
  3. Classifies the signal as WIN (>= +50% on the contract), LOSS (<= -50%),
     BREAKEVEN, or OPEN (still within the window).

Runs weekly (Sunday night ET) via .github/workflows/backtest_review.yml.
Pushes a summary to ntfy.sh topic `ragebudgetopt`.

The point is to build a real, self-honest track record of the scanner's
picks so we can see which scanner (nightly / chatty / live / wheel) is
actually earning its keep.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from signal_log import LOG_PATH, read_signals

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ragebudgetopt")
LOOKBACK_DAYS = int(os.environ.get("BACKTEST_LOOKBACK_DAYS", "7"))
HORIZON_DAYS = int(os.environ.get("BACKTEST_HORIZON_DAYS", "7"))

# Where scored signals get written for later analysis
SCORED_PATH = Path(__file__).resolve().parent / "signals_scored.jsonl"


def _ascii(s: str) -> str:
    """Sanitize ntfy Title header (latin-1 only)."""
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201C": '"', "\u201D": '"',
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s.encode("ascii", "ignore").decode("ascii")


def fetch_yahoo_bars(ticker: str, days: int = 30) -> list[dict]:
    """Pull daily bars from Yahoo for the last ~N days. Returns list of
    {t: timestamp_seconds, o, h, l, c, v} sorted oldest → newest."""
    period2 = int(datetime.now(timezone.utc).timestamp())
    period1 = period2 - days * 24 * 60 * 60
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  yahoo fetch failed for {ticker}: {e}")
        return []

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
        bars = []
        for i, ts in enumerate(timestamps):
            if q["close"][i] is None:
                continue
            bars.append({
                "t": ts,
                "o": q["open"][i],
                "h": q["high"][i],
                "l": q["low"][i],
                "c": q["close"][i],
                "v": q["volume"][i],
            })
        return bars
    except (KeyError, TypeError, IndexError):
        return []


def price_on_or_after(bars: list[dict], target_dt: datetime) -> tuple[float, float] | None:
    """Return (close_at_first_bar_on_or_after, high_since_entry) or None if no bars.
    Also returns the *high* seen since target_dt so we can detect intra-window peaks."""
    ts_target = target_dt.timestamp()
    entry_bar = None
    max_high = None
    for b in bars:
        if b["t"] >= ts_target:
            if entry_bar is None:
                entry_bar = b
                max_high = b["h"]
            else:
                if b["h"] > max_high:
                    max_high = b["h"]
    if entry_bar is None:
        return None
    return entry_bar["c"], max_high


def estimate_contract_return(sig: dict, current_price: float, peak_price: float) -> tuple[float, float]:
    """
    Estimate the contract's % return given the underlying's move.

    Uses a rough "delta ≈ 0.3 for OTM 30-45DTE" heuristic:
      new_contract ≈ entry_contract + delta * (price_move) - theta_decay
    Then converts to a % return on entry_contract.

    Returns (return_pct_at_peak, return_pct_at_current).
    """
    entry_price = sig.get("price")
    strike = sig.get("strike")
    est_cost = sig.get("est_cost")  # $/share of contract
    trend = sig.get("trend", "BULLISH")

    if not entry_price or not est_cost or est_cost <= 0:
        return 0.0, 0.0

    # Direction: bullish contracts gain when price rises, bearish when it falls
    if trend == "BULLISH" or trend == "WHEEL":
        peak_move = peak_price - entry_price
        now_move  = current_price - entry_price
    else:  # BEARISH -> PUTs
        peak_move = entry_price - peak_price
        now_move  = entry_price - current_price

    # Rough delta estimate (OTM ~0.30, closer to strike = higher)
    if strike:
        distance_pct = abs(strike - entry_price) / entry_price if entry_price else 1
        # closer strike -> higher delta
        delta = max(0.15, 0.45 - distance_pct * 2)
    else:
        delta = 0.3

    # Theta over ~7 days on a 30-45 DTE contract: roughly 5-8% of premium
    theta_decay_pct = 6.0

    # $ change in contract per share = delta * $ move in stock
    peak_contract_change_per_share = delta * peak_move
    now_contract_change_per_share  = delta * now_move

    peak_pct = ((peak_contract_change_per_share / est_cost) * 100.0) - theta_decay_pct
    now_pct  = ((now_contract_change_per_share  / est_cost) * 100.0) - theta_decay_pct

    # A long option cannot lose more than 100% of its premium.
    peak_pct = max(peak_pct, -100.0)
    now_pct  = max(now_pct,  -100.0)

    return round(peak_pct, 1), round(now_pct, 1)


def classify(peak_pct: float, now_pct: float) -> str:
    """
    Given peak and current returns, decide what the trade would have been.

    Rule mirrors user's strategy:
      - Sell half at +50% → if peak hit >= +50%, WIN
      - Stop at -60% → if peak >= -60% AND now <= -60%, LOSS
      - Otherwise BREAKEVEN or OPEN
    """
    if peak_pct >= 50:
        return "WIN"
    if now_pct <= -60:
        return "LOSS"
    if peak_pct >= 20 or now_pct >= 20:
        return "SMALL_WIN"
    if now_pct <= -30:
        return "SMALL_LOSS"
    return "FLAT"


def review() -> dict:
    signals = read_signals()
    if not signals:
        print("No signals in log yet.")
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    recent = []
    for s in signals:
        try:
            ts = datetime.fromisoformat(s["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            recent.append((ts, s))

    print(f"Reviewing {len(recent)} signals from last {LOOKBACK_DAYS} days")

    # Group by ticker to only fetch bars once per ticker
    by_ticker: dict[str, list[tuple[datetime, dict]]] = defaultdict(list)
    for ts, s in recent:
        by_ticker[s.get("ticker", "?")].append((ts, s))

    scored: list[dict] = []
    for ticker, entries in by_ticker.items():
        if not ticker or ticker == "?":
            continue
        bars = fetch_yahoo_bars(ticker, days=30)
        if not bars:
            print(f"  no bars for {ticker}")
            continue
        for ts, sig in entries:
            price_check = price_on_or_after(bars, ts)
            if price_check is None:
                # Signal from earlier today, no bar yet
                continue
            _entry_bar_close, peak_price = price_check
            # Current price = last close in bars
            current_price = bars[-1]["c"]

            peak_pct, now_pct = estimate_contract_return(sig, current_price, peak_price)
            outcome = classify(peak_pct, now_pct)
            scored.append({
                **sig,
                "review_current_price": round(current_price, 2),
                "review_peak_price": round(peak_price, 2),
                "review_peak_pct": peak_pct,
                "review_now_pct": now_pct,
                "review_outcome": outcome,
                "review_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })

    return {"scored": scored, "count": len(scored)}


def write_scored(scored: list[dict]) -> None:
    """Append scored rows to signals_scored.jsonl for accumulating history."""
    with SCORED_PATH.open("a", encoding="utf-8") as fh:
        for s in scored:
            fh.write(json.dumps(s, separators=(",", ":")) + "\n")


def build_summary(scored: list[dict]) -> tuple[str, str]:
    """Build ntfy Title + Body summarizing the week."""
    if not scored:
        return (
            "Weekly Scanner Review — no data",
            "No signals recorded this week. Nothing to score."
        )

    # Tally by scanner
    by_scanner: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in scored:
        sc = s.get("scanner", "?")
        oc = s.get("review_outcome", "?")
        by_scanner[sc][oc] += 1
        by_scanner[sc]["total"] += 1

    # Best/worst
    by_perf = sorted(scored, key=lambda x: x.get("review_peak_pct", 0), reverse=True)
    top = by_perf[:3]
    worst = [x for x in by_perf if x.get("review_now_pct", 0) <= -30][:3]

    wins = sum(1 for s in scored if s.get("review_outcome") == "WIN")
    small_wins = sum(1 for s in scored if s.get("review_outcome") == "SMALL_WIN")
    losses = sum(1 for s in scored if s.get("review_outcome") == "LOSS")
    small_losses = sum(1 for s in scored if s.get("review_outcome") == "SMALL_LOSS")
    flat = sum(1 for s in scored if s.get("review_outcome") == "FLAT")
    total = len(scored)
    win_rate = round((wins + small_wins) / total * 100) if total else 0

    lines = [
        f"Signals reviewed: {total} (last {LOOKBACK_DAYS} days)",
        f"WIN: {wins}  SMALL_WIN: {small_wins}",
        f"LOSS: {losses}  SMALL_LOSS: {small_losses}  FLAT: {flat}",
        f"Win rate (any green): {win_rate}%",
        "",
        "── By scanner ──",
    ]
    for sc, counts in sorted(by_scanner.items()):
        total_sc = counts.get("total", 0)
        w = counts.get("WIN", 0) + counts.get("SMALL_WIN", 0)
        l = counts.get("LOSS", 0) + counts.get("SMALL_LOSS", 0)
        wr = round(w / total_sc * 100) if total_sc else 0
        lines.append(f"  {sc}: {total_sc} signals · {w}W {l}L · {wr}% green")

    if top:
        lines.append("")
        lines.append("── Best 3 (peak %) ──")
        for s in top:
            lines.append(
                f"  {s.get('ticker')} ({s.get('scanner')}): "
                f"peak {s.get('review_peak_pct')}% · now {s.get('review_now_pct')}% · "
                f"{s.get('review_outcome')}"
            )

    if worst:
        lines.append("")
        lines.append("── Worst 3 (now %) ──")
        for s in worst:
            lines.append(
                f"  {s.get('ticker')} ({s.get('scanner')}): "
                f"peak {s.get('review_peak_pct')}% · now {s.get('review_now_pct')}%"
            )

    title = f"Weekly Scanner Review — {wins + small_wins}W / {losses + small_losses}L / {flat} flat"
    body = "\n".join(lines)
    return title, body


def push_summary(title: str, body: str) -> None:
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title": _ascii(title),
                "Priority": "default",
                "Tags": "bar_chart",
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15):
            pass
        print(f"Pushed: {title}")
    except Exception as e:
        print(f"push error: {e}")


def main():
    print(f"\n{'='*60}")
    print(f"Weekly Backtest Review — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Lookback: {LOOKBACK_DAYS} days")
    print(f"{'='*60}\n")

    result = review()
    scored = result.get("scored", [])

    if scored:
        write_scored(scored)

    title, body = build_summary(scored)
    print(f"\n{title}\n{'-'*60}\n{body}\n")
    push_summary(title, body)


if __name__ == "__main__":
    main()
