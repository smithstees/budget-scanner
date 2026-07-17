// ══════════════════════════════════════════════════════════════════════════
// TRADE LOGGER — buy/sell buttons + Google Sheets sync
// Restored from pre-commit-37566f5 (Apr 9 2026 lost feature)
// Shared across app.html, live_scanner.html, index.html
// Storage keys: trade_log (localStorage), sheets_webapp_url (localStorage)
// ══════════════════════════════════════════════════════════════════════════
(function(w){
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  var trades   = JSON.parse(localStorage.getItem('trade_log') || '[]');
  var webAppUrl = localStorage.getItem('sheets_webapp_url') || '';
  var logState = null; // { action:'buy'|'sell', ticker:'', tradeId:null }

  // ── Storage ──────────────────────────────────────────────────────────────
  function save() { localStorage.setItem('trade_log', JSON.stringify(trades)); }

  // ── Sheets sync (fire and forget, non-critical) ──────────────────────────
  function syncToSheets(trade, type) {
    if (!webAppUrl) return;
    try {
      var payload = {
        date: trade.date,
        ticker: trade.ticker,
        direction: trade.direction || '',
        entryPrice: trade.entryPrice,
        exitPrice: trade.exitPrice || '',
        entryCost: trade.entryCost || '',
        exitValue: trade.exitValue || '',
        pnl: trade.pnl || '',
        pctGain: trade.pctGain || '',
        result: trade.result || (type === 'buy' ? 'OPEN' : ''),
        notes: type === 'sell' ? 'Closed via scanner app' : 'Entered via scanner app'
      };
      // no-cors avoids CORS preflight for Apps Script Web Apps
      fetch(webAppUrl, {
        method: 'POST',
        mode: 'no-cors',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).catch(function(e){ console.log('Sheets sync failed (non-critical):', e && e.message); });
    } catch(e) {
      console.log('Sheets sync error (non-critical):', e && e.message);
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────
  var TL = {
    getTrades: function() { return trades.slice(); },
    getOpen:   function() { return trades.filter(function(t){ return !t.exitPrice; }); },
    getClosed: function() { return trades.filter(function(t){ return t.exitPrice != null; }); },
    getWebAppUrl: function() { return webAppUrl; },

    setWebAppUrl: function(url) {
      url = (url || '').trim();
      if (!url) { webAppUrl = ''; localStorage.removeItem('sheets_webapp_url'); return true; }
      if (!/^https:\/\//.test(url)) return false;
      webAppUrl = url;
      localStorage.setItem('sheets_webapp_url', url);
      return true;
    },

    logBuy: function(ticker, pricePerShare, opts) {
      opts = opts || {};
      var val = parseFloat(pricePerShare);
      if (!ticker || !val || val <= 0) return null;
      var trade = {
        id: Date.now().toString(),
        ticker: String(ticker).trim().toUpperCase(),
        date: new Date().toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'}),
        entryDate: new Date().toISOString(),
        entryPrice: val,
        entryCost: Math.round(val * 100 * 100) / 100, // 1 contract = 100 shares
        exitPrice: null,
        direction: opts.direction || 'unknown', // 'CALL' | 'PUT' | 'STOCK' | 'unknown'
        strike: opts.strike || null,
        expiry: opts.expiry || null,
        notes:  opts.notes  || ''
      };
      trades.unshift(trade);
      save();
      syncToSheets(trade, 'buy');
      return trade;
    },

    logSell: function(tradeId, pricePerShare) {
      var val = parseFloat(pricePerShare);
      if (!val || val <= 0) return null;
      var trade = trades.find(function(t){ return t.id === tradeId; });
      if (!trade) return null;
      trade.exitPrice = val;
      trade.exitDate = new Date().toISOString();
      trade.exitValue = Math.round(val * 100 * 100) / 100;
      var pnl = Math.round((val - trade.entryPrice) * 100 * 100) / 100;
      var pct = Math.round(((val - trade.entryPrice) / trade.entryPrice) * 10000) / 100;
      trade.pnl = pnl;
      trade.pctGain = pct;
      trade.result = pct >= 50 ? '🎯 TARGET' : pct <= -50 ? '🛑 STOPPED' : pct > 0 ? '✓ WIN' : '✗ LOSS';
      save();
      syncToSheets(trade, 'sell');
      return trade;
    },

    deleteTrade: function(tradeId) {
      var i = trades.findIndex(function(t){ return t.id === tradeId; });
      if (i < 0) return false;
      trades.splice(i, 1);
      save();
      return true;
    },

    // Summary stats for UI
    stats: function() {
      var closed = trades.filter(function(t){ return t.exitPrice != null; });
      var open   = trades.filter(function(t){ return !t.exitPrice; });
      var wins   = closed.filter(function(t){ return (t.pnl||0) > 0; });
      var totalPnl = closed.reduce(function(s,t){ return s + (t.pnl || 0); }, 0);
      var winRate = closed.length ? Math.round((wins.length / closed.length) * 100) : 0;
      return {
        total: trades.length,
        open: open.length,
        closed: closed.length,
        wins: wins.length,
        losses: closed.length - wins.length,
        winRate: winRate,
        totalPnl: totalPnl
      };
    }
  };

  w.TradeLogger = TL;
})(window);
