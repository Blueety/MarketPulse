# Journal：四象限矩阵可视化（`/macro` + `/macro/cn`）

> 用户反馈（2026-09-18）："这个 四象限：好像只有文字，没有图啊"
> 任务目录：`tasks/2026-09-18-macro-quadrant-matrix/` ｜ 计划：`plan.md`

---

## 1. 目标

把宏观页一级块里那行 12px 灰字（「四象限：再通胀（通胀↑ · 增长↑）」）升级为**可读的 2×2 矩阵**，
补回两层被纯文字丢掉的信息：**位置感**（当前在四格的哪一格）与**换格**（一眼看出象限边界）。

**明确不做**（plan §7 逐条守住）：不做换格轨迹/箭头（`history_regime` 只有三态**天数**，没有四象限历史序列，
画轨迹＝编数据）；不给四格染红绿（象限无褒贬，「滞胀」不是「跌」）；不改 `#regime-quadrant` 文案；
不改后端四象限算法；不动首页。

## 2. 改动清单（5 文件，+约 190 行）

| 文件 | 改动 |
|---|---|
| `web/templates/macro.html` | 在 `#regime-quadrant` **之后**新增兄弟容器 `#regime-matrix`（内含 `data-skel="quadrant"` 骨架 span） |
| `web/templates/macro_cn.html` | 在 `#cn-quadrant` 之后新增 `#cn-matrix`（中国页原本就没有骨架，容器内不放） |
| `web/static/macro.js` | 新增 `QUAD_CELLS` + `quadrantMatrixHtml(curKey, curLabel, ax)`；`renderRegime()` 里写 `#regime-matrix` |
| `web/static/macro_cn.js` | 同源复制这两个（互指注释写明"改一处必须同步"）；口径按中国页传入 |
| `web/static/style.css` | 新增 `.regime-matrix` / `.rm-axis` / `.rm-axis.rm-hd` / `.rm-cell` / `.rm-cell.is-now` / `.rm-skel`（**全部新类名**，`.mac-*` 一行未动） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 新增 `QM-*` 断言组（33 条）+ 主流程注册调用 |
| `docs/frontend-structure.md` | 两页模块清单补 `#regime-matrix` / `#cn-matrix`；§5.2 补 `QUAD_CELLS` 说明；§7 新增第 13 条硬约束；§6 行号区间同步 |
| `docs/pitfalls.md` | 新增「Playwright mock 的三类假红/假绿」节（4 条） |
| `docs/architecture.md` | 决策表追加 1 行 |

**零改动已核实**：`web/app.py`、`src/**`、`tests/**`、`web/static/app.js`、`chart-crosshair.js`、
`_sidebar.html` / `_topbar.html`、`index.html`。

## 3. 设计要点（为什么是矩阵）

数据只有**两个二元离散量**（`inflation_axis` = up/down、`growth_axis` = expanding/contracting）：

- ❌ 散点/定位图：假装连续，点的位置暗示并不存在的精度
- ❌ 雷达图/条形图：表达不了"两轴交叉"这个核心语义
- ✅ 2×2 矩阵 + 当前格高亮：与数据形态一一对应，**位置本身就是信息**

排列固定为教材口径：**横轴 = 通胀（左低右高）、纵轴 = 增长（上高下低）**。
四格名称取自服务端共享字典 `QUADRANTS`（`src/econ_fetcher.py:192`，两页共用）：

| 位置 | 组合 | key | 名称 |
|---|---|---|---|
| 左上 | 通胀↓ + 增长↑ | `goldilocks` | 复苏 |
| 右上 | 通胀↑ + 增长↑ | `reflation` | 再通胀 |
| 左下 | 通胀↓ + 增长↓ | `deflation` | 通缩衰退 |
| 右下 | 通胀↑ + 增长↓ | `stagflation` | 滞胀 |

- **当前格文案恒用服务端 `quadrant_label`**，本地 `QUAD_CELLS.label` 只兜底另外三格 ⇒ 后端改文案时
  当前格永不漂移；另三格若漂移会在 `QM-2`/`QM-2c` 上暴露。
- **无 quadrant 时四格照常渲染、一个都不高亮**（容器加 `is-unknown`，格子 55% 透明度）⇒ 高度恒定不跳变。
- 轴标签**按页传入**：`/macro` = `通胀 ↓/↑` + `增长 ↑/↓`；`/macro/cn` = `通胀 回落/上行` + `增长 扩张/收缩`
  —— 中国页增长轴是 **PMI 与 50 比较的水平口径**，写箭头会误导（`QM-2d` 专门断言中国页**不得**出现 ↑/↓）。

