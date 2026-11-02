# MarketPulse 十二期：相关性分析 — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`src/analyzer.py`（compute_streaks/load_history 纯函数范式、HISTORY_MAX/CORRELATION 常量位）、`src/reporter.py`（render_report 各板块拼装、generate_context 六键契约 + 原子写）、`daily_report.py`（history 单次加载复用）、`src/config.py`（trend.chart_days=30）、`tests/test_reporter.py`（sample_data 夹具）、`tests/test_context.py`（无全键相等断言，加键不破存量）。

## 目标

- 日报新增「📊 相关性分析」板块：计算 5 组关键指数对的 Pearson 相关系数（纯 Python、零新依赖）。
- 相关性矩阵表格（指数对 / 相关系数 / 有效样本），颜色编码：>0.5 红、<-0.5 绿、中间灰。
- 显著相关性（|r|>0.5）写入 `context/YYYY-MM-DD.json` 新键 `correlation`。
- 数据窗口最近 30 个交易日（复用 config `trend.chart_days`），每对至少 10 个有效数据点才计算，保留两位小数。
- pytest 全绿（存量 + 新增 tests/test_phase12.py）。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `src/analyzer.py` | 修改：新增 `CORRELATION_PAIRS` / `CORRELATION_DAYS` / `CORRELATION_MIN_POINTS` 常量 + `compute_correlation()` 纯函数 |
| `src/reporter.py` | 修改：`render_report` 加 `correlations=None` 参数 + 「📊 相关性分析」章节（含颜色 span）；`generate_context` 加 `correlations=None` 参数 + `correlation` 键 |
| `daily_report.py` | 修改：`compute_correlation(history)` 计算一次，透传给 `render_report` 与 `generate_context` |
| `tests/test_phase12.py` | 新增（约 17 条）：相关系数纯逻辑 / 报告章节与颜色 / context 键 / 入口透传 |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步（context 契约变更 → 需同步 Hermes Prompt，交付配置项，见「待确认决策 D」） |

不改：`snapshot_report.py`（快照不渲染相关性）、`web/*`（context 新增键为增量，web 只读 sector_heat 键，未知键忽略，无 schema 校验）、`src/config.py` / `config.json`（阈值/窗口 PRD 已定稿为常量，不配置化）、`src/fetcher.py`、`src/alerter.py`、`requirements.txt`（零新依赖）。

## 核心设计

### 1. `analyzer.py`：常量 + 纯函数

```python
# 十二期：相关性分析（PRD 定稿 5 组关键对；窗口/最少样本/显著阈值均为 PRD 固定值，不配置化）
CORRELATION_PAIRS = [   # (指数A, 指数B) —— 顺序即报告与 context 输出顺序
    ("VIX", "GSPC"),    # 恐慌 ↔ 标普500（负相关越强，美股对恐慌越敏感）
    ("VIX", "SH"),      # 恐慌 ↔ 上证（VIX 对 A 股传导强度）
    ("GSPC", "SH"),     # 标普500 ↔ 上证（中美股市联动）
    ("IXIC", "CYB"),    # 纳指 ↔ 创业板（中美科技股同步性）
    ("MOVE", "VIX"),    # 债市恐慌 ↔ 股市恐慌
]
CORRELATION_DAYS = int(_CFG["trend"]["chart_days"])   # 窗口 30 交易日，与趋势图同一配置源（单事实来源）
CORRELATION_MIN_POINTS = 10                            # 至少 10 个有效数据点
CORRELATION_SIGNIFICANT = 0.5                          # |r| 显著阈值（颜色编码与 context 写入共用）
```

```python
def compute_correlation(history, pairs=None, window=None) -> list[dict]:
    """计算指定指数对的 Pearson 相关系数（纯 Python，零依赖）。

    窗口 = 最后 window 行（默认 CORRELATION_DAYS=30）；每对取两序列均非 None/非数值缺口的
    对齐点，有效点数 >= CORRELATION_MIN_POINTS(10) 才计算，否则 r=None。
    常量序列（零方差）→ r=None；浮点误差钳制到 [-1,1]，保留两位小数。
    返回 [{a, b, pair, r, n}]，顺序 = pairs 顺序。纯计算、可单测。
    """
```

- Pearson 公式（内联私有 `_pearson(xs, ys)`，不开新函数名污染）：
  `mx/my` 均值 → 协方差/方差 → `r = cov / sqrt(vx*vy)`；`vx==0 or vy==0` → None。
