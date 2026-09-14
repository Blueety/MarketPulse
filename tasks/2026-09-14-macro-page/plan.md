# 计划：宏观数据独立页（`/macro`）—— Apple × Financial Research Terminal

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-macro-page/`
- **输入**：`宏观数据页 Task Handoff`（PRD）
- **架构师职责**：核对 PRD 假设 → 调研业界方案 → 实测可行性 → 出可落地计划

---

## 1. 结论先行

**PRD 方向成立，但有 2 处核心假设不成立、1 处隐藏实现坑。已全部找到有出处的解决路径。**

| # | PRD 假设 | 核对结果 |
|---|---|---|
| 1 | `/api/macro` 提供美元/10Y/原油/黄金，支持三级回退 + TTL | ✅ **成立**（`web/app.py:551-556`）|
| 2 | **「correlation 已存在，可作为宏观关系的数据基础」** | ❌ **不成立** → 见 §2.1，已有替代方案 |
| 3 | 时间范围含 **5Y** | ⚠️ **不可得**（现状 400 天）→ 实测可扩，见 §2.3 |
| 4 | **「进入独立页面」** | ⚠️ 现状是单页锚点架构，「宏观数据」是 `is-disabled` 占位 → 见 §2.2 |
| 5 | `Macro Score 68/100` | ❌ 现有 score 是 **-3~+3 的 3 因子波动率分**，非百分制、无宏观维度 → 见 §3 |
| 6 | 历史宏观环境（30 天分布） | ⚠️ 需**逐日回放**（现有函数只算最新一天），数据够、逻辑是新增 |

**已定决策（需求方 2026-09-14）**：
- 页面形态 → **新增路由 `GET /macro`**（独立第二页）
- 宏观关系 → **调研业界方案**（结论见 §3.2）
- Macro Score → **调研业界方案**（结论见 §3.1）
- 时间范围 → **扩 tail 到 5 年**（实测可行，见 §2.3）

---

## 2. PRD 假设核对（含证据）

### 2.1 ❌ 「correlation 可作宏观关系的数据基础」不成立

PRD 举例：美元↔黄金、10Y↔纳指、原油↔通胀

实际 `src/analyzer.py:68-74`：

```python
CORRELATION_PAIRS = [
    ("VIX", "GSPC"), ("VIX", "SH"), ("GSPC", "SH"), ("IXIC", "CYB"), ("MOVE", "VIX"),
]
```

**只有 5 对，全是「指数↔指数」，一对宏观都没有。**

**根因**：`compute_correlation` 基于 `history`（10 个指数，`_HISTORY_KEYS`），而宏观品种是**实时取数、不入 history** 的（`_load_macro` → `fetch_watchlist`，只返回不落盘）。

**解决路径（§3.2 有调研支撑）**：`/api/macro` 返回的 `trend` 带**原始序列**（`raw` 字段 + `dates`），扩到 5 年后有 **1255~1521 个交易日** → **宏观两两相关可在 web 层现算**，零数据管线改动。

⚠️ 但「原油↔通胀」**没有数据源**（库内无通胀序列）→ 第一版不做，换成本库可得的对。

### 2.2 ⚠️ 「独立页面」与单页锚点架构冲突

现状（`index.html:47-58`）：导航全是锚点

```html
<a class="nav-item" href="#overview" data-target="overview">…市场概览</a>
…
<span class="nav-item is-disabled" title="未开放">…宏观数据</span>   ← 占位项
```

整个看板只有 `index.html` 一个页面模板。

**已定：新增路由 `GET /macro`。** 但这带出两个必须解决的问题：

1. **侧栏/顶栏共用** → 抽 Jinja include（项目已用 Jinja2，零新依赖），还是复制一份？
2. **跨页导航语义** → 首页用锚点（`#overview`），宏观页的侧栏要回首页得用 `/#overview`。需要在 include 里参数化 href 前缀。

⚠️ 抽 include 会改动 `index.html`，而 `verify_ui.py` 有大量断言依赖它。**渲染结果不变，断言应全绿** —— 但必须实测确认。

