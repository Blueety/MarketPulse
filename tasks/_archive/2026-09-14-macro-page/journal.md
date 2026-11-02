# 执行记录：宏观数据独立页（`/macro`）—— Apple × Financial Research Terminal

- **日期**：2026-09-14
- **计划**：`tasks/2026-09-14-macro-page/plan.md`（已含执行者反馈后的 5 处更正）
- **前置**：`tasks/2026-09-14-econ-data-source` ✅ 已完成（提供 `/api/econ`）
- **状态**：**M-0 ~ M-9 全部完成并实测**（含最高风险的抽 include 与宏观页 UI 验收）

---

## 1. 进度与实测（逐条）

### M-0 基线

```
pytest tests/ -q                → 592 passed
verify_ui.py                    → FAILED 4（全部是写死 "2026-09-11" 的日期假红）
scrollH 1920/1280/375           → 1216 / 1930 / 2505
```

### M-1 取数层加 `range_`（零影响自选股）

`_fetch_yahoo_watch(symbol, range_="2y")` / `fetch_watchlist(stocks, range_="2y")`，
`_one()` 内改 `_fetch_yahoo_watch(sym, range_)`。**默认值保持不变** → 自选股链路零影响。

⚠️ **plan「默认值不变 → 不应有任何失败」这个假设不成立**（详见 §2.2）：`tests/test_phase24.py`
有 4 个**单参 lambda 桩**，加第二参后必然 `TypeError`。已按「生产代码正确、桩跟随」处理，
**未删除任何断言**，并新增 `test_range_passthrough` 作为 R2 护栏（断言 `seen == ["2y", "5y"]`，
将来若有人把默认值直接改成 5y，这条会红）。

### M-2 `/api/macro` 扩到 5 年

```
trend.dates = 1258（目标 ≈1260）
冷启动 2.16s（含 4 标的真实 5y 取数） / 热缓存 0.02s
各序列 raw：dx-y.nyb 1257 点、^tnx 1254、cl=f 1257、gc=f 1257
```

**首页回归**（改完 M-2 立刻测）：`FAILED 4`（与基线逐条相同）、`scrollH 1216/1930/2505` **完全一致**
→ 扩到 5Y **未波及首页**：`app.js:815-824` 已有「按当前窗口起点裁剪 macro 深度序列」的逻辑
（`if (windowStart && d < windowStart) return`），400 → 1260 点对首页无影响。

### M-3 三个纯函数（web/app.py）

| 函数 | 说明 |
|---|---|
| `_compute_macro_regime(indices, records, trend)` | 四维度 -2~+2 → 总分 → =总分/8 → `{level, score, score100, normalized, factors, basis}` |
| `compute_macro_correlation(trend, window=252)` | 1 年滚动窗口 → 固定 6 对 `{a,b,pair,r,n}`；`r=None` 表示样本不足/零方差 |
| `_macro_history_regime(records, days=30)` | 逐日回放（复用 `_compute_risk_appetite`）→ `{risk_on, neutral, risk_off, days}` |

`_load_macro()` 把三者与 `stocks`/`trend` **合并成一份响应**（避免前端多次取数、防口径漂移）；
全程内存计算，零落盘。

**真实数据实测**（`/api/macro`）：

```
regime: risk_on  score=3  score100=68.8  normalized=0.375
   风险偏好 VIX 15.84 平静 → +2 ｜ 美元 -0.47% → 0 ｜ 利率 +0.213pp → -1 ｜ 商品 +12.83% → +2
correlation: 美元↔黄金 -0.37 ｜ 美元↔原油 +0.24 ｜ 美元↔10Y +0.38
             黄金↔原油 -0.14 ｜ 黄金↔10Y -0.18 ｜ 原油↔10Y +0.47    (n ≈ 250)
history_regime: risk_on 20 / neutral 6 / risk_off 0  (days=30)
```

> 自洽性抽查：实测 `normalized=0.375 → score100=68.8`，与 plan §3.1 的验算示例（`0.36 → 68`）一致。

**测试**：`tests/test_web.py` 新增 22 条（含 `.git` 无关的纯函数边界：分档 / 零方差 / 样本不足 /
常量序列 / 缺维度 / 计分公式），全量 **618 passed**。

### M-4 抽顶栏 / 侧栏（**本任务最高风险步**，已通过）

