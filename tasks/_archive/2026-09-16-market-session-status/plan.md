# 实施计划：侧栏市场状态改为两行两市场（market session status，方案 C）

> **需求来源**：2026-09-16 20:41 用户截图 + 口述 ——「这个开盘时间，要写 A 股开盘还是美股开盘，谁开盘谁没有，现在是 A 股已经收盘了，但是美股还没开盘」
> **需求方裁定（2026-09-16 20:48，本版已 incorporate）**：
> ① 绿点语义 = **此刻有任一市场在交易**才亮；② 凌晨场景 A 股写 **「未开盘」**；③ 采用 **两行两市场** 呈现
> **产出**：架构师**实测后**出具（自起 uvicorn + Playwright 量 DOM 与**注入式 A/B**，非代码推演）；**未改动任何项目文件**
> **基线**：2026-09-16 20:52，`master` @ `403c47c`，工作区 **clean**（`git status --short` 空）
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 任务目标

**Goal**：侧栏底部的市场状态必须**逐市场指名**并**按该市场的真实交易时段**判定，而不是"今天是不是工作日"。

判定基准取用户截图的两个事实：**20:40 时 A 股已收盘、美股未开盘**。该时刻的正确显示为**两行**：

```
● A股 已收盘          ← 点熄灭（灰）
● 美股 未开盘          ← 点熄灭（灰）
  北京时间 20:40
```

而当前实现是单行 `● 市场已开盘`（绿点常亮）—— 见 §3。

---

## 2. 结论先行与方案选型

### 2.1 结论（证据见 §3）

1. **这是缺陷，不是文案偏好。** 当前 `open = 周一~周五`，**完全不判时刻**：工作日任意时刻（20:40、凌晨 3:00）都显示「市场已开盘」。
2. **方案 C 实测代价极低**：`style.css` **零改动**（`.ms-row` 已是 flex row，天然支持多行）；footer 45 → **63px**（+18）；`#sidebar` **不产生**纵向滚动条；页面 `scrollHeight` **完全不变**（`1216@1920`，护栏 1240 不受影响）；三档宽度**零横向溢出**。
3. **判定必须用各市场自己的本地时区**（A 股 `Asia/Shanghai`、美股 `America/New_York`），**绝不能换算成北京时间再比 `21:30`** —— 后者在 11 月夏令时结束时会**静默错一小时**（R2）。
4. **单点语义 → 双点映射**：用户裁定的"任一市场在交易才亮"落到两行结构上 = **逐市场着色**（该市场交易中 → 绿 `--green`；否则 → 灰 `--text-muted`）；"整体是否亮" ⇔ "至少一颗为绿"。**不新增第三个"总状态"点**。

### 2.2 方案对比（记录取舍）

| 方案 | 内容 | 实测代价 | 决策 |
|---|---|---|---|
| A 单行复合 | `● A股已收盘 · 美股未开盘` | 0 高度增量 | **否决**（用户已选 C） |
| B 动态主语单市场 | 只显示当前该关注的市场 | 最小 | **否决**：要"谁开盘谁没有"= 两个都得看到 |
| **C 两行两市场** | 每行一个市场 + 独立状态点，第三行保留北京时间 | **footer +18px、CSS 零改、零溢出（实测）** | **采用** |

### 2.3 明确不做

| 不做 | 理由 |
|---|---|
| 盘前 / 盘后（pre-market / after-hours）四态 | 16:00–21:30 显示「美股 盘前」会让人以为散户可交易，反而误导。侧栏是"一眼状态"，不是交易终端 |
| 交易日历 / 节假日判定（`is_market_holiday`） | 需引入日历依赖（违反"不引入新依赖"）。**已确认取舍**：节假日按工作日时段照常判定，记入 R3 |
| 硬编码"北京 21:30 / 22:30" | 夏令时炸弹，见 R2 |
| 第三个"总状态"点 | 双点已能表达"任一在交易"，第三个点无信息增量、且占高度 |

### 2.4 顺带发现（建议记入 journal / pitfalls，不改代码）

`tasks/2026-09-11-frontend-bento-redesign/plan.md:297` 写明本期按 **`is_market_holiday` 语义**实现，但 `grep -r is_market_holiday web/` **零命中** —— 当时承诺的交易日语义**从未落地**，这正是"休市"此前只在周末出现的根因。属**计划-实现漂移**；本方案把它扶正为"时段判定"，节假日部分明确排除（§2.3）。

