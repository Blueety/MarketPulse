# 实施计划：中国宏观数据独立页 `/macro/cn`

> **需求来源**：2026-09-14 会话 + 选型确认（本任务无 `prd.md`，Goal 取自该确认）
> **产出**：架构师只读分析后出具；**未改动任何项目文件**
> **前置**：数据源已完成 **3 轮实测**（31 个候选接口），结论见 §3 —— **本方案的全部指标均有实测依据**
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 任务目标

**Goal（源自 2026-09-14 选型确认）**：
> 现有 `/macro` 是全球（实为美国）宏观页，**新增一个中国宏观数据独立页 `/macro/cn`**，与 `/macro` 平行。

已确认的四项选型：

| 项 | 决定 |
|---|---|
| 页面形态 | **独立新页 `/macro/cn`**，复用 `_topbar.html` / `_sidebar.html` + `.shell` |
| 指标范围 | **全指标**：通胀+增长 / 流动性 / 利率 / 就业+消费+地产（共 13 个统计序列） |
| 四象限 | **做**，增长轴用**真 PMI**（50 荣枯线），季度 GDP 作交叉校验 |
| 行情 | **并入**：上证/深证/创业板 + 人民币汇率 + 10Y 中国国债 |

**本方案相对会话初版的两处纠正**（实测推翻了先验假设，见 §3.4）：

1. 「70 城房价」**不成立** —— `macro_china_new_house_price` 实测只覆盖 **北京、上海 2 城**（非 70 城）→ 文案与聚合规则都要改。
2. 美国版四象限因缺 PMI 用「就业替代」；**中国版有真 PMI，但口径必须改**：PMI 是扩散指数，增长轴取**水平**（与 50 比较）而非**同比方向** —— 不可照抄美国版的 `_growth_axis`。

---

## 2. 结论先行与架构选型

**选定：新建 `src/cn_econ_fetcher.py`（与 `src/econ_fetcher.py` 平行）+ 2 个新端点 + 1 个新页面。**

| 决策点 | 选择 | 理由 |
|---|---|---|
| 数据模块 | **新建 `src/cn_econ_fetcher.py`**，不改 `econ_fetcher.py` | 两者数据源（BLS vs AkShare）、序列数（4 vs 13）、TTL、失败语义都不同；塞进一个模块会让"只缓存成功"等纪律互相污染 |
| 四象限常量 | 把 `econ_fetcher._QUADRANTS` **提升为公开 `QUADRANTS`** 并 import 复用 | 四象限是同一套语义（reflation/goldilocks/stagflation/deflation），复制一份必然漂移；仅 1 行改动 + 同步引用处 |
| 页面模板 | **新建 `macro_cn.html`**，复用 `.mac-*` CSS 类 | `.mac-*` 已是 research terminal 风格；复用类 = 两页视觉天然一致 + 零样式重复。**只新增必要的少量 `.cn-*` 规则** |
| 侧栏入口 | **新增同级项**「中国宏观」，不做二级菜单 | 二级菜单要改 `.nav` 结构与 F-5 断言形状（风险大）；同级项只让 `navCount 10→11`，改动最小且语义清晰 |
| 取数并发 | `ThreadPoolExecutor(max_workers=6)` + 整体限时 | 13 个接口**串行实测合计 ≈ 24s**，超过项目任何预算（`US_SECTOR_TIMEOUT=20`）→ 必须并发；见 R1 降级路径 |
| 端点拆分 | 先做**单端点** `/api/econ/cn`；若并发实测仍 >10s 则改**分组端点** | 单端点对前端最简单；分组是明确的降级路径（见 R1） |

---

## 3. 数据源实测（本方案的事实依据）

### 3.1 ✅ 统计指标 —— 全部可用且新鲜（13 个序列）

| key | AkShare 接口 | 耗时 | 最新数据 | 取值列 | 分组 |
|---|---|---|---|---|---|
| `cpi` | `macro_china_cpi` | 0.89s | **2026-08**（同比 0.8 / 环比 0.4） | `月份` / `全国-同比增长` / `全国-当月` | price |
| `ppi` | `macro_china_ppi` | 1.01s | **2026-08**（同比 3.8） | `月份` / `当月同比增长` / `当月` | price |
| `pmi` | `macro_china_pmi` | 1.12s | **2026-08**（制造 49.8 / 非制造 49.0） | `月份` / `制造业-指数` / `非制造业-指数` | growth |
| `gdp` | `macro_china_gdp` | 0.81s | **2026 Q1-2**（同比 4.7） | `季度` / `国内生产总值-同比增长` | growth |
| `m2` | `macro_china_money_supply` | 0.94s | **2026-08**（M2 356.8 万亿 / 同比 7.5） | `月份` / `货币和准货币(M2)-数量(亿元)` / `-同比增长` / `货币(M1)-同比增长` / `流通中的现金(M0)-同比增长` | money |
| `social_financing` | `macro_china_bank_financing` | 0.96s | **2026-08**（3314） | `日期` / `最新值` / `涨跌幅` | money |
| `credit` | `macro_china_new_financial_credit` | 1.06s | **2026-08** | `月份` / `累计-同比增长`（主）/ `当月-同比增长` | money |
| `unemployment` | `macro_china_urban_unemployment` | 0.88s | **2026-07**（调查失业率 5.2） | 长表 `date`/`item`/`value`，**item 有 4 种**，取 `全国城镇调查失业率` | labor |
| `retail` | `macro_china_consumer_goods_retail` | 0.94s | **2026-07**（同比 0.6） | `月份` / `同比增长` / `累计-同比增长` | labor |
| `house_price` | `macro_china_new_house_price` | 1.17s | **2026-07** | `日期` / `城市`（**仅 2 城**）/ `新建商品住宅价格指数-同比` / `二手住宅价格指数-同比` | estate |
| `lpr` | `macro_china_lpr` | 5.54s | **2026-08-20**（1Y 3.00 / 5Y 3.50） | `TRADE_DATE` / `LPR1Y` / `LPR5Y` | rate |
| `shibor` | `macro_china_shibor_all` | 2.15s | **2026-09-11**（日频） | `日期` / `O/N-定价` / `1W-定价` / `1M-定价` | rate |
| `bond_10y` | `bond_china_yield(start=6m)` | 7.49s | **2026-09-14** | `曲线名称` / `日期` / `10年`（含 3月~30年 全期限） | rate |

