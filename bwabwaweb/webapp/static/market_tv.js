// webapp/static/market_tv.js — chart TradingView Lightweight Charts v4.
// Candlestick + overlay MA/EMA/BOLL + panel RSI/MACD terpisah.
// Data dari /market/item/{name}/ohlc. Zoom boleh, pan tidak.
(function () {
  var root = document.getElementById("chart-root");
  if (!root) return;

  var itemName = root.dataset.item || "";
  var tier = root.dataset.tier || "basic";
  var isVip = tier === "pro";
  if (!itemName) return;

  if (typeof LightweightCharts === "undefined") {
    var st0 = document.getElementById("chart-status");
    if (st0) { st0.textContent = "Chart library tidak termuat."; st0.style.display = "block"; }
    return;
  }

  var PREF_KEY = "rishuu.chart.prefs.v2";
  var DEFAULT_PREFS = {
    hours: 720,
    bin: "24",
    overlays: { ma7: true, ma30: true, ema13: true, boll: false },
    panels: { rsi: true, macd: false }
  };
  var prefs = loadPrefs();

  var statusEl = document.getElementById("chart-status");
  var priceDiv = document.getElementById("price-chart");
  var rsiDiv = document.getElementById("rsi-chart");
  var macdDiv = document.getElementById("macd-chart");
  var rsiPanel = document.getElementById("rsi-panel");
  var macdPanel = document.getElementById("macd-panel");

  var chartPrice = null, chartRsi = null, chartMacd = null;
  var sCandle = null, sMa7 = null, sMa30 = null, sEma13 = null, sBollUp = null, sBollLow = null;
  var sRsi = null, sMacdHist = null, sMacdLine = null, sMacdSignal = null;
  var currentBars = [];

  // ---- util ----
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback || "";
  }
  function setStatus(text) {
    if (!statusEl) return;
    if (text) { statusEl.textContent = text; statusEl.style.display = "block"; }
    else { statusEl.style.display = "none"; }
  }
  function loadPrefs() {
    try {
      var raw = localStorage.getItem(PREF_KEY);
      if (!raw) return JSON.parse(JSON.stringify(DEFAULT_PREFS));
      var p = JSON.parse(raw);
      return {
        hours: p.hours || DEFAULT_PREFS.hours,
        bin: p.bin || DEFAULT_PREFS.bin,
        overlays: Object.assign({}, DEFAULT_PREFS.overlays, p.overlays || {}),
        panels: Object.assign({}, DEFAULT_PREFS.panels, p.panels || {})
      };
    } catch (e) { return JSON.parse(JSON.stringify(DEFAULT_PREFS)); }
  }
  function savePrefs() {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch (e) {}
  }
  function hoursLabel(h) {
    if (h % 24 === 0 && h >= 24) return (h / 24) + " hari";
    return h + " jam";
  }
  function fmtNum(v) {
    if (v == null) return "-";
    return v.toFixed(3);
  }

  // ---- chart base options ----
  function baseChartOptions(container, bgColor) {
    return {
      layout: {
        background: { type: "solid", color: bgColor },
        textColor: cssVar("--clay-text-muted", "#8A857C"),
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(138,133,124,0.10)" },
        horzLines: { color: "rgba(138,133,124,0.10)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
        timeVisible: prefs.hours <= 48,
        secondsVisible: false,
        barSpacing: 6,
        minBarSpacing: 4,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      crosshair: { mode: 1 },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: true,
        horzTouchDrag: false,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: false,
        mouseWheel: true,
        pinch: true,
      },
      kineticScroll: {
        touch: false,
        mouse: false,
      },
      width: container.clientWidth,
      height: container.clientHeight,
    };
  }

  // ---- destroy ----
  function destroyCharts() {
    if (chartPrice) { chartPrice.remove(); chartPrice = null; }
    if (chartRsi) { chartRsi.remove(); chartRsi = null; }
    if (chartMacd) { chartMacd.remove(); chartMacd = null; }
    sCandle = sMa7 = sMa30 = sEma13 = sBollUp = sBollLow = null;
    sRsi = sMacdHist = sMacdLine = sMacdSignal = null;
  }

  // ---- fetch + render ----
  function fetchData() {
    var url;
    if (isVip) {
      url = "/market/item/" + encodeURIComponent(itemName) + "/ohlc-indicators?hours=" + prefs.hours;
      if (prefs.bin && prefs.bin !== "auto") url += "&bin=" + prefs.bin;
    } else {
      // BASIC: range + bin, tanpa indikator advanced
      url = "/market/item/" + encodeURIComponent(itemName) + "/ohlc?hours=" + prefs.hours;
      if (prefs.bin && prefs.bin !== "auto") url += "&bin=" + prefs.bin;
    }

    setStatus("Memuat…");
    fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        if (!data.bars || !data.bars.length) {
          setStatus("Tidak ada bar OHLC untuk rentang ini.");
          return;
        }
        updateBadge(data);
        setStatus("");
        render(data);
      })
      .catch(function (err) { setStatus("Gagal memuat data chart (" + err.message + ")."); });
  }

  function updateBadge(data) {
    var badge = document.getElementById("chart-badge");
    if (!badge) return;
    var binLabel = (data.bin_hours === 0) ? "raw" : data.bin_hours + " jam/bin";
    badge.textContent = binLabel + " · " + hoursLabel(data.range_hours);
  }

  function render(data) {
    var bars = data.bars || [];
    var ind = data.indicators || {};
    currentBars = bars;

    destroyCharts();

    var cardBg = "transparent";
    var panelBg = cssVar("--clay-panel-bg", "#0a0a08");
    var textColor = cssVar("--clay-text-muted", "#8A857C");
    var sage = cssVar("--clay-sage", "#7FA57B");
    var blue = cssVar("--clay-blue", "#9DB4D6");
    var sand = cssVar("--clay-sand", "#D9C49A");
    var terra = cssVar("--clay-terra", "#C08A78");

    // ---- PRICE CHART ----
    chartPrice = LightweightCharts.createChart(priceDiv, baseChartOptions(priceDiv, cardBg));
    var priceFmt = { type: "price", precision: 3, minMove: 0.001 };
    sCandle = chartPrice.addCandlestickSeries({
      upColor: "#26a69a", downColor: "#ef5350",
      borderUpColor: "#26a69a", borderDownColor: "#ef5350",
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
      priceFormat: priceFmt,
    });
    sCandle.setData(bars.map(function (b) {
      return { time: b.t, open: b.o, high: b.h, low: b.l, close: b.c };
    }));

    if (ind.ma7 && ind.ma7.length) {
      sMa7 = chartPrice.addLineSeries({ color: sage, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFmt });
      sMa7.setData(filterNull(ind.ma7));
      sMa7.applyOptions({ visible: !!prefs.overlays.ma7 });
    }
    if (ind.ma30 && ind.ma30.length) {
      sMa30 = chartPrice.addLineSeries({ color: blue, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFmt });
      sMa30.setData(filterNull(ind.ma30));
      sMa30.applyOptions({ visible: !!prefs.overlays.ma30 });
    }
    if (ind.ema13 && ind.ema13.length) {
      sEma13 = chartPrice.addLineSeries({ color: sand, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFmt });
      sEma13.setData(filterNull(ind.ema13));
      sEma13.applyOptions({ visible: !!prefs.overlays.ema13 });
    }
    if (ind.boll && ind.boll.length) {
      sBollUp = chartPrice.addLineSeries({ color: textColor, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFmt });
      sBollUp.setData(ind.boll.filter(function (p) { return p.upper != null; }).map(function (p) { return { time: p.t, value: p.upper }; }));
      sBollUp.applyOptions({ visible: !!prefs.overlays.boll });
      sBollLow = chartPrice.addLineSeries({ color: textColor, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFmt });
      sBollLow.setData(ind.boll.filter(function (p) { return p.lower != null; }).map(function (p) { return { time: p.t, value: p.lower }; }));
      sBollLow.applyOptions({ visible: !!prefs.overlays.boll });
    }

    chartPrice.timeScale().fitContent();

    // ---- RSI CHART ----
    if (prefs.panels.rsi && ind.rsi14 && ind.rsi14.length) {
      rsiPanel.style.display = "";
      chartRsi = LightweightCharts.createChart(rsiDiv, baseChartOptions(rsiDiv, panelBg));
      chartRsi.priceScale("right").applyOptions({ autoScale: false });
      sRsi = chartRsi.addLineSeries({ color: blue, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false });
      sRsi.setData(filterNull(ind.rsi14));
      sRsi.createPriceLine({ price: 70, color: terra, lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
      sRsi.createPriceLine({ price: 30, color: sage, lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
      chartRsi.timeScale().fitContent();
    } else {
      rsiPanel.style.display = "none";
    }

    // ---- MACD CHART ----
    if (prefs.panels.macd && ind.macd && ind.macd.length) {
      macdPanel.style.display = "";
      chartMacd = LightweightCharts.createChart(macdDiv, baseChartOptions(macdDiv, panelBg));
      sMacdHist = chartMacd.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      sMacdHist.setData(ind.macd.map(function (p) {
        if (p.hist == null) return null;
        return { time: p.t, value: p.hist, color: p.hist >= 0 ? "rgba(38,166,154,0.5)" : "rgba(239,83,80,0.5)" };
      }).filter(Boolean));
      sMacdLine = chartMacd.addLineSeries({ color: sand, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      sMacdLine.setData(filterNull2(ind.macd, "macd"));
      sMacdSignal = chartMacd.addLineSeries({ color: terra, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      sMacdSignal.setData(filterNull2(ind.macd, "signal"));
      chartMacd.timeScale().fitContent();
    } else {
      macdPanel.style.display = "none";
    }

    // ---- sync time scale ----
    syncTimeScales([chartPrice, chartRsi, chartMacd].filter(Boolean));

    syncChipStates();
  }

  function filterNull(arr) {
    return arr.filter(function (p) { return p.v != null; }).map(function (p) { return { time: p.t, value: p.v }; });
  }
  function filterNull2(arr, key) {
    return arr.filter(function (p) { return p[key] != null; }).map(function (p) { return { time: p.t, value: p[key] }; });
  }

  function syncTimeScales(charts) {
    var syncing = false;
    charts.forEach(function (src) {
      src.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
        if (!range || syncing) return;
        syncing = true;
        charts.forEach(function (dst) {
          if (dst === src) return;
          dst.timeScale().setVisibleLogicalRange(range);
        });
        syncing = false;
      });
    });
  }

  // ---- chip wiring ----
  function syncChipStates() {
    root.querySelectorAll("[data-series]").forEach(function (b) {
      b.classList.toggle("is-active", !!prefs.overlays[b.dataset.series]);
    });
    root.querySelectorAll("[data-range]").forEach(function (b) {
      b.classList.toggle("is-active", parseInt(b.dataset.range, 10) === prefs.hours);
    });
    root.querySelectorAll("[data-bin]").forEach(function (b) {
      b.classList.toggle("is-active", b.dataset.bin === prefs.bin);
    });
    root.querySelectorAll("[data-panel]").forEach(function (b) {
      b.classList.toggle("is-active", !!prefs.panels[b.dataset.panel]);
    });
  }

  root.addEventListener("click", function (ev) {
    var btn = ev.target.closest("button.chart-chip");
    if (!btn) return;

    if (btn.dataset.series) {
      var k = btn.dataset.series;
      prefs.overlays[k] = !prefs.overlays[k];
      var vis = prefs.overlays[k];
      if (k === "ma7" && sMa7) sMa7.applyOptions({ visible: vis });
      if (k === "ma30" && sMa30) sMa30.applyOptions({ visible: vis });
      if (k === "ema13" && sEma13) sEma13.applyOptions({ visible: vis });
      if (k === "boll") {
        if (sBollUp) sBollUp.applyOptions({ visible: vis });
        if (sBollLow) sBollLow.applyOptions({ visible: vis });
      }
      savePrefs(); syncChipStates();
      return;
    }
    if (btn.dataset.range) {
      prefs.hours = parseInt(btn.dataset.range, 10);
      if (prefs.bin !== "auto" && parseInt(prefs.bin, 10) > prefs.hours) prefs.bin = "auto";
      savePrefs(); fetchData();
      return;
    }
    if (btn.dataset.bin) {
      var b = btn.dataset.bin;
      if (b !== "auto" && parseInt(b, 10) > prefs.hours) return;
      prefs.bin = b;
      savePrefs(); fetchData();
      return;
    }
    if (btn.dataset.panel) {
      var pk = btn.dataset.panel;
      prefs.panels[pk] = !prefs.panels[pk];
      savePrefs(); fetchData();
      return;
    }
  });

  fetchData();
})();
