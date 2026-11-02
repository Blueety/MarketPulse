# MarketPulse 十七期 — Web 看板交互增强 · 执行日志

- 日期：2026-08-31
- 计划：`tasks/2026-09-01-marketpulse-phase17/plan.md`
- PRD：`tasks/2026-09-01-marketpulse-phase17/prd.md`

## 目标

看板从「静态展示最近 7 天」升级为「主动探索」：时间范围切换（7/30/90 天）、指标筛选（复选框）、悬停详情（原始值 + 涨跌幅）、表格排序（收盘 / 涨跌幅）、数据更新时间提示。零侵入主流程，web 进程只读，零新增 Python 依赖，Chart.js + 原生 JS 不换框架。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增纯函数 `_resolve_symbols(symbols)`（None/空白→全部、`split+upper`、按 SYMBOLS 注册表序过滤、未知静默忽略、全未知→`[]`）；`_build_history_payload(days=30, symbols=None)` 重构为读全量→过滤周末→取最近 `days` 条（交易日条数语义），series 增 `raw`（等长、GLD 已 ×10）；`api_history` 端点加 `days: Query(30, ge=1, le=90)` 与 `symbols: Query(None)`；`change_7d` 键名保留（语义改为窗口涨跌幅）。`_last_records` / `_compute_latest` / `/api/latest` 不动。 |
| `web/templates/index.html` | 顶部加 zoom 插件 CDN（`onerror=window.__zoomFailed`）；趋势卡片加 `.range-bar`（3 按钮 + `#range-label`）、`#symbol-filter`（JS 渲染 10 复选框 + 全选/清空）；概览表「收盘」「涨跌幅」表头加 `data-sort` + 排序指示 span；单一 `state` + `refresh()` 管线驱动历史/概览/板块（告警仅初始加载一次）；`renderCharts` 按 group id 注册 `charts` 实例、重渲染前 `destroy()`、整组无选中显示「无选中指标」占位；`renderLineChart` 加 `rawVal` 并在 tooltip 显示「标签 原始值 (涨跌幅)」、缩放配置（zoom 插件可用时）、动画降到 300ms；`renderBarChart`（GLD/BTC 柱状图组）tooltip 动态 `ND 涨跌幅`、返回实例；`renderMeta` 显示 `ND 涨跌幅`；`renderOverview` 加「数据截至：」前缀 + 按 selected 过滤 + 三态排序（升→降→原序，null 恒后）。 |
| `web/static/style.css` | 新增 `.range-bar`（分段按钮 + `.active` 高亮）、`.symbol-filter`（chips + 全选/清空、`.chip.on` 态）、`.th-sort`（cursor + 排序指示）、`.chart-empty` 占位、768/480 断点补充。 |
| `tests/test_web.py` | 更新 `test_api_history`（默认 30 天 → 8 条、vix null 索引 1→2）、`test_api_history_series_shape`（键集加 `raw`）；新增 `test_api_history_days_param` / `_days_caps` / `_days_invalid`（422）/ `_symbols_param`（注册表序、大小写、未知忽略、全未知→`[]`、空串→全 10）/ `_combined` / `_raw_values` / `test_resolve_symbols` 纯函数。 |

## 验证结果

- `venv/Scripts/python -m pytest tests/ -q` → **305 passed**（web 模块 31 passed，含 9 条新增），无回归（对比既有的 ~296 条）。
- 浏览器实测（uvicorn :8011，CDN 可达，`__chartFailed=false`、`__zoomFailed=false`、`hasChart=true`）：
  - 4 个图表实例均创建成功；`chart-gld-btc` 为 `bar`，其余 3 个为 `line`。
  - 点击 7/30/90 按钮：`#range-label` 与 `.active` 正确切换，`refresh()` 重取数据、meta 显示 `ND 涨跌幅`（如「纳斯达克 90D +7.61%」）。
  - 指标筛选：取消「标普500」→ 概览表行 10→9、图表同步隐去该曲线、`.chip.on` 计数同步；点「清空」→ 表格单行占位、4 个图区均显示「无选中指标」占位，不崩不白屏。
  - 表格排序：点击「收盘」表头三态循环，升序为 `[14.43, 19.92, 70.97, …, 77615.61]`，降序为逆序，均严格单调；null 恒排最后；▲/▼ 指示正确。
  - 悬停数据：line 数据集数据点带 `rawVal`（采样 `7443.28`），tooltip 回调可展示「原始值 (涨跌幅)」；缩放配置 `options.plugins.zoom.wheel.enabled=true` 已注入；动画 `duration=300`。
- CDN 降级路径由既有 `window.__chartFailed || !window.Chart` 分支覆盖（本次环境可达，未触发，但逻辑保持不变）。

## 遇到的问题

- `cd /d D:/AGENT/MarketPulse` 在持久 shell 报错（该 shell 不支持 `cd /d`）；改用 `bash` 工具的 `cwd` 参数。
- 浏览器 `run` 作用域中 `document` 不在顶层作用域，必须通过 `tab.evaluate(() => {...})` 访问 DOM。
- 测试脚本里 `.filter-act:last-child` 选不到「清空」按钮（chips 在其后），改用按 textContent 查找。
- 提交后 `git status` 显示 working tree clean（编辑已被自动提交至 HEAD）；`git diff` 无输出属预期，非改动丢失——solution 已落地并经测试 + 浏览器双重验证。

## 下次注意什么

- 改 `/api/history` 默认窗口（7→30）必须同步更新既有断言（条数、null 索引、键集）。
- Chart.js 重渲染务必先 `chart.destroy()`，按 group id 存实例注册表，否则报 `Canvas is already in use`。
- FastAPI `Query(ge=1, le=90)` 越界自动 422，前端无需自行校验。
- 新增 series 字段（如 `raw`）要同步 `test_api_history_series_shape` 的键集断言。
- 浏览器自动化访问 DOM 一律走 `tab.evaluate`；CDN 插件缺失用 `<script onerror>` 置标志位降级，与 Chart.js 自身 `__chartFailed` 纪律一致。
- gld-btc 在十七期明确为柱状图组（`type:"bar"` 由计划指定，复用既有 `renderBarChart` 死代码）。
