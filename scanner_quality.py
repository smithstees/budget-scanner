"""
scanner_quality.py — quality filters and enrichments for options scanners.

Everything here is optional: each function returns useful info and callers
decide whether to hard-block a signal or just annotate it. Free-tier data
sources only:

    - Yahoo Finance chart API for stock bars (SPY regime, IV rank proxy)
    - Yahoo Finance quoteSummary for earnings dates
    - Nasdaq api.nasdaq.com for option chains (bid/ask/OI, spot spread)
    - Black-Scholes inversion to compute IV from mid, then delta

All fetches are wrapped in try/except so a single hiccup never breaks a scan.

Provides:
    - iv_rank(ticker) -> float | None    (0-100)
    - has_earnings_within(ticker, days) -> bool | None
    - target_delta_strike(ticker, spot, expiry_days, direction) -> dict | None
    - is_liquid(chain_entry) -> bool
    - spy_regime() -> "BULLISH" | "BEARISH" | "NEUTRAL"
    - SectorCap for enforcing MAX_PER_SECTOR
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import config

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


def _get_json(url: str, timeout: int = 15, extra_headers: dict | None = None) -> dict | None:
    """GET + parse JSON, gently. Returns None on any failure."""
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [quality] fetch failed ({url[:80]}...): {e}")
        return None


def _f(x) -> float | None:
    if x is None or x == "--":
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _i(x) -> int | None:
    if x is None or x == "--":
        return None
    try:
        return int(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────
# Historical Vol / IV Rank
# ─────────────────────────────────────────────────────────────────────
def _historical_volatility(closes: list[float], period: int = 30) -> float | None:
    if len(closes) < period + 1:
        return None
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i]:
            log_returns.append(math.log(closes[i] / closes[i - 1]))
    if len(log_returns) < period:
        return None
    recent = log_returns[-period:]
    mean = sum(recent) / len(recent)
    var = sum((r - mean) ** 2 for r in recent) / len(recent)
    daily_vol = math.sqrt(var)
    return daily_vol * math.sqrt(252)  # annualized


def iv_rank(ticker: str) -> float | None:
    """
    Approximate IV Rank using 1 year of realized vol as a proxy.

    True IV Rank compares current IV to 52-week IV range, but no free
    source exposes historical IV. Realized-vol IVR is a reasonable proxy:
    when realized vol is at the top of its 1-year range, implied vol
    usually is too (and premium sellers are happier than buyers).

    Returns 0-100 or None if unable to compute.
    """
    period2 = int(datetime.now(timezone.utc).timestamp())
    period1 = period2 - 400 * 24 * 60 * 60
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    data = _get_json(url)
    if not data:
        return None

    try:
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, TypeError, IndexError):
        return None

    if len(closes) < 60:
        return None

    # rolling 21-day realized vol series
    rolling = []
    for i in range(21, len(closes)):
        window = closes[i - 21 : i]
        rv = _historical_volatility(window, period=20)
        if rv is not None:
            rolling.append(rv)

    if len(rolling) < 30:
        return None

    recent = rolling[-1]
    lo = min(rolling)
    hi = max(rolling)
    if hi == lo:
        return 50.0
    ivr = (recent - lo) / (hi - lo) * 100.0
    return round(max(0.0, min(100.0, ivr)), 1)


# ─────────────────────────────────────────────────────────────────────
# Earnings blackout — Yahoo quoteSummary
# ─────────────────────────────────────────────────────────────────────
def has_earnings_within(ticker: str, days: int = None) -> bool | None:
    """Return True/False/None. None = couldn't determine (be conservative)."""
    if days is None:
        days = config.EARNINGS_BLACKOUT_DAYS
    url = (
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
        f"?modules=calendarEvents"
    )
    data = _get_json(url)
    if not data:
        return None
    try:
        events = data["quoteSummary"]["result"][0]["calendarEvents"]["earnings"]
        raw_dates = events.get("earningsDate", [])
        if not raw_dates:
            return False
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now + days * 86400
        for entry in raw_dates:
            raw = entry.get("raw") if isinstance(entry, dict) else None
            if raw and now <= raw <= cutoff:
                return True
        return False
    except (KeyError, TypeError, IndexError):
        return None


