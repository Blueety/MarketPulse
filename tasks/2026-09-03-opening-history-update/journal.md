# 任务日志：二十七期 开盘/快照实时价合并写 history

## 目标
修复收盘日报趋势图末点错配：盘中（开盘分析 / 快照）已算出的实时价未进入 `data/history.json`，
仅美东收盘后 `daily_report` 全量 append 一行，导致趋势图末点只反映美股收盘、A 股/开盘实时价缺失。
改为三入口共享 history：盘中入口把本市场子集实时价 merge 进当日行；日报读时剔除自身 date 行后用前一日收盘定稿。

## 改动文件清单
- `src/analyzer.py`：新增 `_HISTORY_KEYS`（SYMBOLS 小写 frozenset）+ `merge_history(date, values)`
  （按 date 合并写当日行：子集投影、新建行补 None、按 date 去重幂等、裁 90 天、原子写；取数全失败→空操作）。
- `snapshot_report.py`：读 history 后剔除自身 date 行（决策 R4）；main 末尾调用 merge_history 合并本市场子集。
- `opening_analyzer.py`：import merge_history；main 末尾（cron push 前）按 market 子集合并写（a-share={SH,SZ,CYB}、us={GSPC,IXIC}，VIX 不写）。
- `daily_report.py`：load_history 后剔除自身 date 行（决策 R6）；末尾 append_history 全量定稿不受影响。
- `web/app.py`：`_compute_latest` 末行某符号为 None 时前向回填最近非空行值，change_pct 强制 None（决策 R5）。
- `tests/test_merge_history.py`：新增 11 例（投影/子集合并/不覆盖/空操作/去重幂等/None 处理/坏文件）。
- `tests/test_phase7.py`：snapshot 接线桩 + 断言（suffix/merge_date/merge_values）。
- `tests/test_phase15.py`：`test_main_orchestration` 补 merge 桩+断言；`test_zero_persistence` 反转验证 history 被合并写、context 仍零写入。
- `tests/test_phase27.py`：`test_snapshot_passes_history` 补 merge 桩（防触碰真实 history）。
- `tests/test_web.py`：新增 `test_compute_latest_backfills_sparse`（稀疏行回填）。
- `docs/architecture.md`：关键决策表新增「日间合并写 history + 读时剔除（二十七期）」行。
- `AGENTS.md`：analyzer 行补充 merge_history 说明。
- `docs/pitfalls.md`：新增两条（读时剔除+merge_history 配套；merge_history 不写 alt/VIX）。

## 验证结果
- 全量回归：420 passed（原 408 + 11 merge 单测 + 1 web 测试）。
- 真实 `merge_history` 收敛冒烟：同日 a-share 子集 + us 子集两次调用，09-03 行含 sh/sz/cyb/gspc/ixic，互不覆盖；读时剔除正确移除非当日行。
- `test_phase7` / `test_phase15` / `test_phase27` 均通过；web 测试 37 passed。

## 遇到的问题
1. `snapshot_report` 编辑误删 `last_values = load_last_values()` 行 → 回归 NameError，已恢复。
2. `test_phase7` 的 `_patch` 在加 merge 桩时误删了 `run_alert_checks` 桩 → alert_type 断言 KeyError，已补回。
3. `test_web.py` 别名是 `web.app`（非 `app`），且 `web.app` 无 `DATA_DIR`/`load_history` 模块属性；
   最终改为直接传 list 给 `_compute_latest`（与既有测试一致），移除多余 monkeypatch。

## 下次注意什么
- 编辑含多行的 PUT 范围务必精确，避免误吞相邻行（`last_values`、`run_alert_checks` 桩两次踩坑）。
- 测试桩改动宜逐条 diff 核对，尤其 `_patch` 类聚合桩。
- web 模块路径常量/函数引用纪律：monkeypatch 落点打 `web.app`，但 `web.app` 不重新导出 `load_history`/`DATA_DIR`；
  纯函数测试直接构造入参，少打 patch。
- `merge_history` 与 `append_history` 分工：盘中走 merge（子集），日报走 append（全量定稿），二者对当日行等价，日报无需再调 merge。
