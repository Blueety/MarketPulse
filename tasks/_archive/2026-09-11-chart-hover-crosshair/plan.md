# MarketPulse 图表悬停水平参考线（Crosshair）· 实施计划

> 架构师产出（Phase 3）。**只提供方案，不含完整实现代码**；代码由执行者编写。
> 现状事实来自代码核对（`web/static/app.js`），非推演。

---

## 0. 前置说明

| 项 | 说明 |
|---|---|
| 触发 | 需求方 2026-09-11：「数据悬浮在图表数据上的时候，可以有个横线连接到 y 轴，这样方便我看数据」 |
| 任务关系 | **独立新任务**。`tasks/2026-09-11-glassmorphism-fix/plan.md`（玻璃化）已在 §1 明确 **不改 `app.js`**，本任务只动 `app.js`，**代码上互不阻塞** |
| **任务顺序（重要，避免并发冲突）** | `verify_ui.py` 同时是**玻璃化任务的活跃文件** —— 执行者已在推进该任务，并把它从 387 行扩到了 **400 行**。为避免同一文件被两个任务并发编辑（本仓库有 auto-commit cron，冲突更易被误提交），**本任务请在玻璃化任务落地后再开工**；开工前先 `git log --oneline -- tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` 确认最新版本再追加 |
| prd.md | 无。Goal 来源 = 需求方原话 + 下方 4 项确认 |
| 依赖 | **零新增依赖**（用 Chart.js 内联插件；**不引入** `chartjs-plugin-annotation`） |

**已确认的 4 项设计决策**

| # | 问题 | 决策 |
|---|---|---|
| Q1 | 横线跨度 | **整幅全宽**（从左边缘到右边缘贯穿绘图区） |
| Q2 | 多条系列时画几条 | **只画一条，跟着鼠标纵向位置走**（不吸附数据点、不按系列区分） |
| Q3 | 轴上数值气泡 | **加**（Y 轴端小色块 + 百分比数值） |
| Q4 | 读数口径 | **百分比**（横线读涨跌幅档位；具体股价看 tooltip） |

> ⚠️ **Q2 是本次方案的定调项**：横线的 Y 坐标取**鼠标在绘图区内的 Y**，而不是某个数据点的 Y。
> 因此它是**一条中性色参考线 + 一个百分比读数**，与"哪个系列"无关。这也正好绕开了多系列歧义（`mode:'index'` 下会有 2~3 个激活点，各自 Y 不同）。

---

## 1. 任务目标

**Goal**

在 `#chart-main`（唯一图表实例 `charts.main`）上增加悬停水平参考线：鼠标进入绘图区后，一条全宽水平虚线跟随鼠标纵向位置，并在 Y 轴端显示该高度对应的**涨跌幅百分比**；鼠标离开绘图区即消失。

**一句话验收标准**

鼠标在绘图区内上下移动时，横线与 Y 轴端百分比气泡**实时跟随**（`canvas.toDataURL()` 在两次不同 Y 位置必然不同）；鼠标移出绘图区后横线与气泡**消失**（画布回到无参考线状态）；且不影响既有 tooltip、类别 tab、缩放平移与 `scrollHeight ≤ 1240`。

**必须保持（回归护栏）**

| 指标 | 现状 | 本任务要求 |
|---|---|---|
| 既有 tooltip（悬停显示日期 + 各系列原价/百分比） | 工作 | 不变 |
| `charts.main` 单一实例 + 重渲染前 `destroy()` | 工作 | 不变 |
| 类别 tab（股票/波动率/宏观/另类资产）切换 | 工作 | 不变 |
| ctrl+滚轮缩放 / ctrl+拖拽平移（CDN 插件） | 工作 | 不变（见 R3） |
| `scrollHeight` @1920×1080 | **1235** | ≤1240（不变；本任务不加 DOM） |
| `scrollingElement.scrollWidth === innerWidth` | true | true |
| Console error | 0 | 0 |
| 双主题 | 正常 | 气泡颜色随主题（复用 token） |

**Out of Scope（本次不做）**

