    // === 主题切换 ===
    function getTheme() {
      try {
        return localStorage.getItem('mp-theme') || 'dark';
      } catch (e) {
        return 'dark';
      }
    }
    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
    }
    applyTheme(getTheme());
    // CSS 变量读取：图表色单一来源在 style.css 的 --c-* token（Light/Dark 两套）。
    // Chart.js 不随 CSS 变量自动变色，切主题后由既有 renderCharts(state.history) 重渲染生效（pitfall #48）。
    function cssVar(name, fallback) {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback || "";
    }
    function themeColors() {
      return {
        tooltipBg: cssVar('--c-tip-bg', 'rgba(17, 22, 30, 0.95)'),
        tooltipTitle: cssVar('--c-tip-title', '#E3E8EF'),
        tooltipBody: cssVar('--c-tip-body', '#E3E8EF'),
        tooltipBorder: cssVar('--c-tip-border', '#1E2733'),
        axisTick: cssVar('--c-axis-tick', '#8492A6'),
        gridLine: cssVar('--c-grid-line', 'rgba(30, 39, 51, 0.10)'),
        gridLineBar: cssVar('--c-grid-line-bar', 'rgba(30, 39, 51, 0.28)'),
      };
    }
    const SERIES_VAR = {
      gspc: "--c-gspc", ixic: "--c-ixic", sh: "--c-sh", sz: "--c-sz", cyb: "--c-cyb",
      vix: "--c-vix", vxn: "--c-vxn", move: "--c-move", gld: "--c-gld", btc: "--c-btc"
    };
    // CSS token 缺失时的保底色（= Dark 现值，与旧 COLORS_DARK 一致）
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
    const charts = {};  // group id -> Chart 实例（重渲染前 destroy）
  if (window.Chart && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;
    const SHORT = {
      gspc: "标普500", ixic: "纳指", sh: "上证", sz: "深证", cyb: "创业板",
      vix: "VIX", vxn: "VXN", move: "MOVE", gld: "黄金", btc: "比特币"
    };
    const GROUPS = [
      { id: "chart-gspc-ixic", name: "美股大盘", keys: ["gspc", "ixic"], type: "line" },
      { id: "chart-sh-sz-cyb", name: "A 股大盘", keys: ["sh", "sz", "cyb"], type: "line" },
      { id: "chart-vix-vxn-move", name: "波动率", keys: ["vix", "vxn", "move"], type: "line" },
      { id: "chart-gld-btc", name: "另类资产", keys: ["gld", "btc"], type: "line" },
    ];

    const DEFAULT_GROUPS = ["chart-gspc-ixic", "chart-sh-sz-cyb"];  // 趋势区默认仅显两主板大图

    // 单一状态源：驱动所有视图刷新
    const state = {
      days: 30,
      selected: new Set(ALL_KEYS),
      visibleGroups: new Set(DEFAULT_GROUPS),  // 趋势区分组可见集（与表格 selected 解耦）
      sort: { key: null, dir: 1 },  // key: "value" | "change_pct"；dir: 1 升序 / -1 降序 / null 原序
      history: null,  // 最近一次 /api/history 全量 payload（显隐纯客户端管理）
      latest: null,   // 最近一次 /api/latest payload
      watch: null,   // 最近一次 /api/watchlist payload（lede 自选格复用）
    };
    let watchChart = null;  // 自选股 Chart 实例（重渲染前 destroy）

    function escapeHtml(s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }


    function fmtNum(v, digits) {
      if (v == null) return "—";
      return Number(v).toFixed(digits);
    }
    function fmtPct(v) {
      if (v == null || isNaN(v)) return "—";
      return (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%";
    }

    function buildQuery() {
      // 显隐改为纯客户端状态：恒返回全量 10 序列；symbols 参数保留向后兼容但前端不再使用
      return "/api/history?days=" + state.days;
    }

    function renderOverview(latest) {
      document.getElementById("overview-date").textContent = "数据截至：" + (latest.date || "");
      const tbody = document.getElementById("overview-body");
      tbody.innerHTML = "";
      if (!latest.indices || !latest.indices.length) {
        tbody.innerHTML = '<tr><td colspan="3">暂无数据</td></tr>';
        return;
      }
      // 按 selected 过滤（单一管线，图表与表格同步）
      let rows = latest.indices.filter(function (it) {
        return state.selected.has(it.symbol.toLowerCase());
      });
      // 排序（过滤之后执行）；null 恒排最后
      if (state.sort.key) {
        const k = state.sort.key;
        const dir = state.sort.dir;
        rows = rows.slice().sort(function (a, b) {
          const av = a[k], bv = b[k];
          if (av == null && bv == null) return 0;
          if (av == null) return 1;
          if (bv == null) return -1;
          return (av - bv) * dir;
        });
      }
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="3">无选中指标</td></tr>';
        return;
      }
      const srcDates = new Set();
      rows.forEach(function (it) {
        const chg = it.change_pct;
        const st = it.status || "—";
        const srcDate = it.source_date && it.source_date !== latest.date ? it.source_date : null;
        if (srcDate) srcDates.add(srcDate);
        const isWeekend = (new Date().getDay() % 6) === 0;   // 0=周日 6=周六
        // 涨跌色仅在真实行情显示：周末休市 / 回填(未收盘) 用中性色，避免「休市」绿字或连跌红底
        const cls = (isWeekend || srcDate) ? "" : (chg == null ? "" : (chg >= 0 ? "pos" : "neg"));
        let rowCls = "";
        if (st.indexOf("失败") >= 0) rowCls = "row-warn";
        else if (st.indexOf("异动") >= 0) rowCls = "row-flash";

        const tr = document.createElement("tr");
        tr.className = rowCls;
        const valCell = fmtNum(it.value, 2);
        const chgCell = isWeekend ? "休市" : (srcDate ? "未收盘" : fmtPct(chg));
        const tm = st.match(/连[涨跌]\d+日/);
        const trendSub = tm ? '<span class="trend-sub">' + tm[0] + "</span>" : "";
        tr.innerHTML =
          '<td class="name">' + escapeHtml(it.label) + trendSub + "</td>" +
          '<td class="num val"' + (srcDate ? ' title="数据回填自 ' + srcDate + '"' : "") + '>' + valCell + "</td>" +
          '<td class="num chg ' + cls + '">' + chgCell + "</td>";
        tbody.appendChild(tr);
      });
      const subEl = document.getElementById("overview-sub");
      if (subEl) {
        subEl.textContent = srcDates.size
          ? "· 最新交易日（部分标的回填至 " + [...srcDates].join("、") + "）"
          : "· 最新交易日";
      }
      updateSortIndicators();
    }
    function renderLede(latest, watch) {
      var el = document.getElementById('lede');
      if (!el) return;
      var idx = {}; if (latest && latest.indices) { if (Array.isArray(latest.indices)) latest.indices.forEach(function (d) { if (d && d.symbol) idx[d.symbol] = d; }); else idx = latest.indices; }
      var cells = [];
      function make(sym, label, kind) {
        var d = idx[sym];
        if (!d || d.value == null) return null;
        var chg = d.change_pct;
        var sub, subCls;
        if (chg == null) { sub = d.status || '—'; subCls = ''; }
        else { sub = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%'; subCls = chg >= 0 ? 'pos' : 'neg'; }
        return { label: label, kind: kind, sym: sym, val: fmtNum(d.value, 2), sub: sub, subCls: subCls };
      }
      var us = make('GSPC', '美股', 'accent');
      var vix = make('VIX', 'VIX', 'neg');
      var ashare = make('SH', 'A股', 'pos');
      if (us) cells.push(us);
      if (vix) cells.push(vix);
      if (ashare) cells.push(ashare);
      var wcell = null;
      if (watch && watch.stocks && watch.stocks.length) {
        for (var i = 0; i < watch.stocks.length; i++) {
          var s = watch.stocks[i];
          if (s && s.value != null) {
            var wc = s.change_pct;
            var wsub = wc == null ? (s.status || '—') : (wc >= 0 ? '+' : '') + wc.toFixed(2) + '%';
            wcell = { label: (s.label || s.symbol || '自选'), kind: 'accent', sym: s.symbol, val: fmtNum(s.value, 2), sub: wsub, subCls: wc == null ? '' : (wc >= 0 ? 'pos' : 'neg') };
            break;
          }
        }
      }
      if (wcell) {
        cells.push(wcell);
      } else {
        // 自选格占位：watchlist 未到达 / 取数失败 → 先显「—」，到达后由 success 分支补画
        cells.push({ label: '自选', kind: 'accent', sym: '', val: '—', sub: '加载中…', subCls: '' });
      }
      if (!cells.length) { el.style.display = 'none'; return; }
      el.style.display = '';
      el.innerHTML = cells.map(function (c) {
        return '<div class="lede-cell lede-' + c.kind + '">' +
          '<div class="lede-info">' +
            '<div class="lede-label">' + c.label + '</div>' +
            '<div class="lede-val">' + c.val + '</div>' +
            '<div class="lede-sub ' + c.subCls + '">' + c.sub + '</div>' +
          '</div>' +
          '<canvas class="kpi-spark" data-sym="' + (c.sym || '') + '"></canvas>' +
          '</div>';
      }).join('');
      drawSparklines(latest, watch);
    }

    var _sparkSeries = {};
    function sparkColor(cv) {
      var cell = cv.closest ? cv.closest('.lede-cell') : null;
      var sub = cell && cell.querySelector('.lede-sub');
      var cls = sub ? (sub.className || '') : '';
      if (cls.indexOf('pos') >= 0 || cls.indexOf('neg') >= 0) return getComputedStyle(sub).color;
      return getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#9aa4b2';
    }
    function drawOneSpark(cv, values, color) {
      if (!cv) return;
      if (!values || !values.length) { var c0 = cv.getContext('2d'); if (c0) c0.clearRect(0, 0, cv.width, cv.height); return; }
      var ctx = cv.getContext('2d');
      var pts = [];
      for (var i = 0; i < values.length; i++) { if (values[i] != null) pts.push(values[i]); }
      if (pts.length < 2) { ctx.clearRect(0, 0, cv.width, cv.height); return; }
      var dpr = window.devicePixelRatio || 1;
      var w = cv.clientWidth || (cv.parentElement ? cv.parentElement.clientWidth : 100) || 100;
      var h = 40;
      cv.width = Math.max(1, Math.round(w * dpr));
      cv.height = Math.max(1, Math.round(h * dpr));
      cv.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
      var range = (max - min) || 1;
      var n = pts.length;
      ctx.beginPath();
      for (var j = 0; j < n; j++) {
        var x = (n === 1) ? 0 : (j / (n - 1)) * w;
        var y = h - ((pts[j] - min) / range) * (h - 6) - 3;
        if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.lineWidth = 1.5; ctx.lineJoin = 'round'; ctx.strokeStyle = color || '#9aa4b2'; ctx.stroke();
    }
    function drawSparklines(latest, watch) {
      var canvases = document.querySelectorAll('#lede canvas.kpi-spark');
      if (!canvases.length) return;
      var map = {};
      if (watch && watch.trend && watch.trend.series) {
        watch.trend.series.forEach(function (s) { if (s && s.key) map[s.key] = s.values; });
      }
      function paint(m) {
        _sparkSeries = m;
        canvases.forEach(function (cv) {
          var k = (cv.dataset.sym || '').toLowerCase();
          drawOneSpark(cv, m[k], sparkColor(cv));
        });
      }
      paint(map);
      function withHist(h) {
        (h.series || []).forEach(function (s) { if (s && s.key) map[s.key] = s.values; });
        paint(map);
      }
      if (state.history && state.history.series) withHist(state.history);
      else fetch('/api/history?days=30').then(function (r) { return r.json(); }).then(withHist).catch(function () {});
    }
    function repaintSparklines() {
      var canvases = document.querySelectorAll('#lede canvas.kpi-spark');
      canvases.forEach(function (cv) {
        var k = (cv.dataset.sym || '').toLowerCase();
        drawOneSpark(cv, _sparkSeries[k], sparkColor(cv));
      });
    }

    function renderSector(latest) {
      const tbody = document.getElementById("sector-body");
      tbody.innerHTML = "";
      const gainers = (latest.sector_heat && latest.sector_heat.gainers) || [];
      if (!gainers.length) {
        tbody.innerHTML = '<tr><td colspan="4">数据暂缺</td></tr>';
        return;
      }
      gainers.slice(0, 5).forEach(function (g) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + escapeHtml(g.name || "—") + "</td>" +
          '<td class="pos">' + fmtPct(g.change) + "</td>" +
          '<td class="col-turnover">' + escapeHtml(g.turnover || "—") + "</td>" +
          "<td>" + escapeHtml(g.top_stock || "—") + "</td>";
        tbody.appendChild(tr);
      });
    }

    function renderAlerts(alerts) {
      const box = document.getElementById("alert-list");
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

    function renderMeta(g, series) {
      const box = document.getElementById(g.id).parentElement;
      const el = box ? box.querySelector(".chart-meta") : null;
      if (!el) return;
      el.innerHTML = "";
      series.forEach(function (s) {
        const span = document.createElement("span");
        span.className = "meta-item";
        span.style.color = colors()[s.key] || "#8b949e";
        span.textContent = s.label + " " + state.days + "D " + fmtPct(s.change_7d);
        el.appendChild(span);
      });
    }

    function renderLineChart(canvas, history, series) {
      const ctx = canvas.getContext("2d");

      const allDates = new Set();
      series.forEach(function (s) {
        (s.values || []).forEach(function (v, i) {
          if (v != null) allDates.add(history.dates[i]);
        });
      });
      const tradingDates = Array.from(allDates).filter(function (d) {
        var dt = new Date(d);
        return dt.getDay() !== 0 && dt.getDay() !== 6;
      }).sort();
      const dateIndexMap = {};
      tradingDates.forEach(function (d, i) { dateIndexMap[d] = i; });

      const datasets = series.map(function (s) {
        const pts = [];
                  let lastVal = null;
                  let lastRaw = null;
                  (s.values || []).forEach(function (v, i) {
                    const date = history.dates[i];
                    if (dateIndexMap[date] === undefined) return;
                    if (v != null) {
                      lastVal = v;
                      lastRaw = s.raw ? s.raw[i] : null;
                      pts.push({ x: date, y: v, rawVal: lastRaw });
                    } else if (lastVal != null) {
                      // 前向填充：用前一个值连接空缺（黄金周末不断线）
                      pts.push({ x: date, y: lastVal, rawVal: lastRaw, filled: true });
                    }
                  });
        return {
          label: s.label,
          key: s.key,
          data: pts,
          borderColor: colors()[s.key] + "d9",
          hoverBorderColor: colors()[s.key],
          hoverBorderWidth: 2.6,
          backgroundColor: "transparent",
          fill: false,
          tension: 0.25,
          borderWidth: 1.8,
          pointRadius: function (c) { return c.dataIndex === c.dataset.data.length - 1 ? 2.5 : 0; },
          pointHoverRadius: 'ontouchstart' in window ? 0 : 7,
          pointHoverBorderWidth: 'ontouchstart' in window ? 0 : 2,
          pointBackgroundColor: colors()[s.key],
          pointBorderColor: "#fff",
          pointBorderWidth: 1.5,
          pointHitRadius: 10,
        };
      });

      const options = {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: false,
            labels: {
              color: themeColors().axisTick,
              usePointStyle: true,
              boxWidth: 8,
              font: { size: 12 }
            }
          },
          tooltip: {
            enabled: !('ontouchstart' in window),  // 移动端禁用悬浮
            backgroundColor: themeColors().tooltipBg,
            titleColor: themeColors().tooltipTitle,
            bodyColor: themeColors().tooltipBody,
            borderColor: themeColors().tooltipBorder,
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
                const raw = pt && pt.raw != null ? pt.raw : null;
                const val = rv !== null ? rv : raw;
                if (val == null || ctx.parsed.y == null) return ctx.dataset.label + " —";
                return ctx.dataset.label + " " + fmtNum(val, 2) + " (" + fmtPct(ctx.parsed.y - 100) + ")";
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
              color: themeColors().axisTick,
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 10,
              callback: function (value, index) {
                const parts = String(tradingDates[index]).split("-");
                return Number(parts[1]) + "/" + Number(parts[2]);
              }
            }
          },
          y: {
            grid: { color: themeColors().gridLine },
            border: { display: false },
            ticks: {
              font: { size: 11 },
              color: themeColors().axisTick,
              maxTicksLimit: 5,
              callback: function (value) { return (value >= 100 ? "+" : "") + (value - 100).toFixed(1) + "%"; }
            }
          }
        },
        animation: { duration: 300, easing: "easeOutQuart" }
      };
      // 缩放/平移：仅当 zoom 插件可用时启用（CDN 失败则静默降级）
      if (window.ChartZoom && !window.__zoomFailed) {
        options.plugins.zoom = {
          wheel: { enabled: true, modifierKey: "ctrl" },
          pan: { enabled: true, modifierKey: "ctrl" },
          limits: { y: { min: "original", max: "original" } }
        };
      }
      return new Chart(canvas, { type: "line", data: { datasets: datasets }, options: options });
    }

    function renderGroup(g, history) {
      // 从零构建某组图表（首载 / 范围切换 / 空组恢复重建）；会 destroy 旧实例。
      // 显隐纯客户端：series 含该组全部序列，未选中者经 dataset.hidden 隐藏，图例项常驻可点回。
      const canvas = document.getElementById(g.id);
      const box = canvas.parentElement;
      const series = history.series.filter(function (s) {
        return g.keys.indexOf(s.key) !== -1;
      });
      const anySelected = series.some(function (s) { return state.selected.has(s.key); });
      const groupVisible = state.visibleGroups.has(g.id);
      if (charts[g.id]) { charts[g.id].destroy(); delete charts[g.id]; }
      let ph = box.querySelector(".chart-empty");
      if (!groupVisible || !anySelected) {
        canvas.style.display = "none";
        if (!ph) {
          ph = document.createElement("p");
          ph.className = "empty chart-empty";
          ph.textContent = "无选中指标";
          box.appendChild(ph);
        }
        const meta = box.querySelector(".chart-meta");
        if (meta) meta.innerHTML = "";
        return;
      }
      if (ph) ph.remove();
      canvas.style.display = "";
      const chart = renderLineChart(canvas, history, series);
      chart.data.datasets.forEach(function (ds) {
        if (!state.selected.has(ds.key)) ds.hidden = true;
      });
      chart.update();
      charts[g.id] = chart;
      renderMeta(g, series.filter(function (s) { return state.selected.has(s.key); }));
    }

    function renderCharts(history) {
      if (window.__chartFailed || !window.Chart) {
        GROUPS.forEach(function (g) {
          const box = document.getElementById(g.id).parentElement;
          box.innerHTML = '<p class="empty">图表加载失败（离线 / CDN 不可达）</p>';
        });
        return;
      }
      // 清除所有旧占位（从"全不选"状态恢复时必需）
      document.querySelectorAll(".chart-empty").forEach(function (el) { el.remove(); });
      // zoom 插件注册（仅一次）
      if (window.ChartZoom && !window.__zoomFailed && !renderCharts._zoomRegistered) {
        Chart.register(window.ChartZoom);
        renderCharts._zoomRegistered = true;
      }
      GROUPS.forEach(function (g) { renderGroup(g, history); });
    }

    function onGroupClick(idx) {
      const g = GROUPS[idx];
      // 趋势区按「分组可见集」切换：点单组→仅显该组；再点已独占组→恢复默认两主板
      const sole = state.visibleGroups.size === 1 && state.visibleGroups.has(g.id);
      state.visibleGroups = sole ? new Set(DEFAULT_GROUPS) : new Set([g.id]);
      syncSelection();
    }

    function syncSelection() {
      // 纯客户端同步中枢：图例 / 类别 / 芯片 / 全选清空 的统一入口，不发起网络请求。
      if (!state.history || !state.latest) { refresh(); return; }
      GROUPS.forEach(function (g) {
        const canvas = document.getElementById(g.id);
        const box = canvas.parentElement;
        const series = state.history.series.filter(function (s) {
          return g.keys.indexOf(s.key) !== -1;
        });
        const anySelected = series.some(function (s) { return state.selected.has(s.key); });
        const groupVisible = state.visibleGroups.has(g.id);
        if (charts[g.id]) {
          if (!groupVisible || !anySelected) {
            // 整组变空 → destroy + 占位
            charts[g.id].destroy();
            delete charts[g.id];
            canvas.style.display = "none";
            let ph = box.querySelector(".chart-empty");
            if (!ph) {
              ph = document.createElement("p");
              ph.className = "empty chart-empty";
              ph.textContent = "无选中指标";
              box.appendChild(ph);
            }
            const meta = box.querySelector(".chart-meta");
            if (meta) meta.innerHTML = "";
            return;
          }
          // 性能路径：仅改 dataset.hidden + update（无网络请求）
          charts[g.id].data.datasets.forEach(function (ds) {
            ds.hidden = !state.selected.has(ds.key);
          });
          charts[g.id].update();
          renderMeta(g, series.filter(function (s) { return state.selected.has(s.key); }));
        } else {
          // chart 不存在（空组恢复 / 首载后）→ 用缓存重建（hidden 一并应用）
          renderGroup(g, state.history);
        }
      });
      renderOverview(state.latest);  // 概览表复用缓存 latest + 既有 selected 过滤/排序
      renderFilter();  // 刷新类别按钮 / chips / 全选清空 的类
    }

    function renderFilter() {
      // 类别批量按钮（group-bar）
      const gbar = document.getElementById("group-bar");
      gbar.innerHTML = "";
      GROUPS.forEach(function (g, idx) {
        const btn = document.createElement("button");
        btn.type = "button";
        const active = state.visibleGroups.has(g.id);
        btn.className = "filter-act" + (active ? " active" : "");
        btn.textContent = g.name;
        btn.dataset.group = String(idx);
        btn.addEventListener("click", function () { onGroupClick(idx); });
        gbar.appendChild(btn);
      });
      // 全选 / 清空 + 指标 chips（symbol-filter）
      const box = document.getElementById("symbol-filter");
      box.innerHTML = "";
      const allBtn = document.createElement("button");
      allBtn.type = "button";
      allBtn.className = "filter-act";
      allBtn.textContent = "全选";
      allBtn.addEventListener("click", function () {
        state.selected = new Set(ALL_KEYS);
        state.visibleGroups = new Set(GROUPS.map(function (g) { return g.id; }));
        syncSelection();
      });
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "filter-act";
      clearBtn.textContent = "清空";
      clearBtn.addEventListener("click", function () {
        state.selected = new Set();
        syncSelection();
      });
      box.appendChild(allBtn);
      box.appendChild(clearBtn);
      ALL_KEYS.forEach(function (key) {
        const label = document.createElement("label");
        label.className = "chip" + (state.selected.has(key) ? " on" : "");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = state.selected.has(key);
        cb.addEventListener("change", function () {
          if (cb.checked) state.selected.add(key);
          else state.selected.delete(key);
          syncSelection();
        });
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.style.background = colors()[key];
        const text = document.createElement("span");
        text.textContent = SHORT[key] || key;
        label.appendChild(cb);
        label.appendChild(dot);
        label.appendChild(text);
        box.appendChild(label);
      });
    }

    function updateSortIndicators() {
      document.querySelectorAll(".th-sort").forEach(function (th) {
        const ind = th.querySelector(".sort-ind");
        if (!ind) return;
        if (state.sort.key === th.dataset.sort) {
          ind.textContent = state.sort.dir === 1 ? "▲" : "▼";
        } else {
          ind.textContent = "";
        }
      });
    }

    function renderWatchlist(payload) {
      const section = document.getElementById("watchlist-section");
      const body = document.getElementById("watchlist-body");
      section.classList.remove("hidden");
      const trendByKey = {};
      (payload.trend && payload.trend.series || []).forEach(function (s) {
        trendByKey[s.key] = s;
      });
      body.innerHTML = "";
      payload.stocks.forEach(function (row) {
        const tr = document.createElement("tr");
        const key = (row.symbol || "").toLowerCase();
        const trend = trendByKey[key];
        if (row.value == null) {
          // 失败行：名称保留，其余列「数据暂缺」（NF3）
          tr.innerHTML =
            '<td>' + escapeHtml(row.label) + '</td>' +
            '<td class="empty">数据暂缺</td>' +
            '<td class="empty">数据暂缺</td>' +
            '<td class="empty">数据暂缺</td>';
          body.appendChild(tr);
          return;
        }
        const cls = row.change_pct == null ? "" : (row.change_pct >= 0 ? "pos" : "neg");
        const trendCell = trend && trend.change_7d != null ? fmtPct(trend.change_7d) : "—";
        tr.innerHTML =
          '<td>' + escapeHtml(row.label) + '</td>' +
          '<td>' + fmtNum(row.value, 2) + '</td>' +
          '<td class="' + cls + '">' + fmtPct(row.change_pct) + '</td>' +
          '<td>' + trendCell + '</td>';
        body.appendChild(tr);
      });
      renderWatchChart(payload.trend);
    }

    function renderWatchChart(trend) {
      const canvas = document.getElementById("chart-watchlist");
      const box = canvas.parentElement;
      if (!window.Chart || window.__chartFailed) {
        box.innerHTML = '<p class="empty">图表加载失败（离线 / CDN 不可达）</p>';
        return;
      }
      if (!trend || !trend.series || !trend.series.length) {
        box.innerHTML = '<p class="empty">数据暂缺</p>';
        return;
      }
      const tc = themeColors();

      const allDates = new Set();
      trend.series.forEach(function (s) {
        (s.values || []).forEach(function (v, i) {
          if (v != null) allDates.add(trend.dates[i]);
        });
      });
      const tradingDates = Array.from(allDates).filter(function (d) {
        var dt = new Date(d);
        return dt.getDay() !== 0 && dt.getDay() !== 6;
      }).sort();
      const dateIndexMap = {};
      tradingDates.forEach(function (d, i) { dateIndexMap[d] = i; });

      const palette = Object.values(colors());
      const datasets = trend.series.map(function (s, i) {
        const pts = [];
        let lastVal = null;
        let lastRaw = null;
        (s.values || []).forEach(function (v, i2) {
          const date = trend.dates[i2];
          if (dateIndexMap[date] === undefined) return;
          if (v != null) {
            lastVal = v;
            lastRaw = s.raw ? s.raw[i2] : null;
            pts.push({ x: date, y: v, rawVal: lastRaw });
          } else if (lastVal != null) {
            // 前向填充：用前一个值连接空缺（黄金周末不断线）
            pts.push({ x: date, y: lastVal, rawVal: lastRaw, filled: true });
          }
        });
        const color = palette[i % palette.length];
        return {
          label: s.label,
          key: s.key,
          data: pts,
          borderColor: color + "d9",
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
          pointHitRadius: 10,
        };
      });

      const options = {
        responsive: true,
        maintainAspectRatio: false,   // 高由 CSS 220px 决定，避免 aspect=2 画 320 高被压缩到 220 显示（糊）
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            display: false,
            labels: {
              color: tc.axisTick,
              usePointStyle: true,
              boxWidth: 8,
              font: { size: 12 }
            }
          },
          tooltip: {
            enabled: !('ontouchstart' in window),  // 移动端禁用悬浮
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
                const raw = pt && pt.raw != null ? pt.raw : null;
                const val = rv !== null ? rv : raw;
                if (val == null || ctx.parsed.y == null) return ctx.dataset.label + " —";
                return ctx.dataset.label + " " + fmtNum(val, 2) + " (" + fmtPct(ctx.parsed.y - 100) + ")";
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
              maxTicksLimit: 10,
              callback: function (value, index) {
                const parts = String(tradingDates[index]).split("-");
                return Number(parts[1]) + "/" + Number(parts[2]);
              }
            }
          },
          y: {
            grid: { color: tc.gridLine },
            border: { display: false },
            ticks: {
              font: { size: 11 },
              color: tc.axisTick,
              maxTicksLimit: 5,
              callback: function (value) { return (value >= 100 ? "+" : "") + (value - 100).toFixed(1) + "%"; }
            }
          }
        },
        animation: { duration: 300, easing: "easeOutQuart" }
      };
      // 缩放/平移：仅当 zoom 插件可用时启用（CDN 失败则静默降级）
      if (window.ChartZoom && !window.__zoomFailed) {
        options.plugins.zoom = {
          wheel: { enabled: true, modifierKey: "ctrl" },
          pan: { enabled: true, modifierKey: "ctrl" },
          limits: { y: { min: "original", max: "original" } }
        };
      }
      if (watchChart) watchChart.destroy();
      watchChart = new Chart(canvas, { type: "line", data: { datasets: datasets }, options: options });
    }


    function refresh() {
      // 历史趋势：恒取全量（显隐纯客户端）；写入缓存供 syncSelection 复用
      fetch(buildQuery()).then(function (r) { return r.json(); })
        .then(function (history) {
          state.history = history;
          renderCharts(history);
        })
        .catch(function () { /* 图表区已在渲染函数内降级 */ });
      // 最新概览 + 板块：始终请求（表格按 selected 过滤 + 排序）
      fetch("/api/latest").then(function (r) { return r.json(); })
        .then(function (data) {
          state.latest = data;
          var _u = document.getElementById('sidebar-updated'); if (_u) _u.textContent = '更新 ' + new Date().toTimeString().slice(0, 5);
          renderOverview(data);
          renderSector(data);
          renderLede(data, state.watch);
        })
        .catch(function (e) { loadFailed(e.message, "overview-body"); });
    }

    function loadFailed(msg, boxId) {
      const box = document.getElementById(boxId);
      if (box) box.innerHTML = '<tr><td colspan="3">加载失败：' + msg + "</td></tr>";
    }

    document.addEventListener("DOMContentLoaded", function () {
      // 主题切换
      var themeBtn = document.getElementById('sidebar-theme');
      if (themeBtn) {
        themeBtn.addEventListener('click', function() {
          var next = getTheme() === 'dark' ? 'light' : 'dark';
          try { localStorage.setItem('mp-theme', next); } catch (e) {}
          applyTheme(next);
          if (state.history) renderCharts(state.history);
          repaintSparklines();
        });
      }
      // 移动端抽屉导航
      var menuBtn = document.getElementById('menu-toggle');
      if (menuBtn) menuBtn.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
      var navBackdrop = document.createElement('div');
      navBackdrop.className = 'nav-backdrop';
      document.body.appendChild(navBackdrop);
      navBackdrop.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
      document.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
        item.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
      });
      document.getElementById('main').addEventListener('click', function () { if (document.body.classList.contains('nav-open')) document.body.classList.remove('nav-open'); });
      // 侧栏导航：锚点平滑滚动 + active 态（无内容菜单 disabled 拦截）
      document.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
        item.addEventListener('click', function (e) {
          if (item.classList.contains('disabled')) { e.preventDefault(); return; }
          var target = item.getAttribute('data-target');
          var el = target && document.getElementById(target);
          if (el) {
            e.preventDefault();
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            document.querySelectorAll('#sidebar .nav-item').forEach(function (n) { n.classList.remove('active'); });
            item.classList.add('active');
          }
        });
      });
      // 刷新按钮
      var refreshBtn = document.getElementById('refresh-btn');
      if (refreshBtn) refreshBtn.addEventListener('click', function () { refresh(); });

      // 时间范围按钮
      document.getElementById("range-bar").addEventListener("click", function (e) {
        const btn = e.target.closest("button[data-days]");
        if (!btn) return;
        state.days = parseInt(btn.dataset.days, 10);
        document.querySelectorAll("#range-bar button").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        document.getElementById("range-label").textContent = state.days;
        refresh();
      });
      // 排序表头：升序 → 降序 → 原序 三态循环
      document.querySelectorAll(".th-sort").forEach(function (th) {
        th.addEventListener("click", function () {
          const key = th.dataset.sort;
          if (state.sort.key === key) {
            if (state.sort.dir === 1) state.sort.dir = -1;     // 升 → 降
            else { state.sort.key = null; state.sort.dir = 1; } // 降 → 原序
          } else {
            state.sort.key = key; state.sort.dir = 1;          // 新列 → 升序
          }
          refresh();
        });
      });

      renderFilter();
      refresh();
      // 告警仅初始加载一次（不随筛选/范围变化）
      fetch("/api/alerts")
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (data) {
          renderAlerts(Array.isArray(data) ? data : []);
        })
        .catch(function (err) {
          console.error("[alerts] fetch failed:", err);
          var el = document.getElementById("alert-list");
          if (el) el.innerHTML = '<p class="empty">加载失败</p>';
        });

      // 自选股实时取数：hidden=false（有配置）才显示卡片；取数失败/超时占位可见，不静默
      var wlTimer = null;
      var wlFetch = fetch("/api/watchlist").then(function (r) { return r.json(); });
      var wlTimeout = new Promise(function (_, reject) {
        wlTimer = setTimeout(function () { reject(new Error("watchlist 取数超时（12s）")); }, 12000);
      });
      Promise.race([wlFetch, wlTimeout])
        .then(function (data) {
          clearTimeout(wlTimer);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          if (data && data.hidden) { sec.classList.add("hidden"); return; }  // F4：无配置不闪现
          sec.classList.remove("hidden");
          if (!data || !data.stocks || !data.stocks.length) {
            var b = document.getElementById("watchlist-body");
            if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（实时取数失败）</td></tr>';
            return;
          }
          renderWatchlist(data);
          state.watch = data;
          renderLede(state.latest, data);
        })
        .catch(function (err) {
          console.error("[watchlist] fetch failed:", err);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          sec.classList.remove("hidden");  // 异常态：失败占位可见（网络/解析/超时）
          var b = document.getElementById("watchlist-body");
          if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（取数失败）</td></tr>';
        });

    });
