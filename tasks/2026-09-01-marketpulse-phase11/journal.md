# MarketPulse 十一期 Web 看板 — 执行日志

## 目标

FastAPI Web 看板，浏览器只读展示最近 7 天市场数据（趋势图 / 指数表格 / 板块热度 / 告警记录）。
严格按 `tasks/2026-09-01-marketpulse-phase11/plan.md` 实施，零侵入 `daily_report.py` / `snapshot_report.py` / `src/*`。

## 改动文件清单

新增：
- `requirements.txt`：+4 运行依赖（fastapi>=0.115.0 / uvicorn>=0.30.0 / jinja2>=3.1.0 / httpx>=0.27.0）。
- `web/__init__.py`：空包标记，使 `web.app` 成为常规包。
- `web/app.py`：FastAPI 应用 + 4 端点（`/` / `/api/history` / `/api/latest` / `/api/alerts`）+ 解析纯函数（`_load_history_raw` / `_last_records` / `_build_history_payload` / `_compute_latest` / `_load_latest_context` / `_load_sector_heat` / `_parse_alert_file` / `_load_alerts`）。
- `web/templates/index.html`：单页模板（Chart.js CDN + 内联 JS 调 3 个 API + 4 模块 + 降级文案）。
- `web/static/style.css`：响应式样式（桌面 2 列 / `@media (max-width:768px)` 单列，表格横向滚动）。
- `tests/test_web.py`：20 条（解析纯函数 + 端点 + 空数据容错）。

修改（仅文档同步，无代码改动）：
- `docs/architecture.md`：模块表加 Web 看板行、关键决策加十一期行、依赖边界更新为含 4 个 web 依赖。
- `docs/commands.md`：快速检查表加 uvicorn 启动行、验证要点加十一期块。
- `docs/pitfalls.md`：加「模块 web/（十一期）」5 条易错点。

未改动：`daily_report.py`、`snapshot_report.py`、`src/*`、`config.py`、`config.json`、`.gitignore`。

## 验证结果

1. 依赖安装：`venv/Scripts/pip install -r requirements.txt` 成功；`import fastapi, uvicorn, jinja2, httpx` 无错。
2. 应用导入：`from web.app import app` 无错，注册 `/` `/api/history` `/api/latest` `/api/alerts` 四个路由 + `/static` 挂载。
3. 单元测试：`pytest tests/test_web.py -v` → 20 passed。
4. 全量回归：`pytest tests/ -v` → **231 passed**（既有 211 + 新增 20，零回归）。
5. 实跑（uvicorn 起 8000）：
   - `/api/history`：dates=7、series=10 组、null 值保留（2026-08-29 vix=null 在序列中）。
   - `/api/latest`：date=2026-08-30、indices=10 键、sector_heat.gainers=5。
   - `/api/alerts`：当前 alerts/ 为空 → `[]`（空态友好）。
   - `/`：200、含 Chart.js CDN 引用。
6. 数据一致性（Python 断言）：
   - `/api/history` 末条各序列 value 与 `data/history.json` 最后一条逐值一致。
   - `/api/latest` 各指数 change_pct 与 history 相邻记录手算 `(cur-prev)/prev*100` 一致（基准 null/0 → null）。
7. 浏览器实测（headless）：概览表 10 行、板块热度 5 行、4 张趋势图均真实绘制（canvas 非空白像素 16k–21k）、告警区「暂无告警记录」、零 console 错误。
8. 移动端（375px）：charts-grid 单列（单列 track 373px）、表格横向可滚、容器 padding 14px。
9. 离线/CDN 失败降级（拦截 chart.js 请求 + 禁缓存）：4 图区显示「图表加载失败」，概览/板块/告警仍正常。

## 遇到的问题

- 路径常量 monkeypatch 落点：项目既有纪律要求解析函数引用使用方模块常量。因此 `web/app.py` 从 analyzer 导入 HISTORY_FILE/ALERTS_DIR/CONTEXT_DIR 后**重新绑定为模块级名字**并自行实现 `_load_history_raw` 等读取本模块常量，而非调用 `analyzer.load_history()`（后者引用 analyzer 常量，monkeypatch `web.app` 不生效）。这是零侵入 + 可测的关键。
- 板块热度数据源偏离 PRD 字面：PRD 写「从 history.json」，但 history.json 无板块字段；实际唯一来源是 `context/*.json` 的 `sector_heat`。已按「单独 JSON = context」落地并写入 architecture.md 备忘。
- 测试初版 `_load_alerts_desc_limit` 用统一 frontmatter 日期导致排序断言失败：改为 `make_alert(date)` 夹具生成逐日不同日期，验证按文件名倒序。
- 编辑工具多次误伤相邻行（ALERT_MD 常量被替换、import 行被吞）：已修复并复跑测试确认 20 passed。

## 下次注意什么

- 改 `web/app.py` 路径常量时，monkeypatch 必须打 `web.app` 而非 `analyzer`；新增数据解析函数一律读本模块常量。
- 板块热度如需扩展（美股 us_sector_heat / 领跌 losers），数据源仍在 context，前端加表即可，无需改后端解析（context 已含）。
- Chart.js 走 CDN，离线环境图区降级文案已兜底；若后续要完全离线，可改为本地 `web/static/chart.umd.min.js` 并改模板引用。
- 趋势图分组（4 组）与配色沿用九期既有色系；新增标的进 SYMBOLS 时前端 GROUPS/COLORS 需同步（目前写死在前端 JS）。
