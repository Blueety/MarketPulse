/* 阈值回测页（/backtest）逻辑 —— 2026-09-20（任务档 tasks/2026-09-20-backtest-ui/）。
 *
 * 数据源（只读，零落盘）：`/api/backtest`
 *   → { as_of, window{start,end}, stats{rows,effective_trading_days,triggers}, elapsed_ms,
 *       threshold_config{dynamic,lookback_days,k_factor,fallback[{symbol,threshold}]},
 *       symbols[{symbol,threshold,effective_points,alerts,annualized,levels{WARN,ALERT},
 *                threshold_modes{dynamic,fixed},effective_trigger_rate,insufficient,
 *                forward{"1"|"3"|"5"|"10":{avg,win,n}}}],
 *       methods[7 条口径原文], empty_reason }
 *
 * 口径纪律（前端不得"美化"掉）：
 *   - 🔴 **后效为负是正常语义**：「告警后下跌」恰恰说明告警有效 —— 数字按**方向**染色
 *     （涨/跌），**不得**把负值渲染成"失败/危险"色，也不得加"❌"之类判断标记。
 *   - `n` 是**样本数**：窗口不足的样本不计入（`n` 与均值一起展示，不得藏起来）。
 *   - `effective_trigger_rate` 为 `null` ⇒ 显示「—」（**不是 0%**）。
 *   - 口径说明一律取 `methods[]`（服务端与 md 报告**同一来源**），前端**不得改写措辞**
 *     （尤其「胜率 = 方向延续占比，不是预测准确率」）。
 *   - ⚠️ **涨跌色沿用全站既有口径**（`.up = var(--green)` / `.down = var(--red)`，见 .mac/.tl）：
 *     本页 plan 里写的「红涨绿跌」与既有代码**冲突**，为保持一致**未采纳**（见 journal §4.1）；
 *     若要改，是**全站跨三页**的决定，不是本页。
 *
 * 本文件刻意复制**第 5 份** shell 行为（主题 / 移动端抽屉 / 市场状态）：与 app.js / macro.js /
 *   macro_cn.js / timeline.js 同口径 —— **改一处必须五处同改**（AGENTS.md：抽共享 shell.js 另开任务）。
 *   主题初始化必须与 backtest.html 的 head 内联脚本同源（pitfall「主题初始化分叉」）。
 */
