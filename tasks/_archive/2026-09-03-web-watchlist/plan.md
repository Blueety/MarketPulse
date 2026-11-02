# 实施计划 — Web 看板新增「自选股」模块

> 日期：2026-09-04 ｜ 任务目录：`tasks/2026-09-03-web-watchlist/`
> 来源：`tasks/2026-09-03-web-watchlist/prd.md`（F1–F5 / NF1–NF3）
> 前置阅读已完成：AGENTS.md、docs/architecture.md、docs/commands.md、tasks/ 下相关任务（2026-09-03-context-fallback 为最近一次 web/app.py 改动）

## 1. 任务目标

在 web 看板新增「自选股」模块：展示 `config.json` 中 `watchlist.stocks` 配置的自选股（名称/当前价/涨跌幅/近 30 日趋势）+ 近 30 日折线图。数据每次刷新页面时经既有 `src/fetcher.fetch_watchlist()` 实时获取（PRD F5），无配置时模块整体隐藏（F4），取数失败显示「数据暂缺」且不影响其他模块（NF3）。

| PRD 项 | 内容 | 落地 |
|---|---|---|
| F1 | 自选股表格（名称/当前价/涨跌幅/近30日趋势） | 表格 4 列；「近30日趋势」列 = 30 日窗口涨跌幅（`change_7d` 语义，与 `/api/history` 一致） |
| F2 | 近30日趋势折线图（可选） | 表格下方 chart-box，归一化基准 100（复用既有 `_normalize_series` 语义），多标的单图、按行循环取色 |
| F3 | 配置驱动 | 端点每次请求 `load_config()["watchlist"]["stocks"]`（`src/config.py` 已暴露，零改动） |
| F4 | 无配置时隐藏 | 服务端返回 `stocks=[]` → 前端模块 `display:none`（HTML 初始即隐藏防闪） |
| F5 | 实时取数 | `GET /api/watchlist` → 端点内调 `fetch_watchlist()`（联网、零写盘，兼容 web「进程绝不写数据文件」纪律） |
| NF1 | 只改 web/app.py + index.html | 见「4. 要改的文件列表」；`src/config.py` 仅验证不改代码 |
| NF2 | 不引入新依赖 | `requests`/`akshare` 均在 `requirements.txt` 已有 |
| NF3 | 容错 | 端点内 `try/except` 降级空结构（HTTP 200，不 500，沿用既有解析函数容错风格）；单标的失败仅该行「数据暂缺」 |

### 验收标准

1. 本地 config.json 含 `watchlist.stocks`（如 `515300.SS`）时启动看板：出现「自选股」卡片，表格含 名称/当前价/涨跌幅/近30日趋势 四列真实数据，下方折线图渲染。
2. config 缺失 / `watchlist.stocks` 为空：整卡不可见（页面与现状完全一致）。
3. 配置了取数必失败的假 symbol（如 `XXXX.XX`）：该行名称保留、其余列「数据暂缺」，其他模块（概览/板块/告警）不受影响；`/api/watchlist` 返回 200。
4. `pytest tests/test_web.py -v` 新增用例全绿；全量 `pytest tests/ -v` 无回归。

## 2. 现状盘点（只读结论）

