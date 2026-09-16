# 实施计划：`/macro` 状态体验与因子可读性（新增项）

> **需求来源**：`tasks/2026-09-16-macro-page-frontend-refactor/prd.md`（收窄定稿）
> **产出**：架构师实测后出具（含 `verify_ui.py` 的**本次实测基线数字**）；**未修改任何项目文件**
> **基线**：2026-09-16 22:4x，`master` @ `5360662`，工作区 clean（除 `docs/frontend-structure.md` 与 `tasks/2026-09-16-macro-page-frontend-refactor/` 为未跟踪新文件）
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 任务目标（引用 prd Goal）

在**不动**五级分层、`M-*` 护栏与双主题契约的前提下，只做四件从未做过的事：

1. **N1** 宏观页四态：`loading`（骨架屏）/ `ok` / `empty`（`.mac-empty`）/ `failed`（可重试）；
2. **N2** shimmer **仅用于 loading**（不得把"缺失"做成永久动画）；
3. **N3** 因子「影响资产」→ 方向 Badge + **复用既有 4 个 SVG** 的资产 chip；
4. **N4** `#regime-score` 语义色，**由服务端 `level` 同源推导**（不自己造阈值）。

---

## 2. 要改的文件

| 文件 | 改动性质 | 内容 |
|---|---|---|
| `web/templates/macro.html` | 改（约 +14 行） | ① 各块预置**骨架屏静态节点**（复用 `.skeleton`，与首页同做法）；② 失败态**重试按钮**；③ **不改任何既有 id** |
| `web/static/macro.js` | 改（约 +90 行 / −10） | 四态状态机 + `assetChipHtml()` + `#regime-score` 的 class 挂载 + shimmer 占位；`showChartFail()` 归并进失败态 |
| `web/static/style.css` | 改（**新增规则一律 `#mac-*` 限定**，约 +18 行） | 骨架屏尺寸占位、失败态修饰类、chip 样式；**不改任何 `.mac-*` 公共声明** |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 改（约 +110 行） | 新增 `N-*` 断言组（四态 / chip / score 同源色 / 无残留 skeleton） |
| `docs/architecture.md`、`docs/pitfalls.md` | 收尾追加 | 决策行 + 踩坑（shimmer ≠ 空值态；`score100` 是 0~100 而非 ±2） |

**零改动（须在 journal 复核）**：`web/app.py`、`src/**`、`tests/**`、`web/static/app.js`、`web/static/macro_cn.js`、`web/static/chart-crosshair.js`、`_topbar.html`、`_sidebar.html`。
（不新增静态文件 ⇒ **`_ASSET_FILES` 无需登记**；这是"不抽共享文件"的直接收益。）

---

## 3. 实测基线（本方案的事实依据）

### 3.1 复现路径

1. `venv/Scripts/python -m uvicorn web.app:app --port 8000`
2. 打开 `http://localhost:8000/macro`
3. **首屏**（清空缓存后强刷）可见：主图区空白、`#regime-score` 为字面 `—`、`#macro-asof` 为 `—`（无任何加载指示）
4. `curl localhost:8000/api/macro` → 4 品种 `value` 全 `null`、`trend.dates=[]`（Yahoo 403，`G8`）；此时页面**既不报错也不提示**，只有文字「数据暂缺」

### 3.2 关键测量点（`verify_ui.py` 本次实跑输出，light 主题）

| 量 | 实测值 | 与本任务的关系 |
|---|---|---|
| `#mac-factors` slack / `#mac-vars` slack | **12px / 12px** | **M-6 上限 20px ⇒ 仅剩 8px 余量**。N3 加内容会使 slack 变小（更安全），但**必须实测前后值并记录** |
| `regimeIsCard` / `regimeBorderTop` | `False` / `0px` | **M-7 基线绿** —— 本轮不得改动（Hero 卡片化已出范围） |
| `quiet bg` | `rgba(0,0,0,0)` | 四/五级块"无底色"是刻意设计（`style.css:709`）|
| `#mac-regime` 三段列宽 | `[210, 85, 1052] of 1396` | 一级块布局基线；N4 只加颜色**不改宽度** |
| `docH` | `1498 @1920` / `1349 @1280` / `1801 @375` | 无总高断言，仅作前后对比记录 |
| `chartWrapH` | `340 @1280` / `390 @375` | **M-8 要求 375 档 ≥360px**（当前 390，余量 30px）⇒ 骨架屏**不得**改变主图容器高度 |
| `twoCol` | `2 @1280` / `1 @375` | M-10 基线 |

> ⚠️ **`verify_ui.py` 的主跑主题是 light**（`hero bg=rgb(255,255,255)`）⇒ **N1–N4 的两主题差异只能靠人工截图覆盖**（见 §6 V6），自动断言只保证 light 下成立。

