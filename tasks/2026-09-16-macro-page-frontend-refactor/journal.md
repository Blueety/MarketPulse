# Journal — `/macro` 状态体验与因子可读性（N1–N4 新增项）

- **日期**：2026-09-16
- **任务目录**：`tasks/2026-09-16-macro-page-frontend-refactor/`
- **依据**：`prd.md`（收窄定稿：只做新增，7 项明确不做）+ `plan.md`（架构师实测后出具）
- **性质**：前端四态状态机 + 因子 chip + Score 语义色 + 验收断言组 + 文档回填
- **执行角色**：编码执行者（Phase 3 Step 3.6–3.7）；未做架构决策、未做计划外改动
- **基线**：`master` @ `5360662`（工作区 clean；`docs/frontend-structure.md` 与任务目录为未跟踪新文件）

---

## 1. 目标（已达成）

只做四项**新增**，不动五级分层 / `M-*` 护栏 / 双主题契约：

1. **N1** 宏观页四态：`loading`（骨架屏）/ `ok` / `empty`（`.mac-empty`）/ `failed`（`.mac-empty.is-failed` + 可重试）
2. **N2** shimmer **仅用于 loading**（"取不到数"仍走 `.mac-empty`，不得做成永久动画）
3. **N3** 因子「影响资产」→ 方向 Badge + 资产图标 chip（复用既有 4 个 SVG，零新增素材）
4. **N4** `#regime-score` 语义色，**由服务端 `level` 同源推导**（禁"`score100 > 50` 就染绿"）

**明确不做（逐条遵守，未顺手做）**：Hero 卡片化、全局提对比、卡片套卡片、JetBrains Mono/webfont、SOON 徽章、改默认主题、后端（`web/app.py` / `src/**` / `tests/**` 零改动）。

---

## 2. 改动文件清单（实际规模 vs plan §8 预估）

| 文件 | plan 预估 | 实际 | 内容 |
|---|---|---|---|
| `web/templates/macro.html` | +14 −2 | **+32 −19** | 11 个块预置**静态骨架屏**（`data-skel="<block>"`，复用 `.skeleton`）；失败条 `#mac-fail-bar` + `#mac-retry`；**未改任何既有 id**（`#macro-chart-fail` / `#regime-*` / `#macro-*` 全部原样） |
| `web/static/macro.js` | +90 −10 | **+211 −22** | 四态状态机（`SKEL_OF_SOURCE` / `BLOCK_HOST` / `clearSkel` / `settleSource` / `markSource` / `markFailedEmpties`）+ 失败条 + 重试（上限 3）+ `getJSON` 非 2xx 判失败 + `assetChipsHtml()` + `LEVEL_CLASS` + `window.__macroState` 观测钩子 + `window.__macroTimeoutMs` 超时注入钩子 |
| `web/static/style.css` | +18 −0 | **+62 −0** | 骨架尺寸（**全部 `#mac-*` / `#macro-*` id 限定**）、失败条 `:not(.hidden)`、失败态块级左红线、chip/badge 样式、经济数据骨架的断点镜像 |
| `tasks/.../verify_ui.py` | +110 | **+386** | 新增 `NA-*` 断言组（32 条）+ `_na_payload` / `NA_ECON` / `NA_JS` / `_na_open` 助手；**未删改任何既有断言** |
| `docs/pitfalls.md` | +3 | **+12 行（8 条规则）** | 新段「模块 web/（宏观页四态 + 因子 chip + Score 语义色，2026-09-16）」 |
| `docs/architecture.md` | +3 | **+2** | 决策表 1 行（append-only，`## 约束` 之前） |

> ⚠️ **规模超预估 2–3 倍**（合计 +684 −21，plan 预估约 +230）。主因：① 本项目注释纪律要求把"为什么这么写"落在代码旁（`macro.js` 里约一半行是注释）；② 验收组比 plan 的 110 行多，因为补了 mock 夹具、四组 Score 用例、CN 页零影响与截图。**功能范围未超**（未做任何 §2 明令不做项）。请需求方在审 diff 时确认这个体量可接受。

**零改动（已逐项核实）**：`web/app.py`、`src/**`、`tests/**`、`web/static/app.js`、`web/static/macro_cn.js`、`web/static/chart-crosshair.js`、`web/templates/_topbar.html`、`_sidebar.html`、`index.html`。不新增静态文件 ⇒ `_ASSET_FILES` 无需登记。

---