**做法（与 plan 略有差异，见 §2.1）**：抽成**两个** include —— `_topbar.html` + `_sidebar.html`，
`index.html` 内改为 `{% include %}`；`index.html` 改动范围与 plan 完全一致（仅原来的 27~67 行）。
`/` 路由渲染时传 `base_prefix=""`、`active_page="dashboard"`。

**⚠️ 失败断言原文 + 实测值（按纪律留痕，本次未触发回滚）**：

```
FAIL  F-5 nav=10 项（7 真实+3 占位）且 data-target 全命中
      actual={'navCount': 10, 'navDisabled': 2, 'navBad': ['宏观数据'], …}
```

即：只有 F-5 一条因**本次有意变更**而红（`navDisabled` 3→2 + 新增跨页链接被判为「坏项」），
**其余全部断言（含玻璃判据、侧栏透明/层级、navLabel、布局三件套、图表、双主题、抽屉）全绿**
→ 说明 include 拆分后**渲染结果未变**，方案可行、**不需要回滚**。

**F-5 的根因不在 include，而在断言本身编码了旧产品决定**：
其 `navBad` 规则是「无 `data-target` 且非 `is-disabled` → 判为坏」—— 这条规则写在
「所有非锚点导航项都是占位」的年代；现在「宏观数据」是**合法的跨页链接**。
故按新意图同步断言（**不是放宽，而是补强**）：

- `FIDELITY_JS` 的 `navBad` 增加「`href` 以 `/` 开头 = 跨页路由链接 → 合规」分支，并回传 `macroHref`；
- F-5 改为 `navCount==10 && navDisabled==2 && !navBad && macroHref=="/macro"`，
  判据文字同步为「7 锚点 + 1 跨页 /macro + 2 占位」。

**复验结果**：

```
PASS  F-5 nav=10（7 锚点 + 1 跨页 /macro + 2 占位）且 data-target/href 全命中
FAILED: 4   ← 只剩既有 4 条日期假红（与本任务无关）
```

### M-5 `/macro` 路由 + `macro.html`

- 新增路由（`base_prefix="/"` → 侧栏锚点变 `/#overview` 回首页；`active_page="macro"` → 高亮「宏观数据」）；
- `macro.html` 七个模块骨架（hooks: `#mac-regime` / `#mac-market` / `#mac-vars` / `#mac-factors` /
  `#mac-relation` / `#mac-history` / `#mac-econ`）+ 复用 `_topbar.html` / `_sidebar.html`；
- `_asset_version()` 改为读 `_ASSET_FILES = ("style.css", "app.js", "macro.js")`（**不存在的文件自动跳过**，
  否则新增 macro.js 之前会把整个版本号打成 "0"）。新增前端文件必须加进这个元组，否则改它不换 URL。

### M-6 `macro.js`（主图 + 7 模块渲染）

- 主图：单 canvas + 品种胶囊（5）+ 时间范围胶囊（5）；`maintainAspectRatio:false` + 容器
  `height: clamp(340px,46vh,560px)`；**无任何 `!important` 覆盖 canvas 尺寸**（C2）。
- **`toYieldDisplay(v)`（显示层单一函数，plan 要求的三条附加项全部满足）**：
  `|v| > 20` 才 ÷10；越界时 `console.warn` **一次**（不静默）；单测/断言锁定当前口径
  （`4.985 → 4.979%` 实测，见 MX-6）；**相关性不动**（Pearson 尺度不变，不必进数据层）。
- 多变量「全部对比」→ 起点归一化 100（`v / 首个非空 * 100`，数据变换而非坐标轴 min）；
  单变量 → **真实价**（10Y 走 `toYieldDisplay`）。
- 模块渲染全部**只消费服务端结果**：`regime`（四维度）/ `correlation` / `history_regime` / `econ`
  的 `quadrant` —— 前端零重算（§4.4 职责边界）。
- Shell 行为（主题 / 移动端抽屉 / 市场状态 + 顶栏数据日）**刻意复制**自 app.js（约 35 行）：
  首页刚做完 shell 抽取，不在同一任务再动它；文件头已注明「出现第三处复用应抽 `shell.js`」。

### M-7 样式（research terminal）

