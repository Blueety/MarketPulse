// MarketPulse 看板前端（Bento 仪表盘）
// 单一状态源 state 驱动全部视图；图表唯一实例 charts.main（重渲染前 destroy）。
// 纪律：切换类别 tab / 时间范围只复用 state.history，不发重复网络请求。

// === 主题切换 ===
function getTheme() {
  try {
    return localStorage.getItem('mp-theme') || 'light';
  } catch (e) {
    return 'light';
  }
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
}
applyTheme(getTheme());

// CSS 变量读取：图表色单一来源在 style.css 的 --c-* token（Light/Dark 两套）。
// Chart.js 不随 CSS 变量自动变色，切主题后重渲染（renderMainChart / repaintSparklines）生效。
function cssVar(name, fallback) {
  var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback || "";
}
function themeColors() {
  return {
    tooltipBg: cssVar('--c-tip-bg', 'rgba(255, 255, 255, 0.95)'),
    tooltipTitle: cssVar('--c-tip-title', '#1d1d1f'),
    tooltipBody: cssVar('--c-tip-body', '#1d1d1f'),
    tooltipBorder: cssVar('--c-tip-border', '#d2d2d7'),
    axisTick: cssVar('--c-axis-tick', '#86868b'),
    gridLine: cssVar('--c-grid-line', 'rgba(0, 0, 0, 0.06)')
  };
}
const SERIES_VAR = {
  gspc: "--c-gspc", ixic: "--c-ixic", sh: "--c-sh", sz: "--c-sz", cyb: "--c-cyb",
  vix: "--c-vix", vxn: "--c-vxn", move: "--c-move", gld: "--c-gld", btc: "--c-btc"
};
// CSS token 缺失时的保底色（= Dark 硬编码值）
const SERIES_FALLBACK = {
  gspc: "#66A8E0", ixic: "#2FD6A8", sh: "#FF6E5E", sz: "#F0A868", cyb: "#C792EA",
  vix: "#FFB454", vxn: "#E0913E", move: "#A78BFA", gld: "#E5C07B", btc: "#F7931A"
};
const ALL_KEYS = Object.keys(SERIES_VAR);
function colors() {
  var out = {};
  ALL_KEYS.forEach(function (k) { out[k] = cssVar(SERIES_VAR[k], SERIES_FALLBACK[k]); });
  return out;
}

// 色值加透明度：#RGB / #RRGGBB → rgba()；其余形式（rgb()/变量值）原样返回。
function withAlpha(color, a) {
  var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(color || '').trim());
  if (!m) return color;
  var h = m[1];
  if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
  var n = parseInt(h, 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}

const charts = {};  // 'main' -> Chart 实例（重渲染前 destroy）
if (window.Chart && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;

// 趋势主图类别（四图合一后的 4 个 tab，keys 为 history 小写键）
const GROUPS = [
  { id: "us", name: "美股大盘", keys: ["gspc", "ixic"] },
  { id: "cn", name: "A 股大盘", keys: ["sh", "sz", "cyb"] },
  { id: "vol", name: "波动率", keys: ["vix", "vxn", "move"] },
  { id: "alt", name: "另类资产", keys: ["gld", "btc"] }
];

// 静态占位模块（无数据源，仅保视觉；grep data-placeholder 定位全部待接点）
const PLACEHOLDERS = [
  { id: 'fund-flow', title: '资金流向（近5日）', note: '数据未接入' }
];

// 市场概览 6 小卡：indices = /api/latest，macro = /api/macro。
// 图标（需求方 2026-09-12 参照效果图定稿）：市场类 → 旗（美股 'us' / A股 'cn'，twemoji 简化素材）；
// 品种类 → 圆形图形素材（/static/icons/*.svg：dollar/bond/gold/oil），char 作 SVG 失败时的兜底字符。
const OVERVIEW_CARDS = [
  { id: 'GSPC', label: '美股 · 标普500', source: 'indices', flag: 'us' },
  { id: 'SH', label: 'A股 · 上证指数', source: 'indices', flag: 'cn' },
  { id: 'GLD', label: '黄金 ETF', source: 'indices', scale: 10, icon: 'gold', char: '金' },
  { id: 'DX-Y.NYB', label: '美元指数', source: 'macro', icon: 'dollar', char: '元' },
  { id: '^TNX', label: '10Y 美债', source: 'macro', suffix: '%', icon: 'bond', char: '债' },
  { id: 'CL=F', label: '原油', source: 'macro', icon: 'oil', char: '油' }
];

// === V1 品牌色行图标（16px 圆角方块 + 1 字符）===
// 底色单一事实来源：值为 style.css 的 --c-* 变量名，iconHtml 经内联 var() 引用 →
// 双主题自动跟随（渲染函数不在切主题时重跑，写死色值会漏切）。无板块/品种 brand 色，
// 用 ICON_PALETTE 按行序循环。字符：OVERVIEW_CARDS.char / ICON_CHARS 按 symbol 查 /
// 板块名首字符；查不到色 → 中性灰（--text-muted，双主题可见）。
const ICON_COLORS = {
  "GSPC": "--c-gspc", "SH": "--c-sh", "GLD": "--c-gld",
  "DX-Y.NYB": "--c-ixic", "^TNX": "--c-move", "CL=F": "--c-vxn",
  "515300.SS": "--c-gspc"
};
const ICON_CHARS = { "515300.SS": "红" };
const ICON_PALETTE = ["--c-gspc", "--c-ixic", "--c-sh", "--c-sz", "--c-cyb", "--c-move", "--c-vix", "--c-gld"];
const ICON_FALLBACK_VAR = "--text-muted";
function iconHtml(colorVar, char) {
  const bg = "var(" + (colorVar || ICON_FALLBACK_VAR) + ")";
  return '<i class="ico" style="background:' + bg + '">' + escapeHtml(char || "") + "</i>";
}
// 旗标变体：真旗 SVG 素材（web/static/flags/，取自 twemoji 后做图标级简化）铺在上层；
// 加载失败（离线）时 onerror 移除 <img>，露出底层 CSS 画旗（.ico-flag-us/cn）兜底。
// Windows 无旗 Emoji（🇺🇸 渲染成 "US" 字母），不能用 Emoji 字符。
function iconFlagHtml(which) {
  const k = which === 'cn' ? 'cn' : 'us';
  return '<i class="ico ico-flag ico-flag-' + k + '">' +
    '<img class="ico-flag-img" src="/static/flags/' + k + '.svg" alt="" onerror="this.remove()"></i>';
}
// 圆形图形素材变体（/static/icons/*.svg）：底层铺品牌色块，img 失败自动露出（onerror 移除）
function iconAssetHtml(colorVar, name) {
  const bg = "var(" + (colorVar || ICON_FALLBACK_VAR) + ")";
  return '<i class="ico" style="background:' + bg + '">' +
    '<img class="ico-flag-img" src="/static/icons/' + name + '.svg" alt="" onerror="this.remove()"></i>';
}

// 单一状态源：驱动所有视图刷新
const state = {
  days: 30,
  trendGroup: 'us',   // 趋势主图当前类别 tab
  history: null,      // /api/history 全量 payload
  latest: null,       // /api/latest payload
  watch: null,        // /api/watchlist payload
  macro: null         // /api/macro payload
};

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function fmtNum(v, digits) {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}
// 建议 7（千分位）：只给「价格」用 —— 不动 fmtNum，避免波及告警阈值/风险因子/tooltip。
function fmtNumSep(v, digits) {
  if (v == null) return "—";
  var n = Number(v);
  if (!isFinite(n)) return "—";
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtPct(v) {
  if (v == null || isNaN(v)) return "—";
  return (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%";
}
// Y 轴刻度与悬停气泡共用的涨跌幅格式化（单一事实来源，防气泡与刻度漂移）
function fmtAxisPct(value) {
  return (value >= 100 ? "+" : "") + (value - 100).toFixed(1) + "%";
}
function buildQuery() {
  return "/api/history?days=" + state.days;
}

// === 日期工具（C6：星期必须按数据日算；禁止 new Date("YYYY-MM-DD") 的本地时区偏移）===
function isWeekendDate(dateStr) {
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || ''));
  if (!m) return false;
  var wd = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay();
  return wd === 0 || wd === 6;
}
function weekdayLabel(dateStr) {
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || ''));
  if (!m) return '';
  var wd = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay();
  return '周' + ['日', '一', '二', '三', '四', '五', '六'][wd];
}

