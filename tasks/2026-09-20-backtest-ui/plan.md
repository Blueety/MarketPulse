# 方案：回测 UI（把 backtest 搬到看板）

> **任务档**：`tasks/2026-09-20-backtest-ui/`
> **P1 第 1 个**（P0 四项已闭环：鉴权 / G1 凭据 / 验收分层 / pathspec 修复）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 18:5x，本机直连。
>
> ⚠️ 本文档作者是架构师，**不直接改项目代码**。`web/**`、`src/**` 的改动由执行者实施。
>
> **状态（2026-09-20 18:5x）：定稿，可交付执行者实施。** §10 四项已裁定
> （**D-1=A / D-2=A / D-3=A / D-4=A**，用户原话「都按你的推荐来」），
> 且**确认 scope 收窄**：本轮只做「把现有回测结果呈现出来」，**不做**页面上实时调阈值参数（§9）。
> **实施顺序**：Step 1（搬迁，零行为改动）→ Step 2（端点）→ Step 3-4（页面）→ Step 5（nav 三处）→ Step 6（断言）。
> **Step 1 不可跳过、不可与后续步骤合并** —— 它是后续一切的地基，且它的正确性判据（10 条测试 + md diff 为空）是独立的。

---

## 0. 结论先行

1. **缺口是"闭环断了"**：项目有 27 期动态阈值、2675 行历史、`check_breach` 单一事实来源、
   一份完整的回测脚本（7 标的多指标），但**结果只落在 `reports/backtest_report.md`**——
   **看板上看不到**。用户改了 `config.json` 的阈值，**没有任何地方能告诉他"改完历史上会怎样"**。
2. **实测耗时 0.897s**（266 有效交易日 / 309 触发事件 / 7 标的）⇒ **可实时算，不需要预计算落盘**。
   这一点很关键：它让本任务的架构**极简**（无需新增数据文件、无需 cron）。
3. 🔴 **本任务的核心价值决定了"不能缓存"**：该功能的意义就是「**改阈值 → 立刻看历史表现**」。
   若加长 TTL，用户改完 `config.json` 却看到旧结果 ⇒ **功能价值归零**。故推荐**不缓存**（前端给 loading 态）。
4. **推荐把纯统计函数搬到 `src/backtest.py`**（方案 C），而非让 web 直接 import `scripts/`。
   依据是**既有先例**：`src/timeline.py` 就是这个模式 —— 纯逻辑进 `src/`，`scripts/` 只留入口。
5. ⚠️ **新增页面 = 第 5 份 shell JS 副本**（主题/抽屉/市场状态）。这是**已知且有意**的复制成本
   （见 `docs/frontend-structure.md` §7-4），但**第 5 次复制**意味着该考虑抽取了（§10 D-3）。
6. ⚠️ **navCount 写死在 3 处**（`verify_ui.py` 的 `F-5:1027` / `CN-7:2038` / `TL:3851`），
   加 nav 项必须三处同改 —— 这是历史踩过的坑。

---

## 1. 任务目标

**Goal**：把 `scripts/backtest.py` 的回测结果做成看板页面，让「调阈值 → 看历史表现」闭环。

验收标准：

1. 新增页面可看：每标的的**告警次数 / 年化频率 / WARN-ALERT 分布 / 有效触发率 / 1·3·5·10 日后效（均值+胜率+n）**
2. 页面明示**当前生效的阈值口径**（动态/固定、回看窗口、k 因子、回退阈值）—— 不写清就无法解读
3. 页面明示**方法学边界**（照 md 报告「方法说明」7 条，含"胜率=方向延续占比"这类易误读项）
4. 改 `config.json` 后刷新页面**能立即看到变化**（⇒ 不缓存或短 TTL）
5. 既有 `verify_ui.py` 断言**零新增失败**（含 navCount 三处同改后仍绿）
6. `pytest tests/` 无新增失败

---

## 2. 实测取证（Step 0，已完成）

### 2.1 回测脚本现状

