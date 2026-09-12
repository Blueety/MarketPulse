# 计划：前端评审建议分诊与落地（8 条外部建议）

- **日期**：2026-09-12
- **任务目录**：`tasks/2026-09-12-frontend-polish/`
- **来源**：外部 UI/UX 评审给出的 8 条建议（评审方**未看过当前代码**，属通用建议）
- **架构师职责**：逐条比对实际代码 → 分诊「已实现 / 有效 / 与既有决策冲突」→ 只落地值得做的

---

## 1. 结论先行

**8 条建议中：4 条已实现、2 条有效、2 条有冲突需改造、1 条含隐藏依赖风险。**

| # | 建议 | 判定 | 处置 |
|---|---|---|---|
| 1 | 等宽字体 + `tabular-nums` | ❌ **已实现** | 不采纳。webfont 会引入新依赖 + FOUT 反效果 |
| 2 | Dark 玻璃 `backdrop-filter` | ❌ **已实现** | 不采纳。会覆盖双主题 glass token |
| 3 | 提升对比度 | ✅ **有效** | **采纳**（唯一真正的 CSS 缺陷） |
| 4 | 数字右对齐 | ❌ **已实现** | 不采纳 |
| 5 | 涨跌幅 Badge | ⚠️ **有严重冲突** | **改造后采纳**（新建命名空间 + 零增高） |
| 6 | 图表渐变填充 | ❌ **已实现** | 不采纳（现有实现比建议更正确） |
| 7 | 千分位格式化 | ⚠️ **有效但位置错** | **采纳但改位置**（是 `fmtNum` 不是 tooltip） |
| 8 | 骨架屏 | ✅ **有效** | **采纳** |

### 1.1 贯穿全局的硬约束：只剩 20px

实测基线（`verify_ui.py`，EXIT=0 / ALL PASSED）：

```text
1920×1080  scrollH = 1220    （护栏 ≤1240 → 余量 20px）
  .row-kpi 97 | .row-main 527 | .row-3 252 | .row-news 195 | .dash 1120
  #trend 527 = #watchlist-section 527   #overview 252 = #sectors 252 = #us-sectors 252
  #alerts 195 = #news 195               ← 并排两卡已等高（N-6 的 132px 生效）
1280×720  scrollH = 1935
375×812   scrollH = 2539
console error = 0
```

**任何增加行高的改动都必须先算账。** 尤其建议 5（Badge）—— 表格加一个带 padding 的胶囊，5 行就是 +20px 起步，**足以直接爆掉护栏**。

---

## 2. 逐条分诊（含代码取证）

### 建议 1 · 等宽字体 + `tabular-nums` —— ❌ 已实现

```css
/* style.css:14 */  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
/* style.css:85 */  body { font-variant-numeric: tabular-nums; }      ← 全局已开
/* style.css:322 */ .data-table td.num { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
```
`.kpi-val` / `.kpi-sub` / `.mini-val` / `.mini-sub` / `.bar-val` / `.date-chip` / `.alert-meta` 全部已用 `--mono`。

**为什么建议里的字体不能照抄**：`JetBrains Mono` / `Roboto Mono` 是 **webfont**，需要下载字体文件或引 CDN：
- 违反项目「零新增依赖」纪律；
- 引 CDN 有不可达风险（项目已有此 pitfall：CDN 不可达时图区降级）；
- 更要命的是 **FOUT/FOIT 会让数字在字体加载瞬间变宽/跳一下** —— 恰恰是这条建议要消除的反效果。

**可选微调（零成本）**：把 `DIN Alternate`（Windows / macOS 系统自带）加到 `--mono` 栈**最前**，金融数字观感更好且无网络依赖。

### 建议 2 · Dark 玻璃 `backdrop-filter` —— ❌ 已实现

玻璃化任务（`2026-09-11-glassmorphism-fix`）已完成，实测 backdrop 11/11 生效，`.pill` 已用 `var(--glass-border)`。

**为什么不能照抄建议里的硬编码值**：
```css
/* 建议写法 */ background: rgba(18,24,38,0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.08);
```
1. 它只有**一套值**，会直接覆盖双主题 `--glass-*` token 体系 → 浅色主题立刻崩。
2. 它会把**数据密集卡**（`#overview` / `#trend` / `#alerts`）也变成 0.75 alpha，推翻当初「数据密集卡用 `--glass-bg-strong`(dark α≈0.72) 保小字可读性」的决策。