### 2.3 ⚠️ 5Y 数据不可得（但可扩，且实测很快）

`web/app.py:600` → `_build_watchlist_payload(stocks, values, series, tail=400)`

而取数层 `src/fetcher.py:565-571`：

```python
def _fetch_yahoo_watch(symbol):
    """…range=2y, interval=1d；三十四期窗口放宽到 2 年，深度由调用方 _series_tail 决定…"""
    resp = _yahoo_chart_get(symbol, {"interval": "1d", "range": "2y"})
```

→ 实际只有 400 点 ≈ 1.6 年。

**实测 Yahoo 5 年覆盖（本轮亲自跑的）**：

| 品种 | 1y | **5y** | 10y | 5y 耗时 |
|---|---|---|---|---|
| 美元指数 DX-Y.NYB | n=303 | **n=1521** | n=3038 | 0.4s |
| 10Y美债 ^TNX | n=252 | **n=1255** | n=2514 | 0.3s |
| 原油 CL=F | n=251 | **n=1260** | n=2516 | 0.4s |
| 黄金 GC=F | n=251 | **n=1260** | n=2516 | 0.3s |

→ **5Y 数据完整可得，耗时与 1y 同级（0.3~0.4s）**，扩到 5 年成本可忽略。

⚠️ **隐藏坑**：`range=2y` 是**自选股与宏观共用**的。直接改成 `5y` 会让 `/api/watchlist` 也多取 2.5 倍数据（它只需要 30 天）。
→ **必须给 `_fetch_yahoo_watch` 加 `range` 参数**（默认 `2y` 保持不变，宏观传 `5y`），并透传 `fetch_watchlist(stocks, range=...)`。**零影响自选股链路。**

---

## 3. 调研结论（需求方要求，含出处）

### 3.1 Macro Score —— 采用 Equicurious 四指标仪表盘方法论

**出处**：Equicurious《Using Risk-On/Risk-Off Dashboards》

| 项 | 做法 |
|---|---|
| 指标数 | **4 个主要指标**（次要指标不参与计分） |
| 每项打分 | **-2 ~ +2**（五档区间） |
| 原始总分 | **-8 ~ +8**（4 × ±2） |
| 归一化 | **总分 ÷ 8** → **-1 ~ +1** |
| 状态映射 | `> +0.25` → **Risk-On** · `-0.25 ~ +0.25` → **Neutral** · `< -0.25` → **Risk-Off** |
| 权重 | 文章说明"60/40 只是示例，**等权同样合理**；关键是**在需要之前就先定好权重**，而不是去优化它" |

原文四指标为：VIX（水平 + 20日均线）、IG 信用利差、HY 信用利差、DXY（相对 50 日均线）。

**我们的适配（关键）**：库内**没有信用利差**（需 FRED）。改用本库可得数据填满 PRD 要求的四维度：

| PRD 维度 | 我们的指标 | 打分依据（现有能力） |
|---|---|---|
| **风险偏好** | VIX + MOVE | `analyzer.classify_vix` / `classify_move` **已有阈值**，单一事实来源 |
| **美元** | DX-Y.NYB 相对 N 日均线偏离 | 偏离幅度分档（±1%/±2%） |
| **利率** | ^TNX（10Y）变化方向 | 5 日变化幅度分档 |
| **商品** | CL=F 原油（+ GC=F 黄金）变化 | 5 日变化幅度分档 |

**100 分制映射（满足 PRD 的 `68/100` 展示）**：
```text
macro_score = (normalized + 1) / 2 * 100      # normalized ∈ [-1, +1] → score ∈ [0, 100]
```
验算：`normalized = +0.36` → `68` ✅ 自洽。

⚠️ **诚实标注**：美元/利率/商品的**分档阈值是工程取值**（参考 Equicurious 的档位形态），非行业标准。前端需标注「评分口径」，并在 plan/journal 记录，避免被当成权威指标。

**PRD Risks 的呼应**：PRD 说"不要伪造复杂 Macro Score"。本方案**有出处、每步可解释、纯函数可单测**，不是伪造 —— 但阈值必须标注来源与性质。

