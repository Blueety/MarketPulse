# 计划：为宏观数据页主图加悬停水平参考线（crosshair）

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-macro-chart-crosshair/`
- **触发**：需求方「顺便给宏观数据页面的这个图表也加上跟随鼠标的那个横线」
- **前置**：`2026-09-11-chart-hover-crosshair` ✅（首页已实现）· `2026-09-14-macro-page` ✅（宏观页已存在）
- **性质**：纯前端（新增 1 个共享 JS + 2 个 html 各加 1 行 `<script>` + 2 处接线 + 自定义格式化器）

---

## 1. 结论先行

**不能把首页插件直接搬过去 —— 它的读数格式化器与宏观图的轴语义不匹配，照搬会输出荒谬数字。**

```
首页 fmtAxisPct(v) = (v >= 100 ? '+' : '') + (v - 100).toFixed(1) + '%'
                     ↑ 这是「相对 100 的偏离百分比」，专为归一化涨跌幅轴设计
```

宏观主图有**两种轴语义**（`macro.js:244-246`）：

```js
var data = multi ? normalize(raw)                        // 全部对比：起点 = 100 的指数
                 : raw.map(v => displayValue(k, v));      // 单变量：真实价格
```

→ 若照搬 `fmtAxisPct`，读数会变成：

| 模式 | 轴值 | `fmtAxisPct` 输出 | **正确应为** | 判定 |
|---|---|---|---|---|
| 美元指数 | 99.64 | `-0.4%` | `99.64` | ❌ 把价格读成偏离 |
| 10Y 美债 | 4.987 | `-95.0%` | `4.99%` | ❌ |
| 原油 | 103.95 | `+4.0%` | `103.95` | ❌ |
| **黄金** | **4386.60** | **`+4286.6%`** | `4386.60` | ❌ **荒谬** |
| 全部对比 | 122.8 | `+22.8%` | `122.80`（指数）| ⚠️ 语义可辩 |

**黄金会显示 `+4286.6%`** —— 这是本任务必须避免的头号后果。

---

## 2. 实测证据

### 2.1 首页插件拿不到（`macro.html` 不加载 `app.js`）

```text
app.js:709   const hoverCrosshair = { id: 'hoverCrosshair', … }   ← app.js 内定义
app.js:867   plugins: [hoverCrosshair]   // 内联插件仅挂本实例（不 Chart.register，避免影响全局）
```

```text
macro.html:L21   <script src="chart.js CDN">
macro.html:L115  <script src="/static/macro.js">      ← 只此两个，无 app.js
index.html:L23   <script src="chartjs-plugin-zoom">
index.html:L195  <script src="/static/app.js">        ← 首页才有
```

→ **插件在宏观页完全不存在**（`Chart.register` 是刻意没做的，见 `app.js:706` 注释）。

### 2.2 两页图表配置的差异

| 项 | 首页（`app.js`） | 宏观页（`macro.js`） |
|---|---|---|
| 插件挂载 | **顶层** `plugins: [hoverCrosshair]`（`:867`）| `plugins` 在 **`options` 内**（`:270`，目前只有 `legend`/`tooltip`）|
| y 轴侧 | `position: "right"`（`:633`）| `position: "right"`（`:295`）✅ **一致** |
| 轴语义 | 归一化涨跌幅（`fmtAxisPct` 的 `-100` 偏移）| **单变量=真实价 / 全部对比=起点100** |
| 单位表 | — | `PICKS[].unit`：美元 `""` / 10Y `%` / 原油 `$` / 黄金 `$` |
| 已有 helper | `themeColors()` `withAlpha()` `cssVar()` `fmtAxisPct()` | `cssVar` `fmt` `fmtSigned` `displayValue` `unitOf` `toYieldDisplay` / **无 `themeColors` `withAlpha`** |

### 2.3 首页 crosshair 的现有断言（**搬走后必须仍绿**）

| 断言 | 位置 | 依赖 |
|---|---|---|
| CS-1 | `verify_ui.py:452-454` | `"hoverCrosshair" in c.config.plugins` → **插件 `id` 不能改** |
| CS-4 | `verify_ui.py:479-486` | `c.$crosshairLabel == fmtAxisPct(c.scales.y.getValueForPixel(c.$crossY))` → **依赖全局 `fmtAxisPct` 仍是全局函数** |
| CS-6 | `verify_ui.py:468-473` | tooltip 与横线并存 |
| CS-7a/7b | `verify_ui.py:503-505` | 切 tab 重建后仍带插件 |
| F-7a | `verify_ui.py:588-603` | 轴在右时 `$crosshairLabel` 仍产生 |

⚠️ **任何改动都不能破坏这 5 条** —— 它们锁定了三条硬契约：**插件 `id` 为 `hoverCrosshair`** / **`$crosshairLabel` 挂钩存在** / **`fmtAxisPct` 保持全局可调用**。

---

## 3. 两个必须避开的陷阱

### 陷阱 1 · 格式化口径（本任务核心）

宏观页的读数**必须按模式 + 品种分派**，不能硬编码百分比：

```text
全部对比 → 指数值，2 位小数（如 122.80）
单变量   → 真实价 + 品种单位（美元 99.64 / 10Y 4.987% / 原油 $103.95 / 黄金 $4386.60）
```

### 陷阱 2 · `displayValue` 二次换算（极易踩）

`macro.js:246` 在**建数据集时**已经对 10Y 做过口径处理：

```js
data = multi ? normalize(raw) : raw.map(function (v) { return displayValue(k, v); });
```

→ **Y 轴上的值已是"显示值"**。crosshair 格式化器拿到的是轴值，**绝不能再调一次 `displayValue(k, v)`**，否则 `^tnx` 会被 `toYieldDisplay` 除两次（4.987 → 0.4987）。

✅ 正确做法：**直接格式化传入的 `v`**，只补单位。

---

## 4. 方案：抽共享插件 + 可注入格式化器

### 4.1 为什么抽共享而不是在 `macro.js` 里复制

逻辑双份的代价：将来改一处忘一处（本次就出现了一个现成的例子 —— 插件里的 `themeColors`/`withAlpha` 在 `macro.js` 里根本不存在，复制就得再抄两份）。

与项目既有纪律一致：上一轮刚把 shell 抽成 `_topbar.html` + `_sidebar.html` 达到「单一来源」。

### 4.2 新建 `web/static/chart-crosshair.js`

**契约（必须满足，否则破首页断言）**：

| # | 契约 |
|---|---|
| 1 | 暴露 `window.hoverCrosshair`，且 **`id === 'hoverCrosshair'`**（CS-1 / CS-7b）|
| 2 | 仍是**内联插件**（不 `Chart.register`），由各页挂到自己的实例上 |
| 3 | 仍写 `chart.$crosshairLabel`（CS-4 / F-7a）|
| 4 | 气泡位置仍**动态读 `axis.position`**（`app.js:755`），勿写死 left |
| 5 | 仍用 `afterEvent` + 1px 节流 + `chart.draw()`（勿用 `update()`）|
| 6 | 仍画在 `afterDatasetsDraw`（线在数据之上、tooltip 之下）|

**新增能力：格式化器可注入**

```text
// 优先取实例级配置，回落全局默认（保持首页行为不变）
formatter = chart.options.plugins.hoverCrosshair.formatter
            || chart.config.plugins.hoverCrosshair.formatter
            || window.__defaultCrosshairFormatter
