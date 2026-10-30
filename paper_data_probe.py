"""Small provider health probe, including outside trading hours. Never trades.

This is transport/schema evidence only, not a qualifying trial observation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import live_scanner as live
import scanner_quality as quality
import market_data


def main():
    now = datetime.now(timezone.utc)
    path = Path(__file__).resolve().parent / 'reports/paper-trial/data-health.json'
    if path.exists() and json.loads(path.read_text())['as_of'][:10] == now.date().isoformat():
        print('Daily diagnostic already recorded; no additional provider requests.')
        return
    market_data.reset_events()
    bars, previous = live.fetch_intraday('SOFI')
    earnings = quality.has_earnings_within('SOFI')
    volatility = quality.iv_rank('SOFI')
    regime = quality.spy_regime()
    chain = quality._fetch_nasdaq_chain('SOFI', 45)
    result = dict(as_of=now.isoformat(), paper_only=True, diagnostic_only=True,
                  ticker='SOFI', stock_bars=len(bars or []),
                  last_stock_bar=(bars[-1]['t'] if bars else None),
                  earnings_available=earnings is not None,
                  realized_volatility_available=volatility is not None,
                  regime_available=regime != 'NEUTRAL',
                  option_chain=quality.CHAIN_HEALTH.get('SOFI', {}),
                  transport=market_data.health(),
                  note='Not a signal or fill. Outside-hours data cannot establish intraday usability.')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
