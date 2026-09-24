/* 设置页（/settings）逻辑 —— 2026-09-20（任务档 tasks/2026-09-20-settings-page）。
 *
 * 数据源：`/api/settings`（GET：生效值 + env 覆盖 + schema；POST：白名单内的部分更新）。
 *
 * 口径纪律（plan §0 / R8 / R4，前端不得"美化"掉）：
 *   - 动态阈值三参数（开关/回看/k 因子）**置顶**：实测当前触发判定 100% 走动态模式，
 *     固定阈值只是回退基准 —— 不突出它，用户改了半天等于改了个寂寞。
 *   - 被 `ALERT_THRESHOLD_*` 等 env 覆盖的键：**显式标注「被 env 覆盖，本页修改不生效」**，
 *     不隐藏（plan R4：env > config 是既有优先级链，UI 必须服从并如实展示）。
 *   - Railway 上只读：保存按钮禁用并说明原因（写入即丢）。
 *
 * 本文件刻意复制**第 6 份** shell 行为（主题 / 抽屉 / 市场状态）：与 app.js / macro.js /
 *   macro_cn.js / timeline.js / backtest.js 同口径 —— **改一处必须六处同改**。
 *   主题初始化必须与 settings.html 的 head 内联脚本同源（pitfall「主题初始化分叉」）。
 */
