# MarketPulse 看板玻璃化（Glassmorphism）· 实施计划

> 架构师产出（Phase 3）。**只提供方案，不含完整实现代码**；代码由执行者编写。
> 基线数据来自 **Playwright 实测**（dark + light 各一遍，1920×1080，DPR=1），非代码推演。

---

## 0. 前置说明

| 项 | 说明 |
|---|---|
| 触发 | `tasks/2026-09-11-frontend-bento-redesign/plan.md`（Bento 重构 P0）**已完成并通过验收**，但需求方反馈「做出来的前端没有效果图里的玻璃感」 |
| 任务关系 | 本文件是**独立的后续任务**。旧 plan 保持「已完成」状态，**不要再向旧 plan 追加内容** |
| 前置产物 | 旧任务已交付：`web/templates/index.html`(185 行) / `web/static/style.css`(412 行) / `web/static/app.js`(826 行) / `web/app.py`(547 行) / `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`(387 行验收脚本) |
| prd.md | 本任务无 prd.md；Goal 来源 = 需求方反馈「没有效果图的玻璃感」 + §12 待确认项 |
| **责任归属** | **玻璃缺失源于旧 plan §7 Step 2 的 token 设计**：`.card { background: var(--bg-elevated) }` 用的是**不透明**色、`body` 是**纯色**底。**执行者无过错**，本计划修正的是方案层缺陷 |

**要求方原话**：「任务完成了，但是做出来的前端没有效果图里的玻璃感」

---

## 1. 任务目标

**Goal**

让看板卡片呈现效果图所示的玻璃质感 —— **半透明面板 + 背景透光模糊 + 边缘拾光 + 背景氛围层次**，同时**不回退**上一轮已达成的布局与功能验收。

**一句话验收标准**

1920×1080 下：**所有非 promo 卡片与 KPI 卡全部** `backdrop-filter !== 'none'`（“全覆盖”断言为 true）、卡片背景 alpha **<0.2（展示型）/ 0.6~0.8（数据型）**、`body` 有 **≥2 层**氛围渐变、卡片外发光模糊半径 **≥24px**；**且 `scrollHeight` 仍 ≤1240、无横向溢出、Console error 恒 0**。

（用“全覆盖”而不用“计数”，是为避免 Step G-9 结构重排改变卡片数量后断言失效。）

**必须保持（回归护栏，不得回退）**

| 指标 | 上一轮实测 | 本任务要求 |
|---|---|---|
| `document.scrollingElement.scrollHeight` @1920×1080 | **1235** | **≤1240**（不变） |
| `scrollingElement.scrollWidth === innerWidth` | true | 必须 true |
| `console` error 数 | **0** | **0** |
| `.row-kpi` 列数 @1920 | 5 列同排 | 不变 |
| 375 下 `#menu-toggle` → `body.nav-open` 抽屉 | 正常 | 正常 |
| 双主题（`data-theme` dark/light） | 均正常 | 均正常 |
| 顶栏日期 `2026-09-11 周五` | 正确 | 不变 |

**Out of Scope（本次不做）**

- 不改 `web/app.py`、`web/static/app.js`、API 契约、`src/*`（玻璃化是纯 CSS 层）。
- **不改 `app.js`**（玻璃化纯 CSS；Step G-9 的结构搬迁经核实也**不需要**动 `app.js`，见 §6 Step G-9 说明）。
- `index.html` **允许结构性改动，但仅限 Step G-9**（底部行按效果图重排）；其余部分不动。
- 不动 `data/` `context/` `alerts/` `reports/`（生成物）。
- 不改 `tests/`（本任务无 Python 逻辑变更；验收走 `verify_ui.py`）。
- 不新增任何依赖、不引入字体外链、不新增二进制图片资源（§4.4 promo 例外需 §12 确认）。
- 不重做栅格/布局（上一轮已达标）。

---

## 2. 现状基线（实测取证）

**测量方式**：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（该脚本自动挑空闲端口起 uvicorn、跑完自动结束、截图与 JSON 落 `$env:TEMP/marketpulse-verify`）。
**补充取证**：本次架构分析另跑了一次计算样式探针（`backdropFilter` / `backgroundColor` / `backgroundImage` / `boxShadow` / `borderColor` 全量扫描），dark 与 light 各一遍。

### 2.1 玻璃判据实测

| 判据 | Dark | Light | 结论 |
|---|---|---|---|
| 全站 `backdrop-filter !== none` 的元素数 | **0** | **0** | ❌ 模糊机制**完全不存在** |
| 全站 `background-image !== none` 的元素数 | **1** | **1** | ❌ 仅 `.card.promo`，**无背景氛围层** |
| `.kpi-card` 的 `background-color` / alpha | `rgb(17,24,39)` / **1** | `rgb(255,255,255)` / **1** | ❌ 完全不透明 |
| 普通 `.card`（`#trend`/`#alerts` 等）alpha | **1** | **1** | ❌ 完全不透明 |
| `body` 的 `background-color` / `background-image` | `rgb(11,15,20)` / **none** | `rgb(247,248,250)` / **none** | ❌ **纯色底，无氛围** |
| `.topbar` alpha | **1**（`rgb(11,15,20)`） | **1**（`rgb(247,248,250)`） | ❌ 不透明，加 blur 也看不见 |
| `#sidebar` alpha | **1** | **1** | ❌ 同上 |
| `--card-glow`（顶边内高光） | `inset 0 1px 0 rgba(255,255,255,.03)` | `inset 0 1px 0 rgba(255,255,255,.7)` | ⚠️ 深色下 3% 白 ≈ **肉眼不可见**；两主题差 **23 倍** |
| `--card-shadow`（dark） | `0 1px 2px rgba(0,0,0,.32), 0 2px 8px rgba(0,0,0,.18)` | — | ⚠️ 纯黑投影叠在 `#0B0F14` 上 → 卡片**浮不起来** |
| `.card.promo` `background-image` | `linear-gradient(135deg, rgb(29,78,216), rgb(14,165,233) 55%, rgb(20,184,166))` | 同 | ❌ 高饱和亮渐变 = 营销 banner 语言 |
| `.card` / `.card.promo` 的 `borderTopColor` | `rgba(0,0,0,0)`（promo **显式** transparent） | 同 | ❌ 玻璃切边被关掉 |

### 2.2 布局侧（已达标，不得回退）

| 指标 | 实测 | 目标 | 结论 |
|---|---|---|---|
| `scrollHeight` @1920×1080 | **1235** | ≤1240 | ✅（旧版 2632） |
| `scrollWidth === innerWidth` | 1920 === 1920 | 必须 | ✅ |
| `.card` / `.kpi-card` 数 | 10 / 4 | — | ✅ bento 栅格化成功 |
| `console` error | **0** | 0 | ✅ |
| 顶栏日期 | `2026-09-11 周五` | 周五 | ✅（旧缺陷 C6 已修） |
| 占位模块 | 资讯 / 资金流向 / 风险偏好 = 「数据未接入」 | 3 处 | ✅ |

→ **只需修视觉层。布局与数据层一律不动。**

---

## 3. 根因分析（两层）

### 3.1 渲染表现根因（用户实际看到什么）

1. **画面没有层次**：整页只有一个纯色 `rgb(11,15,20)`，无明暗过渡、无色彩光斑 → 玻璃要「折射」的对象不存在，观感是「黑底上几个深灰矩形」。
2. **卡片像印刷色块，不像透光面板**：卡片 `rgb(17,24,39)`（alpha=1）盖在 `rgb(11,15,20)` 上，仅差一点点亮度 → 卡片边界只靠一条 `rgb(30,39,51)` 细线维系，无任何「透光 / 折射」暗示。
3. **卡片浮不起来**：投影是纯黑 `rgba(0,0,0,.32)`，在近黑背景上对比度≈0 → 本应「悬于背景之上」的卡片反而像「贴在背景上的补丁」。
4. **边缘没有拾光**：顶边内高光仅 `rgba(255,255,255,.03)`（3% 白）× `#111827` → ΔL 远低于人眼阈值，**实际不可见**；玻璃标志性的「顶边一道亮线」完全缺失。
5. **promo 卡是全页最扎眼的违和点**：`rgb(29,78,216)→rgb(14,165,233)→rgb(20,184,166)` 高饱和亮渐变，在一片近黑中像广告位；效果图那张卡是「暗调图片 + 半透明暗遮罩 + 玻璃边」。
6. **滚动时没有「玻璃扫过背景」的动感**：既无模糊也无背景变化，卡片与背景刚性绑定。

### 3.2 代码逻辑根因（CSS 机制）

