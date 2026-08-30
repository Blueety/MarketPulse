# 实施计划 — MarketPulse 七期「盘中快照扩展」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase7/prd.md`。六期 B 已落地（147 条测试全绿）。

## 任务概要

- **目标**（引用 PRD Goal）：扩展盘中快照能力，A 股/美股交易时段内各取快照，通过 Hermes cron 推送。新增创业板指数（`399006.SZ`），SYMBOLS 7→8。
- **Python 侧职责**：`snapshot_report.py` 支持 `--market a-share|us` + `--time open|midday|close|noon`（4 个 cron 各传一组参数）；创业板入 SYMBOLS/STOCK_SYMBOLS/A_SHARE_SYMBOLS（streak/趋势/休市/大盘告警自动接线）；快照存 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`；快照时复用 `run_alert_checks` 检查大盘告警（告警文件按 `{market}-{time}` 命名防与日报碰撞）；零新依赖。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，基线 147，更新后 + 新增）
  - `venv/Scripts/python snapshot_report.py --market a-share --time midday` / `--market us --time open`（快照手动矩阵）
  - `venv/Scripts/python daily_report.py`（8 指数闭环）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| SYMBOLS 注册表 | `src/fetcher.py` 7 键 GSPC/IXIC/SH/SZ/VIX/VXN/MOVE；`STOCK_SYMBOLS = {GSPC,IXIC,SH,SZ}`、`A_SHARE_SYMBOLS = {SH,SZ}`；`fetch_all()` 无参遍历全量、源间 sleep(2s)。**无市场过滤能力，需加 `market` 参数** |
| snapshot_report.py | 单入口无参数：取全量 7 指数 → 渲染三板块午盘快照（美东 12:30）→ 落盘 `YYYY-MM-DD-noon.md` → `run_alert_checks(..., "noon", path)`。**main() 无测试直接 import，改造 CLI 安全** |
| **天然透传点（零改动自动生效）** | `daily_report.py` 的 history record `{k.lower(): values[k] for k in SYMBOLS}`、`compute_streaks`/`_stock_has_data`/`check_breach`/`build_statuses`（`STOCK_SYMBOLS` 成员判定）、`alerter.collect_breaches`（遍历 SYMBOLS + `.get()` 容忍缺失）、`ALERT_THRESHOLDS` 派生 `_CFG["alert"][sym.lower()]` —— **CYB 加入三个常量 + DEFAULTS 后日报/趋势/告警/context 全部自动覆盖** |
| **必须改的点** | ① `fetch_all` 加 `market` 过滤（快照只取本市场子集）；② `render_snapshot` 需按 market 渲染单板块（现硬编码三板块 + VIX 状态行，且 `values[s]` 直接索引——缺键即 KeyError）；③ `save_snapshot` 文件名写死 `-noon.md` → 需 suffix 参数；④ `snapshot_report.py` 加 argparse + 市场日期（A 股快照不能用美东日期，见设计 B）；⑤ `config.py` DEFAULTS.alert 缺 `cyb`（**不加则 `ALERT_THRESHOLDS` import 即 KeyError**）；⑥ `load_history` 投影补 `cyb`；⑦ `generate_context` history_30d 补 `cyb` 数组 |
| **告警文件碰撞风险** | `run_alert_checks` 写 `alerts/{date}-{alert_type}.md`。若 A 股收盘快照传 `"close"`，与日报的 `alerts/{date}-close.md` **同一路径互相覆盖**（A 股收盘 15:00 与美股收盘日报不同时刻，后者会冲掉前者）。需传复合 type（设计 C） |
| **日期域问题** | 现快照一律 `get_us_eastern_date()`。A 股午盘北京 9/1 11:30 = 美东 8/31 23:30 → 文件落 `8/31` 名下，且 alerts.log 去重键会与 A 股收盘（北京 9/1 = 美东 9/1 03:00）分裂 → 同 A 股交易日午盘/收盘去重失效（设计 B） |
| **既有测试** | 147 条。**受影响面（仅夹具/常量断言，语义不变）**：`test_phase6a.py` 的 `TestSymbolsAndConfig`（`STOCK_SYMBOLS == 4 键` 精确断言——必改）、`TestReportSections`/`TestContextExtension`（values 7 键 dict，render/context 直接索引 → KeyError）；`test_phase6b.py` 的 `test_seven_symbols`/`test_stock_and_ashare_groups`（8/5/3 键断言——必改）、`Test休市`/`TestReportThreeSections`/`TestContextPhase6b`（values 缺 CYB → KeyError）；`test_reporter.py` 的 `sample_data()`/`TestSnapshot`（7 键）；`test_context.py` 各 `TestGenerateContext`（values 7 键 + history_30d 等长断言链）；`test_analyzer.py::test_append_and_load`（精确 dict 相等，补 `cyb: None`）；三处 `clean_thresholds` delenv 集合补 CYB。`test_alerter.py` 其余（`_breaching_values` 无 A 股键，`.get()` 容忍）天然存活 |
| 文档 | architecture.md（7 指数/单午盘快照）、commands.md、pitfalls.md、AGENTS.md、README.md（调度表只有 00:30 午盘 cron；目录树、测试数 147、数据流）均需同步七期 |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **4 个 cron**：A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00（北京时间）。
2. **新增创业板** `399006.SZ`，SYMBOLS 8 个，告警阈值 ±5%。
3. **扩展现有 snapshot_report.py**，不新建模块。
4. **快照存 reports/snapshots/**（`YYYY-MM-DD-{market}-{time}.md`），gitignore 已有。
5. **不做存储 cleanup**。
6. **不做报告整合**（快照独立存储）。
7. **不做快照 AI 解读**。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **CLI 与默认值**：`--market {a-share,us}` 默认 `us`、`--time {open,midday,close,noon}` 默认 `noon`；裸跑 `python snapshot_report.py` = 美股午盘快照。`--market a-share` 取 SH/SZ/CYB，`--market us` 取 GSPC/IXIC（PRD 定稿：**us 快照不含波动率**——原午盘快照的 VIX/VXN/MOVE 板块与 VIX 状态行从快照移除，波动率仅保留在日报；这是 PRD 明确的行为变更） | 每个参数组合恰好对应一个 cron，零死路径；裸跑仍可手动（架构约束"全程可手动运行"） |
| B | **快照日期 = 市场自身交易日**：analyzer 新增 `get_market_date(market)`——`a-share` 用 `Asia/Shanghai`、`us` 用美东（复用 `EASTERN_TZ`）；快照文件名、报告「日期」行（a-share 标北京时间 / us 标美东时间）、`run_alert_checks` 的 alerts.log 去重键**全部用市场日期** | ① 文件按用户认知的交易日归档（A 股 9/1 午盘不落 8/31 名下）；② 去重语义在各市场内正确：A 股午盘（北京 9/1）→ 收盘（北京 9/1）→ 日报（美东 9/1，与 A 股收盘 15:00=美东 03:00 **恒同日**）同键，午盘触发则收盘/日报跳过，同指数当日只告警一次；美股开盘（美东 9/1）→ 午盘（美东 9/1）→ 日报（美东 9/1）同理 |
| C | **快照告警文件防碰撞**：`snapshot_report.py` 传 `alert_type = f"{market}-{time}"` → `alerts/{date}-a-share-midday.md` / `-a-share-close.md` / `-us-open.md` / `-us-noon.md`；日报保持 `alerts/{date}-close.md`（**alerter.py 零改动**——alert_type 本就是字符串，frontmatter `type:` 显示复合名，对 Hermes 更明确） | A 股收盘快照与日报同用 `close` 会互相覆盖同一文件；复合名使 5 类告警路径互不冲突，Hermes 按文件名各推一次 |
| D | **兼容签名**：`render_snapshot(date, values, statuses, market=None, time="noon")`——`market=None` 保持现三板块午盘快照**逐字不变**（既有 TestSnapshot 测试零改动），cron 传 `market="a-share"/"us"` 走单板块渲染（仅大盘表 + 日期/类型行，无 VIX 状态行）；`save_snapshot(date, content, suffix="noon")`——默认名不变，入口传 `suffix=f"{market}-{time}"` | PRD「既有测试不受影响」；默认路径与生产路径分离，不产生死代码 |
| E | **创业板接线**：fetcher `SYMBOLS["CYB"] = {"label":"创业板指","ticker":"399006.SZ"}`（置于 SZ 后 VIX 前）；`STOCK_SYMBOLS` 扩 5 键、`A_SHARE_SYMBOLS` 扩 3 键；新增 `MARKETS = {"a-share": frozenset({"SH","SZ","CYB"}), "us": frozenset({"GSPC","IXIC"})}`（显式字面量，注释标明 PRD 定稿：us 仅大盘不含波动率）；config `alert.cyb: 5.0` + `ALERT_THRESHOLD_CYB` env 映射 | streak/趋势标签/休市判定/大盘告警（恒 WARN/异动）/日报 A 股板块第三行/context indices 与 history_30d 全部自动覆盖，与 6B 同机制 |
| F | **既有测试夹具扩展**：全部 values dict 7→8 键（CYB）、集合断言 8/5/3、`clean_thresholds` 补 CYB、`test_append_and_load` 期望补 `"cyb": None`——**仅扩展夹具/常量，既有断言语义不动** | 与 6B 处理模式一致；PRD「既有测试不受影响」= 语义不受影响，夹具随注册表扩展是必要配套 |
| G | **旧 noon 命名退役**：`reports/snapshots/YYYY-MM-DD-noon.md` 与 `alerts/YYYY-MM-DD-noon.md` 不再由入口产生（旧文件留盘不清理——决策 5）；Hermes Prompt 的 00:30 午盘 cron 替换为 00:00 美股午盘 cron，读取新文件名 | 命名统一 `{market}-{time}`；cron 调度整体换代，无新旧并行路径 |

## config.json 结构扩展

```json
{
  "analysis": { "vix": {…}, "move": {…} },          /* 不动 */
  "alert": {
    "vix": 20, "vxn": 20, "move": 15,
    "gspc": 4, "ixic": 4.5, "sh": 4, "sz": 4,
    "cyb": 5                                            /* 新增：创业板 ±5% */
  },
  "trend": { "chart_days": 30, "streak_days": 3 },    /* 不动 */
  "history": { "retention_days": 90 }                 /* 不动 */
}
```

| env（最高优先级） | 覆盖路径 | 消费方 |
|---|---|---|
| `ALERT_THRESHOLD_CYB` | `alert.cyb` | `alert_threshold()`（调用时 + import 快照） |

用户现有 config.json 缺 cyb 键 → 白名单深合并补默认 5.0，不破坏（与 sh/sz 同机制，无需迁移）。

## 4 个 cron 与产出文件

| 任务 | 时间(北京) | 命令 | 快照文件 | 告警文件（触发时） |
|---|---|---|---|---|
| A 股午盘 | 11:30 | `python snapshot_report.py --market a-share --time midday` | `snapshots/{date}-a-share-midday.md` | `alerts/{date}-a-share-midday.md` |
| A 股收盘 | 15:00 | `python snapshot_report.py --market a-share --time close` | `snapshots/{date}-a-share-close.md` | `alerts/{date}-a-share-close.md` |
| 美股开盘 | 21:30 | `python snapshot_report.py --market us --time open` | `snapshots/{date}-us-open.md` | `alerts/{date}-us-open.md` |
| 美股午盘 | 00:00 | `python snapshot_report.py --market us --time noon` | `snapshots/{date}-us-noon.md` | `alerts/{date}-us-noon.md` |

`{date}`：a-share 用北京时间、us 用美东时间（设计 B）。原 00:30 午盘 cron 由 00:00 美股午盘取代（设计 G）。alerts.log 去重：A 股午盘触发 → 收盘/日报跳过；美股开盘触发 → 美股午盘/日报跳过；跨市场独立（各记各的 symbol）。

## 文件清单

### 修改

| 文件 | 改动 | 预估 |
|---|---|---|
| `src/fetcher.py` | SYMBOLS 增 CYB（label「创业板指」、ticker `399006.SZ`，SZ 后 VIX 前）；`STOCK_SYMBOLS` 5 键、`A_SHARE_SYMBOLS` 3 键；新增 `MARKETS` 分组；`fetch_all(market=None)` 按市场过滤遍历（无参全量，行为不变） | +8 |
| `src/config.py` | DEFAULTS.alert 增 `cyb: 5.0`；ENV_MAP 增 `ALERT_THRESHOLD_CYB` | +2 |
| `src/analyzer.py` | 新增 `SHANGHAI_TZ` + `get_market_date(market)`（a-share→北京时间、us→美东，设计 B）；`load_history` 投影补 `cyb`（旧记录→None） | +6 |
| `src/reporter.py` | `render_snapshot` 加 `market=None, time="noon"`：None 分支原样保留，market 分支单板块渲染（A 股表含休市单元格、日期/类型行按市场+时段文案，设计 D）；`save_snapshot` 加 `suffix="noon"`；`generate_context` history_30d 增 `cyb` 数组 | +22 |
| `snapshot_report.py` | argparse（`--market`/`--time`，默认 us/noon）；main 改为市场化：`get_market_date(market)` → `fetch_all(market)` → `build_statuses` → `save_snapshot(date, content, suffix=f"{market}-{time}")` → `run_alert_checks(date, values, last_values, f"{market}-{time}", path)` | +22 |
| `tests/test_phase6a.py` | 集合断言 4→5 键、values dict 7→8 键、clean_thresholds 补 CYB、append record 补 cyb | ~-0/+10 |
| `tests/test_phase6b.py` | 集合断言 8/5/3 键、values dict 补 CYB、context/历史用例补 cyb、clean_thresholds 补 CYB | ~-0/+12 |
| `tests/test_reporter.py` | `sample_data()` 8 键、placeholder 计数 7→8、TestSnapshot values 8 键 | ~-0/+6 |
| `tests/test_context.py` | 各 values dict 补 CYB、history_30d 等长断言链补 cyb、`test_all_sources_failed` 补 None | ~-0/+10 |
| `tests/test_analyzer.py` | `test_append_and_load` 期望 dict 补 `"cyb": None` | +1 |
| `tests/test_alerter.py` | `clean_thresholds` delenv 集合补 CYB | +1 |
| `docs/architecture.md` | 概览（4 快照 cron）/模块表（snapshot_report 职责）/数据流/决策表（设计 A-G）/约束 | — |
| `docs/commands.md` | 快照命令带参数、验证矩阵补 `--market a-share/us`、创业板告警、复合告警文件断言 | — |
| `docs/pitfalls.md` | 七期小节（见风险表） | — |
| `AGENTS.md` | 项目地图：snapshot_report 描述、snapshots 文件名模式、alerts 复合名、SYMBOLS 8 | — |
| `README.md` | 能力表七期行、指数表 + 创业板 ±5%、快照章节（4 时点命令）、调度表 5 行、目录树、测试数、数据流 | — |

### 新增

| 文件 | 内容 | 预估 |
|---|---|---|
| `tests/test_phase7.py` | 七期专项测试（见下「测试设计」） | ~+130 |

**不改**：`src/alerter.py`（alert_type 字符串透传零改动）、`daily_report.py`（fetch_all() 无参 + record 派生 SYMBOLS 自动 8 键）、`seed_history.py`（键派生已含 cyb）、`render_trend_chart`（三面板不动）、`config.json`（用户文件，深合并补默认）、`requirements.txt`、`.env`、context 五键顶层结构、日报/告警既有格式。

## 测试设计

### 既有测试更新（只扩 fixture/常量断言，不动既有断言语义）

- `test_phase6a.py`：`test_symbols_order_stock_first` → `STOCK_SYMBOLS == {"GSPC","IXIC","SH","SZ","CYB"}`（`[:4]`/`[-3:]` 顺序断言天然存活）；`test_config_defaults_phase6a` 补 `alert_threshold("CYB") == 5.0`；`TestReportSections`/`TestContextExtension` values 8 键 + A 股板块含创业板行断言。
- `test_phase6b.py`：`test_seven_symbols` → 8 键（含 CYB）；`test_stock_and_ashare_groups` → 5/3 键；`test_tickers` 补 `399006.SZ`；`Test休市`/`TestReportThreeSections`/`TestContextPhase6b` values 8 键 + history record 补 `cyb` + 等长断言补 cyb 数组。
- `test_reporter.py`：`sample_data()` values/changes/statuses 补 `CYB: 10500.0 / -0.20 / ("连涨1日", ...)`；`test_no_unreplaced_placeholder` 计数 7→8；`TestSnapshot` 两处 values 8 键。
- `test_context.py`：各 values dict 补 `"CYB": 10500.0`（`test_all_sources_failed` 补 `None`）；`test_history_window_30` 等长断言链补 `cyb`。
- `test_analyzer.py`：`test_append_and_load` 期望 dict 补 `"cyb": None`。
- `test_alerter.py` / `test_context.py` / `test_phase6a.py` / `test_phase6b.py`：`clean_thresholds` delenv 集合补 `CYB`。
- `test_config.py`：`test_defaults_match_hardcoded` 补 `cfg["alert"]["cyb"] == 5.0`（可选）。

### 新增 tests/test_phase7.py

- **TestSymbolsPhase7**：SYMBOLS 8 键、前五顺序 GSPC/IXIC/SH/SZ/CYB、ticker `399006.SZ`、`STOCK_SYMBOLS` 5 键、`A_SHARE_SYMBOLS` 3 键、`MARKETS == {"a-share": {"SH","SZ","CYB"}, "us": {"GSPC","IXIC"}}`（纯常量断言，不联网）。
- **TestMarketDate**：`get_market_date("a-share")` / `("us")` 均匹配 `YYYY-MM-DD` 正则（与既有 test_format 同风格，不 mock 时钟）。
- **TestFetchAllMarket**：monkeypatch `fetch_with_retry` 返回固定值 + `sleep` no-op → `fetch_all("a-share")` 恰含 SH/SZ/CYB 三键、`fetch_all("us")` 恰含 GSPC/IXIC、`fetch_all()` 8 键（不联网）。
- **TestRenderMarketSnapshot**：`render_snapshot(date, values, statuses, market="a-share", time="midday")` → 含「A 股大盘」+ 创业板指行 + 「北京时间」+ 类型行含「午盘」，不含美股/波动率板块与 VIX 状态行；`market="us", time="open"` → 含美股大盘 + 标普/纳斯达克 + 「美东时间」+ 「开盘」，不含 A 股；`market=None` 保持三板块 + 「盘中快照（美东 12:30）」（既有测试已锁，此处补显式对照）。A 股 None 值 → 「休市」单元格。
- **TestSaveSnapshotSuffix**：`save_snapshot(date, content, suffix="a-share-close")` → `{date}-a-share-close.md`。
- **TestCYBBreach**：`check_breach("CYB", 105.1, 100.0)` 触发（+5.1% > 5.0，level WARN、state 异动、threshold 5.0）；恰好 +5.0% 不触发；`ALERT_THRESHOLD_CYB=6` env → +5.1% 不触发；CYB streak 接线（历史连涨 → 上升趋势）。
- **TestAlertFileNoCollision**（设计 C 关键用例）：同日期依次跑 `run_alert_checks(..., "a-share-close", ...)` 与 `(..., "close", ...)` → `alerts/{date}-a-share-close.md` 与 `{date}-close.md` 两文件并存互不覆盖；`us-open` 同理。
- **TestDedupMarketScoped**（设计 B）：同 key 下 A 股午盘 SH 触发 → 收盘 SH 跳过（VIX 不受影响）；US open GSPC 触发 → us-noon GSPC 跳过；跨市场独立（SH 标记不影响 GSPC）。
- **TestSnapshotEntryOrchestration**：monkeypatch `fetch_all`/`load_last_values`/`build_statuses`/`render_snapshot`/`save_snapshot`/`run_alert_checks` → `snapshot_report.main("a-share", "midday")` 返回 0，断言 `save_snapshot` 以 `suffix="a-share-midday"`、`run_alert_checks` 以 `alert_type="a-share-midday"` 被调（入口编排不联网）；默认参数解析 `us/noon`。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | fetcher：SYMBOLS + 分组 + MARKETS + fetch_all(market) | src/fetcher.py | 顺序错乱影响输出顺序；ticker 后缀笔误；无参行为回归 | `venv/Scripts/python -c "from src.fetcher import SYMBOLS, STOCK_SYMBOLS, A_SHARE_SYMBOLS, MARKETS; print(list(SYMBOLS), STOCK_SYMBOLS, A_SHARE_SYMBOLS, MARKETS)"` + TestFetchAllMarket |
| 2 | config：DEFAULTS/ENV_MAP 补 cyb | src/config.py | 键名漂移 → ALERT_THRESHOLDS import KeyError | `venv/Scripts/python -m pytest tests/test_config.py -v` 全绿 + import 冒烟 |
| 3 | analyzer：get_market_date + load_history 投影 | src/analyzer.py | 旧记录缺键；时区键名 | `venv/Scripts/python -m pytest tests/test_analyzer.py tests/test_phase6b.py -v` |
| 4 | reporter：render_snapshot market 分支 + save_snapshot suffix + context cyb | src/reporter.py | None 分支模板漂移破坏既有断言 | `venv/Scripts/python -m pytest tests/test_reporter.py tests/test_phase6a.py tests/test_context.py -v`（先扩 fixtures 再跑） |
| 5 | snapshot_report.py：argparse + 市场化编排 | snapshot_report.py | 参数默认/透传错 | TestSnapshotEntryOrchestration + `venv/Scripts/python snapshot_report.py --help` |
| 6 | 既有测试 fixture 更新 + 新增 test_phase7.py | tests/ | fixture 漏改致 KeyError | `venv/Scripts/python -m pytest tests/ -v` 全绿（基线 147 更新后 + 新增 ≈ 165+） |
| 7 | 文档同步（architecture/commands/pitfalls/AGENTS/README） | 上述 5 文件 | 文档与实现漂移 | 逐份核对最终代码 |
| 8 | 手动验证矩阵 + 行数预算 + `git diff` 审查 | 全部 | 增量超预算 | 见下方矩阵；源码增量 ≤ ~60 行（fetcher 8 + config 2 + analyzer 6 + reporter 22 + snapshot 22） |

### 手动验证矩阵（步骤 8，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| A 股午盘快照 | `venv/Scripts/python snapshot_report.py --market a-share --time midday` | 日志仅 3 个指数（上证/深证/创业板）；`reports/snapshots/{北京日期}-a-share-midday.md` 单板块三行、日期标（北京时间）；不写 history |
| 美股开盘快照 | `venv/Scripts/python snapshot_report.py --market us --time open` | 日志仅 GSPC/IXIC；`{美东日期}-us-open.md` 单板块两行；不含波动率板块 |
| 裸跑默认 | `venv/Scripts/python snapshot_report.py` | 等价 us/noon，产出 `{美东日期}-us-noon.md` |
| 创业板告警 | 备份 `data/last_values.json`，模拟 CYB 基准 = 当前值/1.052（+5.2%），跑 `snapshot_report.py --market a-share --time close` | 生成 `alerts/{日期}-a-share-close.md`（level WARN、阈值 ±5.0%、state 异动）；alerts.log 记 CYB |
| 午盘→收盘去重 | 同一模拟基准先跑 `--time midday` 再跑 `--time close` | 午盘触发 → 收盘 CYB 跳过（同 key）；告警文件各生成一份 |
| 与日报去重 | 上面收盘已标记 CYB 后跑 `daily_report.py` | 日报 CYB 不再告警（alerts.log 当日已标记）；`alerts/{美东日期}-close.md` 与 `-a-share-close.md` 并存不覆盖 |
| env 覆盖 | `ALERT_THRESHOLD_CYB=6 ... --market a-share --time close`（+5.2% 模拟） | CYB 不再告警（5.2 < 6） |
| 日报闭环 | `venv/Scripts/python daily_report.py` | 日志 8 个指数；A 股板块三行（含创业板指）；`history.json` 记录含 cyb；`context/{日期}.json` indices 8 键、history_30d 含 cyb 数组 |
| 休市容错 | 单测锁定（None → 休市行）；手动以真实数据为准 | **说明**：Yahoo 对 A 股休市日返回最近收盘（非 None），快照正常显示数值；`None→休市` 路径由 TestRenderMarketSnapshot 覆盖 |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（无网络） |
| 恢复 | 恢复 `last_values.json` 原值；清理验证期告警/快照文件 | 生产数据无残留 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| **告警文件覆盖**（A 股收盘与日报同写 `{date}-close.md`） | 设计 C 复合 type 彻底隔离；TestAlertFileNoCollision 锁定 |
| **双日期域**（北京/美东）在 alerts.log 混用 | 设计 B 论证：唯一同日重叠点是 A 股收盘 15:00 北京 = 美东同日 03:00，与日报去重键恒一致；午盘用北京键与收盘/日报同 A 股交易日联动，语义正确；写入 pitfalls |
| 旧 `noon.md` 文件名退役被 Hermes 旧 cron 继续读 | 设计 G：cron 调度表整体换代（README 同步），Hermes Prompt 更新列入交付清单 |
| 测试 fixtures 漏 8 键 → render/context 直接索引 KeyError | 步骤 6 逐一核对 4 个测试文件的 values dict（~10 处）+ 全量回归兜底 |
| 创业板休市日 streak 语义 | Yahoo 返回最近收盘 → 当日涨跌 0 → 去尾 0 不打断既有 streak（6B 已锁机制，CYB 同路径） |
| CYB 首次运行 | last_values 无 cyb 键 → 趋势「数据积累中」、check_breach 返回 None 不告警——正常首跑行为 |
| 8 指数拉取超时 | 日报 8 源 ≈ 2s×7 + 8 请求 ≈ 20-23s（7 源时已 ~16-19s，增量可接受）；快照 3/2 源更短 |
| us 快照不再含波动率（行为变更） | PRD 定稿明示（"us: 取 GSPC/IXIC"）；日报仍含波动率，README/architecture 同步说明 |
| 用户 config.json 无 cyb 键 | 深合并补默认 5.0，与 sh/sz 同机制，实测无需迁移 |
| context 契约变更（indices 8 键、history_30d 增 cyb）被 Hermes Prompt 忽略 | Hermes Prompt 同步列入交付清单 |
| 行数超预算 | 步骤 8 硬校验：源码增量 ≤ ~60 行 |

## 不做什么

- 不加除创业板外的新指数、不加新依赖、不改 Yahoo 取数机制、不加推送逻辑。
- 不做存储 cleanup、不做报告整合、不做快照 AI 解读（已确认决策 5/6/7）。
- 不改 `src/alerter.py`、`daily_report.py`、`seed_history.py`、`render_trend_chart`、告警去重机制、context 五键顶层结构。
- 快照不写 history.json、不算涨跌幅、不动 `data/last_values.json`（沿用只读基准）。
- 不改 `.env`、`requirements.txt`、`config.json`（用户文件）。

## 预计影响范围

- **新增文件**：`tests/test_phase7.py`（~130）。
- **修改文件**：`src/fetcher.py`（+8）、`src/config.py`（+2）、`src/analyzer.py`（+6）、`src/reporter.py`（+22）、`snapshot_report.py`（+22）、既有 6 个测试文件（夹具/常量断言扩展，既有断言语义不变）、docs 4 份 + README。
- **不受影响**：`src/alerter.py`、`daily_report.py`、`seed_history.py`、`render_trend_chart`、`requirements.txt`、`.env`、告警去重机制、context 顶层契约、Hermes cron 机制本身。
- **交付清单（非仓库文件）**：Hermes Prompt 同步——① cron 调度表 4 新任务（替换 00:30 午盘）；② 快照文件新命名 `{date}-{market}-{time}.md`；③ 告警文件新命名 `alerts/{date}-{market}-{time}.md`；④ context indices 8 键、history_30d 增 cyb 数组。

## 确认

- [ ] 人已审阅计划
- [ ] 设计 A（CLI 默认 us/noon；us 快照仅大盘，波动率板块从快照移除）/ B（快照日期=市场交易日）/ C（告警文件复合名防碰撞）/ D（兼容签名默认行为不变）/ E（创业板接线）/ F（既有测试夹具扩展）/ G（旧 noon 命名退役）已确认
- [ ] 既有 147 条测试的实际影响面已如实标注（夹具/常量断言扩展，断言语义不变）
- [ ] config 扩展（cyb 5.0 + env 映射）已确认
- [ ] us 快照不含波动率的行为变更已确认（PRD 定稿）
- [ ] A 股快照用北京时间归档（区别于现全项目美东日期惯例）已确认
- [ ] 旧 `YYYY-MM-DD-noon.md` 命名退役、4 新命名接管已确认（含 Hermes Prompt 同步）
- [ ] 没有遗漏测试（符号表/市场过滤/市场日期/单板块渲染/suffix 落盘/创业板告警/告警文件防碰撞/跨市场去重/入口编排全覆盖）
- [ ] 没有引入不必要依赖或额外配置段