**`bond_china_yield` 的额外收益**：一次请求返回 **3 条曲线** —— `中债国债收益率曲线` / `中债商业银行普通债收益率曲线(AAA)` / `中债中短期票据收益率曲线(AAA)`。
→ **顺带拿到信用利差**（国债 vs 商金债同期限）：这正是美国版因 FRED 不通而**被迫用"波动率/美元/利率/商品"替代信用维度**的那个缺口（见 `econ_fetcher.py` 第 18-19 行注释）。**中国版可以把这个维度补回来。**

### 3.2 ❌ 否决清单 —— 「东财报告族」（列名 `商品/日期/今值/预测值/前值`）

| 接口 | 耗时 | 最新数据 |
|---|---|---|
| `macro_china_pmi_yearly` | 10.5s | 2025-08-31 |
| `macro_china_non_man_pmi` | 11.8s | 2025-08-31 |
| `macro_china_cx_pmi_yearly` | 8.5s | 2025-09-01 |
| `macro_china_industrial_production_yoy` | 15.7s | 2025-09-15（今值 nan） |
| `macro_china_m2_yearly` | 18.5s | 2025-09-12（今值 nan） |
| `macro_china_gdp_yearly` | 5.5s | 2025-07-15 |
| `macro_china_fx_reserves_yearly` | 9.0s | 2025-09-07 |
| `macro_china_trade_balance` / `exports_yoy` / `ppi_yearly` / `retail_price_index` | **>20s** | 超预算 |

### 3.3 ★ 选源规律（可复用，写进 `pitfalls.md`）

> **列名就是停更指纹**：`商品/日期/今值/预测值/前值` → 东财报告族，**停更在 2025-09 且耗时 5~20s+，一律否决**；
> 中文语义列（`月份/全国-…`、`季度/…`、`TRADE_DATE/…`） → 统计局/央行族，**<1.2s 且新鲜到 2026-08**。

这与项目既有认知**完全吻合**（`macro_usa_*` 同族同为 2025-09 停更 + 9.5~28s）—— 说明是同一上游问题，不是偶发。**因此中国页不需要接任何一个被否决接口。**

### 3.4 ⚠️ 两个纠正性发现（推翻先验假设）

| # | 先验假设 | 实测事实 | 影响 |
|---|---|---|---|
| **C1** | `macro_china_new_house_price` = 「70 城房价指数」 | **只有 2 城：北京、上海**（`城市_n = 2`，374 行 = 2 城 × 187 月，2011-01 ~ 2026-07） | 文案必须写「北京 · 上海」，**不能写「70 城」**；**不需要城市聚合**（只有 2 城），但需要一个"北上并列"的双序列展示 |
| **C2** | 增长轴照搬美国版（同比方向） | **PMI 是扩散指数**：49.8 与 `50` 比较才是荣枯；而它的 `制造业-同比增长` = +0.81%（方向 up）—— 两个读数结论相反 | 增长轴取 **水平**（PMI vs 50），**不取同比方向**。必须写进 `basis` 与前端标注 |

### 3.5 ⚠️ 数据质量告警（不得静默消费）

| 序列 | 现象 | 处置 |
|---|---|---|
| `credit` | 2026-08「当月」= 552、**2026-07「当月」= -5896（负值）**、同比 -91.2% | **主用 `累计-同比增长`**（-20.9%，方向可读）；`当月` 降级为参考或不出图；`basis` 标注口径 |
| `retail` | 2026-07 同比 0.6%（偏低） | 同时输出 `累计-同比增长`（1.2%）供对照；不做合理性断言 |
| `bond_10y` | **1 年窗口返回 0 行**（`bond_china_yield_1y` 实测 rows=0） | 固定用 **6 个月窗口** + 空结果守卫（见 R2） |

### 3.6 ✅ 行情类

| 标的 | 链路 | 实测 |
|---|---|---|
| 上证 / 深证 / 创业板 | **复用 `/api/history`**（SQLite `data/marketpulse.db` 已有 `sh`/`sz`/`cyb`） | 现网可用，无需新增端点 |
| 人民币汇率 | `_fetch_yahoo_watch("CNY=X", "3mo")` | ✅ 返回 `(6.6983, [(date, value)…])`，日线完整 |
| 10Y 中国国债 | `bond_china_yield(start, end)` → `中债国债收益率曲线` 的 `10年` 列 | ✅ 2026-09-14 有值 |
| 信用利差（bonus） | 同上，`商业银行普通债 AAA` − `国债` 同期限 | ✅ 同一次请求免费获得 |
| ~~`CNH=X`~~ | — | ❌ 只返回 **1 个点**（6.7098），**不可作趋势** → 选 `CNY=X` |

---

## 4. 要改的文件列表

### 新增

| 文件 | 说明 |
|---|---|
| `src/cn_econ_fetcher.py` | 中国宏观取数 + 解析 + 派生（13 序列 + 四象限），零写盘 |
| `web/templates/macro_cn.html` | 中国宏观页（复用 `_topbar` / `_sidebar` / `.mac-*`） |
| `web/static/macro_cn.js` | 新页交互（主题同口径、图表、模块渲染） |
| `tests/test_cn_econ.py` | 取数/解析/四象限/失败降级的单测 |
| `scripts/probe_cn_macro.py` | **数据源探针固化**（13 可行 + 8 否决的实测回归；见 R7） |
| `tasks/2026-09-14-cn-macro-page/journal.md` | 执行者收尾填写 |

### 修改