---

## 3. 实测基线（本方案的事实依据，全部实跑）

### 3.1 复现路径（精确到操作）

1. `venv/Scripts/python -m uvicorn web.app:app --port 8000`
2. 浏览器打开 `http://localhost:8000/`（本次探针自选空闲端口 **7698** / **9754**）
3. 看**侧栏底部** `.sidebar-footer` 内：`● 市场已开盘` + `北京时间 HH:MM`
4. 在 20:44（A 股 15:00 已收盘、美股 21:30 未开盘）实测：**仍显示「市场已开盘」+ 绿点 `rgb(22, 160, 133)`**
5. 三页同现象：`/` · `/macro` · `/macro/cn` 状态文本**逐字相同**

探针：`%TEMP%\mp_probe_status.py` → `%TEMP%\mp-probe-status\measure.json`；方案 C 注入式 A/B：`%TEMP%\mp_probe_c.py` → `%TEMP%\mp-probe-c\measureC.json`（**均未落仓库**）。

### 3.2 渲染表现根因（用户实际看到什么）

北京时间 **20:44**：A 股已收盘、美股未开盘 → **两个市场都不可交易**，chip 却显示 **`● 市场已开盘`**（绿点 `rgb(22,160,133)`）。文案**无主语**，无法判断说的是哪个市场；且该状态在工作日**恒为真**（20:44 与 10:00 显示完全一样）。

### 3.3 代码逻辑根因（导致该表现的机制）

**（a）判定只到"星期"这一层** —— `web/static/app.js:967-988`（`macro.js:136-154` / `macro_cn.js:122-140` 为逐字副本）：

```js
parts = Intl.DateTimeFormat('en-US', {timeZone:'Asia/Shanghai', weekday, hour, minute}).formatToParts(now)
open = wdIdx >= 1 && wdIdx <= 5      // ★ 只判工作日；hh/mm 取出来只用于显示时间，从不参与判定
st.textContent = open ? '市场已开盘' : '休市'
```

**（b）三份副本** —— 三页各有一份逐字重复的实现（项目既有决策：macro 页刻意复制 shell 行为约 35 行，见 `tasks/2026-09-14-macro-page/journal.md:120`）⇒ **改 DOM id 与逻辑必须三处同改**（R1）。

**（c）`.ms-row` 为 `white-space: nowrap`** —— 文案超宽不换行、不截断，而是溢出（详见 §3.5）。

### 3.4 关键测量点（实测）

**基线（1920×1080，`/`）**：

| 元素 / 量 | 实测值 |
|---|---|
| `#sidebar` | `232 × 1024`，`padding 12px/12px`，`border-box` |
| `.sidebar-footer` | `x=12, w=207, h=45`（`clientH=44`），`display:flex`，`gap:10px`，`align-items:center`，`padding-top:12px`，`border-top:1px`，`border-box` |
| `#sidebar-theme` | `28 × 28`，`flex-shrink:0` |
| `.market-status` | `73 × 32`，`flex: 0 1 auto`，`min-width: 0`，`gap: 2px`，`overflow: visible`，`border-box` |
| `.ms-row`（单行） | `73 × 16`，`white-space: nowrap`，`font-size: 11px`，`line-height: 15.95px` |
| `#market-status` 文本 | 55px（"市场已开盘" 5 字 ⇒ **11px/字**） |
| `#market-time` | `73 × 15`，`font-size: 10px` |
| `#market-dot` | `ms-dot open`，`background: rgb(22,160,133)` |
| **可用宽度** | **169px** = `207 − 28 − 10`；单行文本预算 **156px ≈ 14 汉字** |

**方案 C 注入式 A/B（把候选 DOM 注入真实页面后重测，三档视口）**：