| # | 机制根因 | 位置（当前文件行号） |
|---|---|---|
| **G1** | **玻璃三要素同时缺失且互为前提**：① 半透明面板 ② `backdrop-filter` ③ 背景可模糊内容。当前 ① `--bg-elevated` alpha=1，② 全站 0 处，③ `body` 纯色 | `style.css:154-161`（`.card`）、`:188-194`（`.kpi-card`）、`:54-61`（`body`） |
| **G2** | **token 语义错配**：`--bg-elevated` 的语义是「提升层**不透明**底色」，被直接当卡片底色复用。玻璃需要**独立一组** glass token（bg alpha / border alpha / highlight / blur / saturate），**不能**复用不透明色 token | `style.css:4,32`（`:root` / `[data-theme="dark"]`） |
| **G3** | **`--card-glow` 双主题量级不一致**：dark `.03` vs light `.7`（**23 倍**）。同名 token 承载两种视觉强度 → 深色主题高光失效，且改 light 参数会误伤 dark | `style.css:19,43` |
| **G4** | **`--card-shadow` 在深色下是纯黑**。深色底上玻璃卡片需要「微弱外发光 + 内高光」，黑投影在近黑底上不可见 | `style.css:42` |
| **G5** | **边框是不透明深色** `rgb(30,39,51)`：形成「描边线」而非玻璃「半透明切边」。玻璃边须 `rgba(255,255,255,.08~.14)`，靠背景透出形成切边高光 | `style.css:34,156` |
| **G6** | **promo 卡走「实色渐变填充」路径**（`.card.promo{background:linear-gradient(...); border-color:transparent}`），被实现为「彩色卡片」而非「图 + 玻璃叠层」→ **无法靠调 token 变玻璃**，必须单独改 | `style.css:216-232` |
| **G7** | **无 `saturate()`**：玻璃感相当一部分来自背景色被 `saturate(160~180%)` 提纯后透出。只加 `blur()` → 透出来仍偏灰 | 全站 |
| **G8** | **无背景氛围层**：`body`/`.main`/`.dash` 均无 `background-image` 与 `::before` 光斑 → 即 G1 的 ③，也是**修复的首要工作项** | `style.css:54-61, 142-151` |

### 3.3 因果链（本计划的核心结论）

```text
[背景氛围层]        ← 缺失 G8：body 无渐变/光斑，纯色
      │  没有它，后面两步全部无效
      ▼
[面板半透明]        ← 缺失 G1①：--bg-elevated alpha = 1
      │  没有它，backdrop-filter 采样不到任何东西
      ▼
[backdrop-filter: blur() saturate()]   ← 缺失 G1② / G7
      │  只有到这里，前三步才开始产生「玻璃」视觉
      ▼
[半透明亮边 + 内高光 + 外发光]  ← 缺失 G3/G4/G5：切边拾光
      ▼
[玻璃感]
```

**反例（务必写进交接说明）**：
- 只给 `.card` 加 `backdrop-filter: blur(20px)`，但卡片 alpha 仍为 1 → **模糊层根本不渲染**；
- 卡片 alpha 改低、但背景仍是纯色 → 模糊纯色 ≡ 同色 → **视觉零变化**；
- 只有当「背景有内容」+「面板半透明」同时成立，`backdrop-filter` 才开始起效。

**这就是"加了没效果"的机制解释。** 顺序不能颠倒是本计划最重要的一条纪律。

---

## 4. 方案（替代方案 + 选型）

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（选）真玻璃** | `body` 叠多层 `radial-gradient` 氛围 → 卡片降低 alpha → 加 `backdrop-filter: blur() saturate()` → 半透明亮边 + 内高光 + 外发光 | 唯一能产生真正「透光模糊」的机制。Chromium/Safari 支持良好（本项目已依赖 `:has()` 与 `color-mix()`，`backdrop-filter` 必然可用） |
| B 伪玻璃（降级） | 不做 `backdrop-filter`，仅用「半透明底 + 多层 `inset/outer` 阴影 + 亮边 + 氛围光斑」模拟 | 视觉约达 80%，**零层叠上下文副作用、零滚动开销**；作为 `@supports not (backdrop-filter: blur(1px))` 的降级路径 |
| C 图片背景 | 页面铺一张暗色纹理图，玻璃叠上去 | 最接近效果图的 promo 观感，但违反「不新增二进制资源」；整页图片拖累加载与主题切换 |

**选型：A 为主 + B 作 `@supports` 降级。** 理由：A 是必要机制；B 独用时在深色底上玻璃感依然弱（无模糊），只能兜底不能主用。

### 4.1 氛围层的实现要点（关键，决定成败）

**不要新建 `position:fixed` 的 DOM 层，直接给 `body` 叠多层背景：**

```text
/* 伪代码 —— 只描述层序，不写完整实现 */
body {
  background-image:
    var(--ambient-1),   /* 左上 蓝光斑 */
    var(--ambient-2),   /* 右上 紫光斑 */
    var(--ambient-3);   /* 底部 青光斑 */
  background-color: var(--bg-primary);   /* 最底层，保持原纯色 */
  background-attachment: fixed;          /* 光斑固定；卡片滚动时"玻璃扫过背景"更真实 */
  background-repeat: no-repeat;
}
```

**为什么不用新增 DOM 层**：

1. **背景不参与布局** → 绝不会把刚达成的 `scrollHeight = 1235` 撑大（新增 in-flow 元素会直接毁掉 §2.2 验收）；
2. 不引入 `z-index` 关系变化 → 不与 `.topbar:100` / `#sidebar:60` / `.nav-backdrop:55` 打架；
3. 无额外合成层，零滚动开销。

⚠️ **反面写法**：`body::before { position: fixed; inset: 0; z-index: -1 }` —— 会被 `body` 自身的不透明 `background` **盖住而完全不可见**（经典陷阱），需同时把 `body` 底色改成透明。**不推荐**。

### 4.2 推荐的 glass token（双主题，**必须分别调参**）

> ⚠️ **本节参数已被 §4.6.2「效果图校准值」取代**（2026-09-11 需求方重发效果图后校准）。
> 实施时**以 §4.6.2 为准**；本节保留作为推导过程与替代方案记录。

**Dark（`[data-theme="dark"]`）**

| token | 建议值 | 说明 |
|---|---|---|
| `--glass-bg`（展示型：KPI / promo / 板块卡） | `rgba(255,255,255,.045)` | 低 alpha 才算玻璃 |
| `--glass-bg-strong`（**数据密集**：`#overview`/`#trend`/`#alerts`） | `rgba(17,24,39,.72)` | 保表格小字可读性（见 R17） |
| `--glass-border` | `rgba(255,255,255,.10)` | 半透明亮边 |
| `--glass-highlight` | `inset 0 1px 0 rgba(255,255,255,.10)` | 顶边拾光（**替代** `--card-glow` 的 3%） |
| `--glass-blur` | `blur(18px) saturate(180%)` | **必须带 `saturate`**（G7） |
| `--glass-shadow` | `0 8px 32px rgba(0,0,0,.40)` | **替代** `--card-shadow` 的 1~2px 小黑影 |
| `--ambient-1` | `radial-gradient(900px 620px at 10% -8%, rgba(59,130,246,.22), transparent 62%)` | 蓝 |
| `--ambient-2` | `radial-gradient(760px 520px at 90% 4%, rgba(139,92,246,.18), transparent 62%)` | 紫 |
| `--ambient-3` | `radial-gradient(900px 640px at 55% 105%, rgba(20,184,166,.14), transparent 62%)` | 青 |
| `--bg-primary` | **不变** `#0B0F14` | 作为最底背景层 |

**Light（`:root`）**

| token | 建议值 |
|---|---|
| `--glass-bg` | `rgba(255,255,255,.62)` |
| `--glass-bg-strong` | `rgba(255,255,255,.86)` |
| `--glass-border` | `rgba(255,255,255,.90)` |
| `--glass-highlight` | `inset 0 1px 0 rgba(255,255,255,1)` |
| `--glass-blur` | `blur(16px) saturate(150%)` |
| `--glass-shadow` | `0 8px 28px rgba(16,24,40,.10)` |
| `--ambient-1` | `radial-gradient(900px 620px at 10% -8%, rgba(22,119,255,.12), transparent 62%)` |
| `--ambient-2` | `radial-gradient(760px 520px at 90% 4%, rgba(114,46,209,.10), transparent 62%)` |
| `--ambient-3` | `radial-gradient(900px 640px at 55% 105%, rgba(19,194,194,.10), transparent 62%)` |
| `--bg-primary` | **不变** `#F7F8FA` |