// === 数据索引（/api/latest 的 indices 是 list 非 dict，必须按 symbol 建映射）===
function sourceMap(kind) {
  var map = {};
  if (kind === 'macro') {
    (((state.macro || {}).stocks) || []).forEach(function (it) {
      if (it && it.symbol) map[it.symbol] = it;
    });
  } else {
    (((state.latest || {}).indices) || []).forEach(function (it) {
      if (it && it.symbol) map[it.symbol] = it;
    });
  }
  return map;
}

// === 市场概览 6 小卡 ===
// P-4 骨架屏（建议 8）：加载态占位形状与 6 小卡一致 → 数据到达时行高不突变（CLS）
var OVERVIEW_SKELETON = '<div class="skeleton sk-card"></div>'.repeat(6);
function renderOverview() {
  var box = document.getElementById('overview-body');
  if (!box) return;
  if (!state.latest) { box.innerHTML = OVERVIEW_SKELETON; return; }
  var idxMap = sourceMap('indices');
  var macMap = sourceMap('macro');
  box.innerHTML = OVERVIEW_CARDS.map(function (c) {
    const ico = c.flag ? iconFlagHtml(c.flag)
      : c.icon ? iconAssetHtml(ICON_COLORS[c.id], c.icon)
      : iconHtml(ICON_COLORS[c.id], c.char);
    var d = (c.source === 'indices' ? idxMap : macMap)[c.id];
    if (!d || d.value == null) {
      // macro 未接数据 → 「数据未接入」；indices 缺失 → 「数据暂缺」
      var note = c.source === 'macro' ? '数据未接入' : '数据暂缺';
      return '<div class="mini-card is-empty"><div class="mini-label">' + ico +
        escapeHtml(c.label) + '</div><div class="mini-val">' + note + '</div><div class="mini-sub">—</div></div>';
    }
    var val = c.scale ? d.value * c.scale : d.value;
    var chg = d.change_pct;
    var cls = chg == null ? '' : (chg >= 0 ? 'pos' : 'neg');
    var sub = chg == null ? (d.status || '—') : fmtPct(chg);
    return '<div class="mini-card"><div class="mini-label">' + ico +
      escapeHtml(c.label) + '</div>' +
      '<div class="mini-val">' + fmtNumSep(val, 2) + escapeHtml(c.suffix || '') + '</div>' +
      '<div class="mini-sub ' + cls + '">' + escapeHtml(sub) + '</div></div>';
  }).join('');
}

// === 市场情绪：A 股热点板块 Top 5 ===
function renderSector(latest) {
  const tbody = document.getElementById("sector-body");
  if (!tbody) return;
  tbody.innerHTML = "";
  const gainers = (latest && latest.sector_heat && latest.sector_heat.gainers) || [];
  if (!gainers.length) {
    tbody.innerHTML = '<tr><td colspan="5">数据暂缺</td></tr>';
    return;
  }
  gainers.slice(0, 5).forEach(function (g, i) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td class="col-ico">' + iconHtml(ICON_PALETTE[i % ICON_PALETTE.length], (g.name || "—").charAt(0)) + "</td>" +
      "<td>" + escapeHtml(g.name || "—") + "</td>" +
      '<td class="num chg"><span class="chg-pill ' + ((g.change || 0) >= 0 ? "pos" : "neg") + '">' +
        fmtPct(g.change) + "</span></td>" +
      '<td class="col-turnover num">' + escapeHtml(g.turnover || "—") + "</td>" +
      "<td>" + escapeHtml(g.top_stock || "—") + "</td>";
    tbody.appendChild(tr);
  });
}

