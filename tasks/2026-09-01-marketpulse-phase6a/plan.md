# 实施计划 — MarketPulse 六期 A「美股大盘监控」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase6a/prd.md`

## 任务概要

- **目标**（引用 PRD Goal）：在现有 VIX/VXN/MOVE 波动率监控基础上，新增美股大盘（标普 500 `^GSPC`、纳斯达克 `^IXIC`），日报扩为「美股大盘 + 波动率指数」两板块，告警/历史/context 同步扩展，经 QQ 统一推送。A 股留到六期 B。
- **Python 侧职责**：`SYMBOLS` 3→5；新增大盘趋势（连续涨跌天数）纯逻辑；日报/快照渲染拆两板块；告警阈值 GSPC ±4% / IXIC ±4.5%；history/context 扩展字段；零新依赖，全部走 Yahoo。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，更新后 113 + 新增）
  - `venv/Scripts/python daily_report.py` / `snapshot_report.py`（两入口手动矩阵）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| SYMBOLS 注册表 | `src/fetcher.py` 三键 `VIX/VXN/MOVE`（label/source/ticker），`fetch_all()` 遍历 SYMBOLS，源间 sleep(2s) | 
| 大盘数据的天然透传点 | `daily_report.py` 的 history record 用 `{k.lower(): values[k] for k in SYMBOLS}` 构造、`save_last_values` 按非 None 值全量写、`collect_breaches`/`check_breach` 用 `.get()` 容忍缺失——**SYMBOLS 扩到 5 后这些点零改动自动生效** |
| **大盘状态分类缺口** | `build_statuses` 对非 MOVE 指数一律 `classify_vix`（20/30 阈值）——GSPC 5000 点会被判「恐慌」；`check_breach` 的 level 同路径（`(classify_move if MOVE else classify_vix)`）——大盘触发必然升级 ALERT。**必须为大盘指数单独定义状态/级别语义** |
| `build_statuses` 索引方式 | `values[sym]` 直接索引（3 键 dict 时代成立）；`generate_context` 的 indices 推导、`render_report`/`render_snapshot` 的表格循环同样直接索引 `values[sym]`/`statuses[sym]`——**SYMBOLS 扩到 5 后，任何仍传 3 键 dict 的调用点 KeyError** |
| `load_history` 投影 | 固定返回 `{date, vix, vxn, move}` 四键——**需加 gspc/ixic（旧记录缺失 → None，向下兼容）** |
| 告警独立 | alerts.log 去重按 symbol 行式记录（`YYYY-MM-DD SYMBOL`），午盘/收盘各自 `_load_alerted`——**大盘与 VIX 天然分开记录，无需新机制** |
| 趋势图 | `render_trend_chart` 显式三面板（move/vxn/vix），与 SYMBOLS 解耦——**零改动**，PRD 要求不包含大盘 |
| 阈值配置 | 五期 `config.py`：`ALERT_THRESHOLDS` 由 `{sym: float(_CFG["alert"][sym.lower()]) for sym in SYMBOLS}` 派生——**DEFAULTS 补 gspc/ixic 键后自动接线**；用户现有 config.json 缺键由深合并补默认 |
| 既有测试 | 113 条。**受影响面**（诚实盘点，PRD「既有测试不受影响」不成立）：`test_reporter.py` 的 `sample_data`/快照 fixtures 为 3 键 dict（render 直接索引 → KeyError）、`first_run` 计数 3；`test_context.py` 全部 `TestGenerateContext` 的 values 为 3 键；`test_analyzer.py::TestHistory::test_append_and_load` 断言 `load_history` 精确四键相等。其余（alerter/config/classify/趋势图）经 `.get()` 或逐键断言天然存活 |
| 文档 | architecture.md 概览/模块表/数据流/决策表、commands.md 验证矩阵、pitfalls.md、AGENTS.md、README.md 均需同步 |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **仅加美股，A 股暂缓** — GSPC/IXIC 先行验证 Yahoo 数据质量。
2. **零新依赖** — 全部走 Yahoo Finance chart REST（现有 `fetch_vix_vxn` 直连机制）。
3. **告警独立** — 大盘与 VIX 分开记录互不干扰（alerts.log 按 symbol 去重机制已天然满足，仅需测试锁定）。
4. **向下兼容** — 日报加板块不破坏既有内容；history 新字段 optional，旧记录读为 None。
5. **context 复用 `generate_context()`** — 不新建 context_builder.py，扩展 reporter.py 既有函数。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **分组常量放 fetcher**：`STOCK_SYMBOLS = frozenset({"GSPC", "IXIC"})` 与 SYMBOLS 同处数据注册表；SYMBOLS 顺序改为 GSPC/IXIC 在前（context indices、告警收集顺序随大盘先行）；波动率组用排除法 `[s for s in SYMBOLS if s not in STOCK_SYMBOLS]` 保持 VIX/VXN/MOVE 原序 | 单处定义，analyzer/reporter 共用；顺序决定 context/告警输出顺序，大盘板块在报告前部 |
| B | **大盘趋势 = 连续同向涨跌天数（streak）**，新纯函数 `compute_streaks(values, last_values, history, date)` 返回 `{sym: signed_int}`（正=连涨、负=连跌、0=无方向），analyzer 实现可单测。方向来源：今日 `current vs last_values` + 历史相邻记录（排除 `date==今日` 行）；方向序列去尾 0 后从最后非零方向往前数连续同号 | PRD「连续 N 日涨跌，基于 history.json」；确定性、纯计算、边界可测 |
| C | **趋势状态四档标签**（`trend_label(streak, has_data)`，N=streak_days 默认 3，调用时经 `env_float("TREND_STREAK_DAYS", …)` 复核，同五期设计 A 模式）：无数据 → `数据积累中`；`streak==0` → `横盘`；`1≤\|s\|<N` → `连涨X日`/`连跌X日`；`\|s\|≥N` → `上升趋势`/`下跌趋势` | 满足 PRD「首次运行无大盘历史显示'数据积累中'」；N 配置化（`trend.streak_days`，env `TREND_STREAK_DAYS`）延续「改配置不改代码」 |
| D | **`build_statuses(values, errors, last_values=None, history=None)` 扩展**（不改签名行为，新增可选参数）：大盘指数不再走 `classify_vix`，改由 B/C 出趋势标签；`values[sym]` 改 `values.get(sym)` 容忍缺失（与 collect_breaches 一致）。波动率分支与现行为逐位一致 | 单一入口，避免调用方手工合并两个 statuses dict；可选参数使既有 3 键调用天然存活（大盘 → 数据积累中） |
| E | **`check_breach` 大盘特判**：`symbol in STOCK_SYMBOLS` 时 state=`异动`、level=**恒 `WARN`**、suggestion=`大盘指数当日波动显著，注意仓位与风险管理。`（新常量 `STOCK_SUGGESTION`）；阈值走既有 `alert_threshold()`（GSPC 4.0 / IXIC 4.5，env `ALERT_THRESHOLD_GSPC/IXIC` 覆盖） | 大盘无恐慌区间定义，不臆造分级；PRD 未要求大盘 ALERT；现 classify 路径会把 5000 点判恐慌 → 必改 |
| F | **日报/快照拆两板块**：日报标题改 `# 📊 全市场情绪日报`；`## 🌏 美股大盘`（| 指数 \| 收盘价 \| 涨跌幅 \| 趋势 \|，2 行）置于 `## 📈 波动率指数`（| 指数 \| 收盘价 \| 涨跌幅 \| 状态 \|，3 行，行格式与现版逐字一致）之前；VIX 状态行/趋势图章节/总结不动。快照同构：大盘 `| 指数 \| 当前值 \| 趋势 \|`、波动率 `| 指数 \| 当前值 \| 状态 \|` | PRD 报告结构定稿；波动率行格式不变保既有断言（如 `| VXN（科技波动） | 获取失败 | — | 获取失败 |`） |
| G | **context 扩展**：indices 自动含 5 键；`history_30d` 增 `gspc`/`ixic` 等长数组（`load_history` 投影补两键）；breach/search_keywords 机制不动。**Hermes Prompt 需同步**（context 契约新增 2 个数组 + indices 2 键——Hermes Prompt 为外部交付配置项，非仓库文件，列入交付清单） | 决策 5 约束下最小扩展；契约字段名沿用 vix/vxn/move 小写风格 |
| H | **快照入口补读 history**：`snapshot_report.py` 增加只读 `load_history()`（不写），供大盘趋势列使用——与「快照只读缓存」原则一致，不写 history/缓存 | 快照大盘行需要趋势；读操作无并发写风险 |
| I | **既有测试更新原则**：仅扩展 fixtures 到 5 键 dict / 精确断言补两键，**不断言语义**；`build_statuses`/`generate_context` 保持直接索引（fixtures 补全），不做 `.get` 降级掩盖 | 保持测试真实性；改动面收敛在 ~6 处 fixture + 1 处精确相等断言 |
| J | **交易日/节假日判断不在 Python 侧**：现状无交易日逻辑，运行时机由 Hermes cron 控制（周末不触发为调度配置）；PRD 提及的周末规则属 Hermes 侧，本次不改代码 | 零新增依赖 + 现状即如此；计划如实标注避免实施者误加逻辑 |