**同时退役 / 整改**：

- `--card-glow` → 由 `--glass-highlight` 取代（消除 G3 的 23 倍量级错配）。
- `--card-shadow` → 由 `--glass-shadow` 取代（消除 G4 的纯黑投影）。

⚠️ 退役时须确认**无遗漏引用**：CSS 变量未定义会让**整条声明 invalid**（不是只丢那一段）。例如 `box-shadow: var(--glass-shadow), var(--glass-highlight)` 中若变量名拼错，**整条 `box-shadow` 会被丢弃** → 表现为「卡片突然没阴影」，容易被误判为选择器写错（见 R21）。

### 4.3 顶栏 / 侧栏（**已按效果图定稿**，见 §4.6.3）

- **`.topbar` → 玻璃化**：`background` 改 `rgba(11,15,20,.72)`（light `rgba(247,248,250,.72)`）+ `backdrop-filter: var(--glass-blur)`，底边 1px `var(--glass-border)`。滚动时内容在顶栏下模糊穿过，是效果图里最明显的玻璃线索。
- **`#sidebar` → 只改透明**：`background: transparent`，保留 1px 右分隔线，**不加** `backdrop-filter`。依据：效果图侧栏与页面同层、仅靠分隔线区分，本身不是玻璃层；同时规避 R19（sticky + blur 残影）与 R18（层叠上下文）。

⚠️ `.topbar` 仍受 R18/R19 约束（`position: sticky` + `z-index: 100`），须实测（§6 Step G-6）。

### 4.4 promo 卡（必须单独改 —— G6）

> ⚠️ **本节已被 §4.6.4 取代：需求方 2026-09-11 决定「先不管他」，本任务不做 promo 视觉改造。**
> 仅保留一条动作：给 `.card.promo` 显式 `backdrop-filter: none`。本节其余内容留作后续任务的参考方案。

目标形态 = 「氛围图 + 半透明暗遮罩 + 玻璃边 + 白字」：

1. 底色由**高饱和亮渐变**改为**低饱和暗调**（如 `linear-gradient(160deg, rgba(37,99,235,.50), rgba(15,23,42,.78))` 叠一层 `radial-gradient` 作「图片氛围」）；
2. 保留现有 `.promo-visual` 内联 SVG 作为「图像抽象」；
3. `border-color: transparent` → 改回 `var(--glass-border)`（当前该声明把玻璃切边**显式关掉**了）；
4. 加同一套 `--glass-blur`。

### 4.5 降级路径（方案 B）

```text
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  /* 提高 alpha 至近实色 + 加强 inset 高光 + 去掉 blur，保证文字可读、视觉不塌 */
}
```

### 4.6 效果图校准参数（2026-09-11 重发效果图后）

**总判**：效果图是 **低强度玻璃（subtle glass）**，不是高饱和霓虹玻璃。玻璃观感由三样东西构成 —— **① 背景斜向冷色光束 + ② 1px 冷色亮描边 + ③ 低 alpha 面板（背景可见）**；**不靠**重投影，也**不靠**强内发光。→ 这就要求 §4.2 的 `saturate 180%` 与 `0 8px 32px rgba(0,0,0,.40)` 都要**下调**。

#### 4.6.1 背景氛围层（效果图最显眼的玻璃线索，当前完全缺失）

| 层 | 效果图观察 | 建议实现（伪代码） |
|---|---|---|
| **L1 右上大范围柔光** | 页面右上区（promo 卡后方一带）明显更亮 | `radial-gradient(1200px 820px at 78% -8%, rgba(150,190,255,.14), transparent 62%)` |
| **L2 斜向光束** | 一条宽约页面 1/3 的冷色斜带，方向约 **120~150°**（左下 → 右上），斜穿趋势图与市场情绪卡区域 | `linear-gradient(148deg, transparent 18%, rgba(120,160,220,.07) 40%, transparent 64%)` |
| ~~**L3 极淡斜向纹理**~~ | ~~背景可见规则平行斜纹（间距约 5~8px）~~ → **需求方 2026-09-11 判定为「噪声」，不加** | — |

- 层序：**L1 → L2 →** `background-color: var(--bg-primary)`（**仅两层**，L3 已否决），沿用 §4.1 的 `body` 多层 `background-image` 方案。
  → 因此 §6 Step G-1 的**断言 4 目标值由「≥3 层」下调为「≥2 层」**（判据随之更新，避免断言与方案不一致而恒 FAIL）。
- ⚠️ `background-attachment: fixed` 下所有层相对**视口**定位 → 滚动时光束不动、卡片在光束上滑过 → 正是「玻璃扫过背景」的观感（效果图即此语义）。
- ⚠️ 三层都用 `px` 尺寸，小视口下仍能覆盖卡片区域，避免 §8.2「卡片全落在纯色区、看不出玻璃」。

#### 4.6.2 卡片参数（**校准值，取代 §4.2 的建议值**）

| token | Dark（校准） | Light（校准） | 效果图依据 |
|---|---|---|---|
| `--glass-bg` | `rgba(255,255,255,.035)` | `rgba(255,255,255,.66)` | 卡内可见背景光束但被压暗 → 低 alpha。**校准旋钮**：若实测卡内光束过亮，改用暗色面板 `rgba(15,22,34,.45)` |
| `--glass-bg-strong`（数据卡 `#overview`/`#trend`/`#alerts`） | `rgba(17,24,39,.66)` | `rgba(255,255,255,.88)` | 表格/图表区比展示卡更实，保证 12px 小字可读 |
| `--glass-border` | `rgba(155,185,230,.20)` | `rgba(255,255,255,.92)` | 效果图描边是**可见的冷色亮线**；当前 `rgb(30,39,51)` 太平太暗 |
| `--glass-highlight` | `inset 0 1px 0 rgba(255,255,255,.07)` | `inset 0 1px 0 rgba(255,255,255,1)` | 效果图顶边亮线**含蓄**，比 §4.2 的 `.10` 再降一档 |
| `--glass-blur` | `blur(20px) saturate(150%)` | `blur(18px) saturate(140%)` | 卡内光束被平滑扩散 → blur 偏大；`saturate` 由 180% **下调**（效果图是低饱和冷调，非霓虹） |
| `--glass-shadow` | `0 1px 1px rgba(0,0,0,.28), 0 12px 40px rgba(0,0,0,.36)` | `0 8px 28px rgba(16,24,40,.08)` | 效果图卡片**几乎看不到投影**，形体定义主要来自描边 → 阴影只做极轻托底 |
| `--radius-card` | `12px`（**不变**） | 同 | 效果图圆角 ≈10~12px |

**三条关键校准结论**：

1. **描边是"冷色亮线"（偏蓝白），不是深灰线** —— 这是「玻璃切边」观感的主要来源，**比内高光更重要**。当前 `rgb(30,39,51)` 是深色描边，方向就错了。
2. **`saturate` 从 180% 降到 150%**：效果图是低饱和冷调。
3. **`--glass-shadow` 要减弱**：不要用强投影去"托"卡片（§4.2 的 `0 8px 32px rgba(0,0,0,.40)` 偏重）。

#### 4.6.3 其他玻璃元素（效果图可见）

| 元素 | 效果图观察 | 当前实现 | 处理 |
|---|---|---|---|
| 顶栏搜索框 | 半透明填充 + 1px 冷色描边 + **≈8~10px 圆角矩形**（非全圆胶囊） | `border-radius:999px` 全胶囊 + 不透明 `var(--bg-elevated)` | 半径改 8~10px + 底改半透明 |
| 日期 chip | 无填充（纯描边）+ 1px 边框 | 已是 `transparent` 底 + 999px | 保留，仅统一描边色 |
| KPI 卡 | ~~边缘可见淡红 / 淡蓝着色描边~~ → **需求方 2026-09-11 复核「没有看到」**，判定为我的误读（低置信度观察，可能是图片色度渗出） | 无方向着色 | **不做**。KPI 卡与其它卡片使用同一 `--glass-border`（不做 `--glass-border-up/down` 变体） |
| 侧栏 | 与页面**同层、透明**，仅靠 1px 右分隔线区分 | `background: var(--bg-primary)`（不透明） | 侧栏改**透明**（**不参与**玻璃层，避免 R19）；1px 右分隔线保留 |
| 侧栏底部按钮组 | **主题切换按钮（太阳图标）就在「市场已开盘 / 北京时间」左侧** —— 与当前实现的结构、图标完全一致 | `#sidebar-theme`（太阳 SVG，`index.html:56`）+ `.market-status`（`ms-dot` 绿点 + `ms-row` + `ms-time`，`:57-60`） | ✅ **结构无需改动**；只需把该按钮描边由 `var(--border)` 统一为 `var(--glass-border)`，并随侧栏一起改透明。⚠️ **勘误**：本节初稿曾写「底部无主题切换按钮」，属**对效果图的误读**，已更正（详见 §12 第 7 项） |