// === 美股行业板块：横幅条（条宽 = |change| / max|change|）===
// 风险偏好仪表（三十二期）：/api/latest.risk_appetite 渲染；null/缺失 → 「数据暂缺」不隐藏（防布局跳变）
function renderRiskAppetite(latest) {
  const body = document.getElementById('risk-appetite-body');
  if (!body) return;
  const ra = latest && latest.risk_appetite;
  const labels = { high: '风险偏好高', low: '风险偏好低', neutral: '风险偏好中性' };
  const clsMap = { high: 'pos', low: 'neg', neutral: 'muted' };
  if (!ra || ra.level == null || !labels[ra.level]) {
    body.innerHTML = '<p class="ph-note">数据暂缺</p>';
    return;
  }
  const items = (ra.factors || []).map(function (f) {
    if (f.name === 'VIX 5日') {
      const c = f.impact >= 0 ? 'pos' : 'neg';
      return '<li>VIX 5日 <span class="' + c + '">' + fmtPct(f.change_pct) + '</span></li>';
    }
    return '<li>' + escapeHtml(f.name) + ' ' + fmtNum(f.value, 1) + ' · ' + escapeHtml(f.state) + '</li>';
  });
  body.innerHTML = '<div class="ra-label ' + clsMap[ra.level] + '">' + escapeHtml(labels[ra.level]) + '</div>' +
    '<ul class="ra-factors">' + items.join('') + '</ul>';
}

function renderUsSectors(latest) {
  const box = document.getElementById('us-sectors-body');
  if (!box) return;
  const gainers = (latest && latest.us_sector_heat && latest.us_sector_heat.gainers) || [];
  const rows = gainers.slice(0, 8);
  if (!rows.length) {
    box.innerHTML = '<p class="empty">数据暂缺</p>';
    return;
  }
  let maxAbs = 0.01;
  rows.forEach(function (r) { maxAbs = Math.max(maxAbs, Math.abs(r.change || 0)); });
  box.innerHTML = rows.map(function (r, i) {
    const chg = r.change || 0;
    const width = Math.min(100, Math.abs(chg) / maxAbs * 100).toFixed(1);
    const cls = chg >= 0 ? 'pos' : 'neg';
    return '<div class="bar-row">' +
      iconHtml(ICON_PALETTE[i % ICON_PALETTE.length], (r.name || '—').charAt(0)) +
      '<span class="bar-name">' + escapeHtml(r.name || '—') + '</span>' +
      '<span class="bar-track"><i class="' + cls + '" style="width:' + width + '%"></i></span>' +
      '<span class="bar-val"><span class="chg-pill ' + cls + '">' + fmtPct(r.change) + '</span></span></div>';
  }).join('');
}

// === 告警记录 ===
function renderAlerts(alerts) {
  const box = document.getElementById("alert-list");
  if (!box) return;
  if (!alerts || !alerts.length) {
    box.innerHTML = '<p class="empty">暂无告警记录</p>';
    return;
  }
  box.innerHTML = '';
  alerts.forEach(function (a) {
    const level = a.level || "";
    const cls = level === "ALERT" ? "alert" : (level === "WARN" ? "warn" : "");
    const card = document.createElement("div");
    card.className = "alert-card " + cls;
    card.innerHTML =
      '<div class="alert-head"><span class="badge ' + cls + '">' + escapeHtml(level) + "</span>" +
      "<span>" + escapeHtml(a.symbol || "") + " · " + escapeHtml(a.date || "") + "</span></div>" +
      '<div class="alert-meta">类型：' + escapeHtml(a.type || "—") + " ｜ 市场状态：" + escapeHtml(a.state || "—") + "</div>" +
      '<div class="alert-row">当前值：' + fmtNum(a.current, 2) + " ｜ 昨日收盘：" + fmtNum(a.last, 2) +
      " ｜ 变化率：" + fmtPct(a.change_pct) + "（阈值 ±" + fmtNum(a.threshold, 1) + "%）</div>" +
      '<div class="alert-sugg">建议：' + escapeHtml(a.suggestion || "—") + "</div>" +
      '<div class="alert-report">相关报告：' + escapeHtml(a.report || "—") + "</div>";
    box.appendChild(card);
  });
}

// === 静态占位模块 ===
// 市场关系（三十三期）：context 显著相关对 pills（按 |r| 降序，cap 5）；
// 正 r=红/同向联动、负 r=绿/对冲（与日报相关性表同色语义，勿按涨红跌绿直觉写反）。
function renderMarketRelation(latest) {
  const row = document.querySelector('#market-relation .pill-row');
  if (!row) return;
  const list = ((latest && latest.correlation) || [])
    .slice().sort(function (x, y) { return Math.abs(y.r) - Math.abs(x.r); }).slice(0, 5);
  if (!list.length) {
    row.innerHTML = '<p class="ph-note">暂无显著相关对（近30日 |r|≤0.5）</p>';
    return;
  }
  row.innerHTML = list.map(function (c) {
    const cls = c.r >= 0 ? 'pos' : 'neg';
    const r = (c.r >= 0 ? '+' : '') + Number(c.r).toFixed(2);
    return '<span class="pill ' + cls + '" title="近' + c.n + '个交易日">' +
      escapeHtml(c.pair) + ' ' + r + '</span>';
  }).join('');
}

// 取一句话（单行展示用）：优先 summary，为空则回退 title；按句末标点切首句（首句 <12 字补第二句）；
// 最终一律截到 42 字（含 …）。**回退路径也要截断**，否则长标题会突破 N-2 的 ≤43 上限。
// 上限与落盘层 MAX_SUMMARY_LEN（src/news_saver.py）保持一致：**不再二次截断**，
// 显示不完的行由 CSS `overflow-x: auto` 横向滚动（需求方 2026-09-12：字数显示太少 → 多显示 + 可横滚）。
var NEWS_MAX_LEN = 120;

function oneLine(summary, fallback) {
  var text = String(summary == null ? '' : summary).trim()
    || String(fallback == null ? '' : fallback).trim();
  if (!text) return '';
  var parts = text.split(/[。！？；!?;]/);
  var first = (parts[0] || '').trim();
  if (first.length < 12 && parts[1]) first = (first + '。' + parts[1]).trim();
  if (!first) first = text;
  return first.length > NEWS_MAX_LEN ? first.slice(0, NEWS_MAX_LEN - 1) + '…' : first;
}

