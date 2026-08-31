# MarketPulse 十五期：开盘分析 — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`daily_report.py`（编排模式：取数 → 渲染 → 落盘 → 容错，退出码恒 0）、`snapshot_report.py`（独立入口 + `--market`/`--time` 参数 + `save_snapshot` 复合名归档先例）、`src/fetcher.py`（SYMBOLS 注册表 / fetch_with_retry / VIX 走 Yahoo）、`src/reporter.py`（render_snapshot 单板块渲染 + save_snapshot）、`src/analyzer.py`（get_market_date 市场时区 / classify_vix / fmt_value）、`src/alerter.py`（run_alert_checks 仅收盘/快照使用）。
> 环境实测（2026-08-31，仅只读探测不改码）：新浪 `hq.sinajs.cn` 实时接口对 **A 股指数**（sh000001/sz399001/sz399006）与 **美股指数**（gb_inx=标普500 / gb_ixic=纳斯达克）均返回 200 且字段**自带昨收价**；**VIX 新浪无数据**（gb_vix / gb_$vix 等全部为空串），Yahoo chart meta `regularMarketPrice` 可作实时值兜底（实测 14.43 vs chartPreviousClose 15.85）。

## 目标

- 新增 `opening_analyzer.py` 独立入口：开盘后 15-30 分钟（A 股 9:45 / 美股 21:45，北京时间）生成开盘分析。
- 数据源：新浪实时行情（PRD 已确认决策 1）；VIX 新浪无数据 → Yahoo 实时兜底（待确认 B）。
- 分析内容：开盘跳空（对比昨收） / 板块轮动（开盘热点） / 市场情绪（VIX + 大盘方向） / AI 解读（Hermes 追加，100-200 字）。
- 输出：独立报告 `reports/opening/YYYY-MM-DD-{market}.md`（复合名防 A 股/美股同日碰撞，待确认 A）+ 日报引用章节 + 可选 QQ 推送（Hermes 侧，交付配置）。
- 容错：数据不足时优雅降级，报告仍生成、退出码恒 0；**零持久化写入**（不写 history / last_values / context / alerts.log）。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `opening_analyzer.py` | 新增：开盘分析独立入口（argparse `--market a-share\|us`，默认 a-share；裸跑 = A 股开盘分析） |
| `src/fetcher.py` | 修改：+`REALTIME_URL` / `REALTIME_MARKETS` 注册表 / `parse_sina_realtime` 纯解析 / `fetch_realtime_quotes(market)`（新浪直连 + VIX Yahoo 兜底），复用 `fetch_with_retry` / `_SESSION` |
| `src/reporter.py` | 修改：+`render_opening_report`（跳空表 / 板块 / 情绪 / 速览 / AI 解读占位）+`save_opening`（`reports/opening/` 复合名）；`render_report` 加 `opening_refs` 可选参数（默认 None → 章节省略，存量零影响） |
| `daily_report.py` | 修改：渲染前读当日开盘分析 → 传 `opening_refs`（「🔔 开盘分析」章节，含链接 + 摘要） |
| `tests/test_phase15.py` | 新增：新浪解析 / 跳空计算 / 情绪 / 报告渲染 / 降级 / 日报引用 / 入口编排 / 零持久化（约 15 条，全 mock 网络） |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步 |

不改：`snapshot_report.py`、`src/analyzer.py`（仅 import 既有函数）、`src/alerter.py`、`src/config.py`、`src/image_renderer.py`、`web/`、`requirements.txt`（requests 已有，零新增依赖）、`.env`、`data/`、`alerts/`、`context/`。

## 核心设计

### 1. 数据流与触发时机

```text
Hermes cron（北京时间）：
  A 股开盘 9:45  ──> venv/Scripts/python opening_analyzer.py --market a-share
  美股开盘 21:45 ──> venv/Scripts/python opening_analyzer.py --market us
                      │
                      ├─> fetch_realtime_quotes(market)   新浪 hq.sinajs.cn（A 股 sh/sz / 美股 gb_）
                      │     └─> VIX：Yahoo regularMarketPrice 兜底（新浪无 VIX）
                      ├─> fetch_sector_heat()（A 股）/ fetch_us_sector_heat()（美股）—— 开盘热点板块
                      ├─> 跳空计算：(今开-昨收)/昨收、当前涨跌：(当前-昨收)/昨收
                      ├─> render_opening_report ──> reports/opening/YYYY-MM-DD-{market}.md
                      └─> （零持久化：不写 history/last_values/context/alerts.log）

daily_report.py（美东收盘后，北京次日凌晨）：
  └─> load_opening_refs(date) ──> 读 {date}-us.md + {date}-a-share.md（见 6）
        └─> render_report(..., opening_refs=...) ──> 日报「🔔 开盘分析」章节（链接 + 摘要）

Hermes 读取 reports/opening/*.md → 追加「🤖 AI 解读」（100-200 字）→ 可选推送 QQ（交付配置，脚本不含推送逻辑）
```