- 对齐抽取：`[(x, y) for r in rows if isinstance(r.get(a_lower), (int, float)) and isinstance(r.get(b_lower), (int, float))]`（与 compute_streaks 同款 isinstance 容错）。
- 键派生：`a.lower()` / `b.lower()`（history 存小写键，六期B 教训）。
- `pair` 展示串 = 复用 `SYMBOLS` 注册表 label：`f"{SYMBOLS[a]['label']} ↔ {SYMBOLS[b]['label']}"`（见「待确认决策 B」）。

### 2. `reporter.py`：报告章节 + 颜色编码

- `render_report(..., correlations=None)`：新关键字参数，默认 None → 章节省略（存量测试与调用零影响）。
- 章节插在「📈 波动率指数」表之后、「🏷️ 市场状态」之前（相关性主涉 VIX/MOVE，与波动率相邻）。

```markdown
---

## 📊 相关性分析

| 指数对 | 相关系数 | 有效样本 |
| :--- | :--- | :--- |
| VIX（恐慌指数） ↔ 标普500 | <span style="color:#d1495b">**-0.72**</span> | 30 |
| ... | ... | ... |

> 窗口：近 30 个交易日；每对需 ≥10 个有效样本；|r|>0.5 视为显著相关。
```

- 颜色规则（复用既有柔和色系，pitfalls 纪律）：
  - `r > 0.5` → 红 `#d1495b`；`r < -0.5` → 绿 `#1a9e6c`；否则灰 `#999999`。
  - `r is None` → 灰 `#999999` 显示「数据不足」，样本数列出实际 n。
  - 数值带符号两位小数（`+0.62` / `-0.72`），HTML `<span style="color:...">` 实现（QQ Markdown 可渲染，不引入新依赖）。
- 辅助私有函数 `_correlation_row_md(item)` 拼单行（可单测）。

### 3. `reporter.py`：context 新键 `correlation`

- `generate_context(..., correlations=None)`：新关键字参数；payload 新增：

```jsonc
"correlation": [   // 仅 |r| > 0.5 的显著对（PRD 字面）；无显著/未传 → []
  { "a": "VIX", "b": "GSPC", "pair": "VIX（恐慌指数） ↔ 标普500", "r": -0.72, "n": 30 }
]
```

- 键恒存在（空列表兜底，与 `sector_heat` 同契约纪律）；context 契约变更 → 同步 Hermes Prompt（决策 D）。
- 原子写机制不动；`correlations=None` 时不抛、写 `[]`（存量 context 测试零影响）。

### 4. `daily_report.py`：单次计算、双消费点透传

- `history = load_history()` 之后 `correlations = compute_correlation(history)`（report 阶段历史未含当日，与趋势图「排除当日」语义一致；九期「history 单次加载复用」纪律）。
- `render_report(..., correlations=correlations)` 与 `generate_context(..., correlations=correlations)` 透传同一对象（报告与 context 数值一致）。
- 纯函数调用不加 try/except（与 compute_streaks 同风格；compute_correlation 自身对异常数据防御）。

## 实施步骤

1. **analyzer.py**：加 4 个常量 + `compute_correlation()` + 私有 `_pearson()`。验证：`venv/Scripts/python -m pytest tests/test_analyzer.py -v` 不回归。
2. **reporter.py**：`_correlation_row_md` + `render_report` 章节 + `generate_context` 键。验证：`venv/Scripts/python -m pytest tests/test_reporter.py tests/test_context.py -v` 不回归。
3. **daily_report.py**：计算 + 双透传。验证：`venv/Scripts/python -m pytest tests/test_phase7.py tests/test_phase8.py -v`（入口编排既有测试不回归）。
4. **tests/test_phase12.py** 新增（见下）。验证：`venv/Scripts/python -m pytest tests/test_phase12.py -v` 绿。
5. **全量回归**：`venv/Scripts/python -m pytest tests/ -v`（既有 231 条不回归 + 新增全绿）。
6. **实跑验证**（见「验证命令」）：`venv/Scripts/python daily_report.py`，检查报告「📊 相关性分析」章节与 `context/YYYY-MM-DD.json` 的 `correlation` 键；数据不足时显示「数据不足」不崩。
7. **文档同步**：architecture.md（analyzer/reporter 职责 + context 契约七键 + 报告新章节）、commands.md（验证要点）、pitfalls.md（Pearson 边界：零方差/对齐/最小样本/窗口语义/颜色复用）、AGENTS.md（project map 中 analyzer/reporter/context 描述）。

## 新增测试 tests/test_phase12.py（约 17 条）

