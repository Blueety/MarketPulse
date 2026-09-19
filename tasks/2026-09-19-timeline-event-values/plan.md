# 方案：市场日历「事件结果值」层（actual / forecast / previous）

> **需求原话（用户 2026-09-19）**：
> 「市场日历中的事件，只有事件名称，没有事件内容，比如美国的加息议会，没说会后加息了多少，
> 或者 cpi 数据公布，没说 cpi 公布了多少，与大家的预期差了多少」
>
> 页面定位：侧栏「市场日历」= `/timeline`（内部命名 timeline，2026-09-19 接手同名占位项）。
> 前置任务档：`tasks/2026-09-18-event-timeline-page/`（plan v3 定稿 / research.md / journal.md）。
>
> **本文档为只读分析 + 方案，不含完整实现代码。所有"实测"结论均标注了实测条件（2026-09-19，本机直连）。**
>
> **状态（2026-09-19）：定稿，可实施。** §11 的 5 个决策点已确认，**全部采纳推荐项**
> （`D-1a` / `D-2a` / `D-3a` / `D-4a` / `D-5a`）——下文各节已按定稿口径改写。

---

## 0. 结论先行

1. **这不是 bug，是 Phase 1 被显式排除的能力**。`tasks/2026-09-18-event-timeline-page/plan.md` §10 原文：
   「❌ 不接商业 API（TradingEconomics / FMP / Finnhub / sifting.io）」——当时的目标只是"把事件排进日历"。
2. **要做，必须新增一个"结果值层"**（actual / forecast / previous），因为它**在现有数据链路的任何一环都不存在**。
3. **数据源已实测选定**：TradingView 经济日历 JSON 端点（`economic-calendar.tradingview.com/events`）
   —— 本机直连 **200 / 1.6s / 无 key / 无代理**，且 **actual + forecast + previous + unit + importance 全齐**。
4. **对齐命中率已实测：过去事件 33/33 命中，且全部零容差**（不需要 ±1 天容差，大幅降低实现复杂度）；
   未命中 8 条**全部是未来事件**（≥2026-10-28，尚未公布，属正常）。
5. **推荐架构：方案 A（骨架不动 + 结果值层 join）**，不推翻已定稿的"官方日历做骨架"决策。
6. **5 个决策点已定稿**（§11 决策记录），全部采纳推荐项：
   - `D-1a` CPI **照实显示指数水平、零派生**——TradingView 的美国 CPI 是**指数水平 334.98**、**没有同比%**，
     页面按「CPI 指数 334.98（预期 334.85 / 前值 333.92）」显示，并在口径区写明"指数水平，非同比"。
   - `D-2a` 未来事件有 `forecast` 就显示「预期 X（待公布）」，没有就显示「待公布」。
   - `D-3a` `importance` **只落库、不上色**（语义无官方文档，不自己发明分档含义）。
   - `D-4a` 移动端（375px）值区**精简为「实际 X · 变动 Y」两项**，完整三项只在 ≥768px 显示。
   - `D-5a` **只 enrich 骨架已有行**，不做历史回填、不用 TV 反向补事件。

---

## 1. 根因分析（两层，对应"渲染表现根因 / 代码逻辑根因"）

### 1.1 渲染表现根因（用户实际看到什么）

在 `/timeline`「已发生」区，每个事件只有一行：

```
[CPI]  08:30 ET  美国 8 月 CPI（消费者物价指数）  BEA/BLS标签
```

**没有任何数值**。用户举的两个例子在库里都真实存在、且都是"只差数值"：

| 库里现有行（实测 db） | 用户想要的 | 缺什么 |
|---|---|---|
| `2026-09-16 FOMC`「FOMC Meeting - Sep 15-16, 2026」 | 「会后加息了多少」 | 决议利率 4.00%、前值 3.75% ⇒ +25bp 这个**变化量** |
| `2026-09-11 CPI`「CPI Release — August 2026 Data」 | 「CPI 公布了多少、与预期差多少」 | 实际值、预期值、前值、偏离量 |

### 1.2 代码逻辑根因（导致该表现的机制）

**两层同时缺失，缺的是"源"不是"渲染"**：

**① 数据模型层：`econ_events` 表根本没有"值"这个维度**

```sql
-- src/storage.py:49 现状（实测 PRAGMA table_info）
date, kind, title, agency, source, time_et, status, note, fetched_at
```

`src/timeline.py:291-300` 组装 payload 时也是逐键显式构造 —— 即使表里加了列，**不显式加键也不会透传**。
`web/static/timeline.js:247-262` `eventHtml()` 只渲染 kind / time_et / title_zh / status / note / agency。

**② 数据源层：两个源都是"纯日程源"，源头就没有数值**

| 源 | 实测拿到的字段 | 有没有值 |
|---|---|---|
| Fed 官网 FOMC 日历（HTML） | 月份、日期区间、`*`(含 SEP) | ❌ 只有会期 |
| smartcalendars `.ics` 镜像 | `SUMMARY` / `DTSTART` / `DESCRIPTION` / `STATUS` | ❌ **无**。且 `DESCRIPTION` 实测 218 条里**只有 6 条**出现 "actual/forecast" 字样，且是说明文案不是数值 |
| Google News（叙事层） | 篇数 + 首条标题 | ❌ 非结构化，抽数值等于编造 |

⇒ **结论**：链路上没有任何一环"丢掉了"值——**从未采集过**。因此修法只能是**引入一个带值的新数据源 + 新增结果值层**，
在前端"美化"或"改渲染"是无效方向。

---

## 2. 数据源选型：本机可达性实测对照表（2026-09-19）

实测条件：本机直连（未走 Clash 7890 代理），`requests`，超时 25–40s。