关键点：开盘分析独立于收盘/快照主流程，**只读新浪实时 + 只写自己的报告文件**。新浪昨收字段直接作跳空基准，**不依赖 `data/last_values.json`**（避免缓存基准缺失/时区错位问题）；VIX 非新浪源，情绪章节标注来源时点（美股开盘=实时，A 股开盘=上一交易日收盘）。

### 2. src/fetcher.py 增量（约 60 行）

常量：

```python
REALTIME_URL = "https://hq.sinajs.cn/list={codes}"
# 开盘分析实时行情注册表：SYMBOLS 键 → (新浪代码, 期望名称)
REALTIME_MARKETS = {
    "a-share": {
        "SH": ("sh000001", "上证指数"),
        "SZ": ("sz399001", "深证成指"),
        "CYB": ("sz399006", "创业板指"),
    },
    "us": {
        "GSPC": ("gb_inx", "标普500指数"),
        "IXIC": ("gb_ixic", "纳斯达克"),
    },
}
# 新浪 A 股字段序：0名称 1今开 2昨收 3当前价 4最高 5最低 … 30日期 31时间
# 新浪美股字段序：0名称 1当前价 2涨跌幅% 3时间 4涨跌额 5昨收 6今开 7最高 8最低 …
```

- `parse_sina_realtime(text: str, market: str) -> dict | None`：纯函数。解析单条 `var hq_str_xxx="..."` 响应（A 股 / 美股两套字段序），返回 `{current, prev_close, open}`（float）；空串 / 字段不足 / 数值非法 → `None`（可单测，全 mock）。
- `fetch_realtime_quotes(market: str) -> tuple[dict, dict]`：单次 GET `hq.sinajs.cn/list={codes}`（带 `Referer: https://finance.sina.com.cn`，复用 `_SESSION`，`TIMEOUT`），逐条解析；A 股 3 指数 / 美股 2 指数任一失败记 errors 不中断；随后 VIX 单独走 `fetch_vix_vxn("^VIX")`（Yahoo，实时/最近收盘，现有函数），VIX 的 prev_close 取 Yahoo meta `chartPreviousClose`（无则 None）。返回 `(quotes, errors)`，`quotes[sym] = {current, prev_close, open}`。外层再包 `fetch_with_retry` 语义（复用现有重试，失败返回空 dict + errors）。
- 新浪接口请求头必须带 `Referer`（实测裸 UA 也可，但带 Referer 更稳，与既有 `_SESSION.headers` 合并）。

### 3. opening_analyzer.py（约 130 行，根目录独立入口）

```python
# 开盘分析独立入口（PRD 文件名）。
# 用法: python opening_analyzer.py [--market a-share|us]   （默认 a-share；裸跑 = A 股开盘分析）
def main(market: str = "a-share") -> int:
    date = get_market_date(market)          # a-share 北京时间 / us 美东时间（analyzer 既有）
    quotes, errors = fetch_realtime_quotes(market)   # {sym: {current, prev_close, open}}
    sector_heat = fetch_sector_heat() if market == "a-share" else fetch_us_sector_heat()
    gaps = compute_gaps(quotes)             # {sym: {"open_gap": %, "current_change": %}}
    sentiment = build_opening_sentiment(quotes, errors)  # VIX 状态 + 大盘整体方向
    path = save_opening(date, market, render_opening_report(date, market, quotes, gaps, sentiment, sector_heat, errors))
    log.info("开盘分析已生成: %s", path)
    return 0   # 全源失败也恒 0，避免 Hermes cron 误报警
```

- `compute_gaps(quotes) -> dict`：纯函数。`open_gap = (open - prev_close)/prev_close*100`、`current_change = (current - prev_close)/prev_close*100`；缺 prev_close（None/0）→ 对应项 `None`。
- `build_opening_sentiment(quotes, errors) -> dict`：确定性情绪。VIX 有值 → `classify_vix` 状态 + 描述；VIX 缺失 → 「数据暂缺」；大盘方向 = 跳空均值符号（高开/低开/平开，|均值|<0.3% 记平开）。
- 不调用 `run_alert_checks`（开盘分析不告警，PRD 未要求）、不写任何缓存/历史/context。
- argparse：`--market choices=("a-share","us") default="a-share"`。

