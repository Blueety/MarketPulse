# Journal — 自选股看板文件化（快照落盘，web 读文件零延迟）

- 日期：2026-09-12
- 角色：编码执行者（Phase 3 Step 3.6-3.7），按 `plan.md`（方案 A：彻底文件化）实施
- 基线：pytest 459 passed / verify_ui ALL PASSED（开工前确认）

## 目标

自选股卡片打开即现（与其他卡片同毫秒级）：报告链路（daily + snapshot）落盘 `data/watchlist.json`
快照，`/api/watchlist` 只读文件（快照优先 + symbol 配置比对 + 实时回退），放弃盘中实时、
以 `as_of` 时点标注防误读（用户已确认语义变更）。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `src/analyzer.py` | +47 行 | `WATCHLIST_FILE` 常量；`save_watchlist_snapshot`（stocks 空/values 全 None → False 空操作；存原始数据 series tuple→list；原子写）；`load_watchlist_snapshot`（缺键/类型异常 → None，容错同 load_history） |
| `daily_report.py` | +6 行 | fetch_watchlist 成功路径内 try/except 落盘（决策 H 容错） |
| `snapshot_report.py` | +10 行 | main() context 块后、auto_commit_push 前：配置了 stocks → fetch + save（try/except，新鲜度随 4 cron） |
| `web/app.py` | ±30 行 | `_watchlist_config()` 抽取（env > config.json 原语义）；`_load_watchlist` 快照优先 + symbol 比对 + 实时回退，命中加 `as_of`；`load_watchlist_snapshot` 模块级导入（monkeypatch 打 web.app） |
| `web/templates/index.html` | ±2 行 | 副标题「实时取数」→ `<span id="watchlist-asof">收盘快照</span>`；「现价」→「最新价」 |
| `web/static/app.js` | +6 行 | renderWatchlist 读 `as_of`（slice(5,16) 格式化 MM-DD HH:MM）；空态去「（实时取数失败）」 |
| `tests/test_analyzer.py` | +63 行 | TestWatchlistSnapshot 9 条（roundtrip/覆盖/空 cfg/全 None/缺文件/坏 JSON/非 dict/缺键/类型错） |
| `tests/test_web.py` | +55 行 | `_reset_watch_cache` 适配（默认隔离快照读取为 None）；3 条新用例（文件命中零联网 / mismatch 回退 / 无快照回退） |
| `docs/architecture.md` / `AGENTS.md` / `docs/pitfalls.md` | 收尾 | 决策行 1 条 / web 行更新 / 4 条坑位 |

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| S1 | `pytest tests/test_analyzer.py -q` | **53 passed**（9 新用例 + 零回归） |
| S2 | `AUTO_PUSH=0 daily_report.py` × 2 | 两次 **EXIT=0**；`data/watchlist.json` 生成（515300.SS、65 点）且二次运行覆盖、`saved_at` 11:30→11:32 |
| S3 | `pytest tests/test_web.py -q` | **62 passed**（3 新用例；文件命中用例把 fetch_watchlist mock 成 raise 仍 200 → 证明零联网） |
| S4 | `node --check app.js` + `verify_ui.py` | JS OK；**ALL PASSED / EXIT=0** 三视口 |
| S5 | `AUTO_PUSH=0 snapshot_report.py --market a-share --time midday` | **EXIT=0 但休市门跳过**（周六，plan 风险 9 的预期行为）→ 真跑验证顺延下一交易日 cron；代码路径与 S2 已验证调用序列相同 |
| S6 | `pytest tests/ -q` | **471 passed**（459 基线 + 12 新增，全仓库零回归） |

## 遇到的问题

1. **plan 说"conftest tmp 环境无快照文件"不成立**：conftest 只隔离 CONFIG_PATH，DATA_DIR 仍是真实
   `data/`；S2 真跑后真实快照会劫持既有未打补丁用例。处置：`_reset_watch_cache` autouse fixture
   默认把 `load_watchlist_snapshot` 隔离为 None，文件路径用例自行覆盖（test 级 setattr 晚于 fixture 生效）。
2. **S5 真跑遇周六休市门**：EXIT=0 但日志只有「休市…跳过」，main 内新增块未执行。该门本身是
   plan 风险 9 的预期行为（且不可绕过验证——绕过=制造 H.5 周末污染 history 坑）。S5 块与 S2 已
   双次真跑验证的调用序列相同，真跑验证由下一交易日 cron 自然完成。
3. **用户 11:40 并行实验**：用户改 config（515300.SS→AAPL）并跑了 daily_report，`data/watchlist.json`
   与 `context/2026-09-03.json`（vix null→15.84 等回填）被其运行改写并随 cron 入库——恰好真实演练了
   S3 的 mismatch 回退路径；均为用户数据/生成物操作，不在本任务代码 diff 内，无需处理。

## 下次注意什么

- "文件优先"端点改造：autouse fixture 默认隔离文件读取是必做项，否则真实数据文件劫持测试。
- main() 尾部新增逻辑的"真跑验证"在休市日是空转（门在 main 开头），退出码 0 不代表执行了新代码。
- 快照类文件存"原始数据"（加工留展示层）+ JSON 往返后 tuple→list 的兼容要测试钉死。
- 给 append-only 文档（决策表/坑位）做编辑时，new_string 必须完整包含旧文，编辑后 grep 计数核对。