| 文件 | 改动 |
|---|---|
| `src/econ_fetcher.py` | `_QUADRANTS` → 公开 `QUADRANTS`（1 行 + 引用同步） |
| `web/app.py` | `_CN_ECON_TTL` / `_cn_econ_cache` / `GET /api/econ/cn` / `GET /api/cn/quotes` / `GET /macro/cn`；`_ASSET_FILES` 加 `macro_cn.js` |
| `web/templates/_sidebar.html` | 新增同级项「中国宏观」→ `href="/macro/cn"`，`active_page == 'macro-cn'` 高亮 |
| `web/static/style.css` | 追加 `.cn-*` 最小补充段（优先复用 `.mac-*`） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **F-5 断言补强**（`navCount 10→11` + `macroHrefs` 数组）+ 新增 `assert_macro_cn_page` |
| `tests/test_web.py` | 追加 `/macro/cn` / `/api/econ/cn` / `/api/cn/quotes` 用例 |
| `docs/architecture.md` | 新增 1 决策行（**append-only**） |
| `docs/pitfalls.md` | 追加：AkShare 列名停更指纹 / PMI 水平 vs 方向 / 房价仅 2 城 / `bond_china_yield` 区间敏感 |
| `docs/commands.md` | 追加探针与新端点的验证命令 |
| `docs/system-overview.md` | §2.4 路由表补 2 行；§11 规模统计更新 |
| `AGENTS.md` | 项目地图补 `src/cn_econ_fetcher.py` 与新页 |

---

## 5. 实现步骤

### Step 1 · `src/cn_econ_fetcher.py` — 常量表 + 解析纯函数

```text
# 伪代码
CN_ECON_SERIES = {
  "cpi":  {"group":"price", "label":"CPI", "unit":"%", "fn":"macro_china_cpi",
           "ym_col":"月份", "main_col":"全国-同比增长", "aux_col":"全国-当月"},
  ...
}
_CN_ECON_TIMEOUT = 25      # 整体限时（daemon 线程 + join，复用 fetch_sector_heat 范式）
_CN_ECON_WORKERS = 6       # 并发度
_CN_HISTORY_MONTHS = 36    # 输出给前端的 history 长度（月度 3 年）

def _parse_ym(raw) -> str | None      # "2026年08月份" → "2026-08"；"2026年第1-2季度" → "2026Q2"
def _require_cols(df, cols) -> bool   # 缺列守卫（复用 fetch_sector_heat 纪律，防 akshare 升级改列名）
```

**验证**：单测喂构造 DataFrame（不联网），断言 `_parse_ym("2026年08月份") == "2026-08"`、缺列返回 False。

### Step 2 · 逐序列 fetcher（AkShare 调用 + 解析）

```text
def _fetch_one(key) -> tuple[str, list[tuple[str, float]]]:
    # 1. akshare 函数名从 CN_ECON_SERIES[key]["fn"] 取，缺失 → 返回 [](不抛)
    # 2. _require_cols 缺列 → 返回 []
    # 3. 特殊分支（必须显式，不能"通用解析"糊过去）：
    #    - unemployment: 长表，过滤 item.strip() == "全国城镇调查失业率"
    #    - house_price : 按 城市 拆两条序列（北京/上海），非长表聚合
    #    - bond_10y    : 过滤 曲线名称 == "中债国债收益率曲线"，取 "10年" 列
    #    - credit      : 主用 "累计-同比增长"
    # 4. 排序升序统一（同 BLS 纪律：后续一律按时间取尾）
```

**验证**：13 个 key 逐个跑真实取数（一次脚本），打印 `sec` 与最新月份，与 §3.1 对照。

### Step 3 · 并发取数 `fetch_cn_econ_raw()`

```text
def fetch_cn_econ_raw() -> dict[key, list[tuple[str, float]]]:
    # ThreadPoolExecutor(max_workers=_CN_ECON_WORKERS) 提交 13 个任务
    # 每个任务内部 try/except → 失败返回该 key 的 []（不中断其余）
    # 整体用 daemon 线程 + join(_CN_ECON_TIMEOUT) 限时；超时 → 已完成的部分 + 未完成的 []
    # 返回 {key: rows}，**不抛异常**（调用方降级）
```

**验证**：`time` 实测总耗时。**判据：并发后总耗时 ≤ 8s（可接受）；>10s 则启用 R1 降级路径（分组端点）**。

### Step 4 · 派生 + 中国版四象限 `build_cn_econ_payload()`

```text
def build_cn_econ_payload(raw, failed_keys) -> dict:
    # series[]: key/group/label/unit/latest/date/yoy/prev_yoy/direction/history
    #   - yoy: 百分比口径序列直接取列值；指数口径序列（如 gdp 已是同比）直接用
    #   - 按月键找去年同月（BLS 教训：真实数据会缺月，禁止"取第 13 个"）
    # as_of = 各序列最新数据月份的最大值（月度口径；季度 GDP 用 2026Q2）
    # failed = failed_keys（前端逐模块显示「数据暂缺」）

    # 通胀轴：CPI 同比方向为主 + PPI 二次确认（同 _infl_axis 语义）
    # ★ 增长轴（中国版口径，**与美股版不同**）：
    #   pmi_3m = mean(最近 3 个月制造业 PMI)
    #   pmi_axis = "expanding" if pmi_3m >= 50 else "contracting"     # 50 是天然荣枯线，不是工程取值
    #   gdp_axis = direction(gdp 同比 最近 2 期)                       # 交叉校验
    #   conflict = (pmi_axis != gdp_axis)   → 如实上报，**不静默取一个**
    # 象限 = QUADRANTS[(inflation_axis, growth_axis)]
    # basis: 明确写出「增长轴用 PMI 与 50 比较（水平），非同比方向」「房价仅北上 2 城」
    #        「credit 主用累计同比」「as_of 为数据月份，存在发布滞后」
```

**验证**：单测断言 `growth_axis` 由 PMI 水平决定（构造 PMI=49.8 → contracting；50.1 → expanding，**且同比方向相反时仍以水平为准**）；`conflict` 字段正确上报。

### Step 5 · `econ_fetcher._QUADRANTS` → 公开 `QUADRANTS`

改 1 行定义名 + 同步该文件内 1 处引用（`build_econ_payload`）。**不改任何 BLS 逻辑**。
**验证**：`pytest tests/test_econ*.py tests/ -k econ` 全绿（既有断言零改动）。

### Step 6 · `web/app.py` — 2 个新端点

