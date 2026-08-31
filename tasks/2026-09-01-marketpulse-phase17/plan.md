# MarketPulse 十七期 Plan — Web 看板交互增强

> 任务卡：`tasks/2026-09-01-marketpulse-phase17/prd.md`
> 目标：看板从"静态展示最近 7 天"升级为"主动探索"——时间范围切换、指标筛选、悬停详情、表格排序、数据更新时间提示。
> 原则：零侵入主流程（不碰 `daily_report.py` / `snapshot_report.py` / `src/*`），web 进程保持只读，零新增 Python 依赖，Chart.js + 原生 JS 不换框架。

## 待确认决策

1. **`days` 参数语义：交易日条数 vs 自然日**。推荐**交易日条数**——过滤周末后取最近 N 条记录（与现有 7 日行为完全一致，`days=7` 返回与今日相同结果；PRD「最近 30 条数据」按此落地，`days=90` 恰好等于 history 保留窗口 90 条）。备选：按自然日过滤（复杂且与"近 30 日"习惯不符）。
2. **悬停详情是否显示原始数值**。推荐**新增 `raw` 字段**（与 `values` 等长，GLD 同样 ×10 显示值，与图线一致）：PRD「Done When」字面要求"日期 + 各指数值"，现 tooltip 只显示相对基准百分比；加 `raw` 后 tooltip 显示"标普500 105.00 (+5.00%)"。代价：`test_api_history_series_shape` 断言键集需加 `raw`。
3. **缩放/平移实现**。推荐**引入 chartjs-plugin-zoom（官方 Chart.js 插件，CDN 加载）**，配置 `wheel.enabled + modifierKey:'ctrl'`（避免与页面滚轮冲突）、`pan` 拖拽平移、`limits` 限制缩放范围；脚本 `onerror` 置 `window.__zoomFailed`，插件缺失时图表照常渲染仅无缩放（与现有 CDN 降级纪律一致）。备选：不做（Done When 未列 zoom，7/30/90 按钮已覆盖时间导航）——若确认不做则删减执行步骤 4 中 zoom 部分。
4. **`change_7d` 键名保留 vs 改名**。推荐**保留键名**（`change_7d`，向后兼容，API 形状不变），语义改为"所选窗口涨跌幅"，前端按 `state.days` 动态显示标签（`30D 涨跌幅`）；改名为 `change_window` 会破坏既有 API 消费者与测试断言，违反 PRD「API 不改动现有调用方式」。
5. **`symbols` 参数容错**。推荐：逗号分隔、大小写不敏感（`.upper()`）、按 **SYMBOLS 注册表顺序**输出（确定性，忽略参数传序）；未知符号静默忽略；全部未知 → `series: []`（dates 仍返回）；空串/缺省 → 全部。备选：未知符号返回 400（过严，前端筛选永远传合法键，无收益）。

## 影响分析

### 功能 1：时间范围选择器（高）

- **实现**：`/api/history` 加 `days` Query 参数（`Query(30, ge=1, le=90)`）；`_build_history_payload` 重构为读全量历史 → 过滤周末 → 取最近 N 条（替代现 `_last_records(14)` 再截 7 的启发式——对 90 天该启发式会失效，保留窗口只有 90 条）。前端顶部加 7天/30天/90天 分段按钮，点击更新 `state.days` 后统一刷新。
- **文件**：`web/app.py`（+15 行）、`web/templates/index.html`（+30 行）、`web/static/style.css`（+20 行）。
- **注意**：默认值 7→30 是 PRD 要求的**行为变更**，既有测试 `test_api_history` 断言 `len(dates) <= 7` 与 vix null 索引（1→2）必须同步更新。

### 功能 2：指标筛选（高）

- **实现**：`/api/history` 加 `symbols` Query 参数（新增 `_resolve_symbols` 纯函数，可单测）；前端图表区上方渲染 10 个复选框（色点 + 短标签），勾选状态存入 `state.selected`，变更后以 `?symbols=` 重新 fetch；筛选同时作用于图表与概览表（风险表"表格图表不同步"正解：单一 `refresh()` 管线）。
- **文件**：`web/app.py`（+12 行 `_resolve_symbols`）、`index.html`（+40 行 JS/HTML）、`style.css`（+15 行）。
- **注意**：GLD/BTC 柱状图组同样按 `selected` 过滤；整组无选中时图表区显示「无选中指标」占位（不崩、不白屏）。

### 功能 3：图表交互优化（中）