| 候选源 | 实测结果 | actual | forecast | previous | 结论 |
|---|---|---|---|---|---|
| **TradingView 经济日历 JSON**<br>`economic-calendar.tradingview.com/events` | ✅ **HTTP 200**，1.58s，229 KB，无 key | ✅ | ✅ | ✅ | **✅ 选用** |
| Trading Economics `c=guest:guest` | ❌ **HTTP 410**：`"the guest account has been discontinued"` | — | — | — | 排除（已停止免费访客） |
| FMP `apikey=demo` | ❌ HTTP 401 `Invalid API KEY` | — | — | — | 排除（需商用 key） |
| FRED | ❌ HTTP 400 需 `api_key`；且**只有实际值、无预期** | 部分 | ❌ | — | 排除 |
| BLS 官方 API（项目生产已在用） | ✅ 可用（POST） | ✅ | ❌ | — | 保留为**交叉校验**备选 |
| jin10 `datacenter-api` | ❌ HTTP 502 | — | — | — | 排除 |
| jin10 `cdn.jin10.com` | ❌ HTTP 404 | — | — | — | 排除 |
| ForexFactory | ❌ HTTP 403（Cloudflare "Just a moment..."） | — | — | — | 排除 |
| 东方财富 `RPT_ECONOMIC_CALENDAR` | ❌ `报表配置不存在`（名字不对，未穷举） | — | — | — | 排除（二期可再探） |
| 镜像 `.ics` 的 `DESCRIPTION` | ✅ 200，但含值条目 6/218 | ❌ | ❌ | ❌ | 排除 |

### 2.1 TradingView 端点实测字段（原样，供复核）

```json
{
  "id": "390604", "title": "Fed Interest Rate Decision", "country": "US",
  "indicator": "Interest Rate", "ticker": "ECONOMICS:USINTR",
  "category": "mny", "period": "", "referenceDate": "2026-09-16T00:00:00Z",
  "source": "Federal Reserve", "source_url": "http://www.federalreserve.gov/",
  "actual": 4, "previous": 3.75, "forecast": 4,
  "actualRaw": 4, "previousRaw": 3.75, "forecastRaw": 4,
  "currency": "USD", "unit": "%", "importance": 1,
  "date": "2026-09-16T18:00:00.000Z"
}
```

**选它的理由**：唯一一个"零 key、零新依赖（`requests` 已在 `requirements.txt`）、直连可用、三类值齐全"的源。
附带三个白捡的好处：
- `source` / `source_url` → **自动标注原始机构**（满足既有"如实标注来源"纪律，无需手写映射）；
- `unit` → 单位（%，避免"4 是多少"的歧义）；
- `importance`（-1/0/1）→ **源自带重要性分档**，正好满足原 plan §10「不做事件重要性的人工标定；要分档就接有官方分档的源，不自己发明阈值」。

### 2.2 用户两个例子的实测答案（验证方案能真的回答需求）

| 需求 | 实测数据 |
|---|---|
| 「议息会后加息了多少」 | `2026-09-16 Fed Interest Rate Decision`：actual **4.00**、previous **3.75**、forecast 4.00、unit % ⇒ **加息 25bp**，符合预期 |
| 「CPI 公布多少、与预期差多少」 | `2026-09-11 CPI`：actual **334.98**、forecast **334.85**、previous **333.92** ⇒ **高于预期 +0.13**（指数水平，见 §11 D-1） |
| （附）非农 | `2026-09-04 Non Farm Payrolls`：actual **162**、forecast **56**、previous **21** ⇒ 大幅超预期 |

---

## 3. 方案选型

### 方案 A（推荐）：骨架不动 + 新增「结果值层」按 `(事件日, kind)` join

```
[TradingView /events]  ──►  src/econ_values.py（抓取 → 归一化 → headline 选择 → 择优）
                                      │  {(ET日期, kind): {actual, forecast, previous, unit, importance,
                                      │                    value_source, value_title}}
                                      ▼
[Fed 页 + 镜像 .ics] ──► econ_calendar.collect_events() ──► join ──► econ_events 表（新增 7 列）
                                      ▼
      storage.query_econ_events() ─► timeline.build_timeline() ─► /api/timeline ─► timeline.js 渲染
```

**关键：join 放在同步脚本侧，不放在 web 侧。** 理由：`/api/timeline` 既有纪律是**不联网**（见 `web/app.py:978-980`
注释：「本端点**不联网**，因此不会像 `/api/econ` 那样受上游抖动影响」），且 TTL 6h 缓存。值落库后该纪律完整保留。

**选它的理由**：
1. `docs/architecture.md` 关键决策行已定稿「官方日历做骨架」，本方案**不改这条决策**，docstring 里那句
   "BLS/BEA/Census 事件经第三方镜像获得"的诚实边界也继续成立（值层单独标来源）。
2. **风险隔离**：TradingView 一旦失效，页面**退化成今天的样子**（只有日程），而不是整个页面挂掉。
   对比方案 B，退化成"连日期都没有"。
3. diff 最小：新增 1 个模块 + 1 个测试文件，改动 5 个既有文件，**不重写 `econ_calendar.py`**。

### 方案 B（不选）：全量改用 TradingView 作为唯一事件源

- 优点：一条链路、字段最全、时刻精确到秒。
- 不选理由：① 推翻已定稿决策（`docs/architecture.md` 关键决策行需重写）；② **该端点未公开、无 SLA、无文档**
  ——把唯一的日期来源压在它身上，是**把降级空间清零**；③ 需重写 `econ_calendar.py` + 全部 `TL-*` 断言；
  ④ 会丢掉 Fed 官方页"含 SEP"等**官方专有信息**。
- 保留为**二期退路**：若 Fed 页与镜像双双失效，再评估。

### 方案 C（不选）：从新闻标题里抽数值

- 不选理由：不可靠、不可对账、**会编造**（违反项目"不猜、不造"纪律），且新闻层受 100 条上限影响。

### 方案 D（不选）：只用 BLS API 实际值、放弃"预期"

- 不选理由：① 拿不到用户**明确要的**「与预期差多少」；② BLS API 只有 4 个序列（CPI-U / PPI / 失业率 / 非农），
  覆盖不了 FOMC / GDP / PCE / 零售 / 工业产出。
- 保留为**交叉校验**手段（二期可选）。

---

## 4. 关键设计点（每条都有实测依据，`D*` 编号在下文被引用）

### D1. 单请求上限 2000 条 ⇒ 抓取必须分段
实测：**2019 / 2021 / 2023 / 2025 / 2026 全年 US 条数"都恰好 2000"**（打满上限），
而 Q3 1007 条、近 90 天 983 条、近 30 天 337 条。
⇒ 抓取按**月分段**（US 每月约 170–200 条，远低于上限）。**年度回填**同理必须分段，不能一把梭。

### D2. `kind → headline 指标` 映射表（必须显式写死；含实测依据）

