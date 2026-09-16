# 实施计划：悬停横线吸附到数据线（crosshair snap）

> **需求来源**：2026-09-15 用户口述 ——「图表上的横线要吸附在线上，鼠标移过去，那个横线是随着鼠标在线上移动」
> **产出**：架构师**实测后**出具（起 uvicorn + Playwright 量化，非代码推演）；**未改动任何项目文件**
> **基线**：2026-09-15 19:25，工作区**含未提交的中国宏观页改动**（`src/cn_econ_fetcher.py` / `web/static/macro_cn.js` / `web/templates/macro_cn.html` 等尚未入库）
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 任务目标

**Goal**：图表的悬停水平参考线**不再是自由浮动的鼠标线**，而是**吸附到当前 x 位置最近的数据线上**，随鼠标沿 x 移动而在线上滑行。

**改动位置**：`web/static/chart-crosshair.js`（**三图共享**的内联插件）→ 一次改动同时覆盖
`#chart-main`（首页趋势四图合一）/ `#macro-chart`（宏观页）/ `#cn-chart`（中国宏观页）。

**附带收益（实测发现的第二个缺陷，本方案一并修掉）**：现在轴端气泡读的是「鼠标高度处的轴值」，
在单数据集图上**与鼠标 x 完全无关** —— 实测在 `/macro/cn` 上把鼠标横向移动 3 个位置，
`$crosshairLabel` **恒为 `3950.22`**。吸附后气泡将显示**该日期该序列的真实值**。

---

## 2. 结论先行与方案选型

### 2.1 吸附目标的选择规则

| 规则 | 决策 | 理由 |
|---|---|---|
| **先定 x，再定线** | 取 x 最近的数据点索引 `idx0`（**单一、确定性**），再在该列里选 y 最近的数据集 | "吸附在线上"必须是「当前日期的某条线」，先定 x 才不会跨日期 |
| **同 x 多线取最近 y** | 在所有**可见**数据集中取 `|p.y − mouseY|` 最小者 | 与直觉一致；鼠标靠近哪条线就吸哪条 |
| 多线时是否换线 | **允许切换**（鼠标纵移跨过两线之间的中线时换目标线） | 这是"随鼠标在线上移动"的自然含义 |

### 2.2 三个方案

| 方案 | 内容 | 决策 |
|---|---|---|
| **A（最小）** | 只把 `$crossY` 改为吸附点 y；线色仍中性；气泡仍纯数值 | **必做**（已解决用户诉求） |
| **B（含归因）** | A + **线色改为吸附数据集的 `borderColor`**（alpha 0.65）+ 在吸附点画 3px 圆点 | **已确认采用**（2026-09-15）：2–3 条线时，一条中性线在系列间跳动而气泡只给一个数字，用户无法判断吸的是哪条。颜色是零文本成本的归因 |
| C | 把序列名拼进气泡文本（`"纳斯达克 -1.4%"`） | **否决**：会改 `chart.$crosshairLabel` 的语义，直接打破 CS-4（`label == fmtAxisPct(getValueForPixel($crossY))` + 格式正则）与 XC-2/3/4 —— 为了文案去动可测性挂钩不划算 |

⚠️ **方案 B 推翻了插件头注释里的既有设计决策**（`chart-crosshair.js:97-98`：「一条**中性色**线 + 一个轴读数，**与系列无关**」）。原决策在"线不属于任何系列"时是自洽的；吸附之后线**必然属于某个系列**，中性色不再成立。
→ **必须同步更新插件头注释与 `docs/architecture.md` 决策行**，否则后人会以"违反既定设计"为由回退它。

### 2.3 退化策略（每一处都必须显式定义，不能靠默认行为）

| 场景 | 策略 |
|---|---|
| 该 x 列**所有数据集都为 null**（缺口；`/macro/cn` 多品种模式的日期轴是并集，缺口常见） | 依次尝试 `idx0±1, ±2, ±3`；仍无 → **回退到鼠标 y**（保持旧行为，线不闪断） |
| 鼠标在绘图区**外的 x**（但 y 在区内） | **钳制 x 到 `[area.left, area.right]` 后吸附**。可见性规则**不变**（仍只由 y 判定）→ CS-3 语义逐字不变 |
| 鼠标 y 在绘图区外 / `mouseout` / `touchend` | 与现状**完全相同**（清 `$crossY` + 重绘） |
| 数据集 `hidden` | 跳过（不参与吸附） |

---

## 3. 实测基线（本方案的事实依据）

方法：脚本自起 uvicorn（自动挑空闲端口 13060）+ Playwright（1920×1080，`device_scale_factor=1`），
在固定 x 上取 3 个 y、在固定 y 上取 3 个 x，逐点读回 `chart.$crossY` 并**离线计算**最近数据点位置。
截图证据：`%TEMP%\mp_snap_home.png` / `mp_snap_macro_cn.png`；原始数据：`%TEMP%\mp_snap_probe.json`。
`pageerrors = []`（探针本身不干扰页面）。

### 3.1 现状：横线 = 鼠标 y（自由浮动），实测确证

`deltaMouseCross = mouseY − $crossY`，**全部 18 个采样点为 `−0.48 ~ +0.48`** → 横线精确跟随鼠标，与数据无关。

### 3.2 横线离最近数据线有多远（`deltaMouseLine = mouseY − lineY`）