## 3. 验证结果（全部实跑）

| # | 命令 / 动作 | 结果 |
|---|---|---|
| V0 | `node --check web/static/macro.js` | 退出码 0 ✔ |
| V1 | `venv/Scripts/python -m pytest tests/test_web.py -q` | **120 passed**（后端契约不变）✔ |
| V2-a | 全量验收（**改动前基线**，上游健康） | **509 PASS / 0 FAIL / ALL PASSED** ✔ 记下基线数字（见 §4） |
| V2-b | 全量验收（改动后，上游健康） | **541 PASS / 0 FAIL / ALL PASSED**（+32 = NA 组）✔ 新增红 **0** |
| V2-c | 全量验收（改动后，**上游又挂**） | **519 PASS / 12 FAIL**；12 条全在 `MX-*/M-*/XC-*/N-12*`（本任务未触碰的组）→ 同刻基线 A/B 见 §5.4 |
| V3 | 基线 A/B（`git archive HEAD` + venv 目录联接；**未用 `git stash`**） | 同刻 HEAD 基线 **15 条失败**，本轮 12 条为**其真子集** ⇒ 新增红 **0** ✔ |
| V4 | **改前红跑**（新断言组跑在 HEAD 副本上） | **28 FAIL / 4 PASS**；4 条 PASS 全部是"改前改后都该绿"的不变量护栏（M-6 上限、`/macro/cn` 零影响 ×3）✔ 先红后绿成立 |
| V4-b | 绿跑（工作区） | **32 PASS / 0 FAIL** ✔ |
| V5 | 几何（五视口，`M-*` 全绿） | `#mac-factors` slack **12px 不变**；`chartWrapH` **497 / 340 / 390 不变**；`twoCol` 2@1280、1@375；三档零横向溢出 ✔ |
| V6 | 双主题人工截图 | `shot-na-macro-light.png` / `shot-na-macro-dark.png`（已人工查看：四态/chip/Score 色在两主题下均成立，四/五级"背景资料"低对比未被破坏）✔ 另留 `shot-na-loading.png` / `shot-na-failed.png` / `shot-na-cn.png` |
| V7 | `/macro/cn` 观感零变化 | `NA-8/8b/8c` 全绿：CN 页 0 骨架 / 0 chip / 0 badge / 0 `is-failed`，共享 `.mac-factor-row` 网格仍 `72px 70px`，无横向溢出；并留截图 ✔ |

---

## 4. 几何与规模对照（上游健康数据下，基线 → 改动后）

| 量 | 基线 | 改动后 | 判定 |
|---|---|---|---|
| `#mac-factors` slack / `#mac-vars` slack | 12px / 12px | **12px / 12px** | M-6 上限 20 ⇒ 未劣化（N3 加 chip **没有**撑高留白） |
| `docH` @1920 / 1280 / 375 | 1632 / 1524 / 2518 | **1642 / 1534 / 2529** | +10 ~ +11px（plan §6 容差 <+40px） |
| `chartWrapH` @1920 / 1280 / 375 | 497 / 340 / 390 | **497 / 340 / 390** | 骨架用绝对定位铺满 ⇒ 不改容器高（M-8 / MX-3b 安全） |
| `twoCol` @1280 / 375 | 2 / 1 | 2 / 1 | M-10 不变 |
| 断言总数 | 509 | **541** | +32（NA 组） |

---

## 5. 遇到的问题

### 5.1 N4 的关键陷阱（用户已预先点名，实测确认）

`score100 = (normalized+1)/2*100` 是 **0~100、中性 50**，**不是** ±2 的分值区间（±2 是四个因子的 `impact`，见 `web/app.py:766-794` 与 `:807`）。若按"正/负分"上色，`score100=50` 会被当正分 → **全表偏绿**，且可能与 `#regime-level` 文案相反。
本实现：`sc.className = "score-num " + (LEVEL_CLASS[r.level] || "flat")`，**只读 `level`**。
⚠️ 更关键的是**断言设计**：真实数据里 `level` 与 `score100` 恰好同向（实测 `Risk-On` 配 `68.8`），只喂"一致用例"的话**错误实现也会全绿**。故 `NA-7` 里加了两组**矛盾输入**：`risk_off + 80.0`（必须红）、`risk_on + 35.0`（必须绿）。

### 5.2 三处"真空绿" + 一处"崩溃"（红跑抓出来的，全部已修）