| 量 | 基线 | 方案 C | 判定 |
|---|---|---|---|
| `.sidebar-footer` 高 | 45 | **63** | +18px（两行 16×2 + gap 2×2 − 原单行 16） |
| `.market-status` 高 | 32 | **50** | 三行（16 + 16 + 15）+ gap 2×2 |
| `.nav` 高 | 444 | **444（不变）** | 侧栏 `flex-col` + `footer{margin-top:auto}` ⇒ 只向上挤压空白 |
| `#sidebar` 是否出纵向滚动条 | False | **False** | 1080 / 720 两档皆然 |
| `body.scrollHeight` @1920 | 1216 | **1216（不变）** | `≤1240` 护栏不受影响 |
| `body.scrollWidth` vs 视口 | 相等 | **相等** | 1920 / 1280 / 769 三档零横向溢出 |
| 侧栏贴底 `bottom − innerHeight` | 0 | **0** | 贴底断言不受影响 |
| 新行 1 `A股 已收盘` | — | `73px`，`scrollW == clientW` | 无溢出（预算 169） |
| 新行 2 `美股 未开盘` | — | `73px`，`scrollW == clientW` | 无溢出 |
| 灰点实测色 | `rgb(22,160,133)`（绿） | `rgb(156,163,175)`（=`--text-muted`） | 复用现有 `.ms-dot` 规则 |
| 主题按钮垂直居中 | — | footer 中心 = 按钮中心 = **1039** | 对齐正确 |

> **结论：方案 C 的 `style.css` 可零改动**（`.market-status` / `.ms-row` / `.ms-dot` / `.ms-dot.open` 全部复用），改动收敛到 **DOM（1 文件）+ 3 个 JS + 验收脚本**。

### 3.5 box-sizing 说明（为什么"加字"危险、"加行"安全）

- 链条上四个盒子（`#sidebar` / `.sidebar-footer` / `.market-status` / `.ms-row`）**实测全部 `border-box`**，且本处**均无 padding / border**（footer 的 `padding-top:12px` 与 `border-top:1px` 已含在 45px 内）⇒ `clientWidth == offsetWidth`，尺寸**不是**被内边距吃掉的。
- 真正的宽度约束来自**父级 flex 行剩余空间**：`207 − 28（主题按钮，flex-shrink:0） − 10（gap） = 169px`。
- **关键差异**：`.ms-row` 是 `white-space: nowrap` ⇒ 文本**永不换行** ⇒ 超宽时既不换行也不截断，而是**溢出到 `.market-status` 之外**（其 `overflow: visible`）；又因 `#sidebar{overflow-y:auto}` 使 `overflow-x` 计算值变 `auto` ⇒ 长文案可能让侧栏**冒出横向滚动条**。
- 而**加行是安全的**：`.market-status` 是 `flex-direction: column`，新增 `.ms-row` 只增高（实测 32→50，父级 footer 随之 45→63），**不触碰宽度链**。这正是"两行两市场"比"单行堆文案"更稳的机制性原因：**每行只需 ~73px，对 169px 预算有 2 倍余量**。

---

## 4. 会话状态机定义（核心口径）

### 4.1 判定规则（按**各市场本地时钟**，周一~周五）

| 市场 | 时区 | 未开盘 | 交易中 | 其他 |
|---|---|---|---|---|
| A 股 | `Asia/Shanghai` | `t < 09:30` | `09:30 ≤ t < 11:30` 或 `13:00 ≤ t < 15:00` | `11:30 ≤ t < 13:00` → **午间休市**；`t ≥ 15:00` → 已收盘 |
| 美股 | `America/New_York` | `t < 09:30` | `09:30 ≤ t < 16:00` | `t ≥ 16:00` → 已收盘 |

- **边界含左不含右**（`09:30:00` 算开盘，`11:30:00` 算午休）。
- 周末：按**各自时区的 local weekday** 判 → 该市场「休市」。
  **不做特例是正确的**：北京周六 03:00 = 美东**周五** 15:00 ⇒ A 股"休市" + 美股"交易中"，符合事实。
- ⇒ 夏令时由 **IANA tz 数据自动处理**，代码里**不出现 21:30 / 22:30 魔数**（本方案最重要的实现约束）。
- **「未开盘」的语义**（用户已裁定）：按该市场**自身的本地时钟**，`t < 09:30` 即「未开盘」—— 北京凌晨 3:00 的 A 股写「未开盘」（当日尚未开），与 A 股时钟自洽。

### 4.2 覆盖表（供实现与断言共用）

| 北京时刻（夏/冬令时） | A 股行 | 美股行 | 点色 |
|---|---|---|---|
| 03:00 | `A股 未开盘` | `美股 交易中` | 灰 / **绿** |
| **20:44（用户截图）** | **`A股 已收盘`** | **`美股 未开盘`** | **灰 / 灰** ← 本期要修的那一格 |
| 21:30 / 22:30 | `A股 已收盘` | `美股 交易中` | 灰 / **绿** |
| 04:30 / 05:30 | `A股 未开盘` | `美股 已收盘` | 灰 / 灰 |
| 10:00 | `A股 交易中` | `美股 已收盘` | **绿** / 灰 |
| 12:00 | `A股 午间休市` | `美股 未开盘` | 灰 / 灰 |
| 周六 12:00 | `A股 休市` | `美股 休市` | 灰 / 灰 |