| 页面 / 图 | 数据集数 | 采样点 `deltaMouseLine` |
|---|---|---|
| `/` `#chart-main`（美股大盘 tab） | 2 | −197.5 / −59.2 / −5.3 / **+27.5** / −59.2 / −54.6 |
| `/` `#chart-main`（波动率 tab） | 3 | −133.0 / **+2.5** / **+78.6** / +27.5 / +2.5 / +23.4 |
| `/macro/cn` `#cn-chart`（默认单变量） | **1** | **−268.9** / −108.1 / +27.3 / +15.7 / −108.1 / +37.0 |

**最大偏离 −268.9px** —— 横线可以在离任何数据线 269px 的地方飘着。这是用户诉求的量化表达。

### 3.3 关键几何基线（`box-sizing` 一节会用到的坐标口径）

| 图 | canvas id | canvas 尺寸 | `chartArea` (CSS px) | 绘图区尺寸 |
|---|---|---|---|---|
| 首页趋势主图 | `chart-main` | 1024 × 432 @ viewport(277,268) | (11,10) → (979,405) | 968 × 395 |
| 中国宏观主图 | `cn-chart` | **1346 × 496** @ viewport(403,359) | (31,10) → (1304,469) | 1273 × 459 |

三图共同点（实测）：`scales = ['x','y']`（**单 y 轴**）、`interaction.mode = 'index'`、`crosshair = True`、
数据集 `pointRadius: 0`（首页为函数，仅末点 2.5）、`spanGaps: true`、`tension` 0.15~0.25。

### 3.4 ★ 两个会打破既有断言的实测事实

**(1) 同 x 纵移，「最近数据集」可能不变 → 吸附后 y 相同**

首页美股大盘 tab（x=0.5）实测：

| 鼠标 y 位置 | 最近数据集 | 数据索引 | 该点 y |
|---|---|---|---|
| y=0.15 | ds#0 | idx=14 | **266.3888** |
| y=0.5 | ds#0 | idx=14 | **266.3888** ← 与上完全相同 |
| y=0.85 | ds#1 | idx=13 | 350.8273 |

→ `CS-2` 用 y=0.3 与 y=0.7 两点（`verify_ui.py:461-462`）。**该两点已由 §3.6 实测**（把本方案的 `snapToNearest` 原样注入浏览器实跑）：两点都吸附到 **297.63**（同一 ds#0、同一 idx=13）→ 画布指纹相同 → **CS-2 必红**。

**(2) 并列（tie）在真实采样中会实际发生**

`colCount`（与鼠标 x 等距的数据点个数）实测出现过 **4**（x=0.5，2 数据集 × 2 个等距索引）
—— 采样点间距 ≈ 968÷250 ≈ 3.9px，鼠标落在两采样点正中即产生 tie。
→ 实现**不得**用"收集所有等距点"的写法，必须**确定性取单一索引**（并列时取较小索引）。

### 3.5 读数与 x 无关（第二个缺陷的实测证据）

`/macro/cn`（单数据集）在 x=0.30 / 0.50 / 0.70 三个位置、鼠标 y 固定 239：

| x | `$crossY` | `$crosshairLabel` | 该 x 处数据点 y（`lineY`） |
|---|---|---|---|
| 0.30 | 239 | **`3950.22`** | 223.47 |
| 0.50 | 239 | **`3950.22`** | 347.33 |
| 0.70 | 239 | **`3950.22`** | 202.18 |

→ 气泡读数**完全不随日期变化**。用户横向扫过整条曲线，读到的一直是同一个数。

### 3.6 吸附后各采样点预测（**实测**，非推算）

方法：把 §附 的 `snapToNearest` 伪代码**原样实现在浏览器里注入**（纯注入，不落盘、不改任何项目文件），
对 `verify_ui.py` 里 CS-2 / XC-5 / CNC 的**真实采样点**算出吸附目标。`pageerrors = []`。

| 页面 / 图 | 同 x 的两个 y | 吸附后 `snapY` | 判定 |
|---|---|---|---|
| `/` `#chart-main`（美股 tab，**2** 数据集） | y=0.3 → **297.63**（ds#0, idx=13）<br>y=0.7 → **297.63**（ds#0, idx=13） | **相同** | **CS-2 必红（实测确证）** |
| `/` `#chart-main`（波动率 tab，**3** 数据集） | y=0.3 → 201.83（ds#2）<br>y=0.7 → 266.93（ds#1） | 不同 | 旧判据**仍绿** —— 但理由已从"跟手"变成"**换了目标线**" |
| `/macro`（`__all__`，**4** 数据集） | y=0.50 → 243.15（ds#3）<br>y=0.72 → 366.97（ds#1） | 不同 | **XC-5 实测仍绿**（修正 §4/§9 原先的"脆弱"表述）—— 同样是**语义漂移** |
| `/macro/cn`（**单**数据集） | y=0.15 → **372.65**<br>y=0.50 → **372.65** | **相同** | 单数据集下同 x 必然吸同一 y（符合预期）→ 该页的"必红型"断言**当前不存在**（= §6 Step 4 的覆盖缺口） |

**我提的替换断言自身是否站得住（同样实测）**：