| 断言 | 缺陷 | 修法 |
|---|---|---|
| `NA-1d` | 基线无 `__macroState` 钩子 → `blocks=None` → `not None` 为真 → PASS | 加 `a1["hasHook"] is True` 合取项 |
| `NA-2 / NA-4 / NA-5d` | 基线本来就没有骨架/图片 ⇒"骨架已撤掉""无破图"**平凡成立** | 加"前置状态确实存在"：`a1["skelVisible"] >= 8 and …`、`bool(d["imgSrc"]) and …`、`bool(d["blocks"])` |
| `NA-2c` | `len(a2["blocks"])` 在 `None` 时 **TypeError → 整组中断**（红跑只报了 4 条就"结束"，极具误导性） | 先 `bool(...)` 再 `len(...)`；点重试改写成"找不到按钮就返回 false"的 JS |
| `NA-2f` | 只判"无 error" → 基线因**写死 15s 超时**、3.2s 内根本没降级，也 PASS | 合取"降级确实发生"（`settled`） |

### 5.3 骨架屏"包裹层是 grid item"导致布局完全走形（截图实测发现）

`#mac-econ` 是 `repeat(4, minmax(0,1fr))` 的 grid，我最初把 4 条骨架放进一个 wrapper `<div>` → 该 wrapper **只占第 1 个列位**，再被内部 4 列切成 4 份 → 渲染成"4 个小方块缩在左上角"，与真实"四张整宽卡"完全不符（截图 `shot-na-loading.png` 一眼可见）。修法：`#mac-econ [data-skel] { grid-column: 1 / -1; … }` + 镜像 `.mac-econ` 的 768/480 断点。
同理把四维指标骨架由 1 条改 4 条：`.regime-factors` 在 ≥1440 是 2 列 grid（`style.css:817`）⇒ 4 条正好 2 行，<1440 是纵向 flex ⇒ 4 行。**判据**：占位层落进 grid/flex 容器时，先确认它会被当成一个 item 还是铺满。

### 5.4 两个取数源互相抹掉状态类（实测 `factorsFailed=False` 而 `econFailed=True`）

`/api/macro` 与 `/api/econ` 各自 `.then/.catch` 都调 `renderAll()`，而 `renderAll` **重建容器 `innerHTML`** ⇒ 先结算的一方刚给 `.mac-empty` 加的 `is-failed` 被后结算的一方清掉。
修法：把失败态修饰收进 `renderAll()` 内部、**在所有 render 之后**按 `failMacro/failEcon` 标志位统一补挂（幂等），不散落在各 catch 里。

### 5.5 断言把"模板常驻元素"算进去了（假红）

失败条自身的 `<p class="mac-empty is-failed" id="mac-fail-msg">` 是**模板静态常驻**（靠 `.hidden` 控显隐）⇒ 成功态 `document.querySelectorAll('.mac-empty.is-failed').length` 也 =1 → "成功态不残留 is-failed"永远假红（实测 `actual=(False, 1)`）。修法：`.filter(n => !n.closest('#mac-fail-bar'))` 后再计数。

### 5.6 `.hidden` 与 id 特异性打架

`.hidden { display: none }` 只有 (0,1,0)。若给 `#mac-fail-bar` 写 `display: flex`（(1,0,0)）会**盖掉隐藏语义 → 失败条常显**。修法：显示语义写在 `#mac-fail-bar:not(.hidden) { display: flex; … }`。

### 5.7 标签前缀撞名（按 plan 执行会出事）

plan 让用 `N-*`，但 `N-*` 已被首页「最新资讯」断言占用（`N-1` / `N-7` / `N-11` / `N-12a`…）→ 改名 **`NA-*`**（同 `XC-*` 先例，已在脚本内注释说明）。**这是对 plan 的偏离，请需求方知悉**（不撞名才可定位失败）。

### 5.8 上游数据源二次停摆（与本任务无关，但影响"整跑是否全绿"）

改动前基线跑（上游健康）**ALL PASSED**；改后跑一次全绿；随后再跑时 Yahoo 又取不到数（端点直打：4 品种 `value` 全 `null`、`trend.dates=[]`；`/api/econ` `as_of=null`）→ 12 条 `MX-*/M-*/XC-*/N-12*` 变红。
**同刻基线 A/B**：HEAD 副本 15 条 ⊇ 本轮 12 条 ⇒ **新增红 0**。⚠️ 本轮**未修**这 12 条（属既有问题 + 上游，超范围；C4 明令不得为上游红项造数）。