```text
_CN_ECON_TTL = 6 * 3600          # 月度数据；与 _ECON_TTL 同纪律
_cn_econ_cache = {"ts": 0.0, "payload": None}
_cn_econ_lock = threading.Lock()

@app.get("/api/econ/cn")   → 与 api_econ 同形状（TTL 命中直接返回）
@app.get("/api/cn/quotes") → CNY=X + 10Y 国债 + 信用利差（复用 _fetch_yahoo_watch）
```

**"只缓存成功"的细化（与 BLS 版的有意差异，必须写进注释）**：

| 版本 | 规则 | 理由 |
|---|---|---|
| BLS `/api/econ` | `if fresh.get("as_of")` 才缓存 | **1 个**上游请求；失败=全失败 |
| 中国 `/api/econ/cn` | **仅当 13 个 key 全部失败（`as_of` 为空）才不缓存**；部分成功照常缓存 | 13 个**独立**接口；"1 个失败就整份不缓存"会让每次请求都重打 13 个接口（用户等 25s）。失败明细走 `failed` 列表交给前端逐模块降级 |

> ⚠️ 这条差异**必须写进代码注释**，否则后人会以"与 BLS 不一致"为由"统一"掉它 → 变成每次都打满 13 个接口。

**验证**：连续调 3 次，第 2/3 次命中缓存（用 `monkeypatch` 计数 `fetch_cn_econ_raw` 调用次数）；断网 → 200 + 空结构 + `as_of=None`；部分失败 → 200 + `failed` 非空。

### Step 7 · `GET /macro/cn` 路由 + 模板

```python
@app.get("/macro/cn", response_class=HTMLResponse)
def macro_cn_page() -> HTMLResponse:
    template = _TEMPLATES.get_template("macro_cn.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="macro-cn"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp
```

`macro_cn.html` 结构（模块顺序，与全球页同构但指标不同）：

| 层级 | 模块 | 数据源 |
|---|---|---|
| 一级（`.mac-flat`） | 当前宏观环境（四象限 + 轴口径注释） | `/api/econ/cn` |
| 二级（`.mac-card-hero`） | 中国宏观市场（主图 + 品种胶囊 + 时间范围） | `/api/cn/quotes` + `/api/history` |
| 三级（`.mac-2col`） | 核心宏观变量 + 宏观因子 | `/api/econ/cn` |
| 四级（`.mac-2col`） | 利率与流动性 + 地产（北上双序列） | `/api/econ/cn` |
| 五级（弱化卡） | 经济数据明细（**必须显示数据月份**，不得写「最新/实时」） | `/api/econ/cn` |

**两处必须照抄的纪律**（各 1 处，且都要写注释"与 macro.html 同源，改一处必须改两处"）：
1. `<head>` 内**主题预应用脚本**（`<html data-theme="light">` 是默认值，脚本必须**显式应用存储到的值**）—— 否则 dark 用户进本页突然变白且**不报错**（pitfall：主题初始化分叉）。
2. 图表容器**必须显式给高度** + `maintainAspectRatio:false` + **禁止 `!important` 覆盖 canvas**（C2 三件套，缺一不可）。

**验证**：`curl -s localhost:<port>/macro/cn | head -40`；浏览器打开确认样式与 `/macro` 一致。

### Step 8 · `_sidebar.html` + `_ASSET_FILES`

```html
<a class="nav-item{% if active_page == 'macro' %} active{% endif %}" href="/macro">…宏观数据…</a>
<a class="nav-item{% if active_page == 'macro-cn' %} active{% endif %}" href="/macro/cn">…中国宏观…</a>
```

⚠️ **两条硬纪律**：
1. 新项**必须是 `<a href="/macro/cn">`，不得写 `data-target`**（页内锚点处理器找不到会静默失效，F-5 会判坏项）；也不得写 `href="#"`（会跳页顶）。
2. `web/app.py` 的 `_ASSET_FILES` **必须加 `"macro_cn.js"`** —— 否则改它不会换 `?v=` URL，验证时吃到旧副本（pitfall 明确警告，`macro-chart-crosshair` 那次踩过）。

**验证**：`grep -n "macro_cn.js" web/app.py`；`curl -s localhost:<port>/macro/cn | grep -o 'macro_cn.js?v=[0-9]*'`。

### Step 9 · `verify_ui.py` — **F-5 补强（不是删除）**

**现状**（`verify_ui.py:579`）：

```python
check(f["navCount"] == 10 and f["navDisabled"] == 2 and not f["navBad"]
      and f["macroHref"] == "/macro",
      "F-5 nav=10（7 锚点 + 1 跨页 /macro + 2 占位）且 data-target/href 全命中", f)
```

**新增侧栏项后本断言必红**。按 `pitfalls.md` 既定纪律判别：

| 判别 | 结论 |
|---|---|
| 是"方案不可行"吗 | **不是** —— include/渲染路径未变，只是产品决定变了（多了一个合法跨页链接） |
| 是"断言脆弱"吗 | **是** —— `navCount == 10` 把数量写死 |

→ **处置：补强断言**（禁止删除，也禁止放松判据）：

```text
# 1. 探针：macroHref（单值）→ macroHrefs（数组），收集所有 href 以 / 开头的项
#    ⚠️ 现状 `else if (href.charAt(0)==='/') { if (href==='/macro') macroHref = href; }`
#       只认 /macro —— 新链接会**静默不被任何断言覆盖**（比断言变红更危险）
# 2. 断言改为：navCount == 11 and navDisabled == 2 and not navBad
#              and sorted(macroHrefs) == sorted(["/macro", "/macro/cn"])
# 3. 新增 assert_macro_cn_page()：见 §7.4
```

**验证**：先跑一次确认 F-5 变红（**先红后绿**，证明断言在测东西），补强后转绿。

### Step 10 · 测试

新增 `tests/test_cn_econ.py`（不联网，mock DataFrame / mock akshare）：

