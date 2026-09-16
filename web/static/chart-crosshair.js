/* 悬停水平参考线（crosshair）—— 首页与宏观页**共享**的内联插件。
 *
 * 为什么共享而不是在 macro.js 里再抄一份（2026-09-14 macro-chart-crosshair）：
 *   两页都需要这条线，但**读数口径不同**：
 *     首页   y 轴 = 归一化涨跌幅（相对 100 的偏离）→ fmtAxisPct(v) = (v-100).toFixed(1) + '%'
 *     宏观页 y 轴 = 单变量**真实价格**（10Y 是百分数、黄金是美元）或「全部对比」的起点 100 指数
 *   照搬首页插件会让黄金 4386.60 显示成 `+4286.6%` —— 页面不报错、console 干净，只是数字荒谬。
 *   → 插件本体共享，**读数格式化器按实例注入**：
 *       首页  → `plugins: [window.hoverCrosshair]`（默认口径 = fmtAxisPct）
 *       其他页 → `plugins: [window.makeHoverCrosshair({ formatter: fn })]`
 *     ⚠️ **不要**把 formatter 写进 `options.plugins.hoverCrosshair` —— Chart.js 把插件选项当
 *        scriptable option 解析，读到函数值会**立即以 context 调用**它 → 整页抛
 *        `TypeError: Cannot convert object to primitive value`（实测踩过，见 makeHoverCrosshair 注释）。
 *
 * 硬契约（勿破；verify_ui.py 的 CS-1 / CS-4 / CS-7b / F-7a 直接依赖）：
 *   1) 暴露 `window.hoverCrosshair`，且 `id === 'hoverCrosshair'`；
 *   2) 仍是**内联插件**（不 `Chart.register`，避免影响全局实例）；
 *   3) 仍写 `chart.$crosshairLabel`（气泡文本的唯一可测挂钩）；
 *   4) 气泡水平位置**动态读 `axis.position`**（不写死 left）；
 *   5) 仍用 `afterEvent` + 节流 + `chart.draw()`（勿用 `update()`，会重算布局/动画）；
 *      ⚠️ **节流对象必须是被绘制的量**（= 吸附后的 y），不是鼠标 y —— 绑错会让单数据集图
 *      每帧无意义重绘（2026-09-15 L4）；阈值 0.5px（吸附点是离散像素值，1px 会吞掉换点）；
 *   6) 仍画在 `afterDatasetsDraw`（线在数据之上、tooltip 之下）；
 *   7) 仍写 `chart.$crossSource`（吸附目标的可测挂钩：`{dsIndex, dataIdx}`，无吸附目标时为 null）。
 *
 * ⚠️ 加载顺序：本文件必须在各页业务脚本（`app.js` / `macro.js`）**之前**引入。
 *    顺序错 → `window.hoverCrosshair === undefined` → `plugins: [undefined]` 被 Chart.js
 *    **静默忽略**（不报错、console 干净）→ 表现为"横线没出来"，极易误判为插件 bug。
 *
 * 本文件同时承载 `cssVar` / `themeColors` / `withAlpha` 三个全局小工具：
 *    它们原先在 `app.js` 与 `macro.js` **各有一份**（`cssVar` 两份、`withAlpha` 两份），
 *    随插件一起收敛到此处，两页业务脚本仍按原样裸调用（全局函数，无需改调用点）。
 */
