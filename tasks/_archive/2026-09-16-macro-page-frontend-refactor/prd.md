# PRD（收窄定稿）：`/macro` 前端新增项 —— 状态体验与因子可读性

> **来源**：2026-09-16 用户 Task Handoff（web 对话稿）+ 架构师评审 `prd-review.md`
> **范围裁定（2026-09-16 22:4x，需求方）**：**去掉所有"上一轮改过、这轮要往回改"的项**，本次**只做新增**。
> **定稿人**：架构师。**未修改任何项目文件**。

---

## 1. Goal

在**不动** `/macro` 既有五级分层、`M-*` 布局护栏与双主题契约的前提下，补齐三件"从未做过"的事：

1. **宏观页三态体验**：加载中（骨架屏）／取数失败（可重试）／无数据（统一空态），替代当前"首屏空白 + 一行文字提示"。
2. **因子可读性**：给四维度因子的「影响资产」加**方向 Badge + 资产图标 chip**（当前是纯文本）。
3. **Macro Score 语义色**：`#regime-score` 从**中性色**改为按**服务端 `level` 同源**的正/负/中性色。

> 一句话：**这轮是"补空态与可读性"，不是"改视觉风格"。** 视觉风格（暗黑终端化、全局提对比、Hero 卡片化）**不在本轮**。

---

## 2. 明确不做（Out of Scope，逐条带理由，执行者不得顺手做）

| # | 不做 | 理由（依据） |
|---|---|---|
| 1 | Hero `#mac-regime` **卡片化** | 会撞 `verify_ui.py:1988` **M-7**（`regimeIsCard === false` 且 border=0），且推翻 2026-09-14「降卡片感」决策 |
| 2 | **全局**"提升视觉对比度" | 四/五级 `.mac-card-quiet` 是**刻意的"背景资料"降对比**（`style.css:709`；`macro.html:107-108` 标注 PRD 要点 8） |
| 3 | 变量/因子**卡片化、卡片套卡片** | 三级块"同一卡片内两栏"是上一轮为消除 D5/D6 空转留白**刚去掉**的结构（`macro.html:77-79`） |
| 4 | 引入 **JetBrains Mono / webfont** | `--mono` 系统栈已存在（`style.css:16`）且关键数值**本来就是 mono** → 属新增外部依赖，违反"零新依赖" |
| 5 | Disabled / `SOON` 徽章 | **已实现**（`.is-disabled` / `.is-placeholder` / `.link-btn{cursor:not-allowed}`）；`frontend-structure.md §8` 有完整清单 |
| 6 | 改默认主题为 dark | 现状 `macro.html:2` 默认 light 且 **light 是主推**；改它牵动 3 页 + 4 处主题初始化。**双主题保持不变** |
| 7 | 后端 `/api/macro`、`/api/econ` 任何改动 | 沿用 handoff 原约束 |

---

## 3. 勘误（handoff 原文的 3 处事实错误，执行前必读）

| # | handoff 原文 | 实测事实 | 影响 |
|---|---|---|---|
| **E1** | 「Macro Score 结合**分值区间（-2.0 ~ +2.0）** 强化正负语义色彩」 | `#regime-score` 显示的是 **`score100 = (normalized+1)/2*100`**，范围 **0 ~ 100，中性 = 50，没有负数**（`web/app.py:807`）。`-2 ~ +2` 是**四个因子各自的 `impact`** | 若按"正分/负分"上色，`score100=50` 会被当"正分"→ **全表偏绿**。必须改为**相对 50 的偏离**，且**与服务端 `level` 同源** |
| **E2** | 「`text-emerald-400` / `text-rose-400`」 | 本项目**无框架、无构建**（`frontend-structure.md §1`），不存在 Tailwind | 删掉。用既有 `--green` / `--red`（`.mac .up/.down/.flat` 已在 `style.css:725-727` 定义） |
| **E3** | 「数据缺失时使用脉冲高亮/Shimmer 占位，减少破折号 `—`」 | 把"**缺失**"做成永久 shimmer = 用动画掩盖"取不到数"（同 `pitfalls`「降级为空会掩盖故障」） | **Shimmer 只允许用于"加载中"**；"无数据/失败"必须落在既有 `.mac-empty` 上（该 class 是**可测契约**，见 §5-C1） |

---

## 4. 本轮要做的 4 项（含可测验收标准）

### N1｜宏观页三态：加载中 / 取数失败（可重试） / 无数据

**现状**：`#macro-chart-fail` 只有一行「图表加载失败」（`macro.html:72`）；宏观页首屏空白或字面 `—`（`frontend-structure.md §9-5` 原文承认）。

**四态定义（必须严格区分）**：