| 项 | 实测 |
|---|---|
| 规模 | `scripts/backtest.py` **370 行** |
| 纯函数 | `collect_triggers` / `forward_stats` / `effective_trigger_rate` / `annualized_frequency` / `load_backtest_history` / `_effective_trading_days` / `_effective_points` |
| 渲染 | `render_report`（→ md）/ `print_summary`（终端） |
| 常量 | `BACKTEST_SYMBOLS = ["VIX","VXN","MOVE","GSPC","IXIC","SH","SZ"]`（**7 个**）、`HORIZONS = (1,3,5,10)` |
| **数据源** | `load_backtest_history()` 默认走 `load_history()` = **已迁移的 SQLite**（`data/history.json` 只是 09-12 旧快照，仅供 `--history` 演练） |
| **耗时** | **0.897s**（内部计时；含 Python 启动 2.26s） |
| 本次跑出 | 266 有效交易日 / 309 触发事件 / 7 标的全有数据 |

> 📌 顺带更正：`AGENTS.md` 写 backtest「只读 `data/history.json`」**已过时**（实际读 db）。

### 2.2 报告结构（= API 字段设计依据）

**全局**：运行日期、数据窗口、有效交易日、动态阈值参数（启用?/回看窗口 20/k 因子 2.0）、各标的回退阈值表

**每标的**（7 个）：
```
回退阈值(%) · 阈值模式分布(dynamic N / fixed N) · 有效点 N · 告警次数 · 年化频率(次/年)
· WARN/ALERT 分布 · 有效触发率(%)
· 后效表：4 窗口 × (平均收益% / 胜率 / 样本数 n)
```

**总览对比表**：7 行 × 8 列（标的/告警次数/年化/有效触发率/1·3·5·10 日平均后效）

**方法说明**（7 条，含易误读项）：
- 触发检测用**生产 `check_breach`**（严格大于、动态阈值按 `history[:i]` 排除当日）
- 胜率 = 前向收益与**告警当日变化率同号**（方向延续）占比 —— ⚠️ **不是"预测准确率"**
- 有效触发率 = 触发后 5 个交易日内出现任意单日 |变化率| ≥ 1.0%
- 后效 = 点对点收益，**缺口不阻断**；窗口不足的样本不计入（n 透明展示）
- 年化 = 告警次数 / 有效跨度天数 × 365

### 2.3 工程约束（决定实现细节）

| 项 | 实测 | 影响 |
|---|---|---|
| `scripts/` 可 import? | **无 `__init__.py`** ⇒ 隐式命名空间包；`python -m scripts.sync_econ_calendar` 能跑 ⇒ 根在 `sys.path` | `from scripts.backtest import ...` **理论上可行**，但见 §3.2 选型 |
| `_ASSET_FILES` | `("style.css","app.js","macro.js","chart-crosshair.js","macro_cn.js","timeline.js")` | **新增 `backtest.js` 必须登记**，否则验证吃旧副本 |
| navCount 断言 | `verify_ui.py` 的 **`F-5:1027`**、**`CN-7:2038`**、**`TL:3851`** 三处写死 `== 11` | 加 nav 项 ⇒ **三处同改** |
| shell 副本 | 现有 **4 份**（`app.js`/`macro.js`/`macro_cn.js`/`timeline.js`）各含主题/抽屉/市场状态 | 新增页面 ⇒ **第 5 份** |

---

## 3. 方案选型

### 3.1 数据获取：可实时算（不需要预计算）

| 方案 | 评价 |
|---|---|
| **A. 实时算（推荐）** | 0.897s ⇒ 可接受；**无需新增数据文件、无需 cron、无需落盘**；`config.json` 改动**立即可见** |
| B. 预计算落盘（如 `data/backtest.json` + cron） | ❌ 过度工程：为一个 0.9s 的计算引入文件 + cron + 缓存失效问题 |
| C. 解析 `reports/backtest_report.md` | ❌ 脆弱（依赖 md 格式），且 `reports/` 被 `.gitignore` 排除 |

**选 A**。0.897s 的关键意义是：**本任务不需要任何新持久化**。

### 3.2 统计逻辑放哪（关键架构决策）