| 新断言 | 采样 | 吸附后 `snapY` | 判定 |
|---|---|---|---|
| **CS-2a**（不同 x → 指纹不同） | x=0.3 → 179.68 / x=0.7 → 261.77 | 不同 | **站得住** |
| 同上（波动率 tab） | x=0.3 → 179.67 / x=0.7 → 183.85 | 不同 | 站得住 |
| **XC-5a** | x=0.3 → 316.78 / x=0.7 → 299.16 | 不同 | 站得住 |
| **CNC-3a** | x=0.25 → 220.02 / x=0.75 → 301.64 | 不同 | 站得住 |
| **CS-8 的反向判据**（"不再跟手"） | 鼠标 y=128.16 → `snapY`=297.63 | `|snapY − mouseY| = **169.47px**` | 断言"`|$crossY − mouseY|` 允许远大于 1"有实测支撑 |

**两条必须带走的结论**：

1. **CS-2 必红**（实测）；**XC-5 实测仍绿但语义已漂移** → **二者都要补新断言，不得因 XC-5 绿着就不动它**。
   它绿的原因是"换了目标线"，不是"吸附正确" —— 这正是「断言变绿≠测的是同一件事」的实例。
2. 本批采样 `tie=0`、`nanAtCol=0`，但 §3.4(2) 已实测出现过 tie（`colCount=4`）
   → **确定性取索引与 NaN 守卫仍需实现**（"采样未覆盖"≠"不会发生"）。

---

## 4. 两层根因

### 4.1 渲染表现根因（用户实际看到什么）

1. 横线是一条**与数据无关的自由水平线**：鼠标纵向移动 N px，线就移动 N px；最近的数据线可能在 **269px 之外**（§3.2）。
2. 轴端气泡读数是**"鼠标高度处的轴值"**，不是"某个数据点的值" → 在单数据集图上**左右移动鼠标读数不变**（§3.5 实测恒为 `3950.22`）。
3. 因为数据集 `pointRadius: 0`（仅末点可见），线上**没有可见的点**作为锚 —— 用户无法把"这条横线 + 这个数字"对应到任何具体数据点。

### 4.2 代码逻辑根因（哪段机制导致）

| # | 位置 | 机制 |
|---|---|---|
| **L1** | `afterEvent`：`chart.$crossY = e.y` | 直接采用**事件坐标**。插件**从不查询任何 `dataset` 的 element 位置** → "这条线是什么"的定义就是"鼠标 y"。这是表现 1 的唯一原因 |
| **L2** | 插件头注释 `:97-98` | 原设计**刻意**如此：「横线 Y 取鼠标在绘图区内的纵向位置（**非数据点**）→ 一条中性色线 + 一个轴读数，**与系列无关**」。**这不是 bug，是当时的设计**；需求已变 |
| **L3** | `afterDatasetsDraw`：`formatter(scales.y.getValueForPixel($crossY))` | 读数**从 `$crossY` 派生** → 继承 L1，天然与 x 无关。表现 2 是 L1 的必然推论，不是独立缺陷 |
| **L4** | `afterEvent`：`Math.abs(e.y - chart.$crossY) < 1` 节流 | 节流绑在**鼠标 y** 上。吸附后若不改绑，`dsCount==1` 的图（`/macro/cn`）里鼠标纵移时"吸附 y 未变但鼠标 y 变了"→ 每帧都触发 `chart.draw()` 的无意义重绘。**这是本次改动最容易漏的一处** |
| **L5** | `afterEvent` 可见性只判 `e.y` | 现状不需 x；吸附后**需要 x** → 必须显式钳制 x，且**不得**顺手把可见性规则改成也判 x（会改掉 CS-3 语义） |

---

## 5. 要改的文件列表

| 类型 | 文件 | 说明 |
|---|---|---|
| **修改** | `web/static/chart-crosshair.js` | 唯一的实现文件：新增吸附纯函数 + 改 `afterEvent` + 改 `afterDatasetsDraw` 的线色/圆点 |
| **修改** | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **CS-2 改为 CS-2a/CS-2b**、**XC-5 同款改造**、新增 **CS-8** 吸附数值断言、新增 **CNC-1~5**（`#cn-chart` 覆盖缺口） |
| **修改** | `web/app.py` | **仅一处**：`_ASSET_FILES` 已含 `chart-crosshair.js`（实测确认，无需改）→ **本文件预计零改动**（保留此行以便复核） |
| **修改** | `docs/architecture.md` | 新增 1 决策行（append-only） |
| **修改** | `docs/pitfalls.md` | 追加：节流对象必须与被绘制的量一致（L4）；「同 x 纵移指纹变化」类断言在吸附后失效（CS-2/XC-5）；tie 必须确定性取索引 |
| **新增** | `tasks/2026-09-15-crosshair-snap/journal.md` | 执行者收尾填写 |

**零改动**：`src/**` 全部、`tests/**`（本改动不触 Python 逻辑，`pytest` 不受影响）、`web/templates/**`、`web/static/app.js`、`web/static/macro.js`、`web/static/macro_cn.js`、`web/static/style.css`。

> 三页的**调用点零改动**：插件本体共享，`window.hoverCrosshair`（首页）与 `window.makeHoverCrosshair({formatter})`（宏观两页）的**对外契约不变**。

---

## 6. 实现步骤

### Step 1 · 新增纯函数 `snapToNearest(chart, mx, my)`

