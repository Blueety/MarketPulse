# MarketPulse 十期：黄金 & 比特币监控 — 实施计划

> 架构师只读分析产出。目标、涉及文件、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`fetcher.py` / `analyzer.py` / `reporter.py` / `alerter.py` / `config.py` / 两入口 / 全部存量测试。

## 目标

- 新增 GLD（黄金 ETF）与 BTC-USD（比特币）日度监控，纳入收盘日报、趋势图与 history/context。
- 零新依赖（沿用 Yahoo Finance chart REST）；快照入口（4 cron）不含另类资产。
- 另类资产告警与现有告警分离（不并入现有告警流程）。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `src/fetcher.py` | SYMBOLS +2、新增 ALT_SYMBOLS 分组 |
| `src/analyzer.py` | ALERT_THRESHOLDS 排除另类资产、compute_streaks 符号集参数化、build_statuses 另类资产分支、load_history +2 键 |
| `src/alerter.py` | collect_breaches 跳过另类资产 |
| `src/reporter.py` | 另类资产板块渲染、alts 趋势图注册表、context +2 键、vol 分组排除另类资产 |
| `daily_report.py` | alts 趋势图接线（约 +5 行） |
| `tests/test_phase10.py` | 新增（约 20-25 条） |
| `tests/test_phase6a/6b/7/analyzer/reporter.py` | 存量断言/夹具同步（见「存量测试影响」） |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步 |

不改：`snapshot_report.py`（MARKETS 不含另类资产，自动隔离）、`config.py`、`requirements.txt`、`config.json`。

## 核心设计

### 1. 注册表：SYMBOLS 追加末尾，新增 ALT_SYMBOLS

```python
SYMBOLS = { ...8 项原样...,
    "GLD": {"label": "黄金 ETF（GLD）", "source": "yahoo", "ticker": "GLD"},
    "BTC": {"label": "比特币（BTC-USD）", "source": "yahoo", "ticker": "BTC-USD"},
}
ALT_SYMBOLS = frozenset({"GLD", "BTC"})
```

- 追加在 MOVE 之后（另类资产板块在报告后部，顺序与板块一致）。
- history 键自动派生为 `gld` / `btc`（`record = {"date": date, **{k.lower(): ...}}` 已覆盖，daily_report.py 无需改）。
- `MARKETS` 不动：`fetch_all("us"/"a-share")` 天然不含另类资产，快照 4 cron 零改动。
- `fetch_vix_vxn` 对 GLD / BTC-USD 走 Yahoo 分支（非 .SS/.SZ），`regularMarketPrice` 直接可用；`quote("BTC-USD")` 中连字符不编码，无特殊处理。
- 7×24 交易的 BTC 按 Yahoo 提供的日收盘值直接取用（PRD 约束）。

### 2. 告警分离：collect_breaches 排除 ALT_SYMBOLS

- `analyzer.ALERT_THRESHOLDS` 推导改为 `for sym in SYMBOLS if sym not in ALT_SYMBOLS`。
  **必须**：否则 SYMBOLS +2 后 `_CFG["alert"]["gld"]` KeyError，import 即崩（config DEFAULTS 无此键，也不应加——另类资产不设阈值）。
- `alerter.collect_breaches` 循环 `if sym in ALT_SYMBOLS: continue`：GLD/BTC 永不触发告警、不写告警文件、不入 alerts.log、不进入 breach/search_keywords 异动词。
- 理由：PRD 未定义另类资产阈值；「分离」=不并入现有告警机制；与八期「板块热度不设阈值」先例一致，避免主观阈值。

### 3. 趋势（连续涨跌天数）：复用大盘 streak 机制

- `compute_streaks` 加参数 `symbols: set = STOCK_SYMBOLS`（默认值保持存量行为，既有测试零改动），循环目标改为传入集合。
- `build_statuses` 新增分支：`elif sym in ALT_SYMBOLS:` 走与 STOCK_SYMBOLS 相同的 `trend_label(streak, has)` + `_trend_desc(...)`（`compute_streaks` 调用处传 `STOCK_SYMBOLS | ALT_SYMBOLS`，单次调用）。
- 趋势列复用大盘四档标签（数据积累中/横盘/连涨X日/上升或下跌趋势），与大盘列同语义——PRD 括号「连续涨跌天数」即指此机制。
- 另类资产取数失败（None）→ 「获取失败」（非 A 股分支），不显示「休市」。
- 注意：`_trend_desc` 文案含「大盘」字样，该字段仅存于 statuses 元组第二元素，渲染/context 均不消费（只取 `[0]` 标签），可复用不改写。

### 4. 日报「另类资产」板块

- `render_report` 新增 `alts_trend_chart` 默认参数（None），在「## 🇨🇳 A 股大盘」章节（含 cn 趋势图）之后插入：

```
## 💰 另类资产

| 资产 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
| 黄金 ETF（GLD） | 252.30 | +0.45% | 连涨2日 |
| 比特币（BTC-USD） | 65000.00 | -1.20% | 连跌1日 |
```