### 4. src/reporter.py 增量

- `render_opening_report(date, market, quotes, gaps, sentiment, sector_heat=None, errors=None) -> str`：Markdown 结构（A 股/美股同模板，市场文案按 market 区分，日期行注明时区）：

```text
# 🌅 开盘分析

**日期**：{date}（北京时间 / 美东时间）
**类型**：开盘分析（开盘后 15-30 分钟）

---

## 📊 开盘跳空

| 指数 | 开盘价 | 昨收 | 跳空 | 当前价 | 当前涨跌 |
| :--- | :--- | :--- | :--- | :--- | :--- |
{rows}   ← 缺昨收 → 跳空/涨跌显示「—」；取数失败 → 「获取失败」

---

## 🔥 热点板块 Top 5（开盘）

| 板块 | 涨跌幅 | 成交额 | 领涨股 |
{_sector_table_md 复用；空 → 「数据暂缺」}

---

## 📉 领跌板块 Top 5（开盘）

（同上，空 → 「数据暂缺」）

---

## 🏷️ 开盘情绪

**VIX 当前值：{fmt_value} → 状态：{label}**（数据来源：Yahoo Finance）
> {描述}

**大盘方向**：{高开/低开/平开}（{跳空均值说明}）

---

## 📝 开盘速览

- 大盘整体{高开/低开/平开}，{最强/最弱}指数跳空 {x.xx}%。
- 领涨板块：{Top1 板块}（{x.xx}%）；领跌板块：{Top1 板块}（{x.xx}%）。
- VIX {值}，市场情绪{label}。

---

## 🤖 AI 解读

（待 Hermes 追加：100-200 字开盘分析）

---
*本报告由 MarketPulse 自动生成 | 数据来源：新浪实时行情（VIX 来自 Yahoo Finance）*
```

- `save_opening(date: str, market: str, content: str) -> "Path"`：`OPENING_DIR = REPORTS_DIR/"opening"`（analyzer.py 已有 REPORTS_DIR，reporter 直接 `REPORTS_DIR/"opening"`，不新增 analyzer 常量即可——沿用 save_snapshot 先例在 reporter 内部 mkdir）。文件 `YYYY-MM-DD-{market}.md`。
- `render_report(..., opening_refs=None)`：新可选参数（默认 None → 不渲染，存量调用零影响）。章节插在「📝 总结」后、脚注前：

```text
---

## 🔔 开盘分析

- 🌏 美股开盘分析：[查看](opening/{date}-us.md) — 标普500 跳空 {x.xx}%，VIX {值}（{label}）
- 🇨🇳 A 股开盘分析：[查看](opening/{date}-a-share.md) — 上证指数 跳空 {x.xx}%
```

- `load_opening_refs(date: str) -> list[dict]`：读 `reports/opening/{date}-us.md` 与 `{date}-a-share.md`（存在才收录），各解析摘要行（从「📊 开盘跳空」表首行 + 「🏷️ 开盘情绪」VIX 行提取）；文件缺失/坏格式 → 该市场跳过不报错。

### 5. daily_report.py 接线

render_report 调用前（约 5 行）：

```python
opening_refs = load_opening_refs(date)   # 读当日开盘分析（美股/ A 股按日期匹配，见 6）
report = render_report(date, ..., opening_refs=opening_refs)
```

失败不中断日报（load_opening_refs 内部已容错，任何异常 → [] 记日志）。

### 6. 日期匹配语义（时区对齐）

- 美股开盘分析：美东日期 D 的开盘在北京 D 日 21:45 生成 → 归档美东日期 D → `{D}-us.md`。
- A 股开盘分析：北京 D 日 9:45 生成 → 归档北京日期 D → `{D}-a-share.md`。
- 日报：美东 D 收盘后在北京 D+1 凌晨生成 → `date` = 美东 D。此时 `{D}-us.md`（北京 D 21:45 已生成）与 `{D}-a-share.md`（北京 D 9:45 已生成，对应美东 D-1 晚间交易时段）**均已存在** → 两文件同日命名词缀一致，`load_opening_refs` 直接按美东 date 拼接，无时区转换。日报引用的 A 股开盘分析语义 = 「最近一次 A 股开盘」。
- 极端情形：日报当日 A 股开盘分析尚未生成（如 cron 延迟）→ 该市场引用行自动省略，不影响日报。

