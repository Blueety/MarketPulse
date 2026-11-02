# 调研：别人怎么做事「宏观事件 + 市场影响」这类页面

> 起因：用户要求"网上别人有什么别的方案，你去查一下"。
> 本文是**外部方案调研 + 本机可达性实测**，用于校正 `plan.md`。所有"实测"结论都标了实测条件。

---

## 0. 一句话结论

**主流做法不是"从新闻里发现事件"，而是"用官方发布日历预定事件、再叠加市场反应"。**

我们的原方案（Google News 检索 → 按篇数聚类）其实是**绕远路**：它在用"媒体报道量"去**反推**事件，
而议息、非农、CPI 这类事件的**日期是提前数周就官方公告的**——完全不需要反推。

顺带还有两条值得借鉴的：
1. **事件研究法（Event Study）** 是算"影响"的行业标准口径（不是点对点涨跌，而是**异常收益 AR/CAR**）；
2. **官方日历天然包含未来**（实测拿到 2027-07 的会议日）⇒ 时间线可以同时是**"回看" + "前瞻"**。

---

## 1. 业界三类做法

### 1.1 官方发布日历（免费、权威、结构化）

| 机构 | 提供什么 | 形态 |
|---|---|---|
| **BLS** | 非农（Employment Situation）、CPI、PPI 的发布时间 | 网页月历 + **iCalendar 订阅 `bls.gov/schedule/news_release/bls.ics`** |
| **BEA** | GDP、PCE 发布日程 | 网页日程页 |
| **美联储** | FOMC 会议日历（含是否有 SEP 经济预测） | 网页（`/monetarypolicy/fomccalendars.htm`） |
| **Census** | 零售销售（MARTS）等 | 网页日程 |

公开事实：非农固定在 **08:30 ET**，CPI/PPI/GDP/PCE/零售同为 08:30 ET，工业产出 09:15 ET。

### 1.2 商业 / 聚合 API

| 提供方 | 覆盖 | 事件元数据 | 价格 |
|---|---|---|---|
| **Trading Economics** | 196 国 | **importance 分档 + group 分类（interest rate / inflation / labour…）** | 免费档额度小；标准档 ~$149/月 |
| **FMP** | 全球日历 | calendar / previous / consensus；**单次查询宽度上限 3 个月** | 有免费档 |
| **Finnhub** | 经济日历 | 事件时段 + 实际/预期 | ~$50/月 |
| **EODHD** | 全球日历 | 日历 + 预期趋势 | 从 ~$19.99/月 |
| **Alpha Vantage** | 偏财报日历（EARNINGS_CALENDAR / IPO_CALENDAR） | — | 免费档 |
| **FRED** | 历史宏观序列（**不是事件日历**） | — | 免费 key |
| **sifting.io** | 美国事件 | **impact tier（low/medium/high）+ agency + event_id** | API key |

**OpenBB** 的价值在于把 `fmp / nasdaq / tradingeconomics` 三家统一成一个接口：
`obb.economy.calendar(start_date=…, importance="High", group="interest rate")` —— 换源不改代码。

⚠️ OpenBB 文档里有一条重要的**诚实提示**（值得我们抄进自己的口径）：

> "Do not rely on the economic calendar for real-time updates. Times posted are **scheduled by publishers and are estimates**
> which do not reflect the actual time data is released to the public."

### 1.3 事件研究法（Event Study）—— "影响"的标准算法

学术与业界算"事件影响"的通用做法（Fama 等人 1960 年代奠基）：

```
估计窗口（如 252 交易日）  →  用市场模型 / Fama-French 因子模型回归，建立"正常收益"基线
        ↓
事件窗口（如 [-5, +10] 交易日）
        ↓
AR  (异常收益) = 实际收益 − 模型预测的正常收益      ← 关键：扣掉"大盘本来就会涨跌"
CAR (累计异常收益) = AR 在窗口内累加
        ↓
显著性检验：t 检验 / Patell Z / Wilcoxon / 符号检验 → 判断"是否真的异常"
        ↓
AAR / CAAR：把同类事件（如所有非农日）聚合成平均效应
```

**开源实现**（都支持市场模型 + Fama-French 3/5 因子）：