#### 4.6.4 promo 卡 → **本任务不做（需求方 2026-09-11 决定「先不管他」）**

效果图的「全球市场动态」是**真实照片底**（黄昏雪山 + 蓝紫天空）+ 底部暗渐变遮罩 + 白字 + 「查看分析 →」。

**本任务处理方式：保持现状，不改。** 记为**已知视觉妥协**（promo 仍是高饱和亮渐变，与全局玻璃语言不一致），留给后续任务。

三条工程注记（避免无谓开销 / 避免误判）：

1. `.card.promo` 会**继承** `.card` 新增的 `backdrop-filter`，但其自身 `background: linear-gradient(...)` 不透明 → **模糊层看不出来**（等同白跑一个合成层）。**建议给 `.card.promo` 显式加 `backdrop-filter: none`**，省掉一个无意义的 backdrop 层（R20 性能纪律）。
2. `.card.promo` 未声明 `box-shadow` → 会继承新的 `--glass-shadow`。这是**期望行为**（比现状更协调），无需额外处理。
3. 保留 `.card.promo` 现有的 `border-color: transparent` 与 `border-radius: var(--radius-card)`，**不动**。

#### 4.6.5 顺带发现的非玻璃差距 → **已决定：下一个任务**（需求方 2026-09-11）

以下与玻璃无关、对照效果图可见。**本任务不做**（会触及 `index.html` + `app.js`，超出玻璃化边界），另开任务处理；其中**第 4 条已升级为本任务 Step G-9**：

1. **每行标的缺彩色小图标**：效果图的 自选列表 / 市场概览 / 资金流向 / 行业板块 每行都有 ~16px 彩色圆角方块（按品种品牌色），当前实现没有。
2. **趋势图 y 轴在右侧**：效果图 y 轴刻度（`+6% / +3% / 0 / -3% / -6%`）在**右**侧；当前实现在左侧。
3. **品牌字风格**：效果图是 `MarketPulse`（常规大小写、非等宽、无字距），当前是 `MARKETPULSE`（等宽大写 + 字距）。
4. **底部行结构差异** → **已升级为本任务范围内工作**（需求方「按效果图为准」+ 选定方案 ② 双 tab 合并），见 §6 **Step G-9**。
5. **头像形状**：效果图是深色**圆角方块**，当前是 `MP` 文字的**蓝色圆形**（`index.html:40`）。
6. **侧栏导航标签与效果图不同**：效果图 nav 为 7 项（市场概览 / 自选列表 / 新闻资讯 / 宏观数据 / 市场日历 / **板块表现** / 设置）；当前实现也是 7 项但标签与分组语义差异较大（市场概览 / **市场趋势** / 市场情绪 / 美股板块 / 自选列表 / 最新资讯 / 告警记录）。**本任务只改 Step G-9 里那 1 处**（「美股板块」→「板块表现」），整体 nav 对齐另开任务。
7. **效果图日期仍是错的**：写 `2026-09-11 周四`，实为**周五**（与旧 plan R10 同一错误，**不要照抄**）。

---

## 5. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/style.css` | **改（主要）** | 412 → ≈465 行：新增 glass token 双套、`body` 氛围层（L1+L2 两层）、`.card`/`.kpi-card` 玻璃化、数据卡 `-strong` 变体、`.topbar` 玻璃化 + `#sidebar` 透明化 + 主题按钮描边统一、`.card.promo` 显式 `backdrop-filter: none`、`@supports` 降级块、退役 `--card-glow`/`--card-shadow` |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **改（扩展，禁止覆盖）** | 387 行 → ≈430 行：**在原脚本上追加玻璃判据断言**（§6 Step G-1 列出的 10 条）。⚠️ 该脚本已由执行者写好并入库，**只做增量扩展** |
| `web/templates/index.html` | **改（仅 Step G-9）** | ① `#fund-flow` / `#risk-appetite` 从行 4 移入 row-3 中卡作子块 + 新增「市场关系」子块；② 右卡 `#us-sectors` 改「行业板块表现」**双 tab**（A股 / 美股，纯 CSS `:checked`，A 股表从原中卡搬入）；③ `.row-news` 由 4 卡降为 2 卡。⚠️ **保留 `fund-flow-body` / `risk-appetite-body` / `news-body` / `sector-body` / `us-sectors-body` 五个 id**（`app.js` 契约） |
| `web/static/app.js` | **不改** | 玻璃化纯 CSS |
| `web/app.py` | **不改** | — |
| `tests/` | **不改** | 无 Python 逻辑变更 |

**预计不动**：`src/*`、`daily_report.py`、`snapshot_report.py`、`opening_analyzer.py`、`scripts/*`、`data/*`、`context/*`、`alerts/*`、`reports/*`、`config.json`。

---

## 6. 实现步骤（每步可独立验证）

### Step G-1 · 先扩展验收脚本（护栏先行）

在 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` 上**追加**以下断言（沿用其既有「自动选端口 + 三视口 + 退出码 0/1」框架）：

| # | 断言 | 目标值 |
|---|---|---|
| 1 | **全覆盖语义断言（不用计数，避免结构变更后失效）**：`[...document.querySelectorAll('.card:not(.card.promo), .kpi-card')].every(el => getComputedStyle(el).backdropFilter !== 'none')` | **true**（当前实现为 false：全站 0 处） |
| 1b | `.card.promo` 的 `backdropFilter` | **`none`**（Step G-7 显式禁用）。⚠️ **此条基线即 PASS**（promo 当前本就没有 backdrop-filter）—— 它是 **G-4 之后的回归护栏**：`.card` 加上 blur 后 promo 会继承，若 G-7 没做就会变红。**不属于"基线应红"的那一批** |
| 2 | `.kpi-card` 的 `backgroundColor` alpha | **< 0.2** |
| 3 | 数据卡（`#overview`/`#trend`/`#alerts`）alpha | **0.6 ~ 0.8** |
| 4 | `body` 的 `backgroundImage` 层数（`radial-gradient` / `linear-gradient` 计数） | **≥ 2**（L3 已否决，见 §4.6.1） |
| 5 | 卡片 `inset` 高光的白色 alpha | **≥ 0.08** |
| 6 | 卡片 `borderTopColor` alpha | **0.08 ~ 0.14** |
| 7 | 卡片外阴影模糊半径 | **≥ 24px** |
| 8 | **回归**：`scrollHeight` @1920×1080 | **≤1240** |
| 9 | **回归**：`scrollWidth === innerWidth`（三视口） | true |
| 10 | **回归**：`consoleErrors.length` | **0** |
| 11 | **回归**：375 下 `#menu-toggle` → `body.nav-open` 抽屉可开可关 | true |
| 12 | **回归**：切主题后 `.card` 的 `backgroundColor` 与 `borderTopColor` 均改变 | true |

- **验证**：先跑一次脚本，期望 **断言 1、2、3、4、5、6、7 全部 FAIL；1b 与 8~12 全部 PASS** —— 这是「基线红、护栏绿」的起点，可证明断言真的在测东西（不是恒真）。
  ⚠️ **`1b` 基线就是绿的**（promo 本来就没有 `backdrop-filter`），它是 G-4 之后的回归护栏，别误以为"基线不该绿"。其余基线状态：1 全覆盖=假、2/3 卡片 alpha=1、4 渐变层数=0、5 高光 alpha=0.03、6 边框 alpha=1、7 阴影模糊=8px。
  `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`

### Step G-2 · 定义 glass token（双主题双套）

- 在 `:root` 与 `[data-theme="dark"]` 各加 §4.2 的 9 个 token。
- 保留 `--card-glow`/`--card-shadow` 作为**过渡别名**指向新 token（避免遗漏引用导致整条声明失效，见 R21），确认无引用后再删除。
- **验证**：断言 `getComputedStyle(document.documentElement).getPropertyValue('--glass-blur')` 非空；**且断言 8~10 仍全部 PASS**（token 定义不应改变任何尺寸）。

### Step G-3 · 背景氛围层（**前置依赖，不可跳过**）