| 态 | 触发 | 呈现 | 可测锚点 |
|---|---|---|---|
| `loading` | fetch 未返回（含 `loadAll()` 未完成） | 骨架屏（**复用 `.skeleton`**，静态写在 HTML 里，与首页 overview/watchlist 做法一致） | `#mac-… .skeleton` 存在；**超时后必须切走** |
| `ok` | 取数成功且有数据 | 正常渲染 | 既有 `M-*` 断言 |
| `empty` | 取数成功但无数据 | **`.mac-empty`**（保留类名与「数据暂缺」字样） | 既有 `verify_ui.py:1472` 契约 |
| `failed` | 请求异常 / **15s 超时** / CDN 失败 | **`.mac-empty` + `is-failed` 修饰类 + 重试按钮** | 新增 N-* 断言（见 §5） |

**硬约束**：
- **`.mac-empty` 类名与「数据暂缺」文案不得改**（`verify_ui.py:1604` 断言 `#macro-econ .mac-empty` 存在 + 「数据暂缺」出现在 `#regime-quadrant`）。
- **超时必须能从 `loading` 切到 `failed`** —— 否则上游 403（当前 G8 常态）会永远显示骨架屏，比现在更糟。
- 重试按钮绑定在 IIFE 内（`loadAll` 是 IIFE 私有函数）；重试失败走 `console.warn`，**不得产生 `console.error`**（M-9b：`/macro` console error = 0；`AbortError` 分级见 `pitfalls`）。

**验收**：`page.route` 把 `/api/macro` 与 `/api/econ` mock 成 ① 延迟 3s ② 500/异常 ③ 空结构，分别断言 骨架屏出现 → 失败态出现且含重试 → 点重试后再次发起请求。

### N2｜Shimmer 仅用于加载态

**现状**：字面 `—` 出现在 `renderRegime:475`（`#regime-score`）、`renderAll:682/684`（`#macro-asof` 等）、`varState:496`（状态词）。

**规则**：
- `loading` 期间：这些位置显示 shimmer 占位；
- 取数结束：**一律替换为真实值或既有 `—`/`.mac-empty`**，**不得残留 shimmer**；
- 实现只在 `macro.js` 内（**不改共享 CSS 的 `.mac-*` 公共声明**）→ `/macro/cn` 不受影响。

**验收**：加载完成后，`/macro` 全页 `document.querySelectorAll('.skeleton').length === 0`（或仅剩首页式静态骨架该有的数量 0）；且 `—` 与 `.mac-empty` 的既有语义未被替换掉。

### N3｜因子「影响资产」→ 方向 Badge + 资产图标 chip

**现状**：`macro.js:540-543` 渲染 `.fr-assets`，纯文本「影响：股票 / 信用 受益」（映射见 `FACTOR_ASSETS` `macro.js:55-60`）。

**实现（零新增素材）**：复用**已存在**的 4 个 SVG 与全站图标类：
```
<i class="ico" style="background:var(--…)"><img class="ico-flag-img"
   src="/static/icons/<dollar|bond|gold|oil>.svg" alt="" onerror="this.remove()"></i>
```
（`app.js:97-101` 的 `iconAssetHtml` 是同一写法；`.ico` / `.ico-flag-img` 已在 `style.css:397-403` 全站生效，**macro 页可直接复用**。）

**映射（美元→dollar / 利率·美债→bond / 黄金→gold / 原油·能源→oil）**；「股票 / 信用」**无对应素材 → 只用文字 chip，不新增 SVG**（保持零二进制新增）。

**硬约束**：
- **不抽共享文件**（避免 `_ASSET_FILES` 登记 + 3 个模板改 `<script>` 顺序的连带成本）→ 在 `macro.js` 内写局部 `assetChipHtml()`；
- ⚠️ **`.mac-factor-row` 网格被 `/macro/cn` 共用**（`.cn-*` 复用 `.mac-*`）→ 若需调网格，选择器**必须写成 `#mac-factors …`** 限定，不改公共声明；
- ⚠️ **M-6 护栏**：`#mac-factors` 额外留白 ≤ 20px（`verify_ui.py:1991`）。N3 会加内容 → 必须**实测 slack 前后值**并记录（M-6 是上限，加内容一般安全，但要有数）。

**验收**：`#macro-factors` 每行的资产 chip 数 ≥ 1；有素材的资产渲染出 `<img>` 且 `naturalWidth > 0`（离线时 `onerror` 自移除，不得留破图）；`#mac-factors` 的 `slack ≤ 20`。

### N4｜`#regime-score` 语义色（与 `level` 同源）

**现状**：`style.css:743` `.score-num { color: var(--text-primary) }` —— **中性**。

**实现（关键：不自己造阈值）**：颜色**必须由服务端 `r.level` 推导**，而不是"按 50 加减某个 δ" ——
否则会出现"文案写 Risk-On、数字染红"这类**标注与行为不同源**的缺陷（`pitfalls` 专条）。映射：

| `r.level` | class | 颜色 |
|---|---|---|
| `risk_on` | `up` | `var(--green)` |
| `risk_off` | `down` | `var(--red)` |
| `neutral` / 缺失 | `flat` | `var(--text-muted)` |

