# 实施计划 — MarketPulse 八期「A 股板块热度监控」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase8/prd.md`。七期已落地（170 条测试全绿）。

## 任务概要

- **目标**（引用 PRD Goal）：接入 AkShare 概念板块数据，日报展示当日最热门 Top 5 概念板块（名称、涨跌幅、成交额、领涨股），丰富市场情绪感知。
- **Python 侧职责**：`src/fetcher.py` 新增 `fetch_sector_heat(top_n=5)`（失败返回空列表，10s 限时）；`src/reporter.py` 日报 A 股板块后新增「🔥 A 股热点板块 Top 5」表格、`generate_context` 扩展 `sector_heat` 字段；`daily_report.py` 取板块数据传入 reporter；板块异动注入 `search_keywords`（不触发独立告警）；零新依赖（akshare 已在 requirements.txt）。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，基线 170，新增 test_phase8.py）
  - `venv/Scripts/python daily_report.py`（日报闭环，检查板块表格 + context）
  - 断网/限流场景：板块容错返回「数据暂缺」，退出码 0

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| SYMBOLS 注册表 | `src/fetcher.py` 8 键（七期加 CYB）；`fetch_all()` 遍历 SYMBOLS 带 2s 源间节流。**板块取数是独立单请求，不参与 SYMBOLS 循环** |
| akshare 现状 | `requirements.txt` 已含 `akshare>=1.18.0`；`fetch_from_akshare` 已用 `ak.stock_zh_index_daily`（A 股指数取数）。**`ak.stock_sector_spot` 可用** |
| **实测 API 结构（与 PRD 记载有差异，见设计 B）** | `ak.stock_sector_spot(indicator="概念")` → 175 行 × 13 列，实测无 null。**数据源实际是新浪**（`money.finance.sina.com.cn/q/view/newFLJK.php`），非东财；**akshare 内部 `requests.get` 无 timeout 参数**——网络异常时可无限挂起，PRD「超时 ≤10 秒」约束必须由我方限时实现（设计 A） |
| **实测列名** | `['label','板块','公司家数','平均价格','涨跌额','涨跌幅','总成交量','总成交额','股票代码','个股-涨跌幅','个股-当前价','个股-涨跌额','股票名称']`。**PRD 记载的 `总成交额(元)` 实际为 `总成交额`**（int，单位元）；领涨股 = `股票名称` 列（板块内涨幅最大个股） |
| **实测格式化样本** | 水产品 3.79% / 1370489337 元 → `{'name':'水产品','change':3.79,'turnover':'13.7亿','top_stock':'中水渔业'}`——与 PRD 返回格式示例完全一致（成交额 ÷1e8 保留 1 位） |
| reporter.py | `render_report(date, values, changes, statuses, summary, has_history, trend_chart=None)`——A 股板块表格渲染后直接接波动率章节，**需插入板块章节**；`generate_context(date, values, changes, statuses, last_values)` 五键 payload，**需加 sector_heat 键** |
| analyzer.py | `build_search_keywords(date, breaches)` 方向感知（surge/drop）、计数上限 5、常规日 1 个 "market summary {date}"。**PRD 决策 6「板块异动写入 search_keywords」落点** |
| daily_report.py | 编排：取数 → 算涨跌幅 → 渲染 → 写报告 → 告警 → 历史 → 缓存 → context。**板块取数插入 fetch_all 之后**，失败不中断 |
| 既有测试 | 170 条。`render_report`/`generate_context`/`build_search_keywords` **全部加默认参数**（`sector_heat=None`）→ 既有调用与断言零改动（test_context.py 断言具体字段值，不断言键集合，加键安全） |
| 快照入口 | `snapshot_report.py` 不涉及——PRD 只要求日报展示板块，快照不加（保持最小 diff） |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **数据来源**：AkShare `stock_sector_spot(indicator="概念")`，已验证可用。
2. **展示数量**：Top 5 按涨跌幅排序。
3. **展示位置**：日报「A 股大盘」表格下方，新增「🔥 A 股热点板块 Top 5」。
4. **容错**：AkShare 失败返回空列表，不影响日报。
5. **context 扩展**：板块数据写入 context.json 供 AI 解读。
6. **不加新告警**：板块异动写入 search_keywords，不触发独立告警。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **线程限时 10s**：`fetch_sector_heat` 用 daemon 线程 + `join(SECTOR_TIMEOUT=10)`（复用 `render_trend_chart` 的 CHART_TIMEOUT join 模式，Windows 无 SIGALRM）；超时记日志返回 `[]` | akshare 新浪接口 `requests.get` **无 timeout 参数**，网络异常可无限挂起；PRD 约束「板块获取超时 ≤10 秒」必须显式实现。实测正常请求 ~2-3s（含 akshare import 冷启动），10s 余量充足 |
| B | **列名以实测为准**：成交额列用 `总成交额`（非 PRD 记载的 `总成交额(元)`）；解析时校验必需列存在（`板块`/`涨跌幅`/`总成交额`/`股票名称`），缺列视为失败返回 `[]` | 实测列名与 PRD 记载不符（akshare 版本差异）；必需列校验防列名漂移崩溃，写入 pitfalls |
| C | **板块异动阈值 ±5%**：`analyzer.py` 新增常量 `SECTOR_ALERT_PCT = 5.0`；`abs(change) >= 5.0` 视为板块异动（阈值边界：≥ 触发，与告警"严格大于"语义区分——板块异动非告警，用 ≥ 更宽松） | PRD 决策 6 未给阈值；5% 与 A 股板块日涨幅量级匹配（实测 Top1 水产品仅 3.79%，常态不触发）；常量而非 config——PRD 未要求配置化，保持 diff 最小，可后续外置 |
| D | **关键词格式与既有同构**：异动板块生成 `f"{板块名} {surge|drop} {date}"`（方向感知，change>=0 用 surge）；`build_search_keywords(date, breaches, sector_heat=None)` 扩展签名，**默认 None 保持既有行为零改动**；词序 = breach 词 → sector 词 → 定向词（breach 日），统一 `[:5]` 截断；无任何异动仍 1 个 "market summary {date}" | 中文板块名 + 英文方向词，tavily 支持中文搜索；与既有方向感知模式一致（pitfalls 决策 C）；sector 词追加不挤掉指数异动词 |
| E | **默认参数透传**：`render_report(..., sector_heat=None)`、`generate_context(..., sector_heat=None)`；表格**恒渲染**（含空列表），数据为空时单行 `\| 数据暂缺 \| — \| — \| — \|` | PRD「失败时显示数据暂缺」；默认参数保证既有 170 条测试零改动 |
| F | **入口接线位置**：`daily_report.py` 在 `fetch_all()` 之后调 `fetch_sector_heat()`（独立容错，失败返回 [] 记日志），渲染与 context 都传同一份数据；快照入口不动 | 板块数据不阻塞指数主流程（10s 限时兜底）；A 股休市日新浪返回最近交易日板块数据，日报在美东收盘后运行、A 股已收盘，语义正确 |