| 方案 | 做法 | 评价 |
|---|---|---|
| A. web 直接 `from scripts.backtest import ...` | 零搬迁 | 违背分层：`scripts/` 的定位是**独立入口脚本**（`AGENTS.md`）；且 `scripts/` 非包（无 `__init__.py`），依赖隐式命名空间包的脆弱行为 |
| **C. 新建 `src/backtest.py`，纯函数搬过去（推荐）** | `scripts/backtest.py` 改薄，只留 CLI + md 渲染 + `from src.backtest import ...` | ✅ **与既有先例一致**：`src/timeline.py`（纯逻辑在 src/）+ `scripts/sync_econ_calendar.py`（入口）；单一事实来源；web 与 CLI 共用同一份计算 |
| B. 在 `web/app.py` 里重写统计 | ❌ **同一算法两份实现** ⇒ 必然漂移（本项目的头号禁忌） |

**选 C**。搬迁的函数：`collect_triggers` / `forward_stats` / `effective_trigger_rate` /
`annualized_frequency` / `load_backtest_history` / `_effective_trading_days` / `_effective_points`
以及常量 `BACKTEST_SYMBOLS` / `HORIZONS`。
留在 `scripts/`：`render_report`（md 渲染）/ `print_summary` / `main`（CLI 参数与退出码）。

⚠️ **搬迁的铁律**：`scripts/backtest.py` 必须改为 `from src.backtest import ...`，
**不得保留第二份实现**。`tests/test_backtest.py`（10 条）是这次搬迁的**回归护栏** ——
它们当前 import 的路径要同步更新，但**断言语义零改动**。

### 3.3 页面 or 模块

| 方案 | 评价 |
|---|---|
| **A. 独立页面 `/backtest`（推荐）** | 内容量大（7 标的 × 8 指标 + 后效表 + 口径说明），需要独立空间；回测是"分析工具"，与看板"当前状态"性质不同 |
| B. 首页新卡片 | ❌ 首页 `.dash` 四行栅格已满载，且 `scrollHeight ≤ 1240` 是硬护栏（Bento 重构的核心指标），加卡片必破 |
| C. 挂 `/timeline` 区块 | ❌ 语义不搭（timeline = 事件日历；回测 = 告警阈值评估），且会把该页撑得很长 |

**选 A**。代价明确：+1 nav 项（三处 navCount）+ 第 5 份 shell JS 副本。

### 3.4 缓存策略（本任务的价值观决策）

| 方案 | 评价 |
|---|---|
| **A. 不缓存，实时算（推荐）** | 功能的**核心价值**就是"改阈值→立刻看效果"；0.897s 可接受；前端给 loading 骨架（页已有 `.skeleton` 体系） |
| B. TTL 6h（照 `/api/econ`） | ❌ 用户改完 `config.json` 看不到变化 ⇒ **功能价值归零** |
| C. TTL 5min | 折中，但仍会产生"我改了怎么没变"的困惑 |

**选 A**。若将来性能成为问题，再加"按 `config.json` mtime 失效"的缓存（不是定时 TTL）。

> ⚠️ **这条要在 plan 里留痕**：为什么这个端点**故意不缓存**（与项目其他端点相反）。
> 否则后人看到"别的端点都有 TTL，这个没有"，会当成遗漏给补上 —— 那就把功能价值补没了。

---

## 4. 涉及文件清单

### 新增

| 文件 | 内容 |
|---|---|
| `src/backtest.py` | 从 `scripts/backtest.py` 搬迁的纯统计函数 + 常量（**唯一实现**） |
| `web/templates/backtest.html` | 页面模板（含 head 主题内联脚本 —— **第 5 处**同源） |
| `web/static/backtest.js` | 页面业务脚本（含 shell 逻辑 —— **第 5 份副本**） |
| `tasks/2026-09-20-backtest-ui/verify_backtest.py`（可选） | 若断言量大，可先落独立 runner 快速迭代，最终并入 `verify_ui.py` |

### 修改