(function () {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------------------------------------------------------- shell（第 6 份副本）

  function getTheme() {
    try { return localStorage.getItem("mp-theme") || "light"; } catch (e) { return "light"; }
  }

  // ⚠️ 改这里必须同步 settings.html 的 head 内联脚本与另五份副本。
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme || getTheme());
  }
  applyTheme();

  // ⚠️ 本段在 app.js / macro.js / macro_cn.js / timeline.js / backtest.js / settings.js 各有一份**逐字副本**
  //    —— 改一处必须六处同改。
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
    // BUG-008(a)（2026-09-24）：顶栏「刷新数据」原本是**死按钮** —— settings.js 是 6 份 shell 副本里
    //   唯一没绑定的（另 5 页都是 `load(true)`），点击 0 请求、用户以为在刷新。
    //   本页语义 = 重新拉 `/api/settings`（生效值 + env 覆盖 + schema），即重跑 `load()`
    //   （本页无趋势图缓存，无需 force 参数）；绑定位置与另 5 页一致，都放在 `bindShell`。
    var refreshBtn = el("refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", function () { load(); });
    // BUG-008(b)：本页**不写** `#topbar-date` —— 设置页展示的是配置生效值，没有「数据日」可取，
    //   凭空填一个日期等于造假（口径：有数据的页面写数据日，没有的保持「—」）。
    updateMarketStatus();
    setInterval(updateMarketStatus, 60000);
  }

  // ---------------------------------------------------------------- 业务

  var state = { values: {}, envOver: {}, readonly: false, stocks: [] };

  function getJSON(url) { return fetch(url).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }); }

  function postJSON(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body) }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
    });
  }

  // 简单输入控件（白名单键 → 输入框）
  var TEXT_KEYS = [
    "alert.k_factor", "alert.lookback_days",
    "alert.vix", "alert.vxn", "alert.move", "alert.gspc", "alert.ixic", "alert.sh", "alert.sz", "alert.cyb",
    "analysis.vix.peaceful", "analysis.vix.panic", "analysis.move.normal", "analysis.move.tight",
    "watchlist.corr_high_threshold"
  ];
  var BOOL_KEYS = ["alert.dynamic"];

  function fieldHtml(key, label, note) {
    var id = "st-f-" + key.replace(/\./g, "-");
    var envMark = state.envOver[key]
      ? ' <span class="st-envmark">被 env 覆盖（' + escapeHtml(state.envOver[key]) + '）—— 本页修改不生效</span>'
      : "";
    return '<div class="st-row"><label class="st-label" for="' + id + '">' + escapeHtml(label) + envMark +
      '</label><input class="st-input" id="' + id + '" data-key="' + key + '" value="' +
      escapeHtml(state.values[key] == null ? "" : state.values[key]) + '">' +
      (note ? '<span class="st-note">' + escapeHtml(note) + "</span>" : "") + "</div>";
  }

  function render() {
    el("st-alert-dynamic").value = state.values["alert.dynamic"] ? "true" : "false";
    el("st-alert-lookback_days").value = state.values["alert.lookback_days"];
    el("st-alert-k_factor").value = state.values["alert.k_factor"];
    el("st-readonly-note").textContent = state.readonly
      ? "🔒 " + (state.readonlyReason || "当前环境只读。") : "";

    // 各标的阈值（动态模式下是回退基准，如实标注）
    var symKeys = ["alert.vix", "alert.vxn", "alert.move", "alert.gspc", "alert.ixic", "alert.sh", "alert.sz", "alert.cyb"];
    el("st-alert-grid").innerHTML = symKeys.map(function (k) {
      return fieldHtml(k, k.replace("alert.", "").toUpperCase());
    }).join("");

    // 状态区间
    el("st-status-grid").innerHTML =
      fieldHtml("analysis.vix.peaceful", "VIX 平静线") +
      fieldHtml("analysis.vix.panic", "VIX 恐慌线") +
      fieldHtml("analysis.move.normal", "MOVE 正常线") +
      fieldHtml("analysis.move.tight", "MOVE 紧张线");

    // 自选相关性阈值
    el("st-wl-corr").innerHTML = fieldHtml("watchlist.corr_high_threshold", "相关性高阈值（0~1）");

    renderStocks();

    if (state.readonly) {
      var save = el("st-save");
      save.disabled = true;
      save.textContent = "只读（线上环境不可保存）";
    }
  }

  function renderStocks() {
    var box = el("st-wl-rows");
    if (!state.stocks.length) {
      box.innerHTML = '<p class="st-empty">暂无自选，点「+ 加一行」。</p>';
      return;
    }
    box.innerHTML = state.stocks.map(function (s, i) {
      return '<div class="st-row st-wl-row">' +
        '<input class="st-input" data-wl="symbol" data-i="' + i + '" placeholder="symbol（如 600519 / AAPL）" value="' + escapeHtml(s.symbol) + '">' +
        '<input class="st-input" data-wl="label" data-i="' + i + '" placeholder="名称" value="' + escapeHtml(s.label) + '">' +
        '<button type="button" class="st-btn st-btn-del" data-del="' + i + '" title="删除该行">✕</button></div>';
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("[data-del]"), function (b) {
      b.addEventListener("click", function () {
        state.stocks.splice(Number(b.getAttribute("data-del")), 1);
        renderStocks();
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll("[data-wl]"), function (inp) {
      inp.addEventListener("change", function () {
        var i = Number(inp.getAttribute("data-i")), k = inp.getAttribute("data-wl");
        if (state.stocks[i]) state.stocks[i][k] = inp.value;
      });
    });
  }

  function collect() {
    var patch = {};
    TEXT_KEYS.forEach(function (k) {
      var inp = el("st-f-" + k.replace(/\./g, "-"));
      if (inp) patch[k] = inp.value;
    });
    BOOL_KEYS.forEach(function (k) { patch[k] = el(k ? "st-" + k.replace(/\./g, "-") : "") ? el("st-" + k.replace(/\./g, "-")).value : "true"; });
    // watchlist.stocks：从行里收（空行剔除，交给后端校验报错）
    var rows = [];
    state.stocks.forEach(function (s) {
      if (String(s.symbol || "").trim() || String(s.label || "").trim()) {
        var item = { symbol: s.symbol, label: s.label };
        var c = (s.cost == null) ? "" : String(s.cost).trim();
        if (c !== "") item.cost = Number(c);      // 空 ⇒ 不带 cost 键 = 清除
        rows.push(item);
      }
    });
    patch["watchlist.stocks"] = rows;
    return patch;
  }

  function save() {
    var msg = el("st-msg"), fail = el("st-fail");
    fail.hidden = true;
    msg.textContent = "保存中…";
    postJSON("/api/settings", collect()).then(function (res) {
      if (res.ok && res.data.saved) {
        state.values = res.data.values || {};
        msg.textContent = "✔ 已保存并生效（看板内告警与回测计算已更新；可在阈值回测页验证）";
        state.stocks = (state.values["watchlist.stocks"] || []).slice();
        render();
      } else {
        var errors = (res.data && res.data.detail && res.data.detail.errors) || [];
        fail.hidden = false;
        fail.textContent = "保存失败：" + (errors.length ? errors.join("；") : JSON.stringify(res.data).slice(0, 200));
        msg.textContent = "";
      }
    }).catch(function (e) {
      fail.hidden = false;
      fail.textContent = "保存失败：" + (e && e.message ? e.message : e);
      msg.textContent = "";
    });
  }

  function load() {
    getJSON("/api/settings").then(function (d) {
      state.values = d.values || {};
      state.envOver = d.env_overrides || {};
      state.readonly = !!d.readonly;
      state.readonlyReason = d.readonly_reason;
      state.stocks = (state.values["watchlist.stocks"] || []).slice();
      render();
    }).catch(function (e) {
      var fail = el("st-fail");
      fail.hidden = false;
      fail.textContent = "设置加载失败：" + (e && e.message ? e.message : e);
    });
  }

  bindShell();
  el("st-save").addEventListener("click", save);
  el("st-wl-add").addEventListener("click", function () {
    if (state.stocks.length >= 20) return;      // 与 src/config.py 的上限一致
    state.stocks.push({ symbol: "", label: "", cost: null });
    renderStocks();
  });
  load();
})();