| kind | TradingView headline 标题 | unit | importance | 实测样本（act/fc/prev） |
|---|---|---|---|---|
| `FOMC` | `Fed Interest Rate Decision` | % | 1 | 4 / 4 / 3.75 |
| `非农` | `Non Farm Payrolls` | **（源无 unit ⇒ 见 D2.1①）** | 1 | 162 / 56 / 21 |
| `CPI` | `CPI` | **（源无 unit，=指数水平 ⇒ 见 D2.1②）** | 0 | 334.98 / 334.85 / 333.92 |
| `PPI` | `PPI MoM` | % | 1 | 0.4 / 0.4 / 0.1 |
| `GDP` | `GDP Growth Rate QoQ Final`／`2nd Est`／`Adv`（**按期次选**，见下） | % | 1 | 1.5 / 1.5 / 2.1 |
| `PCE` | `Core PCE Price Index MoM`（备选 `PCE Price Index MoM`） | % | 1 | 0.2 / 0.2 / 0.1 |
| `零售` | `Retail Sales MoM` | % | 1 | 1.2 / 0.8 / -0.5 |
| `工业产出` | `Industrial Production MoM` | % | 0 | 0 / 0.3 / 0.2 |

⚠️ **GDP 期次必须按期次选，不能按顺序取第一条**：TV 同期有 `GDP Growth Rate QoQ Adv` / `2nd Est` / `Final` 三行，
骨架 title 里已写明 `(Advance Estimate)` / `(Second Estimate)` / `Third Estimate`。
**直接复用既有 `econ_calendar._stage_zh()`**（它已经能把英文 title 解析成 `初值/第二次估计/终值`）来选对应 TV 行
—— 实测这样做 3 次全中（07-30→Adv、08-26→2nd Est、09-30→Final）。

⚠️ **归一化表与 `econ_calendar.KINDS` 必须同源**：TV 的 288 个指标标题里绝大多数不属于这 8 类（PMI、初请失业金…），
**P1 只 enrich 既有 8 类，其余 TV 指标一律不入库**（否则页面会被 2000+ 条/年的小指标淹没）。映射表未命中的 kind → 记 warning，不静默。

### D2.1 显示口径规则（按定稿决策 `D-1a` / `D-3a` 固化，实现时照此写）

**① `unit` 缺失时不得猜单位**（这条是 `D-1a`「零派生」能落地的前提）：
实测 `CPI` 与 `非农` 的 `unit` 都是 `None`，而 `FOMC`/`PPI`/`GDP`/`PCE`/`零售`/`工业产出` 都是 `%`。

| 情形 | 显示 | 禁止 |
|---|---|---|
| `unit` 有值（如 `%`） | `实际 4.00%` | — |
| `unit` 为 null（CPI 指数 / 非农） | `实际 334.98`（**不加任何单位后缀**），口径区注明"源未提供单位" | ❌ 不写 `334.98 点`、❌ 不写 `162 千人`、❌ 不把指数当同比写成 `3.2%` |

**② CPI 按指数水平显示，不派生同比**（`D-1a`）：固定文案
`CPI 指数 334.98（预期 334.85 / 前值 333.92）`，并在「口径与来源」区新增一条：
「美国 CPI 显示为**指数水平**（源数据如此），非同比百分比；同比需另行换算，本页不做。」

**③ `importance` 只落库、不上色**（`D-3a`）：不做行内标记、不做筛选、不做排序键。
落库目的仅是"将来要分档时不必重抓历史"，且**不预设 -1/0/1 的业务含义**。

**④ 「变动」与「偏离预期」两个数字的口径**（都是减法，不是模型）：
- **变动** = `actual − previous`。FOMC 专项：`+0.25` 个百分点 ⇒ 显示 **`加息 25bp`**（`−0.25` ⇒ `降息 25bp`，`0` ⇒ `维持不变`）；其余类显示 `+0.3pp`。
- **偏离预期** = `actual − forecast` ⇒ 文案 `高于预期 +0.13` / `低于预期 -0.2` / `符合预期`。
- ⚠️ 两者都是**纯减法**，不引入任何模型；但仍是本页**最接近"判断"**的文案 ⇒ 措辞只准用
  「高于 / 低于 / 符合预期」这类**客观比较**，**禁止**「利好 / 利空 / 超预期将推动」类因果措辞
  （`TL-7` 复跑必须仍绿，见 `EV-8`）。
- ⚠️ **任一操作数为 `null` 时整项不显示**，不得把 `null` 当 `0` 参与减法（同 `EV-4` 的纪律）。

### D3. 同一 `(日期, kind)` 在 TV 侧可能有多行 ⇒ 必须择优（实测有真重复）

实测：`2025-12-16` 有**两条** `Non Farm Payrolls`（act=-105/fc=None 与 act=64/fc=50，政府停摆顺延的两个数据期）；
`2026-01-14` 两条 `PPI MoM`；`2026-01-22` 两条 `Core PCE Price Index MoM`（一条 fc=None）。
⇒ 若"按标题匹配后取第一条"，会**随机取到错的那条**。
**择优规则（沿用既有 `econ_calendar._rank` 的模式）**：`forecast 非空` > `actual 非空` > `previous 非空`，
再取 `date` 较晚者；**两条候选都非空时记 warning**（暴露歧义，不静默）。断言 `EV-5` 用 `2025-12-16` 这个真实案例锁死。

### D4. 匹配键必须用**美东日期**，不是 UTC 日期

TV 的 `date` 是 UTC ISO（`2026-09-16T18:00:00.000Z`）。实测转 ET 后得到
`08:30` / `14:00` / `10:00`，**与骨架 `time_et` 逐一吻合**（非农/CPI/PPI/零售/GDP/PCE = 08:30 ET，FOMC = 14:00 ET）。
⇒ 用 `econ_calendar._parse_dtstart` 同款的 ET 转换后取日期匹配。
⚠️ 若直接用 UTC 日期，落在 00:00–04:00 UTC 的事件会**错一天**。当前 8 类都在 12:30Z–19:00Z 不触发，
但**规则必须写对**（否则将来扩类型必错）。
（实测结论：**零容差即 33/33 命中**，所以 v1 不要加 ±1 天容差 —— 容差会引入"张冠李戴"的新风险。）