> ⚠️ **勘误（2026-09-16 21:2x，执行者红跑时发现，架构师已确认并修正）**：本表初版有两格是**手写直觉**而非由 §4.1 规则推导，与规则冲突：
> ① 初版「北京 12:00」把美股写成 `已收盘` —— 但北京 12:00 = 美东 **00:00**（同一 local weekday），按 §4.1 的 `t < 09:30 → pre` 应为 **`未开盘`**（美股"当日尚未开盘"）；
> ② 初版 Step 6 表把 `2026-09-19T04:00:00Z` 的美股写成 `已收盘` —— 该时刻美东本地是 **周六 00:00** ⇒ 应为 **`休市`**（与本节"周六"行自相矛盾）。
> **教训（已记入 pitfalls）**：覆盖表**必须由判定规则机械推导生成**（用 `zoneinfo` 算，不手算、不凭直觉），否则表与规则漂移且**两处都在同一张纸上时很难被发现**。执行者按 §4.1 落地是正确的，本表现已与规则一致。

### 4.3 文案宽度核算（每行独立，远低于 169px 预算）

| 行文案 | 实测/折算宽（含点 7 + gap 6） | 判定 |
|---|---|---|
| `A股 已收盘` / `美股 未开盘` | **73px（实测）** | ✓ 余 96px |
| `A股 午间休市`（4 字） | ≈ 73 + 11 = 84px | ✓ |
| `A股 交易中` / `美股 交易中` | ≈ 73px | ✓ |
| 现有 `北京时间 20:44`（第三行） | **73px（实测）** | ✓ 不变 |

⇒ 全表**最长约 95px**，对 169px 预算有 ≥1.7 倍余量。**方案 C 基本消除了长度风险**（对比方案 A 单行 137px 紧贴上限）。

---

## 5. 要改的文件列表

| 文件 | 改动性质 | 内容 |
|---|---|---|
| `web/templates/_sidebar.html` | **改（:25-28）** | `.market-status` 内 1 行 → 2 行：`#market-dot-cn`+`#market-status-cn` / `#market-dot-us`+`#market-status-us`，第三行 `#market-time` **原样保留**；每行加 `data-market="cn\|us"`（给验收脚本稳定选择器） |
| `web/static/app.js` | 改（`updateMarketStatus`，:966-988） | 时段判定 + 两行文案 + 逐点着色 |
| `web/static/macro.js` | 改（:136-154） | 同上（**逐字同口径**） |
| `web/static/macro_cn.js` | 改（:122-140） | 同上（**逐字同口径**） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 改（`:159-160` 取值 + `:2748-2749` 断言 + 新增断言组） | 见 §7 |
| `web/static/style.css` | **不改（已实测确认零改动）** | 复用 `.market-status` / `.ms-row` / `.ms-dot` / `.ms-dot.open` |
| `web/app.py` | **不改**（不新增静态文件 ⇒ `_ASSET_FILES` 无需登记） | — |
| `docs/pitfalls.md` / `docs/architecture.md` | 收尾追加（按 AGENTS.md） | 1 段踩坑 + 决策表 1 行 |

**不变**：`src/**`、`tests/**`（本次零 Python 改动 ⇒ `pytest` 基线 663 passed 应保持）、`data/**`。

### 5.1 id 变更的引用清单（**必须逐条核对，防"假绿"**）

> 本项目已有教训：改结构后旧选择器**静默变 0**，其中"应为 0"类断言会**直接变假绿**（`docs/pitfalls.md:388`）。故先把引用点穷举（已 `grep` 全仓）：