| 文件 | 改动 |
|---|---|
| `scripts/backtest.py` | 改薄：纯函数改为 import，保留 `render_report` / `print_summary` / `main` |
| `web/app.py` | ① 新增 `GET /api/backtest`（**不缓存**）；② 新增 `GET /backtest` 路由；③ `_ASSET_FILES` 加 `backtest.js` |
| `web/templates/_sidebar.html` | 新增 nav 项「阈值回测」（**跨页链接，不写 `data-target`** —— 照 `/macro` `/timeline` 的注释纪律） |
| `web/static/style.css` | 新增 `.bt-*` 段（表格/指标卡/口径区），**不改任何既有 `.mac-*` `.tl-*` `.dash-*` 声明** |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | ① **navCount 三处** `11 → 12`（`F-5:1027` / `CN-7:2038` / `TL:3851`）+ 补 `navDisabled` 说明；② 新增 `BT-*` 断言组 |
| `tests/test_backtest.py` | import 路径随搬迁更新（**断言语义零改动**） |
| `tests/test_web.py` | 新增 `/api/backtest` 与 `/backtest` 的契约用例 |
| `docs/commands.md` | 补新端点/页面 + 「改阈值后怎么验」 |
| `docs/frontend-structure.md` | 页面数 4→5、API 数 +1、**shell 副本 4→5**、§7 硬约束补 navCount 现在是 **三处 `== 12`** |
| `docs/system-overview.md` | §2.4 页面/端点表 + 模块清单加 `src/backtest.py` |
| `AGENTS.md` | 更正 backtest 行「只读 `data/history.json`」→ 实际读 db；补「纯逻辑在 `src/backtest.py`」 |

### 不动

`src/git_ops.py` · `src/fetcher.py` · `check_breach` 的任何语义 · `_DATA_PATHS` ·
`reports/`（仍由 CLI 写）· 三个报告入口

---

## 5. 实施步骤（每步可独立验证）

### Step 1 — 先搬迁纯函数（**零行为改动**）

- 新建 `src/backtest.py`，把 §3.2 列的函数**逐字搬过去**（含 docstring）
- `scripts/backtest.py` 改为 import，删掉原定义
- 验证：`pytest tests/test_backtest.py -v` ⇒ **10 条全绿**（这是搬迁正确性的唯一判据）
- 验证：`venv/Scripts/python scripts/backtest.py` ⇒ 输出与 §2.1 实测**逐行一致**（md 报告 diff 为空）

> ⚠️ **不要顺手重构**：搬迁就是搬迁。函数体一个字符都不改，否则回归判据失效。

### Step 2 — 新增 `/api/backtest`

- 组装 payload（字段照 §2.2）：`as_of` / `window` / `stats`（有效交易日、触发总数）/
  `threshold_config`（动态启用、回看窗口、k 因子、回退阈值表）/ `symbols[]`（每标的全套指标 + 后效）/
  `methods[]`（口径 7 条）
- **不缓存**（§3.4），`?refresh` 参数无需实现（本来就不缓存）
- 失败语义照项目惯例：**恒定 HTTP 200 + 空结构降级**（数据不足 <30 天 ⇒ `symbols: []` + 提示文案）
- 验证：`curl -s localhost:PORT/api/backtest | python -m json.tool | head -40`

### Step 3 — 页面骨架（照 `/timeline` 抄）

- `backtest.html`：`{% include "_topbar.html" %}` + `_sidebar.html`（传 `active_page="backtest"` / `base_prefix="/"`）
- ⚠️ **head 主题内联脚本是第 5 处同源**（`frontend-structure.md` §7-1）：必须与另外 4 处语义一致
- 页面区块：① 概览条（数据窗口/有效交易日/触发总数/阈值口径）② 总览对比表（7×8）
  ③ 每标的详情（可折叠 `<details>` 或 tab）④ 口径与来源（照 `/timeline` 的 `.tl-honest` 模式）+ 失败条
- 验证：页面能开、无 console error、骨架屏在 loading 时可见

### Step 4 — `backtest.js`（含第 5 份 shell 副本）

- shell 部分（`getTheme`/`applyTheme`/`MARKET_SESSIONS`/`marketSessionOf`/`updateMarketStatus`/`bindShell`）
  **逐字复制**自 `timeline.js`，**并加互指注释**（"改一处必须五页同改"）
- 业务部分：`getJSON`（AbortController 20s）→ 渲染总览表 + 详情 + 口径
- ⚠️ 数值渲染纪律（照 `timeline.js`）：**方向判色按四舍五入后的值**（`|v| < 0.005` 不写符号不染色）；
  **后效为负是正常的**（告警后下跌 = 有效），**不要**把负值染成"坏"
- ⚠️ 涨跌色遵守中国习惯：**红涨绿跌**（`--red`/`--green`）

### Step 5 — nav + navCount 三处