### D5. 值的时效：必须每次重算"过去 N 天"，且写入必须是 **preserve** 语义

- 实际值只在公布**之后**才出现 ⇒ 同步必须每次**重算过去 30 天窗口**（幂等 upsert），
  否则"公布当天那次没抓到"就永久缺失。**不能只在事件当天抓一次。**
- TV 对老事件的 `actual` 偶发为 `null` ⇒ **写入必须"非空才写"**，不得用 `null` 抹掉已落库的值
  ——与 `storage.upsert_history_rows(preserve_existing=True)` 的「NULL 不抹盘中值」**同一纪律**。
- **失败不覆盖**：整源失败 → 只记 `failed`，既有值保留（与 `collect_events` 现有容错同纪律）。

### D6. 表结构迁移：`CREATE TABLE IF NOT EXISTS` **不会**给既有库加列

`storage._SCHEMA` 是 `CREATE TABLE IF NOT EXISTS econ_events (...)` —— 对**已存在的** `data/marketpulse.db`
**不会新增列**。本项目无 migration 框架 ⇒ 必须显式写**幂等 `ALTER TABLE ADD COLUMN`**：
`PRAGMA table_info(econ_events)` 先查列存在性，缺哪列补哪列（可重复跑）。
**列先行、代码后行**（与 `docs/pitfalls.md`「新列迁移前不要在 SQL 层 order 该列」同源纪律）。

### D7. 端点未公开 ⇒ 必须写"失效如何重建"注释 + 降级路径

本项目已有约定（`docs/pitfalls.md` 数据层最后一条）：第三方订阅地址要把"若失效如何重新找"**写进代码注释**。
TV 端点同样处理：注释里写清——用于 tradingview.com 经济日历页，参数 `from`/`to`/`countries`/`importance`，
需带 `Origin`/`Referer` 头；**失效时如何重新定位**（DevTools → Network → 过滤 `economic-calendar`）。
降级：抓取失败 → `econ_values` 返回空 + `failed` 记 `tradingview` → 页面**只显示原来那行名字**（不报错、不清空既有值）。

### D8. `.db` 在 git 里被跟踪 ⇒ 落盘即可上线；注意 `-wal` 残留

实测 `git ls-files data | grep marketpulse` → **`data/marketpulse.db` 已被跟踪**
（`AGENTS.md` 里"SQLite 历史库…gitignore 排除"这句对 `.db` **是过时的**，建议顺手更正，见 §5）。
⇒ 值落在 `.db` 里，cron 的 `auto_commit_push`（路径白名单含 `data/`）会把 `.db` 推上去，Railway 直接读到。
⚠️ 唯一风险：若 `data/marketpulse.db-wal` 残留，提交的 `.db` 可能**不含新行**。
当前实测 `data/` 下**无** `-wal`/`-shm`（连接关闭即 checkpoint），属低风险；
保险做法是 push 前调一次既有的 `storage.wal_checkpoint()`。

---

## 5. 要改的文件列表

### 新增

| 文件 | 职责 |
|---|---|
| `src/econ_values.py` | TradingView 抓取 + `kind→headline` 映射 + ET 日期归一 + 择优 + 纯函数可单测。**零新依赖**（`requests` 已在 `requirements.txt`） |
| `tests/test_econ_values.py` | 单测（**不联网**，用固定 JSON fixture）：映射表、ET 转换（含跨午夜用例）、择优、preserve、失败降级 |
| `tasks/2026-09-19-timeline-event-values/journal.md` | 执行日志（AGENTS.md 要求） |

### 修改

| 文件 | 改动 |
|---|---|
| `src/storage.py` | `econ_events` +8 列幂等迁移（`actual` `forecast` `previous` `unit` `importance` `value_source` `value_title` `value_fetched_at`）；`_ECON_COLS` 投影扩展；新增 `update_econ_event_values()`（**preserve 语义**） |
| `scripts/sync_econ_calendar.py` | 新增"抓值 → join → 落库"步骤；新增 `--skip-values` 开关；`failed` 汇总加 `tradingview` |
| `src/timeline.py` | `build_timeline()` 的 `item` 显式加 8 个键（**必须显式，否则不透传**，见 §1.2 ①）；`SOURCE_NOTES` 加第 4 条（TradingView 值层来源说明） |
| `web/static/timeline.js` | `eventHtml()` 按 `D2.1` 渲染值片段（实际 / 预期 / 前值 / 变动 / 偏离预期）；`unit` 为 null 时不加单位后缀；**未来事件按 `D-2a` 显示「预期 X（待公布）」或「待公布」**；**`D-4a`：`matchMedia('(max-width: 767px)')` 下只渲染「实际 X · 变动 Y」两项** |
| `web/static/style.css` | 新增 `.tl-val*` 段（用既有 token，**不写死色值** —— 双主题自动跟随）；`.tl-val-full` / `.tl-val-lite` 两态按断点互斥显示（**不要用 `display:none` 藏在 HTML 里两份**，见 §8.5） |
| `web/templates/timeline.html` | 「口径与来源」区补 2 条：值来源、CPI 指数口径（若采纳 D-1a） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 新增 `EV-*` 断言组（见 §7.2） |
| `docs/architecture.md` | 关键决策行补"结果值层（TradingView）"；模块表补 `src/econ_values.py` |
| `docs/commands.md` | `sync_econ_calendar` 行补 `--skip-values`；「何时跑什么」补值层一行 |
| `docs/pitfalls.md` | 本轮新踩的坑（TV 2000 上限 / UTC→ET / 同日多期次择优 / ALTER TABLE） |
| `AGENTS.md` | 顺带修正 `data/marketpulse.db` 入库状态的过时描述（§4 D8） |

### 不动

`web/app.py`（`/api/timeline` 透传 payload，无需改；`_ASSET_FILES` 已登记 `timeline.js`）、
`src/econ_calendar.py`（骨架链路**零改动** —— 这是方案 A 的核心优势）、
`/`、`/macro`、`/macro/cn` 三页、`data/history.json`、既有 `TL-*` 断言（只增不改）。

---

## 6. 实施步骤（每步可独立验证）