## config.json 结构扩展

```json
{
  "analysis": { "vix": {…}, "move": {…} },          /* 不动 */
  "alert": {
    "vix": 20, "vxn": 20, "move": 15,
    "gspc": 4, "ixic": 4.5                            /* 新增 */
  },
  "trend": { "chart_days": 30, "streak_days": 3 },    /* 新增 streak_days */
  "history": { "retention_days": 90 }
}
```

| env（最高优先级） | 覆盖路径 | 消费方 |
|---|---|---|
| `ALERT_THRESHOLD_GSPC` / `ALERT_THRESHOLD_IXIC` | `alert.gspc` / `alert.ixic` | `alert_threshold()`（调用时 + import 快照） |
| `TREND_STREAK_DAYS` | `trend.streak_days` | `trend_label`（调用时 env_float 复核） |

用户现有 config.json 缺 gspc/ixic/streak_days 键 → 白名单深合并补默认，不破坏。

## 文件清单

### 修改

| 文件 | 改动 | 预估 |
|---|---|---|
| `src/fetcher.py` | SYMBOLS 增 GSPC/IXIC（label「标普500」/「纳斯达克」、ticker `^GSPC`/`^IXIC`，置于 VIX 之前）；新增 `STOCK_SYMBOLS` frozenset | +5 |
| `src/config.py` | DEFAULTS.alert 增 gspc 4.0/ixic 4.5；DEFAULTS.trend 增 streak_days 3；ENV_MAP 增 3 项 | +5 |
| `src/analyzer.py` | 新增 `STREAK_DAYS` 常量（import 快照，来自 config）；新增 `compute_streaks`（B）与 `trend_label`（C）；`build_statuses` 扩展（D）；`check_breach` 大盘分支 + `STOCK_SUGGESTION`（E）；`build_summary` 完整性文案「三个波动率指数…」→ 两板块表述；`load_history` 投影补 gspc/ixic | +~65 |
| `src/reporter.py` | `render_report` 拆两板块（F）；`render_snapshot` 同构拆分；`generate_context` history_30d 增两数组（G） | +~25 |
| `daily_report.py` | `build_statuses(values, errors, last_values, load_history())` 传新参（供大盘趋势） | +1 |
| `snapshot_report.py` | 同上 + 只读 `load_history()`（H） | +2 |
| `tests/test_reporter.py` | `sample_data`/快照 fixtures 扩 5 键；`first_run` 计数 3→5；表格行数断言更新 | ~-2/+6 |
| `tests/test_context.py` | `TestGenerateContext` 各 values dict 扩 5 键；history_30d 断言补 gspc/ixic 数组；`clean_thresholds` 补 GSPC/IXIC | ~-0/+8 |
| `tests/test_analyzer.py` | `TestHistory::test_append_and_load` 精确相等断言补 `"gspc": None, "ixic": None` | +1 |
| `tests/test_alerter.py` | `clean_thresholds` 补 GSPC/IXIC delenv（防宿主 env 泄漏） | +2 |
| `docs/architecture.md` | 概览/数据流（5 指数两板块）/模块表/决策表补六期A 决策（大盘趋势语义、check_breach 特判、两板块渲染） | — |
| `docs/commands.md` | 验证矩阵补大盘场景（告警 ±4/±4.5、env 覆盖、两板块检查） | — |
| `docs/pitfalls.md` | 六期A 小节：大盘无恐慌区间（check_breach 必特判）、streak 语义（今日方向=current vs last_values、排除当日 history 行）、fixtures 需 5 键、build_statuses 容忍 `.get`、Hermes Prompt 契约同步 | — |
| `AGENTS.md` | 项目地图补 5 指数两板块、SYMBOLS 说明 | — |
| `README.md` | 能力一览 + 配置表补 gspc/ixic/streak_days | — |