| # | 用例 | 断言 |
|---|---|---|
| 1 | `_parse_ym` 三种格式 | `2026年08月份→2026-08`、`2026年第1-2季度→2026Q2`、非法→None |
| 2 | 缺列守卫 | 缺必需列 → 返回 `[]`，不抛 |
| 3 | `unemployment` 长表过滤 | 只取 `全国城镇调查失业率`（4 个 item 里选 1） |
| 4 | `house_price` 双城拆分 | 得到北京/上海两条序列，**不是 70 条** |
| 5 | `credit` 主列 | 取 `累计-同比增长`（非负值异常的 `当月`） |
| 6 | **增长轴取 PMI 水平** | PMI 49.8 → `contracting`；50.1 → `expanding`；**且同比方向与之相反时仍以水平为准** |
| 7 | `gdp` 交叉校验 | PMI 与 GDP 方向冲突 → `conflict == True`（不静默覆盖） |
| 8 | 同比按键找去年同月 | 构造缺月序列 → 返回 None 而非错月份基准 |
| 9 | 部分失败缓存 | 13 个里 3 个失败 → payload 仍被缓存 + `failed == 3 项` |
| 10 | 全失败不缓存 | `as_of` 为空 → 不写缓存 |
| 11 | `bond_10y` 空结果守卫 | 空 DataFrame → 该序列 `[]`，其余正常 |
| 12 | 零写盘 | 全程无文件写入（Web 只读边界） |

`tests/test_web.py` 追加：`/macro/cn` 返回 200 + 含 `#cn-econ`；`/api/econ/cn` 空态 200 不 500；`/api/cn/quotes` 失败降级 200。

### Step 11 · 数据源探针固化 `scripts/probe_cn_macro.py`

**动机**：本项目**最大的历史陷阱是数据源静默停更**（`macro_usa_*` 停更一年才被发现；`us_sector_heat` 静默降级）。13 个新接口 = 13 个新的停更风险点，必须有可重跑的探针。

```text
功能：逐个调用 §3.1 的 13 个接口 + §3.2 的 8 个否决接口，
      输出「可用性 / 最新数据月份 / 耗时 / 列名 / 行数」表 + 落 JSON；
      退出码非 0 若：任一**在册可用**接口变为不可用，或其最新月份落后 > 3 个月。
约束：单接口 daemon 线程限时；console 只打 ASCII（GBK 陷阱）；只读、零写盘。
```

**验证**：`venv/Scripts/python scripts/probe_cn_macro.py` → 13/13 可用、最新月份与 §3.1 一致、退出码 0。

### Step 12 · 文档回填

| 文件 | 动作 | 纪律 |
|---|---|---|
| `docs/architecture.md` | **新增**一行决策（append-only，**严禁**用旧文→新文整体替换） | 这是 26/31/33/34 期同类记录的惯例 |
| `docs/pitfalls.md` | 追加 §3.3 列名指纹 / §3.4 C1·C2 / §3.5 数据质量 / R2 区间敏感 / R5 缺列守卫 | 只写可复用规则 |
| `docs/system-overview.md` | §2.4 路由表 +2；§5 模块清单 +`cn_econ_fetcher.py`；§11 规模 | 与代码一致 |
| `docs/commands.md` | 追加探针命令 + 新端点 curl | — |
| `AGENTS.md` | 项目地图 + `src/cn_econ_fetcher.py` / `web/templates/macro_cn.html` / `web/static/macro_cn.js` / `scripts/probe_cn_macro.py` | — |

---

## 6. 验证命令

> 全部来自 `docs/commands.md`；命令在 venv 内执行。**验证一律串行**（pitfall：并行跑 pytest 与 Playwright 会互相制造假失败）。

### 6.1 数据层

```bash
venv/Scripts/python scripts/probe_cn_macro.py              # 数据源回归（13 可用 + 8 否决）
venv/Scripts/python -m pytest tests/test_cn_econ.py -v     # 新增单测（12 条）
```

### 6.2 端点层

```bash
venv/Scripts/python -m uvicorn web.app:app --port 8031     # ★ 必须换新端口
curl -s http://localhost:8031/api/econ/cn | head -c 1200
curl -s http://localhost:8031/api/cn/quotes | head -c 600
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8031/macro/cn
```

### 6.3 全量回归

```bash
venv/Scripts/python -m pytest tests/ -v                                     # 全量（27 文件 + 新增）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # ★ 改前端后必跑
```

`verify_ui.py` 期望：三视口全绿 + F-5 补强后转绿 + 新增 `assert_macro_cn_page` 绿 + `console error = 0`。

### 6.4 必跑说明

| 改动类型 | 必须运行 |
|---|---|
| 新增 `src/cn_econ_fetcher.py` | `probe_cn_macro.py` + `pytest tests/test_cn_econ.py` + `pytest tests/` |
| 新增端点 | `test_web.py` + 手动 curl（含空态） |
| 改 `web/templates` / `web/static` / `_sidebar.html` | **`verify_ui.py`（不可用 `curl 200` 代替）** |
| 改 `verify_ui.py` | 先跑一次确认变红 → 补强 → 再跑确认转绿 |

### 6.5 未运行的检查（必须标注）

- ❌ **未做**：Railway 线上验证（部署后 BLS/AkShare 双链路在容器内的可达性未知）
- ❌ **未做**：真实浏览器（非 headless）在 1500/1024 中间宽度的目视确认 —— 若 headless 通过但用户反馈截断，按 §7.3 复测

---

## 7. UI 专项（本页为新增页面，故为「验收路径」而非「bug 复现路径」）

### 7.1 验收复现路径（精确步骤）

```text
1. cd d:/AGENT/MarketPulse && venv/Scripts/python -m uvicorn web.app:app --port 8031
   ★ 必须用**新端口**（8031 而非 8000）：Jinja2 启动时把模板读入缓存，旧进程不反映改动；
     且 headless 对 /static/*.css 跨端口会命中陈旧副本 → "改了像没改"（pitfall 反复记录）
2. 打开 http://localhost:8031/macro         → 建立基线：记录各模块高度/列数/主图高度
3. 打开 http://localhost:8031/macro/cn      → 本任务新增页
4. 断言侧栏：出现「中国宏观」且为 active；「宏观数据」**不再** active
5. 逐模块核对（与步骤 2 的基线逐项比对，±2px）：
   当前宏观环境 / 中国宏观市场（主图）/ 核心宏观变量 / 宏观因子 / 利率与流动性 / 地产 / 经济数据
6. 执行「硬刷新」（Ctrl+F5）后再看一次 —— 排除启发式缓存
7. 切换主题（点侧栏 ☀️/🌙）→ 本页应即时跟随；刷新后保持（localStorage）
8. 从首页点进 /macro/cn → 主题必须与首页一致（不得突然变白，见 R9）
```