## 4. 验证

| 项 | 结果 |
|---|---|
| V0 语法 | `node --check macro.js` / `macro_cn.js` ✔、`py_compile verify_ui.py` ✔ |
| V1 后端契约单测 | `pytest tests/test_web.py` **120 passed** |
| V2 视觉复核（两页 × 双主题 × 1440/375） | 4 格齐全、当前格高亮、轴标签按页正确、**零横向溢出**；双主题自动跟随（light `--bg-elevated` = 白、dark = `#111827`） |
| V3 **QM 组红跑**（HEAD 隔离副本 `git archive` + venv junction） | **25 FAIL / 8 PASS**（带 `QM-COMPLETE` 标记） |
| V4 **QM 组绿跑** | **33 PASS / 0 FAIL**（带完成标记） |
| V5 全量 | **637 PASS / 0 FAIL**（`ALL PASSED`；0 traceback、汇总行在）|
| V6 双主题人工看图 | macro light/dark（1440）已逐张看过：格子/边框/高亮在双主题下都清晰 |

### 4.1 红跑里 8 条 PASS 的逐条归类（纪律要求）

- 7 条 `无 pageerror`（`QM-3d` ×3 / `QM-4c` / `QM-3i` ×2 / `QM-4d`）= **真不变量**（改前改后都该绿）
- 1 条 `QM-4b`「数据暂缺」文案契约仍在 = **真不变量**（正是 plan §3-1 要保的那条）

⇒ 无漏网。

### 4.2 几何实测（plan §6 的"改前要实测确认"）

| 量 | 实测 |
|---|---|
| `#regime-matrix` 尺寸 | **166 × 89**（cells 62px 宽 × 33px 高；3 行 = 表头 15.9 + 2×33.4 + 2×3 gap） |
| `#cn-matrix` 尺寸 | 宽略宽于 macro（轴文案更长），同样 89 高 |
| `.mac-regime` 行高 | **154px**（plan 预估 ~131 —— 实际由左列 hero 决定：level 32 + quadrant 17 + 6 + 10 + 89） |
| 矩阵下沿超出父级 | **0px**（matrix.bottom == `.mac-regime`.bottom；祖先链 `overflow: visible` 无裁剪） |
| 375 档 | 矩阵 166px 宽、页面 `scrollWidth - innerWidth = 0`（MX-14a 同口径） |

## 5. 过程中踩到/纠正的三个问题

### 5.1 🔴 `page.route` 的 handler 写成 2 个形参 → mock 静默失效（**最贵的一个**）

我为了固定 body 写了 `lambda r, b=cn_body: r.fulfill(...)`。Playwright Python 见到 handler **有 2 个形参**时
会按 `(route, request)` 调用 ⇒ `b` 收到的是 **Request 对象**、`json.dumps` 抛 `TypeError`，
**且异常不在回调里当场报**，要到之后某个 API 调用处才重抛（本次在 `wait_for_function` 处抛
`TypeError: Object of type Request is not JSON serializable`）。

症状极具误导性：CN mock 用例**全红**，看起来像"mock 没生效 / 页面拿不到数据"，我先怀疑了路由 pattern、
响应体字段、页面等待条件，最后靠"单跑能成、在套件里不成"的对照才定位到**回调签名**。
**修法**：工厂返回单参函数（`def _mk(body): def _route(route): ...; return _route`）。已写入 pitfalls。

### 5.2 🟡 等待条件等错了对象（壳 vs 值）

CN 用例改对了 mock 后仍红：我等的是"`#cn-matrix .rm-cell` 出现 4 个"，但**四格在首帧（数据未到）就已渲染**
⇒ 立刻返回、拿到空态。改成等**值**（`#cn-level === 期望 label`）后即绿。已写入 pitfalls。

### 5.3 🟡 缩略截图让我误判"底行被裁"

元素截图在缩略阅读下，格子底部的 1px 边框极易被看成一条裁剪线，我据此报告了"底行被裁"。
随后用几何量（`matrix.bottom - container.bottom == 0`、`scrollHeight == clientHeight`、
祖先链 `overflow`）证伪，并用 **DPR=2 特写**才看清格子完整。
**副产品**：特写暴露了两个**真**问题——① 列头（通胀 ↓/↑）与格子的列未对齐（`.rm-axis` 是"行标签靠右"的对齐，
用在列头上会偏）→ 新增 `.rm-axis.rm-hd`（居中）；② 「通缩衰退」4 字在 `padding: 7px 0` 下**顶满格子** →
改 `padding: 7px 6px`（矩阵宽 142 → 166）。**判据已写入 pitfalls**：裁剪类问题量几何，视觉质量问题看图（且看 DPR=2）。