## config.json 结构

**不新增任何配置段。** 阈值 `SECTOR_ALERT_PCT` 为 analyzer 常量（设计 C），不接入 env/config——PRD 约束零新依赖、未要求配置化。

## 数据格式（fetcher 返回 → 报告/context 共用）

```python
# fetch_sector_heat(top_n=5) -> list[dict]
[
    {"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"},
    {"name": "生物育种", "change": 3.63, "turnover": "72.2亿", "top_stock": "敦煌种业"},
    ...
]
```

- `name` = `板块` 列；`change` = `涨跌幅` round 2 位（float）；`turnover` = `总成交额 / 1e8` 保留 1 位 + "亿"；`top_stock` = `股票名称` 列。
- 排序：`df.sort_values("涨跌幅", ascending=False).head(top_n)`；**负涨幅日 Top5 也可能全为负**（行情差时），表格正常展示负值，不做过滤（Top5 语义 = 当日最强，无论正负）。

## 文件清单

### 修改

| 文件 | 改动 | 预估 |
|---|---|---|
| `src/fetcher.py` | `import threading`；新增 `SECTOR_TIMEOUT = 10` 常量 + `fetch_sector_heat(top_n=5) -> list[dict]`（线程限时、必需列校验、失败返回 []、docstring 注明新浪数据源与列名实测） | +30 |
| `src/analyzer.py` | 新增 `SECTOR_ALERT_PCT = 5.0`；`build_search_keywords(date, breaches, sector_heat=None)` 扩展（sector 词注入 + 截断 5） | +8 |
| `src/reporter.py` | `render_report` 加 `sector_heat=None`：A 股板块表格后插入「🔥 A 股热点板块 Top 5」章节（4 列，空数据「数据暂缺」行）；`generate_context` 加 `sector_heat=None`：payload 加 `sector_heat` 键 + 传 sector 给 `build_search_keywords` | +28 |
| `daily_report.py` | `fetch_sector_heat()` 取板块 → 传 `render_report(..., sector_heat=...)` 与 `generate_context(..., sector_heat=...)`；取数失败已由 fetcher 容错返回 [] | +4 |
| `docs/architecture.md` | 模块表（fetcher 职责补板块热度）、数据流、决策表（设计 A-E） | — |
| `docs/commands.md` | 验证矩阵补板块表格/context sector_heat/断网容错断言 | — |
| `docs/pitfalls.md` | 八期小节（列名漂移、新浪无 timeout、板块异动关键词） | — |
| `AGENTS.md` | 项目地图：fetcher 职责补板块、context 六键 | — |

