# MarketPulse 二十四期 Plan — 持仓/自选股关联

> 架构分析产物。未修改任何源码。依据：`prd.md` + `docs/architecture.md` + `docs/pitfalls.md` + 现状源码阅读。

## 待确认决策

| # | 决策 | 推荐 | 备选 | 理由 |
|---|---|---|---|---|
| D1 | watchlist 配置形状 | `{"watchlist": {"stocks": [{"symbol": "AAPL", "label": "苹果"}, {"symbol": "600519.SS", "label": "贵州茅台"}], "corr_high_threshold": 0.7}}` | 纯字符串数组 `["AAPL", ...]` | 个人持仓需要中文名展示；`label` 缺省回退 symbol，配置保持最小。`corr_high_threshold` 给组合集中度阈值留配置位（默认 0.7） |
| D2 | 自选股相关性数据源 | **自取 30 日序列**：`fetch_watchlist` 每标的 1 次调用直接取近 30 日收盘序列（美股/ETF 走 Yahoo chart `range=1mo`，A 股走 AkShare 日线），当日价与序列一次取齐；相关性由序列与 `history.json` 指数行按 date 合并后计算 | 持久化进 `history.json`（像 gld/btc）多日积累 | 决定性证据：`load_history()` 对每行做 **11 键白名单过滤**，自选股键写入后读回即丢，持久化方案必须改共享契约（波及 backtest/web/TestHistory）；且新加自选股需 ~11 个交易日才有 r（个人场景不可接受）。自取方案首日即可用、零触碰共享契约、配置变更即时生效；取数成本与指数同级（每标的 1 次网络调用） |
| D3 | 自选股 vs 大盘的配对范围 | **按市场归属单基准**：美股/ETF → GSPC，`.SS` → SH，`.SZ` → SZ | 每只 vs 全部 5 大盘 | 20 只 × 5 指数 = 100 对表格失控；单基准表格紧凑、Hermes 解读清晰。归属判定复用既有后缀约定（`.SS`/`.SZ`，与 `fetch_vix_vxn` 分流一致） |
| D4 | 组合集中度判据 | **组合内两两相关系数平均 \|r\| > corr_high_threshold(0.7) → 提示「组合集中度高」** | 与大盘相关性过高判据 | PRD 功能 5「相关性极高提示组合集中度高」的经典语义是组合内同涨同跌 = 分散化不足；两两平均比单对更稳。阈值进 watchlist 配置（沿用数字校验链） |

## 影响分析

### 功能 1：自选股配置（config.json + src/config.py）

- 现 `_merge_valid` 只接受**非 bool 数字 >0** 的叶值，watchlist 是 list[dict]，白名单合并会记日志回退默认——必须新增 list 校验器（`_valid_watchlist`），这是 config 层唯一新增逻辑。
- 校验规则：`stocks` ≤20 只；`symbol` 非空字符串、去重（记日志丢弃重复）；`label` 缺省用 symbol；非法条目丢弃并记日志；`corr_high_threshold` 走既有 `_valid_number` 校验。
- **默认 `stocks: []` 空列表**：现有 config.json 无 watchlist 键 → 回退默认空 → 日报/context 不出现板块，存量运行零影响（render_report/generate_context 默认 None → 省略，项目一贯模式）。
- `config.json` 为 gitignore 排除的用户定制文件，仅新增示例说明（`.env.example` 风格注释不入库，可写进 `AGENTS.md`/`docs/commands.md` 文档）。
- 代码量：config.py +25 行。

### 功能 2：数据获取（src/fetcher.py）

- 新增 `fetch_watchlist(stocks) -> (values, series, errors)`：
  - `values[ticker]` = 当日收盘价；`series[ticker]` = `[(date, close), ...]` 近 30 日序列（供相关性，含当日）；`errors` 逐标的记录。
  - **美股/ETF**：Yahoo chart REST `range=1mo&interval=1d`，当前价取 `meta.regularMarketPrice`（缺则序列最后非空 close），序列解析 `timestamp + indicators.quote[0].close`，时间戳转**美东日期**（`EASTERN_TZ`）。
  - **A 股（`.SS`/`.SZ`）**：AkShare `stock_zh_a_hist`（东财日线，symbol 去掉后缀），列 date/close 直接作序列，末行 close 为当日价。
  - **并行 + 整体限时**：复用 `fetch_us_sector_heat` 线程 + deadline 模式（`SECTOR_TIMEOUT=10`），逐标的 try/except，单标的失败置 None 不中断，全失败返回空 dict。
  - 复用 `fetch_with_retry` 与 `_SESSION`；不新增依赖（akshare 已在 requirements）。
- 时区对齐（易错点）：A 股收盘 15:00 北京 = 美东当日凌晨（全年均当日），AkShare 日期列与 `history.json` 的美东 date 键**同日对齐**；Yahoo 时间戳转美东后与美股指数行同日对齐。无需跨日偏移。
- 代码量：+45 行。

### 功能 3：日报板块（src/reporter.py）