(function () {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // 涨跌方向 → 类名（与全站 .up/.down 同口径，见 style.css 的 .mac/.tl/.bt 三处）
  // ⚠️ 按**四舍五入后**的方向判色：|v| < 0.005 会被显示成「0.00%」，此时染色会读成"有方向"。
  function cls(v) {
    if (v == null || Math.abs(v) < 0.005) return "flat";
    return v > 0 ? "up" : "down";
  }

  // 百分比：null → 「—」；四舍五入到 0 时不写符号（中性）
  function fmtPct(v, digits) {
    if (v == null) return "—";
    var d = digits == null ? 2 : digits;
    var s = Math.abs(v).toFixed(d) + "%";
    if (Math.abs(v) < 0.005) return s;
    return (v > 0 ? "+" : "-") + s;
  }

  // 比率（0~1）→ 百分比字符串；null → 「—」（**绝不显示成 0%**）
  function fmtRate(v, digits) {
    if (v == null) return "—";
    return (v * 100).toFixed(digits == null ? 1 : digits) + "%";
  }

  function fmtNum(v, digits) {
    if (v == null) return "—";
    return Number(v).toFixed(digits == null ? 2 : digits);
  }

  // ---------------------------------------------------------------- shell（第 5 份副本）

  function getTheme() {
    try { return localStorage.getItem("mp-theme") || "light"; } catch (e) { return "light"; }
  }

  // ⚠️ 必须在 init 阶段就把主题落到 <html> 上（backtest.html 的 head 内联脚本是"首屏前"的同一件事，
  //    这里负责"运行时切换 + 进入页面后的再次确认"）；改这里必须同步 head 内联脚本与另四份副本。
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme || getTheme());
  }
  applyTheme();

  // ⚠️ 2026-09-16（market-session-status）：两行两市场 + 逐市场时段判定。
  //    本段在 app.js / macro.js / macro_cn.js / timeline.js / backtest.js 各有一份**逐字副本**
  //    —— 改一处必须五处同改。
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

  var state = { payload: null, loading: false, error: null };

  function load(force) {
    if (state.loading) return;
    state.loading = true;
    // 🔴 不用 `?refresh=`：该端点**本来就不缓存**（见 web/app.py 的 docstring），
    //    带时间戳只是为了绕开浏览器自身的 GET 缓存（改阈值后刷新必须看到新数字）。
    var url = "/api/backtest" + (force ? "?_=" + Date.now() : "");
    getJSON(url)
      .then(function (d) {
        state.payload = d;
        state.error = null;
        render();
      })
      .catch(function (e) {
        state.error = String(e && e.message ? e.message : e);
        console.warn("[backtest] 取数失败：" + state.error);
        render();
      })
      .then(function () { state.loading = false; });
  }

  // ---------------------------------------------------------------- 渲染

  function renderStats(p) {
    var st = p.stats || {};
    el("bt-effdays").textContent = st.effective_trading_days == null ? "—" : String(st.effective_trading_days);
    el("bt-triggers").textContent = st.triggers == null ? "—" : String(st.triggers);
    el("bt-nsymbols").textContent = String((p.symbols || []).length);
    el("bt-elapsed").textContent = p.elapsed_ms == null ? "—" : (p.elapsed_ms / 1000).toFixed(2) + "s";
    el("bt-asof").textContent = p.as_of || "—";
    // BUG-008(b)（2026-09-24）：顶栏 `#topbar-date` 原先在本页**无人写入** ⇒ 恒为「—」。
    // 数据日取 `/api/backtest` 的 `as_of`（库内最新行情日）；无数据（空态 / as_of 缺失）保持「—」。
    var tb = el("topbar-date");
    if (tb) tb.textContent = p.as_of || "—";
    var w = p.window || {};
    el("bt-window").textContent = (w.start && w.end)
      ? "数据窗口 " + w.start + " ~ " + w.end + "（共 " + (st.rows || 0) + " 行）"
      : "数据窗口 —";
  }

  function renderCfg(p) {
    var c = p.threshold_config || {};
    var mode = c.dynamic ? "动态阈值：启用" : "动态阈值：关闭（全部走固定阈值）";
    el("bt-cfg-mode").textContent = mode;
    el("bt-cfg-line").textContent = c.dynamic
      ? "回看窗口 " + c.lookback_days + " 个交易日 · k 因子 " + c.k_factor +
        " · 样本不足 / 零方差 / 计算值 ≤ 0 时回退下表固定阈值"
      : "回退阈值即实际生效阈值（下表）";
    var rows = (c.fallback || []).map(function (f) {
      return '<span class="bt-cfg-chip">' + escapeHtml(f.symbol) + " " + fmtNum(f.threshold, 2) + "%</span>";
    });
    el("bt-cfg-table").innerHTML = rows.length ? rows.join("") : '<span class="bt-empty">—</span>';
  }

  function forwardCell(f) {
    var o = f || {};
    var n = o.n == null ? 0 : o.n;
    if (o.avg == null) return '<td class="bt-fwd">—<span class="bt-n">n=0</span></td>';
    return '<td class="bt-fwd ' + cls(o.avg) + '">' + fmtPct(o.avg) +
      '<span class="bt-n">n=' + n + "</span></td>";
  }

  function renderOverview(p) {
    var syms = p.symbols || [];
    var wrap = el("bt-table-wrap");
    if (!syms.length) {
      wrap.innerHTML = '<p class="bt-empty">' + escapeHtml(p.empty_reason || "暂无回测结果。") + "</p>";
      return;
    }
    var head = "<tr><th>标的</th><th>回退阈值</th><th>告警次数</th><th>年化(次/年)</th>" +
      "<th>有效触发率</th><th>1 日后效</th><th>3 日</th><th>5 日</th><th>10 日</th></tr>";
    var body = syms.map(function (s) {
      var fw = s.forward || {};
      var etr = s.insufficient ? "样本不足" : fmtRate(s.effective_trigger_rate);
      return "<tr>" +
        "<td class=\"bt-sym\">" + escapeHtml(s.symbol) + "</td>" +
        "<td>" + fmtNum(s.threshold, 2) + "%</td>" +
        "<td>" + (s.alerts == null ? "—" : s.alerts) + "</td>" +
        "<td>" + fmtNum(s.annualized, 2) + "</td>" +
        "<td>" + etr + "</td>" +
        forwardCell(fw["1"]) + forwardCell(fw["3"]) + forwardCell(fw["5"]) + forwardCell(fw["10"]) +
        "</tr>";
    }).join("");
    wrap.innerHTML = '<table class="bt-table"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  }

  function renderDetails(p) {
    var syms = p.symbols || [];
    var box = el("bt-details-body");
    if (!syms.length) {
      box.innerHTML = '<p class="bt-empty">' + escapeHtml(p.empty_reason || "暂无回测结果。") + "</p>";
      return;
    }
    box.innerHTML = syms.map(function (s) {
      var fw = s.forward || {};
      var rows = ["1", "3", "5", "10"].map(function (h) {
        var o = fw[h] || {};
        return "<tr><td>" + h + " 日</td><td class=\"" + cls(o.avg) + "\">" + fmtPct(o.avg) +
          "</td><td>" + fmtRate(o.win) + "</td><td>" + (o.n == null ? 0 : o.n) + "</td></tr>";
      }).join("");
      var lm = s.levels || {}, tm = s.threshold_modes || {};
      return '<details class="bt-detail" id="bt-detail-' + escapeHtml(s.symbol) + '">' +
        "<summary><span class=\"bt-sym\">" + escapeHtml(s.symbol) + "</span>" +
        "<span class=\"bt-sum\">告警 " + s.alerts + " · 年化 " + fmtNum(s.annualized, 2) +
        " · 有效触发率 " + (s.insufficient ? "样本不足" : fmtRate(s.effective_trigger_rate)) + "</span></summary>" +
        '<div class="bt-detail-body">' +
        "<p class=\"bt-kv\">回退阈值 <b>" + fmtNum(s.threshold, 2) + "%</b>" +
        " · 有效点 <b>" + s.effective_points + "</b>" +
        " · 阈值模式 dynamic <b>" + (tm.dynamic || 0) + "</b> / fixed <b>" + (tm.fixed || 0) + "</b>" +
        " · WARN <b>" + (lm.WARN || 0) + "</b> / ALERT <b>" + (lm.ALERT || 0) + "</b></p>" +
        (s.insufficient
          ? '<p class="bt-kv">样本不足（有效点 &lt; 30），后效 / 胜率 / 有效触发率暂不统计，避免小样本误导。</p>'
          : '<table class="bt-table bt-table-sm"><thead><tr><th>窗口</th><th>平均收益</th><th>胜率</th><th>样本数 n</th></tr></thead><tbody>' +
            rows + "</tbody></table>") +
        "</div></details>";
    }).join("");
  }

  function renderMethods(p) {
    var ul = el("bt-methods");
    var items = p.methods || [];
    ul.innerHTML = items.map(function (t) {
      // 服务端给的是 md 列表行（以 "- " 开头）⇒ 去掉前缀直接作为 <li>，**不改写其余措辞**
      var s = String(t).replace(/^-\s*/, "");
      return "<li>" + escapeHtml(s).replace(/`([^`]+)`/g, "<code>$1</code>") + "</li>";
    }).join("");
  }

  function render() {
    var p = state.payload;
    var fail = el("bt-fail");
    if (!p) {
      if (fail && state.error) {
        fail.hidden = false;
        fail.textContent = "回测数据加载失败：" + state.error;
      }
      return;
    }
    renderStats(p);
    renderCfg(p);
    renderOverview(p);
    renderDetails(p);
    renderMethods(p);
    if (fail) {
      if (state.error) {
        fail.hidden = false;
        fail.textContent = "回测数据加载失败：" + state.error;
      } else if (p.empty_reason) {
        fail.hidden = false;
        fail.textContent = p.empty_reason;
      } else {
        fail.hidden = true;
        fail.textContent = "";
      }
    }
  }

  bindShell();
  load(false);
})();