- 按 §4.1 给 `body` 叠 3 层 `radial-gradient` + `background-attachment: fixed`，`background-color` 保留 `var(--bg-primary)` 作最底。
- **验证**：
  - 断言 4 PASS（`body.backgroundImage` 含 **≥2 层**氛围渐变：L1 右上柔光 + L2 斜向光束）；
  - **断言 8 必须仍是 PASS** —— `scrollHeight` 不得因氛围层变化（背景不参与布局，这是硬约束）。

### Step G-4 · 卡片玻璃化

- `.card` / `.kpi-card`：
  - `background: var(--glass-bg)`
  - `border: 1px solid var(--glass-border)`
  - `box-shadow: var(--glass-shadow), var(--glass-highlight)`
  - `backdrop-filter: var(--glass-blur)` + `-webkit-backdrop-filter: var(--glass-blur)`
- **验证**：断言 1 / 2 / 5 / 6 / 7 PASS。

### Step G-5 · 数据密集卡提高不透明度

- `#overview` / `#trend` / `#alerts` 用 `--glass-bg-strong`。
- **验证**：断言 3 PASS；**目视 12px 表格小字与趋势图 meta 文案仍清晰**（对照 §2.2 截图）。

### Step G-6 · 顶栏玻璃化 + 侧栏透明化

依据效果图（§4.6.3）：

- `.topbar`：`background` 由 `var(--bg-primary)` → `rgba(11,15,20,.72)`（light `rgba(247,248,250,.72)`）+ `backdrop-filter: var(--glass-blur)` + 1px `var(--glass-border)` 底边。
- `#sidebar` → **只改透明**：`background: transparent`，保留 1px 右分隔线；**不加** `backdrop-filter`（规避 R19，且效果图的侧栏本身不是玻璃层）。
- `#sidebar-theme`（太阳按钮）描边由 `var(--border)` → `var(--glass-border)`。
- **验证**：断言 1（全覆盖）仍 PASS（`.topbar` 不在该选择器集合内，故另加一条：`.topbar` 的 `backdropFilter !== 'none'`）；`#sidebar` 的 `backgroundColor` 应为 `rgba(0, 0, 0, 0)` 且 `backdropFilter === 'none'`；**实际滚动**观察顶栏无模糊残影（R19）；断言 11 仍 PASS（层叠未被 `backdrop-filter` 打乱）。

### Step G-7 · promo 卡 → **本任务不做视觉改造**（需求方 2026-09-11「先不管他」）

- **唯一动作**：给 `.card.promo` 显式加 `backdrop-filter: none`，避免继承 `.card` 的 blur 而白跑一个合成层（其自身 `background` 渐变不透明，模糊本来看不出来 —— §4.6.4 注记 1）。
- **不改**：`.card.promo` 的 `background` 渐变、`border-color: transparent`、`.promo-visual` SVG。
- **验证**：promo 外观**与改动前逐像素一致**（可在 `verify_ui.py` 里截图对比）；其 `backdropFilter` 计算值应为 `none`。
- ⚠️ 后果：promo 仍是高饱和亮渐变，与全局玻璃语言**不一致** → 记为**已知视觉妥协**，写入 `journal.md`。

### Step G-8 · `@supports` 降级块

- 加 §4.5 的降级规则。
- **验证**：CSS 语法检查通过；在 devtools 里临时禁用 `backdrop-filter`（或改用 `@supports` 断言存在）确认降级态文字可读、卡片不塌。

### Step G-9 · 行 3 重排 + 板块卡双 tab 合并（`index.html` + `style.css`）

**依据**：需求方 2026-09-11「按效果图为准」+ 选定 **方案 ②（双 tab 合并）**。

> ⚠️ **措辞勘误（重要，照此实施，勿照旧措辞）**：我在 §12 给出的选项 ② 原文写的是「**中卡**做成『行业板块表现』双 tab」—— 那样中卡既要装「市场情绪 & 资金流向」又要装「行业板块表现」，**自相矛盾且行不通**。
> **正解**：把「A 股热点板块表」并入**右侧卡**（现有 `#us-sectors`，本就是「美股行业板块」），合并后右侧卡 =「行业板块表现」双 tab（A股 / 美股）；**中卡腾出来**做「市场情绪 & 资金流向」。以下以本勘误为准。

**目标行-3 形态（3 列，对齐效果图）**：

| 列 | 卡片 | 内容来源 |
|---|---|---|
| 左 | `#overview`「市场概览」 | **不变**（6 小卡，真实数据） |
| 中 | `#sectors`「市场情绪 & 资金流向」 | 3 个子块 ← `#risk-appetite` + `#fund-flow` 从行 4 **搬入**；+ 新增「市场关系」子块 |
| 右 | `#us-sectors`「行业板块表现」**双 tab** | tab「A股」← 原中卡的 `#sector-body` 表格**搬入**；tab「美股」← 原 `#us-sectors-body` **原地保留** |

**改动 1 · `index.html`**：

1. 中卡 `#sectors`（当前 129-141 行）：标题改「市场情绪 & 资金流向」；**移除**原 A 股板块表；依次放入 3 个子块（各带 `<h3>` 小标题）：
   - 「风险偏好」→ 容器 `#risk-appetite`（内含 `#risk-appetite-body`）
   - 「资金流向（近5日）」→ 容器 `#fund-flow`（内含 `#fund-flow-body`）
   - 「市场关系」→ 4 个 `disabled` pill 按钮（股指vs美债 / 美元vs黄金 / VIXvs股市 / 原油vs经济），**静态渲染**
2. 右卡 `#us-sectors`（143-151 行）：标题改「行业板块表现」；改为**纯 CSS 双 tab**：
   - DOM 结构（**radio 必须位于面板之前的同级兄弟位置**）：
     `<input type="radio" name="sector-tab" id="sector-tab-cn" checked>` +
     `<input type="radio" name="sector-tab" id="sector-tab-us">` →
     `<div class="tab-labels"><label for="sector-tab-cn">A股</label><label for="sector-tab-us">美股</label></div>` →
     `<div class="tab-panels"><div class="panel panel-cn">…A股表…</div><div class="panel panel-us">…美股列表…</div></div>`
   - tab「A股」面板内放原 A 股板块表，**`#sector-body` 原样保留**
   - tab「美股」面板内放 `#us-sectors-body`，**原样保留**
3. 行 4 `.row-news`（154-177 行）：删除 `#fund-flow` / `#risk-appetite` 两个 `<section>`（已搬入中卡），只留 `#alerts` + `#news`。
4. 侧栏导航（47-53 行）：**只改 1 处文案** —— `data-target="us-sectors"` 的 nav 标签「美股板块」→「**板块表现**」。
   理由：重排后该卡已含 A股 / 美股 双 tab，旧标签「美股板块」只对了一半；且「板块表现」与效果图 nav 用词一致。
   **其余 6 个 nav 项全部不动**，其中 nav「市场情绪」→ `#sectors` 在重排后**正好就是新卡名**，语义仍然相符，**无需改**（这是巧合，不是设计）。

**改动 2 · `style.css`**：

- `.row-news`：`repeat(4, minmax(0, 1fr))` → **`≥1400px`：`1fr 2.4fr`**（告警窄 + 资讯宽）；**`<1400px`：`1fr`**（单列堆叠，避免 1280 下左卡仅 ≈292px 装不下告警文本）。
- 中卡子块布局：纵向堆叠 + 子块间距 + `<h3>` 小标题样式。
- **双 tab 样式（CSS-only 三个要点）**：
  1. radio 本体**不能 `display:none`**（会让 label 点击与键盘焦点一起失效）→ 用 `position:absolute; opacity:0; pointer-events:none`；
  2. `.tab-panels > .panel { display: none }`，用**兄弟组合选择器**激活：
     `#sector-tab-cn:checked ~ .tab-panels > .panel-cn { display: block }`、
     `#sector-tab-us:checked ~ .tab-panels > .panel-us { display: block }`；
  3. ⚠️ **两个 `input` 必须是 `.tab-panels` 的前置同级兄弟**，`~` 才生效。若把 input 放进 `.tab-panels` 内部或放到它之后，**tab 完全不工作且不报错** —— 最容易被误判为"CSS 没生效"或"缓存问题"。
  4. label 激活态复用现有 `.active` 观感（`background: var(--blue); color:#fff`），与 `.range-bar button.active` 统一；键盘切换由 radio 语义自带（方向键），`style.css` 既有全局 `:focus-visible` 描边可直接生效。

**`app.js` 零改动的依据（已核实）**：