- `_sidebar.html` 加项（**跨页链接，不写 `data-target`**；位置建议放「市场日历」之后、「设置」之前）
- `verify_ui.py` **三处** `navCount` `11 → 12`：`F-5:1027`、`CN-7:2038`、`TL:3851`
- ⚠️ 漏改任何一处 ⇒ 该断言变红，且**看起来像"新页面改坏了侧栏"**

### Step 6 — 断言与验证

- `verify_ui.py` 新增 `BT-*` 组，建议覆盖：
  - `BT-1` 页面可开 + 概览条字段非空
  - `BT-2` **总览表行数 == API `symbols` 长度**（三方对账：API vs DOM）
  - `BT-3` 数据与 CLI 同源：`GET /api/backtest` 的某标的告警次数 == 跑 `scripts/backtest.py` 解析 md 的同名数值
    （**独立口径对打**，不复用被测代码）
  - `BT-4` 后效为负时**不渲染成"失败"色**（防把正常语义染错）
  - `BT-5` 数据不足时显示空态文案而非崩（mock 空 payload）
  - `BT-6` 五视口无横向溢出（含 `900×800` 这个既有坏带）
  - `BT-7` nav 项 12 且新项 active 正确

---

## 6. 验证命令

```bash
# ① 搬迁正确性（Step 1）
venv/Scripts/python -m pytest tests/test_backtest.py -v
venv/Scripts/python scripts/backtest.py          # 与搬迁前输出逐行比对

# ② 新端点契约（Step 2）
venv/Scripts/python -m pytest tests/test_web.py -v -k backtest
curl -s localhost:PORT/api/backtest | python -m json.tool | head -40

# ③ 全量单测（提交前）
venv/Scripts/python -m pytest tests/ -q

# ④ UI 验收（改前端后必跑；前台 + timeout 600000，约 5 分钟）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --strict
```

> ⚠️ 验收脚本现在是**三态**（`PASS/FAIL/SKIP`，第四个 P0 任务的产物）：
> 看到 `SKIP` 先读 `上游探测:` 行 —— 本页面**不依赖上游**（只读 db），所以**不该出现 SKIP**；
> 若出现，说明探测或依赖标记有问题，要查。要"零未判定"就加 `--strict`。

---

## 7. 风险评估

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 搬迁时"顺手重构"导致 `test_backtest.py` 的 10 条失去回归意义 | 高 | Step 1 明确"逐字搬、不重构"；md 报告 diff 必须为空 |
| **R2** | 统计逻辑出现**两份实现**（web 重写） | 高 | §3.2 选 C；评审时 grep `collect_triggers` / `forward_stats` 的定义处必须只有 1 个 |
| **R3** | navCount **漏改一处**（三处写死） | 中 | Step 5 点名 `F-5:1027` / `CN-7:2038` / `TL:3851` |
| **R4** | 忘记登记 `_ASSET_FILES` ⇒ 验证吃旧副本（改动"不生效"） | 中 | Step 4 明确；`frontend-structure.md` §7-3 已有此坑 |
| **R5** | 第 5 份 shell 副本漏同步某处 ⇒ 主题/抽屉在这个页面行为不一致 | 中 | Step 4 要求逐字复制 + 互指注释 |
| **R6** | **把"后效为负"染成坏色**（语义误读：告警后下跌恰恰是"有效"） | 中 | `BT-4` 断言锁住；plan 明写"负值是正常语义" |
| **R7** | 后人看到"别的端点有 TTL、这个没有"，补上缓存 ⇒ **功能价值归零** | 中 | §3.4 明确"故意不缓存"+ 理由，写进 API docstring 与文档 |
| **R8** | 0.897s 在弱机器/数据增长后变慢，页面卡顿 | 低 | 前端 loading 态 + 报告耗时；数据量是 266 交易日级别，增长缓慢 |
| **R9** | 误把"胜率"当"预测准确率"呈现（方法学误读） | 中 | 口径区必须含 md「方法说明」的 7 条原文；不得改写措辞 |

---

## 8. 预计影响的文件范围

