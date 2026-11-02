# 任务日志 — context 空壳回退（web 看板板块数据兜底）

日期：2026-09-03
任务目录：`tasks/2026-09-03-context-fallback/`

## 目标

`_load_latest_context` 增加回退机制：最新 context 文件是失败运行的空数据（sector_heat 无 gainers）时，回退到最近一个 sector_heat 有数据的 context 文件，使 web 看板板块面板显示最近真实板块数据而非「数据暂缺」。前端、`api_latest` 其余字段、数据生产端（`generate_context`）一律不改。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增 `_read_context_file(path)`（单文件容错解析）；`_load_latest_context` 改为倒序遍历回退（第一个 `sector_heat.gainers` 非空的 context；全无板块 → 返回最新可解析 context；目录缺失/全坏 → None）。`_load_sector_heat`、`api_latest` 零改动。 |
| `tests/test_web.py` | 导入补 `_load_latest_context`；新增 5 条回退用例（`test_load_latest_context_falls_back_from_empty_shell` / `_prefers_newest_with_sector` / `_no_sector_anywhere` / `_skips_corrupt_newest` / `_all_corrupt`）。 |
| `docs/pitfalls.md` | 新增「模块 web/（context 空壳回退，2026-09-03）」小节：空壳遮蔽、`_load_latest_context` 整体回退语义、`gainers` 非空作有效标记、逐文件容错、状态列回退边界、真实数据落地后自然失效。 |
| `docs/architecture.md` | 关键决策表追加「Web 看板板块数据兜底（context 空壳回退，2026-09-03）」一行。 |

不改：`daily_report.py`、`snapshot_report.py`、`src/*`、前端 `index.html`。

## 验证结果

- 实况 smoke（当前仓库即复现现场，09-03 空壳 + 09-02 有数据）：`_load_sector_heat()['gainers']` 修复前 `[]`（空壳遮蔽）→ 现为 `['军工','消费','医药','金融','光伏/新能源']`（09-02 真实大类）。
- `pytest tests/test_web.py -v`：36 passed（31 既有 + 5 新增）。
- `pytest tests/ -v`：408 passed（全量回归）。
- `git diff --stat` 摘要：web/app.py / tests/test_web.py / docs/* 共 +123/-16；改动最小、范围收敛。

## 遇到的问题

1. **edit 多行替换误吞相邻函数**：步骤 1 初次 `PUT 173.=198:` 把原 `_load_latest_context`（至 184）连同 `_load_sector_heat`（187-198）一并替换，导致 `_load_sector_heat` 被删除、`ImportError: cannot import name '_load_sector_heat'`。已用 `PUT >203:` 在原位恢复该函数（与计划「零改动」一致）。印证 pitfalls 既有纪律「edit 多行替换容易误吞相邻代码」。
2. **测试未导入 `_load_latest_context`**：新增用例初跑报 `NameError`，因测试模块 `from web.app import (...)` 列表未含该符号；补入导入后通过。
3. **`context/2026-09-03.json` 出现在 `git diff`**：系本次会话前置诊断运行的遗留未提交改动（非本次引入），不在本任务改动范围内，未触碰。

## 下次注意什么

- 多行 `edit` 范围以「改动起止行为准」，不可把「保持在位但相邻的下一个函数」纳入被替换区间；改完立即 import 自检（`python -c "import web.app"`）。
- 新增引用待测模块符号的用例时，先核对测试文件 import 列表是否已导出该符号。
- 空壳判定只用 `gainers` 非空（前端唯一渲染字段；避免 losers-only 假阳性）。方案 A 下「仅板块取数失败日」状态列会随回退滞后一天（罕见）——若此类日变多，按 architecture 决策注记切方案 C（状态列按 history 最新日期取 context，板块列独立回退）。