| 项目 | 说明 |
|---|---|
| `eventstudies`（pip: `ffjr-eventstudies`） | Python，含 MarketModel / FamaFrench3/5 / Carhart |
| `easy-event-study`（pip: `easy_es`） | 只要 `(ticker, event_date)` 两列就能跑，自动取收益与因子 |
| R `eventstudies` 包 | 学术界常用 |
| Eventus / SAS | 商业与学术工具 |

**这对我们原方案的直接冲击**：原方案"事件后 +3 日 −1.37%"这种**点对点涨跌**说明不了是事件造成的——
那三天大盘本来也在跌。要能说"异常"，得用 AR/CAR。

---

## 2. 本机可达性实测（2026-09-18）

| 源 | 直连 | 代理 7890 | 结果 |
|---|---|---|---|
| **Fed FOMC 日历页** | ✅ 200（167 KB） | — | **可解析**：2025/2026/2027 年会议月份 + 日期（`27-28` / `17-18*`，`*` 疑为含 SEP） |
| **BEA 发布日程** | ✅ 200（75 KB） | — | 可达 |
| **BLS .ics** | ❌ **403** | ❌ **403** | 取不到（网站层拒绝，与项目里记的"BLS 间歇不可用"同源） |
| **BLS 年度日程页** | ❌ 403 | — | 同上 |
| — BLS **API** | ✅（项目生产在用） | — | `api.bls.gov/publicAPI/v2/timeseries/data/` 只给数据，**不给发布日期** |
| **smartcalendars.ai .ics** | ✅ 200（87 KB） | — | **185 个 VEVENT**，`text/calendar`，`REFRESH-INTERVAL:PT24H` |
| Google News RSS + 日期限定 | ✅ | — | 回溯 1 年（见 `plan.md` §2） |

### 2.1 第三方日历镜像的实际内容（实测）

`X-WR-CALDESC` 自述来源：**`Release dates from bls.gov, bea.gov, federalreserve.gov, and census.gov`**

覆盖（185 条）：`FOMC Meeting Day 1/2`（78）、`Retail`（22）、`PPI`（14）、`GDP`（12）、
`US CPI Release`（8）、`Fed Interest Rate Decision`（7）、`Consumer Price Index Release`（3）、`PCE`（2）、
`Employment Situation (Nonfarm Payrolls)`（1）…

字段：`DTSTART;VALUE=DATE`（**只有日期，无时刻**）、`SUMMARY`、`DESCRIPTION`（较详细）、`LOCATION`、
`CATEGORIES`、`STATUS`。**时间跨度到 2027-07**（含未来事件）。

⚠️ 两个数据质量瑕疵，直接抄会出事：
1. 部分条目带 **`[CANCELLED]`** 后缀（如 `Fed Interest Rate Decision [CANCELLED]`）—— 需判断是真取消还是镜像站的标注噪声；
2. `DTSTART` 是**纯日期**，想要"08:30 ET"必须从 `DESCRIPTION` 里二次解析，或按机构惯例硬编码（BLS/BEA 08:30 ET 是公开惯例）。

---

## 3. 与原方案的对比

| 维度 | 原方案（新闻检索） | 官方日历方案 | 结论 |
|---|---|---|---|
| 事件**发现**方式 | 从报道篇数**反推** | 官方**预定**的发布日程 | 官方更准 |
| 日期准确度 | 报道日 ≈ 事件日（可能差 1 天） | 精确到日（甚至时刻） | 官方更准 |
| **未来事件** | ❌ 不可能有（新闻还没发生） | ✅ 实测到 2027-07 | 官方能**前瞻** |
| 事件**重要性** | 篇数（有 100 条上限封顶） | 可自带 impact 分档（商业源） | 各有所长 |
| **叙事/市场解读** | ✅ 有（标题+导语） | ❌ 没有 | 新闻独有 |
| 覆盖范围 | 任意主题（含地缘、关税） | 只有例行发布的指标/会议 | 新闻更宽 |
| 噪声 | 高（赌博站、投顾广告） | 低 | 官方更干净 |
| 依赖 | 无 key | 无 key（Fed/BEA 直连；BLS 需绕） | 相当 |
| 历史回溯 | 1 年（实测） | Fed 页有往年年份；第三方 .ics 只给未来 | 新闻更适合回填历史 |