### 新增

| 文件 | 内容 | 预估 |
|---|---|---|
| `tests/test_phase8.py` | 八期专项测试（见下「测试设计」） | ~+110 |

**不改**：`src/config.py`、`src/alerter.py`、`src/analyzer.py` 除 `build_search_keywords` 外、`snapshot_report.py`、`render_trend_chart`、`render_snapshot`、`requirements.txt`、`.env`、`config.json`、既有测试文件（全部走默认参数，零改动）。

## 测试设计

### 新增 tests/test_phase8.py（不联网）

- **TestFetchSectorHeat**：构造 6 行 DataFrame（含列名实测结构）monkeypatch `ak.stock_sector_spot` → `fetch_sector_heat()` 返回 Top 5、按涨跌幅降序、`turnover` 为 "X.X亿"（如 1370489337 → "13.7亿"）、`change` round 2 位、`top_stock` 取 `股票名称`；`top_n=3` 时返回 3 条。
- **TestFetchSectorHeatFailure**：① `stock_sector_spot` 抛异常 → 返回 `[]`；② 缺必需列（无 `总成交额`）→ 返回 `[]`；③ 超时：monkeypatch `SECTOR_TIMEOUT` 为 0.05 + `stock_sector_spot` sleep 0.5 → 返回 `[]`（线程限时路径，复用 render_trend_chart 超时测试模式）。全部断言不抛异常。
- **TestRenderReportSectorTable**：`render_report(..., sector_heat=[3 条])` → 含「🔥 A 股热点板块 Top 5」标题、板块行 `| 水产品 | +3.79% | 13.7亿 | 中水渔业 |`（正号）、负板块 `-2.50%`；`sector_heat=[]` → 单行「数据暂缺」；`sector_heat=None`（不传）→ 同「数据暂缺」，且既有章节完整（回归既有 8 指数断言）。
- **TestGenerateContextSector**：`generate_context(..., sector_heat=[{name:"创新药", change:5.2, ...}])` → JSON 含 `sector_heat` 键且值透传；`search_keywords` 含 `"创新药 surge 2026-08-30"`；`sector_heat=None` → `sector_heat == []`、`search_keywords == ["market summary ..."]`（既有行为回归）。
- **TestBuildSearchKeywordsSector**：无 breach + 异动板块（change=5.2）→ `["创新药 surge {date}"]`；无 breach + 无异动板块（change=3.79）→ `["market summary {date}"]`（阈值 5.0 边界，3.79 < 5 不注入）；有 breach + 异动板块 → breach 词在前、板块词在后、总数 ≤5；板块 change 恰好 5.0 → 注入（≥ 触发）。
- **TestDailyReportWiring**（可选，若需锁编排）：monkeypatch `fetch_sector_heat`/`render_report`/`generate_context` 断言 sector 数据透传——与七期 TestSnapshotEntryOrchestration 同模式。

### 既有测试影响

- `build_search_keywords`/`render_report`/`generate_context` 加默认参数 → **零改动**。
- `test_reporter.py::test_no_unreplaced_placeholder` 断言 `count == 8`：板块表用「数据暂缺」独立文案，不受影响。
- `test_context.py` 断言具体字段值、不断言键集合 → `sector_heat` 新键安全。
- `daily_report.py` 无对应单测文件（编排由手动验证覆盖）。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | fetcher：`fetch_sector_heat` + 线程限时 + 列校验 | src/fetcher.py | 列名漂移；线程超时逻辑 | `venv/Scripts/python -c "from src.fetcher import fetch_sector_heat; print(fetch_sector_heat())"`（真实网络，验证返回格式）+ TestFetchSectorHeat |
| 2 | analyzer：`SECTOR_ALERT_PCT` + `build_search_keywords` 扩展 | src/analyzer.py | 默认参数回归破坏既有断言 | `venv/Scripts/python -m pytest tests/test_context.py -v`（TestBuildSearchKeywords 全绿） |
| 3 | reporter：render_report 板块章节 + generate_context sector_heat | src/reporter.py | 章节位置插入破坏既有模板断言 | `venv/Scripts/python -m pytest tests/test_reporter.py tests/test_context.py -v` |
| 4 | daily_report.py 接线 | daily_report.py | sector 数据未透传 | `venv/Scripts/python daily_report.py` 实际运行（检查报告与 context） |
| 5 | 新增 test_phase8.py | tests/test_phase8.py | 线程超时测试 flaky | `venv/Scripts/python -m pytest tests/test_phase8.py -v` |
| 6 | 文档同步（architecture/commands/pitfalls/AGENTS） | 上述 4 文件 | 文档与实现漂移 | 逐份核对最终代码 |
| 7 | 手动验证矩阵 + 行数预算 + `git diff` 审查 | 全部 | 增量超预算 | 见下方矩阵；源码增量 ≤ ~70 行（fetcher 30 + analyzer 8 + reporter 28 + daily 4） |