- **不加垂直竖线**（十字准星的竖向部分）。⭐ 说明：`interaction.mode` 已是 `'index'`，补竖线约 5 行，若你要可随时加，本任务按你的原话只做横向。
- 不改 tooltip 内容/样式。
- 不改 Y 轴刻度口径（仍是归一化百分比轴；**改成价格轴属另一件事**，会失去跨市场对比能力）。
- 不改 Y 轴位置（当前在**左侧**；效果图在右侧，属"下一个任务"）。本任务让插件**动态读 `yScale.left/right`**，因此两个任务互不阻塞。
- 不动 `index.html` / `style.css` / `web/app.py` / `tests/`。
- 不为自选列表加参考线（自选列表已是纯 CSS 迷你条，无 Chart.js 实例）。

---

## 2. 现状基线（代码事实）

| 事实 | 位置 |
|---|---|
| 全看板**只有一个** Chart.js 实例：`charts.main`（文件头注释明示"图表唯一实例"） | `app.js:2`、`app.js:488` |
| 图表创建点：`renderMainChart()` → `charts.main = new Chart(canvas, { type, data, options })` | `app.js:448-493` |
| `interaction: { mode: "index", intersect: false }` **已开启** → 悬停整幅绘图区即激活该 x 的全部数据点 | `app.js:329` |
| `scales.y` **未设 `position`** → 默认**左侧** | `app.js:375-384` |
| Y 轴刻度格式化：`(value >= 100 ? "+" : "") + (value - 100).toFixed(1) + "%"`（**内联匿名函数**） | `app.js:382` |
| `scales.x` 为 `type: "category"` | `app.js:360` |
| `themeColors()` 返回 `tooltipBg / tooltipTitle / tooltipBody / tooltipBorder / axisTick / gridLine` → **可直接复用作气泡配色** | `app.js:24-32` |
| 全文件**无** `afterDraw` / `afterEvent` / `getActiveElements` / `crosshair` / 任何插件代码 → 本功能是从零新增 | 全文件 |
| tooltip 在触屏下禁用：`enabled: !('ontouchstart' in window)` | `app.js:336` |
| 缩放/平移插件按可用性注入 `options.plugins.zoom` | `app.js:388-394` |

**关键结论**：改动面极小 —— 新增 1 个内联插件（约 40~55 行）+ 在唯一的 `new Chart(...)` 处加一行 `plugins: [hoverCrosshair]`。**`app.js` 是唯一被改文件。**

---

## 3. 方案（替代方案 + 选型）

### 3.1 横线锚点：**鼠标 Y（选定）** vs 数据点 Y

| 方案 | 行为 | 评价 |
|---|---|---|
| **A（选，= Q2 决策）** | 横线 Y = **鼠标在绘图区内的 Y**；气泡数值 = `yScale.getValueForPixel(mouseY)` | 可读**任意高度**（不受数据点分布限制），一次只有一条线，天然规避多系列歧义。与 TradingView/交易所终端一致 |
| B | 横线 Y = 激活数据点的 Y（每系列一条） | 只能读数据点所在档位；`mode:'index'` 下会同时出现 2~3 条线 → 与需求方"就一条线"的要求不符 |
| C | 横线 Y = 离鼠标最近的那个数据点的 Y（单条） | 会在数据点之间"跳变"（吸附），刻度读数不连续；需求方明确说了"就我鼠标那个位置" |

### 3.2 获取鼠标 Y 与**重绘触发**（本方案最关键的技术点）

⚠️ **最大陷阱**：Chart.js 只在**激活元素集合发生变化**时自动重绘。鼠标在**同一个 x 索引内上下移动**时，激活集合不变 → **不会重绘** → 横线会"卡住不动"。必须手动触发重绘。

**推荐机制**：用插件钩子 `afterEvent(chart, args)` 拿归一化后的事件（Chart.js 已把坐标换算好，无需自己处理 canvas 偏移与 DPR）：

```text
# 伪代码 —— 描述机制，不写完整实现
const hoverCrosshair = {
  id: 'hoverCrosshair',
  afterEvent(chart, args) {
    const e = args.event, area = chart.chartArea;
    if (e.type === 'mouseout') { clear(); chart.draw(); return; }      // 触屏补 touchend
    if (e.type !== 'mousemove' && e.type !== 'touchmove') return;
    const inside = e.y >= area.top && e.y <= area.bottom;
    if (!inside)            { clear(); chart.draw(); return; }         // 移出绘图区即隐藏
    if (Math.abs(e.y - chart.$crossY) < 1) return;                     // 1px 粒度节流，防每帧重绘
    chart.$crossY = e.y;
    chart.draw();                                                      // ★ 手动重绘才有实时跟随
  },
  afterDatasetsDraw(chart) { /* 画横线 + 轴上数值气泡 */ }
};
```