- `renderPlaceholders()`（`app.js:240-250`）：契约是 `getElementById(id)` 改其 `h2` 文案 + `getElementById(id + '-body')` 填「数据未接入」。搬迁后 `#fund-flow` / `#risk-appetite` 不再是卡片、内部无 `h2` → `cardEl.querySelector('h2')` 返回 `null`，被 **`if (h)` 守卫跳过，不报错**；只要 `fund-flow-body` / `risk-appetite-body` / `news-body` **三个 id 仍在**，文案照常渲染。
- `renderSector()`（`app.js:170-188`）写 `#sector-body`（tbody）→ **留在 A股 tab 面板内，id 不变** ✅
- `renderUsSectors()`（`app.js:191-236`）写 `#us-sectors-body`（div）→ **留在美股 tab 面板内，id 不变** ✅；且它只在 `box` 内部替换 `innerHTML`，**不会破坏 tab 结构** ✅

→ **`#sectors` / `#us-sectors` / `#sector-body` / `#us-sectors-body` 四个 id 一律不改**（同时避免影响 `app.js` 与侧栏锚点），`app.js` 一行都不用改。
（可选清理：`PLACEHOLDERS` 的 `title` 字段对移入卡内的两个条目将不再生效；追求整洁可删该字段，但**会动 `app.js`**，本次不做，仅在 `journal.md` 记一笔。）

**「市场关系」子块不加入 `data-placeholder`**：4 个 pill 本身就是占位形态，HTML 里静态渲染即可 → 全站 `data-placeholder` 计数**保持 3**，与 `app.js` 的 `PLACEHOLDERS`（3 条）一致，**断言无需改动**。

**`.row-3` 的 `align-items`**：保持默认 `stretch`（三卡**等高**，对齐效果图）；高度取三列最大值 → 必须回归 `scrollHeight`。

**验证**：

- `.row-news` 的 `gridTemplateColumns` 为 **2 段**（≥1400px）；
- `#sectors` 内存在 **3 个子块**；`#risk-appetite-body` / `#fund-flow-body` 均存在且显示「数据未接入」；
- 全站 `data-placeholder` 计数仍为 **3**；
- 3 处占位文案仍显示「数据未接入」（`#news` / `#fund-flow` / `#risk-appetite`）；
- `#sector-body` 与 `#us-sectors-body` 均存在，且**分属不同 tab 面板**；
- **tab 功能断言**（在 `verify_ui.py` 里用 `tab.evaluate`）：默认 `.panel-cn` 可见；执行 `document.getElementById('sector-tab-us').checked = true` 后 `.panel-us` 可见、`.panel-cn` 隐藏；
- `#sector-body` 内有 **5 行**（A 股 Top5 真实数据）、`#us-sectors-body` 内 **8 行**（美股 Top8）→ 证明两个渲染函数都仍在正常工作；
- 侧栏 nav 中 `data-target="us-sectors"` 的标签文本为「**板块表现**」，且点击后仍能滚动到 `#us-sectors`（锚点未因重排失效）；
- Console **0 error**（重点：确认 `renderPlaceholders` 未因 `h2` 缺失报错）；
- 回归：`scrollHeight` @1920×1080 仍 ≤1240（三卡等高取最大值，若顶破需回 §8.1 复核）。

**默认激活的 tab：A 股**。理由：A 股板块是本项目 row-3 的原生真实数据、信息量（4 列：板块/涨跌幅/成交额/领涨股）大于美股的条形列表。
⚠️ 效果图右侧卡标题是「行业板块表现（**美股**）」；若更看重与效果图一致，把 `checked` 从 `#sector-tab-cn` 移到 `#sector-tab-us` 即可（**一处改动，随时可切，不阻塞实施**）。

### Step G-10 · 全量回归 + 收尾

- 跑完整 `verify_ui.py` → **退出码 0**（断言 1~12 全绿）。
- 跑 `venv/Scripts/python -m pytest tests/ -v` → 全绿（无 Python 改动，应无变化）。
- 双主题 × 三视口目视复核（§8）。
- 追加 `docs/pitfalls.md`：G1 因果链（「不降 alpha 加 blur = 零变化」）、R21（CSS 变量未定义导致整条声明失效）、本次踩到的 auto-cron 抢提交陷阱（见 §10 R24）。
- 写 `tasks/2026-09-11-glassmorphism-fix/journal.md`。

---

## 7. 复现路径、测量点与 box-sizing 说明

### 7.1 复现路径（精确步骤）

1. `cd d:/AGENT/MarketPulse`
2. 启动看板：`venv\Scripts\python -m uvicorn web.app:app --port 8016`
   ⚠️ **每次验证换新端口**（8016 → 8017 → 8018 递进）。同端口复测会命中 304/陈旧 CSS 副本 → 「改动没生效」类假阴性（`docs/pitfalls.md`「跨端口 CSS 缓存假阴性」）。
   💡 也可以直接用 `verify_ui.py`，它**自动挑空闲端口**，天然规避此问题。
3. 浏览器打开 `http://127.0.0.1:8016/`，硬刷新 `Ctrl+Shift+R`。
4. **现状（修复前）可观察到的现象**：
   1. 整页纯黑，**无任何光晕/渐变**；
   2. 卡片与背景只差一点点亮度，**无「悬空感」**，投影看不见；
   3. 卡片顶边**没有亮线**；
   4. promo 卡是**突兀的亮蓝青块**；
   5. 滚动时卡片与背景**刚性绑定**，无模糊位移。
5. DevTools Console 应无 error。

### 7.2 关键测量点（执行者须逐项实测记录）

| 测量点 | 取法 | 修复前实测 | 目标 |
|---|---|---|---|
| **卡片 `backdrop-filter` 全覆盖** | `[...querySelectorAll('.card:not(.card.promo), .kpi-card')].every(el => getComputedStyle(el).backdropFilter !== 'none')` | **false**（全站 0 处） | **true** |
| `.topbar` / `#sidebar` | `.topbar` 的 `backdropFilter`；`#sidebar` 的 `backgroundColor` + `backdropFilter` | `none`；`rgb(11,15,20)` + `none` | `.topbar` ≠ `none`；`#sidebar` 为 `rgba(0, 0, 0, 0)` 且 `none` |
| `.kpi-card` 背景 alpha | 解析 `getComputedStyle(el).backgroundColor` 第 4 位 | **1** | **< 0.2** |
| 数据卡背景 alpha | 同上（取 `#overview`/`#trend`/`#alerts`） | **1** | **0.6 ~ 0.8** |
| `body` 氛围层数 | `getComputedStyle(document.body).backgroundImage` 中渐变层计数 | **0** | **≥ 2** |
| 卡片盒尺寸（不得变） | `offsetWidth × offsetHeight` | 记录 | 与修复前一致 |
| 卡片 `clientHeight` | `el.clientHeight` | `offsetHeight − 2`（1px 上下边框） | 同上 |
| KPI 卡 `clientHeight` | 同上 | 记录 | 与修复前一致（border-box 下 border 不变则不变） |
| 父容器尺寸基准 | `.row-kpi` / `.row-main` 的 `clientWidth × clientHeight` | 记录 | 与修复前一致 |
| 窗口尺寸 | `innerWidth × innerHeight` | 1920×1080 | — |
| 顶边内高光 alpha | `boxShadow` 中 `inset ... 0px 1px` 的白色 alpha | **0.03** | **≥ 0.08** |
| 边框颜色 alpha | `getComputedStyle(el).borderTopColor` | `rgb(30,39,51)` → **1** | **0.08 ~ 0.14** |
| 外阴影模糊半径 | `boxShadow` 第一段的第 3 个长度 | **2px** | **≥ 24px** |
| **布局回归** | `document.scrollingElement.scrollHeight` @1920×1080 | **1235** | **≤1240**（不得变大） |
| **溢出回归** | `scrollingElement.scrollWidth === innerWidth` | true | true |
| **层级关系** | `.topbar`/`#sidebar`/`.nav-backdrop` 的 `z-index` | 100 / 60 / 55 | 关系不变 |
| **功能回归** | `consoleErrors.length`；375 下抽屉开关 | 0；正常 | 0；正常 |

### 7.3 box-sizing 说明

`web/static/style.css:51` 为 `* { margin:0; padding:0; box-sizing:border-box }` —— **全局 border-box，无例外**。玻璃化的具体影响：