### 3.2 宏观关系 —— 1-year rolling correlation（业界惯例）

**调研到的做法**：

| 来源 | 做法 |
|---|---|
| Convex《Cross-Asset Correlation Matrix》 | **1-year rolling correlations, updated daily** |
| thetrading.tools《Cross-Asset Macro Panel》 | **15 个品种合成 4 个宏观维度**（与 PRD 四维度设计吻合） |
| Perspicium / TradingView | 相关性矩阵 + rolling 窗口 |

**结论：用 1 年滚动窗口算两两相关**（4 变量 → **6 对**），只展示 `|r|` 显著的对。

**为什么用 1 年**：短窗口（30 日）噪声大、长窗口（5 年）掩盖 regime 切换；1 年是业界常见折中。

**数据来源**：`/api/macro` 的 `trend.raw`（扩到 5y 后有 ~1260 点，足够 1 年窗口）。

**可支持的对**：

| 类型 | 对 | 可行性 |
|---|---|---|
| 宏观内部 | 美元↔黄金 · 美元↔原油 · 美元↔10Y · 黄金↔原油 · 黄金↔10Y · 原油↔10Y | ✅ 同源，日期天然对齐 |
| 宏观↔股市 | 美元↔标普 · 10Y↔纳指 · 原油↔标普 | ✅ 跨源，但**日期口径一致**（`_fetch_yahoo_watch` 用 `EASTERN_TZ`，history 亦是美东）→ 可对齐 |
| 原油↔通胀 | — | ❌ **无数据源，第一版不做** |

⚠️ **不复用 `compute_correlation`**（它绑定 `history` 的 10 个指数键）。新增独立纯函数 `compute_macro_correlation(macro_series, index_series, window)`，复用 `analyzer._pearson` / `_returns`。

---

## 4. 架构决策

### 4.1 页面形态：新增路由 + 抽 Jinja include

```text
GET /                     → index.html（首页，现有，逻辑不变）
GET /macro                → macro.html（新页）
```

**侧栏/顶栏处理**：抽 `web/templates/_shell.html`（含 topbar + sidebar），两页 include。

- **零新依赖**（项目已用 Jinja2）
- **参数化**：`{% include "_shell.html" %}` 由上下文变量驱动
  - `base_prefix`：index 页为 `''`，macro 页为 `'/'` → 首页锚点链接变 `/#overview`
  - `active_page`：`'dashboard'` / `'macro'` → 决定哪一项高亮
  - `macro_enabled`：**index 页"宏观数据"项从 `is-disabled` 改为 `<a href="/macro">`**
- **渲染结果不变** → `verify_ui.py` 既有断言应全绿（**但必须实测确认**）

⚠️ 抽 include 会改动 `index.html`（235 行，含大量内联 SVG）。**这是本任务最大的回归风险**，见 §7 R1。

### 4.2 数据层改动（最小化）

| 改动 | 位置 | 影响面 |
|---|---|---|
| `_fetch_yahoo_watch(symbol, range='2y')` 加参数 | `src/fetcher.py:565` | 默认值不变 → **自选股零影响** |
| `fetch_watchlist(stocks, range='2y')` 透传 | `src/fetcher.py` | 同上 |
| `_load_macro` 传 `range='5y'` + `tail=1260` | `web/app.py:592-603` | 仅宏观端点 |
| 新增 `_macro_correlation` 计算 + `/api/macro` 加 `correlation` 键 | `web/app.py` | 仅宏观端点 |
| 新增 `/macro` 路由 | `web/app.py` | 新增，不影响现有 |

⚠️ **Web 只读、零写盘**约束不变 —— 所有计算在内存完成，不落盘。

### 4.3 页面信息架构（对应 PRD 七模块）

