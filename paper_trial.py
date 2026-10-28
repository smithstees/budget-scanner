"""Finite 50-signal forward paper trial. No orders, paid APIs, or notifications."""
from __future__ import annotations
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import config
import live_scanner as live
import scanner_quality as quality

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / 'reports/paper-trial/state.json'
REPORT_PATH = ROOT / 'reports/paper-trial/latest.json'
ET = ZoneInfo('America/New_York')
RULES = dict(target_signals=50, starting_cash=200.0, max_entry_cost=30.0,
             max_open_positions=3, contracts_per_trade=1, fee_per_side=.65,
             slippage_per_share=.01, target_multiplier=1.5, stop_multiplier=.4,
             max_holding_days=7, realized_loss_stop=60.0, maximum_calendar_days=60,
             minimum_score=65, data_delay_warning='Public data may be delayed; hourly observations miss intrahour stops',
             selection='Existing live mean-reversion score >=65; exact long CALL/PUT contracts; existing quality filters unchanged')


def time_value(s):
    d = datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d.astimezone(timezone.utc)


def new_state(now):
    return dict(schema_version=1, trial_id='budget-options-50-v1', paper_only=True,
                rules=RULES.copy(), started_at=now.isoformat(), last_run_at=None,
                cash=RULES['starting_cash'], signals=[], observations=[],
                equity_high=RULES['starting_cash'], max_observed_drawdown=0.0,
                collection_finished=False, status='collecting', stop_reason=None)


def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def quote_valid(q):
    return q and all(finite(q.get(k)) for k in ('bid','ask')) and 0 <= q['bid'] <= q['ask']


def contract_key(s):
    return (s['ticker'], s['contract_type'], s['strike'], s['expiry'])


def close_positions(state, chains, now):
    rules=state['rules']
    for s in state['signals']:
        if s['status']!='OPEN': continue
        is_call=s['contract_type']=='CALL'
        q=next((q for q in chains.get(s['ticker'],[]) if q['strike']==s['strike'] and
                q['expiry']==s['expiry'] and q['is_call']==is_call),None)
        expiry=datetime.fromisoformat(s['expiry']+'T16:00:00').replace(tzinfo=ET).astimezone(timezone.utc)
        if now > expiry:
            # An expired contract's current absent quote is not a settlement record.
            s['status']='UNVERIFIED_EXIT'
            s['reason']='Expiry reached without verified settlement/exit; cost remains reserved'
            continue
        if not quote_valid(q): continue
        price=round(max(0,q['bid']-rules['slippage_per_share']),4)
        s['last_observed_bid']=q['bid']
        s['last_mark_at']=now.isoformat()
        s['last_mark_value']=round(price*100-rules['fee_per_side'],2)
        elapsed=now-time_value(s['entered_at'])
        reason=None
        if price<=s['entry_price']*rules['stop_multiplier']: reason='STOP'
        elif price>=s['entry_price']*rules['target_multiplier']: reason='TARGET'
        elif elapsed>=timedelta(days=rules['max_holding_days']): reason='TIME_EXIT'
        if reason:
            proceeds=round(price*100-rules['fee_per_side'],2)
            s.update(status='CLOSED', exit_price=price, exited_at=now.isoformat(),
                     exit_reason=reason, net_pnl=round(proceeds-s['entry_cost'],2))
            state['cash']=round(state['cash']+proceeds,2)


def accept_candidates(state,candidates,now):
    rules=state['rules']
    seen={s['daily_key'] for s in state['signals']}
    for candidate in sorted(candidates,key=lambda x:(-x['score'],x['ticker'])):
        if len(state['signals'])>=rules['target_signals'] or state['collection_finished']:break
        if not candidate.get('contract_verified') or candidate.get('score',0)<rules['minimum_score']:continue
        if candidate.get('contract_type') not in ('CALL','PUT'):continue
        if not candidate.get('expiry') or not finite(candidate.get('strike')) or not 0<candidate['entry_bid']<=candidate['entry_ask']:continue
        key='|'.join(map(str,(now.astimezone(ET).date().isoformat(),*contract_key(candidate))))
        if key in seen:continue
        seen.add(key)
        s={k:candidate[k] for k in ('ticker','contract_type','strike','expiry','score','entry_bid','entry_ask')}
        s.update(signal_id=hashlib.sha256(key.encode()).hexdigest()[:24],daily_key=key,
                 observed_at=now.isoformat(),status='SKIPPED',reason=None)
        entry_price=round(s['entry_ask']+rules['slippage_per_share'],4)
        cost=round(entry_price*100+rules['fee_per_side'],2)
        open_s=[x for x in state['signals'] if x['status']=='OPEN']
        if cost>rules['max_entry_cost']:s['reason']='Above $30 all-in cap'
        elif cost>state['cash']:s['reason']='Insufficient simulated cash'
        elif len(open_s)>=rules['max_open_positions']:s['reason']='Three open positions already'
        elif any(x['ticker']==s['ticker'] for x in open_s):s['reason']='Existing position in same ticker'
        else:
            s.update(status='OPEN',entry_price=entry_price,entry_cost=cost,entered_at=now.isoformat())
            state['cash']=round(state['cash']-cost,2)
        state['signals'].append(s)
    if len(state['signals'])>=rules['target_signals']:
        state['collection_finished']=True
        state['stop_reason']='50 qualifying signals collected'