1. **改边框颜色/透明度不改尺寸**：`border: 1px solid var(--border)` → `1px solid var(--glass-border)`，宽度不变，卡片**外尺寸与内容区都不变**（border-box 下 border 已计入 `width`）。
2. **`backdrop-filter` 不影响盒模型**：它不参与 `width/height/padding/border` 计算，**只创建层叠上下文**（R18）。因此**不会**改变 §2.2 的任何尺寸验收值 —— `scrollHeight` 必须仍为 **1235**。
3. **`padding` 若调整需复核高度**：border-box 下 `height`/`max-height`/`min-height` **均含 padding**。`.kpi-card` 当前 `padding:14px 16px` 靠内容撑高；若为玻璃内边距把 padding 加到 `18px 20px`，卡片实际高度会增加 → 需复核 §2.2 的「KPI ≥96px」目标（只增不减，风险低，但会改变 `scrollHeight`，可能突破 1240 上限，**建议不动 padding**）。
4. **氛围层必须不参与布局**：用 `body` 的 `background-image`（背景**从不**参与布局）而非新增 in-flow 元素；否则 `scrollHeight` 会从 1235 涨上去，**直接破坏 §2.2 验收**。若采用绝对/定位层，须 `position:fixed` + `pointer-events:none`，且**不能**用 `z-index:-1`（会被 `body` 不透明底色盖住而不可见）。
5. **`::before` 高光层（若采用）**：`position:absolute; inset:0` 在绝对定位下相对包含块的 **padding box**（不含 1px border）；需父元素 `position:relative`（`.card` 实测已是 `position:relative` ✅），且必须 `pointer-events:none` 以免挡住表格悬停与点击。
6. **`--card-glow` 退役注意**：当前它是 `box-shadow` 的第二段（`box-shadow: var(--card-shadow), var(--card-glow)`）。替换时须确认无遗漏引用 —— **CSS 变量未定义会让整条声明 invalid**，即整条 `box-shadow` 被丢弃（不是只丢那一段），表现为「卡片突然没阴影」（见 R21）。

---

## 8. 多尺寸验收

### 8.1 1920×1080（常规窗口，主验收）

- 背景可见 **3 处光斑**（左上蓝 / 右上紫 / 底部青），且卡片覆盖区域仍能看出背景明暗过渡。
- 卡片呈**半透明**，边缘有 **1px 半透明亮线**，顶边有**可见拾光**，卡片有**柔和外发光**（模糊半径 ≥24px）。
- promo 卡**保持现状**（本任务不做视觉改造，§4.6.4）—— 外观应与改动前一致，且 `backdropFilter` 为 `none`。
- **`scrollHeight` 仍 ≤1240**；`.row-kpi` 仍 **5 列同排**；`.row-main` 仍 1.9:1 同排。
- `.row-3` 仍 **3 列同排**：中卡「市场情绪 & 资金流向」含 **3 个子块**（风险偏好 / 资金流向（近5日）/ 市场关系）；右卡「行业板块表现」为**双 tab**（A股 默认可见 / 美股）。
- `.row-news` 为 **2 列 `1fr 2.4fr`**（告警记录窄 + 最新资讯宽，按效果图比例）。
- `scrollWidth === 1920`；Console error **0**。

### 8.2 1280×720（小窗口）

- `scrollWidth === 1280` —— **无横向溢出**（本档最易踩 `min-content` 溢出，必须验证）。
- 光斑用 **px 尺寸**而非百分比 → 小视口下仍覆盖卡片区域，**不得出现「卡片全落在纯色区、看不出玻璃」**。
- `.row-kpi` 仍 3+2 两行；`.row-main` 仍堆叠；`.row-3` 仍 2+1。
- `.row-news` 退化为**单列堆叠**（`<1400px` 断点），避免 1280 下左卡仅 ≈292px 装不下告警文本。
- `backdrop-filter` **全覆盖断言为 true**（§7.2，不用计数）。
- `scrollHeight` 允许比 1080p 长，但 ≤2400。
- 卡片 `offsetWidth × offsetHeight` 与修复前一致（玻璃化不得改变尺寸）。

### 8.3 375×812（附加，移动端）

- `scrollWidth === 375`；卡片单列，玻璃仍生效。
- `backdrop-filter` 层数 = 卡数（**性能敏感档**，须目视滚动无卡顿，见 R20）。
- 侧栏（z=60）与 `.nav-backdrop`（z=55）层叠**未被 `backdrop-filter` 打乱**：点击背景仍能关闭抽屉。
- 图表高度 280px；表格 `.table-scroll` 横滚、页面本身不横滚。

### 8.4 双主题

- Dark 与 Light **各自独立调参**（token 已拆双套）。
- 切换主题后：卡片玻璃强度、光斑颜色、边框 alpha 均需目视复查。
- **不得出现**「light 下文字糊在浅色光斑上」或「dark 下卡片与背景无法区分」。

---

## 9. 验证命令

引用 `docs/commands.md` 的既有命令：

```bash
# 【主验收】UI 视觉 + 布局断言（自动挑端口起服务、退出码 0/1）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 手动查看（每次换新端口）
venv/Scripts/python -m uvicorn web.app:app --port 8016

# 回归：无 Python 逻辑变更，应保持全绿
venv/Scripts/python -m pytest tests/ -v

# 后端契约（本任务不改 web/app.py，可选）
venv/Scripts/python -m pytest tests/test_web.py -v
```

**验收判据**：`verify_ui.py` 退出码 **0**（断言 1~12 全绿），且 `pytest tests/ -v` 全绿。

---

## 10. 风险与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R15** | **只加 `backdrop-filter` 得到零变化** | **高** | 机制见 §3.3：模糊纯色 ≡ 同色；卡片 alpha=1 时模糊层不渲染。**必须按 G-3 → G-4 顺序**。这是执行者最容易「改了看不到效果」进而怀疑代码的点 |
| **R16** | 氛围层把 `scrollHeight` 撑大，毁掉 §2.2 验收 | **高** | 用 `body` 的 `background-image`（不参与布局）；**不要**新增 in-flow 元素。G-3 验证必须**同时**断言 `scrollHeight` 不变 |
| **R17** | 半透明导致数据可读性下降 | **中** | 数字密集区（市场概览 6 小卡、趋势图 meta、告警正文）用 `--glass-bg-strong`（dark α≈0.72）；验收时目视 12px 小字是否清晰 |
| **R18** | `backdrop-filter` **创建层叠上下文** | **中** | 任何 `backdrop-filter !== none` 的元素都会成为层叠上下文，改变内部 `z-index` 参照系。必须回归 `.topbar:100` / `#sidebar:60` / `.nav-backdrop:55` 关系不变，375 下抽屉开关正常 |
| **R19** | `position: sticky` + `backdrop-filter` 滚动残影 | **中** | Chromium 在 sticky 元素上偶发「模糊层不跟随重绘」。G-6 需**实际滚动**观察顶栏/侧栏；有残影则降级为方案 B（不用 blur，只提 alpha + 亮边） |
| **R20** | 多层 `backdrop-filter` 的每帧重算开销 | **中** | 预计 **16~18 个** backdrop 层。纪律：只给 `.card`/`.kpi-card`/`.topbar`/`#sidebar`，**不要**给内部子元素重复加；375 档目视滚动帧率；必要时先只保留 10 张大卡片 |
| **R21** | **CSS 变量未定义导致整条声明失效** | **中** | `box-shadow: var(--glass-shadow), var(--glass-highlight)` 中任一变量未定义 → **整条 `box-shadow` 被丢弃**（不是只丢那一段）。退役 `--card-glow`/`--card-shadow` 时**必须先保留过渡别名**，确认无引用后再删。表现为「卡片突然没阴影/没底色」，极易误判为选择器写错 |
| **R22** | promo 卡无法靠调 token 变玻璃 | **中** | G6 是**结构问题**（`.card.promo` 自身 `background:linear-gradient(...)` + `border-color:transparent` 会覆盖 `.card` 的玻璃规则），**必须单独改**，不能指望继承 |
| **R23** | 与效果图强度不匹配 | **中** | 效果图原图在本次会话已不可读（见 §12）。§4.2 的 alpha/blur 是**按 glassmorphism 通用参数给的工程值**，未经效果图逐像素比对。执行者按建议值实现后，再与效果图并排微调 |
| **R24** | **外部 auto-commit cron 会抢提交，破坏"改完再提交"的假设** | **中（本次已实际踩到 3 次）** | 仓库有 Hermes「每日数据更新」cron，会频繁执行 `git add -A` + commit + push。本次已造成：① 临时文件 `_dbg/*` 被提交入库（≈887 KB）；② 我刚写入的脚本被提交 → 导致 `git checkout -- <file>` 还原时拿到的是**我自己**的版本而非历史版本（"还原失败"假象）。**对策**：临时文件落 `$env:TEMP`；改动完成后**立刻**用 `git status` 确认；还原历史文件必须用 `git checkout <具体sha> -- <path>`（不要依赖 `HEAD`）；看到"文件内容不是我以为的"先查 `git log --oneline -- <path>` |
| **R25** | 误覆盖他人已入库文件 | **中（本次已实际发生）** | 本次架构分析中，我在未先 `read_file` 的情况下 `write_to_file` 覆盖了执行者已写好的 387 行 `verify_ui.py`（我的版本仅 146 行，丢失了自动选端口/三视口/退出码等能力），后从历史提交 `5c4ea6b` 还原。**对策**：写任何已存在路径前**必须先 `read_file`**；新增验证工具优先**扩展现有脚本**而非新建 |