**⇒ 两者不是替代关系，是「骨架」与「血肉」的关系。**

---

## 4. 建议的架构（三源合流）

```
① 事件骨架  ← 官方日历（Fed 直连 + BEA 直连 + BLS 走镜像/备选）
       ├─ 过去：日期 + 事件名 + 机构 + 时刻
       └─ 未来：可提前列出的日程（这是新增能力）
                    ↓ 按 (日期 × 事件类型) 对齐
② 市场反应  ← db 日线（既有 268 行）
       ├─ 当日涨跌（GSPC/IXIC/SH）
       └─ 事件后 +1/3/5/10 交易日点对点（现有口径）
                    ↓ 可选升级
③ 叙事热度  ← Google News 检索（原方案保留）
       └─ 「当天市场在谈什么」+ 篇数热度
                    ↓ 二期可选
④ 严格口径  ← Event Study（AR / CAR + 显著性检验）
```

### 4.1 关于 BLS 403 的三个处置（需选一）

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（推荐先做）** | Fed + BEA 直连官方；BLS 侧走 smartcalendars 镜像，**标注"经由第三方镜像，原始来源 bls.gov"** | 依赖第三方可用性 |
| B | 生产环境（Railway 海外 IP）直连 BLS .ics，本机只在测试时跳过 | 本机开发环境测不到 |
| C | 接 sifting.io / FMP（有 key、有 impact 分档） | 引入 API key 与新依赖 |

> 说明：BLS **API** 虽然通，但它只返回**数据**（period 如 `2026-08`），
> 用它反推发布日期只能得到"通常次月中旬"这种近似值 —— **不如镜像站的精确日期**。

### 4.2 关于"影响"口径的升级（二期）

如果要让"影响"具备统计意义，需要引入 AR/CAR：
- 需要：市场基准序列（已有：GSPC）+ 可选因子数据（Fama-French，需额外下载）
- 门禁：项目当前**零新依赖**纪律 → 纯 Python 实现市场模型的 OLS（两参数回归）是可行的，
  但 Fama-French 因子要新增数据源（`pandas_datareader` 或直接下 CSV）→ **建议二期再评估**。

---

## 5. 我还额外发现的两点

1. **日历天然前瞻**：官方日历有未来日程（实测到 2027-07）⇒ 时间线可以做**双区**：
   「已发生」（带市场反应）+「即将到来」（带倒计时）。这比单纯回看更实用，
   而且"提醒我下周三有议息"这种需求，现有项目结构（Hermes 推送）已经具备。
2. **`importance` 分档是普遍设计**：Trading Economics、sifting.io、OpenBB 全都提供
   low/medium/high 影响分档。我们的"篇数热度"是自创口径，若接入 sifting.io/FMP 可直接用官方分档，
   **免得自己发明阈值**（与项目"不自己造阈值"的纪律一致）。

---

## 6. 参考链接

- BLS 非农发布日程：`https://www.bls.gov/schedule/news_release/empsit.htm`
- BLS iCal 订阅：`https://www.bls.gov/schedule/news_release/bls.ics`（**本机 403**）
- Fed FOMC 日历：`https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`（**本机 200**）
- BEA 发布日程：`https://www.bea.gov/news/schedule`（**本机 200**）
- OpenBB 经济日历文档：`https://github.com/OpenBB-finance/openbb-docs`（market_calendars.mdx）
- sifting.io 经济日历 API：`https://sifting.io/docs/economic-calendar/list`
- 事件研究法开源实现：`https://github.com/rla3rd/eventstudies`、`https://github.com/Darenar/easy-event-study`

---

## 7. 对 `plan.md` 的影响（待用户确认）

1. **事件骨架改用官方日历**（原方案是新闻反推）—— 这是**方案级改动**，不是细节。
2. 增加**未来事件**分区（原方案没有）。
3. 新闻检索**降级为叙事层**（原方案里它是主体）。
4. AR/CAR 列为二期评估项（原方案的点对点口径保留为第一期）。
5. BLS 403 需要选一条路（§4.1）。