### 3.3 box-sizing 说明

- `#mac-factors` / `#mac-vars` 在 `.mac-2col` 网格内，`align-self: start`（**不被拉伸**）⇒ 其 `slack` 反映的是**自身内容外的留白**，加内容 → `slack` 减小，**不会顶破 M-6 的上限**。
- `.mac-factor-row` 的网格是 `72px 70px minmax(0,1fr)`（`style.css:785`），第 4 个子元素 `.fr-assets` 会**换行到第二行第 1 列** —— 即 chip 加在 `.fr-assets` 内**只增高、不改列结构**。
  ⚠️ 该规则 **被 `/macro/cn` 共用** ⇒ 若要调网格，选择器必须写 `#mac-factors .mac-factor-row`。
- 骨架屏节点须**占据与真实内容同量级的高度**（否则加载完成瞬间页面跳动）。做法：给骨架容器一个 `min-height`（按实测量取，如主图区直接用既有 `#macro-chart-wrap` 的 `clamp` 高度），**不要**给 `.skeleton` 本身写全局高度。

---

## 4. 实施步骤（每步可独立验证）

### Step 1 — 四态状态机（`macro.js` 骨架）

```js
// 伪代码：每块一个状态；'loading' | 'ok' | 'empty' | 'failed'
function setBlockState(blockId, state, opts) {
  // empty/failed 一律写 .mac-empty（★ 保持既有可测契约），failed 额外挂 is-failed + 重试按钮
}
```
- 状态源：`loadAll()` 的三个承诺（`/api/macro`、`/api/econ`）各自的 `pending / fulfilled(有数据) / fulfilled(空) / rejected`。
- ⚠️ **`.mac-empty` 类名与「数据暂缺」文案不得改**（`verify_ui.py:1472/1604` 断言依赖）。

**验证**：`node --check web/static/macro.js`；打开页面手动 `window.__macroState`（新增可测挂钩）观察四态。

### Step 2 — 失败态 + 重试 + **超时兜底**

- `getJSON()` 已有 `AbortController` 超时（15s）→ 超时必须走 `failed`，**不得停在 `loading`**。
- 重试按钮绑定在 IIFE 内（`loadAll` 是私有函数）；重试计数上限 3 次后禁用按钮。
- ⚠️ **M-9b**：`AbortError` → `console.warn`，其余才 `console.error`（`pitfalls` 既有处置）。

**验证**（`page.route` mock）：延迟 3s → 见骨架屏；返回异常 → 见失败态 + 重试；点重试 → 断言再次发起请求。

### Step 3 — Shimmer 仅用于 loading

- 只在 `renderRegime:475`（`#regime-score`）、`renderAll:682/684`（`#macro-asof`）、`varState:496` 的**加载期**用 shimmer 占位；
- 取数结束**一律替换**为真实值或既有 `—` / `.mac-empty`。

**验证**：加载完成后 `document.querySelectorAll('.skeleton').length === 0`。

### Step 4 — 因子资产 chip（复用既有素材，零新增）

```js
// 伪代码：与 app.js:97-101 同写法，但局部实现（不抽共享文件）
function assetChipHtml(name) {
  var icon = ICON_BY_ASSET[name];              // dollar | bond | gold | oil | null
  return '<span class="fr-chip">' + (icon
    ? '<i class="ico" style="background:var(--…)"><img class="ico-flag-img" src="/static/icons/'
      + icon + '.svg" alt="" onerror="this.remove()"></i>' : '') + escapeHtml(name) + '</span>';
}
```
- 映射：美元→`dollar`、利率·美债→`bond`、黄金→`gold`、原油·能源→`oil`；**「股票 / 信用」无素材 → 纯文字 chip**（零二进制新增）。
- ⚠️ **必须实测 `#mac-factors` 的 slack 前后值**（基线 12px / 上限 20px）并记入 journal。

**验证**：`#macro-factors` 每行 chip ≥1；有素材处 `<img>.naturalWidth > 0`；离线时不得留破图（`onerror` 自移除）。

### Step 5 — `#regime-score` 语义色（与 `level` 同源）

```js
// 伪代码：颜色由服务端 level 推导 —— 不得按 score100 与 50 的差值自造阈值
sc.className = "score-num " + (r.level === "risk_on" ? "up"
                            : r.level === "risk_off" ? "down" : "flat");
```
- `.mac .up/.down/.flat` **已存在**（`style.css:725-727`）⇒ **CSS 零改动**。
- ⚠️ 严禁"`score100 > 50` 就染绿"：`score100 = (normalized+1)/2*100`（`web/app.py:807`），中性 = **50**，若按"正/负"上色会让 `50` 也偏绿，且与 `#regime-level` 文案可能相反。

