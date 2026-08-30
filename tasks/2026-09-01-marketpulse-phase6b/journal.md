# 六期B 执行日志 — A 股大盘监控

## 目标

MarketPulse 新增 A 股大盘监控：SYMBOLS 5→7（加 000001.SS / 399001.SZ），日报三板块（美股 → A 股 → 波动率），A 股休市特判（None → 「休市」），config 扩展 SH/SZ 告警阈值（±4%，恒 WARN/异动），context 历史投影补齐 sh/sz 键。严格按架构师 `plan.md` 实施，不 commit，等用户审阅。

## 改动文件清单

源码（5）：
- `src/fetcher.py`：SYMBOLS 注册表加 SH(000001.SS) / SZ(399001.SZ)；新增 `A_SHARE_SYMBOLS = {"SH","SZ"}`、`STOCK_SYMBOLS`（4 键，含 SH/SZ）。
- `src/config.py`：`DEFAULT_ALERT_THRESHOLDS` 加 gspc/ixic/sh/sz=4.0；`ENV_MAP` 加 ALERT_THRESHOLD_SH/SZ。
- `src/analyzer.py`：`build_statuses` 中 A 股 None → 「休市」；`load_history` 投影补齐 sh/sz（缺失→None）；`build_search_keywords` 截断到 5。
- `src/reporter.py`：日报/快照表头「美股大盘」→「美股大盘」+「A 股大盘」（🇨🇳，置于波动率之前）；A 股表 4 列；`generate_context` 的 `history_30d` 加 sh/sz 数组；`_breach_item` 映射 `alert["last"]`→previous、`round(alert["change"],2)`→change_pct。
- `seed_history.py`：`save_last_values` 键派生 `k.upper()`（修复 SH/SZ 写入 last_values 后无法被读回）。

测试（5 旧 + 1 新）：
- `tests/test_config.py` / `test_analyzer.py` / `test_alerter.py` / `test_context.py` / `test_reporter.py` / `test_phase6a.py`：夹具与值字典补齐 SH/SZ，断言三板块顺序/休市行/历史投影。
- `tests/test_phase6b.py`（新增，20 项）：SYMBOLS 分组、A 股 streak（含末尾平坦去尾 0 不打断）、休市特判、A 股告警阈值（恒 WARN/严格大于/env 覆盖/独立去重）、日报三板块、history 投影、context 七数组、search_keywords 上限 5。

文档：
- `README.md`：补六期 A/B 能力行、监控指数表（含 SH/SZ 与休市说明）、告警条件（SH/SZ ±4%）、config 示例与环境变量、测试数 147、数据流源 ticker。

## 验证结果

- 单元测试：`pytest tests/ -q` → **147 passed**（基线 127 + 新增 20）。
- 源码常量自检：SYMBOLS 7 键、tickers、STOCK/A_SHARE 分组、defaults 阈值均符合。
- 实际运行 `daily_report.py`：成功抓取 7 个指数（SH 3952.18 / SZ 13953.07），报告三板块顺序正确（🌏 美股 → 🇨🇳 A 股 → 📈 波动率），A 股首次运行显示「数据积累中」；`history_30d` 含 sh/sz 数组（29 None + 今日值，长度 30 对齐）。
- 实际运行 `snapshot_report.py`：三板块渲染正常，A 股行显示「横盘」。
- `git diff --stat`：10 files +155 -61；源码净增量在预算附近（reporter 因三板块重构 + 静态文案略多于计划估计的 +12）。

## 遇到的问题 / 修复

1. `build_statuses` 编辑时误删 `val = values.get(sym)` 行 → 测试 NameError；已补回。
2. `_breach_item` 重写时键名写错（用 `alert["previous"]`/`alert["change_pct"]`，实际 check_breach 返回 `last`/`change`）→ 测试 KeyError；修正为 `alert["last"]` 与 `round(alert["change"],2)`，并恢复 `previous`/`change_pct` 映射。
3. `test_phase6b.py` 编辑锚点错位：flat-day streak 测试误落入 `Test休市` 类（缺 `_hist`）、`collect_breaches` 误调 `an.`（应在 `alerter`）；已归位并改为 `al.collect_breaches`。
4. flat-day streak 用例初版假设错（末尾平坦应为「今日平」而非历史中间平坦）；改为 4 连涨 + 今日平 → streak=3（去尾 0 验证）。
5. README 多处旧行残留（重复「三个波动率指数」标题、重复「113 项」计数）；已清理。

## 下次注意

- `edit` PUT 区间务必精确落在目标行，跨多行的「替换 + 新增」易吞掉相邻行或产生重复；改完即 `git diff` 核对。
- 重写被误改的函数时，先用 `lsp`/原文确认返回 dict 的真实键名，再映射（check_breach 返回 `last`/`change`/`state`，context 契约用 `previous`/`change_pct`）。
- 新增 fixture（clean_thresholds）扩展键集时，所有相关测试的价值字典需同步补 SH/SZ，否则投影/上下文断言失真。