| # | 步骤 | 文件范围 | 独立验证方式 | 风险 |
|---|---|---|---|---|
| **0** | **join 命中率探针**（只读，不落盘）：拉 TV 值 + 读 db 骨架，打印逐条匹配结果与命中率 | 无（临时脚本，落 `%TEMP%`） | 脚本退出码 0；打印命中率（**基线：过去事件 33/33，零容差**） | 无（只读） |
| **1** | `storage` 加列迁移 + `update_econ_event_values()`（preserve） | `src/storage.py` | 对**既有库**跑 `init_db()` 后：`PRAGMA table_info(econ_events)` 含 8 个新列；`count_econ_events()` **与改动前相同**（旧数据不丢） | 中：写错迁移会污染既有库 → **先备份 `data/marketpulse.db`** |
| **2** | `src/econ_values.py` + 单测 | 新增 2 文件 | `venv/Scripts/python -m pytest tests/test_econ_values.py -v` 全绿（不联网） | 低 |
| **3** | sync 脚本接入（`--skip-values` / `--dry-run` 兼容） | `scripts/sync_econ_calendar.py` | `--dry-run` 打印"值层命中 N/M"；真跑后 `sqlite3` 查 `select count(*) from econ_events where actual is not null` **> 0** 且与步骤 0 的命中数一致 | 中：`--dry-run` 必须**仍不写库** |
| **4** | `timeline.py` 透传 + `SOURCE_NOTES` | `src/timeline.py` | `curl -s "localhost:8000/api/timeline?days=90&future_days=30"` 里事件对象含 `actual` 键 | 低 |
| **5a** | 前端渲染（`D2.1` 五项文案 + `D-2a` 待公布 + `unit` 缺失不加后缀） | `web/static/timeline.js` | `/timeline` 肉眼确认三条：FOMC `实际 4.00% ｜ 预期 4.00% ｜ 前值 3.75% ｜ 加息 25bp`；CPI `实际 334.98`（**无 `%`**）；未来行 `待公布` | 中：见 §8 |
| **5b** | 样式 + 两态断点（`D-4a`）+ 口径文案 | `style.css` / `timeline.html` | `verify_ui.py` 的 `EV-1 ~ EV-11`；@768 三项 / @375 两项 | 中：见 §8.4 / §8.5 |
| **6** | 文档 + 断言 + journal | 5 个文档 + `verify_ui.py` | 完整检查链（§7.1）+ `git diff` 范围核对 | 低 |

**执行顺序纪律**：步骤 1 的迁移必须**先于**步骤 3 的真实落盘（否则 `no such column`）。
步骤 3 真实落盘前**先备份** `data/marketpulse.db` 与 `data/history.json`（后者本轮不该被碰，用于确认"没碰"）。

---

## 7. 验证命令与验收断言

### 7.1 验证命令（全部来自 `docs/commands.md`）

```bash
# 单测（改了 storage / econ_values / timeline 后）
venv/Scripts/python -m pytest tests/ -v

# 完整测试套件 + 前端验收（提交前）
venv/Scripts/python -m pytest tests/ -v
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 本地看板（人工验收环境；web 端点只读、不写 data/）
venv/Scripts/python -m uvicorn web.app:app --port 8000
curl -s "localhost:8000/api/timeline?days=90&future_days=30" | head -c 2000

# 同步脚本（值层接入后先 dry-run，再真跑）
venv/Scripts/python -m scripts.sync_econ_calendar --dry-run
venv/Scripts/python -m scripts.sync_econ_calendar            # 真跑会 commit+push
AUTO_PUSH=0 venv/Scripts/python -m scripts.sync_econ_calendar  # 本地验证用：落盘但不推送

# 落库结果独立核对（绕过 API 与 storage 代码路径）
venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('file:data/marketpulse.db?mode=ro',uri=True);print(c.execute('select count(*) from econ_events where actual is not null').fetchone())"

# 改动范围核对
git diff --stat
```

⚠️ 真跑 `sync_econ_calendar` **会 push 触发 Railway 重部署**，按 `docs/commands.md` 纪律「真跑验证限一次」。

### 7.2 验收断言（新增 `EV-*`，加入 `verify_ui.py`）

| 断言 | 内容 |
|---|---|
| `EV-1` | `/api/timeline` 每个事件含 `actual`/`forecast`/`previous`/`unit`/`value_source` 五键（值可 null，键必须在） |
| `EV-2` | **三方对账**（沿用 `TL-2` 的独立口径手法）：`sqlite3` 直查 `actual is not null` 行数 == API 里 `actual != null` 事件数 == DOM 上渲染出实际值的事件数（前置 `>0`，空集相等不算过） |
| `EV-3` | **真实数据锁死**：`2026-09-16 FOMC` 行的 `actual=4` / `previous=3.75`，UI 文案含 `25bp`；`2026-09-11 CPI` 行 `actual=334.98` / `forecast=334.85` |
| `EV-4` | **无 0/None 混淆**：`actual` 为 null 时**不得**渲染成 `0` / `0.00%`（同 `TL-6` 的纪律，防本项目已踩过的 "None 显示成 0"） |
| `EV-5` | **同日多期次择优**：`2025-12-16` 的非农只取一条（`act=64/fc=50`），页面不出现两行值 |
| `EV-6` | **失败降级**：mock TV 端点 500 → 页面仍有事件行（退化成"只有名字"）、既有 `actual` 不被清空、`failed` 含 `tradingview` |
| `EV-7` | **preserve 语义**：对已落库 `actual` 的行注入一次空值抓取，值仍在（不得被 null 抹掉） |
| `EV-8` | `TL-7` 复跑仍绿（**无因果措辞**）；新增口径说明文案存在（含 D-1a 的"指数水平"与 D-3a 的"源未提供单位"）；四视口无横向溢出（`TL-8` 复跑） |
| `EV-9` | **`unit` 缺失不加单位后缀**（`D2.1①`）：CPI 行的实际值渲染文本为 `334.98`，**不得出现** `%` / `点` / `千人` 等后缀；而 FOMC 行的 `4.00%` **必须**带 `%` |
| `EV-10` | **未来事件文案**（`D-2a`）：`date >= as_of` 的事件若无 `actual`，值区渲染「待公布」或「预期 X（待公布）」，**不得渲染 `0` / `0.00%` 或空白行为**（与 `EV-4` 同纪律） |
| `EV-11` | **两态断点**（`D-4a`）：@768px 值区含「实际 / 预期 / 前值」三项，@375px **只含「实际 / 变动」两项**，且**两份文案不得同时存在于 DOM**（防 §8.5 的"两份 DOM"坑） |