---

## 6. 取证缺口（明确标注，未做）

- ❌ **节假日**未涉及（本任务无日历依赖）。
- ❌ **真实 15s 超时未实跑**：为免等 15s，验收用 `window.__macroTimeoutMs` 注入 2s（走的是**同一条** AbortController 代码路径，但 15000 这个**数值**未在真实等待下验证）。生产未设置该钩子 ⇒ 默认 15000ms 生效。
- ❌ **触屏未验**：本次无触屏相关分支。
- ❌ **Firefox 内核专项（`N-12a/12b`）未修**：基线上同样红（既有问题）。
- ❌ **`#mac-econ` 骨架在 ≤480 档未单独截图**：CSS 已镜像断点，但只人工看过 1440 档（与 1920 一致 4 列）。
- ⚠️ **`docH` 前后对比取自"上游健康"那一次**；上游挂时 docH 会因内容变少而变小（同轮实测 1498），两组数字不可跨数据条件直接比。
- ⚠️ **`FACTOR_ASSETS` 的键 `波动率` 与服务端因子名 `风险偏好` 不匹配**（`macro.js:55-60` vs `web/app.py:766`）⇒ "风险偏好"因子恒走 fallback 文案（"风险资产 受益"），拿不到 `股票 / 信用` 的精确表述。**属既有内容问题、不在 N1–N4 范围内，有意未修**，仅在此记录（`NA-5e` 正好把这条现状钉住：风险偏好行 = 纯文字 chip）。

---

## 7. 下次注意

- **shimmer 只属于 loading**：任何"装载中"占位都必须有一个"必然能走到终态"的出口（含**超时**），否则上游故障时页面比无占位更糟。把超时做成可注入钩子，验收才测得动。
- **占位层落进 grid/flex 先问"我会被当成一个 item 吗"**：`grid-column: 1/-1` 之类的一行修复，不做就是"4 个小方块"级别的走形，且只有截图能发现。
- **"渲染后再补的状态类"必须挂得住下一次渲染**：放进 `renderAll()` 末尾按标志位统一补，别散在各个 catch。
- **按类名计数前先问"模板里有没有常驻同款"**：有就先排除它，否则永远是假红。
- **给"用 `.hidden` 控显隐"的元素加样式，不要写它自身的 `display`** —— 用 `:not(.hidden)` 同源。
- **"两字段应当同源"的断言必须构造两字段冲突的输入**：只喂一致用例等于没测（本次 `level` vs `score100`）。
- **红跑要"报红"不要"崩溃"，也要防"真空绿"**：`all([])==True`、空集比较、基线缺元素时的平凡成立，都要用"前置状态存在"的合取项堵住；红跑里剩下的 PASS 要逐条归类成"真不变量"还是"漏网"。
- **新增断言组前 grep 已占用的标签前缀**（本项目 `N-*` 已属资讯组）。
- **提交清单**：源码 + 共享验收脚本 + `docs/` ×2 + **本任务 `tasks/2026-09-16-macro-page-frontend-refactor/`（prd / prd-review / plan / journal）** + **`docs/frontend-structure.md`（未跟踪新文件，必须一并 add）**；用 `git add <具体路径>`，**不用** `-A`。

---

## 9. 追加修复（2026-09-17，用户反馈「怎么又受益又承压的」）

### 9.1 现象与根因

用户截图红框标出「利率 ↓偏空 → `受益 🪙黄金 承压 长久期`」，问"这什么意思，怎么又受益又承压的"。

- **语义没错**：「利率偏空 → 黄金**受益**、长久期**承压**」——两个 badge 属于**两个不同资产**。
- **排版有错（本任务 N3 引入）**：原 `assetChipsHtml` 按"**每句**出一个 badge、后面跟 N 个 chip"平铺，
  元素排成 `受益 · 黄金 · 承压 · 长久期` ⇒ **中间的 chip 被两个 badge 夹心**，
  在 6px 均等间距下必然被读成"黄金又受益又承压"。**属排版配对歧义，不是数据/文案错误。**
- **顺带发现第二处**：`impact = 0` 时按模板出了 `中性` badge，chip 文案又是「中性不构成方向」
  ⇒ 渲染成 `中性 中性不构成方向`（同一个词两遍，4 行全中）。

### 9.2 修法（`web/static/macro.js` + `web/static/style.css`）