| 文件:行 | 现引用 | 处置 |
|---|---|---|
| `web/templates/_sidebar.html:26` | `#market-dot`、`#market-status` | **改**为 `-cn` / `-us` 两个 id |
| `web/templates/_sidebar.html:27` | `#market-time` | 不变 |
| `web/static/app.js:968,970,985-987` | `getElementById('market-status' / 'market-dot')` | **改**为双 id |
| `web/static/macro.js:137,151-153` | 同上 | **改** |
| `web/static/macro_cn.js:123,137-138` | 同上 | **改** |
| `verify_ui.py:159-160` | 取 `#market-status` / `#market-time` | **改**：`marketStatus` → `{cn, us}`；`marketTime` 不变 |
| `verify_ui.py:2748-2749` | `marketStatus in ("市场已开盘","休市")` | **改**为同源断言（§7 V4） |
| `web/static/style.css:202-206` | 类选择器 `.market-status/.ms-row/.ms-dot/.ms-dot.open` | **类名不变 ⇒ 零改动** |

⚠️ 交付时**必须**再 `grep -n "market-status\|market-dot" web tasks` 复核一次，确认没有残留的 `#market-status` 单数引用（残留会让断言恒 0 = 假绿）。

---

## 6. 实现步骤（每步可独立验证）

> 只给要点与伪代码，**不写完整实现**。

### Step 1 — DOM 先行（`_sidebar.html`）

```html
<div class="market-status">
  <span class="ms-row" data-market="cn"><i class="ms-dot" id="market-dot-cn" aria-hidden="true"></i><span id="market-status-cn">A股 —</span></span>
  <span class="ms-row" data-market="us"><i class="ms-dot" id="market-dot-us" aria-hidden="true"></i><span id="market-status-us">美股 —</span></span>
  <span class="ms-time" id="market-time">北京时间 —</span>
</div>
```
（`aria-hidden="true"`：点的信息已由文本承载，避免屏幕阅读器重复朗读；零视觉影响。）

**验证（本步）**：三页打开，两行各显示占位 `A股 —` / `美股 —`；量 `footer.h == 63`、`#sidebar` 无纵向滚动条、`body.scrollWidth == 视口宽`（与 §3.4 实测一致）。

### Step 2 — 纯函数：单市场会话态

```js
// 伪代码：now 必须可注入（★ DST / 边界断言依赖这一点）
function sessionOf(tz, openHM, closeHM, midday, now) {
  p = partsOf(tz, now)                       // {weekday:'Mon'.., hh, mm}，口径同现有 Intl.DateTimeFormat
  if (p.weekday === 'Sat' || p.weekday === 'Sun') return 'weekend'
  t = hh * 60 + mm
  if (midday && t >= hm(midday[0]) && t < hm(midday[1])) return 'midday'
  if (t >= hm(openHM) && t < hm(closeHM)) return 'open'
  return t < hm(openHM) ? 'pre' : 'post'
}
```
- 口径：`Intl.DateTimeFormat('en-US', {timeZone: tz, weekday:'short', hour:'2-digit', minute:'2-digit', hourCycle:'h23'})` + `formatToParts`（**与现有代码同口径**，零新依赖）。

**验证（本步）**：`node --check web/static/app.js`；console 调
`sessionOf('America/New_York','09:30','16:00',null,new Date('2026-09-16T12:44:00Z'))` → `'pre'`（北京 20:44）。

### Step 3 — 文案与着色

```js
// 伪代码
CN = {open:'交易中', pre:'未开盘', post:'已收盘', midday:'午间休市', weekend:'休市'}
a = sessionOf('Asia/Shanghai',    '09:30','15:00',['11:30','13:00'], now)
u = sessionOf('America/New_York', '09:30','16:00', null,               now)
stCn.textContent = 'A股 ' + CN[a]
stUs.textContent = '美股 ' + CN[u]
dotCn.classList.toggle('open', a === 'open')   // ★ 逐市场着色：交易中=绿，否则灰
dotUs.classList.toggle('open', u === 'open')
tm.textContent   = '北京时间 ' + beijingHM(now)  // 保持不变
```
- **点色语义变更需明示**：原 `open` = "今天是工作日"（全局单点）→ 新 `open` = "**该市场此刻在交易**"（逐市场）。"任一市场在交易" ⇔ "至少一绿"。
- `setInterval(updateMarketStatus, 60000)` **保留**（边界最多延迟 60s，**有意接受**；不因视觉洁癖降到 10s）。

**验证（本步）**：20:4x 起服务 → `A股 已收盘`（灰）/ `美股 未开盘`（灰）；注入 21:30 的 `now` → `美股 交易中`（绿）。

### Step 4 — 复制到另两页（`macro.js` / `macro_cn.js`）