- 行渲染复用 `fmt_value` / `fmt_change` / statuses 标签，与既有板块一致（首跑显示「首次运行，暂无历史对比」）。
- 板块位置待确认（见「待确认决策 B」）。

### 5. 另类资产趋势图（2×1）

- 复用分市场图机制，**零新绘图代码**：`MARKET_CHART_PANELS` 增加 `"alts"` 键，`MARKET_CHART_TITLES["alts"]` 增加标题：

```python
"alts": [("gld", "GLD", "#d4a017"), ("btc", "BTC", "#f7931a")],
MARKET_CHART_TITLES["alts"] = "Gold & Bitcoin — 30-Day Trend"
```

- `render_market_trend_chart(history, date, "alts")` 现成支持：2 面板 → figsize (10,5.4)、文件名 `{date}-alts-trend.png`、每子图独立 y 轴（PRD 约束：单序列/子图，y 天然独立；`sharex=True` 仅共享日期轴，GLD 百位/BTC 万位量级互不干扰）、数据不足子图 "Insufficient Data" 占位、整体行数 <2 返回 None 省略章节、5s 独立限时。
- `render_report` 章节「## 📈 另类资产近30日趋势」（条件渲染，紧随另类资产表格后）。
- `daily_report.py`：独立 try/except 调 `render_market_trend_chart(history, date, "alts")`（与 us/cn 同范式），透传 `alts_trend_chart`。

### 6. history / context

- `load_history` 返回 dict 增补 `"gld": rec.get("gld")`、`"btc": rec.get("btc")`（旧记录缺键 → None，历史兼容）。
- `generate_context`：`history_30d` 增补 `gld` / `btc` 等长数组；`indices` 循环遍历 SYMBOLS 自动含 GLD/BTC。
- **改动**：`indices` 取值从 `values[sym]` 改为 `values.get(sym)`——对齐 pitfalls 既有约定「values 用 .get 容忍缺失（与 collect_breaches 一致）」，使 test_context / test_phase6b 的 8 键输入夹具免于补键（存量测试少动 2 个文件）。
- context 增量（indices +2 键、history_30d +2 数组）需同步 Hermes Prompt 字段表（交付配置项，非仓库文件）。

## 实施步骤

1. **fetcher.py**：SYMBOLS +2（末尾）、新增 ALT_SYMBOLS + 注释。验证：`python -c` 检查 10 键、ticker 正确；MARKETS 子集不含 GLD/BTC。
2. **analyzer.py**：导入 ALT_SYMBOLS；ALERT_THRESHOLDS 排除；compute_streaks 参数化；build_statuses 另类资产分支（含缺失 → 获取失败）；load_history +2 键。验证：`pytest tests/test_analyzer.py tests/test_config.py -v`。
3. **alerter.py**：collect_breaches 跳过 ALT_SYMBOLS。验证：`pytest tests/test_alerter.py -v`。
4. **reporter.py**：render_report/render_snapshot 的 vol_syms 排除 ALT_SYMBOLS（防另类资产漏入「波动率指数」板块——legacy noon 快照路径同样受影响）；render_report 另类资产表格 + alts 趋势图章节 + alts_trend_chart 参数；MARKET_CHART_PANELS/TITLES + "alts"；generate_context 的 .get 化 + history_30d +2。验证：`pytest tests/test_reporter.py tests/test_phase9.py tests/test_context.py tests/test_phase6b.py -v`。
5. **daily_report.py**：alts 图接线（try/except 同 us/cn 范式）。验证：实跑见下。
6. **存量测试更新**（见下表）→ `pytest tests/ -v` 全绿。
7. **新增 tests/test_phase10.py**（见下）。
8. **文档同步**（AGENTS.md / architecture.md / commands.md / pitfalls.md）。

## 存量测试影响（必须同步，否则全量 pytest 红）

| 文件 | 断言 | 原因与修法 |
|---|---|---|
| test_phase6a.py:24 | `set(an.SYMBOLS) == {8 键}` | 精确键断言 → 补 GLD/BTC |
| test_phase6b.py:34 | 同上 | 同上 |
| test_phase6b.py:134 `_seven()` + :78 休市夹具 | render_report 输入缺 GLD/BTC | render_report 另类资产行 `values[sym]` 直取 → 补 2 键（值/涨跌/状态） |
| test_phase7.py:35,37-38 | SYMBOLS 精确集 + 顺序 `[:5]`/`[-3:]` | 追加末尾后 `[-3:]` 变 [MOVE, GLD, BTC] → 改断言（如 `[-5:]` 或按新末 5 键） |
| test_analyzer.py:141 | `load_history()` 返回 dict 全等断言 | 返回 dict +gld/btc:None → 期望字典补 2 键 |
| test_reporter.py:56 | `count("首次运行，暂无历史对比") == 8` | 另类资产 2 行 → 10 |
| test_reporter.py `sample_data()` | 8 键渲染夹具 | 补 GLD/BTC 的 values/changes/statuses（test_phase9 复用此夹具，自动同步）；失败态夹具（:58-100）同补 |