# ─────────────────────────────────────────────────────────────────────
# Option chain from Nasdaq (bid/ask/OI, no IV/delta — we compute those)
# ─────────────────────────────────────────────────────────────────────
def _fetch_nasdaq_chain(ticker: str, expiry_days: int) -> list[dict] | None:
    """
    Fetch a windowed option chain from Nasdaq. Returns rows like:
        {expiry: 'YYYY-MM-DD', strike: float, is_call: bool,
         bid: float, ask: float, oi: int, volume: int}
    """
    today = datetime.now(timezone.utc).date()
    from_date = today.strftime("%Y-%m-%d")
    to = today + timedelta(days=max(expiry_days + 21, 60))
    to_date = to.strftime("%Y-%m-%d")
    url = (
        f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(ticker)}/option-chain"
        f"?assetclass=stocks&fromdate={from_date}&todate={to_date}"
        f"&excode=oprac&callput=callput&money=all&type=all"
    )
    data = _get_json(url)
    if not data:
        return None
    try:
        rows = data["data"]["table"]["rows"]
    except (KeyError, TypeError):
        return None

    parsed: list[dict] = []
    current_expiry = None
    for row in rows:
        exp_group = (row.get("expirygroup") or "").strip()
        if exp_group:
            try:
                dt = datetime.strptime(exp_group, "%B %d, %Y")
                current_expiry = dt.strftime("%Y-%m-%d")
            except ValueError:
                current_expiry = None
            continue
        if not current_expiry:
            continue
        strike = _f(row.get("strike"))
        if strike is None:
            continue

        # calls
        c_bid = _f(row.get("c_Bid"))
        c_ask = _f(row.get("c_Ask"))
        if c_bid is not None or c_ask is not None:
            parsed.append({
                "expiry": current_expiry, "strike": strike, "is_call": True,
                "bid": c_bid or 0.0, "ask": c_ask or 0.0,
                "oi": _i(row.get("c_Openinterest")) or 0,
                "volume": _i(row.get("c_Volume")) or 0,
            })
        # puts
        p_bid = _f(row.get("p_Bid"))
        p_ask = _f(row.get("p_Ask"))
        if p_bid is not None or p_ask is not None:
            parsed.append({
                "expiry": current_expiry, "strike": strike, "is_call": False,
                "bid": p_bid or 0.0, "ask": p_ask or 0.0,
                "oi": _i(row.get("p_Openinterest")) or 0,
                "volume": _i(row.get("p_Volume")) or 0,
            })
    return parsed


def _pick_expiration_near(days_target: int, expiries: list[str]) -> str | None:
    if not expiries:
        return None
    today = datetime.now(timezone.utc).date()
    target = today + timedelta(days=days_target)
    def days_off(e):
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            return abs((d - target).days)
        except ValueError:
            return 9999
    return min(set(expiries), key=days_off)


# ─────────────────────────────────────────────────────────────────────
# Black-Scholes: implied vol + delta
# ─────────────────────────────────────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(iv: float, spot: float, strike: float, tte_days: int, is_call: bool) -> float:
    if iv <= 0 or spot <= 0 or strike <= 0 or tte_days <= 0:
        return 0.0
    t = tte_days / 365.0
    r = 0.05
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)
    except (ValueError, ZeroDivisionError):
        return 0.0
    if is_call:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _bs_delta(iv: float, spot: float, strike: float, tte_days: int, is_call: bool) -> float:
    if iv <= 0 or spot <= 0 or strike <= 0 or tte_days <= 0:
        return 0.0
    t = tte_days / 365.0
    r = 0.05
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    except (ValueError, ZeroDivisionError):
        return 0.0
    n = _norm_cdf(d1)
    return n if is_call else n - 1.0


def _implied_vol(mid: float, spot: float, strike: float, tte_days: int, is_call: bool) -> float | None:
    """Bisection solve for IV. Returns None if unsolvable."""
    if mid <= 0.01 or spot <= 0 or strike <= 0 or tte_days <= 0:
        return None
    lo, hi = 0.01, 5.0
    if _bs_price(hi, spot, strike, tte_days, is_call) < mid:
        return None  # unrealistically high price
    for _ in range(60):
        m = (lo + hi) / 2.0
        p = _bs_price(m, spot, strike, tte_days, is_call)
        if p > mid:
            hi = m
        else:
            lo = m
        if hi - lo < 1e-4:
            break
    return round((lo + hi) / 2.0, 3)