⚠️ 断言标签**禁用 GBK 外字符**（`⇒`、`→` 等）——会让整个脚本 `UnicodeEncodeError` 中途死掉
（`tasks/2026-09-18-event-timeline-page/plan.md:211` 已记，本周刚踩过）。

---

## 8. UI 部分（本方案含前端改动，按 UI 类方案要求补齐）

### 8.1 复现路径（从启动到看见问题）

```bash
1) cd D:\AGENT\MarketPulse
2) venv/Scripts/python -m uvicorn web.app:app --port 8000
3) 浏览器打开 http://127.0.0.1:8000/timeline        （侧栏点「市场日历」同效）
4) 看「已发生」区第一条（约在页面 230px 处）：
   → 现状：只有 [kind] 时刻 中文事件名 机构标签，**行尾无任何数值**
5) 对照需求（改造后的目标态，三条都能当场核对）：
   - FOMC 行：`实际 4.00% ｜ 预期 4.00% ｜ 前值 3.75% ｜ 加息 25bp`
   - CPI 行：`实际 334.98 ｜ 预期 334.85 ｜ 前值 333.92 ｜ 高于预期 +0.13`（**指数水平，不带 % 后缀**）
   - 未来事件行：`预期 X（待公布）` 或 `待公布`
6) 缩窗到 375px 宽复跑第 5 步：值区应**只剩「实际 X · 变动 Y」两项**，且不出现横向滚动条。
```

### 8.2 关键测量点（实测，Playwright chromium，2026-09-19）

**父容器与行盒**：

| 元素 | 实测 |
|---|---|
| `.tl-ev`（事件行） | `box-sizing: border-box`、`display: flex`、**`flex-wrap: wrap`**、`align-items: baseline`、`gap: 6px 8px`、`padding: 0px`、`line-height: 23.2px`、`font-size: 16px`、**`clientHeight/offsetHeight = 20`**、`rectHeight = 19.94` |
| `.tl-events`（`<ul>`） | `display: flex`、`gap: 6px`、`padding: 0px`（**同日多事件并排**，实测 24 天里 5 天有 2 个事件） |
| `.tl-day`（卡片） | `clientWidth` 962（@1280）/ 321（@375）；`rectHeight` **71.73**（@1280）/ **134.2**（@375） |
| `.tl-title` | 文本行数 = 1（`Range.getClientRects().length` 实测） |

**`.tl-ev` 的可用宽度与剩余空间（`offsetWidth` 口径）**：

| 视口 | row `clientWidth` | 现存内容占用 | **行尾剩余** | `.tl-agency` |
|---|---|---|---|---|
| 1920×1080 | 1036 | 287.03 | **748.97** | 显示 |
| 1440×900 | 1008 | 287.03 | 720.97 | 显示 |
| **1280×720** | **856** | 287.03 | **568.97** | 显示 |
| 768×1024 | 706 | 287.03 | 418.97 | 显示 |
| **375×812** | **321** | 254.78 | **66.22** | **`display: none`（移动端隐藏）** |

**拟用值片段的实测尺寸**（文本 `实际 4.00% ｜ 预期 4.00% ｜ 前值 3.75% ｜ 加息 25bp`，`font-size:11px; white-space:nowrap`）：
**宽 263.45px、高 15.94px**。

**两种排布的真实高度增量（原地注入测量，未克隆行，不污染 ul/day 布局）**：

| 排布 | 1920 | 1440 | **1280（720p）** | 768 | **375** |
|---|---|---|---|---|---|
| **行内追加**（值跟在行尾） | rowH **19.94 不变**、dayH 不变 | 同左 | 同左 | 同左 | rowH **19.94 → 41.88（+21.94）**、dayH **134.2 → 156.14（+21.94）** |
| 独立一行（`flex-basis:100%`） | rowH +21.94、dayH +8.08 | 同左 | 同左 | rowH +21.94、dayH +21.94 | rowH +21.94、dayH +21.94 |

**横向溢出**：**两方案在 5 档视口全部 `scrollWidth == clientWidth`、`docOverflowX == false`** —— 因为 `.tl-ev` 是
`flex-wrap: wrap`，放不下就折行而非溢出（**这是本方案的布局安全垫**，也是为什么"加值"不会破 `TL-8` 的无溢出断言）。

### 8.3 box-sizing 说明（必须写清楚，因为它决定"能不能靠 height 约束"）

- **`.tl-ev` 是 `border-box`**（Tailwind/项目 preflight 全局设定，实测 `getComputedStyle` 确认）。
  当前 `padding: 0`、无 `border` ⇒ 本元素 **content 宽 = clientWidth**，故 §8.2 的剩余宽度可直接当预算用。
- **但 `.tl-ev` 的高度是"内容撑开"的**（`clientHeight` 20 来自 `line-height 23.2px` 与 11–13px 子元素，
  **不是显式 `height`**）。⇒ **不要给 `.tl-ev` 设 `height`/`max-height`**：
  - `height` 会把折行内容**裁掉或溢出**（不会把它撑开）；
  - `max-height` 同样**不约束 `padding` 之外的增长**且会静默裁切；
  - 要"限制为一行"只有一条正路：`min-height` + 内容侧 `whitespace-nowrap` + 预算控制（本项目在
    Todo 项目踩过 `h-[44px] + flex-wrap` 内容裸奔的坑，`docs/pitfalls.md` 有同类记录）。
- **`.tl-day` 的高度同理**（`rectHeight` 由内容决定）⇒ 值片段增高会**整体推高卡片**，不会裁。
- **`.tl-title` 是 `white-space: normal`**（实测）⇒ 长中文标题会折行；值片段应显式
  `white-space: nowrap`，避免被同一个折行逻辑"静默折成两行"（**同 `w-64` 弹层 chip 那条坑**）。

### 8.4 多尺寸验收（至少含 720p 与 1080p）