| 类别 | 数量 |
|---|---|
| 新增源码 | 1（`src/backtest.py`，搬 ≈200 行） |
| 新增前端 | 3（模板 + `backtest.js` + `style.css` 的 `.bt-*` 段 ≈120 行） |
| 修改后端 | 1（`web/app.py`：+1 端点 +1 路由 +1 登记） |
| 修改既有 | 3（`scripts/backtest.py` 改薄 / `_sidebar.html` +1 项 / `verify_ui.py` 三处 navCount + `BT-*` 组） |
| 测试 | 2（`test_backtest.py` 路径、`test_web.py` 新用例） |
| 文档 | 4（`commands.md` / `frontend-structure.md` / `system-overview.md` / `AGENTS.md`） |
| **不动** | `check_breach` 语义 · `_DATA_PATHS` · 三入口 · `reports/` 产物格式 |

---

## 9. 明确不做

- ❌ **不引入任何新持久化**（不落 `data/backtest.json`、不加 cron）—— 0.897s 可实时算
- ❌ **不缓存**（§3.4，故意为之）
- ❌ 不改 `check_breach` / 阈值算法 / 统计口径（**只搬不改**）
- ❌ 不重写 md 报告格式（CLI 行为完全保留）
- ❌ 不做"参数可调的回测"（页面上改阈值实时回测）—— 那是**下一个任务**级别的东西，
  本轮只做"把现有回测结果呈现出来"（保持 scope 收窄）
- ❌ 不抽共享 shell（第 5 份副本沿用"复制"决策，抽取单独立项，§10 D-3）
- ❌ 不改首页 `.dash` 栅格与 `scrollHeight ≤ 1240` 护栏

---

## 10. 决策裁定（2026-09-20 18:5x，用户已确认「都按你的推荐来」= 全采纳）

| # | 议题 | 裁定 | 落地 |
|---|---|---|---|
| **D-1** | 统计逻辑落点 | ✅ **A：新建 `src/backtest.py`**，纯函数搬过去，`scripts/backtest.py` 改薄为 CLI 入口 | Step 1 |
| **D-2** | 页面形态 | ✅ **A：独立页面 `/backtest`**（+1 nav 项 / navCount 三处同改 / 第 5 份 shell 副本） | Step 3-5 |
| **D-3** | shell 第 5 份副本 | ✅ **A：照抄 + 明确记录"这是第 5 份"**（本轮不抽共享，抽取单独立项） | Step 4 |
| **D-4** | 用户可见名 | ✅ **A：「阈值回测」**；内部命名一律 `backtest`（路由 / JS / `#bt-*` / `BT-*`） | Step 5 |
| **scope** | 是否含"页面上调阈值实时回测" | ✅ **不含**（用户确认）—— 本轮只做「呈现现有回测结果」 | §9 |

### 10.1 由裁定导出的四条硬约束

1. **Step 1 必须独立完成并单独验证**：`pytest tests/test_backtest.py -v` **10 条全绿**
   **且** `scripts/backtest.py` 的 md 报告与搬迁前 **diff 为空**。两条都过才进 Step 2。
2. **搬迁禁止重构**：函数体一个字符都不改（含 docstring）。改了 ⇒ 上条判据失效 ⇒ 搬迁正确性无从证明。
3. **`src/backtest.py` 是唯一实现**：评审时 grep `def collect_triggers` / `def forward_stats` /
   `def effective_trigger_rate` / `def annualized_frequency` ⇒ **定义处必须各只有 1 个**。
4. **`/api/backtest` 故意不缓存**：实现时**不要**加 `_cache` / TTL（与 `/api/econ` 等端点刻意不同）。
   理由见 §3.4 —— 加缓存会让"改阈值立刻看效果"这个**核心价值归零**。

### 10.2 实施后必须验证（缺一不可）

1. `pytest tests/test_backtest.py -v`（10 条）+ `pytest tests/ -q`（无新增失败）
2. `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（**前台 + timeout 600000**，约 5 分钟）
   ⚠️ navCount 三处已改 `== 12`；本页面**不依赖上游** ⇒ 预期 **0 SKIP**（出现 SKIP 要查依赖标记）
3. 人工：改一次 `config.json` 的某个阈值 → 刷新 `/backtest` → **数值应随之变化**（验证"不缓存"落地）

---

## 11. 一句话

**这个任务之所以简单，全靠一个实测数字：0.897s。** 它让整个功能**不需要任何新的持久化、cron 或缓存**——
而"不缓存"恰恰是这个功能的价值观所在（改完阈值要立刻看到效果）。
唯一的真实成本是**第 5 份 shell 副本**和**三处写死的 navCount**。