// 最新资讯（三十四期）：每行一句话的宏观/世界要闻列表。
// 标题**不显示**，完整标题留在 <a title> 原生 tooltip 里（信息不丢失）；url 不来自可信源 → 必须转义。
// === 最新资讯自动循环滚动（scrollTop + requestAnimationFrame）===
// 为什么不用 CSS transform 动画：手动滚动（overflow-y:auto）与 transform 动画是两套机制，
// 叠加会跳变；且 reduce-motion 关掉动画后，**后面的条目将永远不可达**。用 scrollTop 驱动
// 可让「向上匀速 / 保留手动滚动 / reduce-motion 退化为纯手动」三者共存。
var NEWS_SCROLL_PX_PER_SEC = 16;   // 待目视定稿（约 2.1s 过一行；太快读不了、太慢没感觉）
var _newsRaf = 0, _newsLast = 0, _newsHalf = 0, _newsPaused = false, _newsBound = false;
// ★ 浮点累加位置。**绝不能写 `el.scrollTop += 增量`**：该容器 scrollTop 读回来是整数，
// 当每帧增量 <1px（如 16px/s ÷ 60fps = 0.27px）时小数部分每帧都被取整抹掉 → 位置永远停在 0
// （60fps 下看起来「完全不动」）；低帧率下则变成 1~2px 一格一跳（观感卡顿）。
// 实测证据见 tasks/2026-09-13-news-autoscroll/journal.md。
var _newsPos = 0;

function _newsEl() { return document.getElementById('news-body'); }

function stopNewsAutoScroll() {
  if (_newsRaf) { cancelAnimationFrame(_newsRaf); _newsRaf = 0; }
  _newsPaused = false;
  _newsHalf = 0;
  _newsPos = 0;
}

function _newsStep(now) {
  _newsRaf = requestAnimationFrame(_newsStep);
  var el = _newsEl();
  if (!el) { stopNewsAutoScroll(); return; }
  var dt = (now - _newsLast) / 1000;
  _newsLast = now;
  if (_newsPaused || dt <= 0) return;
  if (dt > 0.5) dt = 0.5;                        // 后台切回/长间隔 → 钳制，防一次跳很远
  _newsPos += NEWS_SCROLL_PX_PER_SEC * dt;       // 浮点累加（不受 getter 取整影响）
  // 无缝循环：越过「第一半高度」时**减去半程**（不是归零，避免累积误差）
  if (_newsHalf > 0 && _newsPos >= _newsHalf) _newsPos -= _newsHalf;
  el.scrollTop = _newsPos;                       // 只在赋值这一刻交给浏览器取整
}

function _newsSyncFromEl() {
  // 用户手动滚动/暂停恢复后，把累加器对齐到真实位置，避免「跳回去」
  var el = _newsEl();
  if (el) _newsPos = el.scrollTop;
}

function startNewsAutoScroll() {
  var el = _newsEl();
  if (!el) return;
  // 无障碍：reduce-motion 下不启动（style.css 另有 overflow-y:auto 兜底，保证内容仍可手动翻到）
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var items = el.querySelectorAll('.news-item');
  var n = Math.floor(items.length / 2);          // 双份内容 → 前一半 = 一个完整循环
  if (n <= 0) return;
  // 半程用「第一半元素的实测高度」而非 scrollHeight/2（末条 1px 边框会让双份不对称）
  var half = 0;
  for (var i = 0; i < n; i++) half += items[i].offsetHeight;
  if (half <= el.clientHeight) return;           // 内容不足一屏 → 不滚（否则原地抖动）
  _newsHalf = half;
  _newsPos = el.scrollTop;
  _newsLast = performance.now();
  if (_newsRaf) cancelAnimationFrame(_newsRaf);  // ★ 防 rAF 叠加（否则速度越来越快）
  _newsRaf = requestAnimationFrame(_newsStep);
}

function _bindNewsHover(el) {
  if (_newsBound) return;                        // 只绑一次（重渲染时 el 不变）
  _newsBound = true;
  el.addEventListener('mouseenter', function () { _newsPaused = true; });
  el.addEventListener('mouseleave', function () {
    _newsPaused = false;
    _newsLast = performance.now();               // ★ 必须重置：否则暂停期间的 dt 会瞬间大跳
    _newsSyncFromEl();                           // ★ 用户可能手动滚过 → 对齐再续滚
  });
  el.addEventListener('focusin', function () { _newsPaused = true; });    // 键盘 Tab 到链接也暂停
  el.addEventListener('focusout', function () {
    _newsPaused = false; _newsLast = performance.now(); _newsSyncFromEl();
  });
  document.addEventListener('visibilitychange', function () {             // 后台标签页不空转
    _newsPaused = document.hidden;
    if (!document.hidden) { _newsLast = performance.now(); _newsSyncFromEl(); }
  });
}

function renderNews(payload) {
  stopNewsAutoScroll();                          // ★ 先停旧循环，再重建 DOM
  const body = document.getElementById('news-body');
  if (!body) return;
  const dateEl = document.getElementById('news-date');
  if (dateEl) dateEl.textContent = payload && payload.date ? '· ' + payload.date : '';
  const items = payload && Array.isArray(payload.items) ? payload.items : [];
  if (!items.length) {
    body.innerHTML = '<p class="ph-note">暂无资讯</p>';
    return;
  }
  const html = items.map(function (n) {
    var text = oneLine(n.summary, n.title);
    return '<div class="news-item">' +
      '<a href="' + escapeHtml(n.url) + '" target="_blank" rel="noopener noreferrer"' +
      ' title="' + escapeHtml(n.title) + '">' + escapeHtml(text) + '</a>' +
      '</div>';
  }).join('');
  // 内容渲染两遍（克隆半与第一半**像素级相同** → 减半程即无缝）。克隆半 aria-hidden 防重复朗读。
  body.innerHTML = html + '<div class="news-clone" aria-hidden="true">' + html + '</div>';
  body.scrollTop = 0;
  _bindNewsHover(body);
  startNewsAutoScroll();                         // 内容不足一屏时内部自行不启动
}

function renderPlaceholders() {
  PLACEHOLDERS.forEach(function (p) {
    var cardEl = document.getElementById(p.id);
    if (cardEl) {
      var h = cardEl.querySelector('h2');
      if (h) h.textContent = p.title;
    }
    var body = document.getElementById(p.id + '-body');
    if (body) body.innerHTML = '<p class="ph-note">' + escapeHtml(p.note) + '</p>';
  });
}

// === 趋势主图（四图合一）===
function buildTradingAxis(dates, series) {
  const allDates = new Set();
  series.forEach(function (s) {
    (s.values || []).forEach(function (v, i) {
      if (v != null) allDates.add(dates[i]);
    });
  });
  const tradingDates = Array.from(allDates).filter(function (d) {
    return !isWeekendDate(d);
  }).sort();
  const dateIndexMap = {};
  tradingDates.forEach(function (d, i) { dateIndexMap[d] = i; });
  return { tradingDates: tradingDates, dateIndexMap: dateIndexMap };
}