- `web/app.py`（332 行）：FastAPI + 3 端点（`/api/history` `/api/latest` `/api/alerts`）+ `/` 单页。纯解析 history/context/alerts，零写盘。模块级路径常量 `HISTORY_FILE/ALERTS_DIR/CONTEXT_DIR` 从 analyzer 重绑定；测试 monkeypatch 落点严格打在**使用方模块 `web.app`**（项目纪律，`tests/test_web.py` 文档字符串明示）。
- 既有复用件：`_normalize_series(raw)`（窗口首非空=100，返回 `(values, change_7d)`）可直接复用于自选股归一化；`_read_context_file` 式单文件容错、`_load_sector_heat` 式「失败→空结构降级」为端点容错范式。
- `src/fetcher.fetch_watchlist(stocks) -> (values, series, errors)`（二十四期已有，**不改**）：逐标的并行线程 + 整体限时 `SECTOR_TIMEOUT=10s`；`values[sym]`=当日价，`series[sym]=[(date, close), ...]`（近 30 日含当日，日期键已对齐：Yahoo 美东 / A 股北京时间）；A 股 `.SS/.SZ` 走 AkShare（新浪日线，失败回退 Yahoo），其余走 Yahoo chart `1mo/1d`；单标的失败仅记入 `errors`，全失败返回空 dict、不抛异常。
- 涨跌幅事实来源（与日报一致）：`daily_report._build_watchlist_view` 用 `series[-2]→series[-1]` 相邻日自算、`round(..., 2)`、`s[-2][1] in (None, 0)` 时 None。web 端必须复用同一公式，避免两处口径漂移。
- `src/config.py`：`load_config()["watchlist"]` = `{"stocks": [≤20 × {symbol, label}], "corr_high_threshold": 0.7}`；label 缺省回退 symbol；`_valid_watchlist` 已校验。`config.json` 项目根、gitignore 排除；conftest 将 `CONFIG_PATH` 指向不存在文件 → 测试/默认环境恒 `stocks=[]`。
- `web/templates/index.html`（727 行）：4 个 `<section class="card">`；JS 单一 `state` + `refresh()` 并行 fetch `/api/history` 与 `/api/latest`；Chart.js 4.4.1 + zoom 插件走 CDN，失败置 `window.__chartFailed` 图区降级「图表加载失败」；`fmtNum/fmtPct`、`.pos/.neg/.empty/.data-table/.chart-box/.chart-head/.chart-meta` 类均可复用；`/api/alerts` 为 DOMContentLoaded 初始一次（自选股同模式）。
- `requirements.txt` 已含 `akshare>=1.18.0`（A 股自选股取数在部署端可用）；web 测试基线 `tests/test_web.py`（563 行）用 TestClient + monkeypatch `web.app.*`。

## 3. 关键设计决策

### 决策 1：API 契约 — 单端点双结构，表格与图同源一次返回

`GET /api/watchlist` 返回：

```jsonc
{
  "stocks": [            // F1 表格行（配置序，非注册表序）
    { "symbol": "515300.SS", "label": "沪深300ETF", "value": 4.123,
      "change_pct": 1.25 }        // 当日 vs 昨收，series 相邻日自算（与日报同公式）
  ],
  "trend": {            // F2 图，与 /api/history 同构（可复用前端渲染形状）
    "dates": ["2026-07-20", "...", "2026-09-03"],   // 各标的有值日并集（字符串排序即时间序）
    "series": [
      { "key": "515300.ss", "label": "沪深300ETF",
        "values": [100.0, "..."],     // 归一化基准 100（复用 _normalize_series）
        "change_7d": 3.2,             // 窗口涨跌幅（表格「近30日趋势」列取此处）
        "raw": [4.05, "..."] }        // 对齐 dates 的实际价
    ]
  }
}
```

理由：前端 `renderLineChart(canvas, {dates}, series)` 的消费形态即「dates + 索引对齐的 values」，trend 块保持该形状 → 前端可完整复用既有图渲染思路（归一化、tooltip 显示 raw+%），后端只做一次对齐/归一化。`stocks` 与 `trend` 由同一次 `fetch_watchlist` 产出，表格与图天然一致。

**失败行语义**（与 `daily_report` 一致）：`errors[sym]` 存在或 `values[sym] is None` → `value: null`、`change_pct: null`，但 symbol/label 保留、该标的 series 有值仍入图（A 股当日盘中无收盘价 ≠ 无历史）；config 空 → `stocks: []`、`trend` 双空。

### 决策 2：日期网格 — 各标的有值日并集 + 前向对齐

Yahoo 美东日与 A 股北京时间日不同历（且个股可能停牌），不做交易日历求交（会互相削点）。取 `dates` = 全部 series 日期**并集**（保序去重），每标的值按 `dates` 对齐（缺失位 `null`）。单市场自选股（当前用户场景即纯 A 股）无缺口、图形正常；混合市场出现缺口，前端 dataset 设 `spanGaps: true` 平滑连接。序列长度 >30 先截尾 30 再并入（「近 30 日」字面；Yahoo 1mo 天然 ~22 点无需截）。