同口径替换，保留各自 `el(...)` 取值风格；**必须加注释互指**："本函数在 `app.js` / `macro.js` / `macro_cn.js` 各有一份，改一处必须三处同改"。

**验证（本步）**：§7 V5（三页逐字一致）。

### Step 5 — 改造验收断言（先红后绿）

- **删** `verify_ui.py:2748` 的 `marketStatus in ("市场已开盘","休市")`（写死文案 ⇒ 下次改文案必假红；且工作日**恒真 ⇒ 假绿**）。
- **换**为同源断言：期望值由页面内同一函数产生（例：`page.evaluate(() => window.__marketSessionLabel())`），再与 DOM 文本比对，**不写死任何具体词**。
- **新增**：两行结构断言（`data-market="cn"/"us"` 各存在且非空）、逐点色断言、§7 V6 几何断言、V5 三页一致性。

**验证（本步）**：先在旧实现下**跑红**（记下红值入 journal），实现后转绿。

### Step 6 — DST / 边界回归护栏（**最不能省的一步**）

用 `page.add_init_script` 或 `page.evaluate` 注入假 `now`，断言：

| 注入 UTC | 北京 | 美东 | 期望（cn / us） |
|---|---|---|---|
| `2026-09-16T12:44:00Z` | 20:44（EDT） | 08:44 | 已收盘 / 未开盘 ← **用户截图场景** |
| `2026-09-16T13:30:00Z` | 21:30（EDT） | 09:30 | 已收盘 / **交易中** |
| `2026-12-01T13:30:00Z` | 21:30（**EST**） | 08:30 | 已收盘 / 未开盘 ← **冬令时护栏** |
| `2026-12-01T14:30:00Z` | 22:30（EST） | 09:30 | 已收盘 / **交易中** |
| `2026-09-16T04:00:00Z` | 12:00 | 00:00 | **午间休市** / **未开盘** |
| `2026-09-19T04:00:00Z`（周六） | 12:00 | 00:00 | **休市** / **休市** |

> ⚠️ 两个 12 月用例即 R2 护栏：**任何写死"北京 21:30"的实现都会在此变红**。并做一次**反向验证**（故意改成硬编码，确认这 2 条变红），证明断言有效。

---

## 7. 验证命令（引自 `docs/commands.md`）

| # | 命令 | 期望 |
|---|---|---|
| V0 | `node --check web/static/app.js`（及 `macro.js` / `macro_cn.js`） | 退出码 0 |
| V1 | `venv/Scripts/python -m pytest tests/ -v` | **663 passed**，零回归（本次不动 Python；数字变化须先解释） |
| V2 | `venv/Scripts/python -m uvicorn web.app:app --port 8000` | 三页可开 |
| V3 | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **EXIT=0 / ALL PASSED**（前端改动**必跑**；禁止用 `curl 200` 或肉眼看代替） |
| V4 | 同 V3，**改实现前先跑一次** | **应当变红**（新断言），红跑清单入 journal |
| V5 | 三页一致性：三页各取 `#market-status-cn` / `#market-status-us` | 同刻**逐字相同** |
| V6 | 几何护栏（1920×1080 / 1280×720 / 769×720 三档） | ① footer.h == **63**；② `.market-status` h == **50**；③ `#sidebar` **无**纵向滚动条（`scrollH ≤ clientH`）；④ 每行 `scrollWidth ≤ clientWidth + 0.5`；⑤ `body.scrollWidth == documentElement.clientWidth`；⑥ 侧栏贴底 `bottom − innerHeight == 0` |
| V7 | 页面总高护栏（既有断言） | `scrollHeight@1920 == 1216 ≤ 1240`（实测方案 C 不变） |
| V8 | 边界/覆盖表断言（§4.2 + Step 6 注入表） | 全部吻合 |

---

## 8. 多尺寸验收（预期效果）

| 视口 | 侧栏 | `.market-status` 可用宽 | 预期（实测值） |
|---|---|---|---|
| 1920×1080 | 内联 232px | 169px | footer **63px**；两行各 73px 完整；`#sidebar` 无纵向滚动条；页面总高 **1216（不变）** |
| 1280×720 | 内联 232px | 169px | 同上（实测 footer 63、`.nav` 444 不变、无滚动条） |
| 1024×768 | 内联 232px | 169px | 同上（`@media(max-width:1024px)` 只改 `.row-kpi`） |
| **769×720（断点下沿）** | 内联 232px | 169px | 同上（实测 footer 63、零横向溢出）。**必须采样这一档**（本项目踩过"断点空档盲区"） |
| 375×812 | **抽屉（关闭态）** | — | chip 在画布外（实测 `x=-190`）⇒ 不可见，不进验收集；打开抽屉后侧栏 240px ⇒ 可用 177px，**更宽，不构成风险** |