function buildLinePts(s, dates, dateIndexMap) {
  const pts = [];
  let lastVal = null;
  let lastRaw = null;
  (s.values || []).forEach(function (v, i) {
    const date = dates[i];
    if (dateIndexMap[date] === undefined) return;
    if (v != null) {
      lastVal = v;
      lastRaw = s.raw ? s.raw[i] : null;
      pts.push({ x: date, y: v, rawVal: lastRaw });
    } else if (lastVal != null) {
      pts.push({ x: date, y: lastVal, rawVal: lastRaw, filled: true });
    }
  });
  return pts;
}

function buildLineDataset(s, color, pts, extra) {
  const area = !!(extra && extra.area);
  const ds = {
    label: s.label,
    key: s.key,
    data: pts,
    borderColor: withAlpha(color, 0.85),
    hoverBorderColor: color,
    hoverBorderWidth: 2.6,
    backgroundColor: "transparent",
    fill: false,
    tension: 0.25,
    borderWidth: 1.8,
    pointRadius: function (c) { return c.dataIndex === c.dataset.data.length - 1 ? 2.5 : 0; },
    pointHoverRadius: 'ontouchstart' in window ? 0 : 7,
    pointHoverBorderWidth: 'ontouchstart' in window ? 0 : 2,
    pointBackgroundColor: color,
    pointBorderColor: "#fff",
    pointBorderWidth: 1.5,
    pointHitRadius: 10
  };
  if (area) {
    // 面积渐变（Chart.js v4 原生）：数据区自上而下淡出
    ds.fill = true;
    ds.backgroundColor = function (ctx) {
      const ca = ctx.chart.chartArea;
      if (!ca) return 'transparent';
      const grad = ctx.chart.ctx.createLinearGradient(0, ca.top, 0, ca.bottom);
      grad.addColorStop(0, withAlpha(color, 0.26));
      grad.addColorStop(1, withAlpha(color, 0));
      return grad;
    };
  }
  return ds;
}

// maintainAspectRatio:false —— 位图尺寸由 .chart-wrap 容器高度决定（禁止 CSS !important 覆盖）
function buildLineOptions(tradingDates, extra) {
  const tc = themeColors();
  const maxTicks = (extra && extra.maxTicks) || 10;
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        display: false,
        labels: { color: tc.axisTick, usePointStyle: true, boxWidth: 8, font: { size: 12 } }
      },
      tooltip: {
        enabled: !('ontouchstart' in window),
        backgroundColor: tc.tooltipBg,
        titleColor: tc.tooltipTitle,
        bodyColor: tc.tooltipBody,
        borderColor: tc.tooltipBorder,
        borderWidth: 1,
        titleFont: { size: 11 },
        bodyFont: { size: 12 },
        padding: 8,
        cornerRadius: 4,
        boxWidth: 8,
        callbacks: {
          title: function (items) { return items.length ? items[0].label : ""; },
          label: function (ctx) {
            const pt = ctx.dataset.data[ctx.dataIndex];
            const rv = pt && pt.rawVal != null ? pt.rawVal : null;
            if (rv == null || ctx.parsed.y == null) return ctx.dataset.label + " —";
            return ctx.dataset.label + " " + fmtNum(rv, 2) + " (" + fmtPct(ctx.parsed.y - 100) + ")";
          }
        }
      }
    },
    scales: {
      x: {
        type: "category",
        labels: tradingDates,
        grid: { display: false },
        ticks: {
          font: { size: 11 },
          color: tc.axisTick,
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: maxTicks,
          callback: function (value, index) {
            const parts = String(tradingDates[index]).split("-");
            return Number(parts[1]) + "/" + Number(parts[2]);
          }
        }
      },
      y: {
        position: "right",   // V2：效果图刻度在右侧（crosshair 气泡动态读轴侧，自动跟随）
        grid: { color: tc.gridLine },
        border: { display: false },
        ticks: {
          font: { size: 11 },
          color: tc.axisTick,
          maxTicksLimit: 5,
          callback: fmtAxisPct
        }
      }
    },
    animation: { duration: 300, easing: "easeOutQuart" }
  };
  if (window.ChartZoom && !window.__zoomFailed) {
    options.plugins.zoom = {
      wheel: { enabled: true, modifierKey: "ctrl" },
      pan: { enabled: true, modifierKey: "ctrl" },
      limits: { y: { min: "original", max: "original" } }
    };
  }
  return options;
}

function tickLimit(days) {
  if (days <= 7) return 7;
  if (days <= 90) return 10;
  return 14;   // 365 点必须限量，否则标签糊成一团
}
function rangeShort(days) {
  return days >= 365 ? '1Y' : days + 'D';
}

function renderTrendTabs() {
  const box = document.getElementById('trend-tabs');
  if (!box) return;
  box.innerHTML = '';
  GROUPS.forEach(function (g) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = g.name;
    btn.className = state.trendGroup === g.id ? 'active' : '';
    btn.dataset.group = g.id;
    btn.addEventListener('click', function () {
      if (state.trendGroup === g.id) return;
      state.trendGroup = g.id;
      // 原地切换 active 类（不重建 DOM，避免按钮节点脱离文档 / 丢失焦点）
      box.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
      renderMainChart();   // 纯客户端切换：复用 state.history，不发网络请求
    });
    box.appendChild(btn);
  });
}

function renderTrendMeta(g, series) {
  const el = document.getElementById('trend-meta');
  if (!el) return;
  el.innerHTML = '';
  if (!series || !series.length) {
    el.textContent = (g ? g.name : '') + ' · 暂无数据';
    return;
  }
  const palette = colors();
  series.forEach(function (s) {
    const span = document.createElement('span');
    span.className = 'meta-item';
    span.style.color = palette[s.key] || '#8b949e';
    span.textContent = s.label + ' ' + rangeShort(state.days) + ' ' + fmtPct(s.change_7d);
    el.appendChild(span);
  });
}

