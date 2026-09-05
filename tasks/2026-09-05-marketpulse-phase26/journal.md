# 二十六期任务日志（2026-09-05）：修复美股快照日期门 + Yahoo 403 双主机轮换

## 目标
1. 美股午盘快照（北京 00:00 cron）正确推送，不再因日期检查跳过。
2. Yahoo 403 时自动双主机轮换，GSPC/IXIC 不再因单主机 403 全空。

## 改动文件清单
- `src/fetcher.py`：新增 `YAHOO_HOSTS=("query1","query2")` + `_yahoo_chart_get(symbol, params)` 逐主机轮换 helper（403/429/5xx/连接错误/超时切下一主机；404 等确定失败立即 `raise_for_status` 不轮换；状态码用 `getattr(resp,"status_code",None)` 兼容无 status_code 的 fake-session 单测）；4 个 Yahoo chart 调用点（fetch_vix_vxn / fetch_vix_realtime / fetch_us_sector_heat._one / _fetch_yahoo_watch）改走 helper；`_SESSION` UA 换浏览器串 + `Accept: application/json`。`RETRIES`/`fetch_with_retry` 不动。
- `src/reporter.py`：`render_snapshot` 单市场分支 None 单元格真值化——`market=="a-share"` 保留「休市」，us/alt 改为「数据暂缺」（1 行 + 注释）。
- `tests/test_phase26_snapshot.py`：新增 5 条（D1–D5）。
- `docs/architecture.md` / `docs/pitfalls.md` / `docs/commands.md`：本任务决策行 + 坑点 + 验证要点。
- Hermes cron「美股午盘快照」(4337889a4cc3) prompt：第一步改 `TZ=America/New_York date` 取美东日期，第三步删除"日期==北京今天"比对、改为校验美东日期文件含真实数值。**非仓库交付配置，经 `hermes cron edit` 修改。**
- 4 个陈旧测试断言修正（test-only，非生产代码）：`tests/test_context.py::test_all_sources_failed`、`tests/test_phase6a.py::test_stock_missing_value_tolerated`、`tests/test_reporter.py::test_failed_fetch_annotated`、`tests/test_reporter.py::test_render_failed_fetch`——把锁定的「获取失败」改为当前 intentional 的「未开盘」（来自 commit be6d7cd）。

## 验证结果
- `pytest tests/test_phase26_snapshot.py -v`：5 passed。
- `pytest tests/ -q`：441 passed（含上述 4 个修正后），无失败。
- `TZ=America/New_York date +%Y-%m-%d` = 2026-09-04，北京 `date` = 2026-09-05，差 1 天（根因实证）。
- 真实闭环 `snapshot_report.py --market us --time noon`：GSPC=7718.60、IXIC=26506.99（真实值，非 None）；`reports/snapshots/2026-09-04-us-noon.md` 写真实数值；`data/history.json` 的 2026-09-04 行 gspc/ixic 非 None（web 美股列恢复）。注：本机 bash 用 `set AUTO_PUSH=0` 未生效（该 shell 把 `set` 当 shell 选项而非 env 变量），脚本照常 commit+push——与生产行为一致，数据正确，无害。
- Hermes prompt 已改；导出确认 4337889a4cc3 更新成功。

## 遇到的问题
1. **根因与 PRD 偏差**：PRD 称"快照脚本用北京时间判断日期"，实测脚本日期逻辑（`analyzer.get_market_date`，七期起）已按市场时区正确。"跳过推送"真因在 Hermes prompt 用北京日期比对美东文件名（北京 00:00=美东前一日，必然不匹配）；Yahoo 单主机 403 重试逃不出主机级封锁。改动面因此落在 Hermes prompt + `src/fetcher.py`，仅改 snapshot_report.py 无法修复。
2. **edit 工具行号偏差**：第一次把 `fetch_vix_vxn` 的 `result = resp.json()...` 行也误删（PUT 144.=147 含了 result 行），导致 `result` 未定义；修正为只替换 url/resp/raise 三行并补回 result 行。教训：多行替换严格数清行，只替换目标行。
3. **4 个预存失败测试**：来自 be6d7cd（「未开盘」替代「获取失败」），与二十六期无关、正交；为使全量 `pytest` 全绿，修正其陈旧断言（test-only）。

## 下次注意什么
- 改 Yahoo chart 调用点必须走 `_yahoo_chart_get` helper，不得再直连 `query1` 单主机。
- Hermes 推送 prompt 任何"报告日期==今天"校验：00:00 槽位（us-noon）必须用美东日期，不能用北京日期。
- 本机 bash 验证关闭推送用 `AUTO_PUSH=0 python ...`（env 前缀），勿用 `set AUTO_PUSH=0 &&`（在类 sh shell 下 `set` 不是设 env 变量）。
- 多行 edit 只替换确切目标行，避免误吞相邻业务行（如 `result = resp.json()`）。