`style.css` 追加约 128 行 `.mac-*` 段：大留白 / 细边框 1px / 极浅背景（**刻意不用首页玻璃 token**）/
状态色只落在文字、细边框与细条形上（**严禁堆彩色卡片**）；主图容器比首页主图更高（视觉中心）。
断点对齐既有：≤1299 两列区合流、≤768 数字网格 2 列、≤480 单列。状态类 `.up/.down/.flat` 限定在
`.mac` 作用域内，避免与既有类名相撞。

### M-8 验收（`verify_ui.py` 扩展 `assert_macro_page`，MX-1~MX-15，**全部 PASS**）

```
MX-1  /macro 200
level='Risk-On 风险偏好上行' quadrant='四象限：再通胀（通胀↑ · 增长↑）' score='68.8' factors=4
canvas=1354x496  css=1354x496  wrapH=497          ← C2：位图 == 显示尺寸
pills=[美元指数,10Y 美债,原油,黄金,全部对比] active=美元指数  ranges=[1M..5Y] pts=252
tenYear='4.979%'                                  ← 口径正确（不是 42.5%，也不是 0.4985%）
rel=6(strong=0, n/a=0)  hist=3  econAsOf='数据月份：2026年8月'
MX-7 多变量 4 条线起点全为 100 ｜ MX-8 5Y > 1000 点 ｜ MX-13 主题切换后图表存活
MX-14 375 档无横向溢出 + 两列区降为单列
MX-12 /api/econ 断供（page.route abort）→ 页面仍 200、7 模块在位、模块 6/7 显示「数据暂缺」
MX-15 console error = 0
```

整轮 `verify_ui`：**`FAILED: 4`**（只剩既有 4 条日期假红），截图 3 张
（`shot-macro-1920/‑dark/‑375.png`）。目视：Light/Dark 两套都克制、无彩色卡片堆叠、
状态色只出现在文字与细条形；主图为视觉中心。

> 一处设计选择（记明）：宏观关系**固定列 6 对**，只对 `|r| ≥ 0.5` 加高亮（本次实测 strong=0 —— 
> 当天 6 对都在 ±0.47 以内）。若改成"无显著对就整卡不渲染"，卡片会看起来像坏了；
> 列全部 + 高亮显著 + null 显示「样本不足」信息更完整，也满足验收（不显示错误的 0）。

### M-9 记录

本文件 + `docs/architecture.md` 决策行 + `docs/pitfalls.md` 3 条（见下）。

---

## 2. 与 plan 的差异（4 处，均已核对）

### 2.1 「一个 `_shell.html`」→ 两个 include（`_topbar.html` / `_sidebar.html`）

plan §6 M-4 写的是单文件 `_shell.html`（含 topbar + sidebar）。**单文件无法保持 DOM 不变**：
`.shell` 是网格容器，侧栏必须是它的**子元素**，而顶栏必须在它**外面** ——
一个 include 同时包含两者只能出现「跨文件未闭合标签」（`.shell` 开在 include 里、闭在页面里），
既脆弱又会被任何格式化工具打断。故拆成两个 include，index.html 的改动范围与 plan 一致，
DOM 逐字节保持。**意图（shell 单一来源）不变。**

### 2.2 `tests/test_phase24.py` 的桩必须同步（plan 假设不成立）

详见 §1 M-1。已改 4 个 lambda 桩为 `lambda s, *a:`、`def bad(s)` → `def bad(s, *a)`；
断言一条未删。plan 已把教训写入（「改签名前先 grep 所有 `monkeypatch.setattr` 的 lambda 桩」）。

### 2.3 `_MACRO_TTL` 90s → **300s**（而非建议的 600s）

- 值得提：数据量 ×3（400 → 1258 点），90s 下隔 90 秒就吃一次 ~2.2s 冷启动。
- **为什么不是 600s**：本端点**同时供首页 4 张宏观卡**（美元/10Y/原油/黄金都是**盘中交易**品种），
  首页「刷新数据」按钮也走它 → TTL 过长会让手动刷新拿不到新价。
  ⚠️ 另外更正一处前提：plan 说「宏观报价是日频数据」—— 这不适用于这 4 个品种（日频的是 BLS 经济数据）。
- 取 **300s** 折中；若将来宏观页独立取数（不复用首页链路），可再放宽。改一行常量即可。

### 2.4 `tail` 参数**不改**（保持 1260 = 5Y 全量）—— 附实测体积

需求方问「tail 参数改不改（不改就记进 journal）」。**实测后决定：不改**，理由与数据如下：