### 5.4 🟡 骨架尺寸要与渲染后等高

`min-height: 74px` 是我按 plan 抄的估值，实测渲染后是 **89px** ⇒ 骨架比真身高 15px、数据到达时会跳。
改成 `.rm-skel { height: 89px; width: 166px }` + 容器 `min-height: 89px`（加载期与渲染后**零跳变**）。

### 5.5 一次"自己漏接线"

首轮全量跑出 **604 PASS / 0 FAIL**，但 **QM 组 0 条** —— 我把断言函数写好了却**忘了在主流程注册调用**。
教训：新断言组加完后，先确认它在全量日志里真的出现了（本次靠"分组计数"发现，`grep -c '^  PASS  QM-' == 0`）。

## 6. 全量结果与基线比对

| 轮次 | 结果 | 说明 |
|---|---|---|
| 当日基线（改动前，上游健康） | **604 PASS / 0 FAIL**（`ALL PASSED`） | 与 09-17 的 12 条常红不同：**上游此刻完全正常**（Yahoo/BLS/AkShare 都通，Firefox 组也过） |
| 全量（未注册 QM 的那次） | 604 / 0 | QM 组 0 条 ⇒ 无效，已修（见 §5.5） |
| **全量（最终）** | **637 PASS / 0 FAIL**（`ALL PASSED`） | 637 = 604 + 33（QM 组）；0 traceback、汇总行在 ⇒ 跑完 |

**新增红 0**：与当日基线集合差为空（基线本身 0 条，最终也 0 条）。
今日上游健康 ⇒ **没有出现 09-17 那批 12 条常红**；那批（`MX-6/9/11/11b/7/8/13`、`M-4/5`、`XC-0`、`N-12a/b`，
登记于 `docs/system-overview.md` §9 G8）属间歇性环境项，与本轮改动无关（本轮不触这些面板）。

## 7. 下次注意

1. **Playwright route handler 只写 1 个形参**（工厂函数固定 body），否则 mock 静默失效且报错点离谱。
2. **等"值"不等"壳"**：新增的容器/骨架往往在首帧就存在，等元素存在会立刻返回空态。
3. **新增断言组必须确认在全量日志里出现**（分组 `grep -c`）。
4. 视觉质量问题只看 **DPR=2 特写**；裁剪/溢出类一律量几何。
5. 往高度敏感的块里加内容（这里是宏观页一级块，`.mac-regime` 行高由左列 hero 决定），
   先量几何再决定骨架尺寸，避免加载期跳变。

## 8. 提交清单

```
web/templates/macro.html
web/templates/macro_cn.html
web/static/macro.js
web/static/macro_cn.js
web/static/style.css
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
docs/frontend-structure.md
docs/pitfalls.md
docs/architecture.md
skills/ui-verify-assertion/SKILL.md          ← 见下方说明（超出 plan §9 的 1 个新增文件）
tasks/2026-09-18-macro-quadrant-matrix/plan.md
tasks/2026-09-18-macro-quadrant-matrix/journal.md
```

**超出 plan §9 的 3 项，逐条说明**：

- `docs/pitfalls.md` / `docs/architecture.md`：plan §9 未列，但 `AGENTS.md` 明令"任务完成后提取可复用规则追加到
  `docs/pitfalls.md` 或 `AGENTS.md`"，且历史几轮提交都含这两处 ⇒ 按惯性入列。
- `skills/ui-verify-assertion/SKILL.md`（**新增文件**）：`AGENTS.md` 的 `skills/` 定位是"可复用流程"，
  本轮这套"新增断言组 + HEAD 隔离红跑 + 完成标记判读 + 全量集合比对 + Playwright mock 三坑"
  已是**第 5 次重复**（`NA-*`/`UX-*`/`PW-*`/`QM-*`）⇒ 沉淀成 skill。**这是本轮唯一新增的能力性文件，
  如认为超范围可直接从提交里剔除**（它不影响任何源码路径）。

⚠️ 用 `git add <具体路径>`，**不用** `-A`；**不混入**工作区里未提交的 `docs/user-guide.md`（上一轮独立改动）。