| # | 模块 | 数据来源 | 第一版 |
|---|---|---|---|
| 1 | **宏观环境**（顶部） | 新增 `macro_regime` 计算（§3.1） | ✅ |
| 2 | **核心宏观变量**（4 张） | `/api/macro` 的 `stocks` | ✅ |
| 3 | **宏观主图**（单大图 + 胶囊切换 + 1M/3M/6M/1Y/5Y） | `/api/macro` 的 `trend`（raw） | ✅ |
| 4 | **宏观因子**（美元/利率/通胀/风险偏好） | 同 §3.1 的四维度明细 | ✅ |
| 5 | **宏观关系** | 新增 `correlation`（§3.2） | ✅ |
| 6 | **历史宏观环境**（30 天分布） | 新增逐日回放 | ⚠️ **见下** |
| 7 | 经济数据（CPI/PCE/GDP/PMI） | — | ❌ Out of Scope |

**模块 6 的处理**：需要**逐日回放** `_compute_risk_appetite` 式的打分（现有函数只算最新一天）。
- 数据够（history 有 ~1260 天）
- **但"通胀/通缩/滞胀"需要通胀与增长序列，库内没有** → 第一版**只做 Risk-On/Neutral/Risk-Off 三态分布**，不做四象限（Inflation/Deflation/Stagflation）
- 与 PRD「状态算法不足的部分不要凭空编造」一致

---

## 5. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/fetcher.py` | 改 2 处 | `_fetch_yahoo_watch` / `fetch_watchlist` 加 `range` 参数（**默认 2y 不变**）|
| `web/app.py` | 改 1 处 + 新增约 90 行 | `_load_macro` 传 5y/1260；新增 `_compute_macro_regime` / `compute_macro_correlation` / `_macro_history_regime`；`/api/macro` 加键；新增 `GET /macro` |
| `web/templates/_shell.html` | **新建** | 顶栏 + 侧栏（参数化 `base_prefix` / `active_page`）|
| `web/templates/index.html` | 改 | 抽走 shell 后改为 include；"宏观数据"项改可点 |
| `web/templates/macro.html` | **新建** | 宏观页骨架（7 模块）|
| `web/static/macro.js` | **新建** | 宏观页逻辑（主图 + 胶囊 + 时间范围 + 各模块渲染）|
| `web/static/style.css` | 追加约 120 行 | 宏观页样式（research terminal 风格，**不复用首页 bento token 逻辑**）|
| `tests/test_web.py` | 新增约 60 行 | `/macro` 路由 + `_compute_macro_regime` + 相关纯函数 |
| `tasks/2026-09-14-macro-page/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` / `docs/architecture.md` | 追加 | 见 §8 |

**不改**：`daily_report.py` / `snapshot_report.py` / `src/analyzer.py` 的 `CORRELATION_PAIRS` / `generate_context` / 任何数据落盘。

---

## 6. 实现步骤

### M-0 · 基线（必测，抽 include 前）

```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # 记录 EXIT / scrollH / 断言数
venv/Scripts/python -m pytest tests/ -v                                     # 记录通过数
```

### M-1 · 取数层加 `range` 参数（**零影响自选股**）

```text
def _fetch_yahoo_watch(symbol, range_="2y"):        # 默认值 = 现有行为
    resp = _yahoo_chart_get(symbol, {"interval": "1d", "range": range_})

def fetch_watchlist(stocks, range_="2y"):
    … _fetch_yahoo_watch(sym, range_) …
```

**验证**：`pytest tests/ -v` 全绿（默认值不变 → 不应有任何失败）。

### M-2 · `/api/macro` 扩到 5 年

```text
_load_macro(): fetch_watchlist(stocks, range_="5y") → _build_watchlist_payload(..., tail=1260)
```

**验证**：`curl http://localhost:<port>/api/macro` → `trend.dates` 长度 ≈ 1260，且**耗时仍 < 2s**。

### M-3 · 新增纯函数（可单测，不联网）

| 函数 | 职责 |
|---|---|
| `_compute_macro_regime(stocks_values, ...)` | 四维度 -2~+2 打分 → 总分 → 归一化 → `{level, score, score100, factors}` |
| `compute_macro_correlation(macro_series, index_series, window=252)` | 1 年滚动窗口两两相关 → `[{a,b,pair,r,n}]` |
| `_macro_history_regime(records, days=30)` | 逐日回放 → `{risk_on: n, neutral: n, risk_off: n}` |

