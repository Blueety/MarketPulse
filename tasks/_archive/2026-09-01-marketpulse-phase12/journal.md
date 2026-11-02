# MarketPulse 十二期 — 执行日志

## 目标
计算主要指数间的 Pearson 相关系数（输入=日收益率，非原始价格），日报新增「📊 相关性分析」板块，context 新增 `correlation` 键（仅显著对 |r|>0.5 写入）。

## 改动文件清单
- `src/analyzer.py`：新增常量 `CORRELATION_PAIRS` / `CORRELATION_SIGNIFICANT=0.5` / `CORRELATION_DAYS=30` / `MIN_POINTS=10`；新增 `compute_correlation(history, pairs=None, window=CORRELATION_DAYS)`（纯 Python Pearson；从 history 收盘价推导日收益率；单侧缺口行断开收益链不参与；空对齐 / 零方差 / 样本<10 → r=None；atan 越界钳制 [-1,1]；round 2）。
- `src/reporter.py`：import 增加 `CORRELATION_SIGNIFICANT`；`render_report` 增加 `correlations=None` 参数与「📊 相关性分析」章节（5 对固定组合表格，颜色 r>0.5 红 / r<-0.5 绿 / 否则灰，不足显示「数据不足」）；新增 `_correlation_row_md` 辅助；`generate_context` 增加 `correlations=None` 参数并写 `correlation` 键（仅 |r|>0.5）。
- `daily_report.py`：import `compute_correlation`；`main` 在 `load_history()` 后计算 `correlations` 并透传给 `render_report` 与 `generate_context`。
- `tests/test_phase12.py`：新增 17 条测试（纯逻辑 9 + 报告颜色/章节/缺省 4 + context 键/缺省 3 + 入口透传 1）。
- 文档同步：`docs/architecture.md`（模块表 + context 契约八键）、`docs/commands.md`（十二期验证要点）、`docs/pitfalls.md`（Pearson 边界）、`AGENTS.md`（analyzer/reporter/context 描述）。

## 验证结果
- `venv/Scripts/python -m pytest tests/ -q` → 248 passed，6 failed（全部为 `test_web.py` 既有失败；经 `git stash` 基线核对同样 6 失败，确认非本任务回归）。
- `python daily_report.py` 实跑成功（退出码 0）：`reports/2026-08-30.md` 含「📊 相关性分析」章节，颜色正确（VIX↔GSPC -0.67 绿，其余灰）；`context/2026-08-30.json` 含 `correlation` 键（1 条显著对 VIX↔GSPC r=-0.67 n=27）。
- 存量测试（analyzer/reporter/alerter/context/config/phase6-11）保持通过。

## 遇到的问题
1. **编辑串扰（reporter/daily_report 同窗编辑）**：初期误将 daily_report 的 import 改动以 reporter 的 `#TAG` 写入，造成 reporter 多出 `compute_correlation` import、`fmt_value` 被覆盖删掉、docstring 重复、a_share 循环多出 `us_stock_syms` 行、us 板块表损坏。逐处修复后恢复；并修复 `generate_context` 因合并编辑误删 `search_keywords` 键。
2. **test 文件增量编辑导致函数体错位/重复**：对测试文件做多次 PUT 行号映射漂移，出现 orphan 代码；改为整文件重写解决。
3. **测试数据计数偏差**：`test_insufficient_points` 初版期望 n==4 实为 5（5 个收益率 → 5 个返回），已更正；`test_constant_series` 用 `_prices` 反推价格产生浮点噪声使序列非严格常量，改为直接传恒定价格列表使收益率为 0 → 零方差 → r=None。

## 下次注意什么
- 跨文件编辑时每个文件用自己独立的 `#TAG` 快照，避免把 A 文件的 PUT 误投到 B 文件的窗口。
- 对测试文件优先整文件 `write`，不要用多轮行号 PUT（行号在每轮编辑后漂移）。
- 构造「常量收益率」场景用恒定价格列表，而非反推价格（浮点噪声会改变方差）。
- 合并编辑生成 context 块时，确认没有吞掉既有键（`search_keywords`）。

## 交付提醒（决策 D）
`context` 契约新增 `correlation` 键，需同步 Hermes Prompt 的字段说明（Hermes 侧不在本仓库，归交付方更新）。