→ 若要调强度，**改 `--glass-*` token 的值**，不要写死。

### 建议 3 · 提升对比度 —— ✅ 有效（采纳）

实测 token 值：

| token | Dark 值 | 在 `#0B0F14` 上的对比度 | WCAG AA(4.5) |
|---|---|---|---|
| `--text-primary` | `#E5E7EB` | 很高 | ✅ |
| `--text-secondary` | `#9BA3AF` | **≈7.7:1** | ✅ |
| **`--text-muted`** | **`#6B7280`** | **≈4.06:1** | ❌ **不达标** |
| Light `--text-muted` | `#9CA3AF` on `#F7F8FA` | 偏低 | ❌ |

`--text-muted` 承载的是**真实内容**而非纯装饰：`.ph-note`（「数据未接入」）、`.empty`、`.data-table td.empty`、`.ms-time`、`.link-btn`。

→ **采纳**：dark `--text-muted` `#6B7280` → **`#8E9BAE`**（≈6.9:1）。
⚠️ 同一 token 也用在 `.kpi-card::before` 色条与 `.ms-dot` 圆点上，提亮后装饰会变抢眼 → **必须目视**。

### 建议 4 · 数字右对齐 —— ❌ 已实现

```css
/* style.css:322-323 */ .data-table td.num { text-align: right }  .data-table th.num { text-align: right }
/* style.css:470 */      .bar-val { text-align: right }
```
`renderSector` / 自选列表 / 成交额列均已挂 `num` class。不采纳。

### 建议 5 · 涨涨幅 Badge —— ⚠️ 有严重冲突（改造后采纳）

**现状**：`.pos { color: var(--green) !important; font-weight: 600 }`，纯彩色文字，无底色。

**⚠️ 冲突一（会导致语义反转的严重 bug）**：项目里**已经有一个 `.pill`，而且它的涨跌配色是反的**：
```css
/* style.css:394-395 —— 这是「市场关系/相关性」语义 */
.pill.pos { color: var(--red); }     /* 正 r = 红 = 同向联动 = 风险 */
.pill.neg { color: var(--green); }   /* 负 r = 绿 = 对冲 */
```
**若直接给涨跌幅套 `.pill pos`，「+0.38%」会被染成红色 —— 涨变红，语义彻底反转。**
→ **必须新建独立命名空间 `.chg-pill`，绝不能复用 `.pill`。**
→ 且本项目是**绿涨红跌**（`.pos`=green），与建议里含糊的「浅红/浅绿底」方向不明，执行时以现有约定为准。

**⚠️ 冲突二（20px 余量）**：`#us-sectors` 表格 5 行，badge 若带来 `padding` + 行高增长，5 行 × ~4px = +20px → **正好爆掉护栏**。
→ 只能**零增高实现**：badge 用 `padding: 1px 6px`，同时把所在 `td` 的上下 padding 相应**减少**，保证行高不变。

**范围建议（保守）**：只加在**自选列表**与**A 股/美股板块表**的涨跌幅列；KPI 卡的 `kpi-sub` 保持彩色文字（KPI 卡 26px 主值 + 13px sub，加 badge 易撑高且视觉过噪）。

### 建议 6 · 图表渐变填充 —— ❌ 已实现，且现有实现更正确

```js
/* app.js:426-434 */
ds.fill = true;
ds.backgroundColor = function (ctx) {
  const ca = ctx.chart.chartArea;
  if (!ca) return 'transparent';
  const grad = ctx.chart.ctx.createLinearGradient(0, ca.top, 0, ca.bottom);   // ← 按实际绘图区
  grad.addColorStop(0, withAlpha(color, 0.26));
  grad.addColorStop(1, withAlpha(color, 0));
  return grad;
};
```

**关键差异**：建议里写的是 `createLinearGradient(0, 0, 0, 400)` —— **写死 400px**。而本项目用的是 `ca.top → ca.bottom` **按实际 chartArea 动态计算**。