**验证**：新增单测覆盖（正常 / 数据不足 / 零方差 / 常量序列）。

### M-4 · 抽 `_shell.html`

把 `index.html` 的 `<header class="topbar">` + `<aside id="sidebar">` 抽到 `_shell.html`，参数化：

```text
{% include "_shell.html" %}       <!-- base_prefix / active_page 由渲染上下文提供 -->
```

`index.html` 的"宏观数据"项：

```html
<!-- 从 is-disabled span 改为 -->
<a class="nav-item" href="/macro" data-target=""><svg …/><span>宏观数据</span></a>
```

**验证**（**本步最关键**）：
```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
→ 必须仍是 EXIT=0 / ALL PASSED（渲染结果应完全不变）
```
⚠️ 若断言失败，**先回滚 include，改走"复制侧栏"方案**（§7 R1 的 fallback）。

### M-5 · `/macro` 页面

`web/app.py`：

```text
@app.get("/macro", response_class=HTMLResponse)
def macro_page():
    return _TEMPLATES.get_template("macro.html").render(base_prefix="/", active_page="macro")
```

`macro.html` 骨架（7 模块，对应 PRD 布局）：

```text
宏观数据
┌ 当前宏观环境 ─────────────────────────────┐   ← Risk-On + Score 68 + 四维度方向 + 更新时间
├ 宏观市场（单大图 + 胶囊 + 1M/3M/6M/1Y/5Y）┤   ← canvas#macro-chart
├ 核心宏观变量（4 张）│ 宏观因子（4 项）      ┤
├ 宏观关系（显著对）                          ┤
└ 历史宏观环境（30 天三态分布）                ┘
```

### M-6 · `macro.js` 主图

**复用现有主图范式**（`app.js` 的 `#chart-main` + 4 类别 tab）：单 `canvas` + 胶囊切换 + `maintainAspectRatio:false` + 容器 `clamp()` 高度。

⚠️ **严格遵守项目 C2 教训**：**禁止**用 `!important` 覆盖 canvas 尺寸；`maintainAspectRatio: false` 必设；容器高度用 `clamp()`。断言 `canvas.width === canvas.offsetWidth`。

**单变量** → 显示真实价位（10Y 用 `%` 保留 3 位小数，原油/黄金 2 位）
**多变量** → 标准化（起点 = 100），避免量纲混画（PRD 明确要求）

⚠️ **`^TNX` 的口径**：Yahoo 的 `^TNX` 是**收益率 × 10**（如 `42.5` 表示 4.25%）。**必须除以 10 再显示**，否则 10Y 会显示成 42.5%。→ 这是 PRD Verification 里专门点名的一项。

### M-7 · 样式（research terminal 风格）

新增样式段，**不复用首页 bento 卡片 token 逻辑**：

- 大留白 / 极浅背景 / 细边框（1px `--glass-border`）/ 轻阴影 / 中等圆角
- **低饱和状态色**（复用 `--green/--red` 但降低不透明度）
- 数字与标题层级明显（沿用 `--mono` + `tabular-nums`）
- 图表视觉权重最大（主图高度 ≥ 首页主图）
- **不堆彩色卡片**、不做 Bloomberg 式信息堆叠

**Light / Dark 双主题**必须都验。

### M-8 · 验收

见 §7.4 多尺寸 + `verify_ui.py` 扩展。

### M-9 · 记录

- journal：Macro Score 阈值取值理由与出处、5Y 实测数据、抽 include 的回归结果。
- `docs/architecture.md` 追加决策条目（新路由 + 评分口径 + 相关性独立函数）。
- `docs/pitfalls.md` 追加：
  1. **`range` 参数共用陷阱**：`_fetch_yahoo_watch` 被自选股与宏观共用，改 range 必须参数化。
  2. **`^TNX` 是收益率×10**：直接用会把 4.25% 显示成 42.5%。
  3. **抽 Jinja include 后用 Playwright 断言确认渲染未变**：重构共享片段必须跑既有 UI 验收。