```text
# 伪代码 —— 返回 {y, dsIndex, dataIdx} 或 null（无候选）
1. area = chart.chartArea；cx = clamp(mx, area.left, area.right)     # L5：x 钳制，可见性仍只判 y
2. 扫全部「可见数据集」的全部点，取 |p.x − cx| 最小者 → idx0
     并列（tie）时取**较小索引**（§3.4(2)：tie 实测会出现，必须确定性）
3. 候选 = datasets.filter(可见).map(i => meta.data[idx0]).filter(p => p && isFinite(p.y))
4. 若候选为空（缺口）→ 依次试 idx0±1、±2、±3，取第一个有候选的索引
5. 仍为空 → return null（调用方回退鼠标 y）
6. best = argmin |p.y − my|
7. return {y: best.y, dsIndex, dataIdx}
```

**为什么用「扫点取最近 x」而不是 `scales.x.getValueForPixel()`**：
后者对 `type:'category'` 返回的是「索引 + 0.5」一带的浮点（随 `offset` 配置变化），需要额外假设；
扫点用的是**真实 element 坐标**，与 scale 类型无关，且三图共用同一实现不会分叉。代价 O(n·d) ≈ 250×3，可忽略。

**验证**：`node --check` 校验语法（⚠️ 见 §7 陷阱：不可对内联 `<script>` 整体校验）；浏览器 `tab.evaluate` 直接调用该函数喂构造坐标，断言返回 `{y, dsIndex, dataIdx}` 与 §3.4 表一致。

### Step 2 · 改 `afterEvent`：吸附 + **节流改绑吸附 y**

```text
if (mouseout || touchend) → 清 $crossY + draw（不变）
if (非 mousemove/touchmove || !area) → return
if (e.y < area.top || e.y > area.bottom) → 清 $crossY + draw（可见性规则**逐字不变**）

snap = snapToNearest(chart, e.x, e.y)
targetY = snap ? snap.y : e.y            # 退化：无候选 → 回退鼠标 y（§2.3）

# ★ L4：节流对象改为 targetY（原为 e.y）
if (chart.$crossY != null && Math.abs(targetY - chart.$crossY) < 0.5) return;
chart.$crossY = targetY
chart.$crossSource = snap ? { dsIndex: snap.dsIndex, dataIdx: snap.dataIdx } : null   # 新增可测挂钩
chart.draw()
```

**两处必须注意**：
1. 节流阈值从 `< 1` 收到 `< 0.5`：吸附后 y 是**离散数据点的像素值**，相邻采样点间距可小至 1px 级；阈值太大（1px）会把真实的换点吞掉。
2. 早退时**不更新 `$crossSource`** 是**正确**的（y 未变 ⇒ 吸附目标未变）。若实现里先写 `$crossSource` 再判节流，会出现"source 与已绘制的线不一致"的隐蔽错位。

**验证**：Playwright 里 `chart.$crossY` 必须满足 `|$crossY − 最近数据点 y| < 0.5`（就是断言 CS-8）。

### Step 3 · 改 `afterDatasetsDraw`：线色归因（方案 B）+ 吸附点圆点

```text
text = formatter(scales.y.getValueForPixel(y), chart)     # ← 公式**逐字不变**（CS-4 靠它）
chart.$crosshairLabel = text                              # ← 挂钩语义不变

# 新增：线色取吸附数据集色（dsCount==1 或 $crossSource==null 时退回中性色，保证单线图观感不变）
stroke = (方案B && $crossSource) ? withAlpha(ds.borderColor, 0.65) : withAlpha(tc.axisTick, 0.65)
画虚线（其余不变：4/4 dash、lineWidth 1、area.left→area.right）
# 新增：吸附点圆点（半径 3，填充 dataset.borderColor，描边 tooltipBg）
```

**验证**：`chart.$crosshairLabel` 与 `fmtAxisPct(scales.y.getValueForPixel($crossY))` **仍相等**（CS-4 不变）；
新增断言：`chart.$crosshairLabel` == 吸附点的**真实数据值**经 formatter 的输出。

### Step 4 · 改造 `verify_ui.py` 的两条"跟手"断言（**先红后绿**）

**必红的断言**（§3.4 已推算出原因，执行者须实测确认再改）：

| 断言 | 位置 | 现状判据 | 吸附后 | 处置 |
|---|---|---|---|---|
| **CS-2** | `verify_ui.py:477-478` | 同 x（0.3 / 0.7）两点指纹**不同** | **实测**：两点吸到同一像素 y（`297.63` / `297.63`，同 ds#0 idx=13）→ 指纹**相同** → **必红** | 拆为 CS-2a + CS-2b（下表） |
| **XC-5** | `verify_ui.py:1726-1729` | 同 x（y=0.5 / 0.72，`__all__` 模式）指纹**不同** | **实测仍绿**（`243.15` vs `366.97`，最近线恰好切换）—— 但**判据理由已从"跟手"变成"换了目标线"，属语义漂移** | 仍须同款拆为 XC-5a + XC-5b（**不得因它绿着就不动**：绿 ≠ 测的是吸附） |

**改造方案（补强，不删除 —— `pitfalls.md` 明令「删掉断言让它变绿 = 把真红改成假绿」）**：