---

## 11. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改（主要） | `web/static/style.css` | 412 → ≈465 行（新增 glass token 双套 + 氛围层 + 卡片玻璃化 + `.topbar`/侧栏半透明与透明化 + 侧栏主题按钮描边统一 + promo 显式 `backdrop-filter:none` + `@supports` 降级；删除 `--card-glow`/`--card-shadow` 相关引用） |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 387 → ≈430 行（+12 条玻璃/回归断言） |
| 新增 | `tasks/2026-09-11-glassmorphism-fix/plan.md` | 本文件 |
| 修改（仅 Step G-9） | `web/templates/index.html` | 185 → ≈205 行（① 2 个占位卡移入 row-3 中卡作子块 + 新增「市场关系」子块；② 右卡改双 tab 外壳：2 个 radio + 2 个 label + 2 个 panel 容器；③ `.row-news` 降为 2 卡）。**净行数变化不大**，主要是块位置搬移 + tab 外壳 |
| 新增 | `tasks/2026-09-11-glassmorphism-fix/journal.md` | 执行完成后写 |
| 新增 | `docs/pitfalls.md` 追加段 | 3 条（G1 因果链 / R21 变量失效 / R24 cron 抢提交） |

**净代码变更估算**：约 **+90 / −25 行**（不含本计划文档与 journal）。

**明确不改**：`src/*`、`web/app.py`、`web/static/app.js`、`tests/*`、`config.json`、`data/*`、`context/*`、`alerts/*`、`reports/*`、生成物。

---

## 12. 待需求方确认（阻塞项）

1. ~~**【阻塞精度】效果图需重新发送**~~ → **已解决**：2026-09-11 需求方已重发效果图，校准结果见 **§4.6**。**实施以 §4.6.2 参数为准**，§4.2 仅作推导记录。
2. ~~**强度档位**~~ → **已解决**：效果图为**低强度玻璃**（细描边 + 低 alpha + 柔光束），非霓虹风。`saturate` 由 180% 下调至 **150%**，`--glass-shadow` 减弱（§4.6.2）。
3. ~~**【需确认】promo 卡形态**~~ → **已决定：本任务不做**（需求方 2026-09-11「先不管他」）。效果图该卡是真实照片底，CSS 无法还原；promo **保持现状**，仅在其上显式 `backdrop-filter: none`（§4.6.4 注记 1）。记为**已知视觉妥协**。
4. ~~**【需确认】KPI 卡方向着色描边**~~ → **已解决：不做**。需求方 2026-09-11 复核「没有看到」→ 判定为**我的误读**（低置信度观察，可能是图片色度渗出）。KPI 卡与其它卡片共用同一 `--glass-border`，**不引入** `--glass-border-up/down`。
5. ~~**【需确认】底部行结构**~~ → **已解决**。
   - **行 4**：按效果图，`#fund-flow` / `#risk-appetite` 从行 4 **搬入行 3 中卡**，`.row-news` 降为 2 列（告警记录 + 最新资讯）。
   - **A 股板块表**：需求方 2026-09-11 选定 **方案 ②（双 tab 合并）** —— 把 A 股热点板块表并入**右侧卡**，右侧卡改为「行业板块表现」双 tab（A股 / 美股），纯 CSS `:checked` 实现，`app.js` 零改动。
   - ⚠️ **选项 ② 的原始措辞有误**（写成"**中卡**做成双 tab"，照做会自相矛盾 —— 中卡已要装市场情绪/资金流向）：正解是"**右卡**双 tab"。已按正解写入 **§6 Step G-9**，并在该步保留勘误说明。
   - **结论：Step G-9 不再有阻塞项，可以开工。**
6. ~~**【需确认】背景斜向纹理（L3）**~~ → **已解决：不加**（需求方 2026-09-11 判定为「噪声」）。氛围层降为 **L1 + L2 两层**；§6 Step G-1 的**断言 4 目标值同步由「≥3 层」改为「≥2 层」**（已更新），避免断言与方案不一致而恒 FAIL。
7. ~~**【需确认】侧栏主题切换按钮**~~ → **已解决：保留，无需改动**。
   **勘误**：我此前误读效果图，认为侧栏底部无主题按钮 —— 实际上「市场已开盘」**左侧那个圆形太阳图标就是主题切换按钮**（需求方 2026-09-11 指出）。经核实 `web/templates/index.html:56` 的 `#sidebar-theme` 用的是**同款太阳 SVG**、`:57-60` 的 `.market-status` 结构也与效果图一致 → **当前实现已符合效果图**，玻璃化时只需把该按钮描边由 `var(--border)` 统一为 `var(--glass-border)`。
8. ~~**顶栏 / 侧栏是否也玻璃化**~~ → **已定稿**（2026-09-11）：**只对 `.topbar` 做玻璃**；`#sidebar` **只改透明**（不加 `backdrop-filter`），依据是效果图侧栏与页面同层。见 §4.3 / §6 Step G-6。
9. **验收脚本位置**：维持原决定 —— **扩展现有** `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（单一事实来源，避免两份脚本漂移）。若希望长期沉淀为仓库级工具，可改放 `scripts/verify_ui.py`（需同步改其 `ROOT = parents[2]` → `parents[1]`）——**本次不动，避免无关 churn**（R25）。
10. ~~**【可选】§4.6.5 的非玻璃差距**~~ → **已决定：下一个任务**（需求方 2026-09-11）。剩余 **4 条**（彩色小图标 / y 轴在右 / 品牌字 / 头像形状）**不并入**本次（会触及 `index.html` + `app.js`，超出玻璃化边界）。原第 4 条（底部行结构）已升级为本任务 **Step G-9**。

---

## 13. 确认

- [ ] 人已审阅本计划
- [ ] 已知悉**责任归属**：玻璃缺失源于旧 plan §7 Step 2 的 token 设计，执行者无过错
- [ ] 已确认修复顺序 **G-3（氛围）→ G-4（半透明）→ blur**，不可颠倒（R15）
- [ ] 已确认布局回归护栏（`scrollHeight ≤ 1240`、无横向溢出、0 console error）**不得回退**
- [ ] 已确认 glass token **双主题双套**，无遗漏（R21）
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**（R25）
- [ ] 已确认本次**不改** `app.js` / `web/app.py` / `tests/`
- [ ] 已重发效果图 / 或同意先按建议参数实现并标注「待比对微调」
- [ ] 已确认 **promo 卡本任务不做视觉改造**（仅显式 `backdrop-filter:none`），记为已知视觉妥协
- [ ] 已确认 **侧栏主题切换按钮保留**（`#sidebar-theme`，勘误：效果图底部那个太阳图标就是它）
- [ ] 已确认侧栏改**透明**、仅 `.topbar` 做玻璃层（规避 R19）
- [ ] 已确认 **L3 斜向纹理不加**（氛围层 = **L1 + L2 两层**，断言 4 目标已同步改为 ≥2）
- [ ] 已确认 **KPI 卡不做方向着色描边**（共用 `--glass-border`）
- [ ] 已确认 **Step G-9 底部行结构按效果图重排**（`index.html` 允许改；经核实 `app.js` **零改动**）
- [x] **A 股热点板块表处理已定：方案 ② 双 tab 合并** —— 并入**右侧卡**，右卡改「行业板块表现」双 tab（A股 / 美股）；中卡做「市场情绪 & 资金流向」。Step G-9 已无阻塞
- [ ] 已确认双 tab 为**纯 CSS `:checked`**（radio 必须位于 `.tab-panels` 之前的前置兄弟位置），`app.js` 零改动（`#sector-body` / `#us-sectors-body` 保留在各自面板内）
- [ ] 已确认双 tab **默认激活 A 股**（如需贴合效果图可切到美股，一处改动）
- [ ] 已确认 Step G-9 顺带改 **1 处 nav 文案**：「美股板块」→「板块表现」（该卡重排后已含 A股/美股 双 tab）；其余 6 个 nav 项不动
- [ ] 已确认 §4.6.5 剩余 **4 条**非玻璃差距 → **下一个任务**，不并入本次