| 视口 | 预期效果（行内追加 + `D-4a` 两态） | 判定 |
|---|---|---|
| **1920×1080 / 1440×900** | **完整三项**单行跟在行尾；`rowH` 保持 **19.94**；`dayH` 不变；无横向溢出 | 目视：值在机构标签右侧，**行高与改造前一致** |
| **1280×720（720p）** | 同上（剩余 568.97px，值片段 263.45px ⇒ 余量约 **305px**） | 目视同上；`verify_ui.py` `TL-8` 复跑绿 |
| 768×1024 | 同上（剩余 418.97px ⇒ 余量约 **155px**）—— **768 是"完整三项"的下边界** | 同上 |
| **768×1024（767px 断点内侧）** | `D-4a` 断点取 **`max-width: 767px`** ⇒ 768 仍走**完整三项** | 断言在 768 与 375 各测一次文案项数 |
| **375×812（移动端）** | 走**精简两项**「实际 X · 变动 Y」：值片段宽约 **150px**（实测 263.45px 的 3/4 文案）⇒ 仍会折行（行尾仅 66.22px），`rowH` 约 **+21.94**；**不允许横向溢出**；`.tl-agency` 移动端本就 `display:none` | 目视：值占第二行且不截断；`docOverflowX == false`；文案**只含「实际」「变动」两项** |

⚠️ **余量提醒（写进实现注释）**：完整三项在 720p 的余量是 **568.97 − 263.45 ≈ 305px**；
若将来还要加"影响分档/惊喜度"，每段约 +50–80px —— 1280 与 768 仍在安全区，
**但 375 的 66.22px 永远不够**，所以移动端**必须**走精简态（这就是 `D-4a` 定稿的原因）。

### 8.5 两态实现约定（`D-4a`，避免踩"两份 DOM"的坑）

- **不要**在 `eventHtml()` 里同时输出完整版与精简版两个 `<span>` 再用 CSS `display:none` 切
  —— 会让 `EV-2`「DOM 渲染出实际值的事件数」三方对账**数出两份**，也会让 `TL-5` 的"同日不重复"类断言失真。
- **正确做法**：JS 侧按 `window.matchMedia('(max-width: 767px)')` 决定渲染哪一组文案，
  并监听其 `change` 事件重渲染（本页无 canvas，`render()` 重放即可，与主题切换同一模式）。
- `.tl-val` 必须显式 `white-space: nowrap`（防被 `.tl-title` 同一套折行逻辑静默折成两行）。
- 口径区新增两条文案（`D-1a` / `D-3a`）：
  ① 「美国 CPI 显示为指数水平，非同比百分比」；② 「源未提供单位的指标按原始数值显示」。

---

## 9. 风险评估与注意事项

| # | 风险 | 等级 | 处置 |
|---|---|---|---|
| R1 | **TV 端点未公开/无 SLA/可能改结构或限频** | **高** | ① 抓取失败 → 保留既有值 + `failed` 记 `tradingview`（降级为"今天的页面"）；② 注释写"失效如何重建"（D7）；③ 已实测 4 个替代源（见 §2）与 BLS API 交叉校验路径，二期可切 |
| R2 | **写入把已落库的值抹成 null** | **高** | preserve 语义（D5）+ 断言 `EV-7`；**落盘前备份 `data/marketpulse.db`** |
| R3 | **`ALTER TABLE` 迁移作用到既有库** | **高** | D6：列存在性检查 + 幂等；步骤 1 与步骤 2/3 分开验证；迁移后 `count_econ_events()` 必须与迁移前相同 |
| R4 | **同日多期次级重复 → 取错值** | 中 | D3 择优 + warning；`EV-5` 用 `2025-12-16` 真实案例锁死 |
| R5 | **CPI 口径误解（指数水平 vs 同比%）** | 中 | 见 §11 D-1（需你拍板）；无论选哪条，页面必须写明"TradingView 的美国 CPI 为指数水平" |
| R6 | **UTC→ET 跨日错配** | 中 | D4；单测覆盖 `2025-11-20T13:30Z`（08:30 ET 同日）与一个 `00:30Z` 跨日反例 |
| R7 | **TV 单请求 2000 上限导致大窗口静默截断** | 中 | D1 按月分段；探针复核"分段条数之和 > 单次条数" |
| R8 | **cron 侧仓库外 `git add -A`**（AGENTS.md 明示：Hermes 5 分钟 cron 全量 add） | 中 | 实施时**一次性完成并显式 `git add <路径>`**，不留半成品源码/文档在工作区 |
| R9 | 真跑 `sync_econ_calendar` 会 push → Railway 重部署 | 低 | 本地验证用 `AUTO_PUSH=0`；真跑**限一次**（`docs/commands.md` 纪律） |
| R10 | `data/marketpulse.db-wal` 残留导致 push 的 `.db` 不含新行 | 低 | 实测当前无 `-wal`/`-shm`；保险做法：push 前 `storage.wal_checkpoint()`（D8） |
| R11 | 断言脆弱点：`verify_ui.py` 的 `navCount == 11` 写死在两处 | 低 | **本次不新增 nav 项** ⇒ 不需改；但注意别误改 |
| R12 | 新增值片段后移动端卡片变高，可能让"已发生"列表显得冗长 | 低 | §11 D-4；必要时移动端只显示"实际值 + 变动"两项 |

---

## 10. 影响的文件范围（预计 diff）

- **新增**：`src/econ_values.py`（约 220 行）、`tests/test_econ_values.py`（约 200 行）、`tasks/2026-09-19-timeline-event-values/journal.md`
- **修改**：`src/storage.py`（+60 行）、`scripts/sync_econ_calendar.py`（+40 行）、`src/timeline.py`（+15 行）、
  `web/static/timeline.js`（+45 行）、`web/static/style.css`（+25 行）、`web/templates/timeline.html`（+2 行）、
  `verify_ui.py`（+180 行，`EV-*` 组）、`docs/architecture.md`（+2 行）、`docs/commands.md`（+2 行）、
  `docs/pitfalls.md`（+18 行）、`AGENTS.md`（±1 行）
- **删除**：无
- **DB 变更**：`econ_events` +8 列（幂等 `ALTER TABLE`，不建新表、不动主键、不改既有行）
- **不碰**：`src/econ_calendar.py`、`web/app.py`、`/`、`/macro`、`/macro/cn`、`data/history.json`、既有 `TL-*` 断言

---

## 11. 决策记录（**2026-09-19 已确认：全部采纳推荐项**）

> 下表是**已定稿**口径，实施时直接照此写；"未选项"保留仅为记录取舍理由，**不要再翻案**。