| 新断言 | 判据 | 测的是什么 |
|---|---|---|
| **CS-2a** | **不同 x**（如 0.3 / 0.7、同 y）→ 指纹**不同** | `$crossY` **随数据线走**（吸附的第一语义） |
| **CS-2b** | **同 x + 同最近数据集**（两个远离线的 y）→ 指纹**相同** | **真的吸住了**（不再跟手）。⚠️ 改动前此断言**必红**（现状跟手）→ 天然的"先红后绿"证明 |
| **CS-8** | `|$crossY − 最近可见数据点 y| < 0.5` 且 `|$crossY − mouseY|` 可任意大 | 吸附的**数值**判据（不依赖指纹，最直接） |
| **CS-9** | `$crossSource.dataIdx` == 由鼠标 x 推算的索引；`$crossSource.dsIndex` 指向的数据点在 x 列里是 y 最近者 | 吸附**目标选择**正确（含 tie 确定性） |
| **CNC-1~5** | `#cn-chart`：插件已挂 / `|$crossY − 数据点 y| < 0.5` / 读数 == 该点值 / 同 x 吸住 / 移出清空 | **覆盖缺口**：`#cn-chart` 已挂插件但**当前无任何 crosshair 断言**（`CN_MACRO_JS` 只查 `#cn-chart-wrap`/`#cn-chart` 的尺寸） |

> **先红后绿流程**：改 JS 前先加 CS-2b / CS-8 / CS-9 并跑一次 → 必须**红**（证明断言在测东西）；
> 改完 JS 后转绿。`pitfalls.md` 已有同款纪律（「先跑红证明断言在测东西」）。

### Step 5 · 文档回填

| 文件 | 动作 | 纪律 |
|---|---|---|
| `web/static/chart-crosshair.js` 头注释 | 更新「硬契约」段：新增 `$crossSource`；**修正**「与系列无关」的定调（改为"吸附到最近系列，线色随系列"）；标注 L4 节流对象 | 头注释是后人判断"是否可改"的依据，必须与实现一致 |
| `docs/architecture.md` | 新增 1 决策行（append-only，**严禁**旧文→新文整体替换） | 与 26/31/33/34 期同惯例 |
| `docs/pitfalls.md` | ①「节流对象必须与被绘制的量一致」②「同 x 纵移指纹变化」类断言在吸附后失效（CS-2/XC-5 实录）③ tie 必须确定性取索引（实测 `colCount=4`） | 只写可复用规则 |

---

## 7. 验证命令

> 来自 `docs/commands.md`。**验证一律串行**（`pitfalls.md`：并行跑 pytest 与 Playwright 会互相制造假失败）。

```bash
# 1) 语法自检（⚠️ 见下方陷阱）
node --check web/static/chart-crosshair.js

# 2) 全量 UI 验收（改前端后必跑；CS-* 首页 / XC-* 宏观页 / CN-* 中国页 全覆盖）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 3) Python 侧回归（本改动不触 Python，但按纪律跑一遍确认零影响）
venv/Scripts/python -m pytest tests/ -v
```

**判据**：退出码 0；`verify_ui.py` 的 CS-2a/2b/8/9、XC-5a/5b、CNC-1~5 全绿；`console error = 0`；产物落 `%TEMP%\marketpulse-verify\`。

### 两个验证陷阱（本项目已记录，勿踩）

1. **`node --check` 不可用于内联 `<script>`**：`web/templates/macro_cn.js` 等文件里含 `</script>` 字面量，正则提取会被提前截断 → 报 `Unexpected end of input`（未改的原始文件也报同样错）。本任务改的是**独立 .js 文件**，`node --check` 直接可用 ✔；但如果顺手校验模板则会被假阴性误导。
2. **DPR≠1 测不出来**：插件内坐标**一律 CSS 像素**，本次实现用的三个量（`e.x/e.y`、`meta.data[].y`、`area.left/right`）**都是 CSS 像素**，**没有任何 `devicePixelRatio` 乘法**。但默认验收跑在 `device_scale_factor=1`，**验证不出 DPR 相关错误** → 必须补一次 **DPR=2** 取证：`device_scale_factor=2` 下断言 `canvas.width === canvas.offsetWidth × 2` 且 `|$crossY − 数据点 y| < 0.5`（**仍以 CSS 像素比较**，不乘 DPR）。

### 未运行的检查（必须标注）

- ❌ **未做**：真实触屏设备验证（`touchmove` 路径与鼠标共用同一 `afterEvent`，但触屏下 `pointHoverRadius:0` + tooltip 被禁 → 横线是唯一读数，吸附收益最大）。本方案只做等价性论证，未实测。
- ❌ **未做**：firefox 内核验证（本改动无 `-webkit-`/`-moz-` 分支与原生控件外观，按 `pitfalls.md` 的判据不属"引擎专项 CSS" → 不必双内核）。

---

## 8. UI 专项

### 8.1 复现路径（从启动到看到现象）

```text
1. cd d:/AGENT/MarketPulse
2. venv/Scripts/python -m uvicorn web.app:app --port 8041        # ★ 新端口（旧进程有 Jinja2 模板缓存）
3. 打开 http://localhost:8041/                                   # 首页趋势主图
4. 鼠标移到主图绘图区**中部偏上**（约绘图区高度 15% 处），停住
   → 现状：横线在鼠标高度；最近的数据线在下方约 197px 处（实测 −197.5）
5. 鼠标**只纵向**移动 130px（保持 x 不动）
   → 现状：横线跟着走 130px，读数随之变化；数据线没动
   → 期望（改后）：横线**不动**（已吸在线上），读数**不变**
6. 鼠标**横向**缓慢扫过整条曲线（保持 y 不动）
   → 现状：横线不动、读数几乎不变（在 /macro/cn 上实测恒为 3950.22）
   → 期望（改后）：横线**沿数据线滑行**，读数随之变为该日期的真实值
