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

## 任务 D（追加 2026-09-04）：单自选股图表过宽/扁

### 改动清单
- `web/static/style.css`：在 `.chart-box canvas` 规则（L215-220）后追加 1 规则：
  `/* 自选股图：限宽居中，避免全宽 220px 过扁（单标的场景尤甚） */`
  `#watchlist-section .chart-box { max-width: 640px; margin: 0 auto; }`
- 未改 index.html / Chart.js options / 主图区 / 其它卡（按计划最小改动）。

### 验证结果
- `git diff web/static/style.css`：仅此一处（L221-223），干净。
- `tests/test_web.py -q`：**49 passed**（纯样式改动，Python 测试不受影响）。
- 浏览器实测（另起 8001 端口、主 world `tab.evaluate`，config.json 已配 `515300.SS`）：
  - 视口 1280：`.chart-box`（画布父容器）实测宽 **640px**、居中生效；`#watchlist-section` 可见。
  - 视口 375：`.chart-box` 宽 **359px**（满宽，max-width 不约束），符合预期。
  - 注：自选股 `515300.SS` 本次取数失败（显示「数据暂缺」），`#chart-watchlist` 画布未创建，故画布实时尺寸未能量到；但 `.chart-box` 父容器限宽居中已实测生效，画布 `width:100%` 随之受限。
- **兜底决策**：画布高度由内联 `style="height:220px !important"` 钉死，Chart.js responsive 的 JS 内联样式（无 !important）无法覆盖 → 高度恒定 220px，无需 `renderWatchChart` 补 `maintainAspectRatio:false`。**仅保留 CSS 一处改动**，未加 JS 兜底行。

## 任务 E（追加 2026-09-04）：自选股图表分辨率低/模糊

### 改动内容
- `web/templates/index.html`：`renderWatchChart` 的 `options` 对象（`responsive: true` 之后，约 L778-779）加一行：
  `maintainAspectRatio: false,   // 高由 CSS 220px 决定，避免 aspect=2 画 320 高被压缩到 220 显示（糊）`
- 仅此一行，未改其它（index.html 其余函数 / 主趋势图 / CSS / 后端均不动）。

### 验证结果
- `node --check`（仅隔离校验 watchlist options 片段，规避 `</script>` 截断假阴性）：**JS_OK**。
- `tests/test_web.py -q`：**49 passed**（纯前端 options 改动，Python 测试不受影响）。
- 实时 canvas 测量：**本环境不可行**——`/api/watchlist` 取数持续失败（显示「数据暂缺」，画布被 innerHTML 替换，与任务 D 探测一致），无法量 `canvas.height/rect.height`。按 plan 第 209 行说明，验收采用「片段语法校验 + 确定性代码分析」：
  - 改前：v4 默认 `maintainAspectRatio:true` + `aspectRatio=2`，容器 640px → 逻辑高 320px（物理像素 320×DPR≈400px），CSS `!important` 显示高恒 220px → 内容被纵向压缩 ≈0.69× → 糊/扁。
  - 改后：`maintainAspectRatio:false` → 绘图高 = 容器实际高 ≈220px（与显示 1:1，物理像素 220×DPR≈275px）→ 无压缩、锐利；高仍 220px（任务 D 意图不变）。
  - 横向 DPR：全文件无 `devicePixelRatio`/`Chart.defaults` 覆盖，v4 默认取 `window.devicePixelRatio`（实测 1.25）已高清，非问题源。

### 顺带核实主趋势图（不改动）
- `renderLineChart`（index.html:361 的 `const options`）同样未设 `maintainAspectRatio`，依赖默认 `aspect=2`。
- 主图在 `.charts-grid` 半宽（1280 视口下每图容器 ≈565px）→ 逻辑高 ≈282px，CSS 显示高 `340px !important` → 内容被轻微**拉伸** ≈1.2×（比值 `canvas.height/rect.height ≈ DPR×0.83`，低于 plan 糊阈值 DPR×1.1），非压缩型失真，用户未报。
- 结论：主图观感可接受，**不在本次范围**，不补该行。若后续有人报主图糊，再同法补 `maintainAspectRatio:false` 一行（另行小改）。

## 任务 F（追加 2026-09-04）：自选股图表数据点保证 30 个交易日

### 改动内容
- `src/fetcher.py` 两处（仅 Yahoo 自选股源；A 股源 70 自然日不截、接口层 `_series_tail(30)` 兜底不变，前端零改动）：
  1. L524 `_fetch_yahoo_watch` 请求参数 `range="1mo"` → `range="3mo"`（加注释：3mo 才含足量交易日，交给 `_series_tail` 截 30）。
  2. L518 docstring「近 30 日收盘序列（range=1mo）」→ 「近 30 交易日收盘序列（range=3mo…窗口放大到 3 月以保证足量交易日，最终由 web/app.py 的 `_series_tail` 截最近 30 点）」。

