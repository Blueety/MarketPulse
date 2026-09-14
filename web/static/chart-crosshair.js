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
 *   5) 仍用 `afterEvent` + 1px 节流 + `chart.draw()`（勿用 `update()`，会重算布局/动画）；
 *   6) 仍画在 `afterDatasetsDraw`（线在数据之上、tooltip 之下）。
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

  // === 悬停水平参考线主体 —— 内联插件，仅挂到各页自己的实例上，不 Chart.register ===
  // 定调：横线 Y 取鼠标在绘图区内的纵向位置（非数据点）→ 一条中性色线 + 一个轴读数，
  // 与系列无关。afterDatasetsDraw 绘制 → 线在数据之上、tooltip 之下。
  var hoverCrosshair = {
    id: "hoverCrosshair",
    afterEvent: function (chart, args) {
      var e = args.event;
      var area = chart.chartArea;
      // 离开画布 / 触屏抬手 → 清线重绘（触屏下 tooltip 被禁，横线+气泡是唯一读数）
      if (e.type === "mouseout" || e.type === "touchend") {
        if (chart.$crossY != null) { chart.$crossY = null; chart.draw(); }
        return;
      }
      if ((e.type !== "mousemove" && e.type !== "touchmove") || !area) return;
      if (e.y < area.top || e.y > area.bottom) {
        if (chart.$crossY != null) { chart.$crossY = null; chart.draw(); }   // 移出绘图区即隐藏
        return;
      }
      // 核心：Chart.js 只在激活元素集合变化时自动重绘，同 x 索引内纵向移动集合不变，
      // 必须手动 chart.draw() 才能实时跟随（勿用 update()，会重算布局/动画）；1px 节流。
      if (chart.$crossY != null && Math.abs(e.y - chart.$crossY) < 1) return;
      chart.$crossY = e.y;
      chart.draw();
    },
    afterDatasetsDraw: function (chart) {
      var y = chart.$crossY;
      if (y == null) return;
      var area = chart.chartArea;
      var axis = chart.scales.y;
      var tc = themeColors();
      var ctx = chart.ctx;
      ctx.save();
      // 全宽虚线，中性色与系列无关；坐标一律 CSS 像素，勿乘 devicePixelRatio
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = withAlpha(tc.axisTick, 0.65);
      ctx.moveTo(area.left, y);
      ctx.lineTo(area.right, y);
      ctx.stroke();
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
