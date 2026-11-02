# 七期「盘中快照扩展」执行日志

日期：2026-08-30
执行者：Hy3

## 目标

按架构师计划 `tasks/2026-09-01-marketpulse-phase7/plan.md` 实施盘中快照扩展：
- 创业板（399006.SZ，符号 `CYB`）接入 SYMBOLS（7→8 键）。
- `snapshot_report.py` 支持 `--market {a-share,us}` / `--time {open,midday,close,noon}`，单板块渲染。
- 4 个 Hermes cron 各传一组参数；快照存 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`。
- 告警文件复合名 `alerts/YYYY-MM-DD-{market}-{time}.md` 防与日报碰撞。
- 设计选择 A/B/C/D/E/G 全部落地。

## 改动文件清单

源码：
- `src/fetcher.py`：新增 `CYB` 定义（创业板指 399006.SZ，阈值 cyb=5.0，入 STOCK/A_SHARE）；新增 `STOCK_SYMBOLS`（5 键）、`A_SHARE_SYMBOLS`（3 键）、`MARKETS` 市场子集、`fetch_all(market=None)` 市场过滤取数（新增 `time` 参数隔离开关，未用可删）。
- `src/config.py`：`DEFAULTS` + `ENV_MAP` 新增 `cyb: 5.0` / `ALERT_THRESHOLD_CYB`。
- `src/analyzer.py`：新增 `SHANGHAI_TZ`、`get_market_date(market)`（上海/纽约时区取当日日期，设计 B）；`load_history` 投影补 `cyb`。
- `src/reporter.py`：`render_snapshot(date, values, statuses, market=None, time="noon")` 市场化单板块分支（设计 A：us 仅 GSPC/IXIC、a-share 仅 SH/SZ/CYB，无波动率；设计 B 时区文案；裸调用 = 原三板块美东 12:30，决策 D）；`save_snapshot` 加 `suffix` 参数（默认 noon）；`generate_context` 的 `history_30d` 补 `cyb` 数组。
- `snapshot_report.py`：argparse（--market/--time）+ `main(market, time)` 编排，单板块取数→分类→渲染→落盘→告警检查（只读缓存基准），不写 history/缓存/不推送。

测试：
- `tests/test_phase7.py`（新增）：符号/市场日期/市场过滤取数/单板块渲染/suffix/创业板告警（阈值·严格大于·env）/复合名防碰撞/跨市场去重/入口编排，共 23 项。
- `tests/test_phase6a.py`、`test_phase6b.py`、`test_reporter.py`、`test_context.py`、`test_analyzer.py`、`test_alerter.py`、`test_config.py`：7 指数 fixtures 补 `CYB`（值/涨跌/状态/历史投影/告警值/clean_thresholds），保持全绿。

文档：
- `docs/architecture.md`：概览（8 指数/4 cron/复合名告警）、模块表、数据流、关键决策表（七期行）、约束。
- `docs/commands.md`：快照命令分档、8 指数、去重示例、七期验证项。
- `docs/pitfalls.md`：新增「七期：盘中快照扩展」小节。
- `AGENTS.md`：Project Map 更新 snapshot/reports/alerts/tests/fetcher（8 键含创业板）。
- `README.md`：能力表（七期行）、指数表（创业板）、快照章节（4 cron 表）、调度表、目录树、数据流、告警阈值（含 cyb）、config 示例（cyb）、env 表（CYB）、测试数 170。

## 验证结果

- 单元测试：`pytest tests/ -q` → **170 passed**（基线 147 + 七期 23）。2 个 matplotlib tight_layout 警告为趋势图既有项，与本改动无关。
- 创业板数据真实性（用户明确要求）：实际跑 Yahoo 取 `399006.SZ` → 3424.40，确认可取。
- 端到端实跑（不联网 mock）：
  - `snapshot_report.py --market a-share --time midday` → `reports/snapshots/2026-08-30-a-share-midday.md`，单板块含 SH/SZ/CYB，北京时间归档，日期 2026-08-30。
  - `snapshot_report.py --market us --time open` → `reports/snapshots/2026-08-29-us-open.md`，仅 GSPC/IXIC，美东日期 2026-08-29（设计 B 市场日期差异已验证）。
  - 裸跑 `snapshot_report.py` → `2026-08-29-us-noon.md`。
  - `daily_report.py` → 8 指数全部取到（含 CYB 3424.40），`context/2026-08-29.json` 含 8 indices + `history_30d.cyb` 数组（len 30），`reports/2026-08-29.md` 含「创业板指」行；CYB 状态「数据积累中」（首次出现无基准，符合预期）。
- 验证期仅清理了 3 个临时快照文件；日报/context/history/last_values 均为当日真实数据，保留（未做异动模拟，故无需恢复 last_values）。

## 遇到的问题

- `edit` 工具多行替换多次误吞相邻代码/重复行（与 pitfalls「通用」一致）：render_snapshot 重写、generate_context 投影、`load_history` 投影、clean_thresholds 的 for 行、各测试 values 块均出现重复或错位，已逐处读回修复并回归测试。教训：本类结构性编辑优先 `write` 整文件重写或更小锚点。
- snapshot_report.py 尾部曾遗留重复 `__main__` 块、argparse 误置于 `__main__` 内，已合并到顶部 import 并清理。

## 下次注意什么

- 结构性多函数编辑用 `write_file`/`ast_edit` 而非长 `edit` 补丁，尤其 reporter/fetcher 这类函数密集模块。
- 跨市场日期差异（A 股北京/美股美东）是设计意图，验证时不要当成 bug。
- 复合名 `alerts/YYYY-MM-DD-{market}-{time}.md` 已规避与日报 `close` 碰撞，Hermes 摘要/检测器若按文件名取最新快照，需同步为新的 `{market}-{time}` 模式。
- 旧 `reports/snapshots/YYYY-MM-DD-noon.md` 命名已退役（旧文件留盘不清理，决策 5）；新 cron 一律用复合名。
- config.cyb=5.0 已接入，若用户要调创业板阈值，改 config.json `alert.cyb` 或 env `ALERT_THRESHOLD_CYB`。