### 决策 3：实时取数不做缓存（F5 字面），降级结构不 500

端点每次请求都 `load_config()`（磁盘读，便宜）+ `fetch_watchlist()`（联网）。编排函数 `_load_watchlist()` 包整段 try/except：配置读取/取数/拼装任何异常 → `log.warning` + 返回空结构（HTTP 200），沿用 `_load_sector_heat`「降级空结构」既有范式。进程内 TTL 缓存**本期不做**（F5 要求实时；高频刷新/上游限流若显现，另行决策，见风险 5）。

### 决策 4：模块级名字绑定 — 测试落点仍在使用方

`web/app.py` 顶部新增 `from src.config import load_config` 与 `from src.fetcher import SYMBOLS, fetch_watchlist`；端点/纯函数一律引用本模块名字 `fetch_watchlist` / `load_config`。测试 monkeypatch 打 `web.app.fetch_watchlist`（假数据、零联网）与 `web.app.load_config`（假 stocks 配置）——与既有「路径常量重新绑定 + monkeypatch 使用方」纪律一致。

### 决策 5：前端独立性 — 不接入全局 state，初始隐藏

自选股模块不并入 `state.days/selected/sort` 联动（固定 30 日、无显隐筛选、不参与 4 组图网格）；DOMContentLoaded 时独立 fetch 一次（与 `/api/alerts` 相同生命周期 =「每次刷新页面取数」F5）。HTML 中该 card 初始 `style="display:none"`，JS 收到 `stocks` 非空才显示 → F4 无闪烁隐藏。颜色：既有 `COLORS` 是 10 指数的固定映射，自选股 symbol 不可枚举 → 前端定义 `WATCH_PALETTE`（~10 色数组）按行 `i % len` 取色，不污染 `COLORS`。

### 决策 6：不改 `src/config.py` / `src/fetcher.py`（NF1 + 涉及文件表）

PRD「涉及文件」中 `src/config.py` 语义为**确认可读**：已确认（§2），零代码改动。`fetch_watchlist` 已满足全部需求（并行/限时/双源/回退/容错），复用即不改。