> 宽度预算在 **≥769px 全档恒定 169px**，故 V6 扫 3~4 档即可覆盖全部风险面。
> **垂直方向的风险档是 720p**（`#sidebar` 高仅 664px；`.nav` 444 + footer 63 = 507 < 664）⇒ 实测无滚动条；若视口高再降到 **约 560px 以下**，侧栏才会出现纵向滚动条（记入 R5）。

---

## 9. 风险评估与注意事项

| # | 风险 | 影响 | 处置 |
|---|---|---|---|
| **R1** | **三份副本漏改** + **DOM id 变更漏改引用** | 三页文案不一致；或残留 `#market-status` 单数选择器 ⇒ 断言恒 0 变**假绿** | §5.1 引用清单（已穷举）+ 三处同改 + 互指注释 + V5；交付前再 `grep` 复核 |
| **R2** | **夏令时**：硬编码"北京 21:30" | 2026-11-01 后静默错 1 小时（美东 09:30 = 北京 22:30），**不报错、console 干净** | 按**各市场本地时钟**判定（IANA 处理 DST）；Step 6 的 12 月用例 + 反向验证 |
| **R3** | **节假日不判**（无日历依赖） | 国庆/春节/感恩节当天显示"交易中/未开盘" | **已确认取舍**（§2.3）；"休市"只用于周末，避免绝对断言 |
| **R4** | 文案溢出 | 每行仅 73px（预算 169px，余 96px），**基本消除** | V6 ④ 仍保留溢出断言作长期护栏 |
| **R5** | **侧栏高度 +18px** | 极矮视口（高 < ~560px）会让侧栏出现纵向滚动条 | V6 ③；720p 实测无滚动条 |
| **R6** | **验收断言写死文案** | 下次改文案假红；当前那条在工作日**恒真（假绿）** | 改**同源断言**（期望值由同一函数产生），不写死词 |
| **R7** | **并行会话占用 `verify_ui.py`** | 提交时扫走别人的在途改动（已实测踩过：315 行 / 91 行先例） | 提交前 `git status --short` + `git diff -U0 -- <file>` **逐 hunk 认领** |
| **R8** | 浏览器 ICU 缺 tz 数据 | `Intl` 抛异常 | 保留 `try/catch`，回退占位文案（不崩） |
| **R9** | 点色语义变更（"工作日" → "该市场在交易"） | 后人按旧语义理解 | **裁定（2026-09-16 21:2x）：不为注释去动 `style.css`**（§5/§10 的零改动承诺优先）。语义注释写在 3 个 JS 的 `classList.toggle('open', …)` 调用点，并**指名其驱动的 CSS 规则 `.ms-dot.open`**；`docs/architecture.md` 追加决策行。※ 原 R9 与 §5/§10 冲突是**架构师自相矛盾**，已按此裁定消除 |
| **R10** | 分钟级刷新边界延迟 60s | 21:29:30 打开显示"未开盘"，21:30:20 才变 | **有意接受**（不降 interval，避免无意义重绘） |

---

## 10. 预计影响的文件范围

**直接改动（5 个）**：

```
web/templates/_sidebar.html     ~4 行（.market-status 内 1 行 → 2 行）
web/static/app.js               ~30 行（updateMarketStatus 重写 + 2 个纯函数）
web/static/macro.js             ~30 行（同口径）
web/static/macro_cn.js          ~30 行（同口径）
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   ~+90 行（1 条改写 + 3 组新增）
```

**收尾追加（2 个，按 AGENTS.md）**：`docs/pitfalls.md`（1 段：时区判定 / nowrap 溢出 / 计划-实现漂移）、`docs/architecture.md`（决策表 1 行）。

**零改动（已核对 / 已实测）**：`web/static/style.css`（类名复用 ⇒ 零改动，**由注入式 A/B 实测确认**）、`web/app.py`（不新增静态文件）、`src/**`、`tests/**`、`data/**`。