### 新增

| 文件 | 内容 | 预估 |
|---|---|---|
| `tests/test_phase6a.py` | 新增大盘专项测试（见下「测试设计」） | ~+120 |

**不改**：`src/alerter.py`（按 symbol 分块/去重机制零改动，仅测试补 fixture）、`render_trend_chart`（三面板不动）、`requirements.txt`（零新依赖）、`.env` / `.env.example`、告警文件格式、context 五键顶层结构、Hermes cron 调度。

## 测试设计

### 既有测试更新（只扩 fixture，不动断言语义）

- `test_reporter.py`：`sample_data()` values/changes/statuses 补 `GSPC: 4500.0 / IXIC: 17500.0`（statuses 由 `build_statuses` 派生趋势标签）；快照两处 values 同理；`first_run` 断言 3→5。
- `test_context.py`：各 values dict 补 GSPC/IXIC（如 `{"VIX":21.0,"VXN":19.0,"MOVE":78.0,"GSPC":4500.0,"IXIC":17500.0}`）；`test_non_breach_day` 补 `history_30d["gspc"]` 长度断言。
- `test_analyzer.py`：`test_append_and_load` 期望 dict 补两键 None。
- `test_alerter.py` / `test_context.py` / 新增 fixture：`clean_thresholds` delenv 集合补 `GSPC/IXIC`。