7. 打开 http://localhost:8041/macro/cn 重复 4–6（单数据集，现象最纯净）
8. 打开 http://localhost:8041/macro 重复 4–6，并切「全部对比」胶囊（多线，验证换线归因）
```

### 8.2 关键测量点（元素 / 属性 / 期望）

**本改动无 DOM 布局变化 → 不查 CSS 属性，查 canvas 坐标系量。** 全部经 `tab.evaluate` 读回：

| 测量对象 | 表达式（canvas CSS 像素） | 期望 |
|---|---|---|
| 横线当前 y | `chart.$crossY` | 吸附生效时 == 最近数据点 y |
| 吸附目标可测挂钩 | `chart.$crossSource.dsIndex` / `.dataIdx` | 与鼠标 x 推算的索引一致；dsIndex 指向该列 y 最近者 |
| 读数 | `chart.$crosshairLabel` | == `formatter(scales.y.getValueForPixel($crossY))`（CS-4 不变）；且 == 吸附点**真实数据值**的格式化结果 |
| 吸附误差（**核心判据**） | `\|chart.$crossY − 最近可见数据点 y\|` | **< 0.5**（实测可用的点坐标见 §3.4） |
| 是否仍跟手 | `\|chart.$crossY − mouseY\|` | 允许**很大**（实测基线最大 268.9）→ 改后不再趋近 0。⚠️ 反向断言：`\|$crossY − mouseY\|` **不得**恒 < 1（那是旧行为） |
| 绘图区几何（不变） | `chart.chartArea` | 首页 (11,10)-(979,405)；`#cn-chart` (31,10)-(1304,469) |
| 画布位图 == 显示尺寸（**C2 回归**） | `canvas.width === canvas.offsetWidth && canvas.height === canvas.offsetHeight`（DPR=1） | 相等。首页 1024×432、`#cn-chart` 1346×496 |
| 数据集数 / 可见性 | `chart.data.datasets.length`、`getDatasetMeta(i).hidden` | 首页美股 tab=2、波动率 tab=3、`#cn-chart` 默认=1 |
| 缺口场景 | 多品种模式下 `meta.data[idx].y` 为 `NaN` 的比例 | `/macro/cn` 多品种日期轴是并集 → 必然出现，须验证退化路径 |

**取数陷阱**：`chart.data.labels` 恒为空（x 轴用 `type:'category'` + `options.scales.x.labels`）；
要数「渲染了多少点」必须读 `chart.data.datasets[].data.length`（`pitfalls.md` 已记录该假失败）。

### 8.3 `box-sizing` 说明（本改动为何**不适用**，以及等价的坐标系约束）

**诚实结论：本改动不涉及任何 DOM 盒模型。** 横线与气泡都是**画在 `<canvas>` 上的像素**，
不产生 DOM 盒、不参与布局、不受 `box-sizing` 影响（全局 `* { box-sizing: border-box }`
（`style.css:79`）对本改动无任何作用面）。因此**不伪造 box-sizing 分析**；改用 canvas 的**等价三坐标系**约束：

| 坐标系 | 单位 | 本改动是否使用 | 说明 |
|---|---|---|---|
| **事件坐标** `e.x` / `e.y` | CSS 像素（相对 canvas） | **是** | Chart.js 已归一化；**不得**再乘 DPR |
| **element 坐标** `meta.data[i].x/.y` | CSS 像素 | **是**（吸附的核心） | 与事件坐标同空间 → 可直接比较求最近点。**这是本方案不需要任何换算的根本原因** |
| **位图坐标** `canvas.width/height` | 位图像素 = CSS × DPR | **否** | 仅在验收断言里用于比对 C2 |
| **绘图区** `chart.chartArea` | CSS 像素 | **是**（钳制 x、画线范围） | 与上面两个同空间 |

**必须守住的等价纪律**：
1. 坐标系**不得混用**：吸附只比较 CSS 像素（`e.x/e.y` ↔ `meta.data[].y`）。任何一处乘了 `devicePixelRatio`，在 DPR=2 屏上吸附点会偏移一倍，而 **DPR=1 的默认验收测不出来**（§7 陷阱 2 给出 DPR=2 取证法）。
2. `meta.data[i].y` 在**缺口处为 `NaN`** → 必须 `isFinite()` 守卫，否则 `argmin` 会把 NaN 当最小值选中（JS 里 `NaN` 比较恒 false，会导致选中错误的元素或 undefined 访问）。
3. 吸附点圆点半径（3px）与虚线 `lineWidth`（1px）是 **canvas CSS 像素**，与会话中的 DOM 尺寸（如 `.mac-card` 的 `padding 20px`）**无关系**，调它们不影响任何布局断言（不影响 `scrollHeight ≤ 1240` 那条）。

### 8.4 多尺寸验收

本改动**不改变任何元素尺寸**，理论上与视口无关；但吸附依赖 `chartArea` 与采样点像素间距，
**视口/容器尺寸变化会改变点间距 → 影响 tie 出现频率与吸附精度** → 仍须多尺寸取样。