### 7.2 关键测量点（元素 / 属性 / 期望值）

**先测量基线**：`.mac` 的 `max-width: 1400px`（`style.css:696`）→ 1920 视口下 `.mac` 实宽 = 1400 − `.main` 水平 padding（20px + 28px）= **1352px**。

| 元素 | 属性 | 期望 |
|---|---|---|
| `#cn-chart-wrap` | `getComputedStyle().height` / `clientHeight` | 1920×1080: `clamp(340px,46vh,560px)` → 46vh=**496.8** → **496~497px**（≠340、≠560，证 clamp 中间档生效） |
| ↑ 同上 | 1280×720 | 46vh = 331.2 < 340 → **下限 340px 生效** |
| ↑ 同上 | 375×812 | `@media ≤768` 覆盖为 `clamp(360px,48vh,420px)` → 48vh=389.8 → **389~390px** |
| `#cn-chart`（canvas） | `canvas.width` vs `offsetWidth`；`height` vs `offsetHeight` | **相等**（DPR=1 时 `===`；DPR>1 时 `=== offset × DPR`）← **C2 护栏，本项目量化判据** |
| `document.scrollingElement` | `scrollWidth` vs `window.innerWidth` | **相等**（零横向溢出），三视口 + 1500 + 1024 全测 |
| `#sidebar .nav-item` | 数量 / `.is-disabled` 数量 | **11 / 2** |
| `.mac` | `getBoundingClientRect().width` | 1920: **≈1352**；1280: 1232−48=**≈1232**（受视口限制） |
| `.mac-card` | `paddingTop` / `paddingBottom` | 20px（≤480 档 16px） |
| `.mac-2col` | `gridTemplateColumns` 计算值 | 1920/1280: **两列各 ~667px**；≤768: **单列** |
| 各模块卡片 | `getBoundingClientRect().height` | **与 `/macro` 同名模块 ±2px**（复用 `.mac-*`，理应一致） |
| `#cn-econ` 子项 | `gridTemplateColumns` | 与 `/macro` 的 `#macro-econ` **一致**（不新增断点） |

**定位手段**：`tab.evaluate` 内读 `offsetTop/offsetHeight/clientHeight/getComputedStyle`；Chart.js 读数必须读 `chart.data.datasets[].data.length`（**`chart.data.labels` 恒为空** —— x 轴用 `type:'category'` + `options.scales.x.labels`，pitfall 已记录该假失败）。

### 7.3 box-sizing 说明（本页所有布局判断的前提）

| 项 | 事实 |
|---|---|
| 全局规则 | `web/static/style.css:79` → `* { margin: 0; padding: 0; box-sizing: border-box; }` —— **本页所有元素都是 border-box** |
| 对 `height` / `max-height` 的影响 | 声明的 `height`/`max-height` **包含 padding + border**（不额外叠加） |
| 对 `.mac-chart-wrap` 的影响 | `height: clamp(340px,46vh,560px)` 即**含**内边距框高；该元素无 padding/border → 等于内容高，Chart.js 依此定 canvas 位图 |
| 对 `.mac-card` 的影响 | 卡片**未声明** `height` → 其 `getBoundingClientRect().height` = 内容高 + `padding 20+20` + `border 1+1`。所以"卡片 249px"里含 42px 内边距 —— **比较两页同模块高度时必须同口径** |
| ⚠️ 本页新增 CSS 的三条禁区 | ① **禁止**给 canvas 加 `width`/`height` 的 `!important`（会破坏 canvas 位图 == 显示尺寸，C2 根因）；② **禁止**给图表容器以外的元素声明固定 `height`（border-box 下会与 padding 相加而溢出）；③ 若给并排列表设 `max-height`，**两侧必须同值** —— 只在一侧加约束 = 没加约束（pitfall：「并排卡片必须两侧都有高度约束」，`#news-body` 那次把整行从 195 顶到 232） |

### 7.4 多尺寸验收（≥ 两档 + 两个中间盲区）

| 视口 | 期望 |
|---|---|
| **1920×1080**（常规） | `.mac` 实宽 ≈1352 居中；主图容器 **496~497px**；canvas 位图 == 显示尺寸；`scrollWidth == innerWidth`；侧栏 nav=11；console error **0** |
| **1280×720**（小窗口） | 主图容器 **340px**（下限生效，非 389/496）；`.mac-2col` 两列各 ≥500px 且无截断；`scrollWidth == innerWidth` |
| 375×812 | 主图容器 **389~390px**；`.mac-card` padding 16px；`.mac-2col` 单列；**零横向溢出** |
| **1500×900**（★ 断点空档） | 必测 —— 本页无 1500–1919 专用断点，与首页 5 列档同类风险（pitfall：`verify_ui` 只测 1920/1280/375，**恰好全部避开** 1500–1919 与 769–1024 两个坏带）；断言所有数值/标签**不被省略号截断**（`scrollWidth > clientWidth + 1` 即失败） |
| **1024×768**（★ 中间盲区） | 侧栏仍内联（232px）→ `.mac` 可用宽 ≈ 1024−232−48 = **744px**；主图容器 46vh=353 → **353px**；确认无溢出、无截断 |

**多宽度扫描方式**（复用项目已有做法）：**载入一次页面 + 逐宽度 `page.set_viewport_size()`**（媒体查询即时重算，不重载页面，12 个宽度仅多 ~2.5s）。
**覆盖度护栏**：断言实际扫过的宽度数（防选择器/渲染变化后扫描**空跑并全绿**）。

### 7.5 新增 `assert_macro_cn_page()` 断言清单