### 7. 容错矩阵（PRD 决策 4）

| 故障 | 行为 |
|---|---|
| 新浪接口整体失败 / 超时 / 被限流 | quotes={} → 报告仍生成，各表显示「获取失败」/「数据暂缺」，退出码 0 |
| 单指数解析失败 | 该行「获取失败」，其余正常；errors 记录 |
| 昨收字段缺失 / 为 0 | 跳空、当前涨跌显示「—」（不除零） |
| VIX 新浪/Yahoo 均失败 | 情绪章节「VIX 数据暂缺，无法判断开盘情绪」，大盘方向仍按跳空均值输出 |
| 板块热度失败 / 超时 | 「数据暂缺」（复用 fetch_sector_heat 的 ([], []) 约定） |
| 全部失败 | 报告骨架仍落盘，退出码恒 0（对齐日报纪律） |

### 8. 测试 tests/test_phase15.py（约 15 条，全 mock，不联网）

1. `parse_sina_realtime` A 股：正常响应（今开/昨收/当前价）解析正确；
2. `parse_sina_realtime` 美股：正常响应（当前/昨收/今开）解析正确；
3. `parse_sina_realtime`：空串 / 字段不足 / 非数值 → None；
4. `fetch_realtime_quotes`：mock GET 返回 A 股 3 条 → quotes 结构正确（含 VIX Yahoo 兜底值）；
5. `fetch_realtime_quotes`：请求异常 → 空 dict + errors 记录、不抛；
6. `fetch_realtime_quotes`：VIX Yahoo 失败 → 其余指数正常，VIX 缺失进 errors；
7. `compute_gaps`：正/负跳空、缺昨收 → None（不除零）；
8. `build_opening_sentiment`：VIX 有值 → 状态 label + 描述；缺失 → 「数据暂缺」；
9. `render_opening_report`：章节结构（跳空表/板块/情绪/速览/AI 解读占位）；
10. `render_opening_report`：板块与昨收全缺 → 「数据暂缺」/「—」降级不崩；
11. `save_opening`：路径 `reports/opening/{date}-{market}.md` 且内容落盘；
12. `load_opening_refs`：两文件都存在 → 2 条引用含链接与摘要；缺失 → 空列表不抛；
13. `render_report`：`opening_refs=None` 无章节（存量行为）；传入 → 章节含链接；
14. 入口 `main`：monkeypatch fetch/render/save → 编排成功、退出码 0；
15. 零持久化：mock 全链路后断言 `data/history.json` / `last_values.json` / `context/` 均未写入（比对 mtime 或 monkeypatch 写函数未被调用）。

## 实施步骤

1. **fetcher 层**：`src/fetcher.py` +`REALTIME_URL` / `REALTIME_MARKETS` / `parse_sina_realtime` / `fetch_realtime_quotes` + 测试 1-6。
2. **分析层**：`opening_analyzer.py` 的 `compute_gaps` / `build_opening_sentiment` 纯函数 + 测试 7-8。
3. **报告层**：`src/reporter.py` +`render_opening_report` / `save_opening` + 测试 9-11。
4. **日报引用**：`load_opening_refs` + `render_report` opening_refs 参数 + `daily_report.py` 接线 + 测试 12-13。
5. **入口编排**：`opening_analyzer.py` main + argparse + 零持久化测试 14-15。
6. **实跑验证**：`venv/Scripts/python opening_analyzer.py --market a-share`（北京 9:45-10:00 时段）与 `--market us`（北京 21:45-22:00 时段）各跑一次 → `reports/opening/` 下两文件生成，内容核对（跳空/板块/情绪/速览/AI 解读占位）；非交易时段跑验证容错（VIX 用最近收盘、跳空仍按新浪昨收计算，不报错）。
7. **回归 + 文档**：`venv/Scripts/python -m pytest tests/ -v` 全量（新增 15 条 + 既有约 250 条不回归）；同步 architecture.md（模块表 + 数据流 + 关键决策）、commands.md（新命令 + 验证要点）、pitfalls.md（新浪无 VIX → Yahoo 兜底；新浪昨收直接作跳空基准不依赖缓存；开盘分析零持久化；复合名防碰撞；hq.sinajs.cn 需 Referer 头）、AGENTS.md（project map）。

## 验证命令

