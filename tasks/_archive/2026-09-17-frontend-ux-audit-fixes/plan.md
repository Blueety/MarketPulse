# 实施计划：前端体验走查整改（P1×2 + P2×3）

> **需求来源**：在线文档《前端体验走查报告 — MarketPulse Web 看板》（2026-09-17 09:15–09:40 走查，
> https://www.workbuddy.cn/space/d/rbJF14YE7MfCAvyT53wSxc ，任务档 `tasks/2026-09-17-frontend-ux-review/`）
> **产出**：架构师对报告关键论断**逐条核实后**出具（核对结果见 §2）；**未修改任何项目文件**
> **基线**：2026-09-17 09:56，`master` @ `7dc6231`；工作区仅 `?? tasks/2026-09-17-frontend-ux-review/`（未跟踪）
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 背景与范围裁定

- 昨晚 `/macro` 四态任务已交付（`00adbea`）+ 今早两次修补（`c06758b`/`b5e3a7d`）—— **已收尾，不在本计划范围**。
- 本计划覆盖走查报告的 **P1×2 + P2×3**；P3×3 延后（§6）。
- ⚠️ **走查时间横跨提交**：报告走查 09:15–09:40，而 `b5e3a7d` 落在 09:32 —— 报告中与「因子 chip」相关的观察可能反映修复前状态；本计划采信的 5 项与 chip 无关，不受影响。

---

## 2. 报告论断核实（架构师逐条对码，2 处需修正后实施）

