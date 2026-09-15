/* 中国宏观页（/macro/cn）逻辑 —— 与 /macro 同构（research terminal 风格，复用 .mac-* 类）。
 *
 * 数据源（全部只读，零落盘）：
 *   /api/econ/cn?group=  → { as_of, series[], groups, inflation_axis, growth_axis, quadrant, basis }
 *   /api/cn/quotes       → { cny, bond10y, credit_spread, as_of }
 *   /api/history         → { dates, series[].{key, values, raw} }（上证 / 深证 / 创业板）
 *
 * 职责边界（与 macro.js 同纪律，勿越界）：
 *   四象限 / 通胀轴 / 增长轴 **只在服务端算**（src/cn_econ_fetcher.py），本文件只消费。
 *   ⚠️ 增长轴是 **PMI 与 50 比较的水平口径**，不是同比方向 —— 前端标注必须照抄服务端 basis。
 *
 * 分组加载（R1 降级路径，2026-09-14 实测）：全量并发 10.3s（瓶颈 bond_china_yield 8s）
 *   → **分两波**：先 price+growth（≈3.6s）出四象限，再 money/rate/labor/estate 逐组填充。
 *   ⚠️ 6 个组**同时**发没有收益：13 个上游请求照样同时在飞，墙钟不变（已实测）。
 *
 * 本文件刻意复制的三段 shell 行为（主题 / 移动端抽屉 / 市场状态）：与 macro.js 同口径。
 *   主题初始化**必须与 macro_cn.html 的 head 内联脚本同源**（pitfall「主题初始化分叉」）。
 */