不受影响（已验证）：test_config（ALERT_THRESHOLDS 键访问，排除后仍含 VIX/VXN/MOVE）、test_context / test_phase6b context（.get 化后 8 键输入兼容）、test_phase6a/6b/7/8/9 其余断言（板块渲染为子串/相对顺序断言，另类资产插入不破坏）、test_alerter（collect_breaches 跳过另类资产，8 键输入不触达）。

## 新增测试 test_phase10.py（约 20-25 条，复用 test_reporter.sample_data 风格）

- **注册表**：SYMBOLS 10 键；GLD ticker="GLD"、BTC ticker="BTC-USD"；ALT_SYMBOLS 定义；MARKETS 子集不含另类资产。
- **analyzer**：ALERT_THRESHOLDS 不含 GLD/BTC；build_statuses 另类资产走趋势标签（构造 history+last 断言连涨/连跌）；值 None → 「获取失败」；compute_streaks 默认参数行为不变（存量锁）。
- **alerter**：构造 GLD +50% 场景，collect_breaches 不含 GLD/BTC（告警分离）。
- **reporter**：render_report 含「## 💰 另类资产」章节与两行（标签/收盘/涨跌幅/趋势）；alts_trend_chart 参数 → 「📈 另类资产近30日趋势」章节；章节顺序（A 股大盘 < 另类资产 < 热点板块）；vol 板块不含另类资产；render_market_trend_chart("alts") → `{date}-alts-trend.png`（真实 matplotlib 到 tmp_path，同 test_phase9 范式，含数据不足跳过/占位）；generate_context indices 含 GLD/BTC、history_30d 含 gld/btc 等长数组（含旧记录缺键 → None）。
- **入口接线**：daily_report.main 的 alts 图透传与异常容错（monkeypatch 范式同 test_phase8 入口测试）。

## 验证命令（对应 PRD Verification）

1. `venv/Scripts/python -m pytest tests/ -v` — 全量（含存量同步 + 新增），预期全绿。
2. `venv/Scripts/python daily_report.py` — 实跑：报告含「💰 另类资产」两行（GLD/BTC 收盘、涨跌幅、趋势）；`reports/charts/YYYY-MM-DD-alts-trend.png` 生成（历史 ≥2 条时）；`data/history.json` 新记录含 gld/btc 键；`context/YYYY-MM-DD.json` indices 10 键 + history_30d gld/btc 数组。
3. 断网运行（临时断网或 `RETRIES` 上限场景）：退出码 0、不崩溃、另类资产行显示「获取失败」、趋势图省略/占位，既有 8 指数容错路径不受影响。
4. 模拟验证（验证后恢复 `data/last_values.json` 原值，遵循 pitfalls 既有纪律）：改 last_values 中 GLD 基准制造 +5% 变化 → 日报另类资产行涨跌幅显示正常；确认**不生成**任何含 GLD 的告警文件。
5. 快照回归：`venv/Scripts/python snapshot_report.py --market us --time noon` 输出不含另类资产（子集隔离验证）。

## 待确认决策

- **A（建议默认）**：另类资产完全不参与告警（无阈值、无告警文件）。备选：若需独立告警，用户须给出阈值（如 GLD ±3%、BTC ±5%），再配置 `alert.gld`/`alert.btc` + ENV_MAP，并取消 collect_breaches 跳过。
- **B（建议默认）**：另类资产板块插在「A 股大盘」（含 cn 趋势图）之后、热点板块之前（PRD 字面「A 股大盘之后」）。备选：插在 A 股全部章节（含热点/领跌）之后、波动率之前，保持 A 股内容连续。纯渲染顺序，一行可调。
- **C（建议默认）**：另类资产趋势列复用大盘四档标签（|streak|≥N 显示「上升/下跌趋势」）。备选：恒显「连涨/连跌X日」天数（PRD 括号字面）。
- **D（建议默认）**：context 增量纳入 GLD/BTC（indices + history_30d），需同步 Hermes Prompt 字段表。备选：context 排除另类资产（显式过滤）。

## 风险与边界

- **Yahoo 对 GLD/BTC-USD 限流**：沿用现有单请求 + 退避 + 2s 节流，失败仅单源缺失（history 记 null），不影响整体。
- **历史数据积累**：alts 趋势图需 ≥2 条历史（排除当日）；首周运行图可能省略，属设计行为（与波动率图一致）。
- **context 契约变更**：indices 8→10 键、history_30d +gld/btc，Hermes Prompt 若按固定键解析需同步（交付配置项）。
- **旧 history 兼容**：存量记录无 gld/btc 键 → load_history 补 None，趋势图/context 按空序列占位，不崩。
- **图表文本英文**：alts 图沿用英文标签约束，不引入中文到 matplotlib。

## PRD Done When 对照

- fetcher 支持 GLD/BTC-USD → 步骤 1
- analyzer 涨跌幅 + 趋势判断 → 步骤 2（compute_changes 自动覆盖；streak 复用）
- reporter 日报「另类资产」板块 → 步骤 4
- reporter alts 趋势图 2×1 → 步骤 4（注册表扩展）
- history.json 含 gld/btc → 步骤 2+5（load_history + record 推导）
- pytest 全绿 → 步骤 6-7
- 验证项（实跑/PNG/断网）→ 验证命令 1-5