- `assetChipsHtml` 改为**每个资产一个组** `<span class="fr-grp"><chip><badge></span>`：
  **资产在前、方向在后**，配对不可拆散；组间 `gap: 12px` > 组内 `gap: 5px`。
- flat 分支**不出 badge**，直接显示原文（仍保留 chip，满足"每行 chip ≥1"的验收）。

### 9.3 验证（先红后绿，实跑）

| 步骤 | 结果 |
|---|---|
| 改前红跑（新断言 vs 现网实现） | **3 FAIL**：`NA-5f chipsOutsideGrp=8`、`NA-5h2 neutralDup=4`、`NA-5h3 chipsOutsideGrp=4` ✔ |
| 改后绿跑（NA 组） | **37 PASS / 0 FAIL**（原 31 + 新增 6）✔ |
| 关键数字 | `chips/行=[1,3,2,2]` **不变**、`img/行=[0,2,1,1]` **不变**、`slack=12px` **不变**（信息量未减、几何未变） |
| 全中性夹具 | `badges=[None×4]`（flat 不出 badge）、`neutralDup=0`、`chipsOutsideGrp=0` ✔ |
| 可视复核 | `shot-na-macro-light.png`：利率行现读作 `黄金 受益` / `长久期 承压`，配对一眼可分 ✔ |

### 9.4 新增断言（补强，未删改既有）

- `NA-5f` 每个 chip 都在 `.fr-grp` 内（不裸平铺）
- `NA-5g` 组内 badge 必须在 chip **之后** + `grpCount >= rowCount`（⚠️ 前置条件不可省：首版忘加，
  选择器空集导致该条**真空变绿**）
- `NA-5h / h2 / h3` 全中性夹具：每行仍 ≥1 chip、不重复写「中性」、chip 同样在组内

### 9.5 遗留（未做，需需求方裁定）

- ⚠️ **`FACTOR_ASSETS` 的资产方向与后端 `inverse` 约定不同源（美元 / 利率 两个维度）** —— 本次只修**呈现**，不动文案。

  **后端口径**（`web/app.py:685-695, 766-795`）：`_band_score(..., inverse=True)` 的注释写明
  "数值上行 = 风险偏好下行（美元走强 / 利率上行），符号取反" → 对**美元**与**利率**这两个维度：
  `impact > 0` 意味着**该变量下行**（美元走弱 / 利率下行），`impact < 0` 意味着**该变量上行**。
  ⇒ 前端 `cls(impact)` 显示的「↑ 偏多 / ↓ 偏空」是**对风险偏好**的加减分方向，**不是该变量自身的涨跌**。

  **前端 `FACTOR_ASSETS` 的文案却按"变量上行 = pos"写**，于是这两个维度整体反了：

  | 维度 | 前端 pos 文案 | 实际 `impact>0` 的含义 | 判定 |
  |---|---|---|---|
  | 美元 | `风险资产 受益 · 黄金/原油 承压` | 美元**弱于** 50 日均线 | ✗ 反（弱美元应利多大宗） |
  | 利率 | `美元 受益 · 黄金/长久期 承压` | 利率**下行** | ✗ 反 |
  | 商品 | `能源 / 材料 受益` | 原油**上行** | ✓ 一致（该维度**没有** inverse） |
  | 风险偏好 | `股票 / 信用 受益` | VIX 平静 | ✓ 一致 |

  **今日实证**（2026-09-17 凌晨 FOMC 加息 25bp 至 3.75–4.00%，10Y 突破 5% 创 19 年新高、
  美元指数站上 100、**现货黄金 -0.69%**）→ 用户截图那一行是 `利率 ↓偏空`（= 收益率上行），
  而它写的资产是「**黄金 受益**」——
  同一张截图里黄金 COMEX 就是 **-0.36%**。**文案方向与市场表现相反**，
  而同一行的「长久期资产 承压」方向是对的 ⇒ 进一步印证"这一支是按利率上行写的、且黄金那半句写反"。
  ⚠️ 属 2026-09-14 引入的**既有内容映射**问题（`macro.js:55-60`），不在本次"只修呈现"的范围，**未改**。

- ✅ **更正我在交付说明里的一处口误**：我此前把「利率 偏空」解释成"利率**下行**"（据此还推断
  "与 `pos` 分支不自洽"）——**前提就错了**。按代码，`利率 偏空` = 10Y 近 5 日**上行** 0.10~0.25pp。
  上文 9.5 的表格已按正确符号重写。