// === 悬停水平参考线（crosshair）——内联插件，仅挂 #chart-main 实例，不 Chart.register ===
// Q2 定调：横线 Y 取鼠标在绘图区内的纵向位置（非数据点）→ 一条中性色线 + 一个涨跌幅读数
// （Q3/Q4），与系列无关。afterDatasetsDraw 绘制 → 线在数据之上、tooltip 之下（R5）。
const hoverCrosshair = {
  id: 'hoverCrosshair',
  afterEvent: function (chart, args) {
    const e = args.event;
    const area = chart.chartArea;
    // 离开画布 / 触屏抬手 → 清线重绘（触屏下 tooltip 被禁，横线+气泡是唯一读数）
    if (e.type === 'mouseout' || e.type === 'touchend') {
      if (chart.$crossY != null) { chart.$crossY = null; chart.draw(); }
      return;
    }
    if ((e.type !== 'mousemove' && e.type !== 'touchmove') || !area) return;
    if (e.y < area.top || e.y > area.bottom) {
      if (chart.$crossY != null) { chart.$crossY = null; chart.draw(); }   // 移出绘图区即隐藏
      return;
    }
    // R1 核心：Chart.js 只在激活元素集合变化时自动重绘，同 x 索引内纵向移动集合不变，
    // 必须手动 chart.draw() 才能实时跟随（勿用 update()，会重算布局/动画）；1px 节流。
    if (chart.$crossY != null && Math.abs(e.y - chart.$crossY) < 1) return;
    chart.$crossY = e.y;
    chart.draw();
  },
  afterDatasetsDraw: function (chart) {
    const y = chart.$crossY;
    if (y == null) return;
    const area = chart.chartArea;
    const axis = chart.scales.y;
    const tc = themeColors();
    const ctx = chart.ctx;
    ctx.save();
    // 全宽虚线，中性色与系列无关；坐标一律 CSS 像素，勿乘 devicePixelRatio（R2）
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = withAlpha(tc.axisTick, 0.65);
    ctx.moveTo(area.left, y);
    ctx.lineTo(area.right, y);
    ctx.stroke();
    // Y 轴端百分比气泡：动态贴当前轴侧（R7，勿写死 left），垂直钳制在画布内（R4）
    const text = fmtAxisPct(axis.getValueForPixel(y));
    chart.$crosshairLabel = text;   // 可测性挂钩：verify_ui.py 对气泡的唯一客观断言点
    const f = (window.Chart.defaults && window.Chart.defaults.font) || {};
    ctx.font = '11px ' + (f.family || 'sans-serif');
    const bw = ctx.measureText(text).width + 10;
    const bh = 16;
    const pad = bh / 2 + 2;
    const cy = Math.min(Math.max(y, pad), chart.height - pad);
    const bx = axis.position === 'right' ? area.right + 2 : area.left - 2 - bw;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, cy - bh / 2, bw, bh, 4); else ctx.rect(bx, cy - bh / 2, bw, bh);
    ctx.fillStyle = tc.tooltipBg;
    ctx.fill();
    ctx.strokeStyle = tc.tooltipBorder;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = tc.tooltipBody;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, bx + 5, cy);
    ctx.restore();
  }
};