| # | 断言 | 防的是 |
|---|---|---|
| 1 | `/macro/cn` 返回 200 且 `#cn-regime` / `#cn-chart-wrap` / `#cn-econ` 存在 | 页面未渲染 |
| 2 | `#cn-chart-wrap` 高度落在 §7.2 期望区间（**按视口门控**，不写死数值） | 容器无高度 → 图塌 0（C2） |
| 3 | `canvas.width === canvas.offsetWidth && canvas.height === canvas.offsetHeight` | C2 回归 |
| 4 | 四象限区显示 `data-quadrant` 与口径注释（含「PMI 与 50 比较」） | 口径被误写成"同比方向"（C2 纠正项） |
| 5 | 房价模块文案含「北京」「上海」且**不含「70 城」** | C1 纠正项回归 |
| 6 | `#cn-econ` 显示**数据月份**（形如 `2026年8月`）且不含「最新/实时」 | as_of 口径纪律 |
| 7 | 侧栏「中国宏观」为 active、`nav-item` 总数 11 | F-5 联动 |
| 8 | 在 `add_init_script` 写入 `localStorage["mp-theme"]="dark"` 后加载，`data-theme === "dark"`；与首页同偏好**行为一致** | R9 主题分叉 |
| 9 | console error == 0 | 运行时异常 |

> ⚠️ 断言**不得写死日期/数值**（pitfall：`check("2026-09-11" in topbarDate)` 随数据日推进必红）。期望值一律从被断言的同源数据取（如 `/api/econ/cn` 的 `as_of`）。

---

## 8. 风险评估

| # | 风险 | 级别 | 说明与缓解 |
|---|---|---|---|
| **R1** | **13 接口并发总耗时未知**（串行合计 **≈24s**，超所有现有预算） | **高** | 并发后实测判据 **≤8s**。**降级路径（已备）**：改**分组端点** `/api/econ/cn?group=price\|money\|rate\|growth\|labor\|estate`，前端分组懒加载（先渲染骨架，逐组填充）。**必须在 Step 3 实测后决定，不可假设并发有效** |
| **R2** | `bond_china_yield` **区间参数敏感**（实测 6m→411 行、**1y→0 行**） | **高** | 固定 6 个月窗口 + 空结果守卫（该序列降级 `[]`，不影响其余）；`probe_cn_macro.py` 把"1y 返回 0 行"作为**已知行为**断言，防后人当 bug 改 |
| **R3** | **C1 文案错误**：写成「70 城房价」而实际只有北上 | **高** | 文案写「北京 · 上海」；`assert_macro_cn_page` 断言 #5 + 单测 #4 双钉 |
| **R4** | **C2 口径错误**：增长轴误用 PMI 同比方向 | **高** | 单测 #6 构造"水平与方向相反"的用例；`basis` 与前端标注；断言 #4 |
| **R5** | **AkShare 升级改列名** → 解析静默出错或抛异常 | **高** | `_require_cols` 缺列守卫（复用 `fetch_sector_heat` 纪律）+ 单测 #2；失败降级 `[]` 不中断其余 12 个 |
| **R6** | `credit` 当月口径异常（2026-07 = **-5896**） | **中** | 主用 `累计-同比增长`；前端标注口径；单测 #5 |
| **R7** | **数据源静默停更**（本项目最大历史陷阱） | **中** | `scripts/probe_cn_macro.py` 固化探针 + 退出码非 0 判据（落后 >3 个月） |
| **R8** | **F-5 断言变红**引发误判"方案不可行" | **中** | Step 9 已给判别表与补强方案；**先红后绿**流程；`macroHref→macroHrefs` 扩展（否则新链接**静默无断言覆盖**，比变红更危险） |
| **R9** | **主题初始化分叉**：`<html data-theme="light">` 默认值 + 只处理单一主题 → dark 用户进本页变白且**不报错** | **中** | head 内联脚本**原样照抄** `macro.html` 并注释"改一处必须改两处"；`macro_cn.js` 的 `applyTheme()` 同口径；断言 #8 用 `add_init_script` 预置 localStorage |
| **R10** | `_ASSET_FILES` **漏登记 `macro_cn.js`** | **中** | 改它不换 URL → 验证吃旧副本（pitfall 已记录同款）。Step 8 有 grep 验证 |
| **R11** | 14 个 AkShare 接口**无官方限额但可能限频** | **低** | TTL 6h 使日调用 ≤4 次；观察日志；探针脚本串行执行 |
| **R12** | Railway 容器内 AkShare 可达性未知 | **低** | 本地已实测可达；线上为取证缺口（§6.5） |
| **R13** | 房价"北上并列"双序列在 375 档挤爆 | **低** | 375 档改上下堆叠（复用 `.mac-econ` 的 480 断点单列模式）；§7.4 有断言 |

---

## 9. 影响文件范围

| 类型 | 文件 | 规模（估） |
|---|---|---|
| 新增 | `src/cn_econ_fetcher.py` | ~330 行 |
| 新增 | `web/templates/macro_cn.html` | ~150 行（结构复用 macro.html） |
| 新增 | `web/static/macro_cn.js` | ~450 行 |
| 新增 | `tests/test_cn_econ.py` | ~280 行（12 条） |
| 新增 | `scripts/probe_cn_macro.py` | ~160 行 |
| 新增 | `tasks/2026-09-14-cn-macro-page/journal.md` | — |
| 修改 | `src/econ_fetcher.py` | +1 / −1 行（`_QUADRANTS` → `QUADRANTS` + 引用同步） |
| 修改 | `web/app.py` | ~+90 行（2 端点 + 1 路由 + 缓存 + `_ASSET_FILES`） |
| 修改 | `web/templates/_sidebar.html` | +1 项（~3 行） |
| 修改 | `web/static/style.css` | +30~60 行（`.cn-*` 最小补充） |
| 修改 | `tasks/.../verify_ui.py` | ~+70 行（F-5 补强 + 新页断言） |
| 修改 | `tests/test_web.py` | ~+50 行 |
| 修改 | `docs/*.md` + `AGENTS.md` | 5 文件（decision/pitfalls/commands/system-overview/AGENTS） |
| 删除 | 无 | — |

**零改动**：`daily_report.py` / `snapshot_report.py` / `opening_analyzer.py` / `src/analyzer.py` / `src/reporter.py` / `src/storage.py` / `src/fetcher.py` / `web/templates/macro.html` / `web/static/macro.js` / `web/static/app.js`。