写死 400 会重蹈本项目 **C2 教训（canvas 位图/显示失配）** 的覆辙：容器高度随断点变化（1920 下 527、1280 下 395、375 下 439）时，渐变范围与实际绘图区错位 → 渐变截断或填充不满。

→ 不采纳。若要调，只调 `withAlpha(color, 0.26)` 的 0.26 强度。

### 建议 7 · 千分位 —— ⚠️ 有效，但建议指错了位置

```js
/* app.js:135-138 */
function fmtNum(v, digits) { if (v == null) return "—"; return Number(v).toFixed(digits); }   // ← 无千分位
```

- ❌ **不是 tooltip**：tooltip 是 `fmtNum(rv,2) + " (" + fmtPct(parsed.y - 100) + ")"`（`app.js:470`），主轴是**百分比轴**（crosshair 任务已定调），千分位意义很小。
- ✅ **真正缺的是「最新价」**：`.mini-val` / `.data-table td.num` / KPI 的 `fmtNum(v,2)` → `26881.72` 应显示 `26,881.72`。

→ **采纳，但改在 `fmtNum`**。

⚠️ **两个连带风险**：
1. `fmtNum` 是**全局共用**（告警阈值 `fmtNum(a.threshold,1)`、风险因子 `fmtNum(f.value,1)`、tooltip 等都会被波及）→ 要么接受（数值大多 <1000 无变化），要么新增 `fmtNumSep()` 只给价格用。**建议新增函数、不改动 `fmtNum`**，影响面最小。
2. **宽度变化**：`26,881.72` 比 `26881.72` 多 1 字符。`.kpi-val`（26px，`nowrap + ellipsis`）与 `.mini-val`（17px）在窄视口可能触发省略号 → **必须三视口实测**。

### 建议 8 · 骨架屏 —— ✅ 有效（采纳）

现状：`index.html` 有 **5 处**「加载中…」纯文本（`renderOverview` 的 `app.js:184` 也有 `<p class="empty">加载中…</p>`）。

采纳理由：数据到达时行高突变会推挤下方内容（CLS）。

⚠️ **两个约束**：
1. **骨架条高度必须贴近真实行高**，否则等于把 CLS 从「小跳」变成「大跳」。真实行高参考：`.data-table td { padding: 7px 10px; font-size: 13px }` ≈ 30px/行。
2. **列数已不是 4**：visual-fidelity 已加图标列，现在是 **5 列**（`app.js:222/828` 的 `<td class="col-ico">`）→ 骨架屏 `colspan` 要用 **5**，沿用 4 会错位。

---

## 3. 要改的文件列表