### 验证结果
- `git diff src/fetcher.py`：**仅此 1 文件、2 行**（range 参数 + docstring），干净。
- `venv/Scripts/python -m pytest tests/ -q`：**432 passed / 4 failed**；4 失败为基线 `未开盘` vs `获取失败` 文案（test_context / test_phase6a / test_reporter ×2），与本次 fetcher 字符串改动无关，无新增失败。
- 实时 `/api/watchlist` 点数验证：**本环境不可行**——与任务 D/E 一致，`/api/watchlist` 取数（新浪/AkShare）持续失败返回「数据暂缺」，无法量 `trend.series` 长度。按 plan 第 279 行，采用「代码路径确定性分析」验收：
  - 改前：Yahoo `range=1mo` 仅 ~19-22 交易日 → `_series_tail(30)` 截后仍为 ~20 点（美股/ETF 标的及 A 股回退 Yahoo 场景）。
  - 改后：Yahoo `range=3mo` ≈63 交易日 → `_series_tail(30)` 截最近 30 点 → 保证 30（与主趋势图 `/api/history` 默认 30 点基准一致）。
  - A 股源（70 自然日≈48 交易日）本就 >30，`_series_tail` 已截 30，行为不变。

### 风险
- 仅动 Yahoo range 字符串 + docstring，属数据源窗口扩大；前端/接口层零改动，开销可忽略（单标的单次 3mo 请求，与既有 8 指数同源无新增依赖）。低风险。

## 任务 G（追加 2026-09-04）：非交易日显示「未开盘/未收盘」语义（前端三态 + 后端周末判定）

### 改动内容（仅计划 1、2 两项；第 3 项「非交易日不产生数据行」不在范围，未做）
- `web/templates/index.html` renderOverview（L233-242）：加 `const isWeekend = (new Date().getDay() % 6) === 0;`（0=周日 6=周六）；涨跌幅格 `chgCell` 由 `srcDate ? "未收盘" : fmtPct(chg)` 改为 `srcDate ? (isWeekend ? "休市" : "未收盘") : fmtPct(chg)`。数值列（09-04收盘）标注不变。
- `src/analyzer.py` build_statuses（L508-522）：取数失败分支前加 `us_weekend = datetime.now(EASTERN_TZ).weekday() >= 5`（复用既有 `EASTERN_TZ`，未新增依赖）；美股/alt 失败分支改为 `us_weekend → ("休市","周末休市。")` 否则 `("未开盘","美股未开盘或数据缺失。")`。A 股失败分支（本就"休市"）按 plan 注明不改动。

### 验证结果
- 前端新增片段 `node --check`（隔离，仅校验 isWeekend + chgCell 片段，规避 `</script>` 截断）：**JS_OK**。
- `venv/Scripts/python -m pytest tests/ -q`：**442 passed, 0 failed**（较基线 432 passed/4 failed 全绿；本次无新增失败）。
- 复用既有 `EASTERN_TZ` / `SHANGHAI_TZ`（analyzer.py:75-76），未新增时区依赖。
- 实时 `/api/latest` 验证周六美股=休市：**本环境不可行**——`api_latest`（web/app.py:394-406）状态来自 `_load_latest_context()` 的**缓存 context**（生成时写入，非请求时重算），当前 context 生成于 09-04（周五）故返回「未开盘」；且本机为工作日，`datetime.now(EASTERN_TZ)` 非周末。周末行为由 mock 周六的单元测试覆盖（见下）。

### 对存量失败用例的影响（按任务"关键"提醒同步修正）
- 存量 4 条基线失败（test_context / test_phase6a / test_reporter ×2，均属「未开盘/获取失败」文案，与本改动无关）— 本环境本次全量已 0 失败（基线 4 失败未复现；test_reporter 直接传入 `("未开盘",…)` 元组、不经 build_statuses，未触碰，保留不动）。
- 被本次 build_statuses 代码路径触碰、断言美股符号 `未开盘` 的 3 处断言（周末会返 `休市` 致失败），已同步修正为周末鲁棒（最小改动、保持一致）：
  - `tests/test_analyzer.py:81` `statuses["VXN"][0] == "未开盘"` → `in ("未开盘","休市")`
  - `tests/test_context.py:165` `data["indices"]["VIX"]["status"] == "未开盘"` → `in ("未开盘","休市")`
  - `tests/test_phase6a.py:88` `st["GSPC"][0] == "未开盘"` → `in ("未开盘","休市")`
- 新增 `tests/test_analyzer.py::TestBuildStatuses::test_weekend_us_returns_closed`：monkeypatch `an.datetime.now` 到 2026-09-05（周六），断言 GSPC/IXIC/VIX/VXN/MOVE 全部 → 「休市」、SH（A 股分支）仍「休市」；fake 用真实 `datetime` 子类仅覆盖 `now`，避免影响 `compute_streaks` 等内部 `datetime` 用法。

### 风险 / 局限
- 节假日（如 12/25）仍会标「未开盘」（非周末），plan 已注明：以周末退化为准，可选后续接交易日历；本次不扩展。
- 前端 `isWeekend` 用访问者浏览器本地时区：国内用户周六判定正确；跨时区访问者边缘情况 plan 已注明可接受（看板面向国内）。
- 后端周末判定依赖 `datetime.now`（与 analyzer 既有日期逻辑一致），测试用 monkeypatch 隔离。