function renderMainChart() {
  const canvas = document.getElementById('chart-main');
  const emptyEl = document.getElementById('chart-main-empty');
  if (!canvas) return;
  if (charts.main) { charts.main.destroy(); delete charts.main; }

  let g = GROUPS[0];
  GROUPS.forEach(function (x) { if (x.id === state.trendGroup) g = x; });
  const history = state.history || {};
  const dates = history.dates || [];
  const series = (history.series || []).filter(function (s) { return g.keys.indexOf(s.key) !== -1; });

  if (window.__chartFailed || !window.Chart) {
    canvas.style.display = 'none';
    if (emptyEl) {
      emptyEl.classList.remove('hidden');
      emptyEl.textContent = '图表加载失败（离线 / CDN 不可达）';
    }
    return;
  }
  if (!dates.length || !series.length) {
    canvas.style.display = 'none';
    if (emptyEl) {
      emptyEl.classList.remove('hidden');
      emptyEl.textContent = '暂无数据';
    }
    renderTrendMeta(g, []);
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');
  canvas.style.display = '';
  if (window.ChartZoom && !window.__zoomFailed && !renderMainChart._zoomRegistered) {
    Chart.register(window.ChartZoom);
    renderMainChart._zoomRegistered = true;
  }
  const axis = buildTradingAxis(dates, series);
  const palette = colors();
  const datasets = series.map(function (s) {
    return buildLineDataset(s, palette[s.key], buildLinePts(s, dates, axis.dateIndexMap), { area: true });
  });
  charts.main = new Chart(canvas, {
    type: 'line',
    data: { datasets: datasets },
    options: buildLineOptions(axis.tradingDates, { maxTicks: tickLimit(state.days) }),
    plugins: [hoverCrosshair]   // 内联插件仅挂本实例（不 Chart.register，避免影响全局）
  });
  renderTrendMeta(g, series);
}

// === KPI 卡（4 张：美股 / A股 / VIX / 自选）===
function renderLede() {
  const el = document.getElementById('lede');
  if (!el) return;
  const idxMap = sourceMap('indices');

  function make(sym, label, kind) {
    const d = idxMap[sym];
    if (!d || d.value == null) {
      if (!state.latest) {
        return { label: label, kind: kind, sym: sym, val: '—', sub: '加载中…', subCls: '' };
      }
      return null;
    }
    const chg = d.change_pct;
    let sub, subCls;
    if (chg == null) { sub = d.status || '—'; subCls = ''; }
    else { sub = fmtPct(chg); subCls = chg >= 0 ? 'pos' : 'neg'; }
    return { label: label, kind: kind, sym: sym, val: fmtNumSep(d.value, 2), sub: sub, subCls: subCls };
  }

  const cells = [];
  [make('GSPC', '美股 · 标普500', 'accent'),
   make('SH', 'A股 · 上证指数', 'pos'),
   make('VIX', 'VIX 恐慌指数', 'neg')].forEach(function (c) { if (c) cells.push(c); });

  // 第 4 张：自选（config.json watchlist.stocks 首个有效标的；未到达 → 占位防布局跳变）
  let wcell = null;
  (((state.watch || {}).stocks) || []).forEach(function (s) {
    if (wcell || !s || s.value == null) return;
    const wc = s.change_pct;
    wcell = {
      label: s.label || s.symbol || '自选', kind: 'accent', sym: s.symbol,
      val: fmtNumSep(s.value, 2),
      sub: wc == null ? (s.status || '—') : fmtPct(wc),
      subCls: wc == null ? '' : (wc >= 0 ? 'pos' : 'neg')
    };
  });
  cells.push(wcell || {
    label: '自选', kind: 'accent', sym: '', val: '—',
    sub: state.watch ? '数据暂缺' : '加载中…', subCls: ''
  });

  el.innerHTML = cells.map(function (c) {
    return '<div class="kpi-card kpi-' + c.kind + '">' +
      '<div class="kpi-info">' +
        '<div class="kpi-label">' + escapeHtml(c.label) + '</div>' +
        '<div class="kpi-val">' + escapeHtml(c.val) + '</div>' +
        '<div class="kpi-sub ' + c.subCls + '">' + escapeHtml(c.sub) + '</div>' +
      '</div>' +
      '<canvas class="kpi-spark" data-sym="' + escapeHtml(c.sym || '') + '"></canvas>' +
      '</div>';
  }).join('');
  paintSparklines();
}

// === KPI sparkline（原生 canvas，不用 Chart.js）===
let _sparkSeries = {};
function sparkColor(cv) {
  const card = cv.closest ? cv.closest('.kpi-card') : null;
  const sub = card && card.querySelector('.kpi-sub');
  const cls = sub ? (sub.className || '') : '';
  if (cls.indexOf('pos') >= 0 || cls.indexOf('neg') >= 0) return getComputedStyle(sub).color;
  return getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#9aa4b2';
}
function drawOneSpark(cv, values, color) {
  if (!cv) return;
  const ctx = cv.getContext('2d');
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 96;
  const h = cv.clientHeight || 56;
  const pts = [];
  (values || []).forEach(function (v) { if (v != null) pts.push(v); });
  if (pts.length < 2) { ctx.clearRect(0, 0, cv.width, cv.height); return; }
  cv.width = Math.max(1, Math.round(w * dpr));
  cv.height = Math.max(1, Math.round(h * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
  const range = (max - min) || 1;
  const n = pts.length;
  ctx.beginPath();
  for (let j = 0; j < n; j++) {
    const x = (n === 1) ? 0 : (j / (n - 1)) * w;
    const y = h - ((pts[j] - min) / range) * (h - 6) - 3;
    if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';
  ctx.strokeStyle = color || '#9aa4b2';
  ctx.stroke();
}
function paintSparklines() {
  const canvases = document.querySelectorAll('#lede canvas.kpi-spark');
  if (!canvases.length) return;
  const map = {};
  (((state.history || {}).series) || []).forEach(function (s) { if (s && s.key) map[s.key] = s.values; });
  ((((state.watch || {}).trend) || {}).series || []).forEach(function (s) { if (s && s.key) map[s.key] = s.values; });
  _sparkSeries = map;
  canvases.forEach(function (cv) {
    const k = (cv.dataset.sym || '').toLowerCase();
    drawOneSpark(cv, map[k], sparkColor(cv));
  });
}
function repaintSparklines() {
  document.querySelectorAll('#lede canvas.kpi-spark').forEach(function (cv) {
    const k = (cv.dataset.sym || '').toLowerCase();
    drawOneSpark(cv, _sparkSeries[k], sparkColor(cv));
  });
}

// === 自选列表（实时取数；纯 CSS 百分比迷你条）===
function renderWatchlist(payload) {
  const section = document.getElementById('watchlist-section');
  const body = document.getElementById('watchlist-body');
  if (!body) return;
  if (section) section.classList.remove('hidden');
  // 数据时点标注（三十期文件化）：快照路径带 as_of（ISO 本地时间），实时回退无此键 → 保持默认文案
  const asofEl = document.getElementById('watchlist-asof');
  if (asofEl) {
    const asOf = payload && payload.as_of ? String(payload.as_of) : '';
    asofEl.textContent = asOf.length >= 16 ? asOf.slice(5, 16).replace('T', ' ') : '收盘快照';
  }
  const stocks = (payload && payload.stocks) || [];
  body.innerHTML = '';
  if (!stocks.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">数据暂缺</td></tr>';
    return;
  }
  let maxAbs = 0.01;
  stocks.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.change_pct || 0)); });
  stocks.forEach(function (row) {
    const ico = iconHtml(ICON_COLORS[row.symbol],
      ICON_CHARS[row.symbol] || (row.label || '—').charAt(0));
    const tr = document.createElement('tr');
    if (row.value == null) {
      // 失败行：名称保留、其余列「数据暂缺」
      tr.innerHTML = '<td class="col-ico">' + ico + '</td>' +
        '<td class="name">' + escapeHtml(row.label || '—') + '</td>' +
        '<td class="empty">数据暂缺</td><td class="empty">数据暂缺</td><td class="col-bar"></td>';
      body.appendChild(tr);
      return;
    }
    const chg = row.change_pct;
    const cls = chg == null ? '' : (chg >= 0 ? 'pos' : 'neg');
    const width = chg == null ? 0 : Math.min(100, Math.abs(chg) / maxAbs * 100).toFixed(1);
    tr.innerHTML =
      '<td class="col-ico">' + ico + '</td>' +
      '<td class="name">' + escapeHtml(row.label || '—') + '</td>' +
      '<td class="num">' + fmtNumSep(row.value, 2) + '</td>' +
      '<td class="num chg"><span class="chg-pill ' + cls + '">' + fmtPct(chg) + '</span></td>' +
      '<td class="col-bar"><span class="mini-bar"><i class="' + (chg >= 0 ? 'pos' : 'neg') +
      '" style="width:' + width + '%"></i></span></td>';
    body.appendChild(tr);
  });
}

// === 顶栏数据日（数据日 + 数据日星期，C6）===
function updateTopbarDate(dateStr) {
  const el = document.getElementById('topbar-date');
  if (!el) return;
  if (!dateStr) { el.textContent = '—'; return; }
  const wd = weekdayLabel(dateStr);
  el.textContent = dateStr + (wd ? ' ' + wd : '') + (isWeekendDate(dateStr) ? ' · 休市' : '');
}