`.mac .up/.down/.flat` **已存在**（`style.css:725-727`）→ **CSS 零改动**（`#regime-score` 在 `.mac` 内，规则直接生效）。

**验收**：断言 `#regime-score` 的 `classList` 与 `#regime-level` 的 `level` 语义**同向**（用 mock 的三组 `regime.level` 分别验色）；`neutral` 时不得染绿或染红。

---

## 5. 约束（继承，不得违反）

**C1｜既有验收护栏（动布局前必读）**
`M-6` 因子列留白 ≤20px（`:1991`）· `M-7` `#mac-regime` 非卡片（`:1988`）· `M-8` 375 档主图 ≥360px（`:2020`）· `M-9/M-9b` 三档零横向溢出 + `/macro` console error=0（`:1959/2015/2022`）· `M-10/M-10b` 1280 两列 / 375 单列（`:2017/2019`）。
⚠️ **断言只能补强，不得删除**（删断言让红变绿 = 把真红改假绿，项目明令）。

**C2｜共享面**
`.mac-*` 同时服务 `/macro` 与 `/macro/cn` → 新规则一律 **`#mac-*` / `#cn-*` id 限定**，不改 `.mac-*` 公共声明。
`chart-crosshair.js` 必须在 `macro.js` **之前**加载；canvas 容器显式高度 + `maintainAspectRatio:false` + 禁 `!important`。
shell 三副本（`app.js` / `macro.js` / `macro_cn.js`）——本轮**原则上不碰**；若碰必须三处同改。

**C3｜改类名的"静默变 0"检查**
`verify_ui.py` 依赖：`.mac-var`(1444/1458) · `.mac-rel-row[.strong]`(1446/1462) · `.mac-hist-row`(1469) · `.mac-econ-item`(1470/1698) · `.mac-2col`(1474/1666) · `.mac-card-head`(1636) · `.mac-empty`(1472) · `.mac-note`(1707)。
改名前后各 grep 一次，**逐条判断残留断言是"变红"还是"变假绿"**，并记入 journal。

**C4｜不得为上游红项造数**
10 条上游红（`MX-6/7/8/9/11/11b/13`、`M-4/5`、`XC-0`）源于 Yahoo 403（`system-overview.md §9 G8`）。本任务**只会让它们红得更好看**，禁止在前端补假数据。

---

## 6. Verification

| # | 命令 / 动作 | 期望 |
|---|---|---|
| V1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 后端契约不变（全绿） |
| V2 | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **新增改动前先跑一次**取得基线；改动后失败集 **⊆** 基线失败集（当轮新增红 = 0） |
| V3 | 基线 A/B | `git archive HEAD` 建隔离副本比对（**不要用 `git stash`**，外部 cron 会让它空跑） |
| V4 | 新增 N-* 断言（mock 四态） | 先红后绿；红跑清单入 journal |
| V5 | 五视口几何 | 1920/1600/1280/900/375：零横向溢出；`#mac-factors` slack ≤20；375 两列降单列 |
| V6 | 双主题人工截图 | light / dark 各一张，确认 N1–N4 在两主题下都成立、且**未把"背景资料"卡变成高对比** |
| V7 | `node --check web/static/macro.js` | 语法通过 |

---

## 7. Done When

- [ ] 宏观页有**可区分的四态**（loading / ok / empty / failed），失败态**可重试**，且**超时不再停留骨架屏**。
- [ ] 首屏骨架屏复用了既有 `.skeleton`，**无新增 CSS 骨架体系**。
- [ ] `#macro-factors` 的影响资产是**方向 Badge + 图标 chip**（复用既有 4 个 SVG，零新增素材）。
- [ ] `#regime-score` 颜色由 **`level` 同源**推导，`neutral` 不染色。
- [ ] `M-6 / M-7 / M-8 / M-9 / M-10` 全绿；`/macro/cn` 观感**零变化**（id 限定生效）。
- [ ] 双主题人工截图各一张留档。

---

## 8. Risks

| # | 风险 | 处置 |
|---|---|---|
| R1 | 骨架屏掩盖上游故障（G8 常态 403）→ 永远"加载中" | N1 硬约束：超时/失败必须切 `failed` 态；断言覆盖"超时后不再是 skeleton" |
| R2 | 把"缺失"做成永久 shimmer = 用动画掩盖取不到数 | E3：shimmer 仅限 loading；空值仍走 `.mac-empty` |
| R3 | 改 `.mac-*` 公共声明波及 `/macro/cn` | C2：`#mac-*` id 限定 + V6 人工核对 CN 页 |
| R4 | 类名/网格调整撞 `M-6`（留白上限）或 `M-10`（列数） | 实测 slack / 列数并记 journal；V5 |
| R5 | 重试按钮产生 `console.error` 撞 M-9b | `AbortError` → `console.warn`（`pitfalls` 既有处置） |
| R6 | 改 `macro.js` 误伤 shell 三副本一致性 | 本轮不碰 shell 段（`macro.js:122-236`），若必须碰则三处同改 |