### 新增 tests/test_phase6a.py

- **TestSymbols**：`SYMBOLS` 5 键、ticker 正确、顺序 GSPC/IXIC 在前、`STOCK_SYMBOLS == {"GSPC","IXIC"}`（纯常量断言，不联网）。
- **TestComputeStreaks**：
  - 无历史 → 0；历史全 None → 0
  - 历史连涨 3 日 + 今日涨 → 4；连跌同理
  - 方向反转（涨涨跌）→ 1（从最后非零方向起算）
  - 今日无方向（current==last_values）→ 从历史最近方向续算（横盘不打断）
  - 当日 history 行排除（同日重复运行场景）
- **TestTrendLabel**：无数据→`数据积累中`；streak 0→`横盘`；1/2→`连涨1日`/`连跌2日`（N=3）；3→`上升趋势`、-3→`下跌趋势`；`TREND_STREAK_DAYS=2` env → 2 即趋势（调用时复核）。
- **TestBuildStatusesStock**：大盘键为趋势标签；取数失败（value None）→ `获取失败`；不传 last_values/history（旧调用）→ `数据积累中`。
- **TestCheckBreachStock**：GSPC +4.1% 触发、+4.0% 恰好不触发（严格大于）；IXIC +4.4% 不触发 / +4.6% 触发（阈值独立）；level 恒 `WARN`（即使 +10%）；state=`异动`；suggestion 为大盘文案；`ALERT_THRESHOLD_GSPC=5` env → +4.1% 不触发。
- **TestReportSections**：日报含 `## 🌏 美股大盘` 与 `## 📈 波动率指数` 且大盘在前；大盘表 4 列（含趋势列）、波动率行格式与现版一致；快照两板块；`# 📊 全市场情绪日报` 标题。
- **TestContextStock**：indices 含 5 键；`history_30d` 五数组等长；旧记录（无 gspc 键）→ None 数组，长度仍一致。
- **TestAlertIndependence**：GSPC +4.1% 与 VIX +22% 同触发 → 告警文件两个附录块、alerts.log 两行；午盘只触发 GSPC → 收盘 GSPC 跳过但 VIX 仍可触发（大盘与 VIX 去重互不干扰）。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | fetcher：SYMBOLS + STOCK_SYMBOLS | src/fetcher.py | 顺序错乱影响输出顺序 | `venv/Scripts/python -c "from src.fetcher import SYMBOLS, STOCK_SYMBOLS; print(list(SYMBOLS), STOCK_SYMBOLS)"` |
| 2 | config：DEFAULTS/ENV_MAP 扩展 | src/config.py | 键名与消费方漂移 | `venv/Scripts/python -m pytest tests/test_config.py -v` 全绿（既有断言逐键，天然兼容） |
| 3 | analyzer：STREAK_DAYS + compute_streaks + trend_label + build_statuses 扩展 + check_breach 大盘分支 + load_history 投影 + build_summary 文案 | src/analyzer.py | streak 边界（反转/持平/当日行排除）；大盘误走 classify_vix | `venv/Scripts/python -m pytest tests/test_analyzer.py tests/test_alerter.py -v` 全绿（先跑既有，再逐步加新用例） |
| 4 | reporter：render_report/render_snapshot 拆板块 + generate_context 数组 | src/reporter.py | 波动率行格式漂移破坏既有断言 | `venv/Scripts/python -m pytest tests/test_reporter.py tests/test_context.py -v`（先更新 fixtures 再断言语义） |
| 5 | 两入口传参 + 快照读 history | daily_report.py, snapshot_report.py | 签名不匹配 | `venv/Scripts/python daily_report.py` / `snapshot_report.py` 各跑一次，日志 5 指数 |
| 6 | 既有测试 fixture 更新 + 新增 test_phase6a.py | tests/ | fixture 漏改致 KeyError | `venv/Scripts/python -m pytest tests/ -v` 全绿（113 更新后 + 新增） |
| 7 | 文档同步（architecture/commands/pitfalls/AGENTS/README） | 上述 5 文件 | 文档与实现漂移 | 逐份核对最终代码 |
| 8 | 手动验证矩阵 + 行数预算 + `git diff` 审查 | 全部 | 增量超预算 | 见下方矩阵；源码增量 ≤ ~105 行 |