要点：

1. **重绘用 `chart.draw()`，不要用 `chart.update()`** —— `update()` 会重算布局/动画，代价高且可能触发缩放插件重算；`draw()` 只重绘。
2. **1px 粒度节流**：`Math.abs(delta) < 1` 直接 return，避免高频 mousemove 下无意义重绘。
3. **`afterEvent` 里调 `draw()` 不会递归**：`afterEvent` 只在真实事件时触发，`draw()` 不再派发事件。
4. 钩子选 `afterDatasetsDraw`（**不是** `afterDraw`）→ 横线画在数据线**之上**、tooltip **之下**（Chart.js 的 tooltip 在 `afterDraw` 阶段绘制）。顺序正确，横线不会被曲线压住，也不会盖住 tooltip。
5. **坐标空间**：`chart.chartArea` 与 `event.y` 都是 **CSS 像素**；Chart.js 已对 `ctx` 做过 `setTransform(dpr, 0, 0, dpr, 0, 0)`。**绝对不要在插件里再乘 `devicePixelRatio`**，否则 DPR≠1 的屏幕上位置会整体偏移（这是 canvas 绘制最常见的错误）。

### 3.3 绘制内容

1. **全宽水平虚线**
   - `ctx.moveTo(chartArea.left, y)` → `ctx.lineTo(chartArea.right, y)`
   - `ctx.setLineDash([4, 4])`、`lineWidth: 1`
   - 颜色：**中性**（Q2 决定与系列无关）→ 用 `themeColors().axisTick`（已有主题感知），alpha 约 0.55~0.7
   - 必须 `ctx.save()` / `ctx.restore()` 包裹，避免 `setLineDash` 污染后续绘制
2. **Y 轴端数值气泡**
   - 位置：`const axis = chart.scales.y; const edge = axis.position === 'right' ? chartArea.right : chartArea.left;` → **动态取边**（这样"Y 轴移到右侧"那个任务落地后无需改本插件）
   - 气泡横向伸出绘图区，落在轴标签区；横向对齐：轴在左 → 气泡右边缘贴 `chartArea.left`；轴在右 → 气泡左边缘贴 `chartArea.right`
   - 文本：**必须复用与刻度同一个格式化函数**（见 §5 Step C-2 抽出 `fmtAxisPct`），否则气泡与刻度会漂移
   - 垂直**钳制**在画布内：`y = Math.min(Math.max(y, pad), canvasHeight - pad)`，防止在顶/底边溢出画布
   - 圆角矩形用 `ctx.roundRect(...)`（Chromium ≥99 支持；本项目已依赖 `:has()`/`color-mix()`，无需降级；若要保险可加 `if (ctx.roundRect) ... else arcTo` 兜底）
   - 配色**复用 tooltip token**：底 `tooltipBg`、边 `tooltipBorder`、字 `tooltipBody` → 双主题自动跟随，零新 token
3. **可测性挂钩（有意为之）**：在绘制时把算出的文本写到 `chart.$crosshairLabel = text`。这是给 `verify_ui.py` 用的**唯一可客观断言点**（画布像素无法读文本）。约 1 行，成本极低，请在代码注释里写明用途。

### 3.4 与既有交互的共存

