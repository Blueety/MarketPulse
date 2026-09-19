/* 事件时间线页（/timeline）逻辑 —— 2026-09-18（任务档 tasks/2026-09-18-event-timeline-page）。
 *
 * 数据源（只读，零落盘）：
 *   /api/timeline?days=&future_days=  → { as_of, window, stats, sources, past[], upcoming[] }
 *     每个 day：{ date, events[{kind,title,agency,source,time_et,status,note,news_*}],
 *                 market{gspc,ixic,sh,vix_chg}, forward{"1"|"3"|"5"|"10":{gspc,ixic,sh}} }
 *
 * 口径纪律（plan §4.3 / §7，前端不得"美化"掉）：
 *   - **`forward` 里的 `null` = 该窗口还没走满**（各标的休市/数据节奏不同 ⇒ 逐键判空）
 *     ⇒ 必须渲染「待走满」，**绝不允许显示成 0.00%**（TL-6 专门断言这一点）。
 *   - 事件与行情**并列展示**，不生成因果措辞、不打「利好/利空」标签（TL-7）。
 *   - 新闻篇数是检索口径 ⇒ 文案固定写「至少 N 篇」（每次检索上限 100）。
 *   - 事件类型/机构一律**中性色**；红绿只用于涨跌数字（与全站 `.mac .up/.down` 同口径）。
 *
 * 本文件刻意复制第 4 份 shell 行为（主题 / 移动端抽屉 / 市场状态）：与 app.js / macro.js /
 *   macro_cn.js 同口径 —— **改一处必须四处同改**（AGENTS.md：抽共享 shell.js 另开任务）。
 *   主题初始化必须与 timeline.html 的 head 内联脚本同源（pitfall「主题初始化分叉」）。
 */