```

⚠️ 格式化器签名需带上下文，因为宏观页要按「单变量/多线」分派：
```text
formatter(value, chart)  →  string
```

**同时搬 `themeColors()` / `withAlpha()`**（插件依赖它们；`macro.js` 没有）—— 建议作为 `window.mpThemeColors` / `window.mpWithAlpha` 暴露，`app.js` 改为引用（或保留本地实现 + 共享文件内自带一份，二选一，见 §6 R3）。

### 4.3 两页接线

`index.html` / `macro.html` 各加一行，**必须在该页业务脚本之前**：

```html
<script src="/static/chart-crosshair.js?v={{ asset_v }}"></script>
<script src="/static/app.js?v={{ asset_v }}"></script>      <!-- 或 macro.js -->
```

**首页**（`app.js`）：删掉 `const hoverCrosshair = {...}` 定义（`:706-769`），保留 `plugins: [hoverCrosshair]` 写法；格式化器保持 `fmtAxisPct`（行为逐字节不变）。

**宏观页**（`macro.js`）：
- 顶层加 `plugins: [window.hoverCrosshair]`（与首页一致；注意目前 `plugins` 在 `options` 内，**两者可并存**）
- 新增 `macroCrosshairFormatter(v, chart)`：

```text
function macroCrosshairFormatter(v, chart) {
  var multi = state.mode === 'all';        // 与建图时同一判据
  if (multi) return fmt(v, 2);             // 指数：122.80
  var k = state.activeKey;
  var u = unitOf(k);                       // '' / '%' / '$'
  var d = (k === '^tnx') ? 3 : 2;          // 收益率 3 位小数
  var s = fmt(v, d);                       // ★ 直接格式化，勿再 displayValue
  return (u === '$') ? u + s : s + u;      // $ 在前，% 在后
}
```

---

## 5. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/chart-crosshair.js` | **新建** | 抽出的插件 + `themeColors`/`withAlpha` + 可注入 formatter |
| `web/static/app.js` | 删约 64 / +约 6 行 | 删本地插件定义，改为引用共享；`fmtAxisPct` **保留原地**（CS-4 依赖）|
| `web/static/macro.js` | +约 22 行 | 顶层挂插件 + 新增 `macroCrosshairFormatter` |
| `web/templates/index.html` | +1 行 | 在 `app.js` 前引 `chart-crosshair.js` |
| `web/templates/macro.html` | +1 行 | 在 `macro.js` 前引 `chart-crosshair.js` |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +约 45 行 | 新增 MX-1~MX-6，并**回归 CS-1~7 / F-7a** |
| `tasks/2026-09-14-macro-chart-crosshair/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 1 条 | 见 §7 |

**不改**：`web/app.py` / `src/*` / `style.css`（crosshair 是 canvas 绘制，不走 CSS）/ `macro.html` 的模块结构。

---

## 6. 实现步骤

### X-0 · 基线（**必须先跑，且必须记录**）

```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # 记录 EXIT 与断言总数
venv/Scripts/python -m pytest tests/ -v
```
⚠️ 首页 `assert_crosshair` 与 `assert_fidelity(F-7a)` 是**本次的回归护栏**，改动前先确认它们全绿。

### X-1 · 抽 `chart-crosshair.js`

把 `app.js:706-769` 的插件对象**原样搬出**（保持 `id`/`$crossY`/`$crosshairLabel`/节流/轴侧动态全部不变），只把读数那一行改成走可注入 formatter：

```text
const f = resolveFormatter(chart);
const text = f ? f(axis.getValueForPixel(y), chart) : fmtAxisPct(axis.getValueForPixel(y));
```

⚠️ **兜底必须是 `fmtAxisPct`** —— 保证首页即使没配 formatter 也行为不变。

**验收**：`verify_ui.py` 的 CS-1~CS-7 / F-7a **必须仍全绿**（此步不改任何行为）。

### X-2 · 两页接线

`index.html` / `macro.html` 各加 1 行 `<script>`（**在业务脚本之前**）。

⚠️ 顺序错了会 `undefined` 且**不报错**（`plugins:[undefined]` 被 Chart.js 静默忽略）→ 表现为"横线没出来"，很容易误判为插件 bug。X-4 的 MX-1 就是防这个。

### X-3 · 宏观页格式化器

按 §4.3 实现。**重点自查陷阱 2**：格式化器内**不得**再调 `displayValue`。

### X-4 · 验证（MX 断言 + 首页回归）

| # | 断言 | 期望 |
|---|---|---|
| **MX-1** | `Chart.getChart('#macro-chart')` 的 `config.plugins` 含 `hoverCrosshair` | true（**防 script 顺序错**）|
| **MX-2** | 单变量·黄金：`$crosshairLabel === '4386.60'`（**不是 `+4286.6%`**） | 见 §1 |
| **MX-3** | 单变量·10Y：读数为 `4.987%`（3 位小数 + `%`） | true（**防二次换算**）|
| **MX-4** | 全部对比：读数为纯数字（如 `122.80`），**不含 `%`** | true |
| **MX-5** | 鼠标上下移动两次，`canvas.toDataURL()` 指纹不同（横线实时跟随） | 不同 |
| **MX-6** | 鼠标移出绘图区 → `$crossY === null`（横线隐藏） | true |
| **MX-7** | **切品种胶囊 / 切范围后重建实例仍带插件**（与 CS-7b 同源风险） | true |
| **MX-8** | **回归**：首页 CS-1~CS-7 / F-7a 全绿 | true |
| **MX-9** | **回归**：`/macro` console error 0、无横向溢出、`docH` 不变 | true |

⚠️ **先红后绿**：改动前先跑 MX-1/MX-2/MX-5，**必须 FAIL**（宏观页当前无插件）。
⚠️ **MX-2 是价值最高的一条** —— 它直接锁住 §1 那张表里荒谬的 `+4286.6%`。
⚠️ MX-5 用 `toDataURL()` 指纹（与 CS-2 同法），**不依赖气泡文字**，避免"横线没动但数字碰巧一样"。

### X-5 · 记录

- journal：formatter 分派表（4 品种 + 全部对比各一行实测读数）、script 顺序实测、首页回归结果。
- `docs/pitfalls.md` 追加：
  **同一插件跨页复用时，读数格式化器必须可注入** —— 首页 `fmtAxisPct` 是「相对 100 的偏离」，宏观页单变量是真实价格轴；硬编码格式化器会把黄金 `4386.60` 渲染成 `+4286.6%`，而且**页面不报错、只是数字荒谬**。

---

## 7. 风险

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **格式化器硬编码百分比 → 黄金显示 `+4286.6%`** | **高** | §3 陷阱 1 + §4.3 分派器 + **MX-2 断言** |
| **R2** | **格式化器内二次调 `displayValue` → 10Y 变 0.4987%** | **高** | §3 陷阱 2 + **MX-3 断言** |
| **R3** | 抽共享文件破坏首页 crosshair（CS-1~7 / F-7a 是护栏） | **高** | 插件 `id`/`$crossY`/`$crosshairLabel` 逐字节保持；兜底仍用 `fmtAxisPct`；X-1 后立刻回归 |
| **R4** | `<script>` 顺序错 → 插件 undefined 且**静默失效** | **中** | X-4 的 **MX-1** 专项断言 |
| **R5** | `themeColors`/`withAlpha` 在 `macro.js` 缺失导致插件报错 | **中** | 随插件一起搬入共享文件并暴露；X-4 断言 console error 0 |
| **R6** | 切品种/切范围重建实例后丢插件 | **中** | MX-7（与 CS-7b 同源风险，首页已验证过这一坑）|
| **R7** | 宏观页 `plugins` 在 `options` 内、首页在顶层，写法混用出错 | **中** | 统一用**顶层** `plugins: [...]`；两者并存合法 |
| **R8** | 触屏下 tooltip 被禁，横线是唯一读数 | **低** | 沿用既有 `touchend` 清线逻辑（插件原样保留）|
| **R9** | 改 `app.js` 引发首页其它断言回归 | **中** | X-0 记录基线，X-4 全量回归 |

---

## 8. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 新建 | `web/static/chart-crosshair.js` | 约 85 行（插件 64 + 两个 helper）|
| 修改 | `web/static/app.js` | −约 58 / +约 6 行 |
| 修改 | `web/static/macro.js` | +约 22 行 |
| 修改 | `web/templates/index.html` / `macro.html` | 各 +1 行 |
| 修改（扩展） | `verify_ui.py` | +约 45 行 |
| 新增 | `tasks/2026-09-14-macro-chart-crosshair/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/pitfalls.md` | 1 条 |

**净代码变更估算**：约 **+110 / −58 行**。

---

## 9. 不做什么

- **不 `Chart.register`** 该插件（首页刻意如此，避免影响全局实例）
- **不改插件 id**（`hoverCrosshair`，CS-1/CS-7b 依赖）
- **不动 `fmtAxisPct`**（保留在 `app.js` 全局，CS-4 依赖）
- **不改首页图表行为**（formatter 兜底即原逻辑，逐字节不变）
- **不改宏观图现有 tooltip / 轴 / 数据口径**
- **不在 `macro.js` 里复制一份插件**（逻辑双份会漂移）
- **不引入新依赖**（纯 vanilla，无 CDN）

---

## 10. 确认

- [ ] 已确认**不能照搬**首页插件：`fmtAxisPct` 是「相对 100 的偏离」，宏观单变量是真实价格轴
- [ ] 已确认**黄金会显示 `+4286.6%`** 是本任务的头号后果（MX-2 断言锁住）
- [ ] 已确认**格式化器内不得再调 `displayValue`**（Y 轴值已是显示值，二次换算会让 10Y 变 0.4987%）
- [ ] 已确认**抽共享文件**而非复制（与 shell 抽取同一纪律）
- [ ] 已确认三条硬契约不可破：插件 `id` = `hoverCrosshair`、`$crosshairLabel` 挂钩、`fmtAxisPct` 全局可调用
- [ ] 已确认 **`<script>` 顺序**（共享文件在前），且已知顺序错会**静默失效不报错**
- [ ] 已确认 X-0 基线必须先跑（首页 CS / F-7a 是回归护栏）
