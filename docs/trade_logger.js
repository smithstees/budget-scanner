// Manual fill journal. No broker orders. Local data is never published to GitHub.
(function(w){
  'use strict';
  var trades;
  try { trades = JSON.parse(localStorage.getItem('trade_log') || '[]'); }
  catch(e) { throw new Error('Trade log cannot be read. Export/recover local storage before continuing.'); }
  if (!Array.isArray(trades)) throw new Error('Invalid trade log; existing storage left untouched.');
  var webAppUrl = localStorage.getItem('sheets_webapp_url') || '';
  function number(v) { return v === '' || v == null ? NaN : Number(v); }
  function valid(n) { return typeof n === 'number' && Number.isFinite(n); }
  function cents(n) { return Math.round(n * 100) / 100; }
  function remaining(t) { return t.remainingQuantity == null ? (t.exitPrice == null ? 1 : 0) : t.remainingQuantity; }
  function save() { localStorage.setItem('trade_log', JSON.stringify(trades)); }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function syncToSheets(trade, type) {
    if (!webAppUrl) return;
    var payload = Object.assign({}, trade, {event: type});
    // no-cors cannot confirm server acceptance; local journal remains authoritative.
    fetch(webAppUrl, {method:'POST', mode:'no-cors', headers:{'Content-Type':'text/plain'},
      body:JSON.stringify(payload)}).catch(function(){});
  }
  var TL = {
    getTrades: function(){ return copy(trades); },
    getOpen: function(){ return copy(trades.filter(function(t){ return remaining(t) > 0; })); },
    getClosed: function(){ return copy(trades.filter(function(t){ return remaining(t) === 0; })); },
    getWebAppUrl: function(){ return webAppUrl; },
    setWebAppUrl: function(url){
      url = (url || '').trim();
      if (url && !/^https:\/\//.test(url)) return false;
      webAppUrl = url;
      if (url) localStorage.setItem('sheets_webapp_url', url);
      else localStorage.removeItem('sheets_webapp_url');
      return true;
    },
    logBuy: function(ticker, pricePerShare, opts){
      opts = opts || {};
      var val = number(pricePerShare), qty = number(opts.quantity == null ? 1 : opts.quantity);
      var fees = number(opts.fees == null ? 0 : opts.fees);
      var direction = opts.direction || 'CALL';
      if (!/^[A-Z0-9.^-]{1,12}$/i.test(ticker || '') || !valid(val) || val <= 0 ||
          !Number.isInteger(qty) || qty < 1 || !valid(fees) || fees < 0 ||
          ['CALL','PUT','STOCK'].indexOf(direction) === -1) return null;
      var multiplier = direction === 'STOCK' ? 1 : 100;
      var trade = {
        schemaVersion:2, id:w.crypto && w.crypto.randomUUID ? w.crypto.randomUUID() : String(Date.now())+'-'+Math.random(),
        ticker:String(ticker).toUpperCase(), date:new Date().toLocaleDateString('en-US'),
        entryDate:new Date().toISOString(), entryPrice:val, quantity:qty, remainingQuantity:qty,
        multiplier:multiplier, entryFees:fees, entryCost:cents(val*qty*multiplier+fees),
        exitPrice:null, exits:[], pnl:0, direction:direction,
        mode:opts.mode === 'actual' ? 'actual' : 'paper',
        strategy:opts.strategy || 'manual', strike:opts.strike || null, expiry:opts.expiry || null,
        notes:opts.notes || ''
      };
      trades.unshift(trade); save(); syncToSheets(trade,'buy'); return copy(trade);
    },
    logSell: function(id, pricePerShare, opts){
      opts = opts || {};
      var trade = trades.find(function(t){ return t.id === id; });
      if (!trade || remaining(trade) === 0) return null;
      var val = number(pricePerShare), qty = number(opts.quantity == null ? remaining(trade) : opts.quantity);
      var fees = number(opts.fees == null ? 0 : opts.fees);
      if (!valid(val) || val < 0 || !Number.isInteger(qty) || qty < 1 || qty > remaining(trade) || !valid(fees) || fees < 0) return null;
      // Old entries retain their history; do not relabel them actual or paper.
      if (trade.quantity == null) { trade.quantity=1; trade.remainingQuantity=1; trade.multiplier=100; trade.entryFees=0; trade.mode='unverified'; }
      trade.exits = trade.exits || [];
      var net = cents((val-trade.entryPrice)*qty*trade.multiplier-fees-trade.entryFees*qty/trade.quantity);
      trade.exits.push({ts:new Date().toISOString(),price:val,quantity:qty,fees:fees,pnl:net});
      trade.remainingQuantity -= qty;
      trade.pnl = cents(trade.exits.reduce(function(s,x){ return s+x.pnl; },0));
      trade.exitValue = cents(trade.exits.reduce(function(s,x){ return s+x.price*x.quantity*trade.multiplier-x.fees; },0));
      var allocatedCost = trade.entryCost * (trade.quantity-trade.remainingQuantity)/trade.quantity;
      trade.pctGain = cents(trade.pnl/allocatedCost*100);
      if (trade.remainingQuantity === 0) {
        trade.exitPrice = trade.exits.reduce(function(s,x){ return s+x.price*x.quantity; },0)/trade.quantity;
        trade.exitDate = trade.exits[trade.exits.length-1].ts;
        trade.result = trade.pnl > 0 ? 'WIN' : trade.pnl < 0 ? 'LOSS' : 'FLAT';
      } else trade.result = 'PARTIAL';
      save(); syncToSheets(trade,'sell'); return copy(trade);
    },
    expire: function(id, opts){ return TL.logSell(id,0,opts); },
    deleteTrade: function(id){
      var i=trades.findIndex(function(t){return t.id===id;});
      if(i<0) return false;
      trades.splice(i,1); save(); return true;
    },
    exportJSON: function(){ return JSON.stringify({schemaVersion:2,exportedAt:new Date().toISOString(),trades:trades},null,2); },
    download: function(){
      var url=URL.createObjectURL(new Blob([TL.exportJSON()],{type:'application/json'}));
      var a=document.createElement('a'); a.href=url; a.download='trade-journal.json'; a.click();
      setTimeout(function(){URL.revokeObjectURL(url);},1000);
    },
    stats: function(mode){
      var selected=trades.filter(function(t){return (t.mode || 'unverified') === (mode || 'actual');});
      var closed=selected.filter(function(t){return remaining(t)===0;});
      var wins=closed.filter(function(t){return t.pnl>0;}).length;
      return {total:selected.length, open:selected.length-closed.length, closed:closed.length,wins:wins,
        losses:closed.filter(function(t){return t.pnl<0;}).length,
        winRate:closed.length?Math.round(wins/closed.length*100):0,
        totalPnl:cents(selected.reduce(function(s,t){return s+(t.pnl || 0);},0)),
        allOpen:trades.filter(function(t){return remaining(t)>0;}).length,
        unverified:trades.filter(function(t){return !t.mode || t.mode==='unverified';}).length};
    }
  };
  w.TradeLogger=TL;
})(window);