(function () {
  "use strict";

  var DAY_LABELS = { gspc: "标普500", ixic: "纳斯达克", sh: "上证", vix_chg: "VIX" };
  var PRIMARY = "gspc";
  var WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  var state = { payload: null, days: 90, futureDays: 30, loading: false, error: null, lastDays: null };
  // 「加载更早」的档位（plan §5.2：默认近 90 天，可加载更早；到库内最早事件时按钮隐藏）
  var DAY_STEPS = [90, 365, 1200, 3650];

  function el(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // 涨跌方向 → 类名（与全站 .up/.down 同口径：up=绿、down=红，见 style.css）
  // ⚠️ 按**四舍五入后**的方向判色：|v| < 0.005 会被显示成「0.00%」，此时染绿/染红会读成"有方向"
  //    （实测 2026-07-02 的 +0.0037% 曾渲染成绿色 `+0.00%`）。
  function cls(v) {
    if (v == null || Math.abs(v) < 0.005) return "flat";
    return v > 0 ? "up" : "down";
  }

  // 百分比：null → 占位（调用方传「待走满」则用「待走满」）
  function fmtPct(v, dash) {
    if (v == null) return dash || "—";
    var s = Math.abs(v).toFixed(2) + "%";
    if (Math.abs(v) < 0.005) return s;          // 四舍五入到 0 ⇒ 不写符号（中性）
    return (v > 0 ? "+" : "-") + s;
  }

  // ---------------------------------------------------------------- 结果值层（2026-09-19）
  // 事件行的「实际 / 预期 / 前值 / 变动 / 偏离预期」。三条硬约束（plan D2.1 / D2a / D4a）：
  //   ① **`unit` 为 null 时不加任何单位后缀**（不写 `%` / `点` / `千人`）——源数据如此（实测
  //      美国 CPI 的 actual 是指数水平 334.98、非农是 162 千人，两者 `unit` 连键都没有）；
  //      `unit == "%"` 时固定两位小数 + `%`（与 plan §8.1 的目标文案 `实际 4.00%` 一致）。
  //   ② **`null` 与 `0` 必须区分**：`0` 是真实值（实测 2026-07-15 PPI 的 forecast=0），
  //      只有 `null` 才算"没有这一项"⇒ 整项不渲染，**绝不把 null 当 0 参与减法**。
  //   ③ 两个派生数字都是**纯减法**、不引入模型；措辞只准「高于 / 低于 / 符合预期」这类客观比较，
  //      **禁止**「利好 / 利空 / 超预期将推动」类因果措辞（TL-7 复跑必须仍绿）。
  var MQ_LITE = (typeof window !== "undefined" && window.matchMedia)
    ? window.matchMedia("(max-width: 767px)") : null;   // D-4a 断点：767px 内侧（768 仍走完整三项）
  function valLite() { return !!(MQ_LITE && MQ_LITE.matches); }

  // 数值：最多两位小数、去掉多余尾零（不做位数补零；`unit == "%"` 走固定两位）
  function trim2(v) { return String(Math.round(Number(v) * 100) / 100); }
  function signedTrim(v) { return (v > 0 ? "+" : v < 0 ? "-" : "") + trim2(Math.abs(v)); }
  function fmtNum(v, unit) {
    if (v == null) return "";
    return unit === "%" ? Number(v).toFixed(2) + "%" : trim2(v);
  }

  // 变动 = actual − previous。FOMC 专项按百分点折 bp（plan D2.1④）；
  // ⚠️ `pp` 后缀**只在 `unit == "%"` 时加**：unit 缺失的指标（CPI 指数 / 非农）其差值是水平差、
  //    不是百分点，加 `pp` 就是"猜单位"（违反硬约束 ①）。
  function deltaText(kind, d, unit) {
    if (kind === "FOMC") {
      var bp = Math.round(d * 100);
      if (bp === 0) return "维持不变";
      return (bp > 0 ? "加息 " : "降息 ") + Math.abs(bp) + "bp";
    }
    return "变动 " + signedTrim(d) + (unit === "%" ? "pp" : "");
  }

  // 偏离预期 = actual − forecast（纯减法；措辞只用客观比较）
  function missText(d) {
    var r = Math.round(d * 100) / 100;
    if (r === 0) return "符合预期";
    return (r > 0 ? "高于预期 " : "低于预期 ") + signedTrim(r);
  }

  // 值区条目（有序）。`pending` = 该行属「未来 / 今天」段；`lite` = 移动端精简态（D-4a）。
  function valueItems(ev, pending, lite) {
    var unit = (ev.unit == null ? null : String(ev.unit));
    var a = ev.actual, f = ev.forecast, p = ev.previous;
    var items = [];
    if (a == null) {
      // 未公布 / 无实际值：只可能显示 预期 与 前值（逐项裁剪，缺操作数就整项不出）
      if (pending) {
        // ⚠️ 未来段**不得留空白行为**（plan 硬约束 ②）：必有「待公布」或「预期 X（待公布）」
        items.push(f != null ? "预期 " + fmtNum(f, unit) + "（待公布）" : "待公布");
        if (p != null) items.push("前值 " + fmtNum(p, unit));
        return items;
      }
      if (f != null) items.push("预期 " + fmtNum(f, unit));
      if (p != null) items.push("前值 " + fmtNum(p, unit));
      return items;
    }
    items.push("实际 " + fmtNum(a, unit));
    if (!lite) {
      if (f != null) items.push("预期 " + fmtNum(f, unit));
      if (p != null) items.push("前值 " + fmtNum(p, unit));
      if (p != null) items.push(deltaText(ev.kind, a - p, unit));
      if (f != null) items.push(missText(a - f));
      return items;
    }
    // D-4a 两态：≤767px 只留「实际 X · 变动 Y」（375 档行尾仅剩 66px，完整三项必然折行）
    if (p != null) items.push(deltaText(ev.kind, a - p, unit));
    return items;
  }

  // 值区 HTML：**单份 DOM**（按断点只渲染一组文案）——不用"两份 + CSS 隐藏"，
  // 否则 DOM 里会出现两份「实际」值，让三方对账（EV-2）与「同日不重复」类断言数出双份。
  function valueHtml(ev, pending) {
    var items = valueItems(ev, pending, valLite());
    if (!items.length) return "";
    var src = ev.value_source
      ? ' title="结果值来源：' + escapeHtml(ev.value_source) + "（" + escapeHtml(ev.value_title || "") + '）"'
      : "";
    return '<span class="tl-val" data-val-mode="' + (valLite() ? "lite" : "full") + '"' + src + ">" +
           escapeHtml(items.join(" ｜ ")) + "</span>";
  }

  // ⚠️ 不用 `new Date("YYYY-MM-DD")`（本地时区偏移，pitfall 专条）：用 Date.UTC 纯函数拿星期
  function weekdayZh(dateStr) {
    var p = String(dateStr).split("-");
    if (p.length !== 3) return "";
    return WEEKDAYS[new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).getUTCDay()] || "";
  }

  function dayDiff(a, b) {
    var pa = String(a).split("-"), pb = String(b).split("-");
    if (pa.length !== 3 || pb.length !== 3) return null;
    var ta = Date.UTC(+pa[0], +pa[1] - 1, +pa[2]);
    var tb = Date.UTC(+pb[0], +pb[1] - 1, +pb[2]);
    return Math.round((ta - tb) / 86400000);
  }

  function relLabel(dateStr, asOf) {
    var d = dayDiff(dateStr, asOf);
    if (d == null) return "";
    if (d === 0) return "今天";
    if (d > 0) return d + " 天后";
    return "已过 " + Math.abs(d) + " 天";
  }

  // 窗口文案：< 365 天按天，否则按年（plan §5.2 的「近 90 天 / 可加载更早」）
  function windowLabel(days) {
    if (!days) return "近 —";
    if (days < 365) return "近 " + days + " 天";
    var y = (days / 365);
    return "近 " + (Math.abs(y - Math.round(y)) < 0.05 ? Math.round(y) : y.toFixed(1)) + " 年";
  }

  // ---------------------------------------------------------------- shell（第 4 份副本）

  function getTheme() {
    try { return localStorage.getItem("mp-theme") || "light"; } catch (e) { return "light"; }
  }

  // ⚠️ 必须在 init 阶段就把主题落到 <html> 上（timeline.html 的 head 内联脚本是"首屏前"的同一件事，
  //    这里负责"运行时切换 + 进入页面后的再次确认"）；改这里必须同步 head 内联脚本与另三份副本。
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme || getTheme());
  }
  applyTheme();

  // ⚠️ 2026-09-16（market-session-status）：两行两市场 + 逐市场时段判定。
  //    本段在 app.js / macro.js / macro_cn.js / timeline.js 各有一份**逐字副本** —— 改一处必须四处同改。
  //    点色语义：`open` = 「该市场此刻在交易」；判定一律用**各市场本地时钟**（不得出现 21:30 魔数）。
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

  // 验收同源钩子（verify_ui MS-*）；传 ISO 字符串即注入假 now
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
        applyTheme(next);
        render();                          // 本页无 canvas，重渲染即可（颜色全走 token）
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
    if (refreshBtn) refreshBtn.addEventListener("click", function () { load(true); });
    var moreBtn = el("tl-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", function () {
        var i = DAY_STEPS.indexOf(state.days);
        state.days = DAY_STEPS[Math.min(i + 1, DAY_STEPS.length - 1)];
        load(false);
      });
    }
    // D-4a 两态断点：跨过 767px 时**重渲染**（本页无 canvas，与主题切换同一模式）。
    // 不要用"两份 DOM + CSS 隐藏"实现两态 —— 会让 DOM 里出现两份「实际」值（EV-2 三方对账数出双份）。
    if (MQ_LITE) {
      var onMq = function () { render(); };
      if (MQ_LITE.addEventListener) MQ_LITE.addEventListener("change", onMq);
      else if (MQ_LITE.addListener) MQ_LITE.addListener(onMq);      // 旧内核兜底
    }
    updateMarketStatus();
    setInterval(updateMarketStatus, 60000);
  }

  // ---------------------------------------------------------------- 取数

  function getJSON(url) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 20000) : null;
    return fetch(url, ctrl ? { signal: ctrl.signal } : undefined)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        if (timer) clearTimeout(timer);
        return d;
      });
  }

  function load(force) {
    if (state.loading) return;
    state.loading = true;
    var url = "/api/timeline?days=" + state.days + "&future_days=" + state.futureDays +
              (force ? "&_=" + Date.now() : "");
    getJSON(url)
      .then(function (d) {
        state.payload = d;
        state.error = null;
        render();
      })
      .catch(function (e) {
        state.error = String(e && e.message ? e.message : e);
        console.warn("[timeline] 取数失败：" + state.error);
        render();
      })
      .then(function () { state.loading = false; });
  }

  // ---------------------------------------------------------------- 渲染

  function metric(label, value, dash) {
    var v = value == null ? dash || "—" : fmtPct(value, dash);
    return '<span class="tl-metric"><span class="tl-label">' + escapeHtml(label) + "</span> " +
           '<b class="' + cls(value) + '">' + escapeHtml(v) + "</b></span>";
  }

  function eventHtml(ev, pending) {
    // 事件名：优先用**中文**（`title_zh`，服务端按"类型 + 数据期 + 估计阶段"模板生成）；
    // 英文原文（`title`）挂到 `data-title-en` 与 `title=`（悬停可见）——**中文化不丢原文**。
    var zh = ev.title_zh || ev.title || "";
    var en = ev.title || "";
    var bits = ['<li class="tl-ev" data-kind="' + escapeHtml(ev.kind) + '">'];
    bits.push('<span class="tl-kind">' + escapeHtml(ev.kind) + "</span>");
    if (ev.time_et) bits.push('<span class="tl-time">' + escapeHtml(ev.time_et) + " ET</span>");
    bits.push('<span class="tl-title" data-title-en="' + escapeHtml(en) + '" title="' +
              escapeHtml(en) + '">' + escapeHtml(zh) + "</span>");
    // 结果值层（2026-09-19）：接在事件名之后、机构标签之前（行内追加 —— 实测 1920/1440/1280/768
    // 四档行高保持 19.94 不变；仅 375 档会折行 +21.94，那里本就走精简态）
    bits.push(valueHtml(ev, pending));
    if (ev.status === "tentative") bits.push('<span class="tl-status">暂定</span>');
    if (ev.note) bits.push('<span class="tl-ev-note">' + escapeHtml(ev.note) + "</span>");
    if (ev.agency) bits.push('<span class="tl-agency">' + escapeHtml(ev.agency) + "</span>");
    bits.push("</li>");
    return bits.join("");
  }

  function dayHtml(day, asOf) {
    var isFuture = !!(asOf && day.date >= asOf);   // 当日也算"窗口未开始"（含今天）
    var out = ['<article class="tl-day" data-date="' + escapeHtml(day.date) + '">'];
    out.push('<div class="tl-day-date"><span class="tl-date">' + escapeHtml(day.date.slice(5)) + "</span>" +
             '<span class="tl-week">' + escapeHtml(weekdayZh(day.date)) + "</span>" +
             '<span class="tl-rel">' + escapeHtml(relLabel(day.date, asOf)) + "</span></div>");
    out.push('<div class="tl-day-main">');
    out.push('<ul class="tl-events">' +
             day.events.map(function (e) { return eventHtml(e, isFuture); }).join("") + "</ul>");

    var mk = day.market || {};
    var mparts = ["gspc", "ixic", "sh", "vix_chg"]
      .filter(function (k) { return mk[k] != null; })
      .map(function (k) { return metric(DAY_LABELS[k], mk[k]); });
    if (mparts.length) out.push('<div class="tl-metrics">' + mparts.join("") + "</div>");

    // 事件后窗口：**未来事件不显示**（窗口还没开始，"待走满"会读成"数据缺"）；
    // 已发生事件才显示，且 null 一律渲染「待走满」（TL-6：绝不允许显示成 0.00%）。
    if (!isFuture) {
      var fw = day.forward || {};
      var fparts = ["1", "3", "5", "10"].map(function (h) {
        var per = fw[h] || {};
        return metric("+" + h + "日", per[PRIMARY], "待走满");
      });
      var tips = ["1", "3", "5", "10"].map(function (h) {
        var per = fw[h] || {};
        return "+" + h + "日 " + ["gspc", "ixic", "sh"].map(function (k) {
          return DAY_LABELS[k] + " " + (per[k] == null ? "待走满" : fmtPct(per[k]));
        }).join(" / ");
      });
      out.push('<div class="tl-metrics tl-fwd" title="' + escapeHtml(tips.join(" | ")) + '">' +
               '<span class="tl-metric"><span class="tl-label">事件后</span></span>' +
               fparts.join("") + "</div>");
    }

    var withNews = day.events.filter(function (e) { return e.news_title; });
    withNews.forEach(function (e) {
      var n = e.news_count == null ? "" : '<span class="tl-news-n">至少 ' + e.news_count + " 篇</span>";
      var link = e.news_link
        ? '<a href="' + escapeHtml(e.news_link) + '" target="_blank" rel="noopener noreferrer">' +
          escapeHtml(e.news_title) + "</a>"
        : escapeHtml(e.news_title);
      out.push('<div class="tl-news">' + n + link + "</div>");
    });
    out.push("</div></article>");
    return out.join("");
  }

  function fillList(id, days_, emptyText) {
    var box = el(id);
    if (!box) return days_.length;
    box.innerHTML = days_.length
      ? days_.map(function (d) { return dayHtml(d, (state.payload || {}).as_of || ""); }).join("")
      : '<p class="tl-empty">' + escapeHtml(emptyText) + "</p>";
    return days_.length;
  }

  function render() {
    var p = state.payload;
    var asof = el("tl-asof");
    if (asof) asof.textContent = p ? (p.as_of || "—") : "—";

    if (!p) {
      ["tl-upcoming-body", "tl-past-body"].forEach(function (id) {
        var box = el(id);
        if (box) {
          box.innerHTML = '<p class="tl-empty">' +
            escapeHtml(state.error ? "加载失败：" + state.error : "加载中…") + "</p>";
        }
      });
      return;
    }

    var win = p.window || {};
    var nUp = fillList("tl-upcoming-body", p.upcoming || [],
                       "未来 " + (win.future_days || 0) + " 天内暂无排定的发布日程");
    var nPast = fillList("tl-past-body", p.past || [],
                         "近 " + (win.past_days || 0) + " 天内没有事件（可先跑 sync_econ_calendar）");

    var hintUp = el("tl-upcoming-hint"), hintPast = el("tl-past-hint");
    if (hintUp) hintUp.textContent = "未来 " + win.future_days + " 天 · " + (p.stats || {}).upcoming_events + " 项";
    if (hintPast) hintPast.textContent = windowLabel(win.past_days) + " · " + (p.stats || {}).past_events + " 项";

    var scope = el("tl-scope");
    var rng = p.db_range || [];
    var rangeTxt = rng[0] ? "（" + rng[0] + " ~ " + rng[1] + "）" : "";
    if (scope) {
      var st = p.stats || {};
      scope.textContent = "库内事件 " + st.db_events + " 条" + rangeTxt + " · 本轮窗口 " + nUp + " / " + nPast +
                          " 天 · 行情覆盖 " + st.covered_days + " 个交易日";
    }

    // 「加载更早」：还有更早的数据才显示（旧端日期 > 库内最早日期，或档位没走到底）
    var more = el("tl-more");
    if (more) {
      var oldest = (p.past && p.past.length) ? p.past[p.past.length - 1].date : null;
      var canMore = p.past && p.past.length &&
        (state.days < DAY_STEPS[DAY_STEPS.length - 1] &&
         (!rng[0] || !oldest || oldest > rng[0]));
      more.hidden = !canMore;
      more.textContent = "加载更早（" + windowLabel(DAY_STEPS[Math.min(DAY_STEPS.indexOf(state.days) + 1,
                                                                    DAY_STEPS.length - 1)]) + "）";
    }

    var src = el("tl-src");
    if (src) {
      src.innerHTML = (p.sources || []).map(function (s) {
        return "<li>" + escapeHtml(s.label) + "：<span>" + escapeHtml(s.note) + "</span> " +
               '<a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener noreferrer">来源</a></li>';
      }).join("");
    }

    var fail = el("tl-fail");
    if (fail) {
      var f = p.failed || [];
      fail.hidden = !f.length;
      fail.textContent = f.length ? "本次同步有部分源/条目失败（已保留既有数据）：" + f.slice(0, 6).join("、") : "";
    }
  }

  bindShell();
  load(false);
})();