(function () {
  "use strict";

  // CSS 变量读取：图表色单一来源在 style.css 的 --c-* token（Light/Dark 两套）
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    v = (v || "").trim();
    return v || fallback || "";
  }

  function themeColors() {
    return {
      tooltipBg: cssVar("--c-tip-bg", "rgba(255, 255, 255, 0.95)"),
      tooltipTitle: cssVar("--c-tip-title", "#1d1d1f"),
      tooltipBody: cssVar("--c-tip-body", "#1d1d1f"),
      tooltipBorder: cssVar("--c-tip-border", "#d2d2d7"),
      axisTick: cssVar("--c-axis-tick", "#86868b"),
      gridLine: cssVar("--c-grid-line", "rgba(0, 0, 0, 0.06)")
    };
  }

  // 色值加透明度：#RGB / #RRGGBB → rgba()；其余形式（rgb()/rgba()/变量值）原样返回。
  // ⚠️ 口径与抽取前的 app.js 版本**逐字节相同**：本页实际传入的都是 hex token，
  //    改成"rgb() 也改写 alpha"会悄悄改变首页网格/线的透明度，故不做增强。
  function withAlpha(color, a) {
    var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(color || "").trim());
    if (!m) return color;
    var h = m[1];
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  // 默认口径 = 首页的 fmtAxisPct（**延迟解析**：本文件先于 app.js 加载，此时它还不在）
  function defaultFormatter(v) {
    if (typeof window.fmtAxisPct === "function") return window.fmtAxisPct(v);
    return String(v);
  }

  // 取**本实例的插件对象**（= `config.plugins` 里 id 匹配的那一个）。
  // ⚠️ 只从 `config.plugins` 读，**绝不去读 `options.plugins.hoverCrosshair`**：
  //    Chart.js 把插件选项当 **scriptable option** 解析 —— 读到函数值会**立即以 context 调用**它
  //    （实测 `options.plugins.hoverCrosshair.formatter` 触发
  //     `TypeError: Cannot convert object to primitive value` at `isFinite()`，整页直接抛异常）。
  //    放在插件对象上则是纯数据，不经过选项代理。
  function pluginEntry(chart) {
    var cfg = chart.config && chart.config.plugins;
    if (Object.prototype.toString.call(cfg) === "[object Array]") {
      for (var i = 0; i < cfg.length; i++) {
        if (cfg[i] && cfg[i].id === "hoverCrosshair") return cfg[i];
      }
    } else if (cfg && typeof cfg === "object" && cfg.hoverCrosshair) {
      return cfg.hoverCrosshair;
    }
    return null;
  }

  function resolveFormatter(chart) {
    var p = pluginEntry(chart);
    if (p && typeof p.formatter === "function") return p.formatter;
    // 兜底必须是 fmtAxisPct（CS-4 依赖首页行为逐字节不变）
    if (typeof window.__defaultCrosshairFormatter === "function") return window.__defaultCrosshairFormatter;
    return defaultFormatter;
  }

  // 吸附到最近的数据线（2026-09-15 crosshair-snap）：先按鼠标 x 定**唯一的数据列**，
  // 再在该列的所有**可见**数据集里取 y 最近者 —— 「先定 x 再定线」保证吸附目标必然是
  // 「当前日期的某条线」，不会跨日期。并列（tie）取**较小索引** → 确定性（实测会出现并列）。
  // 只比较 **CSS 像素**：事件坐标 e.x/e.y 与 element 坐标 meta.data[i].x/.y 同空间，
  // ⚠️ 此处**绝不能乘 devicePixelRatio**（DPR≠1 屏上会整体偏移一倍，而 DPR=1 的验收测不出）。
  function snapToNearest(chart, mx, my) {
    var area = chart.chartArea;
    if (!area) return null;
    var cx = Math.min(Math.max(mx, area.left), area.right);   // x 钳制（可见性仍只判 y）

    var idx0 = null, bestDx = Infinity;
    chart.data.datasets.forEach(function (ds, i) {
      var m = chart.getDatasetMeta(i);
      if (m.hidden) return;
      (m.data || []).forEach(function (p, idx) {
        if (!p || !isFinite(p.x)) return;
        var d = Math.abs(p.x - cx);
        if (d < bestDx - 1e-9 || (Math.abs(d - bestDx) <= 1e-9 && idx0 !== null && idx < idx0)) {
          bestDx = d; idx0 = idx;
        }
      });
    });
    if (idx0 === null) return null;

    // 缺口回退：多品种模式的日期轴是并集 → 该列可能全为 NaN，依次试邻列
    var OFFS = [0, -1, 1, -2, 2, -3, 3];
    for (var k = 0; k < OFFS.length; k++) {
      var idx = idx0 + OFFS[k];
      var best = null;
      chart.data.datasets.forEach(function (ds, i) {
        var m = chart.getDatasetMeta(i);
        if (m.hidden) return;
        var p = (m.data || [])[idx];
        if (!p || !isFinite(p.y)) return;                     // ★ NaN 守卫（缺口必经）
        if (!best || Math.abs(p.y - my) < Math.abs(best.y - my)) best = { y: p.y, dsIndex: i };
      });
      if (best) return { y: best.y, dsIndex: best.dsIndex, dataIdx: idx };
    }
    return null;                                              // 全空 → 调用方回退鼠标 y
  }

  // === 悬停水平参考线主体 —— 内联插件，仅挂到各页自己的实例上，不 Chart.register ===
  // 定调（2026-09-15 修订）：横线 Y **吸附到当前 x 最近的数据线**（原为"鼠标纵向位置"）→
  //   线**必然属于某个系列**，故线色取该系列的 borderColor（alpha .65）+ 在吸附点画 3px 圆点；
  //   无吸附目标（缺口/单系列兜底）时仍用中性轴色。轴端气泡仍读**该 y 处的轴值**（与系列无关）。
  //   afterDatasetsDraw 绘制 → 线在数据之上、tooltip 之下。
  var hoverCrosshair = {
    id: "hoverCrosshair",
    afterEvent: function (chart, args) {
      var e = args.event;
      var area = chart.chartArea;
      // 离开画布 / 触屏抬手 → 清线重绘（触屏下 tooltip 被禁，横线+气泡是唯一读数）
      if (e.type === "mouseout" || e.type === "touchend") {
        if (chart.$crossY != null) {
          chart.$crossY = null; chart.$crossSource = null; chart.draw();
        }
        return;
      }
      if ((e.type !== "mousemove" && e.type !== "touchmove") || !area) return;
      if (e.y < area.top || e.y > area.bottom) {
        // 移出绘图区即隐藏（可见性规则**仍只判 y**：不为吸附顺手把 x 加进来）
        if (chart.$crossY != null) {
          chart.$crossY = null; chart.$crossSource = null; chart.draw();
        }
        return;
      }
      // 核心：横线吸附到最近的数据线；整列无数据（缺口）时回退鼠标 y，保证线不闪断。
      var snap = snapToNearest(chart, e.x, e.y);
      var targetY = snap ? snap.y : e.y;
      // Chart.js 只在激活元素集合变化时自动重绘，同 x 索引内纵向移动集合不变，
      // 必须手动 chart.draw()（勿用 update()，会重算布局/动画）。
      // ★ 节流对象必须是**被绘制的量**（吸附后的 y），不是鼠标 y：单数据集图里
      //   鼠标纵移而吸附点不变，绑 e.y 会导致每帧无意义重绘；阈值 0.5px（吸附点是离散像素值，
      //   1px 会把真实的换点吞掉）。早退时**不写** $crossSource —— y 未变 ⇒ 吸附目标未变。
      if (chart.$crossY != null && Math.abs(targetY - chart.$crossY) < 0.5) return;
      chart.$crossY = targetY;
      chart.$crossSource = snap ? { dsIndex: snap.dsIndex, dataIdx: snap.dataIdx } : null;
      chart.draw();
    },
    afterDatasetsDraw: function (chart) {
      var y = chart.$crossY;
      if (y == null) return;
      var area = chart.chartArea;
      var axis = chart.scales.y;
      var tc = themeColors();
      var ctx = chart.ctx;
      var src = chart.$crossSource;
      var srcDs = (src && chart.data.datasets[src.dsIndex]) || null;
      var srcColor = (srcDs && typeof srcDs.borderColor === "string" && srcDs.borderColor)
        ? srcDs.borderColor : null;
      // 线色归因（方案 B）：吸附后横线**必然属于某个系列** → 取该系列色（alpha .65）；
      // 无吸附目标（缺口回退鼠标 y）→ 中性轴色。单数据集时二者观感一致，不会突兀。
      ctx.save();
      // 全宽虚线；坐标一律 CSS 像素，勿乘 devicePixelRatio
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = srcColor ? withAlpha(srcColor, 0.65) : withAlpha(tc.axisTick, 0.65);
      ctx.moveTo(area.left, y);
      ctx.lineTo(area.right, y);
      ctx.stroke();
      // 吸附点圆点：**全图唯一可见的点** —— 各页已把 `pointHoverRadius` 设为 0（见 `app.js` /
      // `macro.js` / `macro_cn.js`），否则 Chart.js 的 `mode:'index'` 会给**每个系列**都画悬停点，
      // 多系列图上就会出现"多个点、虚线只穿过其中一个"（用户 2026-09-16 反馈）。
      // ⚠️ 新增图表时若重新打开 `pointHoverRadius`，必须同步这条不变量（否则该页会出现第二个点）。
      if (src) {
        var meta = chart.getDatasetMeta(src.dsIndex);
        var pt = (meta && meta.data) ? meta.data[src.dataIdx] : null;
        if (pt && isFinite(pt.x) && isFinite(pt.y)) {
          ctx.beginPath();
          ctx.setLineDash([]);
          ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2);
          ctx.fillStyle = srcColor || withAlpha(tc.axisTick, 0.65);
          ctx.fill();
          ctx.lineWidth = 1;
          ctx.strokeStyle = tc.tooltipBg;
          ctx.stroke();
        }
      }
      // Y 轴端读数气泡：动态贴当前轴侧（勿写死 left），垂直钳制在画布内
      var text = resolveFormatter(chart)(axis.getValueForPixel(y), chart);
      chart.$crosshairLabel = text;   // 可测性挂钩：verify_ui.py 对气泡的唯一客观断言点
      var f = (window.Chart.defaults && window.Chart.defaults.font) || {};
      ctx.font = "11px " + (f.family || "sans-serif");
      var bw = ctx.measureText(text).width + 10;
      var bh = 16;
      var pad = bh / 2 + 2;
      var cy = Math.min(Math.max(y, pad), chart.height - pad);
      var bx = axis.position === "right" ? area.right + 2 : area.left - 2 - bw;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(bx, cy - bh / 2, bw, bh, 4); else ctx.rect(bx, cy - bh / 2, bw, bh);
      ctx.fillStyle = tc.tooltipBg;
      ctx.fill();
      ctx.strokeStyle = tc.tooltipBorder;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = tc.tooltipBody;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(text, bx + 5, cy);
      ctx.restore();
    }
  };

  // 需要**自定义读数口径**的页面用这个工厂拿一个实例级插件对象（读数口径随 `formatter` 注入）。
  // ⚠️ 为什么不走 `options.plugins.hoverCrosshair`：见 pluginEntry() 上方的注释（会被当 scriptable
  //    option 立即调用而抛异常）。工厂产出的对象仍是纯数据，`id` 不变 → CS-1 / CS-7b 仍成立。
  function makeHoverCrosshair(opts) {
    return {
      id: "hoverCrosshair",
      formatter: (opts && typeof opts.formatter === "function") ? opts.formatter : null,
      afterEvent: hoverCrosshair.afterEvent,
      afterDatasetsDraw: hoverCrosshair.afterDatasetsDraw
    };
  }

  // 全局暴露（两页业务脚本裸调用同名函数，调用点零改动）
  window.cssVar = cssVar;
  window.themeColors = themeColors;
  window.withAlpha = withAlpha;
  window.__defaultCrosshairFormatter = defaultFormatter;
  window.hoverCrosshair = hoverCrosshair;          // 默认口径实例（首页直接用）
  window.makeHoverCrosshair = makeHoverCrosshair;  // 自定义口径（宏观页用）
})();