| 视口 | 期望 |
|---|---|
| **1920×1080**（常规） | 三图 `\|$crossY − 数据点 y\| < 0.5`；`canvas` 位图 == 显示尺寸；CS-2a/2b/8/9、XC-5a/5b、CNC-1~5 全绿；`console error = 0`；`scrollHeight ≤ 1240`（回归护栏，**本改动不应改变它**） |
| **1280×720**（小窗口） | 同上（首页主图容器 `340px`，绘图区更矮 → 点间距更小，更易触 tie）：换线仍正确、无 NaN 选中、无 console error |
| **375×812**（移动端） | 吸附逻辑与视口无关，但触屏路径（`touchmove`）在 Playwright 里需 `hasTouch=true` 才走 → 若不便模拟，**至少断言鼠标路径在该视口仍工作**，并在 journal 里标注触屏未实测 |
| **DPR=2**（★ 必须补） | `canvas.width === offsetWidth × 2`；`\|$crossY − 数据点 y\| < 0.5`（**CSS 像素比较，不乘 DPR**）→ 证明没有坐标系混用 |
| **1500×900**（★ 中间盲区） | 本项目 `verify_ui` 只测 1920/1280/375，**恰好避开 1500–1919 与 769–1024**（`pitfalls.md` 记录过 KPI 在该盲区被截断）。本改动虽不改布局，但吸附断言的**期望值随绘图区高度变化** → 补测一次确认断言不是"只在 1920 成立" |

**覆盖度护栏**：新增的多宽度/多 DPR 取样要**断言实际执行的采样数**，否则选择器或渲染一变，扫描会**空跑并全绿**（`pitfalls.md` 已有同款教训）。

---

## 9. 风险评估

| # | 风险 | 级别 | 说明与缓解 |
|---|---|---|---|
| **R1** | **CS-2 必红**被误判为"改坏了" | **高** | §3.6 **实测确证**必红（y=0.3 与 y=0.7 都吸附到 `297.63`）。处置：**改为 CS-2a/CS-2b 补强**，不删除、不放松。`pitfalls.md` 的判别表：渲染路径未变、只是产品语义变了 → "断言脆弱"而非"方案不可行" |
| **R2** | **XC-5 实测仍绿，但"绿"会掩盖语义漂移** | **高** | 实测 `243.15` vs `366.97`（最近线恰好切换）→ 断言仍在绿。**危险恰在于"绿"会被读成"无需改"**：它绿的原因是"换了目标线"，不是"吸附正确"。处置：仍按 §6 Step 4 拆为 XC-5a + XC-5b；journal **必须显式记录"绿但语义已变"**，否则后人复跑看到绿就以为这条已覆盖 |
| **R3** | **L4 节流漏改** → 单数据集图（`/macro/cn`）每帧无意义重绘 | **中** | `pitfalls.md` 已记录 crosshair 重绘是 FPS 关注点。修法见 Step 2；断言：鼠标纵移时 `$crossY` 不变且只应触发一次重绘（可用 `chart.$crossDrawCount` 计数钩子取证，**实现时加，验收时读**） |
| **R4** | **tie 导致索引不确定** → 同一点相邻两次吸附到不同索引，线抖动 | **中** | 实测 `colCount=4` 确实发生（§3.4(2)）。修法：并列取**较小索引**；断言 CS-9 覆盖 |
| **R5** | **缺口处 NaN 被当最小值** | **中** | `meta.data[i].y` 在缺口为 NaN（`/macro/cn` 多品种模式必然出现）。必须 `isFinite()` 守卫 + ±3 邻域回退 + 最终回退鼠标 y |
| **R6** | **方案 B 推翻既有设计**（"中性色、与系列无关"）引发后人回退 | **中** | 头注释 + `architecture.md` 决策行同步说明"吸附后线必然属于某系列"；不做的话，新行为会被当成违反既定设计 |
| **R7** | **坐标系混用**（乘了 DPR）→ 仅 DPR=2 可见 | **中** | 默认验收 DPR=1 **测不到**。修法：§7 陷阱 2 的 DPR=2 取证步骤；实现里不出现 `devicePixelRatio` |
| **R8** | **工作区有未提交的中国页改动**，本次改动叠加其上 | **中** | `git status` 实测：`src/cn_econ_fetcher.py` / `web/static/macro_cn.js` / `verify_ui.py` 等 12+ 文件未提交。风险：auto-commit cron 随时可能把它们连同本次半成品一起提交（`pitfalls.md` 记录过连做 4 次 `git add -A` 吞掉半成品）。缓解：**改动是否安全以 `git log --oneline -- <path>` 反查，不要只看 `git status`** |
| **R9** | 触屏路径未实测 | **低** | 共用 `afterEvent`，逻辑等价；但触屏下 `pointHoverRadius:0` + tooltip 禁用 → 横线是唯一读数，吸附收益最大。**记为取证缺口** |
| **R10** | 性能：多点扫描 O(n·d) 每帧 | **低** | 上限 ≈ 250 点 × 3 数据集 = 750 次比较/事件，可忽略；且节流后多数事件早退 |

---

## 10. 影响文件范围

| 类型 | 文件 | 规模（估） |
|---|---|---|
| 修改 | `web/static/chart-crosshair.js` | ~+55 / −12 行（纯函数 ~28 行 + `afterEvent` 改 ~14 行 + `afterDatasetsDraw` 改 ~13 行 + 头注释更新） |
| 修改 | `tasks/.../verify_ui.py` | ~+85 行（CS-2 拆分 + CS-8/CS-9 + XC-5 拆分 + `CNC-1~5` 新函数 + DPR=2 取证） |
| 修改 | `docs/architecture.md` | +1 决策行 |
| 修改 | `docs/pitfalls.md` | +3 条 |
| 新增 | `tasks/2026-09-15-crosshair-snap/journal.md` | — |
| 删除 | 无 | — |