| 项 | 实测 |
|---|---|
| `/api/macro` 全量响应体 | **209,896 B ≈ 205 KB**（其中 `trend` 占 208,529 B = **99.3%**） |
| 分段 | `stocks` 301 B / `regime` 503 B / `correlation` 435 B / `history_regime` 56 B |
| 若改成 `tail=400` | `trend` ≈ 65,909 B（省 ~142 KB） |

**为什么不改**：
1. `tail` 直接决定「时间范围 1M/3M/6M/1Y/5Y 全有数据」这条验收判据 —— 砍到 400 点后 1Y/5Y 档就没数据了。
2. 205 KB 在 **TTL=300s** 下每次页面加载只付一次；首页侧已实测零回归（§1 M-2）。
3. 真正的优化空间不在 tail 而在**压缩**：加一行 `GZipMiddleware` 可把这类数值数组压到 ~1/5。
   **但那是全局中间件改动（影响所有端点），超出本计划范围 → 本次不做**，作为可选后续记在此处。

---

## 3. 实测发现（5 条，均已随 plan 更正）

| # | 发现 | 性质 |
|---|---|---|
| 1 | **`^TNX` 不是「收益率 ×10」**：实测 raw = `4.975`（5 年前 `1.277`，对应 2021-09 的 ~1.3% 历史事实）→ Yahoo 返回的就是百分数。按原 plan ÷10 会显示 **0.4975%**，正好制造出它禁止的错误 | plan 错（已更正）；方案：显示层量级自适应 `\|v\|>20` 才 ÷10 + `log.warning` + 单测锁口径 |
| 2 | **M-1「pytest 全绿」假设不成立**（单参 lambda 桩） | plan 假设错（已更正） |
| 3 | **相关性对用展示符号查 `trend.series` → 6 对全 `None`**：`trend.series[].key` 是 `sym.lower()`，`"DX-Y.NYB"`/`"^TNX"` 查不到 → 页面表现为「永远样本不足」，不报错不崩。**违反项目既有小写键纪律**（`_HISTORY_KEYS = frozenset(s.lower() …)`） | **执行者抓到的真 bug**，已修（查表前转小写） |
| 4 | **利率维度必须用百分点**：`4.00→4.30` 用百分比变化得 +7.5%，与 `(0.10, 0.25)` 阈值量纲不符 → 任何变动都顶格 | **执行者抓到**，已新增 `_chg_abs` |
| 5 | **`/api/macro` 冷启动 2.16s** 略超 plan 的「<2s」 | 如实记录；热缓存 0.02s、前端超时 12s，功能无碍 |

**测试自身也踩到一个值得记的坑**：用「恒定收益率」构造序列去测相关性会得到 `r≈-0.01` 而非 ±1 ——
**恒定收益率 = 零方差（浮点噪声）**，Pearson 退化成 0/0 噪声，那是"零方差"不是"完全相关"。
测相关性必须用**有波动**的收益率（已改为 `_price_from_returns([±r...])` 构造）。

---

## 4. 交付物清单与验收对照

| 类型 | 文件 | 状态 |
|---|---|---|
| 新建 | `web/templates/_topbar.html`、`_sidebar.html`（shell 共用） | ✅ |
| 新建 | `web/templates/macro.html`（7 模块） | ✅ |
| 新建 | `web/static/macro.js`（主图 + 渲染 + shell 行为） | ✅（`node --check` 通过） |
| 修改 | `web/app.py`（3 纯函数 + `/macro` + macro 端点 5Y + `_asset_version`） | ✅ |
| 修改 | `web/templates/index.html`（改 include；「宏观数据」改可点） | ✅ |
| 修改 | `web/static/style.css`（`.mac-*` 段 128 行） | ✅ |
| 修改 | `src/fetcher.py`（`range_` 参数化） | ✅ |
| 修改 | `tests/test_web.py`（+22 宏观纯函数/端点 + 2 路由）、`tests/test_phase24.py`（桩签名同步 + 1 新护栏） | ✅ |
| 修改 | `verify_ui.py`（F-5 同步 + `assert_macro_page` MX-1~MX-15） | ✅ |

**验收判据逐条**（plan §7.2 / 需求方清单）：见 §1 M-8 的 MX-* 全绿结果；护栏与回归：
`verify_ui FAILED: 4`（仅既有日期假红）、`pytest 620 passed`、零新增落盘文件（`git status` 复核）。
