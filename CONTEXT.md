# 领域词表

> 项目的统一语言。**只放词汇定义**，不放实现细节、不放需求、不放待办。
> 描述和命名一律用这里的词；术语冲突当场指出并更新本文件。

## 术语

**触发（breach）**:
`check_breach` 判定某个标的的涨跌幅越过阈值这一事实。触发是**纯计算结果**，不产生任何文件。
_Avoid_: 用「告警」指代未去重的判定结果。

**告警（alert）**:
触发经当日去重（`data/alerts.log`）后**渲染出的产物**——`alerts/YYYY-MM-DD-*.md` 文件与推送内容。同一标的当日已在午盘触发过，收盘就不再生成。
_Avoid_: 「告警」与「触发」混用。

**日报（daily report）**:
`daily_report.py` 的收盘产物：取数 → 报告 + 趋势图 → 写历史/缓存 → 生成 context。日报末尾会按白名单自动提交推送。

**快照（snapshot）**:
`snapshot_report.py` 的盘中产物，**单市场单板块**渲染（`--market a-share|us` × `--time open|midday|close|noon`），**仅存盘不推送**。

**开盘分析（opening analysis）**:
`opening_analyzer.py` 在市场开盘时把各指数开盘价与上一交易日收盘价对比的产物，只覆盖开盘那一刻的板块快照。

**历史长表（history）**:
SQLite `data/marketpulse.db` 的 `history` 表，一行一个 `(date, symbol)`。日报/快照/开盘分析三个入口共用它；`merge_history` 按市场子集投影 + preserve 语义写入。
_Avoid_: 用「history 文件」「历史文件」指代 SQLite 长表。

**事件表（econ_events / econ_event_news）**:
经济日历的数据表。它由 `scripts/sync_econ_calendar` 落盘，备份为**单文件全量** `data/backup/econ_events.json`（不按月冻结——表里有未来日程，按月冻结会既碎又旧）。

**市场子集（MARKETS）**:
取数与渲染的市场范围：`a-share` = SH/SZ/CYB，`us` = GSPC/IXIC。波动率（VIX/VXN/MOVE）与另类资产（GLD/BTC-USD）**不属于任何快照子集**：另类资产只出现在日报与趋势图，且不参与告警。

**大类聚合（板块热度）**:
`SECTOR_MAPPING` / `aggregate_sectors` 把 ~175 个概念板块聚合成 10+1 个大类，日报与 context 的 `sector_heat` 用的是**聚合后**的大类，不是原始概念板块。

**四象限（QUADRANTS）**:
增长轴 × 通胀轴的分档结论。美国版增长轴用**就业替代 GDP/PMI**（如实标注），中国版增长轴用 **PMI 水平与 50 比较**（不是同比方向）；两版**共享同一份键与文案**。

**相关性（correlation）**:
指数对收益率的 Pearson 相关，窗口 **30 个交易日**，`|r| > 0.5` 记为显著对；写进 context 的 `correlation` 键，web 只读消费。

**自选股（watchlist）**:
用户配置的标的列表（≤20 个），存储一律用 **Yahoo 代码格式**（A 股也映射成 Yahoo 格式），但 A 股实际经 AkShare 取数。

**基准（last_values）**:
`data/last_values.json`，涨跌幅的比较基准（上一交易日收盘）。它是缓存，不是历史——历史在 SQLite 长表里。

**档位（task tier）**:
流程概念，不是领域概念：任务规模轴 T0–T3 × 类型轴（加功能/重构、bug 可复现、bug 不可复现）。判定见 `docs/agents/任务分级.md`。

## 关系

- 一个**触发**当日最多落成一条**告警**（每标的每日去重一次，跨市场互不影响）。
- **日报** / **快照** / **开盘分析** 三个入口写同一张**历史长表**，各自只投影自己的**市场子集**。
- **日报**与**快照**生成 **context** 上下文（`context/YYYY-MM-DD.json`），web 只读消费；web 进程绝不写 `data/` `alerts/` `context/`。
- **板块热度**（大类聚合）只在 **A 股**日报与 context 里出现；美股侧对应的是 `us_sector_heat`。

## 已消歧的歧义

- **「history」**：一律指 SQLite 长表 `data/marketpulse.db`。`data/history.json` 只是 **2026-09-12 的旧快照**，除 `scripts/backtest.py --history` 演练外没有意义。
- **「触发」vs「告警」**：踩过坑——`collect_breaches` 是纯计算，跑它不会改任何文件；能落盘的是 `run_alert_checks` 之后的告警渲染。
- **「被忽略的目录」**：`context/` 与 `alerts/` **不是** gitignore 排除（`data/alerts.log` 是 `.gitignore` 的反排除例外），它们在 auto-push 白名单里**会入库**——Railway 的 `/api/latest` 就是从仓库里这份读的。同理 `data/marketpulse.db` 是 tracked 文件，**入库即线上数据源**。
- **「`.db` 提交」**：写库后 push 前必须 `storage.wal_checkpoint()`；否则新行留在 `-wal` 里，提交的副本漏数据（`src/git_ops.py` 在 `auto_commit_push` 内有护栏，手工提交没有）。
- **「板块」**：不加限定词时指**聚合后的大类**（10+1）；原始概念板块一律写「概念板块」。

## 为什么值得维护

- 代码里的变量、函数、文件按同一套词命名，代码库对 Agent 更可导航
- 描述问题时不用绕 20 个词说一件事，省 token 也省沟通
- Agent 读代码时不必现场猜术语——本项目最大的坑恰好都出在术语漂移上（agent 上下文文件的错误描述会直接误导后续实现）