### 手动验证矩阵（步骤 8，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 正常闭环 | 运行 `daily_report.py` | 日志输出 5 个指数收盘价；`reports/YYYY-MM-DD.md` 含两个板块，大盘在波动率之前；`history.json` 记录含 gspc/ixic；`context/YYYY-MM-DD.json` indices 5 键、history_30d 含 gspc/ixic 数组 |
| 大盘告警 | 备份 `data/last_values.json`，模拟 GSPC 基准 = 当前值/1.041（+4.1%），运行 `daily_report.py` | 生成 `alerts/YYYY-MM-DD-close.md`，含 GSPC 附录块（level WARN、阈值 ±4.0%）；alerts.log 记 GSPC；VIX 未异动则不触发，互不干扰 |
| env 覆盖 | `ALERT_THRESHOLD_GSPC=5 venv/Scripts/python daily_report.py`（+4.1% 模拟） | GSPC 不再告警（4.1 < 5） |
| 午盘大盘告警 | 先跑 `snapshot_report.py` 触发 GSPC 午盘告警，再跑 `daily_report.py` | 收盘跳过 GSPC，但 VIX（若异动）仍可触发——大盘与 VIX 去重独立 |
| 无大盘历史 | 首次运行（history 无 gspc/ixic） | 大盘趋势列显示「数据积累中」；不崩溃 |
| 快照两板块 | 运行 `snapshot_report.py` | 快照含大盘/波动率两板块；不写 history |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（无网络） |
| 恢复 | 恢复 `last_values.json` 原值；清理验证期告警文件 | 生产数据无残留 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| **大盘误用 VIX 分类**（5000 点判恐慌 → 告警恒 ALERT、状态列错乱） | 设计 D/E：build_statuses 大盘分支走趋势标签、check_breach 大盘恒 WARN；TestCheckBreachStock 锁定 |
| `build_statuses`/`render_*`/`generate_context` 对 3 键 dict KeyError | 设计 I：既有测试 fixtures 同步扩 5 键（~6 处），不动断言语义；prd「既有 113 不受影响」按实际情况修正为「fixture 扩展后断言不变」 |
| streak 语义歧义（反转日、持平日、当日 history 行、无基准） | 设计 B/C 精确规则 + TestComputeStreaks 六类边界锁定；写入 pitfalls |
| 用户现有 config.json 无大盘键 | 深合并补默认（4/4.5/3），TestLoadFile 模式已覆盖，无需迁移 |
| 5 指数拉取超 15s 预算 | 4 个源间 sleep(2s) = 8s + 5 次请求（本地实测单请求 <1s），预计 10-13s；若实测超预算，降低源间 sleep 为 1s（单处改动） |
| 大盘+波动率同日告警合并推送 | 告警文件按 symbol 分块机制已支持多块；推送合并为 Hermes 侧职责，Python 侧零改动 |
| context 契约变更被 Hermes Prompt 忽略 | 设计 G：Hermes Prompt 更新列入交付清单（外部配置项），AGENTS.md 契约表同步 |
| 旧 history 记录无 gspc/ixic | load_history 投影 `rec.get()` → None；趋势显示「数据积累中」直至积累 ≥2 日，PRD 向下兼容要求满足 |
| 行数超预算 | 步骤 8 `wc -l` 硬校验（源码 832 → 约 940，含 fetcher/config/analyzer/reporter 增量 ≤105） |

