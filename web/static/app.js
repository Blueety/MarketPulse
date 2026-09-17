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
// ⚠️ 2026-09-14（macro-chart-crosshair）：`cssVar` / `themeColors` / `withAlpha` 三件套已收敛到
//    `/static/chart-crosshair.js`（与 crosshair 插件同文件，供首页 + 宏观页共用，消除两份实现）。
//    本文件继续**裸调用同名函数**（它们是 window 上的全局函数）→ 调用点零改动。
//    ⚠️ 该脚本必须在 `<script src="app.js">` **之前**引入（index.html 已保证）。
const SERIES_VAR = {
  gspc: "--c-gspc", ixic: "--c-ixic", sh: "--c-sh", sz: "--c-sz", cyb: "--c-cyb",
  vix: "--c-vix", vxn: "--c-vxn", move: "--c-move", gld: "--c-gld", btc: "--c-btc",
  "gc=f": "--c-gld"   // 三十四期：黄金 COMEX 沿用 GLD 金色 token
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

// 色值加透明度：实现见 `/static/chart-crosshair.js`（`window.withAlpha`，与本文件旧实现逐字节一致）。

const charts = {};  // 'main' -> Chart 实例（重渲染前 destroy）
if (window.Chart && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;

// 趋势主图类别（四图合一后的 4 个 tab，keys 为 history 小写键）
const GROUPS = [
  { id: "us", name: "美股大盘", keys: ["gspc", "ixic"] },
  { id: "cn", name: "A 股大盘", keys: ["sh", "sz", "cyb"] },
  { id: "vol", name: "波动率", keys: ["vix", "vxn", "move"] },
  { id: "alt", name: "另类资产", keys: ["btc"], macroGold: "gc=f" }   // 三十四期：黄金线改用 /api/macro 的 GC=F 实时序列
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
  { id: 'GC=F', label: '黄金 · COMEX', source: 'macro', icon: 'gold', char: '金' },
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
  "DX-Y.NYB": "--c-ixic", "^TNX": "--c-move", "CL=F": "--c-vxn", "GC=F": "--c-gld",
  "515300.SS": "--c-gspc"
};
const ICON_CHARS = {
  "515300.SS": "红",   // 红利低波
  "399997.SZ": "酒",   // 中证白酒
  "515880.SS": "通",   // 通信
  "512010.SS": "医",   // 医药
  "515790.SS": "光",   // 光伏
  "512200.SS": "房",   // 房地产
  "159732.SZ": "电",   // 消费电子
  "159852.SZ": "软",   // 软件
  "513130.SS": "港"    // 恒生科技（港股）
};
const ICON_PALETTE = ["--c-gspc", "--c-ixic", "--c-sh", "--c-sz", "--c-cyb", "--c-move", "--c-vix", "--c-gld"];
const ICON_FALLBACK_VAR = "--text-muted";
function iconHtml(colorVar, char) {
  const bg = "var(" + (colorVar || ICON_FALLBACK_VAR) + ")";
  return '<i class="ico" style="background:' + bg + '">' + escapeHtml(char || "") + "</i>";
}
// 自选股图标底色：ICON_COLORS 命中 → 该标的品牌色；否则**按行序**循环 `ICON_PALETTE_WATCH`。
// ⚠️ 2026-09-17 用户反馈「自选股图标都是同一个颜色」：此前未命中的标的**一律落 `--text-muted` 中性灰**。
//    修法沿用项目既有约定（无 brand 色 → 按行序循环，见上方注释）；这里单独用 10 色版调色板
//    （比 `ICON_PALETTE` 多 `--c-vxn` / `--c-btc`），**不动板块表格的 8 色循环**，避免牵连无关视图。
const ICON_PALETTE_WATCH = ["--c-gspc", "--c-ixic", "--c-sh", "--c-sz", "--c-cyb",
                            "--c-move", "--c-vix", "--c-gld", "--c-vxn", "--c-btc"];
function watchIconColor(symbol, index) {
  return ICON_COLORS[symbol] || ICON_PALETTE_WATCH[index % ICON_PALETTE_WATCH.length];
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
  latestDate: null,   // /api/latest 的 date：判定板块数据是否新鲜（as_of !== date → 显示快照标注）
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
  _sectorAsOf.cn = (latest && latest.sector_heat && latest.sector_heat.as_of) || null;
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

// === 美股行业板块：与 A股 同构的表格（2026-09-14 由条形列表改造）===
// ⚠️ slice 必须与 A股 一样是 5：.row-3 三卡 stretch 等高，行高由内容更高的 panel 决定，
//    美股侧一旦多出行数就会反超 A股 → 撑高 .row-3 → 顶破 scrollHeight ≤1240 护栏。
// ⚠️ 涨跌幅列必须是 `<td class="num chg">`（不能省 chg）：`.chg-pill`(≈19px) 高于 12px 文字行高(≈17.4px)，
//    靠 `#us-sectors .data-table td.chg { padding: 3px 8px }` 上下各减 1px 对冲；漏了是每行 +2px × 5 行。
function renderUsSectors(latest) {
  const tbody = document.getElementById('us-sectors-body');
  if (!tbody) return;
  tbody.innerHTML = '';
  const gainers = (latest && latest.us_sector_heat && latest.us_sector_heat.gainers) || [];
  _sectorAsOf.us = (latest && latest.us_sector_heat && latest.us_sector_heat.as_of) || null;
  if (!gainers.length) {
    tbody.innerHTML = '<tr><td colspan="5">数据暂缺</td></tr>';   // 与 A股 同款空态
    return;
  }
  gainers.slice(0, 5).forEach(function (g, i) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="col-ico">' + iconHtml(ICON_PALETTE[i % ICON_PALETTE.length], (g.name || '—').charAt(0)) + '</td>' +
      '<td>' + escapeHtml(g.name || '—') + '</td>' +
      '<td class="num chg"><span class="chg-pill ' + ((g.change || 0) >= 0 ? 'pos' : 'neg') + '">' +
        fmtPct(g.change) + '</span></td>' +
      '<td class="col-turnover num">' + escapeHtml(g.turnover || '—') + '</td>' +
      '<td>' + escapeHtml(g.top_stock || '—') + '</td>';
    tbody.appendChild(tr);
  });
}

// === 板块数据新鲜度标注（读取端陈旧回填的配套显示）===
// 两个板块在同一天**独立取数**（A股 1 个请求 / 美股 11 个请求）→ 可各自回看到**不同**日期，
// 所以各自的 as_of 分开缓存、按当前 tab 决定显示哪个。
// ⚠️ 纯 CSS tab（:checked + 兄弟选择器）**没有切换事件** → 不挂 radio change 监听，
//    切 tab 时标注不会更新（现象是"A股 tab 显示着美股的快照日期"）。
var _sectorAsOf = { cn: null, us: null };

function renderSectorAsOf() {
  var el = document.getElementById('us-sectors-asof');
  if (!el) return;
  var usRadio = document.getElementById('sector-tab-us');
  var which = (usRadio && usRadio.checked) ? 'us' : 'cn';
  var asOf = _sectorAsOf[which];
  var cur = state.latestDate;
  // as_of === date（数据就是当天的）或 as_of 为 null（无数据，表格自己显示「数据暂缺」）→ 不标注
  el.textContent = (asOf && cur && asOf !== cur) ? '· 数据截至 ' + asOf : '';
}

// === 告警记录 ===
function renderAlerts(alerts) {
  alertScroller.stop();                          // ★ 先停旧循环，再重建 DOM
  const box = document.getElementById("alert-list");
  if (!box) return;
  if (!alerts || !alerts.length) {
    box.innerHTML = '<p class="empty">暂无告警记录</p>';
    return;                                      // 空态不加克隆半、不起滚动
  }
  const cards = alerts.map(function (a) {
    const level = a.level || "";
    const cls = level === "ALERT" ? "alert" : (level === "WARN" ? "warn" : "");
    return '<div class="alert-card ' + cls + '">' +
      '<div class="alert-head"><span class="badge ' + cls + '">' + escapeHtml(level) + "</span>" +
      "<span>" + escapeHtml(a.symbol || "") + " · " + escapeHtml(a.date || "") + "</span></div>" +
      '<div class="alert-meta">类型：' + escapeHtml(a.type || "—") + " ｜ 市场状态：" + escapeHtml(a.state || "—") + "</div>" +
      // ⚠️ 2026-09-17（产线走查 G1）：「当前值：」无时间锚点 —— 告警是**历史文档**（如 09-11 收盘），
      //    用户会拿它和顶部的最新值对不上。措辞锚定为「告警日收盘 / 前一日」，日期由卡片头部承载（原有）。
      // ⚠️ **不要把日期写进这一行**：实测（mp_g1_fit 探针）带日期的行会折行 ⇒ 单条告警卡 134px > 容器 132px
      //    ⇒ 触发 B-12「内容不足一屏仍滚动」的既有护栏（原地抖动）。选型过程见本任务 journal §4.3。
      '<div class="alert-row">告警日收盘：' + fmtNum(a.current, 2) + " ｜ 前一日：" + fmtNum(a.last, 2) +
      " ｜ 变化率：" + fmtPct(a.change_pct) + "（阈值 ±" + fmtNum(a.threshold, 1) + "%）</div>" +
      '<div class="alert-sugg">建议：' + escapeHtml(a.suggestion || "—") + "</div>" +
      '<div class="alert-report">相关报告：' + escapeHtml(a.report || "—") + "</div>" +
      "</div>";
  }).join('');
  // 与资讯卡同一机制：渲染两遍（克隆半像素级相同 → 减周期即无缝），克隆半 aria-hidden 防重复朗读。
  box.innerHTML = cards + '<div class="alert-clone" aria-hidden="true">' + cards + '</div>';
  box.scrollTop = 0;
  alertScroller.bind(box);
  alertScroller.start();                         // 内容不足一屏时内部自行不启动
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
    // ⚠️ 2026-09-17（产线走查 G2 / P2-5）：原文案「暂无显著相关对（近30日 |r|≤0.5）」两处问题——
    //    ①「≤0.5」写法有歧义（规则是"只列出 |r|>0.5 的对"，不存在"≤0.5 的对被排除"）；
    //    ② 纯术语、无任何解释。
    // ⚠️ 数字 0.5 是**引用**不是第二处阈值：correlation 由服务端只收 |r| ≥ CORRELATION_SIGNIFICANT
    //    （src/analyzer.py:77，注释写明"颜色编码与 context 写入共用"）的对 ⇒ 此处"均低于 0.5"即"全部不显著"。
    //    别在这里再发明一个阈值（D2 同款缺陷："标注写 X、行为做 Y"）。
    row.innerHTML = '<p class="ph-note" title="相关系数：衡量两个指数同涨同跌的程度，|r| ≥ 0.5 视为明显联动。' +
      '数据窗口为近 30 个交易日的收盘价。">近 30 日未发现明显联动关系（相关系数 |r| 均低于 0.5）</p>';
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
// === 资讯 / 告警 自动循环滚动（scrollTop + requestAnimationFrame，两卡共用一套机制）===
// 为什么不用 CSS transform 动画：手动滚动（overflow-y:auto）与 transform 动画是两套机制，
// 叠加会跳变；且 reduce-motion 关掉动画后，**后面的条目将永远不可达**。用 scrollTop 驱动
// 可让「向上匀速 / 保留手动滚动 / reduce-motion 退化为纯手动」三者共存。
var NEWS_SCROLL_PX_PER_SEC = 16;   // 两卡共用同一速度（待目视定稿：约 2.1s 过一行）

// 每个滚动容器一份**独立状态**（两个 rAF 循环并存，绝不能共用全局变量，否则互相踩）
function makeAutoScroller(bodyId, itemSel) {
  var st = {
    raf: 0, last: 0, period: 0, paused: false, bound: false,
    // ★ 浮点累加位置。**绝不能写 `el.scrollTop += 增量`**：该容器 scrollTop 读回来是整数，
    // 当每帧增量 <1px（如 16px/s ÷ 60fps = 0.27px）时小数部分每帧都被取整抹掉 → 位置永远停在 0
    // （60fps 下看起来「完全不动」）；低帧率下则变成 1~2px 一格一跳（观感卡顿）。
    // 实测证据见 tasks/2026-09-13-news-autoscroll/journal.md。
    pos: 0,
  };

  function el() { return document.getElementById(bodyId); }

  function stop() {
    if (st.raf) { cancelAnimationFrame(st.raf); st.raf = 0; }
    st.paused = false;
    st.period = 0;
    st.pos = 0;
  }

  function syncFromEl() {
    // 用户手动滚动 / 暂停恢复后把累加器对齐到真实位置，避免「跳回去」
    var e = el();
    if (e) st.pos = e.scrollTop;
  }

  function step(now) {
    st.raf = requestAnimationFrame(step);
    var e = el();
    if (!e) { stop(); return; }
    var dt = (now - st.last) / 1000;
    st.last = now;
    if (st.paused || dt <= 0) return;
    if (dt > 0.5) dt = 0.5;                        // 后台切回/长间隔 → 钳制，防一次跳很远
    st.pos += NEWS_SCROLL_PX_PER_SEC * dt;         // 浮点累加（不受 getter 取整影响）
    // 无缝循环：越过「一个循环周期」时**减去周期**（不是归零，避免累积误差）
    if (st.period > 0 && st.pos >= st.period) st.pos -= st.period;
    e.scrollTop = st.pos;                          // 只在赋值这一刻交给浏览器取整
  }

  function start() {
    var e = el();
    if (!e) return;
    // 无障碍：reduce-motion 下不启动（style.css 另有 overflow-y:auto 兜底，保证内容仍可手动翻到）
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var items = e.querySelectorAll(itemSel);
    var n = Math.floor(items.length / 2);          // 双份内容 → 前一半 = 一个完整循环
    if (n <= 0) return;
    // 周期 = 克隆半首条相对第一半首条的偏移（offsetTop 差）。
    // 比「前一半 offsetHeight 之和」通用：flex gap 布局（.alert-list）下求和法会差 n×gap。
    var period = items[n].offsetTop - items[0].offsetTop;
    if (!(period > 0) || period <= e.clientHeight) return;   // 内容不足一屏 → 不滚（否则原地抖动）
    st.period = period;
    st.pos = e.scrollTop;
    st.last = performance.now();
    if (st.raf) cancelAnimationFrame(st.raf);      // ★ 防 rAF 叠加（否则速度越来越快）
    st.raf = requestAnimationFrame(step);
  }

  function bind(e) {
    if (st.bound) return;                          // 只绑一次（重渲染时 el 不变）
    st.bound = true;
    e.addEventListener('mouseenter', function () { st.paused = true; });
    e.addEventListener('mouseleave', function () {
      st.paused = false;
      st.last = performance.now();                 // ★ 必须重置：否则暂停期间的 dt 会瞬间大跳
      syncFromEl();                                // ★ 用户可能手动滚过 → 对齐再续滚
    });
    e.addEventListener('focusin', function () { st.paused = true; });      // 键盘 Tab 到链接也暂停
    e.addEventListener('focusout', function () {
      st.paused = false; st.last = performance.now(); syncFromEl();
    });
    document.addEventListener('visibilitychange', function () {            // 后台标签页不空转
      st.paused = document.hidden;
      if (!document.hidden) { st.last = performance.now(); syncFromEl(); }
    });
  }

  return { state: st, elId: bodyId, itemSel: itemSel,
           start: start, stop: stop, sync: syncFromEl, bind: bind };
}

var newsScroller = makeAutoScroller('news-body', '.news-item');
var alertScroller = makeAutoScroller('alert-list', '.alert-card');
window.__scroll = { news: newsScroller, alerts: alertScroller };   // 供验收脚本读取内部状态

function renderNews(payload) {
  newsScroller.stop();                           // ★ 先停旧循环，再重建 DOM
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
  // 内容渲染两遍（克隆半与第一半**像素级相同** → 减周期即无缝）。克隆半 aria-hidden 防重复朗读。
  body.innerHTML = html + '<div class="news-clone" aria-hidden="true">' + html + '</div>';
  body.scrollTop = 0;
  newsScroller.bind(body);
  newsScroller.start();                          // 内容不足一屏时内部自行不启动
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
    // ⚠️ 2026-09-16：悬停点交给 `chart-crosshair.js` 的**吸附标记**（每图只画一个，且必定与虚线同高）。
    //    Chart.js 的 `interaction.mode:'index'` 会给**每个系列**都画悬停点 → 多系列图上出现多个点，
    //    而虚线只穿过其中一个（用户反馈："虚线没跟那个点在一块"）。故系列自身不再画悬停点。
    pointHoverRadius: 0,
    pointHoverBorderWidth: 0,
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

// === 悬停水平参考线（crosshair）===
// 2026-09-14（macro-chart-crosshair）：插件本体已抽到 `/static/chart-crosshair.js`（`window.hoverCrosshair`），
// 与宏观页共用同一个对象；**id / $crosshairLabel / 节流 / 轴侧动态 / afterDatasetsDraw 全部未变**。
// 首页的读数口径（fmtAxisPct，相对 100 的偏离）是该插件的**默认兜底**，故此处行为逐字节不变。
// ⚠️ 该脚本必须在 `<script src="app.js">` **之前**引入，否则 `plugins: [window.hoverCrosshair]`
//    会变成 `[undefined]` 并被 Chart.js **静默忽略**（横线不出现且不报错）。

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
      // ⚠️ 2026-09-17（产线走查 G4）：「暂无数据」太泛 —— 这里是**趋势**卡，写明是趋势数据缺失，
      //    与上方失败条（取数失败）区分：这是"取到了但没数据"，不是错误。
      emptyEl.textContent = '暂无趋势数据';
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
  // 三十四期补全：macro 深度序列（tail 400）按当前窗口起点裁剪（防 7D 轴被 400 点撑爆），
  // 轴取 history ∪ macro(可见段) 并集；gc=f 重归一化为「可见窗口首个非空值 = 100」
  // （与 history 系列同基准，双线可比；raw 保留真价供 tooltip），change 按可见窗口覆盖。
  let axis;
  let gcSeries = null;
  if (g.macroGold) {
    const mc = state.macro && state.macro.trend ? state.macro.trend : null;
    gcSeries = (mc && mc.series ? mc.series : []).find(function (s) { return s.key === g.macroGold; }) || null;
  }
  const windowStart = dates.length ? dates[0] : null;
  const mcVisible = [];
  if (gcSeries) {
    (state.macro.trend.dates || []).forEach(function (d, i) {
      if (windowStart && d < windowStart) return;
      mcVisible.push({ d: d, i: i });
    });
    const all = new Set(dates);
    mcVisible.forEach(function (p) { all.add(p.d); });
    const tradingDates = Array.from(all).filter(function (d) { return !isWeekendDate(d); }).sort();
    const dateIndexMap = {};
    tradingDates.forEach(function (d, i) { dateIndexMap[d] = i; });
    axis = { tradingDates: tradingDates, dateIndexMap: dateIndexMap };
  } else {
    axis = buildTradingAxis(dates, series);
  }
  const palette = colors();
  const datasets = series.map(function (s) {
    return buildLineDataset(s, palette[s.key], buildLinePts(s, dates, axis.dateIndexMap), { area: true });
  });
  let gcMeta = null;
  if (gcSeries && mcVisible.length) {
    let base = null;   // 可见窗口首个非空原始值
    mcVisible.forEach(function (p) {
      const v = gcSeries.values ? gcSeries.values[p.i] : null;
      if (base === null && v != null) base = v;
    });
    const scale = base ? 100 / base : 1;
    const gcPts = [];
    let lastVal = null, lastRaw = null;
    mcVisible.forEach(function (p) {
      if (axis.dateIndexMap[p.d] === undefined) return;
      const v = gcSeries.values ? gcSeries.values[p.i] : null;
      const raw = gcSeries.raw ? gcSeries.raw[p.i] : null;
      if (v != null) {
        lastVal = v * scale;
        lastRaw = raw;
        gcPts.push({ x: p.d, y: lastVal, rawVal: raw });
      } else if (lastVal != null) {
        gcPts.push({ x: p.d, y: lastVal, rawVal: lastRaw, filled: true });
      }
    });
    if (gcPts.length) {
      datasets.push(buildLineDataset(gcSeries, palette[gcSeries.key] || palette.gld, gcPts, { area: true }));
      // meta 的涨跌幅按可见窗口覆盖（tail 400 下后端算的是 400 日变化，与所选档位不符）
      gcMeta = Object.assign({}, gcSeries, { change_7d: lastVal != null ? lastVal - 100 : null });
    }
  }
  charts.main = new Chart(canvas, {
    type: 'line',
    data: { datasets: datasets },
    options: buildLineOptions(axis.tradingDates, { maxTicks: tickLimit(state.days) }),
    plugins: [hoverCrosshair]   // 内联插件仅挂本实例（不 Chart.register，避免影响全局）
  });
  renderTrendMeta(g, gcMeta ? series.concat([gcMeta]) : series);
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
  // 图标配色按**配置序**取（而非显示序）：行会按涨跌幅重排，若用显示下标，同一标的的图标颜色
  // 会随名次每次刷新都跳。配置序索引稳定 ⇒ 颜色稳定，且仍能拿到 9 个不同色。
  const cfgIndex = {};
  stocks.forEach(function (s, i) { cfgIndex[s.symbol] = i; });
  // 按涨跌幅从大到小；change_pct 缺失（数据暂缺/失败行）排到最后。
  // Array.prototype.sort 稳定 ⇒ 同值保持配置序，不会来回抖。
  const rows = stocks.slice().sort(function (a, b) {
    const av = (a.change_pct == null || !isFinite(a.change_pct)) ? -Infinity : a.change_pct;
    const bv = (b.change_pct == null || !isFinite(b.change_pct)) ? -Infinity : b.change_pct;
    return bv - av;
  });
  rows.forEach(function (row) {
    const ico = iconHtml(watchIconColor(row.symbol, cfgIndex[row.symbol] || 0),
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
// ⚠️ 2026-09-16（market-session-status）：由单行「市场已开盘」改为**两行两市场**，逐市场按
//    **该市场本地时钟**判交易时段。旧实现只判「今天是不是工作日」⇒ 工作日任意时刻
//    （20:40、凌晨 3:00）都显示绿点「市场已开盘」，无法判断说的是哪个市场。
// ⚠️ **不改用「换算成北京时间再比 21:30」**：11 月夏令时结束后会静默错一小时（代码里不得出现 21:30 魔数）。
// ⚠️ 点色语义随之变更：原 `open` = 「今天是工作日」（全局单点）→ 新 `open` = 「**该市场此刻在交易**」
//    （逐市场）；「任一市场在交易」⇔「至少一颗绿」。
// ⚠️ 本段在 app.js / macro.js / macro_cn.js 各有一份**逐字副本** —— 改一处必须三处同改。
const MARKET_SESSIONS = {
  cn: { tz: 'Asia/Shanghai',    label: 'A股', open: '09:30', close: '15:00', midday: ['11:30', '13:00'] },
  us: { tz: 'America/New_York', label: '美股', open: '09:30', close: '16:00', midday: null },
};
const SESSION_LABELS = { open: '交易中', pre: '未开盘', post: '已收盘', midday: '午间休市', weekend: '休市' };

// 'HH:MM' → 分钟数
function marketHM(hm) {
  const p = hm.split(':');
  return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
}

// 该市场在 now 时刻的本地 {weekday, hh, mm}（口径与旧实现同：Intl + formatToParts，零新依赖）
function marketLocalParts(tz, now) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hourCycle: 'h23', weekday: 'short', hour: '2-digit', minute: '2-digit'
  }).formatToParts(now);
  const map = {};
  parts.forEach(function (p) { map[p.type] = p.value; });
  return { weekday: map.weekday, hh: map.hour, mm: map.minute };
}

// 单市场会话态：'weekend' | 'midday' | 'open' | 'pre' | 'post'
// 边界含左不含右（09:30:00 算开盘、11:30:00 算午休）；周末按**该市场 local weekday** 判
// （北京周六 03:00 = 美东周五 15:00 ⇒ A股「休市」+ 美股「交易中」，无需特例）。
// ⚠️ now 必须可注入 —— 验收的 DST / 时段边界断言依赖它。
function marketSessionOf(cfg, now) {
  const p = marketLocalParts(cfg.tz, now);
  if (p.weekday === 'Sat' || p.weekday === 'Sun') return 'weekend';
  const t = marketHM(p.hh + ':' + p.mm);
  if (cfg.midday && t >= marketHM(cfg.midday[0]) && t < marketHM(cfg.midday[1])) return 'midday';
  if (t >= marketHM(cfg.open) && t < marketHM(cfg.close)) return 'open';
  return t < marketHM(cfg.open) ? 'pre' : 'post';
}

// 两个市场的完整状态（label + 是否交易中）——**渲染与验收共用这一个函数**（同源断言的基础）
function marketStateOf(now) {
  const out = {};
  Object.keys(MARKET_SESSIONS).forEach(function (k) {
    const cfg = MARKET_SESSIONS[k];
    const s = marketSessionOf(cfg, now);
    out[k] = { session: s, open: s === 'open', label: cfg.label + ' ' + SESSION_LABELS[s] };
  });
  return out;
}

// 北京时间（第三行，口径不变）
function marketBeijingHM(now) {
  const p = marketLocalParts('Asia/Shanghai', now);
  return p.hh + ':' + p.mm;
}

// 验收同源钩子（verify_ui 的 MS-* 用它取期望值，避免断言写死文案）；
// 传 ISO 字符串即注入「假 now」—— DST 与时段边界回归靠它，别删。
window.__marketSession = function (iso) {
  try {
    const now = iso ? new Date(iso) : new Date();
    const st = marketStateOf(now);
    return { cn: st.cn, us: st.us, time: '北京时间 ' + marketBeijingHM(now) };
  } catch (e) { return null; }
};

function updateMarketStatus() {
  const stCn = document.getElementById('market-status-cn');
  const stUs = document.getElementById('market-status-us');
  const tm = document.getElementById('market-time');
  const dotCn = document.getElementById('market-dot-cn');
  const dotUs = document.getElementById('market-dot-us');
  if (!stCn || !stUs || !tm) return;
  let st = null, hhmm = '—:—';
  try {
    const now = new Date();
    st = marketStateOf(now);
    hhmm = marketBeijingHM(now);
  } catch (e) { /* 时区数据缺失（ICU 无 tz）：保留占位文案，不崩 */ }
  if (!st) return;
  stCn.textContent = st.cn.label;
  stUs.textContent = st.us.label;
  tm.textContent = '北京时间 ' + hhmm;
  if (dotCn) dotCn.classList.toggle('open', st.cn.open);
  if (dotUs) dotUs.classList.toggle('open', st.us.open);
}

// === 刷新 ===
function loadFailed(msg, boxId) {
  const box = document.getElementById(boxId);
  if (box) box.innerHTML = '<p class="empty">加载失败：' + escapeHtml(msg) + '</p>';
}

// 首页失败条（F2，2026-09-17 走查整改 P1-②/P2-⑤）：history 取数失败 ≠ 静默 ——
// **保留旧图渲染**（离线仍看旧数据的既有行为）+ 显式失败条 + 重试。
// ⚠️ 与宏观页 #mac-fail-bar 同构但**有意复制**（不抽共享函数/class，避免牵连宏观页 N-* 断言与 DOM 契约）。
function showHomeFailBar(show, msg) {
  const bar = document.getElementById('home-fail-bar');
  const m = document.getElementById('home-fail-msg');
  if (m && msg) m.textContent = '趋势数据获取失败 · ' + msg;
  if (bar) bar.classList.toggle('hidden', !show);
}

let refreshing = false;   // 防重入（刷新按钮 / 时间范围连点）

function setRefreshBusy(b) {
  refreshing = b;
  // 刷新期间转圈/禁用（P1-②：此前无任何 loading 反馈）；失败条上的重试一并禁用
  ['refresh-btn', 'home-retry'].forEach(function (id) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = b;
  });
}

// 趋势卡 loading 骨架（G4，2026-09-17 产线走查整改）：fetch 期间显示、结算即撤。
// 骨架在 #chart-main-wrap 内部绝对定位 ⇒ 不改容器高度（canvas 位图==显示尺寸断言不受影响）。
function showHomeChartSkel(show) {
  const sk = document.getElementById('home-chart-skel');
  if (sk) sk.classList.toggle('hidden', !show);
}

function refresh() {
  const rangeLabel = document.getElementById('range-label');
  if (rangeLabel) rangeLabel.textContent = state.days >= 365 ? '近 1 年' : '近 ' + state.days + ' 日';
  if (refreshing) return;
  setRefreshBusy(true);
  showHomeChartSkel(true);       // G4：loading 态（成功/失败结算时撤）
  fetch(buildQuery()).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);   // 非 2xx 直接判失败（500 的 HTML 体会抛 SyntaxError，报错指不到上游）
      return r.json();
    })
    .then(function (history) {
      state.history = history;
      renderMainChart();
      paintSparklines();
      showHomeFailBar(false);
    }, function (e) {
      // ⚠️ 失败 ≠ 静默（P1-②）：**保留旧图渲染**（离线仍看旧数据的既有行为）+ 显式失败条
      renderMainChart();
      showHomeFailBar(true, e && e.message ? e.message : '加载失败');
    })
    .then(function () {
      setRefreshBusy(false);
      showHomeChartSkel(false);   // G4：结算（无论成败）都撤骨架 —— 不得停留在 loading
    });

  fetch('/api/latest').then(function (r) { return r.json(); })
    .then(function (data) {
      state.latest = data;
      state.latestDate = data.date;
      updateTopbarDate(data.date);
      renderOverview();
      renderSector(data);
      renderRiskAppetite(data);
      renderMarketRelation(data);
      renderUsSectors(data);
      renderSectorAsOf();       // 两个板块的 as_of 都写完后才判定
      renderLede();
    })
    .catch(function (e) { loadFailed(e.message, 'overview-body'); });
}