| 文件 | 动作 | 对应建议 |
|---|---|---|
| `web/static/style.css` | 改 1 行 | 建议 3：`--text-muted` dark 提亮 |
| `web/static/style.css` | 新增约 12 行 | 建议 5：`.chg-pill`（**新命名空间**）+ 零增高 padding 对冲 |
| `web/static/style.css` | 新增约 18 行 | 建议 8：骨架屏 `skeleton` 脉冲动画 |
| `web/static/app.js` | 新增约 6 行 | 建议 7：`fmtNumSep()` 千分位（**不动 `fmtNum`**） |
| `web/static/app.js` | 改约 4 处 | 建议 7：价格调用点改用 `fmtNumSep` |
| `web/static/app.js` | 改约 3 处 | 建议 5：涨跌幅列包裹 `.chg-pill` |
| `web/templates/index.html` | 改 5 处 | 建议 8：「加载中…」→ 骨架屏，`colspan=5` |
| `web/static/app.js` | 改 1 处 | 建议 8：`renderOverview` 的加载态 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 扩展约 35 行 | P-1~P-7 断言 |
| `tasks/2026-09-12-frontend-polish/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 | 3 条 |

**不改**：`--glass-*` token、`--mono` 字体栈（除可选 `DIN Alternate`）、图表渐变、`buildLineOptions` 轴配置、`web/app.py`、`src/*`。

---

## 4. 实现步骤（每步可独立验证）

### P-0 · 基线（必做）

```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
→ 期望 EXIT=0 / ALL PASSED / scrollH@1920 = 1220 / console error = 0
```
**记录 1220 这个数字。后面每做完一步都要回来对比，涨幅必须 ≤ 20px（即 ≤1240）。**

### P-1 · 对比度（建议 3）

`style.css` dark 段：`--text-muted: #6B7280` → `#8E9BAE`。

**验证**：三视口 + 双主题目视 `.ph-note`（数据未接入）、`.empty`、`.ms-time`、`.kpi-card::before` 色条、`.ms-dot`；断言 `getComputedStyle(el).color` 等于新值。**重点看装饰元素是否被提亮得过于抢眼**。

### P-2 · 千分位（建议 7）

新增（**不改 `fmtNum`**，避免波及告警阈值 / 风险因子 / tooltip）：

```text
function fmtNumSep(v, digits) {
  if (v == null) return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
```

调用点（只改**价格**，不动百分比）：
- `renderOverview` 的 `.mini-val`（`app.js:204`）
- 自选列表最新价 `<td class="num">`（`app.js:830`）
- KPI 卡 `val: fmtNum(d.value, 2)`（`app.js:698`）—— ⚠️ **高风险点**，26px + nowrap + ellipsis

**验证**：断言 `26,881.72` 形态出现；三视口检查 `.kpi-val` / `.mini-val` **是否出现省略号**（`scrollWidth > clientWidth` 即溢出）。

### P-3 · 涨跌幅 Badge（建议 5）—— **最高风险步，放在最后单独验证**

1. **新建命名空间**（严禁复用 `.pill`）：
```text
.chg-pill { display: inline-block; padding: 1px 6px; border-radius: 4px;
            font-family: var(--mono); font-weight: 600; font-size: 12px; }
.chg-pill.pos { color: var(--green); background: color-mix(in srgb, var(--green) 14%, transparent); }
.chg-pill.neg { color: var(--red);   background: color-mix(in srgb, var(--red) 14%, transparent); }
```
2. **零增高对冲**：badge 所在 `td` 的 `padding: 7px 10px` → `4px 10px`（补回 badge 的 ~3px 上下 padding）。
3. 只包自选列表与板块表的涨跌幅列，**KPI 的 `kpi-sub` 不动**。

**验证**（这一步必须卡死）：
- `scrollH@1920` **必须仍 ≤ 1240**。超过就回退：减小 badge padding，或只给自选列表加、板块表不加。
- 断言涨为绿、跌为红（**明确验证没有撞上 `.pill.pos` 的反转配色**）。

### P-4 · 骨架屏（建议 8）

1. `style.css` 新增（约 18 行）：`.skeleton` + `.sk-row` + `@keyframes sk-pulse`；骨架条行高 **30px**（对齐 `.data-table td` 真实行高）。
2. `index.html` 5 处「加载中…」→ 骨架结构，**`colspan` 用 5**。
3. `app.js:184` 的 `renderOverview` 加载态同步。

⚠️ 加 `@media (prefers-reduced-motion: reduce)` 关闭动画。

**验证**：断网或限速下目视；断言加载态与数据态的 `.row-*` 高度差 **≤ 8px**（CLS 判据）；`console error = 0`。

### P-5 · 断言扩展（只扩展，禁止覆盖）

`verify_ui.py` 现含 bento + 玻璃化 + 纹理 + crosshair + V1~V5 + N-7，追加：

| # | 断言 | 期望 |
|---|---|---|
| **P-1** | dark `--text-muted` 计算值 | `#8E9BAE`（rgb 142,155,174） |
| **P-2** | 价格文本含千分位逗号（`.mini-val` / `td.num`） | 匹配 `/^\d{1,3}(,\d{3})*\.\d{2}$/` |
| **P-3** | `.kpi-val` / `.mini-val` 无溢出 | `scrollWidth <= clientWidth + 1` |
| **P-4** | `.chg-pill.pos` 的 color === `--green`、`.chg-pill.neg` === `--red` | true（**防撞名反转**） |
| **P-5** | 涨跌幅**未**复用 `.pill` | `.news`/表格内 `.pill` 计数 === 0 |
| **P-6** | 骨架屏 `colspan` | === 5 |
| **P-7** | **护栏**：`scrollH@1920 ≤ 1240`、`scrollWidth === innerWidth`、console error 0、backdrop 11/11 | 全部成立 |

⚠️ **先红后绿**：改码前先跑，P-2 / P-4 / P-6 必须是红的。

### P-6 · 记录

- `tasks/2026-09-12-frontend-polish/journal.md`（含每步后的 `scrollH` 实测值对比）。
- `docs/pitfalls.md` 追加：
  1. **同名 token 承载相反语义**：`.pill.pos`=红（相关性）vs `.pos`=绿（涨跌），新增组件必须独立命名空间，否则语义反转且**测试仍全绿**（断言查的是 class 存在，不是颜色）。
  2. **渐变不能写死像素范围**：`createLinearGradient` 必须按 `chartArea.top/bottom` 动态取，写死 400 在断点切换时错位（C2 同源）。
  3. **20px 余量下的增高型改动**：任何给表格行加 padding/徽章的改动，都要同步削减同量 padding 做对冲。

---

## 5. 验证命令（引自 `docs/commands.md`）

| 命令 | 何时跑 |
|---|---|
| `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | P-0 基线；**P-1~P-4 每一步之后** |
| `venv/Scripts/python -m uvicorn web.app:app --port 8019` | 目视（**换新端口**，防 CSS 缓存假阴性） |
| `venv/Scripts/python -m pytest tests/ -v` | 提交前（本任务改前端为主，后端零改动，跑全量防误伤） |

---

## 6. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **涨涨幅 Badge 撞 `.pill.pos` → 涨变红** | **高** | 新建 `.chg-pill`；P-4 断言直接比色值，不只查 class |
| **R2** | **20px 余量被撑爆** | **高** | P-3 零增高对冲；每步后跑 verify_ui 比对 `scrollH`；超限就缩范围 |
| **R3** | 千分位触发 KPI 省略号 | **中** | P-2 新增 `fmtNumSep` 不改 `fmtNum`；P-3 断言无溢出；1280/375 重点看 |
| **R4** | `--text-muted` 提亮后装饰元素过噪 | **中** | P-1 目视 `.kpi-card::before` / `.ms-dot`；必要时给装饰单独 token |
| **R5** | 骨架屏高度与真实行不匹配 → CLS 更严重 | **中** | 骨架条 30px 对齐 `td` 真实行高；P-4 断言高度差 ≤8px |
| **R6** | 骨架屏 `colspan` 沿用 4 → 错位 | **中** | 已是 5 列（visual-fidelity 加了图标列），P-6 断言 |
| **R7** | 照抄建议 1 引入 webfont | **中** | 明确不引；可选仅加系统字体 `DIN Alternate` |
| **R8** | 照抄建议 2 覆盖 glass token | **中** | 明确不改；要调只调 `--glass-*` 的值 |
| **R9** | 照抄建议 6 写死 400px 渐变 | **中** | 明确不改（现有动态实现更正确） |
| **R10** | `prefers-reduced-motion` 用户被动画影响 | **低** | 骨架屏加 reduce 媒体查询关闭 |
| **R11** | auto-commit cron 抢先提交 | **低** | 临时产物落 `$env:TEMP`；改完立刻 `git status` |

---

## 7. UI 类必填

### 7.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8019`（**新端口**）
3. `http://127.0.0.1:8019/`，硬刷新 `Ctrl+Shift+R`
4. 观察点：
   - **建议 3**：任何「数据未接入」灰字、`.empty`、侧栏底部时间 → 是否偏暗难读
   - **建议 5**：自选列表 / A股板块 / 美股板块的涨跌幅 → 现在是纯彩色文字，无底色
   - **建议 7**：市场概览 6 小卡的价格、自选列表最新价 → `26881.72` 无千分位
   - **建议 8**：刷新瞬间表格区域 → 闪现「加载中…」文字，且数据到达时下方内容被顶下去

### 7.2 关键测量点

| 测量点 | 取法 | 基线 / 目标 |
|---|---|---|
| **`scrollH` @1920×1080** | `document.documentElement.scrollHeight` | **1220 → 必须 ≤1240** |
| `.row-news` / `#alerts` / `#news` 高度 | `offsetHeight` | 195 / 195 / 195（并排等高，不得被打破） |
| `.row-3` / `#overview` / `#sectors` / `#us-sectors` | `offsetHeight` | 252（Badge 最易撑高这一行） |
| 涨跌幅 `td` 的 `padding-top/bottom` | `getComputedStyle` | 7px → **4px**（P-3 对冲后） |
| `.chg-pill` 的 `color` | `getComputedStyle` | pos=`--green`、neg=`--red`（**非反转**） |
| `.kpi-val` / `.mini-val` 溢出 | `scrollWidth > clientWidth` | **false** |
| `--text-muted`（dark）计算值 | `getComputedStyle(document.documentElement)` | `#8E9BAE` |
| 骨架 `colspan` | DOM 属性 | **5** |
| **回归**：`scrollWidth === innerWidth` / console error | — | true / **0** |

### 7.3 box-sizing 说明

`style.css:51` 全局 `* { box-sizing: border-box }`，无例外。

1. **`.chg-pill` 的 padding 计入其自身盒模型**：`padding: 1px 6px` + `font-size:12px` → 高度 ≈ 12×1.45 + 2 ≈ 19px，**超过 `td` 的 13px 文字行高** → 这就是为什么必须把 `td` 的 `padding` 从 7px 砍到 4px 做对冲（7+7+13=27 → 4+4+19=27，**行高守恒**）。
2. **border-box 下 `height`/`min-height` 含 padding**：骨架屏若用 `height: 30px` + padding，实际可视内容会被压缩 → 骨架条**不要加 padding**，直接用 `height` 表达行高。
3. **`display: inline-block` 的 badge 不影响表格布局宽度**（在 `td.num` 内右对齐即可），但会受 `td` 的 `white-space: nowrap` 保护，不会折行。
4. **千分位改变的是文本宽度而非盒模型**：`.kpi-val` 是 `nowrap + overflow:hidden + text-overflow:ellipsis`，多 1 个字符在窄视口（1280 下 KPI 卡 ≈185px）可能触到边界 → 这就是 P-3 断言存在的理由。

### 7.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 全部 4 项改动生效；`scrollH` **≤1240**；`.row-3` 三卡仍 252 等高；涨跌幅 badge 绿涨红跌；价格带千分位无省略号 |
| **1280×720** | `.row-3` 仍三列（断点在 768 才堆叠）；**KPI 卡变窄，千分位最易触发省略号 → 重点检查**；`scrollWidth === 1280`；badge 不折行 |
| **375×812** | 卡片单列；badge 在窄列内不溢出；骨架屏 5 列不横向溢出；`prefers-reduced-motion` 下无脉冲动画 |
| **双主题** | `--text-muted` 需**分别**定 dark/light 值；`.chg-pill` 用 `color-mix` 生成底色，**双主题自动生成**，需目视浅色下 `14%` 底是否过淡 |

---

## 8. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/style.css` | +约 32 / −2 行 |
| 修改 | `web/static/app.js` | +约 12 / −6 行 |
| 修改 | `web/templates/index.html` | +约 15 / −5 行 |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +约 35 行（P-1~P-7） |
| 新增 | `tasks/2026-09-12-frontend-polish/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/pitfalls.md` | 3 条 |

**净代码变更估算**：约 **+94 / −13 行**（不含断言）。

---

## 9. 不做什么

- 不引入 webfont（`JetBrains Mono` / `Roboto Mono`）与任何新依赖。
- 不改 `--glass-*` token、不动氛围层、不动玻璃化成果。
- 不改图表渐变实现（现有动态 `chartArea` 方案更正确）。
- 不改 `fmtNum`（新增 `fmtNumSep` 并列，避免波及告警阈值/风险因子/tooltip）。
- 不动 `web/app.py` 与 `src/*`（本任务纯前端）。
- 不给 KPI 卡的 `kpi-sub` 加 badge。

---

## 10. 确认

- [ ] 人已审阅分诊结论（**8 条里 4 条已实现、2 条与既有决策冲突**）
- [ ] 已确认 `.chg-pill` **必须新命名空间**，不得复用 `.pill`（R1）
- [ ] 已确认当前 `scrollH@1920 = 1220`，**余量仅 20px**（R2）
- [ ] 已确认千分位**新增 `fmtNumSep` 而非改 `fmtNum`**（R3）
- [ ] 已确认骨架屏 `colspan = 5`（已因图标列从 4 变 5）
- [ ] 已确认不引入 webfont、不改 glass token、不改渐变
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**
- [ ] 已确认每步之后都要重跑 verify_ui 比对 `scrollH`