- `render_report` 新增 `watchlist=None` 默认参数（存量调用零影响）：提供时在「💰 另类资产」板块之后、「🔥 A 股热点板块」之前插入「📋 自选股/持仓」：
  - 表格 `| 股票 | 收盘价 | 涨跌幅 | 相关性 |`：相关性列显示与基准指数 r 值（复用 12 期着色：r>0.5 红 / r<-0.5 绿 / 数据不足灰），涨跌幅由序列相邻日自算（`(p[-1]-p[-2])/p[-2]`，首日即有）。
  - 集中度提示行：`portfolio_risk.high == True` → `> ⚠️ 组合集中度高：持仓间平均相关系数 X.XX，分散化不足，警惕同涨同跌风险。`
  - 容错：单标的失败 → 收盘价「数据暂缺」、涨跌幅「—」、相关性「数据不足」；全失败 → 整板块占位「自选股数据暂缺」。
- 已核对 `src/image_renderer.py` 解析正则（`| 指数 | 收盘价 | 涨跌幅 | 趋势 |` 表头 / 章节标题）：新板块表头不同、不会被误解析；图片化会把板块整体渲染进卡片，无害，**无需改 image_renderer**。
- 代码量：+30 行。

### 功能 4+5：相关性计算（src/analyzer.py）

- 新增 `compute_portfolio_correlation(watchlist_series, history, pairs=None, window=None, threshold=None) -> dict`：
  - 返回 `{"stocks": [{symbol, label, benchmark, r, n}], "portfolio_risk": {"high": bool, "avg_r": float|None}}`，一次计算供 render_report 与 generate_context 共用（12 期「context 与报告分离、同一份数值」纪律）。
  - 计算核心**复用** `_corr_window` / `_returns` / `_pearson`（不重写 Pearson）：将 watchlist 序列与 `load_history()` 指数行按 date 合并成 `{date, <ticker.lower()>, <指数小写键>}` 行集 → 复用 `_returns` 推导收益率、`_pearson` 计算。窗口/最少样本沿用 `CORRELATION_DAYS=30` / `CORRELATION_MIN_POINTS=10` / `CORRELATION_SIGNIFICANT=0.5`。
  - 配对：D3 按市场归属单基准（美股→GSPC、`.SS`→SH、`.SZ`→SZ）。
  - 组合集中度：`avg_r = mean(|r|)` 所有有效两两对；`high = avg_r > threshold`（默认 0.7）；<2 只或无效对 → `avg_r=None, high=False`。
  - **注意**：`compute_correlation` 的 pair 名依赖 `SYMBOLS[a]['label']`，自选股不在 SYMBOLS → 结果构造自写循环（仅复用计算核心，不调 `compute_correlation` 本体）。
  - 纯函数、零 I/O，可单测。
- 代码量：+40 行。

### context（src/reporter.py generate_context）

- 签名加 `watchlist=None` 默认参数；payload 新增 `watchlist` 键：
  ```json
  "watchlist": {
    "stocks": [{"symbol": "AAPL", "label": "苹果", "value": 231.5, "change_pct": 1.2,
                "corr": {"benchmark": "GSPC", "r": 0.83, "n": 28}}],
    "portfolio_risk": {"high": true, "avg_r": 0.75}
  }
  ```
- 空配置时写空结构 `{"stocks": [], "portfolio_risk": {"high": false, "avg_r": null}}`（键恒定，Hermes Prompt 契约稳定；与 sector_heat 空结构先例一致）。
- **Hermes Prompt 需同步**（交付配置项，非仓库文件）：允许引用自选股表现与集中度提示。
- 影响：`tests/test_context.py` 若断言 payload 键集需补 watchlist 键（核对后更新）。
- 代码量：+15 行。

### 编排入口（daily_report.py）

- 接线：`load_config()["watchlist"]`（fetcher 模块级快照常量）→ `fetch_watchlist(stocks)` → `compute_portfolio_correlation(series, history)` → 传 `render_report(..., watchlist=...)` 与 `generate_context(..., watchlist=...)`。
- **容错纪律**：自选股取数失败不影响日报主流程与退出码（复用既有 try/except 仅记日志模式；全失败 → 板块「数据暂缺」、context watchlist 空结构）。
- 自选股**不参与**告警/趋势图/快照/回测/web：不在 SYMBOLS → ALERT_THRESHOLDS 推导天然排除；不写 last_values（change% 由序列自算）；不写 history.json（D2）。
- 代码量：+15 行。

### 测试（tests/）

| 文件 | 内容 |
|---|---|
| `tests/test_phase24.py`（新增） | fetch_watchlist 分流（美股 Yahoo / A 股 AkShare mock、超时、单标的失败）、compute_portfolio_correlation 纯逻辑（正/负相关、数据不足、缺口断开、集中度阈值）、渲染板块（含暂缺/集中度提示）、context watchlist 键、入口透传（monkeypatch 落点 daily_report.py） |
| `tests/test_analyzer.py` | 新增 compute_portfolio_correlation 用例（PRD 指定文件）；复用 12 期断言范式（pytest.approx 边界） |
| `tests/test_config.py` | watchlist 校验：≤20 截断、重复丢弃、非法条目丢弃、label 缺省、corr_high_threshold 数字校验回退 |
| `tests/test_context.py` | payload 含 watchlist 键（空结构与带数据两态） |