// === 初始化 ===
document.addEventListener('DOMContentLoaded', function () {
  // 板块 tab 切换 → 重算「数据截至」标注（纯 CSS tab 没有切换事件，只能自己挂）
  ['sector-tab-cn', 'sector-tab-us'].forEach(function (id) {
    const r = document.getElementById(id);
    if (r) r.addEventListener('change', renderSectorAsOf);
  });
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
  // 移动端抽屉（F4，2026-09-17 走查整改 P2-④）：开 ⇒ 滚动锁定 + 焦点移入侧栏；关 ⇒ 焦点归还触发按钮
  const menuBtn = document.getElementById('menu-toggle');
  const drawerIsOpen = function () { return document.body.classList.contains('nav-open'); };
  const setDrawerOpen = function (open) {
    const was = drawerIsOpen();
    if (open === was) return;                       // 幂等：桌面端每次点击 main 都会调 close，不能抢焦点
    document.body.classList.toggle('nav-open', open);
    if (open) {
      const sb = document.getElementById('sidebar');
      const first = sb && sb.querySelector('a[href], button:not([disabled])');
      if (first) first.focus();                     // 焦点移入侧栏首个可聚焦项
    } else if (was && menuBtn) {
      menuBtn.focus();                              // 关闭后焦点归还触发按钮
    }
  };
  if (menuBtn) menuBtn.addEventListener('click', function () { setDrawerOpen(!drawerIsOpen()); });
  const navBackdrop = document.createElement('div');
  navBackdrop.className = 'nav-backdrop';
  document.body.appendChild(navBackdrop);
  navBackdrop.addEventListener('click', function () { setDrawerOpen(false); });
  const mainEl = document.getElementById('main');
  if (mainEl) mainEl.addEventListener('click', function () { setDrawerOpen(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && drawerIsOpen()) setDrawerOpen(false);
  });
  // 侧栏锚点导航 + active 态
  document.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
    item.addEventListener('click', function (e) {
      setDrawerOpen(false);
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
  // 首页失败条的重试（F2）：与刷新同一条路径
  const homeRetry = document.getElementById('home-retry');
  if (homeRetry) homeRetry.addEventListener('click', function () { refresh(); });
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
      renderMainChart();   // 三十四期：macro 晚到时补画 alt 组的黄金 COMEX 线
    })
    .catch(function (err) {
      console.error('[macro] fetch failed:', err);
      state.macro = { stocks: [] };
      renderOverview();
    });
});