| # | 报告论断 | 核实结果 |
|---|---|---|
| P1-② | `refresh()` 无 loading/失败反馈；history 取数失败被 `.catch(function(){ renderMainChart(); })` **静默吞掉** | ✅ **属实**：`app.js:1072`；且全页 0 个 `aria-live`。注意：`/api/latest` 那路其实有 `loadFailed()`（`app.js:1087`），短板集中在 **history（趋势主图）** 一路 |
| P1-① | 浅色主题 `--text-tertiary`(#9CA3AF) 对比度 2.2–2.5，需加深至 ≥4.5:1 | ⚠️ **结论对、名字错**：仓库里**没有** `--text-tertiary`，该 token 叫 **`--text-muted`**（light `#9CA3AF` @ `style.css:11`；dark `#8E9BAE` @ `:55` **已经单独修过**——即"深色修了、浅色没修"的不对称成立）。实施必须打在 **light 的 `--text-muted`** 上 |
| P2-③ | `index.html` 主题初始化只处理 light（FOUC + 三处不一致） | ✅ **属实**：`index.html:11-17` 只在 `mp-theme === "light"` 时写属性；`macro.html:16-23` 已是 D1 修复版 |
| P2-④ | 移动抽屉打开时背景仍可滚动、焦点不移入 | ✅ 基本属实（`app.js:1109-1116` 只切 `body.nav-open`，无滚动锁定/焦点管理）；`style.css:601-606` 抽屉为 fixed |
| P2-⑤ | 首页缺「失败条 + 重试」，宏观页已有现成模式 | ✅ **属实**：宏观页 `#mac-fail-bar` + `#mac-retry`（`macro.html:43-48`、`macro.js:128-155/867/906-916`，昨晚交付物）确实可复制；首页 history 一路失败只重绘旧图、无任何提示 |

> 另：报告 P3 的 `.ms-time` 10px 属实（`style.css:206`，我此前实测也是 10px）；h1 landmark / 占位文案未逐一复核，延后时采信报告。

---

## 3. 要改的文件与任务分解

| 步骤 | 文件 | 内容 |
|---|---|---|
| **F1** 浅色对比度（P1-①） | `web/static/style.css` | light 段 `--text-muted: #9CA3AF → #6B7280`（**与 `--text-secondary` 同值**；dark 段不动）；同步加深图表 meta 涨跌色（先 `grep rgb(19,194,194)/#13C2C2` 定位来源，**不写死改法**）；`.ms-time` 10→11px 顺带 |
| **F2** 刷新反馈 + 首页失败条（P1-② + P2-⑤ 合并） | `web/static/app.js`、`web/templates/index.html`、`style.css` | ① 刷新期间按钮转圈/禁用；② trend 卡加 `#home-fail-bar`（复制宏观页 `#mac-fail-bar` 的 DOM 模式 + CSS 块，**保留宏观页原样不动**，N-* 断言零破坏）；③ `app.js:1072` 的静默 catch 改为「**保留旧图渲染 + 显示失败条**」（不得丢掉"离线时仍看旧数据"的既有行为）；④ 趋势卡/顶栏日期补 `aria-live="polite"` |
| **F3** 主题初始化三处同源（P2-③） | `web/templates/index.html` | 把 `macro.html:16-23` 的 D1 修复版内联脚本同步过来（light/dark 双处理），并按项目纪律加互指注释（`frontend-structure.md §7-1`：**改一处必须四处同改**，本轮恰好就是把第 4 处对齐，勿再分叉） |
| **F4** 抽屉滚动锁定 + 焦点管理（P2-④） | `web/static/app.js`、`style.css` | `body.nav-open` 时 `overflow:hidden`；开抽屉焦点移入（首个可聚焦项）、关闭归还触发按钮；补 `Escape` 关闭（可选） |
| **收尾** | `docs/pitfalls.md`、`docs/architecture.md` | 踩坑（报告用错 token 名 `--text-tertiary`；"深色修了浅色没修"的不对称根因）+ 决策行 |

**零改动**：`macro.html` / `macro.js` / `macro_cn.js`（宏观页昨晚交付物与 N-* 断言**必须原样保留**）、`web/app.py`、`src/**`、`tests/**`、`chart-crosshair.js`。

---

## 4. 实施步骤（每步可独立验证）

### Step 1 — F1 对比度（先做，纯 token，风险最低）

- light `--text-muted` 换 `#6B7280` 后，**影响面 = 全站所有 `var(--text-muted)` 消费点**（约 30 处：`.ms-time/.link-btn/.ph-note/.empty/.kpi-card::before/.mac-sub/.mac-note/.mac-foot/.mac-empty/.score-cap/.f-note/.v-unit/.fr-note/.rel-n/.e-date/…`）。
- ⚠️ **有意接受的连带**：`.kpi-card::before` 色条、`.ms-dot`、`.h-bar i.neutral` 等**装饰色**会一起变深 —— dark 侧昨晚之前做过同款取舍（`style.css:53-54` 注释原文「装饰会随之提亮，须目视」），本轮 light 侧对等处理，**必须目视截图留档**。
- 图表 meta 涨跌色：先定位再改；若它读的是 `--c-*` token 则只动 light 段。

**验证**：改前后各截 light 首页/宏观页整页图；`verify_ui` 全量跑（失败集 ⊆ 基线）。

### Step 2 — F2 刷新反馈（P1 核心）

```js
// 伪代码：app.js refresh()
refreshing = true; setRefreshBtnState(true);          // 转圈 + disabled
fetchHistory().then(ok).catch(fail)                   // fail ≠ 静默：showHomeFailBar(msg) 且仍 renderMainChart()
finally { refreshing = false; setRefreshBtnState(false); }
```
- `#home-fail-bar` 的 CSS **照抄** `style.css:766-772` 的 `#mac-fail-bar` 块并换 id（沿用「显示语义由 `:not(.hidden)` 承担、勿给 id 写 display」的既有约定，`macro.html:43` 注释原文）。
- ⚠️ **不要**把 `#mac-fail-bar` 的 id 规则改成共享 class —— 宏观页 N-* 断言与 DOM 契约会受牵连；接受这份小体积复制（与 shell 三副本同源的取舍）。
- `aria-live="polite"` 加在趋势卡标题旁或 `#home-fail-bar` 本身；不要用 `role=alert`（刷数据不是紧急事件）。

**验证**：`page.route` 把 `/api/history` 断成异常 → 断言失败条可见且**旧图仍在**；恢复路由 → 失败条消失；刷新期间按钮 `disabled === true`。

### Step 3 — F3 主题初始化对齐

- 用 `macro.html:16-23` 的版本替换 `index.html:11-17`，注释互指（"与 macro.html / macro_cn.html 同源，改一处四处同改"）。
- ⚠️ 同步后需复核 `verify_ui` 的主题类断言（带 `add_init_script` 写 localStorage 再载入的那组）：light/dark 行为都不应变。

**验证**：`localStorage.mp-theme=dark` 冷载首页 → `documentElement.dataset.theme === "dark"` 且 body 背景色首帧即深色（无浅色闪变）。

### Step 4 — F4 抽屉

- `body.nav-open { overflow: hidden }`；开：焦点移入侧栏首个可聚焦项；关：焦点归还 `#menu-toggle`。
- ⚠️ 不改 `.tab-panels` radio 与 `#sidebar` 的 fixed 定位（`style.css:601-606`）——它们是既有断言依赖。

**验证**：375 视口开抽屉 → `document.body.style.overflow === 'hidden'`、`document.activeElement` 在抽屉内；关闭 → 焦点归还。

### Step 5 — 收尾与提交

- `docs/pitfalls.md`：两条（① 报告引用了不存在的 token 名 —— **评审类文档的 token 名必须 grep 实证**；② 对比度修复"只修了 dark"的不对称根因 = 当时只改了 dark 段）。
- `docs/architecture.md` 决策表 1 行。
- **提交清单**：源码 + `verify_ui.py`（若断言有补强）+ `docs/` + `tasks/2026-09-17-frontend-ux-review/`（**含走查报告任务档，当前未跟踪，必须一起入库**）+ 本任务档。`git add <具体路径>`，不用 `-A`。

---

## 5. 验证命令（引自 `docs/commands.md`）

| # | 命令 | 期望 |
|---|---|---|
| V0 | `node --check web/static/app.js` | 退出码 0 |
| V1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 全绿 |
| V2 | **改前** `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 记录**当日基线**（G8：12 条上游/Firefox 红是常态，**只看相对变化**） |
| V3 | **改后** 同上 | 失败集 ⊆ 基线；F1–F4 的新增断言先红后绿 |
| V4 | 五视口（1920/1600/1280/900/375） | 零横向溢出；对比度抽样 ≥ 4.5:1 |
| V5 | 双主题人工截图 | light 加深后整体不"发灰"、dark 无回归 |

---

## 6. 明确延后（P3，本轮不做）

| 项 | 理由 |
|---|---|
| 首页补 h1 / `.mac-head` 改 `<div>` | 纯 landmark 语义，不影响使用；单独小任务 |
| 长期占位块补「接入计划」文案 | 需求方先给接入计划，前端无依据可写 |
| 失败条下沉为共享组件 | 与"shell 三副本刻意复制"同源的成本/收益题，值得单独讨论后再动 |