## 4. 要改的文件列表

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/app.py` | 修改 | 顶部 import + 模块级绑定（`load_config`/`fetch_watchlist`）；新增纯函数 `_series_tail`、`_build_watchlist_payload`、`_load_watchlist`（编排+容错）；新增 `@app.get("/api/watchlist")` 端点。模块 docstring 与「3 个 JSON API」表述同步更新为 4 个 |
| `web/templates/index.html` | 修改 | 板块热度 card 后新增自选股 card（HTML 初始隐藏 + 表格 tbody + chart-box/canvas）；JS 新增 `WATCH_PALETTE`、`renderWatchlist`、`renderWatchChart`（spanGaps 单图），DOMContentLoaded 追加 `/api/watchlist` fetch |
| `tests/test_web.py` | 修改 | 新增用例（决策 4 的 monkeypatch 纪律），详见步骤 2 |
| `docs/architecture.md` | 修改 | Web 看板模块表与关键决策表补一行（4 端点 + watchlist 实时取数 + 零写盘不变） |
| `docs/commands.md` | 修改 | Web 看板验证要点补 `/api/watchlist` 与自选股场景 |
| `tasks/2026-09-03-web-watchlist/journal.md` | 新增 | 任务完成后按 AGENTS 规范记录（目标/改动/验证/问题） |

**不改**：`src/fetcher.py`、`src/config.py`、`src/analyzer.py`、`src/reporter.py`、`daily_report.py`、`snapshot_report.py`、`web/static/style.css`（全部复用既有类，无新样式）、`config.json`、`.env`、`reports/`、`data/`、`context/`、`alerts/`、`requirements.txt`（零新依赖）。

## 5. 实现步骤（每步可验证）

### 步骤 1：`web/app.py` — 纯函数 + 端点

1. `from src.config import load_config`、`from src.fetcher import SYMBOLS, fetch_watchlist`（加注释：测试 monkeypatch 落点为使用方模块名）。
2. `_series_tail(points, n=30) -> list`：截最近 n 点（保序）。
3. `_build_watchlist_payload(stocks_cfg, values, series) -> dict`：
   - 遍历 `stocks_cfg`（配置序）：`label = it.get("label", sym)`；`pts = _series_tail(series.get(sym) or [])`；
   - `change_pct = round((pts[-1][1]-pts[-2][1])/pts[-2][1]*100, 2)` 仅当 `len(pts)>=2 and pts[-2][1] not in (None, 0)`，否则 `None`（公式逐字对齐 `daily_report._build_watchlist_view`）；
   - `dates` = 全部 pts 日期并集（字符串排序，天然时间序）；每标的按 dates 对齐出 `raw`（缺失 null），`values_n, change_7d = _normalize_series(raw)`（复用本模块既有函数）；series 项 `key=sym.lower()`。
4. `_load_watchlist() -> dict`：try 块内 `cfg = load_config()` → `stocks = cfg.get("watchlist", {}).get("stocks") or []` → 空则返回空结构；否则 `fetch_watchlist(stocks)` + `_build_watchlist_payload(...)`；except → `log.warning` + 空结构（不 500）。
5. 端点 `@app.get("/api/watchlist") def api_watchlist() -> dict: return _load_watchlist()`。
6. 模块 docstring「3 个 JSON API」→「4 个 JSON API」+ 自选股实时取数一句。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（步骤 2 用例先写好亦可同批跑）；`uvicorn` 起服务 curl `/api/watchlist` 返 200 空结构（默认 config 无 stocks）。

### 步骤 2：`tests/test_web.py` — 新增用例（monkeypatch `web.app`，零联网）

1. `test_build_watchlist_payload_*`：stocks 行契约（label 缺省回退 symbol / value / change_pct 相邻日公式 round 2）；trend 契约（dates 并集升序、series 对齐含 null、归一化 base 100、`change_7d`、`key` 小写、raw 保留）。
2. `test_build_watchlist_change_pct_edge`：单点/空序列/昨收 None/昨收 0 → `change_pct` None。
3. `test_build_watchlist_tail_30`：41 点输入 → trend 仅最近 30 点。
4. `test_load_watchlist_empty_config`：monkeypatch `web.app.load_config` → `stocks=[]` → 返回双空结构。
5. `test_load_watchlist_partial_failure`：monkeypatch `web.app.fetch_watchlist` 返回含 errors 的 `(values, series, errors)` → 失败行 `value/change_pct` None、成功行正常、历史 series 仍入图。
6. `test_load_watchlist_fetch_raises`：`fetch_watchlist` 抛异常 → `_load_watchlist` 不抛、返回空结构（NF3）。
7. `test_api_watchlist_endpoint`：TestClient（沿用既有 client fixture 风格）+ monkeypatch `web.app._load_watchlist` 或经 5 的两个 monkeypatch → `GET /api/watchlist` 200 + JSON 形状断言。
8. `test_api_watchlist_no_config_hidden_semantics`：默认配置（conftest 隔离下 stocks 恒空）→ 端点返回 `stocks=[]`（F4 前端据此隐藏）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v` 新增 8 条 + 既有 20 条全绿。

### 步骤 3：`web/templates/index.html` — 模块 HTML + JS

HTML（插在「模块 3：板块热度」`</section>` 之后）：

```html
<!-- 模块 5：自选股（config.json watchlist.stocks；空配置整卡隐藏） -->
<section class="card" id="watchlist-section" style="display:none">
  <h2>自选股 <span class="h2-sub">· config.json 配置 · 实时取数</span></h2>
  <div class="table-scroll">
    <table class="data-table">
      <thead><tr><th>名称</th><th>当前价</th><th>涨跌幅</th><th>近30日趋势</th></tr></thead>
      <tbody id="watchlist-body"><tr><td colspan="4">加载中…</td></tr></tbody>
    </table>
  </div>
  <div class="chart-box">
    <div class="chart-head"><h3>近 30 日走势</h3><div class="chart-meta" id="meta-watchlist"></div></div>
    <canvas id="chart-watchlist"></canvas>
  </div>
</section>
```