- **实现**：
  - 悬停详情：现有 tooltip 已是 `mode:'index'`（悬停任意点显示该日期全部曲线），补 `raw` 值显示（决策 2）。
  - 缩放/平移：chartjs-plugin-zoom CDN + 注册表注册（决策 3）。
- **文件**：`index.html`（+25 行）、`style.css`（+5 行）。
- **注意**：**Chart.js 重渲染必须 `chart.destroy()` 旧实例**（canvas 复用报 "Canvas is already in use"）；`charts` 注册表按组 id 存实例。刷新动画降为 `duration: 300`，90 点重绘远低于 1s 约束。

### 功能 4：数据表格排序（中）

- **实现**：纯前端 JS——概览表「收盘」「涨跌幅」表头加 `data-sort` 属性，点击在 升序→降序→原序 间切换，显示 ▲/▼ 指示；null 值恒排最后（升/降序均如此）；排序在"按 selected 过滤"之后执行。
- **文件**：`index.html`（+30 行）、`style.css`（+10 行）。
- **注意**：排序只作用于 `renderOverview` 的重排，不改 `/api/latest` 返回结构（保持 API 形状）。

### 功能 5：数据更新提示（低）

- **实现**：topbar `#overview-date` 文案改为 `数据截至：{latest.date}`（数据源已有）。
- **文件**：`index.html`（+2 行）。

### 总体影响

| 文件 | 动作 | 代码量 |
|---|---|---|
| `web/app.py` | `_build_history_payload(days, symbols)` 重构 + `_resolve_symbols` 新增 + 端点 Query 参数 + series 增 `raw` | +30 行净 |
| `web/templates/index.html` | 范围按钮 / 筛选复选框 / 动态标题 / 可排序表头 / state+refresh 管线 / chart destroy / tooltip raw / zoom 插件 | +150 行净 |
| `web/static/style.css` | 分段按钮、复选框 chips、排序指示、移动端适配 | +70 行 |
| `tests/test_web.py` | 更新 2 条（默认 30 天、series 键集），新增 ~10 条（days/symbols/组合/容错/raw） | +130 行 |

无 Python 依赖变更；无 `src/*`、入口脚本改动；web 仍只读。

## 修改清单

### `web/app.py`

1. `_build_history_payload(days: int = 30, symbols: str | None = None) -> dict`：
   - 读全量 `_load_history_raw()` → 过滤周末 → `weekdays[-days:]`（`days > 记录数` 时全取）。
   - `keys = _resolve_symbols(symbols)`；每序列除 `values/change_7d` 外新增 `raw`（等长，GLD 已 ×10，与图线一致）。
   - `change_7d` 键名保留，docstring 注明"窗口涨跌幅"。
2. 新增 `_resolve_symbols(symbols: str | None) -> list[str]`：None/空白 → 全部 SYMBOLS 键；否则 split(',') → strip → upper → 按 SYMBOLS 注册表序过滤；解析结果空 → `[]`。
3. `api_history` 端点签名：`days: int = Query(30, ge=1, le=90)`, `symbols: str | None = Query(None)`，透传给 `_build_history_payload`。
4. `_last_records` / `_compute_latest` / `/api/latest` 不动。

### `web/templates/index.html`

1. HTML：topbar 下（或图表卡片头部）加 `.range-bar`（3 按钮，`data-days`）；图表卡片标题改 `<h2>近 <span id="range-label">30</span> 日趋势</h2>`；标题旁加 `<div id="symbol-filter">`（JS 渲染复选框）；概览表「收盘」「涨跌幅」表头加 `data-sort="value|change_pct"` + 排序指示 span。
2. JS：
   - `SHORT` 短标签映射（gspc→标普500 等 10 项）；`state = { days: 30, selected: Set(10 键), sort: {key:null, dir:1} }`；`charts = {}` 实例注册表。
   - `buildQuery()` → `/api/history?days=${days}&symbols=${[...selected].join(',')}`。
   - 单一 `refresh()`：fetch history → `charts[g.id].destroy()` → `renderCharts`；fetch latest → `renderOverview`（filter→sort→渲染）+ `renderSector`。alerts 仅初始加载一次。
   - `renderLineChart` tooltip label 回调：`label + " " + fmtNum(raw) + " (" + fmtPct(y-100) + ")"`（raw 从 `ctx.raw` 取）。
   - `renderBarChart` tooltip 文案 `7D 涨跌幅:` → 动态 `${state.days}D 涨跌幅:`。
   - `renderMeta` / 空组占位（「无选中指标」）。
   - 复选框渲染 + 全选/清空按钮；排序表头点击切换（▲/▼，null 恒后）。
   - zoom 插件：`<script src="chartjs-plugin-zoom CDN" onerror="window.__zoomFailed=true">`；`window.ChartZoom && !window.__zoomFailed` 时注册 `registerables`，options 加 `zoom: {wheel:{enabled:true, modifierKey:'ctrl'}, pan:{enabled:true, modifierKey:'ctrl'}, limits:{y:{min:'original',max:'original'}}}`。