**验证**：mock 三组 `regime.level` → 断言 `#regime-score` 的 class 与 `#regime-level` 同向；`neutral` 不得染色。

### Step 6 — 断言先红后绿 + 几何复核

- 新增 `N-*` 断言组（四态 / chip / score 同源色 / 无残留 skeleton）；
- **改前先跑**取得基线（当前基线红 = 上游 10 条 + Firefox 2 条，见 `G8`）；
- 改后失败集必须 **⊆** 基线失败集（当轮新增红 = 0）。

---

## 5. 验证命令（引自 `docs/commands.md`）

| # | 命令 | 期望 |
|---|---|---|
| V0 | `node --check web/static/macro.js` | 退出码 0 |
| V1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 全绿（后端契约不变） |
| V2 | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 新增红 = 0（对比基线） |
| V3 | 基线 A/B：`git archive HEAD \| tar -x -C <tmp>` + venv junction | HEAD 失败集 ⊇ 本轮失败集；**不用 `git stash`**（外部 cron 会让它空跑） |
| V4 | V5 几何：5 视口（1920/1600/1280/900/375） | 零横向溢出；`#mac-factors` slack ≤ 20；375 两列降单列且 `chartWrapH ≥ 360` |
| V5 | 双主题人工截图（light / dark） | N1–N4 均成立；**四/五级块的"背景资料"低对比未被破坏** |

---

## 6. 多尺寸验收（预期）

| 视口 | 预期 |
|---|---|
| 1920×1080 | 主图区骨架屏高度 ≈ 既有 `#macro-chart-wrap`（不跳动）；`#mac-factors` slack ≤ 20；`docH` 相对基线 1498 增幅 < 40px |
| 1600×900 | 同上（`M-*` 断点空档 A） |
| 1280×720 | 两列保持 2 列；`chartWrapH` 仍 340（骨架屏不得改容器高） |
| 900×800 | 无横向溢出（断点空档 B） |
| 375×812 | 两列降单列；`chartWrapH ≥ 360`（基线 390）；chip 允许换行不溢出 |

---

## 7. 风险评估

| # | 风险 | 影响 | 处置 |
|---|---|---|---|
| **R1** | 骨架屏掩盖上游故障（G8 常态 403）→ 永远"加载中" | 体验比现状更糟（现在是空态，至少是"确定的无数据"） | Step 2 硬约束：15s 超时/异常必须切 `failed`；断言覆盖"超时后不再是 skeleton" |
| **R2** | 把"缺失"做成永久 shimmer | 用动画掩盖"取不到数"（`pitfalls` 有专条） | N2 规则：shimmer 仅 loading；空值走 `.mac-empty` |
| **R3** | 改 `.mac-*` 公共声明波及 `/macro/cn` | CN 页观感被动改（无断言兜底） | 新规则一律 `#mac-*` 限定；V5 人工核对 CN 页 |
| **R4** | chip 撑高 `#mac-factors` → 撞 M-6 / 页面跳动 | M-6 上限 20（基线 12） | 实测 slack 前后值；骨架屏用 `min-height` 对齐真实高度 |
| **R5** | 重试按钮产生 `console.error` → 撞 M-9b | 红项 | `AbortError` → `console.warn` |
| **R6** | 改 `macro.js` 误伤 shell 三副本段（`:122-236`） | 三页行为不一致 | 本轮**不碰 shell 段**；若必须碰则三处同改 + 互指注释 |
| **R7** | 改类名让旧选择器静默变 0（"变假绿"） | 断言失真 | C3 清单 + 改名前后各 grep，逐条判断红/假绿 |

---

## 8. 预计影响范围

```
web/templates/macro.html                          +14  −2    骨架屏节点 + 重试按钮
web/static/macro.js                               +90  −10   四态 + chip + score class + shimmer
web/static/style.css                              +18  −0    #mac-* 限定新规则（不动公共声明）
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py  +110  N-* 断言组（补强，不删既有）
docs/architecture.md / docs/pitfalls.md            +3  −0    决策行 + 踩坑
```

**零改动**：`web/app.py`（不新增静态文件）、`src/**`、`tests/**`、`web/static/app.js`、`macro_cn.js`、`chart-crosshair.js`、`_topbar.html`、`_sidebar.html`。

**提交清单提醒（本项目惯例）**：源码 + 共享验收脚本 + `docs/` 改动 + **本任务 `tasks/<dir>/`（`prd.md` / `prd-review.md` / `plan.md` / `journal.md`）** + `docs/frontend-structure.md`（当前仍是**未跟踪**新文件，必须一并 `git add`）。用 `git add <具体路径>`，**不用** `-A`。