**替代方案 A1（不采用，备查）**：新建 `web/static/market-session.js` 三页共享以消除三份副本。需额外改 3 个模板的 `<script>`（**且必须在业务脚本之前**，本项目踩过"顺序错 → `plugins:[undefined]` 静默忽略"）+ 在 `web/app.py:_ASSET_FILES` 登记新文件（否则改它不换 URL、验证吃旧副本）。在既有"macro 页刻意复制 shell 行为"的决策下 diff 更大；若将来出现第 4 个页面，再按 A1 抽取。

---

## 11. 已确认 / 剩余待确认

**已由需求方裁定（2026-09-16 20:48）**：
1. ✅ 点色 = **此刻有任一市场在交易**才亮（落到双点结构 = **逐市场着色，至少一绿**）
2. ✅ 凌晨场景 A 股写 **「未开盘」**
3. ✅ 采用 **两行两市场**（方案 C）

**执行后裁定（2026-09-16 21:2x，架构师）**：
4. ✅ **市场名格式 = 带空格**（`A股 已收盘`，实测行宽 73px / 预算 169px）—— 与 §11 默认一致
5. ✅ **勘误两格**：§4.2「北京 12:00」的美股 → `未开盘`；Step 6「`2026-09-19T04:00:00Z`」的美股 → `休市`（详见 §4.2 勘误块）
6. ✅ **R9 裁定**：保持 `style.css` 零改动，语义注释落在 JS 调用点

**已无剩余待确认项。**

---

## 12. 架构师独立复核记录（2026-09-16 21:2x）

> 本节为**交付前复核**，不属实现步骤；用于记录"我验证了什么、用什么口径验证的"。

### 12.1 复核方法与结果

| # | 复核项 | 方法（**不复用执行者断言**） | 结果 |
|---|---|---|---|
| A | 交付范围 | `git status --short` + `git diff --stat` | 恰 7 个文件 / +507 −54，与执行者报告逐项一致 |
| B | 零改动承诺 | `git diff --quiet -- web/static/style.css web/app.py src/` | 退出码 **0** ⇒ 三处确实零改动 |
| C | id 残留（防假绿） | 全仓 `grep "market-status\|market-dot"` | **零残留单数 id**；仅两处**注释**提及已删 id（属有意文档化） |
| D | 实现与口径一致性 | 读 `app.js:966-1055` 核心段 | `MARKET_SESSIONS` 逐市场时区、`marketSessionOf` 含左不含右、周末按 local weekday、`now` 可注入；**全段无 `21:30` 魔数** |
| E | **DST / 边界 / 周末 / 跨日** | **独立探针**：Python 侧用**显式 UTC 偏移**（EDT −4 / EST −5 / 北京 +8）独立算期望值，再对打 `window.__marketSession(iso)`；**3 页 × 15 个注入时刻** | **0 FAIL / 45**（含两个冬令时护栏、`09:30/11:30/13:00/15:00/16:00` 全部边界、两个争议格） |
| F | DOM 与函数同源 | 真实时刻对比 `#market-status-cn/-us` 文本、两点 class 与函数输出 | 一致（21:25 → `A股 已收盘` / `美股 未开盘`，双灰点，与 §4.2 覆盖表吻合） |

探针：`%TEMP%\mp_review_session.py` → `%TEMP%\mp-review-session\review.json`（**未落仓库**）。
※ 探针第一版把美东偏移误用于 A 股，得 39 FAIL；**修正探针自身**后 0 FAIL —— 记此一笔以证明"红"可能来自探针而非被测实现（与 `docs/pitfalls.md` 的"探针须与被测实现同口径"同源）。

### 12.2 未复核 / 明确接受的部分

- **V3 的 12 条 `/macro` 组失败**：接受执行者的**基线 A/B 严格超集**论证（`git archive HEAD` 隔离副本：HEAD 基线 15 条 ⊇ 本轮 12 条 ⇒ 新增 0），并以本轮"零改动清单"（`src/` / `web/app.py` / `style.css` 逐字节一致）作为独立旁证 —— 改动面确实不覆盖 `/macro` 数据链。
- **建议的后续（不在本任务范围）**：把这 12 条（Yahoo `http=429` 限流 ⇒ `/api/macro` 全 null、`/api/econ` 的 `as_of=null`）登记到 `docs/system-overview.md` §9 已知缺口表，避免"验收红且长期无人处理"变成新常态（本项目已有"红色被当噪声"的先例）。
