# 任务日志 — 自选股卡片静默隐藏修复

日期：2026-09-04
任务目录：`tasks/2026-09-04-watchlist-fix/`
来源：2026-09-04 诊断结论（实时取数抖动 1.4~10.2s 撞 SECTOR_TIMEOUT + payload 空结构双义 → 前端静默隐藏）

## 目标

修复「自选股卡片不显示且无任何提示」：

1. 后端 `hidden` 语义区分：`/api/watchlist` 响应增加 `hidden` 键——`true`=无配置（前端整卡隐藏），`false`=有配置（前端必显示卡片，取数失败也显示占位）。
2. 前端 12s 超时兜底（`Promise.race`），超时走失败占位而非无限静默。
3. 失败占位可见：取数失败 / 整体异常 / 超时 / 网络错 → 卡片显示「数据暂缺」行。

## 改动文件清单

- `web/app.py`：`_load_watchlist()` 重构，新增 `hidden` 键；配置读取异常与取数异常分层（`load_config` 抛 → `hidden:true` 视同无配置；`fetch_watchlist` / payload 抛 → `hidden:false` + 空结构）；模块 docstring 补 hidden 语义一句。
- `web/templates/index.html`：`DOMContentLoaded` 内 watchlist fetch 链整段重写（`hidden` 驱动显示 + `Promise.race` 12s 超时 + catch 失败占位）；`renderWatchlist` 删除空 `stocks` 自行隐藏逻辑（显示决策上移至调用处按 `hidden` 统一判断）。
- `tests/test_web.py`：4 条既有用例断言更新（`hidden` 键）+ 新增 2 条（`load_config` 抛 / `fetch_watchlist` 抛的 hidden 语义）。
- `docs/architecture.md`：二十八期行补 `/api/watchlist` payload `hidden` 语义。
- `tasks/2026-09-04-watchlist-fix/journal.md`：本文件。

## 验证结果

- `venv/Scripts/python -m pytest tests/test_web.py -v`：**47 passed**（含新增 2 条 `test_load_watchlist_config_raises` / `test_api_watchlist_fetch_raises_endpoint`）。
- `node --check` 隔离校验新 fetch 片段（约束 #39：仅验主脚本块）：**SYNTAX_OK**。
- 全量 `venv/Scripts/python -m pytest tests/`：**427 passed，3 failed**。
  - 3 failed 与本任务无关：`test_analyzer.py::TestBuildStatuses::test_fetch_failed`、`test_context.py::TestGenerateContext::test_all_sources_failed`、`test_phase6a.py::TestBuildStatusesStock::test_stock_missing_value_tolerated`——断言 `'未开盘' == '获取失败'`，涉及 `build_statuses` 状态文案，所在文件本次未改动，属既有失败，不在本次范围。

## 遇到的问题

- 无。计划步骤清晰，单测零联网（`monkeypatch` 打使用方 `web.app`）。

## 下次注意

- 浏览器四场景（无配置 / 有配置正常 / 取数失败 / API 两态）依赖外网实时取数抖动（1.4~10.2s），仅手动 `curl` + 浏览器验证，未纳入自动化；本环境未跑真实 uvicorn 冒烟，端点契约由 TestClient 用例锁定。
- fetch 链改用 `Promise.race` 12s 超时；若后续频繁出现 >12s 成功响应，迟到响应已被 settle 丢弃、需下轮刷新恢复——届时再上「迟到响应覆盖占位」。
- `load_config` 抛 → `hidden:true` 是保守选择（配置不可读视同无配置），日志有 warning 可查。