**零改动**：`src/**`、`tests/**`、`web/templates/**`、`web/static/app.js`、`web/static/macro.js`、`web/static/macro_cn.js`、`web/static/style.css`、`web/app.py`（`_ASSET_FILES` 已含 `chart-crosshair.js`，实测确认）。
**调用点零改动**：三页 `plugins: [window.hoverCrosshair]` / `[window.makeHoverCrosshair({formatter})]` 契约不变。

---

## 11. 不做什么

- **不改**三页的业务脚本与调用点（插件对外契约不变）
- **不改** `chart.$crosshairLabel` / `chart.$crossY` 的**语义与公式**（CS-4 / XC-2/3/4 依赖；只改 `$crossY` 的**取值来源**，公式逐字不动）
- **不改**可见性规则（仍只判 y；不为吸附顺手把 x 加进可见性判断，否则 CS-3 语义变化）
- **不引入** `Chart.register`（保持内联插件，避免影响全局实例）
- **不改**气泡文案（方案 C 已否决，见 §2.2）
- **不新增**依赖、不新增静态文件（因此**无需**动 `_ASSET_FILES`）
- **不做**动画/过渡（吸附是逐点跳变；加 easing 会让"吸住"的判据不可测，且 `pitfalls.md` 已记录"动画态断言必须等过渡结束"的坑）
- **不处理** R8 的中国页未提交改动（不属本任务范围，仅标注）

---

## 12. 确认清单

- [x] **已确认（2026-09-15）**：采用**方案 B**（吸附 + 线色归因 + 吸附点圆点），接受**推翻**"中性色、与系列无关"的既有设计（§2.2）
- [x] **已确认（2026-09-15）**：吸附目标规则 = **先定 x（最近索引，tie 取小）→ 再取该列最近 y 的可见数据集**；**允许随纵向移动换线**（§2.1）
- [ ] 已确认退化策略 4 条（全 NaN 邻域回退 → 鼠标 y；x 越界钳制；y 越界隐藏；hidden 跳过）（§2.3）
- [ ] 已确认 **CS-2 / XC-5 按"补强"处置**（拆成 a/b 两条新语义断言），**不删除、不放松**
- [ ] 已确认 `verify_ui.py` 需新增 `#cn-chart` 的 crosshair 断言（当前**完全无覆盖**）
- [ ] 已确认补 **DPR=2** 取证（默认 DPR=1 测不到坐标系混用）
- [ ] 已确认 `$crossSource` 作为新增可测挂钩（不破坏既有挂钩）
- [ ] 已知悉工作区含**未提交的中国页改动**（R8），改动安全性以 `git log -- <path>` 反查
- [ ] 文件范围合理、无遗漏断言、无新依赖
- [ ] 人已审阅本计划

---

## 附：核心逻辑伪代码

```text
# ---- 吸附纯函数（scale 无关，只用真实 element 坐标）----
function snapToNearest(chart, mx, my) {
  var area = chart.chartArea;
  if (!area) return null;
  var cx = Math.min(Math.max(mx, area.left), area.right);   // L5：钳制 x（可见性仍只判 y）

  var idx0 = null, bestDx = Infinity;
  chart.data.datasets.forEach(function (ds, i) {
    var m = chart.getDatasetMeta(i);
    if (m.hidden) return;
    (m.data || []).forEach(function (p, idx) {
      if (!p || !isFinite(p.x)) return;
      var d = Math.abs(p.x - cx);
      // tie 取较小索引 → 确定性（实测 tie 会真实发生，colCount 曾为 4）
      if (d < bestDx - 1e-9 || (Math.abs(d - bestDx) <= 1e-9 && idx0 !== null && idx < idx0)) {
        bestDx = d; idx0 = idx;
      }
    });
  });
  if (idx0 === null) return null;

  // 缺口回退：idx0±1..±3 找第一个有有限 y 的列
  var OFFS = [0, -1, 1, -2, 2, -3, 3];
  for (var k = 0; k < OFFS.length; k++) {
    var idx = idx0 + OFFS[k];
    var best = null;
    chart.data.datasets.forEach(function (ds, i) {
      var m = chart.getDatasetMeta(i);
      if (m.hidden) return;
      var p = (m.data || [])[idx];
      if (!p || !isFinite(p.y)) return;                      // ★ NaN 守卫（缺口必经）
      if (!best || Math.abs(p.y - my) < Math.abs(best.y - my)) best = { y: p.y, dsIndex: i };
    });
    if (best) return { y: best.y, dsIndex: best.dsIndex, dataIdx: idx };
  }
  return null;                                               // 全空 → 调用方回退鼠标 y
}

# ---- afterEvent（节流对象改为吸附后的 y）----
snap = snapToNearest(chart, e.x, e.y)
targetY = snap ? snap.y : e.y
if (chart.$crossY != null && Math.abs(targetY - chart.$crossY) < 0.5) return;  // ★ L4
chart.$crossY = targetY
chart.$crossSource = snap ? { dsIndex: snap.dsIndex, dataIdx: snap.dataIdx } : null
chart.draw()

# ---- afterDatasetsDraw（读数公式逐字不变；新增线色归因 + 吸附点圆点）----
text = resolveFormatter(chart)(axis.getValueForPixel(y), chart)   # ← 与原实现完全相同
chart.$crosshairLabel = text                                      # ← 挂钩语义不变
stroke = ($crossSource && 方案B) ? withAlpha(ds[i].borderColor, 0.65) : withAlpha(tc.axisTick, 0.65)
```