| # | 议题 | **定稿（采纳）** | 未选项（记录取舍） | 落地位置 |
|---|---|---|---|---|
| **D-1** | CPI 显示口径 | **D-1a 零派生**：照实显示指数水平 `实际 334.98 ｜ 预期 334.85 ｜ 前值 333.92`，口径区写明"美国 CPI 为指数水平，非同比" | D-1b 派生 MoM/YoY（属派生值，须另标注且与源值分列）；D-1c 两个都显示（成本最高） | §4 `D2.1①②`、§5 `timeline.js`/`timeline.html`、§8.5 文案、`EV-9` |
| **D-2** | 未来事件的值 | **D-2a**：有 `forecast` → 「预期 X（待公布）」；无 → 「待公布」 | D-2b 未来完全不显示值区 | §5 `timeline.js`、`EV-10` |
| **D-3** | `.importance`（-1/0/1） | **D-3a 只落库、不上色**（不做标记/筛选/排序，不预设其业务含义） | D-3b 行内小圆点；D-3c 完全不落库 | §4 `D2.1③`、§5 `storage.py`（列照加） |
| **D-4** | 移动端值区 | **D-4a 两态**：375px 只渲染「实际 X · 变动 Y」；≥768px 渲染完整三项 | D-4b 不做响应式（接受移动端行高翻倍） | §5 `timeline.js`/`style.css`、§8.4/§8.5、`EV-11` |
| **D-5** | 历史值回填 | **D-5a 只 enrich 骨架已有行**（窗口内 33 条），零额外复杂度 | D-5b 顺带回填（需分段抓+逐月落库）；D-5c 反向用 TV 补事件（会引入 2000+ 条/年小指标） | §2.2、§6 步骤 3 |

**由此产生的两条硬约束（实施时必须遵守）**：

1. **`unit` 缺失不得猜单位**（`D-1a` 的直接推论）⇒ 见 §4 `D2.1①`。
   `CPI` / `非农` 的 `unit` 实测都是 `null`，必须显示原始数值 + 口径区说明，**禁止**补 `点` / `千人` / `%`。
2. **`future_days` 窗口内的值区不得留空白行为**（`D-2a`）⇒ 见 `EV-10`。
   实测 ≥2026-10-28 的事件在 TV 里**尚无条目**、`2026-10-02 非农` 的 `forecast` 也为 `null`
   ⇒ 这两类都必须落到「待公布」，而不是渲染成空串（空串会被读成"页面坏了"）。

---

## 12. 明确不做

- ❌ 不用 TradingView 替换 Fed / 镜像 骨架（方案 B）
- ❌ 不抓 BLS/BEA 网站正文；不引入 `icalendar` 等新依赖（值层只用 `requests`）
- ❌ 不做因果推断、不打「利好/利空」标签（沿用 `TL-7`）
- ❌ 不新增 nav 项、不改既有 `TL-*` 断言语义（只新增 `EV-*`）
- ❌ 不改 `/`、`/macro`、`/macro/cn` 三页；不动 `data/history.json`
- ❌ 不把 TV 的 288 个指标全量入库（只 enrich 既有 8 类）
- ❌ 不加 ±N 天模糊匹配（实测零容差 33/33，容差反而引入错配风险）
- ❌ 不引入 `importance` 的自定义阈值，也不上色（`D-3a`）
- ❌ **不派生 CPI 的同比 / MoM**（`D-1a`）；不顺带回填历史值（`D-5a`）
- ❌ **不给 `unit` 缺失的指标补单位**（`D2.1①`：不写 `点` / `千人` / `%`）
- ❌ 不用"两份 DOM + CSS 隐藏"实现移动端两态（`D-4a` / §8.5，会让 `EV-2` 三方对账数出两份）

---

## 13. 附：本方案依据的实测证据清单（可复现）

| 证据 | 复现方式 | 结论 |
|---|---|---|
| TV 端点可达 + 字段 | 直连 `GET /events?from&to&countries=US`（带 Origin/Referer） | 200 / 1.58s / `actual`+`forecast`+`previous`+`unit`+`importance` |
| 单请求 2000 上限 | 2019/2021/2023/2025/2026 全年各查一次 | 全部**恰好 2000** |
| 历史深度 | `from=2024-01-01` 查 CPI/非农 | 值仍在（216/170/173 等） |
| **join 命中率** | 拉 TV 3631 条 → 与 db 骨架 41 条窗口事件对齐 | **命中 33 / 未命中 8，命中率 100%（过去事件），全部零容差** |
| 未命中的都是未来 | 逐条打印 | 8 条全部 ≥2026-10-28 |
| CPI 无同比行 | 枚举 2025-08~2026-09 的 CPI 族标题 | 只有 `CPI` / `CPI s.a`，`unit=None`、`importance=0` |
| 同日多期次重复 | 打印近一年 headline 时刻表 | 2025-12-16 两条非农、2026-01-14 两条 PPI、2026-01-22 两条 Core PCE |
| UTC→ET 时刻吻合 | `08:30 ET` / `14:00 ET` 逐条对照骨架 `time_et` | 逐一吻合 |
| 布局几何 | Playwright 五视口 + 原地注入 | §8.2 表格（`flex-wrap: wrap` 是布局安全垫） |
| `.db` 入库 | `git ls-files data` | `data/marketpulse.db` **已跟踪** ⇒ 落盘即上线 |

---

## 14. 确认

- [x] 人已审阅计划（2026-09-19）
- [x] 5 个决策点（§11 D-1~D-5）已拍板 —— **全部采纳推荐项**：`D-1a` / `D-2a` / `D-3a` / `D-4a` / `D-5a`
- [x] 文件范围合理（§5 / §10）
- [x] 未引入新依赖（仅复用既有 `requests`）
- [x] 迁移顺序与备份策略确认（§6 步骤 1/3、R2/R3）
- [x] 新增两条由决策派生的硬约束已写死在方案里：`unit` 缺失不猜单位（`D2.1①`）、未来值区不留空白（`D-2a` / `EV-10`）

**下一步**：按 §6 步骤 0 → 6 交执行者实施（步骤 1 迁移必须先于步骤 3 真实落盘）；
本轮**不动** `docs/pitfalls.md` / `AGENTS.md` 的经验沉淀，待实施完成后一并追加（见 §5 修改清单）。