---

## 10. 不做什么

- **不接入** §3.2 的 8 个被否决接口（含全部外贸族）—— 外贸指标**本期不做**（无可用源）
- **不改** `/macro` 全球页的任何内容（除侧栏新增一项）—— 两页**平行**，不重构为"参数化一页两用"
- **不改** `econ_fetcher.py` 的 BLS 取数/派生逻辑（除 `_QUADRANTS` 公开化）
- **不改** `src/fetcher.py`（`CNY=X` 走既有 `_fetch_yahoo_watch`，**不改其默认参数** —— 该函数被自选股/宏观页共用，改默认值会静默影响另两条链路，pitfall 已记录）
- **不改** `.gitignore`、不加 Python 依赖（`akshare` 已在 `requirements.txt`）
- **不落盘**：不进 history、不写 `context/`、不改 `generate_context`（Web 零写盘边界）
- **不做** 中国版"风险偏好 / 宏观关系 / 历史环境"的完整复刻 —— 本页做「四象限 + 指标 + 行情」，`regime 打分`/`correlation` 是否复刻见确认清单
- **不做** 二级导航菜单重构

---

## 11. 确认清单

- [ ] 已确认 **Step 3 并发实测判据**（≤8s 走单端点；>10s 走分组端点降级）—— 这是本方案唯一的实施中分支点
- [ ] 已确认 **增长轴口径**：PMI 与 `50` 比较（**水平**），非同比方向（C2）
- [ ] 已确认 **房价文案**为「北京 · 上海」，不得写「70 城」（C1）
- [ ] 已确认 `credit` 主用**累计同比**口径，`当月` 降级（R6）
- [ ] 已确认侧栏采用**同级项**（navCount 10→11），配套补强 F-5 断言（不删除）
- [ ] 已确认 `_ASSET_FILES` 登记 `macro_cn.js`
- [ ] 已确认**本页是否复刻** `regime 打分`（风险偏好三态）/ `宏观关系`（相关性）/ `历史环境` 三模块 —— 本方案默认**不复刻**（中国版四象限已承担 regime 表达），若需要请指出
- [ ] 已确认 §7.4 的 5 个验收视口（含 **1500** 与 **1024** 两个中间盲区）
- [ ] 文件范围合理、无遗漏测试、无新依赖
- [ ] 人已审阅本计划

---

## 附 A：数据契约（`GET /api/econ/cn`）

```json
{
  "as_of": "2026-08",
  "fetched_at": "2026-09-14T23:10:00",
  "failed": [],
  "series": [
    {"key": "cpi", "group": "price", "label": "CPI", "unit": "%",
     "latest": 0.8, "date": "2026-08", "yoy": 0.8, "prev_yoy": 0.5,
     "direction": "up", "history": [["2026-07", 0.5], ["2026-08", 0.8]]}
  ],
  "groups": {"price": [], "growth": [], "money": [], "rate": [], "labor": [], "estate": []},
  "inflation_axis": "up",
  "growth_axis": "contracting",
  "quadrant": "stagflation",
  "quadrant_label": "滞胀",
  "growth_inputs": {
    "pmi_3m": 49.4, "pmi_axis": "contracting",
    "gdp_yoy": 4.7, "gdp_axis": "contracting", "conflict": false
  },
  "basis": {
    "inflation": "CPI 同比方向（PPI 同比二次确认）",
    "growth": "制造业 PMI 与 50 荣枯线比较（3 个月均值均值化；**水平口径，非同比方向**）",
    "crosscheck": "季度 GDP 同比方向作交叉校验",
    "price_note": "房价指数仅覆盖北京·上海（接口实际覆盖，非 70 城）",
    "credit_note": "新增信贷主用累计同比；当月口径存在异常值",
    "rate_note": "10Y 国债取自中债国债收益率曲线（6 个月窗口）",
    "asof_note": "as_of 为数据月份，宏观经济数据存在发布滞后"
  }
}
```

**`GET /api/cn/quotes`**：`{"cny": {...}, "bond10y": {...}, "credit_spread": {...}, "as_of": "..."}`，其中 `cny` 复用 `_fetch_yahoo_watch("CNY=X","3mo")` 的 `(value, [(date, value)])` 形状。

## 附 B：关键逻辑伪代码

```text
# ---- 中国版四象限（与美股版**唯一但关键**的差异在增长轴） ----
def _growth_axis_cn(pmi_vals, gdp_vals):
    pmi_3m = mean(pmi_vals[-3:])                          # 平滑单月噪声
    pmi_axis = "expanding" if pmi_3m >= 50 else "contracting"   # ★ 50 = 天然荣枯线
    gdp_axis = _direction(gdp_vals[-1], gdp_vals[-2])     # 交叉校验用方向
    return {"pmi_3m": pmi_3m, "pmi_axis": pmi_axis,
            "gdp_axis": gdp_axis,
            "conflict": bool(gdp_axis) and gdp_axis != pmi_axis}

# ---- 并发取数（限时 + 逐 key 容错） ----
def fetch_cn_econ_raw():
    out, failed = {}, []
    def one(k):
        try:    out[k] = _fetch_one(k)
        except: out[k] = []; failed.append(k)
    # ThreadPoolExecutor(_CN_ECON_WORKERS) 提交全部 13 个 → 整体 join(_CN_ECON_TIMEOUT)
    return out, failed

# ---- 缓存（与 BLS 版的有意差异，注释必须写明理由） ----
@app.get("/api/econ/cn")
def api_econ_cn():
    now = time.time()
    with _cn_econ_lock:
        c = _cn_econ_cache["payload"]
        if c is not None and (now - _cn_econ_cache["ts"]) < _CN_ECON_TTL:
            return c
    raw, failed = fetch_cn_econ_raw()
    fresh = build_cn_econ_payload(raw, failed)
    if fresh["as_of"]:        # ★ 仅"13 个全部失败"才不缓存（BLS 版是"1 个失败即不缓存"）
        with _cn_econ_lock:
            _cn_econ_cache.update(ts=time.time(), payload=fresh)
    return fresh
```