// === 侧栏底部：市场状态 + 北京时间（纯前端，不新增端点）===
function updateMarketStatus() {
  const st = document.getElementById('market-status');
  const tm = document.getElementById('market-time');
  const dot = document.getElementById('market-dot');
  if (!st || !tm) return;
  let open = false, hh = '—', mm = '—';
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Shanghai', hourCycle: 'h23',
      weekday: 'short', hour: '2-digit', minute: '2-digit'
    }).formatToParts(new Date());
    const map = {};
    parts.forEach(function (p) { map[p.type] = p.value; });
    const wdIdx = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(map.weekday);
    open = wdIdx >= 1 && wdIdx <= 5;
    hh = map.hour;
    mm = map.minute;
  } catch (e) { /* 时区数据缺失：保留默认文案 */ }
  st.textContent = open ? '市场已开盘' : '休市';
  tm.textContent = '北京时间 ' + hh + ':' + mm;
  if (dot) dot.classList.toggle('open', open);
}

// === 刷新 ===
function loadFailed(msg, boxId) {
  const box = document.getElementById(boxId);
  if (box) box.innerHTML = '<p class="empty">加载失败：' + escapeHtml(msg) + '</p>';
}

function refresh() {
  const rangeLabel = document.getElementById('range-label');
  if (rangeLabel) rangeLabel.textContent = state.days >= 365 ? '近 1 年' : '近 ' + state.days + ' 日';
  fetch(buildQuery()).then(function (r) { return r.json(); })
    .then(function (history) {
      state.history = history;
      renderMainChart();
      paintSparklines();
    })
    .catch(function () { renderMainChart(); });

  fetch('/api/latest').then(function (r) { return r.json(); })
    .then(function (data) {
      state.latest = data;
      updateTopbarDate(data.date);
      renderOverview();
      renderSector(data);
      renderRiskAppetite(data);
      renderMarketRelation(data);
      renderUsSectors(data);
      renderLede();
    })
    .catch(function (e) { loadFailed(e.message, 'overview-body'); });
}

// === 初始化 ===
document.addEventListener('DOMContentLoaded', function () {
  // 主题切换（切后重渲染图表以同步线色/图例色）
  const themeBtn = document.getElementById('sidebar-theme');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      const next = getTheme() === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('mp-theme', next); } catch (e) {}
      applyTheme(next);
      renderMainChart();
      repaintSparklines();
    });
  }
  // 移动端抽屉
  const menuBtn = document.getElementById('menu-toggle');
  if (menuBtn) menuBtn.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
  const navBackdrop = document.createElement('div');
  navBackdrop.className = 'nav-backdrop';
  document.body.appendChild(navBackdrop);
  navBackdrop.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
  const mainEl = document.getElementById('main');
  if (mainEl) mainEl.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
  // 侧栏锚点导航 + active 态
  document.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
    item.addEventListener('click', function (e) {
      document.body.classList.remove('nav-open');
      const target = item.getAttribute('data-target');
      const el = target && document.getElementById(target);
      if (!el) return;
      e.preventDefault();
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.querySelectorAll('#sidebar .nav-item').forEach(function (n) { n.classList.remove('active'); });
      item.classList.add('active');
    });
  });
  // 刷新按钮
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', function () { refresh(); });
  // 时间范围（7D / 30D / 90D / 1Y）
  const rangeBar = document.getElementById('range-bar');
  if (rangeBar) {
    rangeBar.addEventListener('click', function (e) {
      const btn = e.target.closest('button[data-days]');
      if (!btn) return;
      state.days = parseInt(btn.dataset.days, 10);
      document.querySelectorAll('#range-bar button').forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
      refresh();
    });
  }
  window.addEventListener('resize', repaintSparklines);

  renderPlaceholders();
  renderTrendTabs();
  renderLede();
  updateMarketStatus();
  setInterval(updateMarketStatus, 60000);
  refresh();

  // 告警（仅初始加载一次）
  fetch('/api/alerts')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) { renderAlerts(Array.isArray(data) ? data : []); })
    .catch(function (err) {
      console.error('[alerts] fetch failed:', err);
      const el = document.getElementById('alert-list');
      if (el) el.innerHTML = '<p class="empty">加载失败</p>';
    });

  // 资讯（仅初始加载一次；Hermes 落盘 data/news.json，未接入时为空态「暂无资讯」）
  fetch('/api/news')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) { renderNews(data); })
    .catch(function (err) {
      console.error('[news] fetch failed:', err);
      const el = document.getElementById('news-body');
      if (el) el.innerHTML = '<p class="ph-note">暂无资讯</p>';
    });

  // 自选股实时取数（hidden=true 仅=无配置；异常态失败占位可见，不静默隐藏）
  let wlTimer = null;
  const wlFetch = fetch('/api/watchlist').then(function (r) { return r.json(); });
  const wlTimeout = new Promise(function (_, reject) {
    wlTimer = setTimeout(function () { reject(new Error('watchlist 取数超时（12s）')); }, 12000);
  });
  Promise.race([wlFetch, wlTimeout])
    .then(function (data) {
      clearTimeout(wlTimer);
      const sec = document.getElementById('watchlist-section');
      if (!sec) return;
      state.watch = data || { stocks: [] };
      if (data && data.hidden) {
        sec.classList.add('hidden');   // F4：无配置不闪现
      } else {
        renderWatchlist(state.watch);
      }
      renderLede();
    })
    .catch(function (err) {
      console.error('[watchlist] fetch failed:', err);
      const sec = document.getElementById('watchlist-section');
      if (!sec) return;
      sec.classList.remove('hidden');
      const b = document.getElementById('watchlist-body');
      if (b) b.innerHTML = '<tr><td colspan="5" class="empty">数据暂缺（取数失败）</td></tr>';
      state.watch = { stocks: [] };
      renderLede();
    });

  // 宏观标的（美元指数 / 10Y美债 / 原油）：失败仅占位「数据未接入」，不阻塞其余模块
  let mcTimer = null;
  const mcFetch = fetch('/api/macro').then(function (r) { return r.json(); });
  const mcTimeout = new Promise(function (_, reject) {
    mcTimer = setTimeout(function () { reject(new Error('macro 取数超时（12s）')); }, 12000);
  });
  Promise.race([mcFetch, mcTimeout])
    .then(function (data) {
      clearTimeout(mcTimer);
      state.macro = data || { stocks: [] };
      renderOverview();
    })
    .catch(function (err) {
      console.error('[macro] fetch failed:', err);
      state.macro = { stocks: [] };
      renderOverview();
    });
});