## 不做什么

- 不加 A 股、不加新依赖、不改 Yahoo 取数机制、不加推送逻辑。
- 不改趋势图（保持 VIX/VXN/MOVE 三面板）、不改告警文件格式/去重机制、不改 context 五键顶层结构。
- 不在 Python 侧加交易日/节假日判断（设计 J，属 Hermes cron 调度配置）。
- 不做大盘 ALERT 分级、不做大盘恐慌区间配置（无 PRD 依据）。
- 不新建 context_builder.py / 新告警文件类型 / 新配置段（复用五期基建）。
- 不改 `.env`、`requirements.txt`、Hermes cron 调度。

## 预计影响范围

- **新增文件**：`tests/test_phase6a.py`（~120）。
- **修改文件**：`src/fetcher.py`（+5）、`src/config.py`（+5）、`src/analyzer.py`（+~65）、`src/reporter.py`（+~25）、`daily_report.py`（+1）、`snapshot_report.py`（+2）、既有 4 个测试文件（fixture 扩展，断言语义不变）、docs 5 份、README。
- **不受影响**：`src/alerter.py`、`render_trend_chart`、`requirements.txt`、`.env`、告警文件/context 顶层契约结构、Hermes cron。
- **交付清单（非仓库文件）**：Hermes Prompt 同步 context 契约（indices 5 键、history_30d 增 gspc/ixic）。

## 确认

- [ ] 人已审阅计划
- [ ] 设计选择 A（分组常量）/ B（streak 计算规则）/ C（四档趋势标签 + N=3 可配）/ D（build_statuses 扩展 + 容忍 .get）/ E（大盘告警恒 WARN）/ F（两板块渲染，波动率行格式不变）/ G（context 数组扩展 + Hermes Prompt 同步）/ H（快照只读 history）/ I（既有测试仅扩 fixture）/ J（交易日判断归 Hermes）已确认
- [ ] 既有 113 条测试的实际影响面已如实标注（fixture 扩展，断言不变）
- [ ] config 扩展（gspc 4 / ixic 4.5 / streak_days 3 + env 映射）已确认
- [ ] 大盘告警恒 WARN（无恐慌区间）语义已确认
- [ ] 没有遗漏测试（符号表/streak 边界/趋势标签/大盘告警/两板块渲染/context 数组/告警独立全覆盖）
- [ ] 没有引入不必要依赖或额外配置段