3. topbar：`数据截至：` 前缀。

### `web/static/style.css`

1. `.range-bar`（flex 分段按钮 + `.active` 高亮 + 移动端 wrap）。
2. `.symbol-filter`（flex-wrap chips：色点 + 标签 + `:hover` / checked 态）。
3. `.th-sort`（cursor:pointer、active 着色、▲/▼ 指示）。
4. 768px / 480px 断点补充：范围按钮、筛选区换行不溢出。

### `tests/test_web.py`

更新：
- `test_api_history`：默认 30 天 → `len(dates) == 8`（夹具 8 条全周内），vix null 索引 1→2（08-05 在全量列表 index 2）。
- `test_api_history_series_shape`：键集加 `raw`。

新增：
- `test_api_history_days_param`（`?days=3` → 3 条）、`test_api_history_days_caps`（`?days=90` → 全量）、`test_api_history_days_invalid`（`?days=0` / `?days=91` → 422）。
- `test_api_history_symbols_param`（`?symbols=VIX,GSPC` → 键序 `["gspc","vix"]` 注册表序）、大小写混合、未知符号忽略、全未知 → `series == []`、空串 → 全 10。
- `test_api_history_combined`（`?days=3&symbols=VIX,GSPC`）。
- `test_api_history_raw_values`（gld raw = 历史 ×10）。
- `test_resolve_symbols` 纯函数（None/空白/大小写/未知/全未知）。

## 执行步骤

1. **后端**：改 `web/app.py`（`_resolve_symbols` + `_build_history_payload` 重构 + 端点参数 + `raw`）。
2. **测试**：更新 `tests/test_web.py` 既有 2 条 + 新增 ~10 条 → 运行 `venv/Scripts/python -m pytest tests/test_web.py -v`（全绿后再进前端）。
3. **前端**：改 `index.html`（HTML 结构 + JS 状态管线）与 `style.css`。
4. **验证（浏览器实测）**：见下节；含 90 天切换耗时与移动端视口检查。
5. **收尾**：全量 `venv/Scripts/python -m pytest tests/ -v`；`git diff` 检查改动范围；按 AGENTS.md 写 `tasks/2026-09-01-marketpulse-phase17/journal.md`；可复用教训（Chart.js destroy、Query 参数校验、默认行为变更需同步测试）追加 `docs/pitfalls.md`。

## 验证方法

自动化：
- `venv/Scripts/python -m pytest tests/test_web.py -v`（新旧用例全绿）。
- `venv/Scripts/python -m pytest tests/ -v`（全量回归，web 独立模块不应破坏既有 231+ 用例）。
- `curl "http://127.0.0.1:8001/api/history?days=90&symbols=VIX,GSPC,SH"`：dates ≤ 90、series 恰 3 组、键序 vix/gspc/sh（注册表序）；`?days=0` → 422；无参 → 30 天默认。

浏览器实测（`venv/Scripts/python -m uvicorn web.app:app --port 8000`）：
- 点击 7/30/90 按钮：图表与表格联动刷新、标题 `近 N 日趋势` 正确、meta 标签为 `ND 涨跌幅`、无页面刷新（fetch 异步）。
- 勾选/取消指标：图表曲线与概览表行同步显隐；整组清空显示占位；全选恢复。
- 悬停图表：tooltip 显示日期 + 各指数值 + 涨跌幅；ctrl+滚轮缩放 / ctrl+拖拽平移生效。
- 点击「收盘」「涨跌幅」表头：升序→降序→原序循环，▲/▼ 指示，null 恒排最后。
- 断网/关插件（DevTools 屏蔽 CDN 域名）：图区降级文案，zoom 静默失效，页面不白屏。
- DevTools 手机模拟（375px）：范围按钮与筛选区换行不溢出，表格横滑可用。
- 90 天数据下切换时间范围，重绘耗时 < 1s（DevTools Performance 目测）。