1. `venv/Scripts/python -m pytest tests/test_phase15.py -v` — 新增全绿（mock 网络）。
2. `venv/Scripts/python -m pytest tests/ -v` — 既有全量不回归 + 新增。
3. `venv/Scripts/python opening_analyzer.py --market a-share` — `reports/opening/YYYY-MM-DD-a-share.md` 生成；跳空/板块/情绪/速览内容核对。
4. `venv/Scripts/python opening_analyzer.py --market us` — `reports/opening/YYYY-MM-DD-us.md` 生成；VIX 情绪标注来源时点。
5. 容错：断网 / 删昨日文件 / mock 全失败 → 报告仍生成、退出码 0、无告警文件、`data/` 无写入（对比 mtime）。
6. `venv/Scripts/python daily_report.py` — 日报含「🔔 开盘分析」章节（引用当日已存在的开盘分析）；删除开盘分析文件后重跑 → 章节省略、日报正常。

## 待确认决策

- **A（默认采纳）**：报告文件复合名 `reports/opening/YYYY-MM-DD-{market}.md`（A 股/美股同日各一份）。备选：PRD 字面 `YYYY-MM-DD.md` 单文件 —— A 股 9:45 与美股 21:45 同日生成会互相覆盖，必须区分市场（七期快照复合名先例）。
- **B（默认采纳）**：VIX 情绪走 Yahoo `regularMarketPrice` 兜底（新浪实测无 VIX 数据；A 股开盘时 VIX 为上一交易日收盘，报告标注来源时点）。备选：情绪仅用 A 股指数跳空方向，完全不用 VIX —— 削弱 PRD「结合 VIX 判断开盘情绪」。
- **C（默认采纳）**：开盘分析零持久化（不写 history / last_values / context / alerts.log）。理由：开盘价非收盘价，写 history 会污染趋势图与相关性；开盘分析不告警。备选：写独立 context 供 Hermes —— 超出 PRD 范围，增加复杂度。
- **D（默认采纳）**：日报引用 = 「🔔 开盘分析」章节（每市场一行：链接 + 摘要），`render_report` 可选参数默认 None。备选：日报全文内嵌开盘分析 —— 日报过长；备选：不引用 —— 违反 Done When 第 3 条。
- **E（默认采纳）**：AI 解读 = 报告留「🤖 AI 解读」占位章节，Hermes 读取后追加 100-200 字并可选推 QQ（与日报解读/推送模式一致，脚本不含 LLM/推送逻辑）。备选：Python 侧模板生成确定性解读（非 AI）。
- **F（默认采纳）**：板块轮动 = 开盘时点领涨/领跌 Top5（当前热度快照），不做跨日对比；「轮动变化」由 Hermes 解读时结合昨日报告对比。备选：Python 读昨日开盘分析做板块榜 diff —— 依赖历史报告存在性，脆弱。
- **G（默认采纳）**：裸跑默认 `--market a-share`（A 股开盘先于美股，且新浪 A 股数据完整）。备选：默认 us（与 snapshot 裸跑惯例对齐）—— 开盘分析主场景为 A 股，默认 a-share。

## 风险与边界

- **新浪接口稳定性**：hq.sinajs.cn 为免费接口，可能限流/变更字段；解析容错 + 外层重试；字段序变更 → parse 返回 None → 降级「获取失败」，不崩。
- **非交易时段运行**：新浪返回最近收盘价（非实时），跳空/涨跌仍按昨收计算有效；文档注明「开盘分析应在开盘后 15-30 分钟运行」，cron 时点由 Hermes 配置（交付配置）。
- **VIX 依赖 Yahoo**：Yahoo 不可达 → 情绪降级「数据暂缺」，大盘方向仍可用（新浪）。
- **日报引用依赖开盘分析文件存在**：文件缺失 → 该市场行省略，日报零影响（load_opening_refs 全容错）。
- **与快照命名不冲突**：`reports/opening/` 独立目录，快照在 `reports/snapshots/`，互不干扰。
- **零持久化边界**：若未来需 Hermes 归因分析，可再议独立 context（本次明确不做，决策 C）。

## PRD Done When 对照

- opening_analyzer.py 实现 → 核心设计 3 + 步骤 2/5
- 开盘分析报告生成 → 核心设计 1/4 + 步骤 3/6（`reports/opening/YYYY-MM-DD-{market}.md`，复合名待确认 A）
- 日报中引用开盘分析 → 核心设计 4/5/6 + 步骤 4（「🔔 开盘分析」章节）
- pytest 全绿 → 步骤 7（新增约 15 条 + 既有全量不回归）