- 既有测试零破坏面：render_report/generate_context 新参数默认 None/空 → 存量断言不变；conftest 隔离下 watchlist 默认空。
- 代码量：+120 行。

## 修改清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `config/config.json` | 修改（用户侧示例） | 新增 `watchlist` 示例（2 只美股 + 1 只 A 股），gitignore 排除不入库 |
| `src/config.py` | 修改 | `DEFAULTS` 加 `"watchlist": {"stocks": [], "corr_high_threshold": 0.7}`；新增 `_valid_watchlist`（≤20、symbol 非空去重、label 缺省、非法丢弃记日志）；`load_config` 接线（stocks 走 list 校验、threshold 走 `_valid_number`） |
| `src/fetcher.py` | 修改 | 新增 `fetch_watchlist(stocks)`（并行线程 + `SECTOR_TIMEOUT` 限时；美股 Yahoo chart `range=1mo` 一次取价+序列；A 股 `stock_zh_a_hist` 日线；逐标的容错）；模块级 `WATCHLIST` 配置快照 |
| `src/analyzer.py` | 修改 | 新增 `WATCHLIST_THRESHOLD` 常量 + `compute_portfolio_correlation()`（复用 `_corr_window`/`_returns`/`_pearson`；D3 配对；组合两两平均 \|r\| 集中度） |
| `src/reporter.py` | 修改 | `render_report` 加 `watchlist=None` + 「📋 自选股/持仓」板块（表格 + 集中度提示 + 数据暂缺）；`generate_context` 加 `watchlist=None` + payload `watchlist` 键 |
| `daily_report.py` | 修改 | 接线 fetch_watchlist → compute_portfolio_correlation → render/generate，全 try/except 容错 |
| `tests/test_phase24.py` | 新增 | 见上表 |
| `tests/test_analyzer.py` | 修改 | 相关性用例 |
| `tests/test_config.py` | 修改 | watchlist 校验用例 |
| `tests/test_context.py` | 修改 | watchlist 键断言 |
| `docs/architecture.md` | 修改 | 模块职责 + 数据流 + 关键决策表（D1-D4） |
| `docs/pitfalls.md` | 修改 | 新增 watchlist 易错点（load_history 白名单、时区对齐、config 列表校验、不参与告警） |
| `docs/commands.md` | 修改 | 验证要点 + 测试计数 |

## 执行步骤

1. **config 层**：`src/config.py` DEFAULTS + `_valid_watchlist` + load_config 接线 → 验证：`pytest tests/test_config.py -v`（新增用例绿）。
2. **取数层**：`src/fetcher.py` `fetch_watchlist`（并行 + 限时 + 分流）→ 验证：`test_phase24.py` fetch 用例绿（mock Yahoo/AkShare，不联网）。
3. **计算层**：`src/analyzer.py` `compute_portfolio_correlation`（复用相关性核心 + 集中度）→ 验证：`test_analyzer.py` 新增用例绿。
4. **渲染层**：`src/reporter.py` 板块 + context 键 → 验证：`test_reporter.py`/`test_context.py` 用例绿（新参数默认 None 存量零影响）。
5. **编排接线**：`daily_report.py` 接入（try/except 容错）→ 验证：入口透传用例（monkeypatch 打 `daily_report` 模块）。
6. **全量验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿；手动 `venv/Scripts/python daily_report.py`（config.json 加 3 只自选股）检查日报板块 + context watchlist 键 + 断网容错。
7. **文档**：architecture / pitfalls / commands / AGENTS.md 同步；`git diff` 检查改动范围。
8. **收尾**：`tasks/2026-09-02-marketpulse-phase24/journal.md` 记录目标/改动/验证/风险。

## 验证方法

- **单测**：`venv/Scripts/python -m pytest tests/ -v`（含新 test_phase24 + 既有全量回归，预计 ~240+ passed）。
- **闭环**：`config.json` 加 `watchlist`（2 美股 + 1 A 股）→ `venv/Scripts/python daily_report.py`：
  - 日报含「📋 自选股/持仓」板块，收盘价/涨跌幅/相关性列有值（首日即有——D2 自取序列）；
  - `context/YYYY-MM-DD.json` 含 `watchlist.stocks` 与 `portfolio_risk`（首日相关性有效，因序列自取）；
  - 集中度模拟：两只高度相关美股（如 AAPL/QQQ）→ 平均 |r|>0.7 → 板块出现「组合集中度高」提示。
- **容错**：断网/单标的失败 → 该行「数据暂缺」、日报正常生成、退出码 0、无告警文件（自选股不参与告警）。
- **配置校验**：watchlist 21 只 → 截断 20；重复 symbol → 丢弃；非法条目 → 丢弃，均不崩溃。
- **回归**：删除 watchlist 配置（或空数组）→ 日报与 context 与二十四期前一致（板块省略/空结构）。