(function () {
  "use strict";

  // 时间范围（交易日数；1Y≈252）
  var RANGES = [
    { id: "1m", label: "1M", days: 22 },
    { id: "3m", label: "3M", days: 66 },
    { id: "6m", label: "6M", days: 126 },
    { id: "1y", label: "1Y", days: 252 }
  ];
  // 品种胶囊：单变量显示真实价；「全部对比」做起点归一化（量纲不同，不可共用价格轴）
  var PICKS = [
    { key: "sh", label: "上证", unit: "" },
    { key: "sz", label: "深证", unit: "" },
    { key: "cyb", label: "创业板", unit: "" },
    { key: "cny", label: "人民币", unit: "" },
    { key: "bond10y", label: "10Y 国债", unit: "%" },
    { key: "__all__", label: "全部对比", unit: "" }
  ];
  var MULTI_KEYS = ["sh", "sz", "cyb", "cny", "bond10y"];
  var LABELS = { sh: "上证指数", sz: "深证成指", cyb: "创业板指", cny: "美元/人民币", bond10y: "10Y 国债" };
  var COLORS = {
    sh: ["--c-sh", "#d1495b"], sz: ["--c-sz", "#e07600"], cyb: ["--c-cyb", "#7b5ce0"],
    cny: ["--c-gspc", "#2b6de8"], bond10y: ["--c-move", "#A78BFA"]
  };

  // 序列展示顺序（服务端按注册表序返回，分组到达顺序不定 → 前端显式排序）
  var SERIES_ORDER = ["cpi", "ppi", "pmi", "gdp", "m2", "social_financing", "credit",
                      "unemployment", "retail", "house_price_bj", "house_price_sh",
                      "lpr", "shibor", "bond_10y"];
  // 核心变量（三级块）：其余序列归到「利率与流动性」/「地产」/「经济数据」
  var CORE_KEYS = ["cpi", "ppi", "pmi", "gdp", "m2", "credit", "retail", "unemployment"];
  var RATE_KEYS = ["lpr", "shibor", "bond_10y", "social_financing"];
  var ESTATE_KEYS = ["house_price_bj", "house_price_sh"];

  var FACTOR_ASSETS = {
    "通胀": { up: "周期 / 资源 受益 · 长久期债券承压", down: "债券 受益 · 上游资源承压" },
    "增长": { up: "股票 / 商品 受益", down: "债券 受益 · 顺周期承压" },
    "流动性": { up: "股票 / 信用 受益", down: "信用 / 成长 承压" },
    "信用": { up: "利率债 / 避险 受益（信用收紧）", down: "信用债 / 成长 受益（信用宽松）" }
  };

  var state = {
    groups: {},        // group -> payload（分组到达后累积）
    regime: null,      // 四象限（取任一 quadrant 非空的分组响应）
    quotes: null,
    history: null,
    range: "3m",
    pick: "sh",
    primary: "sh",
    chart: null
  };

  function el(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmt(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toFixed(digits == null ? 2 : digits);
  }

  function fmtSigned(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    var s = Number(v).toFixed(digits == null ? 2 : digits);
    return (v > 0 ? "+" : "") + s;
  }

  function cls(v) { return v == null || !isFinite(v) ? "" : (v > 0 ? "up" : (v < 0 ? "down" : "flat")); }

  function unitOf(key) {
    for (var i = 0; i < PICKS.length; i++) { if (PICKS[i].key === key) return PICKS[i].unit; }
    return "";
  }

  // 周期键 → 中文（**必须显示数据月份**，不得写「最新/实时」）
  function fmtPeriod(s) {
    if (!s) return "—";
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (m) return m[1] + "年" + parseInt(m[2], 10) + "月" + parseInt(m[3], 10) + "日";
    m = /^(\d{4})-(\d{2})$/.exec(s);
    if (m) return m[1] + "年" + parseInt(m[2], 10) + "月";
    m = /^(\d{4})Q(\d)$/.exec(s);
    if (m) return m[1] + "年 " + m[2] + " 季度累计";
    return String(s);
  }

  // ---- 主题 / 抽屉 / 市场状态（与 macro.js 同口径）----
  function getTheme() {
    try { return localStorage.getItem("mp-theme") || "light"; } catch (e) { return "light"; }
  }

  // ⚠️ 必须在 init 阶段就把主题落到 <html> 上（macro_cn.html 的 head 内联脚本是"首屏前"的同一件事，
  //    这里负责"运行时切换 + 进入页面后的再次确认"）；改这里必须同步 head 内联脚本。
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme || getTheme());
  }
  applyTheme();

  function updateMarketStatus() {
    var st = el("market-status"), tm = el("market-time"), dot = el("market-dot");
    if (!st || !tm) return;
    var open = false, hh = "—", mm = "—";
    try {
      var parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Shanghai", hourCycle: "h23",
        weekday: "short", hour: "2-digit", minute: "2-digit"
      }).formatToParts(new Date());
      var map = {};
      parts.forEach(function (p) { map[p.type] = p.value; });
      var wdIdx = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(map.weekday);
      open = wdIdx >= 1 && wdIdx <= 5;
      hh = map.hour; mm = map.minute;
    } catch (e) { /* 时区数据缺失：保留默认文案 */ }
    st.textContent = open ? "市场已开盘" : "休市";
    tm.textContent = "北京时间 " + hh + ":" + mm;
    if (dot) dot.classList.toggle("open", open);
  }

  function bindShell() {
    var themeBtn = el("sidebar-theme");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var next = getTheme() === "dark" ? "light" : "dark";
        try { localStorage.setItem("mp-theme", next); } catch (e) {}
        applyTheme(next);
        renderChart();                     // 图表线色 / 网格色随主题重取
      });
    }
    var menuBtn = el("menu-toggle");
    if (menuBtn) menuBtn.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
    var backdrop = document.createElement("div");
    backdrop.className = "nav-backdrop";
    document.body.appendChild(backdrop);
    backdrop.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
    var main = el("main");
    if (main) main.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
    var refreshBtn = el("refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", loadAll);
    updateMarketStatus();
    setInterval(updateMarketStatus, 60000);
  }

  // ---- 取数 ----
  function getJSON(url, timeoutMs) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutMs || 20000);
    return fetch(url, ctrl ? { signal: ctrl.signal } : undefined)
      .then(function (r) { return r.json(); })
      .then(function (d) { clearTimeout(timer); return d; })
      .catch(function (e) { clearTimeout(timer); throw e; });
  }

  // 取数失败的**分级日志**（2026-09-15）：`AbortError` = 客户端主动取消（超时 / 页面跳转重载），
  // 不是页面缺陷，且页面已用「数据暂缺」把失败可见化 → 走 `console.warn`；
  // 其余（网络/解析/HTTP）才是真错误，仍 `console.error`。
  // ⚠️ 验收脚本的 console-error 断言只统计 `type === "error"` —— 把取消也报成 error
  //    会让「重载一次再测」这类**有意重试**把页面误判成有缺陷。
  function logFetchError(tag, e) {
    var prefix = "[" + tag + "]";
    if (e && e.name === "AbortError") {
      console.warn(prefix + " aborted（超时或页面跳转，页面已显示「数据暂缺」）", e);
    } else {
      console.error(prefix + " failed:", e);
    }
  }

  function loadGroup(g) {
    return getJSON("/api/econ/cn?group=" + g, 30000).then(function (d) {
      state.groups[g] = d || {};
      renderAll();
    }).catch(function (e) {
      logFetchError("cn-econ group " + g, e);
      state.groups[g] = {};
      renderAll();
    });
  }

  // R1：**分两波**（先四象限所需的 price+growth，再其余）—— 同时发 6 组没有收益
  function loadEcon() {
    Promise.all([loadGroup("price"), loadGroup("growth")]).then(function () {
      return Promise.all([loadGroup("money"), loadGroup("rate"), loadGroup("labor"), loadGroup("estate")]);
    });
  }

  function loadQuotes() {
    // 30s（与 econ 分组一致）：冷启动 + 并发时 `/api/cn/quotes` 含中债 8s 取数，20s 偏紧
    getJSON("/api/cn/quotes", 30000)
      .then(function (d) { state.quotes = d || {}; renderAll(); })
      .catch(function (e) { logFetchError("cn-quotes", e); state.quotes = {}; renderAll(); });
  }

  function loadHistory() {
    getJSON("/api/history?days=365&symbols=SH,SZ,CYB", 30000)
      .then(function (d) { state.history = d || {}; renderAll(); })
      .catch(function (e) { logFetchError("cn-history", e); state.history = {}; renderAll(); });
  }

  function loadAll() { loadEcon(); loadQuotes(); loadHistory(); }

  // ---- 归并 ----
  function allSeries() {
    var out = [], seen = {};
    Object.keys(state.groups).forEach(function (g) {
      (state.groups[g].series || []).forEach(function (s) {
        if (seen[s.key]) return;
        seen[s.key] = 1;
        out.push(s);
      });
    });
    out.sort(function (a, b) {
      var ia = SERIES_ORDER.indexOf(a.key), ib = SERIES_ORDER.indexOf(b.key);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    return out;
  }

  function byKey(key) {
    var list = allSeries();
    for (var i = 0; i < list.length; i++) { if (list[i].key === key) return list[i]; }
    return null;
  }

  // 数据截至：优先「月度口径」的 as_of（日频序列会把 as_of 顶到今天，掩盖发布滞后）
  function asOfMonth() {
    var months = [];
    Object.keys(state.groups).forEach(function (g) {
      var a = state.groups[g].as_of;
      if (a && /^\d{4}-\d{2}$/.test(a)) months.push(a);
    });
    return months.length ? months.sort().pop() : null;
  }

  function basis() {
    var out = null;
    Object.keys(state.groups).forEach(function (g) { if (state.groups[g].basis) out = state.groups[g].basis; });
    return out || {};
  }

  function failedKeys() {
    var out = [];
    Object.keys(state.groups).forEach(function (g) {
      (state.groups[g].failed || []).forEach(function (k) { if (out.indexOf(k) < 0) out.push(k); });
    });
    return out;
  }

  function regime() {
    var best = null;
    Object.keys(state.groups).forEach(function (g) {
      var d = state.groups[g];
      // 取**轴最全**的那份（累积 raw 让后到的组自然补上另一条轴）
      if (d.quadrant && (!best || (best.inflation_axis ? 0 : 1) < (d.inflation_axis ? 0 : 1))) best = d;
      if (d.growth_inputs && (!best || !best.quadrant)) best = d;
    });
    return best;
  }

  // ---- 模块 1：当前宏观环境 ----
  function renderRegime() {
    var d = regime();
    var lv = el("cn-level"), q = el("cn-quadrant"), box = el("cn-regime");
    var inp = (d && d.growth_inputs) || {};
    if (lv) {
      lv.textContent = d && d.quadrant_label ? d.quadrant_label : "数据暂缺";
      lv.className = "regime-level " + (d && d.quadrant ? d.quadrant : "none");
    }
    if (q) {
      q.textContent = d && d.quadrant
        ? ("通胀 " + (d.inflation_axis === "up" ? "上行" : "回落") + " · 增长 " +
           (d.growth_axis === "expanding" ? "扩张" : "收缩") +
           (inp.conflict ? "（GDP 交叉校验不一致）" : ""))
        : "";
    }
    if (box) box.setAttribute("data-quadrant", (d && d.quadrant) || "");

    var pmi = el("cn-pmi");
    if (pmi) pmi.textContent = inp.pmi_3m == null ? "—" : fmt(inp.pmi_3m, 1);

    var axes = el("cn-axis");
    if (axes) {
      var rows = [
        { name: "通胀轴", val: d && d.inflation_axis ? (d.inflation_axis === "up" ? "上行" : "回落") : "—",
          dir: (d && d.inflation_axis) === "up" ? "up" : ((d && d.inflation_axis) === "down" ? "down" : "flat"),
          note: "CPI 同比方向（PPI 二次确认）" },
        { name: "增长轴", val: d && d.growth_axis ? (d.growth_axis === "expanding" ? "扩张" : "收缩") : "—",
          dir: d && d.growth_axis === "expanding" ? "up" : (d && d.growth_axis === "contracting" ? "down" : "flat"),
          note: "PMI 与 50 比较（水平口径）" }
      ];
      axes.innerHTML = rows.map(function (r) {
        return '<li class="mac-factor-row"><span class="fr-name">' + escapeHtml(r.name) + "</span>" +
               '<span class="fr-dir ' + cls(r.dir === "up" ? 1 : (r.dir === "down" ? -1 : 0)) + '">' +
               escapeHtml(r.val) + "</span>" +
               '<span class="fr-note">' + escapeHtml(r.note) + "</span></li>";
      }).join("");
    }

    var b = basis();
    var bs = el("cn-basis");
    if (bs) {
      var parts = [];
      if (b.growth) parts.push("增长轴：" + b.growth);
      if (b.inflation) parts.push("通胀轴：" + b.inflation);
      if (b.asof_note) parts.push(b.asof_note);
      bs.textContent = parts.join(" · ");
    }
  }

  // ---- 模块 2：中国宏观市场（主图）----
  function pickRange() {
    for (var i = 0; i < RANGES.length; i++) { if (RANGES[i].id === state.range) return RANGES[i]; }
    return RANGES[1];
  }

  function renderPills() {
    var box = el("cn-pills");
    if (box) {
      box.innerHTML = PICKS.map(function (p) {
        return '<button type="button" class="mac-pill' + (p.key === state.pick ? " active" : "") +
               '" data-pick="' + p.key + '">' + escapeHtml(p.label) + "</button>";
      }).join("");
    }
    var rbox = el("cn-range");
    if (rbox) {
      rbox.innerHTML = RANGES.map(function (r) {
        return '<button type="button" class="mac-pill' + (r.id === state.range ? " active" : "") +
               '" data-range="' + r.id + '">' + r.label + "</button>";
      }).join("");
    }
  }

  function bindPills() {
    var box = el("cn-pills");
    if (box) {
      box.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-pick]");
        if (!b) return;
        state.pick = b.dataset.pick;
        if (state.pick !== "__all__") state.primary = state.pick;
        renderPills(); renderChart();
      });
    }
    var rbox = el("cn-range");
    if (rbox) {
      rbox.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-range]");
        if (!b) return;
        state.range = b.dataset.range;
        renderPills(); renderChart();
      });
    }
  }

  // 单品种 → {dates, values}（**真实价**；归一化只发生在「全部对比」）
  function sourceOf(key) {
    if (key === "cny" || key === "bond10y") {
      var q = state.quotes || {};
      var it = key === "cny" ? q.cny : q.bond10y;
      if (!it || !it.series || !it.series.length) return null;
      return {
        dates: it.series.map(function (p) { return p[0]; }),
        values: it.series.map(function (p) { return p[1]; })
      };
    }
    var h = state.history;
    if (!h || !h.series) return null;
    for (var i = 0; i < h.series.length; i++) {
      if (h.series[i].key === key) return { dates: h.dates || [], values: h.series[i].raw || [] };
    }
    return null;
  }

  function normalize(arr) {
    var base = null;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] != null && isFinite(arr[i])) { base = arr[i]; break; }
    }
    if (!base) return arr.map(function () { return null; });
    return arr.map(function (v) { return (v == null || !isFinite(v)) ? null : (v / base) * 100; });
  }

  function cnCrosshairFormatter(v) {
    if (v == null || !isFinite(v)) return "—";
    if (state.pick === "__all__") return fmt(v, 2);
    var u = unitOf(state.pick);
    return fmt(v, state.pick === "bond10y" ? 3 : 2) + (u ? u : "");
  }

  function renderChart() {
    var canvas = el("cn-chart");
    var fail = el("cn-chart-fail");
    if (!canvas) return;
    if (window.__chartFailed || !window.Chart) {
      if (fail) fail.classList.remove("hidden");
      return;
    }
    if (fail) fail.classList.add("hidden");

    var days = pickRange().days;
    var multi = state.pick === "__all__";
    var dates, datasets;

    if (multi) {
      // 多品种：日期轴取**并集**（A 股 / 汇率 / 中债日历不同），缺值留 null（spanGaps 连接）
      var maps = {}, all = {};
      MULTI_KEYS.forEach(function (k) {
        var src = sourceOf(k);
        if (!src) return;
        var m = {};
        for (var i = 0; i < src.dates.length; i++) { m[src.dates[i]] = src.values[i]; all[src.dates[i]] = 1; }
        maps[k] = m;
      });
      if (!Object.keys(all).length) {
        if (state.chart) { state.chart.destroy(); state.chart = null; }
        return;
      }
      dates = Object.keys(all).sort();
      dates = days > 0 ? dates.slice(-days) : dates;
      datasets = MULTI_KEYS.filter(function (k) { return maps[k]; }).map(function (k) {
        var vals = dates.map(function (d) { return maps[k][d] == null ? null : maps[k][d]; });
        var base = cssVar(COLORS[k][0], COLORS[k][1]);
        var isPrimary = k === state.primary;
        return {
          key: k, label: LABELS[k] || k, data: normalize(vals),
          borderColor: isPrimary ? base : withAlpha(base, 0.45),
          backgroundColor: "transparent",
          borderWidth: isPrimary ? 2.4 : 1.2,
          pointRadius: 0, pointHoverRadius: 3, tension: 0.15, spanGaps: true
        };
      });
    } else {
      var src = sourceOf(state.pick);
      if (!src) {
        if (state.chart) { state.chart.destroy(); state.chart = null; }
        return;
      }
      dates = days > 0 ? src.dates.slice(-days) : src.dates.slice();
      var vals1 = days > 0 ? src.values.slice(-days) : src.values.slice();
      var b1 = cssVar(COLORS[state.pick][0], COLORS[state.pick][1]);
      datasets = [{
        key: state.pick, label: LABELS[state.pick] || state.pick, data: vals1,
        borderColor: b1, backgroundColor: "transparent", borderWidth: 2.4,
        pointRadius: 0, pointHoverRadius: 3, tension: 0.15, spanGaps: true
      }];
    }
    if (!datasets.length) return;

    var tick = cssVar("--text-muted", "#8b949e");
    var grid = cssVar("--border", "rgba(128,128,128,.18)");
    if (state.chart) { state.chart.destroy(); state.chart = null; }
    state.chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: dates, datasets: datasets },
      // ⚠️ 插件用工厂产出**实例级**对象以注入本页读数口径
      //    （不能写 options.plugins.hoverCrosshair = { formatter } —— 会被当 scriptable 立即调用）
      plugins: window.makeHoverCrosshair
        ? [window.makeHoverCrosshair({ formatter: cnCrosshairFormatter })] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,       // ★ C2：容器高度由 CSS 给
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: multi, position: "top", align: "end",
            labels: { color: tick, boxWidth: 8, boxHeight: 8, usePointStyle: true, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var u = multi ? "" : unitOf(ctx.dataset.key);
                return ctx.dataset.label + " " + fmt(ctx.parsed.y, 3) + (u ? u : "");
              }
            }
          }
        },
        scales: {
          x: { ticks: { color: tick, maxTicksLimit: 8, font: { size: 11 }, autoSkip: true, maxRotation: 0 },
               grid: { display: false } },
          y: { position: "right", ticks: { color: tick, font: { size: 11 }, maxTicksLimit: 6 },
               grid: { color: grid } }
        }
      }
    });

    var foot = el("cn-chart-foot");
    if (foot) {
      foot.textContent = (multi ? "全部对比（起点 = 100，消除量纲差异）" : "真实价格") +
        " · " + dates.length + " 个交易日";
    }
  }

  // ---- 模块 3：核心宏观变量 + 宏观因子 ----
  // ⚠️ 同一格里有两个口径，**必须带标签**（2026-09-15 用户反馈「+21.20% 却配 ↓ 箭头，像 bug」）：
  //   颜色 + 正负号 = **同比本身**的符号（本期 vs 去年同月）→ 绿字 +21.20% 是对的；
  //   箭头 = **同比相对上期**的方向（增速回升/回落）。
  //   社融 `+21.20% ↓` 的完整含义 = "同比仍正增长，但增速比上月回落"，两者不矛盾 ——
  //   问题在于**没写口径**。解释由列说明（macro_cn.html 的 .mac-note）+ 单元格 `title` 共同承担；
  //   ⚠️ 不要把箭头改成"跟随数值符号"（那会变成纯冗余装饰，丢掉"增速回落"这层信息）。
  function yoyTitle(s) {
    if (s.yoy == null) {
      return "同比：数据不足（无去年同期基数）。10Y 国债源自中债接口，仅 6 个月窗口";
    }
    var d = s.direction === "up" ? "较上期回升"
          : (s.direction === "down" ? "较上期回落" : "较上期持平");
    return "同比 " + fmtSigned(s.yoy, 2) + "%（本期 vs 去年同月）· " + d;
  }

  // 利率类的「变化」口径（2026-09-15）：**与 6 个月前比，单位 bp**（1bp = 0.01 个百分点）。
  //   ⚠️ 单位必须写在格子里 —— 同一列里非利率序列仍是「同比 %」，**两种单位同列**；
  //     靠「数值自带单位」自描述，不能再造一次口径歧义（同 09-15 箭头那次）。
  //   ⚠️ 数值本身即变化量 → **不配箭头**（箭头只服务"同比 + 箭头=同比较上期"那个双口径格）。
  function chgCell(s) {
    if (s.chg_6m_bp != null) {
      var bp = s.chg_6m_bp;
      return {
        text: (bp > 0 ? "+" : "") + fmt(bp, 1) + "bp",
        cls: cls(bp),
        title: "与 6 个月前相比 " + (bp > 0 ? "+" : "") + fmt(bp, 1) + " bp" +
               "（1bp = 0.01 个百分点）· 现值 " + s.date
      };
    }
    var arrow = s.direction === "up" ? "↑" : (s.direction === "down" ? "↓" : "→");
    // yoy 为空时只显示「—」，**不要拼 "%"**（"—%" 看起来像格式化漏洞）
    return {
      text: s.yoy == null ? "—" : fmtSigned(s.yoy, 2) + "% " + arrow,
      cls: cls(s.yoy),
      title: yoyTitle(s)
    };
  }

  function varRow(s) {
    var c = chgCell(s);
    return '<div class="mac-var"><span class="v-label">' + escapeHtml(s.label) + "</span>" +
      '<span class="v-value">' + fmt(s.latest, s.unit === "亿元" ? 0 : 2) +
      '<span class="v-unit">' + escapeHtml(s.unit || "") + "</span></span>" +
      '<span class="v-chg ' + c.cls + '" title="' + escapeHtml(c.title) + '">' +
      c.text + "</span>" +
      '<span class="v-state">' + escapeHtml(s.date ? fmtPeriod(s.date) : "—") + "</span></div>";
  }

  function renderVars() {
    var box = el("cn-vars");
    if (!box) return;
    var rows = allSeries().filter(function (s) { return CORE_KEYS.indexOf(s.key) >= 0; });
    if (!rows.length) {
      box.innerHTML = '<p class="mac-empty">数据暂缺（/api/econ/cn 未就绪）</p>';
      return;
    }
    box.innerHTML = rows.map(varRow).join("");
  }

  function renderFactors() {
    var box = el("cn-factors");
    if (!box) return;
    var d = regime() || {};
    var inp = d.growth_inputs || {};
    var q = state.quotes || {};
    function dirOf(key) { var s = byKey(key); return s ? s.direction : null; }
    function sign(v) { return v === "up" ? 1 : (v === "down" ? -1 : 0); }

    var spreadDir = null, spreadNote = "信用利差（商金债AAA − 国债）";
    if (q.credit_spread && q.credit_spread.series && q.credit_spread.series.length >= 2) {
      var sp = q.credit_spread.series;
      var last = sp[sp.length - 1][1], prev = sp[sp.length - 2][1];
      spreadDir = last > prev ? "up" : (last < prev ? "down" : null);
      spreadNote = "利差 " + fmt(last, 1) + " bp（走阔 = 信用收紧）";
    } else if (q.credit_spread && q.credit_spread.value != null) {
      spreadNote = "利差 " + fmt(q.credit_spread.value, 1) + " bp";
    }

    var items = [
      { name: "通胀", dir: d.inflation_axis, note: "CPI / PPI 同比方向" },
      { name: "增长", dir: d.growth_axis === "expanding" ? "up" : (d.growth_axis === "contracting" ? "down" : null),
        note: inp.pmi_3m == null ? "PMI 3 个月均值 —" : ("PMI 3M " + fmt(inp.pmi_3m, 1) + " vs 50") },
      { name: "流动性", dir: dirOf("m2"), note: "M2 同比方向" },
      { name: "信用", dir: spreadDir, note: spreadNote }
    ];
    box.innerHTML = items.map(function (it) {
      var v = sign(it.dir);
      var assets = FACTOR_ASSETS[it.name] || {};
      return '<li class="mac-factor-row"><span class="fr-name">' + escapeHtml(it.name) + "</span>" +
        '<span class="fr-dir ' + cls(v) + '">' +
        (it.dir ? (it.dir === "up" ? "上行" : "回落") : "—") + "</span>" +
        '<span class="fr-note">' + escapeHtml(it.note || "") + "</span>" +
        '<span class="fr-assets">' + escapeHtml(v ? assets[it.dir] || "" : "数据暂缺") + "</span></li>";
    }).join("");
  }

  // ---- 模块 4：利率与流动性 + 地产 ----
  function renderRates() {
    var box = el("cn-rate-list");
    if (!box) return;
    var rows = allSeries().filter(function (s) { return RATE_KEYS.indexOf(s.key) >= 0; });
    // 信用利差是 /api/cn/quotes 的副产品，补一行（无数据则整行不出现，不显示假值）
    var q = state.quotes || {};
    box.innerHTML = rows.length || q.credit_spread
      ? rows.map(varRow).join("") + (q.credit_spread ? spreadRow(q.credit_spread) : "")
      : '<p class="mac-empty">数据暂缺</p>';
  }

  function spreadRow(it) {
    var s = (it.series || []);
    var dir = s.length >= 2 ? (s[s.length - 1][1] > s[s.length - 2][1] ? "up"
              : (s[s.length - 1][1] < s[s.length - 2][1] ? "down" : "flat")) : "flat";
    var word = dir === "up" ? "走阔" : (dir === "down" ? "收窄" : "持平");
    // ⚠️ 变化格**必须有 title**（验收 CN-4c 要求所有变化格都带口径；信用利差同为一行）
    return '<div class="mac-var"><span class="v-label">信用利差</span>' +
      '<span class="v-value">' + fmt(it.value, 1) + '<span class="v-unit">bp</span></span>' +
      '<span class="v-chg ' + dir + '" title="信用利差（商金债AAA − 国债）较上期' + word +
      ' · 单位 bp">' + word + "</span>" +
      '<span class="v-state">' + escapeHtml(it.date ? fmtPeriod(it.date) : "—") + "</span></div>";
  }

  function renderEstate() {
    var box = el("cn-estate");
    if (!box) return;
    var rows = allSeries().filter(function (s) { return ESTATE_KEYS.indexOf(s.key) >= 0; });
    if (!rows.length) {
      box.innerHTML = '<p class="mac-empty">数据暂缺</p>';
      return;
    }
    box.innerHTML = rows.map(function (s) {
      // s.label 形如「新建商品住宅价格·北京」→ 取城市名
      var city = (s.label || "").split("·").pop() || s.label;
      return '<div class="cn-city"><div class="cn-city-name">' + escapeHtml(city) + " · 新建商品住宅</div>" +
        '<div class="cn-city-val ' + cls(s.latest) + '">' + fmtSigned(s.latest, 1) + "%</div>" +
        '<div class="cn-city-foot">同比 · ' + escapeHtml(fmtPeriod(s.date)) + "</div></div>";
    }).join("");
  }

  // ---- 模块 5：经济数据明细 ----
  function renderEcon() {
    var box = el("cn-econ");
    var note = el("cn-econ-asof");
    var asOf = asOfMonth();
    if (note) note.textContent = asOf ? "数据月份：" + fmtPeriod(asOf) : "数据暂缺";
    if (!box) return;
    var series = allSeries();
    if (!series.length) {
      box.innerHTML = '<p class="mac-empty">数据暂缺（/api/econ/cn 不可用）</p>';
    } else {
      box.innerHTML = series.map(function (s) {
        // 与 varRow 完全同源：利率走 bp（自带单位），其余走「同比 + 箭头」（title 写明口径）
        var c = chgCell(s);
        var text = (s.chg_6m_bp != null) ? c.text : "同比 " + c.text;
        return '<div class="mac-econ-item"><div class="e-label">' + escapeHtml(s.label) + "</div>" +
          '<div class="e-value">' + fmt(s.latest, s.unit === "亿元" ? 0 : 2) + "</div>" +
          '<div class="e-yoy ' + c.cls + '" title="' + escapeHtml(c.title) + '">' +
          text + "</div>" +
          '<div class="e-date">' + escapeHtml(fmtPeriod(s.date)) + "</div></div>";
      }).join("");
    }
    var fb = el("cn-econ-basis");
    if (fb) {
      var b = basis();
      var f = failedKeys();
      var parts = [];
      if (b.credit_note) parts.push(b.credit_note);
      if (b.price_note) parts.push(b.price_note);
      if (f.length) parts.push("取数失败：" + f.join("、"));
      fb.textContent = parts.join(" · ");
    }
  }

  function renderAll() {
    renderRegime();
    renderPills();
    renderVars();
    renderFactors();
    renderRates();
    renderEstate();
    renderEcon();
    renderChart();
    var asOf = asOfMonth();
    var head = el("cn-asof");
    if (head) head.textContent = asOf ? fmtPeriod(asOf) : "—";
    var tb = el("topbar-date");
    if (tb) {
      var hd = (state.history || {}).dates || [];
      tb.textContent = hd.length ? hd[hd.length - 1] : (asOf || "—");
    }
  }

  // ---- init ----
  bindShell();
  bindPills();
  renderPills();
  renderAll();
  loadAll();
})();
