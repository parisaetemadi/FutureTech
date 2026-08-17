/* Future Tech Market Map — filtering, layout and rendering. */
(function () {
  'use strict';

  var GAP = 10;        // gap between category panels
  var PAD = 6;         // inner padding of a panel
  var HEAD = 28;       // category header strip height
  var TGAP = 5;        // gap between company tiles

  var DATA = null;
  var CATS = {};       // id -> category
  var els = {};

  // ---------- formatting ----------

  function sig3(n) {
    var a = Math.abs(n);
    var d = a >= 100 ? 0 : a >= 10 ? 1 : 2;
    return n.toFixed(d);
  }

  function money(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    var neg = v < 0;
    var a = Math.abs(v);
    var s;
    if (a >= 1e12) s = sig3(a / 1e12) + 'T';
    else if (a >= 1e9) s = sig3(a / 1e9) + 'B';
    else if (a >= 1e6) s = sig3(a / 1e6) + 'M';
    else if (a >= 1e3) s = sig3(a / 1e3) + 'K';
    else s = String(Math.round(a));
    return (neg ? '−$' : '$') + s;
  }

  function clamp(lo, hi, v) { return Math.max(lo, Math.min(hi, v)); }

  function dataYear() {
    var y = parseInt(String(DATA.asOf).slice(0, 4), 10);
    return isNaN(y) ? new Date().getFullYear() : y;
  }

  function ageOf(c) {
    return c.founded ? dataYear() - c.founded : null;
  }

  // ---------- filtering ----------

  function currentFilters() {
    var minB = parseFloat(els.capMin.value);
    var maxB = parseFloat(els.capMax.value);
    return {
      category: els.sector.value,
      min: isNaN(minB) ? null : minB * 1e9,
      max: isNaN(maxB) ? null : maxB * 1e9,
      maxAge: els.age.value === 'all' ? null : parseInt(els.age.value, 10)
    };
  }

  function applyFilters() {
    var f = currentFilters();
    return DATA.companies.filter(function (c) {
      if (f.category !== 'all' && c.category !== f.category) return false;
      if (f.min !== null && c.marketCap < f.min) return false;
      if (f.max !== null && c.marketCap > f.max) return false;
      if (f.maxAge !== null) {
        var a = ageOf(c);
        if (a === null || a > f.maxAge) return false;
      }
      return true;
    });
  }

  // ---------- rendering ----------

  // Roughly how wide a string renders at a given font size in this UI face.
  function textWidth(str, fontSize) { return str.length * fontSize * 0.58; }

  // Header sizing for a sector panel. Returns null when even the smallest
  // legible size would overflow — better no header than a clipped one.
  function headerFor(name, gw) {
    var avail = gw - 36; // horizontal padding + colour dot + gap
    var font = 13.5;
    if (textWidth(name, font) > avail) {
      font = avail / (name.length * 0.58);
    }
    if (font < 9.5 || avail < 30) return null;
    font = Math.min(13.5, font);
    return { font: font, showTotal: avail - textWidth(name, font) > 64 };
  }

  function tileMarkup(c, w, h) {
    // Below this, a ticker can only render as an ellipsis stub ("M…"), which
    // is pure noise. Leave the tile as a plain colour block instead — its area
    // and sector still carry meaning, and the tooltip and link still work.
    if (w < 40 || h < 21 || textWidth(c.ticker, 9) > w - 10) return '';

    var parts = [];
    var ticker = clamp(9, 44, Math.min(w / 8, h / 6));
    var capSize = ticker * (h >= 150 ? 0.85 : 0.72);

    parts.push('<div class="t-ticker" style="font-size:' + ticker.toFixed(1) + 'px">' + c.ticker + '</div>');

    if (h >= 40 && w >= 52) {
      parts.push('<div class="t-cap" style="font-size:' + capSize.toFixed(1) + 'px">' + money(c.marketCap) + '</div>');
    }

    if (h >= 128 && w >= 185) {
      var s = clamp(10.5, 15.5, ticker * 0.34);
      var profit = money(c.netIncome);
      var cls = c.netIncome < 0 ? ' class="neg"' : '';
      parts.push(
        '<div class="t-stats" style="font-size:' + s.toFixed(1) + 'px">' +
          money(c.cash) + ' · ' + money(c.revenue) +
          ' · <span' + cls + '>' + profit + '</span>' +
        '</div>'
      );
    }

    if (h >= 158 && w >= 205 && c.blurb) {
      var b = clamp(10.5, 14.5, ticker * 0.32);
      parts.push('<div class="t-blurb" style="font-size:' + b.toFixed(1) + 'px">' + escapeHtml(c.blurb) + '</div>');
    }

    return parts.join('');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  // A sandboxed frame without allow-popups blocks target="_blank" outright,
  // so the click never goes anywhere. Open via script instead, and if that is
  // blocked too, navigate in place rather than doing nothing.
  // Note: window.open(url, name, 'noopener') returns null even on success, so
  // opener is cleared afterwards instead — otherwise we'd navigate twice.
  function openQuote(ev) {
    if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    var url = this.href;
    var w = null;
    try { w = window.open(url, '_blank'); } catch (e) { w = null; }
    if (w) {
      try { w.opener = null; } catch (e) { /* cross-origin, already safe */ }
    } else {
      window.location.href = url;
    }
  }

  function tooltip(c) {
    var age = ageOf(c);
    return c.ticker + ' — ' + c.name + '\n' +
      CATS[c.category].name + '\n' +
      'Market cap: ' + money(c.marketCap) + '\n' +
      'Cash: ' + money(c.cash) + '\n' +
      'Revenue (TTM): ' + money(c.revenue) + '\n' +
      'Profit (TTM): ' + money(c.netIncome) + '\n' +
      (c.founded ? 'Founded: ' + c.founded + (age !== null ? ' (' + age + " yrs)" : '') : '');
  }

  function render() {
    var rows = applyFilters();
    var map = els.map;
    map.innerHTML = '';

    // header totals
    var sum = rows.reduce(function (a, c) { return a + c.marketCap; }, 0);
    els.totals.innerHTML =
      '<strong>' + rows.length + '</strong> ' + (rows.length === 1 ? 'company' : 'companies') +
      ' · <strong>' + money(sum) + '</strong> combined';

    if (!rows.length) {
      var e = document.createElement('div');
      e.className = 'empty';
      e.innerHTML = '<div>No companies match these filters.</div><div style="font-size:13px">Widen the market-cap range or reset.</div>';
      map.appendChild(e);
      return;
    }

    // group by category
    var byCat = {};
    rows.forEach(function (c) { (byCat[c.category] = byCat[c.category] || []).push(c); });

    var groups = Object.keys(byCat).map(function (id) {
      var list = byCat[id].slice().sort(function (a, b) { return b.marketCap - a.marketCap; });
      return {
        cat: CATS[id],
        list: list,
        total: list.reduce(function (a, c) { return a + c.marketCap; }, 0)
      };
    }).sort(function (a, b) { return b.total - a.total; });

    var W = map.clientWidth;
    var H = map.clientHeight;
    if (W <= 0 || H <= 0) return;

    var gRects = squarify(groups.map(function (g) { return g.total; }), { x: 0, y: 0, w: W, h: H });

    groups.forEach(function (g, i) {
      var r = gRects[i];
      var gx = r.x + GAP / 2, gy = r.y + GAP / 2;
      var gw = Math.max(0, r.w - GAP), gh = Math.max(0, r.h - GAP);
      if (gw < 8 || gh < 8) return;

      var panel = document.createElement('div');
      panel.className = 'group';
      panel.style.left = gx + 'px';
      panel.style.top = gy + 'px';
      panel.style.width = gw + 'px';
      panel.style.height = gh + 'px';

      var headSpec = gh >= 74 ? headerFor(g.cat.name, gw) : null;
      var headH = headSpec ? HEAD : 0;
      if (headSpec) {
        var head = document.createElement('div');
        head.className = 'group-head';
        head.style.fontSize = headSpec.font.toFixed(1) + 'px';
        head.innerHTML =
          '<span class="dot" style="background:' + g.cat.accent + '"></span>' +
          escapeHtml(g.cat.name) +
          (headSpec.showTotal ? ' <span class="group-total">' + money(g.total) + '</span>' : '');
        panel.appendChild(head);
      }

      var inner = {
        x: PAD,
        y: headH || PAD,
        w: Math.max(0, gw - PAD * 2),
        h: Math.max(0, gh - (headH || PAD) - PAD)
      };

      var tRects = squarify(g.list.map(function (c) { return c.marketCap; }), inner);

      g.list.forEach(function (c, k) {
        var t = tRects[k];
        var tw = Math.max(0, t.w - TGAP), th = Math.max(0, t.h - TGAP);
        // Only skip what would be sub-pixel. Anything larger still renders as
        // a colour block, so a cramped sector panel is never left blank.
        if (tw < 4 || th < 4) return;

        var el = document.createElement('a');
        el.className = 'tile';
        el.href = 'https://finance.yahoo.com/quote/' + encodeURIComponent(c.ticker) + '/';
        el.target = '_blank';
        el.rel = 'noopener noreferrer';
        el.setAttribute('aria-label', c.ticker + ' — ' + c.name + ', open on Yahoo Finance');
        el.addEventListener('click', openQuote);
        el.style.left = (t.x + TGAP / 2) + 'px';
        el.style.top = (t.y + TGAP / 2) + 'px';
        el.style.width = tw + 'px';
        el.style.height = th + 'px';
        el.style.background = g.cat.tile;
        el.style.borderColor = g.cat.edge;
        el.title = tooltip(c);
        el.innerHTML = tileMarkup(c, tw, th);
        panel.appendChild(el);
      });

      map.appendChild(panel);
    });
  }

  // ---------- controls ----------

  var PRESETS = {
    all:        [null, null],
    'lte2':     [null, 2],
    'lte10':    [null, 10],
    'lte20':    [null, 20],
    'lte50':    [null, 50],
    'lte100':   [null, 100],
    'gte20':    [20, null],
    'gte100':   [100, null],
    'gte500':   [500, null],
    'gte1000':  [1000, null],
    '1to20':    [1, 20],
    '20to100':  [20, 100]
  };

  function setPreset(key) {
    var p = PRESETS[key];
    if (!p) return;
    els.capMin.value = p[0] === null ? '' : p[0];
    els.capMax.value = p[1] === null ? '' : p[1];
  }

  function syncPresetFromInputs() {
    var minV = els.capMin.value === '' ? null : parseFloat(els.capMin.value);
    var maxV = els.capMax.value === '' ? null : parseFloat(els.capMax.value);
    var match = 'custom';
    Object.keys(PRESETS).forEach(function (k) {
      var p = PRESETS[k];
      if (p[0] === minV && p[1] === maxV) match = k;
    });
    els.capPreset.value = match;
  }

  function reset() {
    els.sector.value = 'all';
    els.capPreset.value = 'lte20';
    setPreset('lte20');
    els.age.value = 'all';
    render();
  }

  // ---------- boot ----------

  function buildControls() {
    DATA.categories.forEach(function (c) {
      CATS[c.id] = c;
      var o = document.createElement('option');
      o.value = c.id;
      o.textContent = c.name;
      els.sector.appendChild(o);
    });

    var legend = document.getElementById('legend');
    DATA.categories.forEach(function (c) {
      var item = document.createElement('span');
      item.className = 'legend-item';
      item.innerHTML = '<span class="dot" style="background:' + c.accent + '"></span>' + escapeHtml(c.name);
      legend.appendChild(item);
    });

    document.getElementById('asOf').textContent = DATA.asOf;

    els.sector.addEventListener('change', render);
    els.age.addEventListener('change', render);
    els.capPreset.addEventListener('change', function () {
      if (this.value !== 'custom') setPreset(this.value);
      render();
    });
    [els.capMin, els.capMax].forEach(function (inp) {
      inp.addEventListener('input', function () { syncPresetFromInputs(); render(); });
    });
    els.reset.addEventListener('click', reset);

    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(render, 120);
    });
  }

  function init() {
    els = {
      map: document.getElementById('map'),
      totals: document.getElementById('totals'),
      sector: document.getElementById('sector'),
      capPreset: document.getElementById('capPreset'),
      capMin: document.getElementById('capMin'),
      capMax: document.getElementById('capMax'),
      age: document.getElementById('age'),
      reset: document.getElementById('reset')
    };

    fetch('data/companies.json', { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (json) {
        DATA = json;
        buildControls();
        els.capPreset.value = 'lte20';
        setPreset('lte20');
        render();
      })
      .catch(function (err) {
        els.map.innerHTML =
          '<div class="empty"><div>Could not load <code>data/companies.json</code> (' +
          escapeHtml(err.message) + ').</div>' +
          '<div style="font-size:13px">Serve the folder over HTTP, e.g. <code>python3 -m http.server</code>.</div></div>';
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
