"""
config.py — single source of truth for scanner tunables.

Import from any scanner instead of hard-coding values. Anything not
here is scanner-specific behavior (e.g. wheel-only settings live in
wheel_scanner.py).

Environment variable overrides (all optional):
    NTFY_TOPIC          — override phone push topic
    NOTIFY_MIN_SCORE    — override push threshold (int)
    STOCK_PRICE_MIN     — override lower price band ($)
    STOCK_PRICE_MAX     — override upper price band ($)
    QUALITY_STRICT      — 1 to enforce all quality filters; 0 to log-only
"""
from __future__ import annotations
import os

# ── Alerting ───────────────────────────────────────────────────────
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ragebudgetopt")

# ── Price/budget band ──────────────────────────────────────────────
# Below $2 = often delisted / illiquid options
# Above $15 = 3-5 OTM options usually cost > $30/contract
STOCK_PRICE_MIN = float(os.environ.get("STOCK_PRICE_MIN", "2.0"))
STOCK_PRICE_MAX = float(os.environ.get("STOCK_PRICE_MAX", "15.0"))

# ── Runway contract targeting ──────────────────────────────────────
EXPIRY_DAYS_MIN = 30
EXPIRY_DAYS_MAX = 45
CONTRACT_MIN    = 0.10  # $ per share
CONTRACT_MAX    = 0.30  # $ per share
TARGET_DELTA_MIN = 0.25
TARGET_DELTA_MAX = 0.35

# ── Alerts thresholds ──────────────────────────────────────────────
# Nightly: 60. Live (intraday): 55. Chatty: 55. Wheel: 65 for STRONG.
NOTIFY_MIN_SCORE = int(os.environ.get("NOTIFY_MIN_SCORE", "60"))

# ── Rate-limits ────────────────────────────────────────────────────
POLYGON_DELAY_SEC = 13  # free tier: ~5 calls/min

# ── Quality-filter behavior ────────────────────────────────────────
# strict: signal fails if a filter fails
# loose:  signal keeps score but downgraded / annotated
QUALITY_STRICT = os.environ.get("QUALITY_STRICT", "1") == "1"

# IV Rank: >60 = elevated. Skip long-premium ideas above this.
IV_RANK_CEILING = 60.0

# Earnings within N days = skip (post-earnings IV crush kills options).
EARNINGS_BLACKOUT_DAYS = int(os.environ.get("EARNINGS_BLACKOUT_DAYS", "21"))

# Liquidity minimums
MIN_OPEN_INTEREST = 100
MAX_SPREAD_PCT_OF_MID = 0.15  # bid/ask spread <= 15% of mid

# SPY regime: if SPY < 200-day SMA, prefer PUTs over CALLs
SPY_REGIME_TICKER = "SPY"
SPY_REGIME_SMA = 200

# Sector caps: max signals per theme per single scan
MAX_PER_SECTOR = 2

# ── Watchlist (with sector tags for MAX_PER_SECTOR) ────────────────
# Sector tags are informal — buckets that tend to trade together.
WATCHLIST: list[tuple[str, str]] = [
    # Fintech / lending
    ("SOFI", "fintech"),
    ("OPEN", "fintech"),
    # Airlines / cruise (low-priced, volatile)
    ("JBLU", "travel"),
    ("AAL",  "travel"),
    ("CCL",  "travel"),
    ("NCLH", "travel"),
    # EVs / mobility
    ("RIVN", "ev"),
    ("LCID", "ev"),
    ("JOBY", "ev"),
    ("ACHR", "ev"),
    ("WKHS", "ev"),
    ("NIO",  "ev"),
    ("XPEV", "ev"),
    ("LI",   "ev"),
    # Crypto miners
    ("MARA", "crypto"),
    ("RIOT", "crypto"),
    ("CLSK", "crypto"),
    ("CIFR", "crypto"),
    ("WULF", "crypto"),
    # Social / consumer
    ("SNAP", "social"),
    ("PINS", "social"),
    # Cannabis / small-cap speculative
    ("TLRY", "spec"),
    ("SNDL", "spec"),
    ("CLOV", "spec"),
    ("ATER", "spec"),
    ("IDEX", "spec"),
    ("MVIS", "spec"),
    # Telecom / media low-priced
    ("NOK",  "telecom"),
    ("SIRI", "telecom"),
    ("T",    "telecom"),
    # Health / other budget names
    ("SENS", "misc"),
    ("GRAB", "misc"),
    ("F",    "misc"),
    ("LYFT", "misc"),
    ("PLUG", "energy"),
    ("SPWR", "energy"),
    ("ENVX", "energy"),
    # Brazilian ADRs / shipping
    ("VALE", "commodities"),
    ("ITUB", "commodities"),
    ("BBD",  "commodities"),
    ("ZIM",  "commodities"),
]

# Just the tickers for backward compat with scripts expecting a flat list
WATCHLIST_TICKERS: list[str] = [t for t, _ in WATCHLIST]

# Ticker -> sector map for cap enforcement
TICKER_SECTOR: dict[str, str] = {t: s for t, s in WATCHLIST}


def sector_of(ticker: str) -> str:
    return TICKER_SECTOR.get(ticker.upper(), "misc")
