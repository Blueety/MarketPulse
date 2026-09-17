/* 宏观数据页（/macro）逻辑 —— research terminal 风格。
 *
 * 数据源（全部只读，零落盘）：
 *   /api/macro → { stocks, trend(5Y: dates + series[].{raw,values}), regime, correlation, history_regime }
 *   /api/econ  → { as_of, series[4], inflation_axis, growth_axis, quadrant, quadrant_label }
 *
 * 职责边界（plan §4.4，勿越界）：
 *   四象限 / 通胀轴 / 增长轴 **只在服务端算**（src/econ_fetcher.py），本文件只消费；
 *   风险偏好三态与四维度打分也由服务端（web/app.py）给出，前端不重算。
 *
 * 本文件内刻意复制的三段 shell 行为（主题 / 移动端抽屉 / 市场状态 + 顶栏数据日）：
 *   与 app.js 同口径。之所以复制而不抽公共文件 —— 首页 app.js 刚做完 shell 抽取（M-4），
 *   不在同一任务里再动它；若将来出现第三处复用，应抽 `shell.js`（已记入 journal）。
 */
(function () {
  "use strict";

  // 时间范围：交易日数（1M≈22 / 3M≈66 / 6M≈126 / 1Y≈252 / 5Y=全部）
  var RANGES = [
    { id: "1m", label: "1M", days: 22 },
    { id: "3m", label: "3M", days: 66 },
    { id: "6m", label: "6M", days: 126 },
    { id: "1y", label: "1Y", days: 252 },
    { id: "5y", label: "5Y", days: 0 }        // 0 = 全部（≈1258 点）
  ];
  // 品种胶囊：单变量显示真实价；「全部对比」做起点归一化（量纲不同，不可共用价格轴）
  var PICKS = [
    { key: "dx-y.nyb", label: "美元指数", unit: "" },
    { key: "^tnx", label: "10Y 美债", unit: "%" },
    { key: "cl=f", label: "原油", unit: "$" },
    { key: "gc=f", label: "黄金", unit: "$" },
    { key: "__all__", label: "全部对比", unit: "" }
  ];
  // 与首页「市场概览」同款品种配色（--c-* 变量，双主题自动跟随）
  var SERIES_VAR = {
    "dx-y.nyb": "--c-ixic", "^tnx": "--c-move", "cl=f": "--c-vxn", "gc=f": "--c-gld"
  };
  var SERIES_FALLBACK = {
    "dx-y.nyb": "#2FD6A8", "^tnx": "#A78BFA", "cl=f": "#E0913E", "gc=f": "#E5C07B"
  };
  // 宏观关系展示口径（2026-09-14 macro-page-refine）——**标注文案由这些常量生成 = 单一事实来源**：
  //   ⚠️ 后端 `compute_macro_correlation` **不带任何 |r| 阈值参数**（固定返回 6 对；r=None 只在样本不足时出现），
  //      所以"只列显著对"这类过滤**只能在前端做**；而过滤规则与标注文案必须同源 ——
  //      D2 的缺陷正是"标注写 |r| ≥ 0.5，行为却把 6 对全列出来"（实测 6 行全 < 0.5，最大 0.47）。
  var REL_MIN = 0.5;        // 显著阈值：|r| ≥ 此值才算「显著对」
  var REL_TOP = 3;          // 默认最多展示几条显著对（PRD 要点 6：只突出最重要的 2~3 个）
  var REL_FALLBACK = 2;     // 无显著对时兜底展示的最强条数（不留空卡，但绝不假装显著）
  var relExpanded = false;  // 「查看全部」展开态
  var SERIES_LABEL = {
    "dx-y.nyb": "美元指数", "^tnx": "10Y 美债", "cl=f": "原油", "gc=f": "黄金"
  };

  // 因子 → 影响资产（**前端静态映射，非模型输出**；方向由服务端已给的 impact 正负选边）
  //   ⚠️ 这是"把偏多/偏空翻译成典型资产"的固定话术，不是研报结论，也不是预测。
  //   ⚠️⚠️ **符号口径（2026-09-17 修）**：服务端对「美元」「利率」两维用
  //      `_band_score(..., inverse=True)` ⇒ **impact > 0 表示该变量「下行」**（web/app.py:685-695
  //      的 docstring 写明"数值上行 = 风险偏好下行"）。所以本表的 pos 必须按
  //      **变量下行**写、neg 按**变量上行**写；「商品」没有 inverse（impact>0 = 油价上行）。
  //      原表按"变量上行 = pos"填 ⇒ 美元/利率 两支整体反了：实测表现为
  //      「利率 ↓偏空（= 收益率上行）」那行却写「黄金 受益」，而同一屏黄金就是 −0.36%
  //      （2026-09-17 用户追问「沃什不是要加息吗」时暴露）。判据见 verify_ui 的 NA-11。
  var FACTOR_ASSETS = {
    "波动率": { pos: "股票 / 信用 受益", neg: "避险资产（黄金、美债）受益" },
    "美元": { pos: "黄金 / 原油 受益 · 美元计价资产承压", neg: "风险资产 受益 · 黄金/原油 承压" },
    "利率": { pos: "美元 承压 · 黄金 / 长久期 受益", neg: "美元 受益 · 黄金/长久期 承压" },
    "商品": { pos: "能源 / 材料 受益", neg: "能源 / 材料 承压" }
  };

  var state = { macro: null, econ: null, range: "1y", pick: "dx-y.nyb", primary: "dx-y.nyb", chart: null };

  // ---- N1/N2 四态 + 骨架屏（2026-09-16 macro-page-frontend-refactor）----
  // 四态：loading（模板里的静态 .skeleton）/ ok / empty（.mac-empty）/ failed（.mac-empty.is-failed + 重试条）
  // ⚠️ `.mac-empty` 类名与「数据暂缺」文案是**可测契约**（verify_ui MX-12b 等）→ 失败态只能**追加** is-failed，不得改名。
  // ⚠️ shimmer 只用于 loading：把"取不到数"做成永久动画 = 用动画掩盖故障（pitfalls 专条）。
  var RETRY_MAX = 3;
  var retryUsed = 0;
  var failMacro = false, failEcon = false;
  var blocks = {};                     // block -> 'loading' | 'ok' | 'failed'（window.__macroState 可观测）
  var SKEL_OF_SOURCE = {               // 取数源 → 结算时要撤掉的骨架块（模板里以 data-skel 标注）
    macro: ["level", "quadrant", "score", "rfactors", "asof", "chart", "vars", "factors", "rel", "history"],
    econ: ["econ"]
  };
  // 块 → 容器 id（失败态要把容器里的 .mac-empty 标成 is-failed，而不只是靠顶部失败条）
  var BLOCK_HOST = {
    level: "regime-level", quadrant: "regime-quadrant", score: "regime-score",
    rfactors: "regime-factors", asof: "macro-asof", chart: "macro-chart-wrap",
    vars: "macro-vars", factors: "macro-factors", rel: "macro-rel",
    history: "macro-history", econ: "macro-econ"
  };

  // 客户端超时可注入：验收用 `window.__macroTimeoutMs` 把它压到 2s，从而**真实走一遍** AbortController 分支
  // （R1 的核心护栏："上游挂了不能永远停在骨架屏"。生产不设置 → 15000ms）
  function fetchTimeoutMs() {
    return (typeof window.__macroTimeoutMs === "number" && window.__macroTimeoutMs > 0)
      ? window.__macroTimeoutMs : 15000;
  }

  function clearSkel(block) {
    var nodes = document.querySelectorAll('[data-skel="' + block + '"]');
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].parentNode) nodes[i].parentNode.removeChild(nodes[i]);
    }
  }

  function settleSource(source) {
    var list = SKEL_OF_SOURCE[source] || [];
    for (var i = 0; i < list.length; i++) { clearSkel(list[i]); }
  }

  function markSource(source, st) {
    var list = SKEL_OF_SOURCE[source] || [];
    for (var i = 0; i < list.length; i++) { blocks[list[i]] = st; }
  }

  // 失败态可见化：给该源各容器里的 `.mac-empty` **追加** is-failed（类名/文案都不换）
  // ⚠️ 只加类不改文案：`.mac-empty` 与「数据暂缺」是 verify_ui 的可测契约（MX-12b）
  // ⚠️ 必须在 **renderAll 之后**统一补挂 —— 渲染会重建容器 innerHTML；两个取数源各自结算，
  //    谁后渲染谁就把先标记的 is-failed 抹掉（实测：macro 标完、econ 的 renderAll 又清空 factors 容器）
  function markFailedEmpties(source) {
    (SKEL_OF_SOURCE[source] || []).forEach(function (b) {
      var host = el(BLOCK_HOST[b]);
      if (!host) return;
      var empties = host.querySelectorAll(".mac-empty");
      for (var i = 0; i < empties.length; i++) { empties[i].classList.add("is-failed"); }
    });
  }

  // 失败条：任一取数源失败才出现（重试按钮绑定见 bindRetry）。
  // ⚠️ 显示语义靠 CSS 的 `#mac-fail-bar:not(.hidden)` —— 不要给 #mac-fail-bar 写 display（id 特异性会盖掉 .hidden）
  function setFailBar() {
    var bar = el("mac-fail-bar"), msg = el("mac-fail-msg");
    var failed = [];
    if (failMacro) failed.push("/api/macro");
    if (failEcon) failed.push("/api/econ");
    if (msg) msg.textContent = failed.length ? "数据暂缺 · " + failed.join(" / ") + " 获取失败" : "数据获取失败";
    if (bar) bar.classList.toggle("hidden", failed.length === 0);
  }

  // 分级日志：AbortError（超时/取消）只 warn —— 它是**有意**的容错动作，报成 console.error 会撞
  // M-9b「/macro console error = 0」（pitfalls 既有处置）。非 AbortError 同样走 warn：
  // 上游 4xx/5xx 是可预期的降级条件，且页面已用失败态把它可见化。
  function logFetch(tag, e) {
    var name = (e && e.name) || "";
    var brief = (e && e.message) ? e.message : String(e);
    console.warn("[macro] " + tag + (name === "AbortError" ? " 超时/取消" : " 失败") + "：" + name + " " + brief);
  }

  // 验收可观测挂钩（verify_ui NA-* 用；只读，不影响渲染）
  window.__macroState = function () {
    var bar = el("mac-fail-bar");
    return {
      blocks: blocks, failMacro: failMacro, failEcon: failEcon,
      retryUsed: retryUsed, retryMax: RETRY_MAX, retryDisabled: !!(el("mac-retry") || {}).disabled,
      failBarShown: bar ? !bar.classList.contains("hidden") : null,
      skeletons: document.querySelectorAll(".skeleton").length,
      skelVisible: [].slice.call(document.querySelectorAll(".skeleton"))
        .filter(function (n) { return n.offsetParent !== null; }).length
    };
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

  function cls(v) { return v == null ? "" : (v > 0 ? "up" : (v < 0 ? "down" : "flat")); }

  // ⚠️ ^TNX 口径（2026-09-14 实测澄清）：Yahoo 这个接口返回的**已经是百分数**
  //    （实测 raw 末值 4.985 = 4.985%；5 年前 1.277 对应 2021-09 的真实 ~1.3%），**不要 ÷10**。
  //    原 plan 的「收益率 ×10 必须 ÷10」是基于业界常识而非实测 —— 照做会显示成 0.4985%。
  //    此处量级自适应只为防上游口径变更：|v| > 20（如 49.85）才 ÷10，且**必须告警，不静默校正**
  //    （项目纪律：静默降级会掩盖故障）。
  //    边界：若 10Y 真涨到 20%+（系统性断裂场景）会被误除 —— 那种场景下本页已无意义，接受。
  var TNX_SCALE_THRESHOLD = 20;
  var _tnxWarned = false;
  function toYieldDisplay(v) {
    if (v == null || !isFinite(v)) return null;
    if (Math.abs(v) > TNX_SCALE_THRESHOLD) {
      if (!_tnxWarned) {
        _tnxWarned = true;
        console.warn("[macro] ^TNX 原始值 " + v + " 超出预期量级（>" + TNX_SCALE_THRESHOLD +
                     "），按 ×10 口径换算后显示；请核对上游口径是否变更");
      }
      return v / 10;
    }
    return v;
  }

  // 品种值 → 显示值（只有 10Y 需要口径处理；其余原样）
  function displayValue(key, v) {
    return key === "^tnx" ? toYieldDisplay(v) : v;
  }

  function unitOf(key) {
    for (var i = 0; i < PICKS.length; i++) { if (PICKS[i].key === key) return PICKS[i].unit; }
    return "";
  }

  // ⚠️ 2026-09-14（macro-chart-crosshair）：本文件原先自带 `cssVar` / `withAlpha` 两份实现，
  //    现已随 crosshair 插件一起收敛到 `/static/chart-crosshair.js`（首页 + 宏观页共用）。
  //    此处继续裸调用同名函数 —— 它们是 window 上的全局函数，调用点零改动。
  //    （口径按 app.js 原实现统一：只处理 hex，其它形式原样返回；本页 `--c-*` token 全是 hex，行为不变。）

  // ---- 主题 / 抽屉 / 市场状态（与 app.js 同口径；见文件头注释）----
  function getTheme() {
    try { return localStorage.getItem("mp-theme") || "light"; } catch (e) { return "light"; }
  }

  // ⚠️ D1（2026-09-14 macro-page-refine）：**必须在 init 阶段就把主题落到 <html> 上**。
  // macro.html 的内联脚本只覆盖"显式 light"，而 HTML 属性默认写死 data-theme="light" →
  // 存储为 dark 时**没有任何代码把 dark 写回**，用户从首页（深色）点进本页会**突然变浅色**。
  // 首页无此问题是因为 app.js 在模块顶层调用了 applyTheme(getTheme())；本页此前只在"点击切换"时才调。
  // ⚠️ 改这里必须同步 macro.html 的 head 内联脚本（docs/pitfalls.md「主题初始化分叉」）。
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme || getTheme());
  }
  applyTheme();   // ★ 尽早执行（本文件在 </body> 前，先于 DOMContentLoaded 与首次渲染）

  // ⚠️ 2026-09-16（market-session-status）：两行两市场 + 逐市场时段判定。
  //    本段在 app.js / macro.js / macro_cn.js 各有一份**逐字副本** —— 改一处必须三处同改。
  //    点色语义：`open` = 「该市场此刻在交易」（不再是「今天是工作日」）。
  //    判定一律用**各市场本地时钟**，代码里不得出现 21:30 / 22:30 魔数（夏令时会静默错一小时）。
  var MARKET_SESSIONS = {
    cn: { tz: "Asia/Shanghai",    label: "A股", open: "09:30", close: "15:00", midday: ["11:30", "13:00"] },
    us: { tz: "America/New_York", label: "美股", open: "09:30", close: "16:00", midday: null }
  };
  var SESSION_LABELS = { open: "交易中", pre: "未开盘", post: "已收盘", midday: "午间休市", weekend: "休市" };

  function marketHM(hm) {
    var p = hm.split(":");
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }

  function marketLocalParts(tz, now) {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23", weekday: "short", hour: "2-digit", minute: "2-digit"
    }).formatToParts(now);
    var map = {};
    parts.forEach(function (p) { map[p.type] = p.value; });
    return { weekday: map.weekday, hh: map.hour, mm: map.minute };
  }

  // 'weekend' | 'midday' | 'open' | 'pre' | 'post'（边界含左不含右；周末按该市场 local weekday）
  function marketSessionOf(cfg, now) {
    var p = marketLocalParts(cfg.tz, now);
    if (p.weekday === "Sat" || p.weekday === "Sun") return "weekend";
    var t = marketHM(p.hh + ":" + p.mm);
    if (cfg.midday && t >= marketHM(cfg.midday[0]) && t < marketHM(cfg.midday[1])) return "midday";
    if (t >= marketHM(cfg.open) && t < marketHM(cfg.close)) return "open";
    return t < marketHM(cfg.open) ? "pre" : "post";
  }

  function marketStateOf(now) {
    var out = {};
    Object.keys(MARKET_SESSIONS).forEach(function (k) {
      var cfg = MARKET_SESSIONS[k];
      var s = marketSessionOf(cfg, now);
      out[k] = { session: s, open: s === "open", label: cfg.label + " " + SESSION_LABELS[s] };
    });
    return out;
  }

  function marketBeijingHM(now) {
    var p = marketLocalParts("Asia/Shanghai", now);
    return p.hh + ":" + p.mm;
  }

  // 验收同源钩子（verify_ui MS-*）；传 ISO 字符串即注入假 now（DST / 边界回归依赖它）
  window.__marketSession = function (iso) {
    try {
      var now = iso ? new Date(iso) : new Date();
      var st = marketStateOf(now);
      return { cn: st.cn, us: st.us, time: "北京时间 " + marketBeijingHM(now) };
    } catch (e) { return null; }
  };

  function updateMarketStatus() {
    var stCn = el("market-status-cn"), stUs = el("market-status-us"), tm = el("market-time");
    var dotCn = el("market-dot-cn"), dotUs = el("market-dot-us");
    if (!stCn || !stUs || !tm) return;
    var st = null, hhmm = "—:—";
    try {
      var now = new Date();
      st = marketStateOf(now);
      hhmm = marketBeijingHM(now);
    } catch (e) { /* 时区数据缺失：保留占位文案 */ }
    if (!st) return;
    stCn.textContent = st.cn.label;
    stUs.textContent = st.us.label;
    tm.textContent = "北京时间 " + hhmm;
    if (dotCn) dotCn.classList.toggle("open", st.cn.open);
    if (dotUs) dotUs.classList.toggle("open", st.us.open);
  }

  function bindShell() {
    var themeBtn = el("sidebar-theme");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var next = getTheme() === "dark" ? "light" : "dark";
        try { localStorage.setItem("mp-theme", next); } catch (e) {}
        applyTheme(next);                   // 与 init 阶段走同一入口（避免两套写法再次分叉）
        renderChart();                      // 图表线色/网格色随主题重取
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

  // ---- 胶囊 ----
  function renderPills() {
    var box = el("macro-pills");
    if (box) {
      box.innerHTML = PICKS.map(function (p) {
        return '<button type="button" class="mac-pill' + (p.key === state.pick ? " active" : "") +
               '" data-pick="' + p.key + '">' + escapeHtml(p.label) + "</button>";
      }).join("");
    }
    var rbox = el("macro-range");
    if (rbox) {
      rbox.innerHTML = RANGES.map(function (r) {
        return '<button type="button" class="mac-pill' + (r.id === state.range ? " active" : "") +
               '" data-range="' + r.id + '">' + r.label + "</button>";
      }).join("");
    }
  }

  function bindPills() {
    var box = el("macro-pills");
    if (box) {
      box.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-pick]");
        if (!b) return;
        state.pick = b.dataset.pick;
        // 「全部对比」时把**最近选过的品种**当作焦点序列（加粗强调，D3 的主次来源）
        if (state.pick !== "__all__") state.primary = state.pick;
        renderPills(); renderChart();
      });
    }
    var rbox = el("macro-range");
    if (rbox) {
      rbox.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-range]");
        if (!b) return;
        state.range = b.dataset.range;
        renderPills(); renderChart();
      });
    }
  }

  // 「查看全部 N 组」折叠开关（宏观关系）
  function bindRelMore() {
    var more = el("macro-rel-more");
    if (!more) return;
    more.addEventListener("click", function () {
      relExpanded = !relExpanded;
      renderRelation();
    });
  }

  // ---- 主图 ----
  function pickRange() {
    for (var i = 0; i < RANGES.length; i++) { if (RANGES[i].id === state.range) return RANGES[i]; }
    return RANGES[3];
  }

  function sliceTrend(trend, n) {
    var dates = trend.dates || [];
    var out = { dates: n > 0 ? dates.slice(-n) : dates.slice(), series: {} };
    (trend.series || []).forEach(function (s) {
      var raw = s.raw || [];
      out.series[s.key] = n > 0 ? raw.slice(-n) : raw.slice();
    });
    return out;
  }

  // 多变量对比：起点归一化 100（`v / 首个非空 * 100`）—— 数据变换，不用坐标轴 min 实现
  function normalize(arr) {
    var base = null;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] != null && isFinite(arr[i])) { base = arr[i]; break; }
    }
    if (!base) return arr.map(function () { return null; });
    return arr.map(function (v) { return (v == null || !isFinite(v)) ? null : (v / base) * 100; });
  }

  // ---- 悬停横向参考线的读数口径（2026-09-14 macro-chart-crosshair）----
  // ⚠️ 陷阱 1：**不能复用首页的 fmtAxisPct** —— 它输出"相对 100 的偏离百分比"（(v-100)+'%'），
  //    而本页单变量模式的 y 轴是**真实价格**：黄金 4386.60 会被读成 `+4286.6%`（页面不报错，数字荒谬）。
  // ⚠️ 陷阱 2：传入的 v **已经是显示值**（建数据集时走过 `normalize()` / `displayValue()`）→
  //    **绝对不能再调一次 `displayValue(k, v)`**，否则 ^tnx 会被 `toYieldDisplay` 除两次（4.987 → 0.4987）。
  //    正确做法：直接格式化 v，只补单位。
  function macroCrosshairFormatter(v) {
    if (v == null || !isFinite(v)) return "—";
    if (state.pick === "__all__") return fmt(v, 2);        // 全部对比：起点 = 100 的指数，纯数字
    var k = state.pick;                                     // 单变量：真实价 + 品种单位
    var u = unitOf(k);
    var digits = k === "^tnx" ? 3 : 2;                      // 收益率 3 位小数（与 tooltip 一致）
    var s = fmt(v, digits);
    return u === "$" ? u + s : s + u;                       // $ 在数值前，% 在后
  }

  function showChartFail(msg) {
    var canvas = el("macro-chart");
    var fail = el("macro-chart-fail");
    if (canvas) canvas.classList.add("hidden");
    if (fail) { fail.classList.remove("hidden"); fail.textContent = msg; }
  }

  function renderChart() {
    var canvas = el("macro-chart");
    if (!canvas || !window.Chart) { showChartFail("图表加载失败"); return; }
    var trend = state.macro && state.macro.trend;
    if (!trend || !(trend.dates || []).length) { showChartFail("数据暂缺"); return; }
    canvas.classList.remove("hidden");
    var fail = el("macro-chart-fail");
    if (fail) fail.classList.add("hidden");

    var win = sliceTrend(trend, pickRange().days);
    var multi = state.pick === "__all__";
    var keys = multi ? Object.keys(win.series) : [state.pick];
    var tick = cssVar("--c-axis-tick", "#86868b");
    var grid = cssVar("--c-grid-line", "rgba(0,0,0,.06)");

    // 焦点序列（D3 的主次来源）：单变量 = 当前品种；「全部对比」= 最近选过的品种（默认 美元指数）
    var primaryKey = multi ? (state.primary || keys[0]) : state.pick;
    var datasets = keys.map(function (k) {
      var raw = win.series[k] || [];
      var data = multi
        ? normalize(raw)
        : raw.map(function (v) { return displayValue(k, v); });
      var isPrimary = k === primaryKey;
      var base = cssVar(SERIES_VAR[k], SERIES_FALLBACK[k]);
      return {
        key: k,
        label: SERIES_LABEL[k] || k,
        data: data,
        // D3：**焦点序列最重、其余降存在感**（改前四条线一律 1.6 且全不透明 → 无主次、视觉纠缠）
        borderColor: isPrimary ? base : withAlpha(base, 0.45),
        backgroundColor: "transparent",
        borderWidth: isPrimary ? 2.4 : 1.2,
        pointRadius: 0,
        // 同 app.js：悬停点只由 `chart-crosshair.js` 的吸附标记提供（避免多系列图出现多个点）
        pointHoverRadius: 0,
        tension: 0.15,
        spanGaps: true
      };
    });

    // D4：全部对比模式的 Y 轴**按数据 min/max ±8% 收紧**（改前由 Chart.js 自动取整成 50~200，
    //     而实测数据只落在 88~180 → 上下各空一大截，有效起伏被压扁在中间；实测 range 150 vs 数据 92）。
    // ⚠️ 单变量模式**不动**（真实价格轴已合规，plan D8）。
    var yScale = {
      position: "right",
      ticks: { color: tick, font: { size: 11 }, maxTicksLimit: 6 },
      grid: { color: grid }
    };
    if (multi) {
      var vals = [];
      datasets.forEach(function (d) {
        d.data.forEach(function (v) { if (v != null && isFinite(v)) vals.push(v); });
      });
      if (vals.length) {
        var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
        var pad = Math.max((hi - lo) * 0.08, 0.5);
        yScale.min = lo - pad;
        yScale.max = hi + pad;
      }
    }

    if (state.chart) { state.chart.destroy(); state.chart = null; }
    state.chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: win.dates, datasets: datasets },
      // 悬停水平参考线：插件实现与首页共用（chart-crosshair.js），用工厂产出**实例级**插件对象
      // 以注入本页读数口径（不 Chart.register，避免影响别的图表）。
      // ⚠️ 不能写成 `options.plugins.hoverCrosshair = { formatter }` —— Chart.js 会把插件选项里的
      //    函数值当 scriptable option **立即调用**（实测抛 Cannot convert object to primitive value）。
      plugins: [window.makeHoverCrosshair({ formatter: macroCrosshairFormatter })],
      options: {
        responsive: true,
        maintainAspectRatio: false,          // ★ C2：容器高度由 CSS 给，不能让 canvas 自撑
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: multi,
            position: "top",
            align: "end",
            labels: { color: tick, boxWidth: 8, boxHeight: 8, usePointStyle: true, font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var k = ctx.dataset.key;
                if (multi) return ctx.dataset.label + " " + fmt(ctx.parsed.y, 2);
                var u = unitOf(k);
                var digits = k === "^tnx" ? 3 : 2;
                return ctx.dataset.label + " " + fmt(ctx.parsed.y, digits) + (u ? u : "");
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: tick, maxTicksLimit: 8, font: { size: 11 }, autoSkip: true, maxRotation: 0 },
            grid: { display: false }
          },
          y: yScale
        }
      }
    });

    var foot = el("macro-chart-foot");
    if (foot) {
      var last = datasets[0] && datasets[0].data.length ? datasets[0].data.length : 0;
      // 明写"强调哪条线"——否则"某条线更粗"会被当成渲染瑕疵而非设计（D3）
      foot.textContent = (multi
          ? "全部对比（起点 = 100，消除量纲差异）· 强调 " + (SERIES_LABEL[primaryKey] || primaryKey)
          : "真实价格")
        + " · " + last + " 个交易日";
    }
  }

  // ---- 模块 1：当前宏观环境 ----
  var LEVEL_TEXT = {
    risk_on: "Risk-On 风险偏好上行",
    neutral: "Neutral 中性",
    risk_off: "Risk-Off 风险规避"
  };
  // N4：level → 语义色 class 的**唯一映射**（渲染与断言共用同一事实来源）
  var LEVEL_CLASS = { risk_on: "up", risk_off: "down", neutral: "flat" };

  function renderRegime() {
    var m = state.macro || {};
    var r = m.regime || {};
    var lv = el("regime-level");
    if (lv) {
      lv.textContent = LEVEL_TEXT[r.level] || "数据暂缺";
      lv.className = "regime-level " + (r.level || "none");
    }
    var q = el("regime-quadrant");
    var econ = state.econ || {};
    if (q) {
      q.textContent = econ.quadrant_label
        ? "四象限：" + econ.quadrant_label + "（通胀" + (econ.inflation_axis === "up" ? "↑" : "↓") +
          " · 增长" + (econ.growth_axis === "expanding" ? "↑" : "↓") + "）"
        : "四象限：数据暂缺（/api/econ 不可用）";
    }
    var sc = el("regime-score");
    if (sc) {
      sc.textContent = r.score100 == null ? "—" : fmt(r.score100, 1);
      // N4：颜色**必须由服务端 level 同源推导**（与 #regime-level 同一事实来源）。
      //     ⚠️ 严禁写成"score100 > 50 就染绿"：score100 = (normalized+1)/2*100 是 **0~100、中性 50**
      //        （web/app.py），不是 ±2 的分值区间 —— 按"正/负分"上色会让 50 也偏绿，
      //        且可能出现"文案 Risk-Off、数字染绿"这类**标注与行为不同源**的缺陷。
      sc.className = "score-num " + (LEVEL_CLASS[r.level] || "flat");
    }
    var basis = el("regime-basis");
    if (basis) basis.textContent = r.basis || "";

    var box = el("regime-factors");
    if (box) {
      var fs = r.factors || [];
      box.innerHTML = fs.length ? fs.map(function (f) {
        var unit = f.unit === "pp" ? "pp" : (f.unit || "");
        return '<li class="mac-factor"><span class="f-name">' + escapeHtml(f.name) + "</span>" +
          '<span class="f-val ' + cls(f.impact) + '">' + fmtSigned(f.value, 2) + unit + "</span>" +
          '<span class="f-imp ' + cls(f.impact) + '">' + fmtSigned(f.impact, 0) + "</span>" +
          '<span class="f-note">' + escapeHtml(f.note || "") + "</span></li>";
      }).join("") : '<li class="mac-empty">数据暂缺</li>';
    }
  }

  // ---- 模块 3：核心宏观变量（4 行紧凑表：名称 / 数值 / 日变化 / 状态词）----
  // ⚠️「状态词」是**日变化的分档口语化**（不是观点，也不是预测），分档阈值为工程取值；
  //    它不引入任何新数据 —— 只把已经显示的 change_pct 说成人话（D6：原 2×2 网格下半屏空转）。
  function varState(chg) {
    if (chg == null || !isFinite(chg)) return { text: "—", cls: "flat" };
    if (chg >= 1) return { text: "明显走强", cls: "up" };
    if (chg >= 0.2) return { text: "小幅走强", cls: "up" };
    if (chg > -0.2) return { text: "基本持平", cls: "flat" };
    if (chg > -1) return { text: "小幅走弱", cls: "down" };
    return { text: "明显走弱", cls: "down" };
  }

  function renderVars() {
    var box = el("macro-vars");
    if (!box) return;
    var stocks = (state.macro || {}).stocks || [];
    if (!stocks.length) { box.innerHTML = '<p class="mac-empty">数据暂缺</p>'; return; }
    box.innerHTML = stocks.map(function (s) {
      var key = s.symbol.toLowerCase();
      var v = displayValue(key, s.value);
      var digits = s.symbol === "^TNX" ? 3 : 2;
      var st = varState(s.change_pct);
      return '<div class="mac-var"><span class="v-label">' + escapeHtml(s.label || s.symbol) + "</span>" +
        '<span class="v-value">' + fmt(v, digits) + '<span class="v-unit">' + unitOf(key) + "</span></span>" +
        '<span class="v-chg ' + cls(s.change_pct) + '">' + fmtSigned(s.change_pct, 2) + "%</span>" +
        '<span class="v-state ' + st.cls + '">' + st.text + "</span></div>";
    }).join("");
  }

  // ---- 模块 4：宏观因子（服务端给的四维度，前端不重算）----
  // 「影响资产」= 把服务端已给的 impact 正负**翻译成典型资产**（前端静态映射，非模型输出）
  function factorAssets(name, impact) {
    var map = null;
    for (var k in FACTOR_ASSETS) {
      if (FACTOR_ASSETS.hasOwnProperty(k) && name && name.indexOf(k) >= 0) { map = FACTOR_ASSETS[k]; break; }
    }
    if (impact > 0) return map ? map.pos : "风险资产 受益";
    if (impact < 0) return map ? map.neg : "风险资产 承压";
    return "中性（不构成方向）";
  }

  // ---- N3（2026-09-16）：影响资产 → 方向 Badge + 资产图标 chip（复用既有 4 个 SVG，**零新增素材**）----
  // 素材映射：美元→dollar / 利率·美债→bond / 黄金→gold / 原油·能源→oil；
  //   「股票 / 信用 / 材料 / 长久期」**无对应素材 → 纯文字 chip**（不新增 SVG）。
  //   颜色复用本页主图同款 --c-* token ⇒ chip 与图表里那条线同色（同一资产同一视觉编码）。
  var ASSET_ICON = {
    "美元": { icon: "dollar", color: "--c-ixic" },
    "美债": { icon: "bond",   color: "--c-move" },
    "利率": { icon: "bond",   color: "--c-move" },
    "黄金": { icon: "gold",   color: "--c-gld" },
    "原油": { icon: "oil",    color: "--c-vxn" },
    "能源": { icon: "oil",    color: "--c-vxn" }
  };
  // 识别用词表（含无素材的资产 —— 它们也要出 chip，只是没有 icon）
  var ASSET_TOKENS = ["避险资产", "风险资产", "长久期", "美元", "美债", "黄金", "原油",
                      "能源", "股票", "信用", "材料"];

  function assetChipHtml(name) {
    var m = ASSET_ICON[name];
    var ico = m
      ? '<i class="ico" style="background:var(' + m.color + ')">' +
        '<img class="ico-flag-img" src="/static/icons/' + m.icon + '.svg" alt="" onerror="this.remove()"></i>'
      : "";
    return '<span class="fr-chip">' + ico + escapeHtml(name) + "</span>";
  }

  // 「影响资产」短语 → 组（chip + 它自己的方向 Badge）。
  // ⚠️ 2026-09-17 用户反馈「怎么又受益又承压的」—— 根因是**配对方式**：原先按"每句出一个 badge、
  //    再跟 N 个 chip"平铺，元素排成 `受益 黄金 承压 长久期` ⇒ 中间那个 chip 被两个 badge **夹心**，
  //    必被读成"黄金又受益又承压"。而真实语义是两个**不同资产**各有各的方向
  //    （利率偏空 → 黄金受益、长久期承压）。
  //    修法：**资产在前、方向在后**，且每个 chip 与它的 badge 同组 `.fr-grp`（配对不可拆散）。
  // ⚠️ 中性（impact=0）不是"影响资产"，没有可配对的对象 → **不出 badge**，直接显示原文
  //    （否则会出现「中性 中性 不构成方向」这种把同一个词写两遍的读法）。
  function assetChipsHtml(text) {
    var out = [];
    String(text || "").split("·").forEach(function (raw) {
      var s = raw.replace(/[（）()]/g, " ").trim();
      if (!s) return;
      var dir = s.indexOf("受益") >= 0 ? "pos" : (s.indexOf("承压") >= 0 ? "neg" : "flat");
      if (dir === "flat") {
        out.push('<span class="fr-grp">' + assetChipHtml(raw.replace(/[（）()]/g, "").trim()) + "</span>");
        return;
      }
      var badge = dir === "pos" ? "受益" : "承压";
      var names = ASSET_TOKENS.filter(function (t) { return s.indexOf(t) >= 0; });
      if (!names.length) names = [s.replace(/(受益|承压|资产|\s)+/g, "") || s];
      names.forEach(function (n) {
        out.push('<span class="fr-grp">' + assetChipHtml(n) +
                 '<span class="fr-badge fr-badge-' + dir + '">' + badge + "</span></span>");
      });
    });
    return out.join("");
  }

  function renderFactors() {
    var box = el("macro-factors");
    if (!box) return;
    var fs = ((state.macro || {}).regime || {}).factors || [];
    if (!fs.length) { box.innerHTML = '<li class="mac-empty">数据暂缺</li>'; return; }
    box.innerHTML = fs.map(function (f) {
      var dir = f.impact > 0 ? "↑ 偏多" : (f.impact < 0 ? "↓ 偏空" : "→ 中性");
      return '<li class="mac-factor-row"><span class="fr-name">' + escapeHtml(f.name) + "</span>" +
        '<span class="fr-dir ' + cls(f.impact) + '">' + dir + "</span>" +
        '<span class="fr-note">' + escapeHtml(f.note || "") + "</span>" +
        '<span class="fr-assets">' + assetChipsHtml(factorAssets(f.name, f.impact)) + "</span></li>";
    }).join("");
  }

  // ---- 模块 5：宏观关系（默认只列最强的 2~3 条 + 「查看全部」展开其余）----
  // ⚠️ 过滤规则与标注文案**同源**（都由 REL_MIN / REL_TOP / REL_FALLBACK 生成）：
  //    D2（2026-09-14）的缺陷正是"标注写 |r| ≥ 0.5，行为却把 6 对全列出来"（实测 6 行全 < 0.5，最大 0.47）。
  //    后端**没有** |r| 阈值参数（固定返回 6 对）→ 过滤只能在前端做，所以"标注"必须跟着前端规则走。
  function relRowHtml(c) {
    if (c.r == null) {   // r=None：**显示「样本不足」而不是错误的 0**（plan R6）
      return '<li class="mac-rel-row muted" data-sig="0"><span class="rel-pair">' +
        escapeHtml(c.pair) + '</span><span class="rel-r">样本不足</span>' +
        '<span class="rel-n">n=' + (c.n || 0) + "</span></li>";
    }
    var strong = Math.abs(c.r) >= REL_MIN;
    var sign = c.r > 0 ? "正相关" : "负相关";
    return '<li class="mac-rel-row' + (strong ? " strong" : "") + '" data-sig="' + (strong ? 1 : 0) + '">' +
      '<span class="rel-pair">' + escapeHtml(c.pair) + '</span>' +
      '<span class="rel-r ' + (c.r > 0 ? "up" : "down") + '">' + fmtSigned(c.r, 2) + "</span>" +
      '<span class="rel-n">' + sign + " · n=" + (c.n || 0) + "</span></li>";
  }

  function renderRelation() {
    var box = el("macro-rel");
    if (!box) return;
    var note = el("macro-rel-note"), more = el("macro-rel-more");
    var rows = ((state.macro || {}).correlation || []).slice();
    if (!rows.length) {
      box.innerHTML = '<li class="mac-empty">数据暂缺</li>';
      if (note) note.textContent = "";
      if (more) more.hidden = true;
      return;
    }
    rows.sort(function (a, b) {
      var ra = a.r == null ? -2 : Math.abs(a.r), rb = b.r == null ? -2 : Math.abs(b.r);
      return rb - ra;
    });
    var valid = rows.filter(function (c) { return c.r != null; });
    var strong = valid.filter(function (c) { return Math.abs(c.r) >= REL_MIN; });
    // 有显著对 → 只列最强的 REL_TOP 条；一条都没达阈值 → 兜底列最强 REL_FALLBACK 条
    // 并在标注里**明说"无显著对"**（绝不把弱相关说成显著）
    var mode = strong.length ? "significant" : "fallback";
    var lead = strong.length ? strong.slice(0, REL_TOP) : valid.slice(0, REL_FALLBACK);
    var shown = relExpanded ? rows : lead;
    box.setAttribute("data-rel-mode", mode);
    box.innerHTML = shown.map(relRowHtml).join("");
    if (note) {
      var head = mode === "significant"
        ? "1 年滚动窗口 · |r| ≥ " + REL_MIN.toFixed(1) + " 的显著对，显示前 " + lead.length + " 组"
        : "1 年滚动窗口 · 当前无显著对（|r| 均 < " + REL_MIN.toFixed(1) + "），显示最强的 " + lead.length + " 组";
      // 展开后标注也要跟着变 —— 否则"标注说显示 2 组、屏幕上是 6 行"又是一次标注/行为不一致
      note.textContent = head + (relExpanded
        ? " · 已展开全部 " + rows.length + " 组"
        : " · 共 " + rows.length + " 组");
    }
    if (more) {
      var hidden = rows.length - shown.length;
      more.hidden = hidden <= 0 && !relExpanded;
      more.textContent = relExpanded ? "收起 ↑" : "查看全部 " + rows.length + " 组 →";
    }
  }

  // ---- 模块 6：历史宏观环境（**当前状态置顶** + 30 天三态分布 + 四象限）----
  function renderHistory() {
    var box = el("macro-history");
    if (!box) return;
    var m = state.macro || {};
    var h = m.history_regime || null;
    var note = el("mac-history-note");
    var econ = state.econ || {};
    if (note) {
      var quad = econ.quadrant_label ? " · 当前四象限：" + econ.quadrant_label : "";
      note.textContent = (h && h.days ? "近 " + h.days + " 个交易日" : "") + quad;
    }
    if (!h || !h.days) { box.innerHTML = '<p class="mac-empty">数据暂缺</p>'; return; }
    // ⚠️ 只说**数据支持得了**的话：接口给的是"近 N 个交易日里各状态各占几天"，**没有**逐日序列，
    //    因此**不写"已持续 X 天"**（那会是无中生有）—— 改为"近 N 个交易日中 M 天"（plan §3.3 要点 7 的原始
    //    措辞"已持续 X 天"因数据不支持而下调，见 journal 2026-09-14）。
    var cur = (m.regime || {}).level;
    var curDays = cur && h[cur] != null ? h[cur] : null;
    var now = (cur && curDays != null)
      ? '<div class="mac-hist-now">当前：<b class="' + cur + '">' + (LEVEL_TEXT[cur] || cur) + "</b>" +
        '<span class="now-sub">近 ' + h.days + " 个交易日中 " + curDays + " 天（" +
        Math.round((curDays / h.days) * 100) + "%）</span></div>"
      : "";
    var items = [
      { key: "risk_on", label: "Risk-On 风险偏好", v: h.risk_on },
      { key: "neutral", label: "Neutral 中性", v: h.neutral },
      { key: "risk_off", label: "Risk-Off 风险规避", v: h.risk_off }
    ];
    box.innerHTML = now + items.map(function (it) {
      var pct = Math.round((it.v / h.days) * 100);
      return '<div class="mac-hist-row"><span class="h-label">' + it.label + "</span>" +
        '<span class="h-bar"><i class="' + it.key + '" style="width:' + pct + '%"></i></span>' +
        '<span class="h-val">' + it.v + " 天 · " + pct + "%</span></div>";
    }).join("");
  }

  // ---- 模块 7：经济数据（**必须显示数据月份**，不得写「最新/实时」）----
  function renderEcon() {
    var box = el("macro-econ");
    var note = el("econ-asof");
    var econ = state.econ || {};
    var asOf = econ.as_of;                       // 形如 "2026-08"（**数据月份**，不是抓取时间）
    if (note) {
      note.textContent = asOf ? "数据月份：" + asOf.slice(0, 4) + "年" + parseInt(asOf.slice(5), 10) + "月" : "数据暂缺";
    }
    var basis = el("econ-basis");
    if (basis) {
      var b = econ.basis || {};
      basis.textContent = b.inflation ? "口径：通胀轴 " + b.inflation + "；增长轴 " + b.growth : "";
    }
    if (!box) return;
    var series = econ.series || [];
    if (!series.length || !asOf) {
      box.innerHTML = '<p class="mac-empty">数据暂缺（/api/econ 不可用）</p>';
      return;
    }
    box.innerHTML = series.map(function (s) {
      var digits = s.unit === "index" ? 2 : 2;
      var arrow = s.direction === "up" ? "↑" : (s.direction === "down" ? "↓" : "→");
      return '<div class="mac-econ-item"><div class="e-label">' + escapeHtml(s.label) + "</div>" +
        '<div class="e-value">' + fmt(s.latest, digits) + "</div>" +
        '<div class="e-yoy ' + cls(s.yoy) + '">同比 ' + fmtSigned(s.yoy, 2) + "% " + arrow + "</div>" +
        '<div class="e-date">' + escapeHtml(s.date || asOf) + "</div></div>";
    }).join("");
  }

  function renderAll() {
    renderRegime();
    renderVars();
    renderFactors();
    renderRelation();
    renderHistory();
    renderEcon();
    renderChart();
    // 失败态修饰：**渲染之后**再补挂（渲染会重建 innerHTML；两个源各自结算，否则互相抹掉）
    if (failMacro) markFailedEmpties("macro");
    if (failEcon) markFailedEmpties("econ");
    var el2 = el("macro-asof");
    if (el2) {
      var dates = ((state.macro || {}).trend || {}).dates || [];
      el2.textContent = dates.length ? dates[dates.length - 1] : "—";
      var tb = el("topbar-date");
      if (tb) tb.textContent = dates.length ? dates[dates.length - 1] : "—";
    }
  }

  // ---- 取数（两个端点并行；任一失败不影响另一个）----
  function getJSON(url, timeoutMs) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutMs || fetchTimeoutMs());
    return fetch(url, ctrl ? { signal: ctrl.signal } : undefined)
      .then(function (r) {
        // 非 2xx 直接判失败：此前无条件 r.json() → 500 的响应体（HTML）会抛 SyntaxError，
        // 报错信息完全指不到"上游返回了 500"这个事实（降级原因不可见）
        if (!r.ok) { var err = new Error("HTTP " + r.status); err.status = r.status; throw err; }
        return r.json();
      })
      .then(function (d) { clearTimeout(timer); return d; })
      .catch(function (e) { clearTimeout(timer); throw e; });
  }

  function loadAll() {
    setFailBar();                       // 重试时先收起旧失败条；新结果会再决定是否显示
    getJSON("/api/macro", fetchTimeoutMs())
      .then(function (d) {
        state.macro = d || {};
        failMacro = false;
        settleSource("macro");
        markSource("macro", "ok");
        renderAll();
        setFailBar();
      })
      .catch(function (e) {
        logFetch("/api/macro", e);
        state.macro = {};
        failMacro = true;
        markSource("macro", "failed");
        renderAll();                    // 走既有 .mac-empty 降级（失败态由 renderAll 统一补 is-failed）
        settleSource("macro");          // renderAll 覆盖了多数容器，图表骨架须显式撤掉（R1：不得停在骨架屏）
        setFailBar();
      });
    getJSON("/api/econ", fetchTimeoutMs())
      .then(function (d) {
        state.econ = d || {};
        failEcon = false;
        settleSource("econ");
        markSource("econ", "ok");
        renderAll();
        setFailBar();
      })
      .catch(function (e) {
        logFetch("/api/econ", e);
        state.econ = {};                        // 模块 6/7 显示「数据暂缺」，页面不崩
        failEcon = true;
        markSource("econ", "failed");
        renderAll();
        settleSource("econ");
        setFailBar();
      });
  }

  // 重试（按钮在模板里，同一 IIFE 内绑定 → 可直达私有 loadAll）
  function bindRetry() {
    var btn = el("mac-retry");
    if (!btn) return;
    btn.addEventListener("click", function () {
      if (retryUsed >= RETRY_MAX) return;
      retryUsed++;
      // 上限用满则禁用（避免无限点 → 无限打上游）
      if (retryUsed >= RETRY_MAX) {
        btn.disabled = true;
        btn.textContent = "重试已达上限";
      }
      loadAll();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindShell();
    renderPills();
    bindPills();
    bindRelMore();
    bindRetry();
    loadAll();
  });
})();
