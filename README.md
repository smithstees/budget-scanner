# Budget Scanner

Research tools for low-cost options, with a manual trade journal and forward
paper review. No broker orders are placed. A setup score is a ranking heuristic,
not a win probability or a claim of reliable monthly income.

## Repair — October 28, 2026

- Long-option alerts require a quoted contract within the 30–45-day expiry,
  0.25–0.35 delta, liquidity, and **ask-price** budget limits. The default
  premium band is $0.10–$0.30 per share ($10–$30 per standard contract, before
  fees). If no contract fits, there is no actionable alert. Missing earnings,
  market regime, or quality-module data blocks alerts rather than passing them.
- Market scores are not calibrated probabilities. The “IV rank” free-data
  estimate is labeled as a **realized-volatility rank**, not true implied-volatility rank.
- Chatty intentionally looks for bullish dip/reversal candidates; its bearish
  candle history is recorded separately, rather than telling the reviewer that a
  CALL should profit when the stock falls. Prior-close indexing is corrected.
- Wheel candidates require real quoted puts. Quoted premium divided by collateral
  is not investment return. Short puts remain excluded from long-option P&L;
  assignment, subsequent stock losses, and covered-call accounting need their own
  validated evaluator.
- All 1,537 legacy signals lack enough exact-contract evidence for a profit test.
  They are retained, marked UNVERIFIED, and never retroactively given invented fills.

## Use the journal

Open the Trades tab in the app. New entries default to **Paper practice**.
Choose **Actual fill** only for an executed trade, then enter the exact instrument,
strike, expiry, quantity and total fees for that fill. Enter 0 for an expired-
worthless option. Partial exits reduce the remaining quantity; one contract cannot
be sold in halves. Fees are included in net realized P&L. Open-position unrealized
losses are not in that total.

Actual, paper, and legacy/unverified records have separate summaries. Old local
entries are preserved rather than silently labeled actual. The journal is stored
in the current browser; use **Export full journal** to save a private backup.
Do not commit your exported journal or brokerage records to this public repository.
Optional Google Sheets delivery is best effort, not confirmed receipt. The sample
Apps Script appends buy and sell events; do not sum both as independent trades.

## Review evidence

```sh
python -m unittest discover -s tests -v
node tests/test_trade_logger.js
python tests/check_scripts.py
python backtest_review.py
```

Outputs go to `reports/`. No data means unknown profit, not zero profit or proof
of a losing system. The old stock-movement/delta-based synthetic win rate is removed.

For new, contract-verified signals, `python observe_quotes.py` records observable
option bids/asks for later review in `option_quotes.jsonl`. It never trades or sends
notifications. This file is a forward observation log, not historical backfill.
Free-source timestamps can be delayed; recorded timestamps are retrieval times.

```sh
python observe_quotes.py
python backtest_review.py --quotes option_quotes.jsonl
```

The paper evaluator buys the recorded entry ask, exits at a later observed bid,
and subtracts a configurable fee per side (default $0.65). The frozen test rules
are +50% target, -60% stop, and a seven-calendar-day holding horizon, capped at
expiry. These are inherited research hypotheses, not optimized recommendations.
A gap through the stop uses the observed bid, not the desired stop price. Missing
exit quotes produce UNVERIFIED, never a fictitious flat or winning trade.

To record quotes manually, each JSONL row needs `signal_id`, `ts` (timezone-aware
ISO), `bid`, `ask`, `expiry` (YYYY-MM-DD), `strike`, and `contract_type` (CALL/PUT).
The contract must exactly match the signal. Exported actual journals are separate
from this paper-quote format.

The GitHub **Scanner evidence review** workflow is on-demand and uploads artifacts;
it does not schedule itself. Public market quote observations and the aggregate report are committed on main
so later manual reviews reuse them. Per-signal review details are also retained
as downloadable artifacts. These contain scanner market data, not your private journal. It does not publish private
trades. Existing scanner workflows remain on-demand. Browser-only scans continue to
use stock data and are explicitly labeled unverified research; they do not have the
Python contract/earnings checks.

## Before describing a strategy as a winner

Compare frozen strategies on new observations, including every eligible signal,
loss, fee, losing month, and missing quote. Report average net P&L per trade and
capital tied up, not just percentage wins. Do not choose thresholds using the same
period used to judge the outcome. Seek a separate, later validation period.

Current paper summaries do **not** simulate account capital, overlapping positions,
execution queues, slippage beyond the quoted spread, unsampled intraday moves,
taxes, or open-position mark-to-market drawdown. Sparse quotes cannot establish an
intraday stop was honored. Neither a positive paper result nor bug-free software
establishes that $500/month is reliable. No parameter “winning combo” has been
validated by this repair.

## Finite 50-signal test (authorized October 28, 2026)

`paper_trial.py` runs a separate forward experiment, without calling any order or
notification function. Frozen rules: $200 hypothetical starting cash; one long
CALL or PUT per accepted entry; $30 maximum entry including $0.65 fee and $0.01
per-share adverse slippage; at most three open positions and one per ticker.
Entry score is at least 65, with the repaired contract/earnings/liquidity checks.
The first 50 qualifying signals are recorded in chronological scan order (ranked
by score within a scan). The same contract can appear at most once per ET date.
All skipped signals and reasons stay in the report; 50 signals is not necessarily
50 executed paper trades when cash/capacity is constrained.

Full-position exits use the first observed bid less $0.01 slippage at +50%, -60%,
or after seven calendar days. Each exit includes a $0.65 fee. New intake pauses
after $60 of realized simulated losses, 50 signals, or a 60-day collection limit;
open positions continue being followed. That loss guard does not guarantee losses
cannot exceed $60 between observations. An expired position with no verified exit
remains explicitly unverified, with its cost reserved, rather than becoming a win.

The Fifty-signal paper trial workflow starts on the implementation push and checks
hourly during weekday market windows, using an ET runtime guard for DST. GitHub
schedules can be delayed or skipped. Market holidays may run and are rejected by
stock-bar freshness checks. Public data can be delayed; hourly observations cannot
establish whether an intrahour stop/target happened first. This is a coarse forward
experiment, not an executable intraday performance guarantee. The original general
scanner schedules remain paused. No paid data subscriptions or real-money orders
are authorized by this experiment.

Persistent public experiment evidence lives in `reports/paper-trial/state.json`
and `reports/paper-trial/latest.json`. The report distinguishes qualifying signals,
skipped entries, actual paper positions, missing observations, realized P&L, and
observed marked equity/drawdown. Missing marks are unknown. Closed P&L is not the
same as total account return when positions remain open/unverified. Direction
comparisons are descriptive, not a reason to retroactively cherry-pick a winner.
The experiment stops collecting automatically; its completion status is reported
by the follow-up task. Scheduler calls after completion do not fetch new data.