### 手动验证矩阵（步骤 4/7，实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 板块表格 | `venv/Scripts/python daily_report.py` | 报告 A 股板块下方含「🔥 A 股热点板块 Top 5」表格 5 行（板块/涨跌幅/成交额/领涨股），涨跌幅带正负号、成交额 "X.X亿" |
| context 扩展 | 检查 `context/{date}.json` | 含 `sector_heat` 键（5 条 dict 数组） |
| 断网容错 | 断网/屏蔽新浪域名后运行 `daily_report.py` | 退出码 0，报告板块表显示「数据暂缺」，其余章节完整；context `sector_heat == []` |
| 板块异动关键词 | 异动板块（abs(change)>=5）当日检查 context | `search_keywords` 含 `"{板块名} surge/drop {date}"` |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（基线 170 + 新增 ≈ 185+，无网络） |
| 恢复 | 无模拟数据残留（板块取数不写任何持久化） | 生产数据无残留 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| **akshare 新浪接口无 timeout**（网络异常无限挂起） | 设计 A 线程限时 10s（与 render_trend_chart 同模式）；超时返回 [] 不中断日报 |
| **列名漂移**（akshare 版本升级改列名） | 设计 B 必需列校验，缺列视为失败返回 []；写入 pitfalls |
| 中文板块名进 search_keywords | tavily 支持中文搜索；方向词 surge/drop 保留英文与既有语义一致；Hermes Prompt 同步说明 |
| 新浪接口限流/反爬 | 容错 [] + 「数据暂缺」；板块数据非日报核心，不影响既有 8 指数闭环 |
| search_keywords 计数截断挤掉板块词 | 设计 D 词序 breach 优先；异动板块多时接受截断（上限 5 是既有契约） |
| 板块异动阈值未配置化 | 设计 C 常量 5.0，标注可后续外置（PRD 未要求，保持 diff 最小） |
| 行情差时 Top5 全为负 | 表格正常展示负值（Top5 语义 = 当日最强）；单测覆盖负值格式化 |
| 周末/休市运行 | 新浪返回最近交易日板块数据，日报语义正确；不特殊处理 |

## 不做什么

- 不加新依赖、不改 `config.py`/`config.json`（板块异动阈值用常量，不接入配置链）。
- 不加板块告警/独立 alerts 文件（决策 6：只进 search_keywords）。
- 快照入口不加板块（PRD 只要求日报）。
- 不改 `render_trend_chart`、`render_snapshot`、`alerter.py`、`requirements.txt`、`.env`。
- 不做板块历史存储/趋势图（PRD 未要求）。
- 不重排既有报告章节顺序（板块章节只插在 A 股板块之后）。

## 预计影响范围

- **新增文件**：`tests/test_phase8.py`（~110）。
- **修改文件**：`src/fetcher.py`（+30）、`src/analyzer.py`（+8）、`src/reporter.py`（+28）、`daily_report.py`（+4）、docs 4 份。
- **不受影响**：`src/config.py`、`src/alerter.py`、`snapshot_report.py`、既有 9 个测试文件（默认参数零改动）、`requirements.txt`、`.env`、`config.json`。
- **交付清单（非仓库文件）**：Hermes Prompt 同步——① context 新增 `sector_heat` 字段（5 条 dict：name/change/turnover/top_stock）；② `search_keywords` 可能含中文板块异动词（`"{板块名} surge/drop {date}"`）；③ 日报新增板块章节供解读参考。

## 确认

- [ ] 人已审阅计划
- [ ] 设计 A（线程限时 10s 防新浪接口无限挂起）/ B（列名以实测为准：`总成交额`、`股票名称`，必需列校验）/ C（板块异动阈值 ±5% 常量，关键词 `{板块名} {surge|drop} {date}`）/ D（`build_search_keywords` 默认参数扩展，词序 breach→sector→定向，截断 5）/ E（`render_report`/`generate_context` 默认参数，表格恒渲染空数据显示「数据暂缺」）/ F（入口接线在 fetch_all 之后，快照不动）已确认
- [ ] 实测列名与 PRD 记载差异（`总成交额(元)` → `总成交额`）已确认按实测实现
- [ ] 板块异动阈值 5.0 作为常量（不接入 config）已确认
- [ ] 既有 170 条测试零改动（全部走默认参数）已确认
- [ ] 没有遗漏测试（取数成功/失败/缺列/超时、表格渲染/空态/负值、context 键、关键词注入/阈值边界/计数、入口接线全覆盖）
- [ ] 没有引入不必要依赖或额外配置段