JS：
1. `const WATCH_PALETTE = [...]`（10 色数组，不写进 `COLORS`）；模块级 `let watchChart = null;`。
2. `renderWatchlist(payload)`：`payload.stocks` 空 → return（保持隐藏）；非空 → `section.style.display = ""`；表格逐行渲染——`value` 非空：`label | fmtNum(value,2) | fmtPct(change_pct)（.pos/.neg）| fmtPct(trend.series 对应 key 的 change_7d)`；`value` 空：名称保留 + 其余列「数据暂缺」（NF3）；图表区走 `renderWatchChart`（见 3）。
3. `renderWatchChart(trend)`：`!window.Chart || window.__chartFailed` → chart-box 显示「图表加载失败（离线 / CDN 不可达）」占位（对齐 renderCharts 降级文案）；`trend.series` 空 → 「数据暂缺」；否则单 Canvas 多 dataset line chart：`data = trend.dates`、y 值 `s.values`（基准 100）、dataset color = `WATCH_PALETTE[i % len]`、`spanGaps: true`、`borderWidth 1.8`、`pointRadius` 末点高亮，tooltip 显示 `raw` 实价 + `(pct)`（复用 themeColors() 配色与既有 tooltip 回调思路）；先 `watchChart && watchChart.destroy()` 再重建。
4. `DOMContentLoaded` 内追加：`fetch("/api/watchlist")` → `renderWatchlist(data)`；catch → `console.error` + 若 section 已显示则表格行「加载失败」（复用既有 loadFailed 文案风格）——模块任何失败不影响 `refresh()` 主链路。

**验证**：起 uvicorn 浏览器实测（见步骤 4；JS 无单测基建，用 tab.evaluate 断言 DOM）。

### 步骤 4：端到端浏览器验证（三个场景）

1. 默认（无 config / conftest 之外的真实 config.json 缺失或 stocks 空）：页面无自选股 card、与改动前视觉一致（F4）。
2. 临时 config（`CONFIG_PATH` 指向含 `watchlist.stocks: [{symbol: "515300.SS", label: "沪深300ETF"}]` 的 json，起 uvicorn）：card 显示、四列有真实数据、涨跌幅与当日行情手算一致、折线渲染（25 期同款浏览器驱动法：`tab.observe`/`tab.evaluate`）。
3. 断网或配置假 symbol `XXXX.XX`：该行「数据暂缺」、概览/板块/告警模块与图均正常（NF3）；改回正常 config 后无重启即生效（load_config 每次现读）。

**验证**：浏览器截图/断言 + `curl http://localhost:PORT/api/watchlist` JSON 抽查。

### 步骤 5：全量回归 + 文档 + journal

- `venv/Scripts/python -m pytest tests/ -v`（全量，基线 382+ passed → 期望 +8）。
- `venv/Scripts/python -m uvicorn web.app:app --port 8002` 冒烟：4 端点 + 首页 200。
- 更新 `docs/architecture.md`（模块表 Web 行、数据流或关键决策表：web 4 端点、watchlist 实时取数经 `fetch_watchlist`、零写盘不变）、`docs/commands.md`（验证要点补自选股三场景与端点）。
- 复用规则按 AGENTS 规范追加 `docs/pitfalls.md` 或 AGENTS.md（如：「web 端点调用联网取数函数须包 try 降级空结构」「web 测试 monkeypatch 打使用方 web.app」——后者已存在于文档，无需重复）。
- 写 `tasks/2026-09-03-web-watchlist/journal.md`；`git diff` 检查改动范围。

**验证**：全量 pytest 输出 + `git diff --stat` 仅限预期文件。

## 6. 验证命令

| # | 命令 | 阶段 | 预期 |
|---|---|---|---|
| 1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 步骤 1–2 后 | 既有 20 + 新增 8 条全绿 |
| 2 | `venv/Scripts/python -m pytest tests/ -v` | 步骤 5 | 全量无回归（基线 382 passed + 8） |
| 3 | `CONFIG_PATH=<临时含 stocks 的 json> venv/Scripts/python -m uvicorn web.app:app --port 8002` | 步骤 3–4 | 页面显示自选股 card；改 json 立即生效 |
| 4 | 默认启动 `venv/Scripts/python -m uvicorn web.app:app --port 8001` | 步骤 4 | 无 config → card 隐藏，页面与改动前一致 |
| 5 | `curl http://localhost:<port>/api/watchlist` | 步骤 4 | 200 + `{stocks, trend:{dates, series}}` 形状；假 symbol 行 `value: null` |
| 6 | `venv/Scripts/python -m pytest tests/ -v` + `git diff --stat` | 步骤 5 | 仅预期文件改动 |