---

## 7. 复现路径与关键测量点（UI 类必填）

### 7.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8023`（**换新端口**，防 CSS/模板缓存假阴性）
3. 首页 `http://127.0.0.1:8023/` → 点侧栏「**宏观数据**」
4. **现状**：该项是灰化不可点的「未开放」占位
5. **目标**：进入 `http://127.0.0.1:8023/macro` 独立页面
6. 页内检查：顶部宏观环境 → 主图胶囊切换（美元/10Y/原油/黄金）→ 时间范围（1M/3M/6M/1Y/5Y）→ 宏观因子 → 宏观关系 → 历史环境

### 7.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| `/macro` HTTP 状态 | `curl -o /dev/null -w "%{http_code}"` | **200** |
| `/api/macro` 的 `trend.dates` 长度 | JSON | **≈1260**（5Y） |
| `/api/macro` 响应耗时 | `curl -w "%{time_total}"` | **< 2s** |
| 首页既有断言 | `verify_ui.py` | **EXIT=0 / ALL PASSED**（抽 include 后不变）|
| `#macro-chart` 的 `canvas.width` vs `offsetWidth` | DOM | **相等**（C2 回归护栏）|
| 10Y 美债显示值 | 页内文本 | **≈4.xx%**（**不是 42.5%**）|
| 多变量对比时 y 轴起点 | 图表 | 全部从 **100** 起 |
| 5Y 档点数 | 图表 | **>1000** |
| Light / Dark | 目视 | 两套都克制、无彩色卡片堆叠 |
| 数据缺失态 | 断网 | 显示「数据暂缺」+ 更新时间，**不显示错误旧值** |

### 7.3 box-sizing 说明

`style.css:51` 全局 `* { box-sizing: border-box }`，无例外。

1. **宏观页不参与 `scrollHeight ≤1240` 护栏**（该护栏只针对首页 `index.html`）。宏观页是独立页面，高度自由。
2. **主图容器高度必须显式给定**：沿用 `#chart-main-wrap { height: clamp(300px, 40vh, 460px) }` 的范式；宏观页主图建议**不低于首页**（PRD 要求"图表成为视觉中心"）。⚠️ 容器无高度时 Chart.js 会塌成 0。
3. **`maintainAspectRatio: false` 是必需项** —— 否则 Chart.js 按 canvas 内在比例撑高，与容器 `clamp()` 打架（C2 根因）。
4. **多变量标准化图的 y 轴**：起点 100 是**数据变换**（`v / v[0] * 100`），不是坐标轴设置 —— 不要试图用 `min: 100` 实现。
5. **`.ico` 等既有组件复用**：`16px` 固定尺寸 + `flex-shrink: 0`，在新栅格里不会变形。

### 7.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 主图占满宽、视觉中心；顶部环境区与主图之间留白充足；无横向溢出 |
| **1280×720** | 主图仍有足够高度（不低于 300px）；两列区（核心变量 / 宏观因子）仍并排 |
| **375×812** | **自然降为单列**；主图可读；胶囊按钮不溢出；表格/长文本不横向撑破 |
| **双主题** | Light / Dark 各自克制；状态色低饱和；图表色随主题切换 |

---