| 交互 | 共存方式 |
|---|---|
| tooltip（`mode:'index'`） | 并存。横线画在 tooltip 之下；tooltip 显示日期 + 各系列原价/% |
| 缩放/平移（ctrl+滚轮 / ctrl+拖拽） | `afterEvent` 在拖拽时也会收到 mousemove → 横线跟随。**见 R3**（拖拽期间多一次 `draw()`，需实测是否掉帧） |
| 触屏 | `touchmove` 也走同一路径（横线跟随手指）；`touchend` 清除。⚠️ tooltip 在触屏下被禁用，此时**只有横线 + 气泡**，需目视确认读数仍够用 |
| 主题切换 | `chart.draw()` 由既有 `renderMainChart()` 重建实例；气泡颜色走 `themeColors()` → 自动跟随，无需额外处理 |

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/app.js` | **改（唯一）** | 823 → ≈880 行：① 抽出 `fmtAxisPct(value)` 并让刻度回调复用它；② 新增内联插件 `hoverCrosshair`（`afterEvent` 取鼠标 Y + 节流重绘；`afterDatasetsDraw` 画全宽虚线 + 轴上气泡）；③ `renderMainChart()` 的 `new Chart(...)` 加 `plugins: [hoverCrosshair]` |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **改（扩展，禁止覆盖）** | **当前 400 行**（写本计划时为 387，执行者跑玻璃化任务时已扩到 400）→ ≈455 行：追加 crosshair 断言。⚠️ 沿用其既有 `check(...)` + `assert_viewport()` + `main()` 框架，**只做增量、不动既有断言** |
| `tasks/2026-09-11-chart-hover-crosshair/plan.md` | 新增 | 本文件 |

**预计不动**：`web/templates/index.html`、`web/static/style.css`、`web/app.py`、`tests/*`、`src/*`、`config.json`、`data/*`、`context/*`、`alerts/*`、`reports/*`。

---

## 5. 实现步骤（每步可独立验证）

### Step C-1 · 先扩展验收脚本（护栏先行）

在 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` 上**追加**（不覆盖）：

| # | 断言 | 目标 |
|---|---|---|
| CS-1 | 插件已挂载：`window.Chart.getChart($('#chart-main')).options.plugins.hoverCrosshair` 存在或 `chart.$crosshairLabel !== undefined` 可达 | true |
| CS-2 | **像素对比（核心判据）**：`page.mouse.move(cx, y1)` 取 `canvas.toDataURL()` → `page.mouse.move(cx, y2)` 再取 → **两者不同** | 不同 |
| CS-3 | **移出即隐藏**：`page.mouse.move` 到绘图区外的页面区域 → 画布数据与"进入绘图区前"的基线**相同** | 相同 |
| CS-4 | 气泡文本 = 轴刻度格式化函数对该高度的输出：读 `chart.$crosshairLabel`，用 `chart.scales.y.getValueForPixel(y)` 反推，断言格式为 `[+-]?\d+\.\d%` | 匹配 |
| CS-5 | **回归**：`scrollHeight` @1920×1080 | ≤1240 |
| CS-6 | **回归**：tooltip 仍工作（悬停后 tooltip 元素/`chart.tooltip.opacity > 0`） | 不变 |
| CS-7 | **回归**：类别 tab 切换后新实例仍带 crosshair（重建后不丢） | true |

**接入方式（已核对脚本现有结构，照此接）**：

- 脚本已有统一断言助手 `check(cond, label, actual=None, expect=None)`（`verify_ui.py:34`）、按视口断言的 `assert_viewport(w, h, m)`（`:190`）、取数函数 `measure(page, url, w, h)`（`:174`）与入口 `main()`（`:229`）。**新增断言一律走 `check()`**，保持输出格式与退出码语义一致。
- 新增函数 **`assert_crosshair(page)`**（需要 Playwright 的 `page` 对象做 `page.mouse.move`），在 `main()` 里 **1920×1080 那一轮之后**调用一次即可 —— 鼠标交互与视口无关，无需三视口各跑一遍。
- ⚠️ **不要往 `MEASURE_JS` 里堆**：crosshair 需要 `chart.chartArea`、`chart.$crosshairLabel`、`canvas.toDataURL()`，请用**独立的小 `page.evaluate(...)` 片段**取，避免既有的 `MEASURE_JS`（已 ≈170 行）继续膨胀。
- 画布指纹统一用 `canvas.toDataURL()` 在 `page.evaluate` 内返回字符串 —— 比截图比对稳定，不受外部渲染与动画影响。
- **`chart` 实例取法**：`window.Chart.getChart(document.getElementById('chart-main'))`。

- **验证**：先跑一次 → **CS-1~CS-4 应 FAIL、CS-5~CS-7 应 PASS**（证明断言真在测东西，不是恒真）。

### Step C-2 · 抽出轴格式化函数（防漂移）

- 把 `app.js:382` 内联的 `(value >= 100 ? "+" : "") + (value - 100).toFixed(1) + "%"` 抽成具名函数 `fmtAxisPct(value)`。
- **`scales.y.ticks.callback` 与气泡文本都调用它**（单一事实来源）。
- **验证**：目视轴刻度**与改动前逐字一致**（如 `+0.0%`、`-3.1%`）；CS-5 仍 PASS。

### Step C-3 · 写入插件（取鼠标 Y + 节流重绘）

- 按 §3.2 伪代码实现 `afterEvent`：`mouseout`/`touchend` 清除；仅绘图区内且 Δy ≥ 1px 才 `chart.$crossY = e.y; chart.draw();`。
- **验证**：CS-1 PASS；手动悬停上下移动，横线**实时跟随**（不卡住、不跳）。

### Step C-4 · 画全宽虚线 + 轴上百分比气泡

- 按 §3.3 实现 `afterDatasetsDraw`；`save/restore` 包裹；气泡垂直钳制；写 `chart.$crosshairLabel`。
- **验证**：CS-2 / CS-3 / CS-4 PASS。

### Step C-5 · 挂到图表实例

- `renderMainChart()` 的 `new Chart(canvas, {...})` 中加 `plugins: [hoverCrosshair]`（**内联插件，不 `Chart.register`** —— 避免影响全局、避免与其他图冲突）。
- **验证**：CS-7 PASS（切 tab 重建后仍生效）；Console 0 error。

### Step C-6 · 全量回归 + 收尾

- `verify_ui.py` 退出码 **0**（全部断言绿）。
- `venv/Scripts/python -m pytest tests/ -v` 全绿（无 Python 变更，应无变化）。
- 目视：双主题 × 三视口 × 触屏模拟（见 §7）。
- 追加 `docs/pitfalls.md`：**Chart.js 同 x 索引内纵向移动不触发自动重绘**（必须 `chart.draw()`）、**插件内不要乘 DPR**。
- 写 `tasks/2026-09-11-chart-hover-crosshair/journal.md`。

---

## 6. 复现路径、测量点与坐标空间说明

### 6.1 复现路径（精确步骤）

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8017`
   ⚠️ **每次验证换新端口**（8017 → 8018 → 8019），同端口会命中陈旧 JS 副本产生假阴性（`docs/pitfalls.md`「跨端口 CSS 缓存假阴性」同理适用于 `app.js`）。
   💡 也可直接用 `verify_ui.py`，它**自动挑空闲端口**。
3. 打开 `http://127.0.0.1:8017/`，硬刷新 `Ctrl+Shift+R`。
4. 移到「市场趋势」卡的图表上，在绘图区内**上下移动鼠标**。
5. **修复前**：只有 tooltip 跟随（且 tooltip 只在 x 变化时明显更新），**没有任何水平参考线**；纵向移动时画面几乎无反馈。
6. **修复后**：一条全宽水平虚线跟随鼠标高度；Y 轴端有百分比气泡实时更新；鼠标移出绘图区两者消失。
7. DevTools Console 无 error；缩放（ctrl+滚轮）与平移（ctrl+拖拽）仍可用。

### 6.2 关键测量点

| 测量点 | 取法 | 修复前 | 目标 |
|---|---|---|---|
| 绘图区范围 | `chart.chartArea` → `{left, right, top, bottom}` | — | 记录，作为鼠标落点基准 |
| 鼠标落点 | `page.mouse.move(cx, cy)`，cy 取 `chartArea.top + h*0.3` / `h*0.7` | — | 两次取值必须产生不同画布 |
| **画布像素指纹** | `canvas.toDataURL()` 前后对比 | 两次相同（无横线） | 两次**不同**（横线跟手） |
| 气泡文本 | `chart.$crosshairLabel` | `undefined` | 匹配 `[+-]?\d+\.\d%` |
| 反推一致性 | `yScale.getValueForPixel(y)` → `fmtAxisPct(...)` | — | 与 `$crosshairLabel` 一致 |
| 轴侧动态性 | `yScale.position === 'left' ? chartArea.left : chartArea.right` | — | 气泡贴在**当前轴侧**（为"轴移到右侧"预留） |
| 气泡垂直钳制 | 把鼠标移到 `chartArea.top` / `chartArea.bottom` 边缘 | — | 气泡**不溢出画布**（`0 ≤ y ≤ canvasHeight`） |
| 实例唯一性 | `Object.keys(Chart.instances).length` | 1 | 仍为 **1**（切 tab 不泄漏实例） |
| **布局回归** | `scrollingElement.scrollHeight` | **1235** | ≤1240 |
| **溢出回归** | `scrollWidth === innerWidth` | true | true |
| tooltip 回归 | `chart.tooltip.opacity > 0`（悬停后） | true | 仍 true |

### 6.3 坐标空间说明（canvas 版的 "box-sizing"）

本任务不改 CSS 盒模型，但有一个**等价风险点**必须写清：

1. **插件里用的是 CSS 像素坐标**。`chart.chartArea`、`axis.getPixelForValue()`、`event.y` 全部是 CSS 像素；Chart.js 已对绘图上下文执行过 `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)`。
2. **绝对不要在插件里乘 `devicePixelRatio`**。若手动乘，在 DPR=2 的屏幕上横线会整体偏移一倍 —— 而 `verify_ui.py` 跑在 **DPR=1** 下**测不出来**（这是个隐蔽坑）。**因此：新增一次 DPR=2 的人工目视复核**（DevTools 切设备像素比，或 `device_scale_factor: 2` 跑一次截图），确认横线位置与鼠标一致。
3. **不要改 `canvas.width/height`**（位图尺寸）。§2 已确认位图尺寸由容器高度 + `maintainAspectRatio:false` 决定；插件只应绘制，不应触碰尺寸，否则会破坏既有的"位图 == 显示尺寸"验收。
4. `ctx.save()/restore()` 必须成对：`setLineDash` / `lineWidth` / `textAlign` / `textBaseline` 任一泄漏都会污染后续绘制（表现为曲线或 tooltip 异常）——**表现是"别的地方坏了"，极易误判为本功能无关**。
5. `roundRect` 属路径 API，调用后需 `ctx.beginPath()` 重新开始，避免与前面的路径粘连。

---

## 7. 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 横线全宽（`chartArea.left → chartArea.right`）；气泡贴在轴侧、垂直钳制在画布内；`scrollHeight` 仍 ≤1240；`.row-kpi` 5 列同排等既有布局不变 |
| **1280×720** | 主图容器高度 300px（`clamp`）→ 可悬停高度较小，横线与气泡**不重叠到轴标签**；`scrollWidth === 1280` 无横向溢出 |
| **375×812** | 单列；`touchmove` 跟随手指，`touchend` 清除；tooltip 在触屏被禁用，此时**只有横线 + 气泡**，需目视确认读数够用；`scrollWidth === 375` |
| **DPR=2** | **新增人工复核项**：横线位置与鼠标一致（验证 §6.3 第 2 条未被违反） |
| **双主题（dark / light）** | 气泡配色随 `themeColors()` 变化；暗色下横线不与深背景融为一片（若看不清，把 `axisTick` 的 alpha 提到 0.75） |
| **缩放/平移中** | ctrl+拖拽平移期间横线仍跟随且**无明显掉帧**（见 R3） |

---

## 8. 验证命令

引用 `docs/commands.md` 的既有命令：

```bash
# 【主验收】UI 断言（自动挑空闲端口起服务；退出码 0/1）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 手动查看（每次换新端口）
venv/Scripts/python -m uvicorn web.app:app --port 8017

# 回归：无 Python 逻辑变更，应保持全绿
venv/Scripts/python -m pytest tests/ -v
```

**验收判据**：`verify_ui.py` 退出码 **0**（CS-1~CS-7 全绿）+ `pytest tests/ -v` 全绿 + §7 的 DPR=2 目视复核通过。

---

## 9. 风险与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R1** | **纵向移动不触发自动重绘 → 横线"卡住"** | **高** | Chart.js 仅在激活元素集合变化时自动重绘；同一 x 索引内纵向移动集合不变。**必须**在 `afterEvent` 里手动 `chart.draw()`。这是本功能最核心的机制，也是"看起来没实现"的头号原因 |
| **R2** | 插件内误乘 `devicePixelRatio` | **高** | Chart.js 已对 ctx 做过 DPR 变换；再乘一次会让横线偏移一倍。⚠️ **`verify_ui.py` 跑在 DPR=1，测不出来** → 必须加 DPR=2 人工复核（§7） |
| **R3** | 平移/缩放期间每帧多一次 `chart.draw()` | **中** | ctrl+拖拽时 mousemove 持续触发，横线重绘叠加在平移重绘上。对策：1px 节流已能削掉大部分；若实测掉帧，用 `requestAnimationFrame` 合并重绘，或平移期间暂停横线 |
| **R4** | 气泡溢出画布 / 与轴标签重叠 | **中** | 顶/底边缘需垂直钳制；气泡横向伸出绘图区时会盖住该高度的轴刻度数字 —— 这是设计取舍（气泡优先），需目视确认可接受 |
| **R5** | 与 tooltip 层叠顺序错误 | **中** | 必须用 `afterDatasetsDraw`（而非 `afterDraw`），否则横线会盖住 tooltip。验证：悬停时 tooltip 应完整可见 |
| **R6** | `ctx` 状态泄漏导致"别处坏了" | **中** | `setLineDash`/`lineWidth`/`textAlign` 必须 `save()/restore()` 成对。表现是曲线或 tooltip 异常，**极易误判为无关** |
| **R7** | 与 Y 轴移右侧任务耦合 | **低** | 本插件**动态读 `yScale.position`** 决定气泡贴哪侧 → 轴移到右侧后自动跟随，无需改本插件。**请勿写死 `chartArea.left`** |
| **R8** | 触屏下 tooltip 被禁用，只剩横线 | **低** | 可接受；若触屏下读数不够，后续可考虑触屏也启用 tooltip（属另一件事） |
| **R9** | 反复切 tab 造成实例泄漏 | **低** | `renderMainChart()` 已有 `charts.main.destroy()`；验证 `Object.keys(Chart.instances).length === 1` |
| **R10** | `roundRect` 兼容性 | **低** | Chromium ≥99 支持；本项目已依赖 `:has()`/`color-mix()` → 无需降级。若要保险，可加 `arcTo` 兜底分支 |

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/app.js` | 823 → ≈880 行（+≈55 行：`fmtAxisPct` 抽出 + 插件 + 1 行 `plugins`；−≈1 行内联格式化） |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 400 → ≈455 行（+`assert_crosshair(page)` 与 CS-1~CS-7 断言） |
| 新增 | `tasks/2026-09-11-chart-hover-crosshair/plan.md` | 本文件 |
| 新增 | `tasks/2026-09-11-chart-hover-crosshair/journal.md` | 执行完成后写 |
| 新增 | `docs/pitfalls.md` 追加段 | 2 条（R1 重绘机制 / R2 DPR） |

**净代码变更估算**：约 **+55 / −5 行**，**全部集中在 `app.js` 一个文件**（不含本计划文档与 journal）。

**明确不改**：`index.html`、`style.css`、`web/app.py`、`tests/*`、`src/*`、`config.json`、生成物。

---

## 11. 不做什么

- **不加垂直竖线**（横向-only，按需求方原话）。
- 不改 tooltip 内容与样式。
- 不改 Y 轴刻度口径（仍是归一化 % 轴）与 Y 轴位置（左侧）。
- 不引入 `chartjs-plugin-annotation` 或任何新依赖。
- 不 `Chart.register` 全局插件（用内联 `plugins: [...]`，避免影响其他图/未来图）。
- 不动 DOM / CSS（本功能纯 canvas 绘制）。
- 不给自选列表加参考线（已无 Chart.js 实例）。

---

## 12. 确认

- [ ] 人已审阅本计划
- [ ] 已知悉横线取的是**鼠标 Y**（非数据点 Y），因此是**一条中性色线**、与系列无关（Q2）
- [ ] 已知悉横线读的是**涨跌幅百分比**，具体股价仍看 tooltip（Q4）
- [ ] 已确认**不加垂直竖线**（如需，约 5 行可加）
- [ ] 已确认插件**动态读 `yScale.position`**，与"Y 轴移到右侧"任务互不阻塞（R7）
- [ ] 已确认**不引入新依赖**，用内联插件实现
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**（当前 400 行，沿用其 `check()` + `assert_viewport()` + `main()` 框架）
- [ ] 已确认**任务顺序**：**玻璃化任务落地后**再开工本任务（`verify_ui.py` 是两任务共用活跃文件，避免并发编辑被 auto-commit cron 误提交）
- [ ] 已确认新增 **DPR=2 人工目视复核**（R2：DPR=1 的自动化测试查不出误乘 DPR）
- [ ] 已确认布局回归护栏（`scrollHeight ≤ 1240`、无横向溢出、0 console error）不得回退