注：测试全链路 monkeypatch `fetch_watchlist`/`load_config`，零联网零写盘；真实取数仅在步骤 4 手动验证（依赖外网，AkShare 实跑）。

## 7. 风险评估

1. **页面刷新延迟**：每次刷新端点至多阻塞 `SECTOR_TIMEOUT=10s`（AkShare 内部请求无 timeout，靠线程 join 限时）+ akshare 首 import 慢。缓解：20 标的并行线程 + 整体限时已有；sync def 端点跑 FastAPI 线程池不阻塞事件循环；失败标的仅缺席对应行。页面冷启动最坏 ~1–10s，属可接受（NF3 语义）。
2. **上游限流放大**：多用户/高频刷新 → 每次全量请求 Yahoo/AkShare/新浪。本期按 F5 不做缓存；若 Railway 侧显现限流/告警，另行加进程内 TTL 缓存（后续项，不进本期）。
3. **混合市场日期缺口**：A 股 + 美股自选股并存时 `dates` 并集出现 null 缺口，图线经 `spanGaps` 平滑连接；单一市场（当前用户场景）无此问题。极端停牌长缺口视觉可辨但非错误。
4. **部署端 config 缺失**：`config.json` gitignore 排除、Railway 部署端默认无 → 模块隐藏（= F4 预期行为）。若用户要在部署看板展示自选股，需把 config.json 放到部署环境（list[dict] 无 env 映射，ENV_MAP 无法表达）——运维事项，本期代码不处理，交付说明中注明。
5. **前端 JS 无自动化**：index.html 无 JS 测试基建，DOM 行为靠步骤 4 浏览器驱动人工验证（项目既有做法，25 期同款）；Python 侧契约（payload 形状/容错）由步骤 2 用例锁定。
6. **口径漂移**：涨跌幅若另写公式会与日报/context 不一致。已决策复用 `daily_report._build_watchlist_view` 的相邻日公式并在测试 2 锁定边界（单点/0 昨收）。

## 8. 影响范围

- **新增**：`/api/watchlist` 端点（4th API）；自选股 card（HTML/JS）；`tests/test_web.py` +8 条。
- **行为变化**：仅看板页面（config 有 stocks 时新增一个卡片）；三个既有端点与所有既有模块零改动；`daily_report.py`/`snapshot_report.py`/`src/*`/回测/开盘分析一律不触。
- **运行面**：web 进程现在会出站请求 Yahoo/AkShare（此前纯读本地文件）——只读纪律不变（不写任何文件）；akshare 依赖在部署端已随 requirements 安装。
- **数据面**：config.json / history / context / alerts 均只读或不动。
- **向后兼容**：无 config 环境页面输出与改动前等价（F4）；`/api/history` 等既有 API 形状不变。

## 9. 不做什么

- 不把自选股并入 4 组趋势图网格 / 全局 days 切换 / 显隐筛选 / 排序状态。
- 不做相关性列、组合集中度、Tavily 新闻归因（>2% 触发属日报/context 侧二十四期已有能力，web 纯展示不加）。
- 不加缓存、不加轮询/自动刷新定时器（F5 字面：刷新页面即取数）。
- 不改 `src/fetcher.py` / `src/config.py` / `style.css` / 三入口脚本 / 生成物目录。
- 不引入新依赖、不新增静态文件。

## 10. 预估 diff

- 修改：`web/app.py`（+~70 行）、`web/templates/index.html`（+~90 行）、`tests/test_web.py`（+~150 行）、`docs/architecture.md`、`docs/commands.md`
- 新增：`tasks/2026-09-03-web-watchlist/journal.md`
- 删除：无

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理（NF1 约束内：仅 app.py + index.html + 测试 + 文档）
- [ ] 测试覆盖 F4/NF3/change 公式边界与端点形状
- [ ] 无新依赖