def update_status(state,now):
    rules=state['rules']
    pnl=round(sum(s.get('net_pnl',0) for s in state['signals']),2)
    unresolved=[s for s in state['signals'] if s['status']=='OPEN']
    unknown=[s for s in state['signals'] if s['status']=='UNVERIFIED_EXIT']
    # Missing current marks stay unknown rather than being shown as safe cash.
    all_marked=all(s.get('last_mark_at')==now.isoformat() for s in unresolved) and not unknown
    equity=round(state['cash']+sum(s.get('last_mark_value',0) for s in unresolved),2) if all_marked else None
    if equity is not None:
        state['equity_high']=max(state['equity_high'],equity)
        state['max_observed_drawdown']=round(max(state['max_observed_drawdown'],state['equity_high']-equity),2)
    if pnl<=-rules['realized_loss_stop']:
        state.update(collection_finished=True,stop_reason='$60 realized paper loss guard reached')
    if (now-time_value(state['started_at'])).days>=rules['maximum_calendar_days']:
        state.update(collection_finished=True,stop_reason='60-day collection deadline reached')
    if state['collection_finished']:
        state['status']='following_open_positions' if unresolved else 'finished_with_missing_exits' if unknown else 'finished'
    return equity


def build_report(state,now,diagnostics,equity):
    rows=state['signals'];closed=[s for s in rows if s['status']=='CLOSED']
    groups=defaultdict(lambda:dict(closed=0,net_pnl=0.0))
    for s in closed:
        g=groups[s['contract_type']];g['closed']+=1;g['net_pnl']=round(g['net_pnl']+s['net_pnl'],2)
    net=round(sum(s['net_pnl'] for s in closed),2)
    return dict(trial_id=state['trial_id'],paper_only=True,as_of=now.isoformat(),status=state['status'],
                rules=state['rules'],qualifying_signals=len(rows),target_signals=50,
                outcomes=dict(Counter(s['status'] for s in rows)),closed_trades=len(closed),
                wins=sum(s['net_pnl']>0 for s in closed),net_realized_paper_pnl=net if closed else None,
                simulated_cash=state['cash'],current_observed_equity=equity,
                max_observed_drawdown=state['max_observed_drawdown'],stop_reason=state['stop_reason'],
                skipped_reasons=dict(Counter(s['reason'] for s in rows if s['status']=='SKIPPED')),
                descriptive_by_direction=dict(groups),diagnostics=diagnostics,
                conclusion='INSUFFICIENT_EVIDENCE' if len(closed)<30 else 'PAPER_RESULTS_ONLY_NO_INCOME_GUARANTEE',
                limitations=['No actual money or orders','Observed quotes are not guaranteed fills',
                             'Hourly checks can miss intrahour stops/targets; stops are not guaranteed',
                             'Repeated correlated signals are not independent trials',
                             'Taxes and account settlement restrictions are not simulated'])


def run(state,now,fetch_bars=live.fetch_intraday,fetch_chain=quality._fetch_nasdaq_chain):
    if state['rules']!=RULES:raise ValueError('Frozen trial rules differ; do not change an active experiment')
    diagnostics={'stocks_checked':0,'stock_data_missing':0,'quality_rejections':{},'eligible_this_run':0}
    candidates=[]
    if state['status'] in ('finished','finished_with_missing_exits'):
        return build_report(state,now,diagnostics,update_status(state,now))
    chains={ticker:fetch_chain(ticker,45) or [] for ticker in sorted({s['ticker'] for s in state['signals'] if s['status']=='OPEN'})}
    close_positions(state,chains,now)
    update_status(state,now)
    if not state['collection_finished']:
        regime=quality.spy_regime()
        for ticker in live.WATCHLIST:
            diagnostics['stocks_checked']+=1
            bars,prev=fetch_bars(ticker)
            if not bars:
                diagnostics['stock_data_missing']+=1;continue
            last=bars[-1].get('t')
            if last is None or not 0 <= now.timestamp()-last <= 30*60:
                diagnostics['stock_data_missing']+=1;continue
            sig=live.analyze(ticker,bars,prev)
            if not sig or sig['score']<RULES['minimum_score']:continue
            sig,ok,reasons=quality.evaluate_long_signal(sig,regime)
            if not ok:
                for reason in reasons:
                    diagnostics['quality_rejections'][reason]=diagnostics['quality_rejections'].get(reason,0)+1
            else:candidates.append(sig)
        diagnostics['eligible_this_run']=len(candidates)
        accept_candidates(state,candidates,now)
    equity=update_status(state,now)
    state['last_run_at']=now.isoformat()
    # Store all observations, including empty runs, so missing data is visible.
    state['observations'].append(dict(as_of=now.isoformat(),diagnostics=diagnostics))
    return build_report(state,now,diagnostics,equity)


def main():
    now=datetime.now(timezone.utc);local=now.astimezone(ET)
    state=json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else new_state(now)
    if local.weekday()>=5 or not 9*60+30 <= local.hour*60+local.minute <= 16*60:
        print('Outside regular weekday market window; no simulated entries or exits.')
        return
    report=run(state,now)
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    STATE_PATH.write_text(json.dumps(state,indent=2)+'\n')
    REPORT_PATH.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