def target_delta_strike(
    ticker: str,
    spot: float,
    expiry_days: int,
    direction: str,
    delta_low: float = None,
    delta_high: float = None,
) -> dict | None:
    """
    Find a real strike from Nasdaq's chain whose computed |delta| falls in
    [delta_low, delta_high]. Returns a dict or None.
    """
    if delta_low is None:  delta_low  = config.TARGET_DELTA_MIN
    if delta_high is None: delta_high = config.TARGET_DELTA_MAX

    chain = _fetch_nasdaq_chain(ticker, expiry_days)
    if not chain:
        return None

    is_call = direction in ("BULLISH", "BULL")
    same_side = [c for c in chain if c["is_call"] == is_call]
    if not same_side:
        return None

    all_expiries = sorted({c["expiry"] for c in same_side})
    picked_expiry = _pick_expiration_near(expiry_days, all_expiries)
    if not picked_expiry:
        return None

    today = datetime.now(timezone.utc).date()
    tte_days = max(1, (datetime.strptime(picked_expiry, "%Y-%m-%d").date() - today).days)

    same_exp = [c for c in same_side if c["expiry"] == picked_expiry]

    best = None
    best_diff = float("inf")
    target_mid_delta = (delta_low + delta_high) / 2.0

    for opt in same_exp:
        strike = opt["strike"]
        bid = opt["bid"]
        ask = opt["ask"]
        if bid <= 0 and ask <= 0:
            continue
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else max(bid, ask)
        if mid <= 0.01:
            continue

        iv = _implied_vol(mid, spot, strike, tte_days, is_call)
        if iv is None:
            continue
        delta = abs(_bs_delta(iv, spot, strike, tte_days, is_call))
        if delta_low <= delta <= delta_high:
            diff = abs(delta - target_mid_delta)
            if diff < best_diff:
                best_diff = diff
                spread_pct = ((ask - bid) / mid) if mid > 0 else 1.0
                best = {
                    "strike": round(strike, 2),
                    "expiry": picked_expiry,
                    "tte_days": tte_days,
                    "iv": iv,
                    "delta": round(delta, 3),
                    "oi": opt["oi"],
                    "volume": opt["volume"],
                    "bid": round(bid, 3),
                    "ask": round(ask, 3),
                    "mid": round(mid, 3),
                    "spread_pct": round(spread_pct, 3),
                    "is_call": is_call,
                }
    return best


def is_liquid(chain_entry: dict) -> bool:
    """OI >= MIN_OPEN_INTEREST AND spread <= MAX_SPREAD_PCT_OF_MID."""
    if not chain_entry:
        return False
    if chain_entry.get("oi", 0) < config.MIN_OPEN_INTEREST:
        return False
    if chain_entry.get("spread_pct", 1.0) > config.MAX_SPREAD_PCT_OF_MID:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────
# SPY regime
# ─────────────────────────────────────────────────────────────────────
_SPY_CACHE: dict = {}


def spy_regime() -> str:
    """Return 'BULLISH' / 'BEARISH' / 'NEUTRAL' based on SPY vs 200-day SMA."""
    global _SPY_CACHE
    if _SPY_CACHE.get("regime"):
        return _SPY_CACHE["regime"]

    period2 = int(datetime.now(timezone.utc).timestamp())
    period1 = period2 - 300 * 24 * 60 * 60
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{config.SPY_REGIME_TICKER}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    data = _get_json(url)
    if not data:
        return "NEUTRAL"

    try:
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, TypeError, IndexError):
        return "NEUTRAL"

    if len(closes) < config.SPY_REGIME_SMA:
        return "NEUTRAL"

    sma = sum(closes[-config.SPY_REGIME_SMA:]) / config.SPY_REGIME_SMA
    last = closes[-1]
    regime = "BULLISH" if last > sma else "BEARISH"
    _SPY_CACHE["regime"] = regime
    _SPY_CACHE["last"] = round(last, 2)
    _SPY_CACHE["sma"] = round(sma, 2)
    return regime


def spy_details() -> dict:
    if not _SPY_CACHE.get("regime"):
        spy_regime()
    return dict(_SPY_CACHE)


# ─────────────────────────────────────────────────────────────────────
# Sector caps
# ─────────────────────────────────────────────────────────────────────
class SectorCap:
    """
    Enforce MAX_PER_SECTOR. Call `try_accept(sector)` per signal in the
    order you want prioritized (highest-scoring first). Returns True/False.
    """
    def __init__(self, cap: int = None):
        self.cap = cap if cap is not None else config.MAX_PER_SECTOR
        self.counts: dict[str, int] = {}

    def try_accept(self, sector: str) -> bool:
        c = self.counts.get(sector, 0)
        if c >= self.cap:
            return False
        self.counts[sector] = c + 1
        return True

    def state(self) -> dict[str, int]:
        return dict(self.counts)