- **TestComputeCorrelation**（analyzer，纯逻辑）：
  1. 完全正相关（x==y）→ r == 1.0；
  2. 完全负相关（y = -x + c）→ r == -1.0；
  3. 无关序列（确定性构造）→ |r| < 0.5 且方向符合预期；
  4. 有效点 <10 → r None、n 正确；
  5. 单侧 null 行被剔除（20 行含 5 个 null → n=15，数值正确）；
  6. 常量序列（零方差）→ r None；
  7. 窗口截断：40 行 → 只用最后 30 行；
  8. 默认 5 对、顺序与键（a/b/pair/r/n）正确；
  9. 保留两位小数（r = 0.666… → 0.67）。
- **TestRenderReportCorrelation**（reporter，复用 test_reporter.sample_data）：
  10. 传 correlations → 含「📊 相关性分析」章节与 5 行表；
  11. r>0.5 红 span / r<-0.5 绿 span / 中间灰 span 断言；
  12. correlations=None → 无该章节（存量兼容）；
  13. r=None 行 → 「数据不足」。
- **TestGenerateContextCorrelation**（reporter + tmp 夹具，仿 test_context）：
  14. 显著对（|r|>0.5）写入 `correlation`，字段 {a,b,pair,r,n} 与原子写（无 .tmp 残留）；
  15. 无显著 → `correlation == []`；
  16. correlations=None → `correlation == []`。
- **入口透传**（monkeypatch daily_report 的 fetch_all/render_report/generate_context/append_history 等，仿 test_phase8「入口透传」范式）：
  17. main 中 render_report 与 generate_context 收到同一 correlations 对象。

## 验证命令（对应 PRD Verification）

1. `venv/Scripts/python -m pytest tests/ -v` — 全量全绿（既有 231 条不回归 + 新增 ~17 条）。
2. `venv/Scripts/python daily_report.py` — 报告含「## 📊 相关性分析」章节，表格 5 行（指数对/相关系数/有效样本），>0.5 红、<-0.5 绿、中间灰；`context/YYYY-MM-DD.json` 含 `correlation` 键（显著对 |r|>0.5；无则 `[]`）；退出码 0。
3. 数据不足场景（临时用 ≤10 条有效对的 history 或新环境）：报告显示「数据不足」灰字、不崩、退出码 0。
4. 验证后恢复 `data/last_values.json` 原值并清理验证期临时文件（生成物可保留）。

## 待确认决策

- **A（默认采纳）**：context 的 `correlation` 仅写入显著对（|r|>0.5），报告表展示全部 5 对（不足显示「数据不足」）。备选：context 写入全部对 + significant 标志——PRD 字面「显著相关性写入 context.json」，按字面落地。
- **B（默认采纳）**：指数对展示用 SYMBOLS 注册表全 label（如「VIX（恐慌指数） ↔ 标普500」）。备选：符号对（VIX ↔ GSPC，机器友好但中文读者不直观）或 PRD 混合式（VIX ↔ 标普500，格式不统一）。全 label 复用注册表零重复定义。
- **C（默认采纳）**：窗口语义 = history 行数最后 30 行（与趋势图 `rows[-TREND_DAYS:]` 一致），非自然日；report 阶段历史未含当日（与图表「排除当日」一致），context 与报告同一份数值。
- **D（必须知会）**：context 契约新增 `correlation` 键 → Hermes Prompt 需同步（交付配置项非仓库文件，实施完成后在 journal 中留交接记录；Python 侧无额外动作）。

## 风险与边界

- **零方差除零**：Pearson 在常量序列下 `vx*vy == 0` 会除零——`_pearson` 先判 `vx==0 or vy==0` 返回 None，不抛（零新依赖纯 Python 的正确性关键）。
- **浮点越界**：完美相关可算出 `1.0000000002`——先钳制 [-1,1] 再 round 两位。
- **存量测试回归**：`render_report`/`generate_context` 均加默认 None 的关键字参数，不传 = 行为不变；test_context 无全键相等断言，加 `correlation` 键不破。
- **历史数据不足**：新装/短历史下 5 对全「数据不足」是设计行为（与趋势图「Insufficient Data」一致），不崩。
- **web 看板**：context 加键为增量，web 只读 sector_heat 键，未知键忽略——零影响（实施后在 commands.md 记录）。
- **另类资产不参与**：GLD/BTC 不在 5 对中（PRD 分析范围定稿，另类资产不告警同理）。

## PRD Done When 对照

- analyzer.py 新增 compute_correlation() 函数 → 核心设计 1 + 步骤 1
- 日报新增「📊 相关性分析」板块 → 核心设计 2 + 步骤 2
- 相关性数值带颜色标记 → 核心设计 2（红 #d1495b / 绿 #1a9e6c / 灰 #999999）
- 显著相关性写入 context.json → 核心设计 3 + 步骤 2
- pytest 全绿 → 步骤 4-5
