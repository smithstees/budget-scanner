"""
signal_log.py — append signals to signals.jsonl for later performance review.

Each line is one JSON object. Fields kept minimal + stable:

    scanner: "nightly" | "chatty" | "live" | "wheel"
    ts: ISO 8601 UTC timestamp when the signal was logged
    date: YYYY-MM-DD (US Eastern for readability)
    ticker: string
    trend: "BULLISH" | "BEARISH" (or "WHEEL" for CSP)
    score: int (0-100)
    price: float (stock price at signal time)
    strike: float (recommended strike, if applicable)
    contract_type: "CALL" | "PUT" | "PUT_SELL" (wheel) | None
    est_cost: float (estimated $/share of contract, if computed)
    rel_vol: float
    atr_pct: float
    rsi: int (nightly only, else None)
    pushed: bool (whether it triggered a phone push)

Used by backtest_review.py to pull entry prices and score signals
against subsequent market performance.

Kept intentionally small — one line per signal, easy to grep, easy to
process incrementally, safe to commit to git.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Log file lives at repo root so both scanners and backtest_review can find it.
LOG_PATH = Path(__file__).resolve().parent / "signals.jsonl"


def _et_date_str() -> str:
    """Format today's date in Eastern time (roughly — GH runners are UTC)."""
    # Simple offset: UTC - 4h for EDT, UTC - 5h for EST.
    # For a log record, 'roughly today' is good enough.
    utc_now = datetime.now(timezone.utc)
    et_hour = (utc_now.hour - 4) % 24
    # If subtracting 4 crossed midnight backwards, roll date back one day
    if utc_now.hour < 4:
        # It's still yesterday in ET
        from datetime import timedelta
        et_date = (utc_now - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        et_date = utc_now.strftime("%Y-%m-%d")
    return et_date


def log_signal(scanner: str, sig: dict[str, Any], pushed: bool = False) -> None:
    """
    Append one signal to signals.jsonl.

    scanner: identifier for which scanner produced this signal
    sig: the signal dict (must have at least 'ticker' + 'trend')
    pushed: whether this signal triggered a phone notification
    """
    try:
        row = {
            "scanner": scanner,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "date": _et_date_str(),
            "ticker": sig.get("ticker"),
            "trend": sig.get("trend"),
            "score": sig.get("score"),
            "price": sig.get("price"),
            "strike": sig.get("strike"),
            "contract_type": sig.get("contract_type"),
            "est_cost": sig.get("est_cost"),
            "rel_vol": sig.get("rel_vol") or sig.get("relVol"),
            "atr_pct": sig.get("atr_pct") or sig.get("atrPct"),
            "rsi": sig.get("rsi"),
            "pushed": bool(pushed),
        }
        # Strip None values to keep the log small
        row = {k: v for k, v in row.items() if v is not None}

        # Ensure parent dir exists (should always, but be safe)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception as e:  # never let logging break a scanner
        print(f"[signal_log] non-critical write failure: {e}")


def read_signals() -> list[dict[str, Any]]:
    """Read all signals from the log. Returns empty list if none."""
    if not LOG_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    with LOG_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