## 8. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **抽 Jinja include 破坏首页既有断言** | **高** | M-4 后**必须**跑 `verify_ui.py`；失败则**回滚改为"复制侧栏"**（零回归风险，代价两处维护） |
| **R2** | `range=2y → 5y` 波及其它链路 | **高** | **必须参数化**（默认 `2y` 不变）；M-1 验证 `pytest` 全绿 |
| **R3** | **`^TNX` 收益率×10 口径** | **高** | M-6 显式除以 10；§7.2 有专项测量点（PRD 也点名了） |
| **R4** | **Macro Score 阈值被当成权威指标** | **中** | §3.1 标注工程取值与出处；前端显示「评分口径」说明；写入 journal |
| **R5** | 5Y 数据拉长 → 响应体变大 | **中** | 实测 5y 耗时 0.3~0.4s；若响应过大可只传 `raw` 的首尾或降采样 |
| **R6** | 宏观关系数据不足（新上市品种 / 日期不齐） | **中** | 纯函数返回 `r=None`；前端显示「样本不足」，**不显示错误的 0** |
| **R7** | 模块 6 只有三态、没有 Inflation/Deflation/Stagflation | **中** | 库内无通胀/增长序列 → **第一版只做三态**，与 PRD「不要凭空编造」一致 |
| **R8** | 页面过度卡片化（PRD 首要担心） | **中** | 明确 research terminal 风格；主图优先；**禁止堆彩色卡片** |
| **R9** | 新增路由与首页导航语义混用（锚点 vs 路由） | **中** | `_shell.html` 参数化 `base_prefix`；宏观页侧栏用 `/#overview` 回首页 |
| **R10** | 主题切换在宏观页失效 | **中** | `macro.js` 需复用 `localStorage["mp-theme"]` + `html.light` 类 + 图表重渲染（现有机制）|
| **R11** | Chart.js CDN 不可达 | **低** | 沿用既有降级文案「图表加载失败」 |
| **R12** | Web 只读约束被破坏 | **低** | 所有新计算在内存完成，**不落盘**；M-8 复核 |

---

## 9. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `src/fetcher.py` | +约 8 / −4 行（range 参数化）|
| 修改 | `web/app.py` | +约 90 / −6 行（3 个纯函数 + `/macro` 路由 + macro 端点扩 5y）|
| 修改 | `web/templates/index.html` | −约 60 行（shell 抽走）+ 2 行（宏观项改可点）|
| 新建 | `web/templates/_shell.html` | 约 70 行 |
| 新建 | `web/templates/macro.html` | 约 180 行 |
| 新建 | `web/static/macro.js` | 约 320 行 |
| 修改 | `web/static/style.css` | +约 120 行 |
| 修改 | `tests/test_web.py` | +约 60 行 |
| 新增 | `tasks/2026-09-14-macro-page/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/architecture.md` / `docs/pitfalls.md` | 决策条目 + 3 条坑 |

**净代码变更估算**：约 **+850 / −70 行**（本任务显著大于此前的前端任务）。

---

## 10. 不做什么

- **不做 CPI / PCE / GDP / PMI**（PRD 明确的 Out of Scope）
- **不做复杂热力图**（宏观关系只列显著对）
- **不做 AI 自动宏观研报**
- **不重构首页**（只抽 shell，布局与逻辑不变）
- **不新增宏观数据供应商**
- **不改 `CORRELATION_PAIRS` / `generate_context` / 任何数据落盘**
- **不把宏观品种写入 history**（改用 web 层现算，避开数据管线）
- **不在第一版做 Inflation / Deflation / Stagflation 四象限**（无通胀与增长序列）

---

## 11. 确认

- [ ] 已确认 **§2.1**：现有 `correlation` 无宏观对，改用 `/api/macro` 序列现算
- [ ] 已确认 **§2.2**：新增路由 `/macro` + 抽 `_shell.html`（含 **R1 回滚预案**）
- [ ] 已确认 **§2.3**：5Y 实测可得（n≈1260 / 0.3~0.4s），但 **`range` 必须参数化**（R2）
- [ ] 已确认 **§3.1**：Macro Score 采用 Equicurious 四指标法（-8~+8 → ÷8 → ±0.25 阈值），阈值标注为工程取值
- [ ] 已确认 **§3.2**：宏观关系用 **1 年滚动窗口**（业界惯例），只列显著对
- [ ] 已知悉 **`^TNX` 是收益率×10**，必须除以 10（R3）
- [ ] 已确认 **模块 6 第一版只做三态分布**，不做四象限（R7）
- [ ] 已确认宏观页**不受首页 `scrollHeight ≤1240` 护栏约束**（独立页面）
- [ ] 已确认 **Web 只读、零写盘**约束不变
