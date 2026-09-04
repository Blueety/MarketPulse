# 执行日志 — 自选股名称/概览旧值问题三项修正（A 定稿保护 / B 展示标注）

日期：2026-09-04
任务目录：`tasks/2026-09-04-watchlist-name/`
计划源：`tasks/2026-09-04-watchlist-name/plan.md`

## 目标

- **A. 定稿保护（核心 bug）**：`daily_report.append_history` 整行覆盖在美东盘中跑日报时会抹掉快照已写入的美股盘中值（GSPC/IXIC）。新增 `merge_existing` 参数，定稿时保留当日行既有非 None 盘中值。
- **B. 展示标注（最小方案）**：web `/api/latest` 回填值加 `source_date`，前端 `renderOverview` 对回填行加「（MM-DD收盘）」小字 + 涨跌幅格「未收盘」，避免旧值观感。
- **C. 调度核对（只核对不改）**：已在 plan.md 第 4 节给核对清单与建议，不在仓库内改调度。

## 改动清单

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | `append_history(record, merge_existing=False)` 新增参数；`merge_existing=True` 时 append 前用当日既有行（仅限 `_HISTORY_KEYS`、排除 date）补全 record 中 None 键；默认 False 其余调用零影响。 |
| `daily_report.py` | L199 调用点改 `append_history(record, merge_existing=True)` + 注释决策理由。 |
| `web/app.py` | `_compute_latest` 回填循环捕获来源日期 `src_date = past["date"]`，indices 项新增 `"source_date": src_date`；`change_pct` 强制 None 逻辑不动。 |
| `web/templates/index.html` | `renderOverview` 内：回填行（`src_date` 非空且 ≠ 概览日期）value 后追加「（MM-DD收盘）」小字、涨跌幅格改显「未收盘」。 |
| `tests/test_merge_history.py` | 新增 `TestAppendHistoryPreserve`（4 条）：True 保留盘中值 / False 默认覆盖回归锁 / True+有值覆盖 / 无当日行新建。 |
| `tests/test_web.py` | `test_compute_latest_backfills_sparse` 加 `source_date` 断言；新增 `source_date_none_when_last_has_value` 与 `source_date_multi_day_chain`。 |
| `docs/architecture.md` | 关键决策表补 2 行（日报定稿保护 / Web 看板来源标注，均 2026-09-04）。 |

未改（按计划）：`src/fetcher.py` / `src/config.py` / `snapshot_report.py` / `opening_analyzer.py` / `merge_history` / 任何配置与生成物 / 自选股链路。

## 验证结果

- `tests/test_merge_history.py -v`：**15 passed**（含 4 条新增）。
- `tests/test_web.py -v`：**49 passed**（含 3 条 source_date 用例）。
- `tests/test_phase25.py tests/test_phase27.py -v`：**35 passed**（daily 编排回归，conftest 已强制 `AUTO_PUSH=0`，无真实 commit/push）。
- 全量 `tests/ -v`：**432 passed / 4 failed**。
  - 4 个失败均为 `未开盘` vs `获取失败` 文案基线问题（`test_context::test_all_sources_failed`、`test_phase6a::test_stock_missing_value_tolerated`、`test_reporter::test_failed_fetch_annotated`、`test_reporter::test_render_failed_fetch`），位于 `build_statuses` / `reporter` 失败文案，与本次改动（merge_existing / source_date / 概览标注）无关，属计划已知的既有基线失败。
- JS 片段隔离 `node --check`：**JS_OK**（按约束 #39 仅校验新增片段，未整文件校验规避 `</script>` 截断假阴性）。
- `git diff --stat`：7 个目标文件变动（analyzer +16/-2、daily +3/-1、app +3、index +8/-2、test_merge +42、test_web +28、arch +2）。`context/2026-09-03.json` 与 `plan.md` 的 M 为进入会话前已存在的改动，非本次引入。

## 问题

- 无阻塞性。全量 4 失败与本次无关（文案基线，计划已标注）。
- 计划预称「既有 3 条失败」，实跑 4 条；均为同一 `未开盘`/`获取失败` 文案根因，未扩大排查范围（不在本次任务面）。

## 下次注意

- `read` 对大文件默认返回结构摘要、且 `:raw` 行选择器在本环境仍被摘要吞掉；用 `path:行号` 纯行号选择器（无 `:raw`）才能取到真实行。
- 调度归位（daily 改到北京 04:40-05:00 美东收盘后）后 A 的兜底保护自然不再触发；当前保护仅作盘中误跑的兜底。
- web 模板改动须另起未缓存端口（如 8001）或硬刷新验收（Jinja2 启动缓存）；本次未做浏览器 DOM 验收，已由 Python 契约用例 + JS 语法校验覆盖。
