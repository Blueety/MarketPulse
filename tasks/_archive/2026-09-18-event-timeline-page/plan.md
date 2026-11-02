# 方案（定稿）：宏观事件时间线页面 `/timeline`

> 用户需求（2026-09-18）："影响市场的新闻事件，比如加息议会、非农数据什么什么的"
> 调研依据：`research.md`（业界三类做法 + 本机可达性实测）
> 用户决策：**采纳调研建议的 A 方案** —— 官方日历做骨架，新闻检索降为叙事层。
>
> 演变过程：v1 把"事件"当成市场异动（错）→ v2 改成新闻检索发现事件（绕远路）→ **v3 定稿：官方日历预定事件 + 新闻补充叙事**。

---

## 1. 一句话方案

**事件日期用官方发布日历（提前公告、精确、含未来），市场影响用本地行情（事后实测），新闻作叙事补充。**

原 v2 方案的错误在于**绕远路**：用"媒体报道了多少篇"去**反推**事件——而议息、非农、CPI 的日期是**提前数周官方公告的**，
根本不需要反推。

---

## 2. 数据源（三源分工，全部经本机实测）

| 源 | 提供什么 | 抓取方式 | 实测结果 |
|---|---|---|---|
| **Fed 官网 FOMC 日历** | FOMC 会议（日期区间 + 是否含 SEP 经济预测） | HTML 解析 | ✅ 200，**2021~2027 共 7 年** |
| **第三方经济日历 .ics**<br>（smartcalendars.ai） | BLS（非农/CPI/PPI）+ BEA（GDP/PCE）+ Census（零售） | iCalendar，**纯 stdlib 可解析** | ✅ 200，**185 事件**，`DTSTART` 覆盖 2026-04 ~ **2028-02** |
| **Google News 检索** | 叙事层：当天媒体在谈什么 + 热度（篇数） | RSS + `after:`/`before:` | ✅ 200，**可回溯 1 年** |

### 2.1 为什么 BLS 不直连

实测：**BLS 的 `.ics` 与日程页，直连与代理 7890 全部 403**（与项目里记的"BLS 间歇不可用"同源）。
BLS 的 **API** (`api.bls.gov`) 项目在生产一直可用，**但 API 只返回数据（period 像 `2026-08`），不返回发布日期** ——
用它反推只能得到"通常次月中旬"这种近似值，**不如镜像的精确日期**。

⇒ 按 A 方案：**BLS 侧走镜像，页面上标注"经由第三方镜像，原始来源 bls.gov"**。

### 2.2 为什么 BEA 也不直连

实测 BEA 日程页 200，但**日程不在 HTML 里**（`<table>` 仅 1 个且非日程表、无 JSON、无 API 痕迹、无 SSR 结构）
⇒ 需要 JS 渲染或未公开接口 ⇒ **一并走镜像**（镜像自述来源含 `bea.gov`）。

### 2.3 各源覆盖范围（实测数字）

| 源 | 时间跨度 | 事件类型 |
|---|---|---|
| Fed FOMC | 2021 ~ **2027** | FOMC 会议（8 场/年）+ 含/不含 SEP |
| 镜像 .ics | 2026-04 ~ **2028-02** | FOMC Day1/2（78）、零售（22）、PPI（14）、GDP（12）、CPI（11）、利率决议（7）、PCE（2）、非农（多条，命名不一） |
| Google News | 近 1 年 | 任意主题（含地缘、关税等日历覆盖不到的） |

---

## 3. ⚠️ 三个实测踩出来的坑（必须按此实现）

### 3.1 Fed 页面的年份**不能按区块顺序推断**

```
h4 顺序实测: 2026, 2025, 2024, 2023, 2022, 2021, 2027   ← 2027 排在最后！
```

**必须从 `<h4>2026 FOMC Meetings</h4>` 的文本解析年份**，不能取"第一个区块"或"最后一个区块"。
（按第一个取会拿到 2026、按最后取会拿到 2027，都不对。）

解析锚点（实测有效）：`fomc-meeting__month` → 月份；`fomc-meeting__date` → 日期（形如 `27-28`、`17-18*`）。
`*` 后缀 = 该次会议含 SEP 经济预测。

### 3.2 镜像 .ics 的 **`STATUS:CANCELLED` 高达 75/185（40%）**

实测 `STATUS` 分布：`CANCELLED: 75`、`TENTATIVE: 3`、其余无 STATUS。

**必须过滤 `CANCELLED`**，否则页面上会出现一堆"已取消"的事件。
`TENTATIVE` **保留但标注"暂定"**（它是有效信息，不是噪声）。

⚠️ 注意：不能因为"40% 被取消"就判定该源不可信 —— iCalendar 规范里**改期 = 取消旧条目 + 新建**，
所以 CANCELLED 多数是"被替换的旧日期"。**过滤后仍需去重**（见下）。

### 3.3 镜像里**同一天同一事件有多条重复**（实测）

```
20260904 | US Employment Situation Release
20260904 | US Employment Situation Report — August 2026 Data     ← 同一天两条
20261106 | US Employment Situation Report — October 2026 Data
20261106 | US Employment Situation Release                        ← 同一天两条
```

⇒ **按 `(日期, 归一化事件类型)` 去重**；类型归一化见 §4.2。

---

## 4. 事件模型

### 4.1 统一结构

```python
{
  "date": "2026-09-11",
  "kind": "CPI",              # 归一化事件类型（见 §4.2）
  "title": "CPI Release — August 2026 Data",
  "agency": "BLS",            # BLS / BEA / Fed / Census
  "source": "mirror",         # fed | mirror | news
  "time_et": "08:30",         # 时刻（镜像 159/185 带时刻；Fed 会议无时刻）
  "status": "ok",             # ok | tentative
  "note": "含 SEP 经济预测",   # 会议类特有
  # 叙事层（可空）
  "news_count": 34,
  "news_title": "美国8月CPI报告改变美联储加息叙事：…",
  "news_link": "https://…",
  # 影响层（由 db 计算，见 §5）
  "market": {"gspc": -0.48, "ixic": -0.56, "sh": -0.07, "vix_chg": -11.21}
}
```

### 4.2 事件类型归一化表

事件名在不同源里写法各异（`US Employment Situation Release` / `Employment Situation (Nonfarm Payrolls)` /
`US Employment Situation Report — August 2026 Data`）⇒ 必须归一化到固定枚举：

| kind | 匹配关键词 | agency |
|---|---|---|
| `FOMC` | `FOMC` | Fed |
| `非农` | `Employment Situation` / `Nonfarm` | BLS |
| `CPI` | `Consumer Price Index` / `CPI` | BLS |
| `PPI` | `Producer Price Index` / `PPI` | BLS |
| `GDP` | `GDP` | BEA |
| `PCE` | `PCE` / `Personal Income and Outlays` | BEA |
| `零售` | `Retail` / `MARTS` | Census |
| `工业产出` | `Industrial Production` / `G.17` | Fed |

⚠️ **归一化必须做**，否则"同一个非农"会在页面上出现三四次（实测就会有）。
去重键 = `(date, kind)`。

### 4.3 影响层（由 db 计算，口径复用既有）

- **当日**：事件日的 `gspc / ixic / sh` 涨跌幅 + `vix` 变化（db 直读）
- **事件后**：`+1 / +3 / +5 / +10 交易日` 点对点收益 —— 与 `scripts/backtest.py` 的 `HORIZONS` **同一口径**
- ⚠️ **"未走满"必须逐键判断**（实测：09-17 的 `gspc` 有值、`ixic` 未有值；同一天 `sh` 已有值）
  ⇒ 用 `h[j].get(k)` 判断，**不要按行判断**，否则会把有数据的列一起标成"无数据"

---

## 5. 页面设计

### 5.1 两个分区

```
┌─ 即将到来 ────────────────────────────────
│  09-30 周二  [GDP]      Q2 终值      08:30 ET
│  10-02 周三  [非农]     9月就业报告    08:30 ET      ← 日历的前瞻能力（原方案做不到）
│  10-14 周二  [CPI]      9月CPI        08:30 ET
├─ 已发生 ─────────────────────────────────
│  09-11 周五   [CPI] 34 篇报道  CPI Release — August 2026 Data
│              当日 标普500 +0.11%  纳斯达克 +0.31%  上证 -0.42%
│              事件后 +1日 -0.48% / +3日 -1.37% / +5日 待走满
│              市场叙事：美国8月CPI报告改变美联储加息叙事：从"加不加"到"加几次"
│  09-16 周三   [FOMC]  议息决议（含 SEP）  当日 …
└──────────────────────────────────────────
```

**「即将到来」是这次调研带来的新增能力**（官方日历含未来日程，实测到 2028-02）。

### 5.2 分组与密度

- 按 `date` 分组，同日多事件合并为一张卡
- 「已发生」默认显示**最近 90 天**，可加载更早（官方日历可回溯到 2021 的 FOMC）
- 「即将到来」默认显示**未来 30 天**

---

## 6. 技术方案

### 6.1 新增文件

| 文件 | 职责 |
|---|---|
| `src/econ_calendar.py` | **两个抓取器 + 归一化**：① Fed FOMC HTML 解析 ② 镜像 .ics 解析（stdlib `email.utils`/正则，**不引入 icalendar 依赖**）③ `normalize_kind()` ④ 去重与 CANCELLED 过滤。纯函数可单测 |
| `src/timeline.py` | 事件 × 行情 → 组装 payload（含 forward 计算，复用 backtest 口径） |
| `scripts/sync_econ_calendar.py` | 抓取并落盘（`--dry-run` / `--from` / `--to`） |
| `web/templates/timeline.html` | 页面 |
| `web/static/timeline.js` | 取数 + 渲染 + shell（第 4 份副本，见 §9） |
| `tests/test_econ_calendar.py` | 单测：归一化、CANCELLED 过滤、去重、Fed 年份解析、iCal 解析 |

### 6.2 改动文件

| 文件 | 改动 |
|---|---|
| `src/storage.py` | 新表 `econ_events`（`date, kind, title, agency, source, time_et, status, note, fetched_at`，`UNIQUE(date, kind, source)`） |
| `web/app.py` | `GET /api/timeline?days=90&future_days=30`（TTL 缓存 6h，照 `/api/econ` 惯例）+ `/timeline` 路由；**`_ASSET_FILES` 加 `timeline.js`** |
| `web/templates/_sidebar.html` | nav 项「事件时间线」（放「告警记录」之后，两者同源） |
| `web/static/style.css` | `.tl-*` 段（用既有 token，**不写死色值**——双主题要自动跟随） |
| `verify_ui.py` | **navCount 11 → 12**（写死在 **915 / 1907** 两处，已 grep 确认）+ `TL-*` 断言组 |
| `docs/frontend-structure.md` | 补新页面模块清单与硬约束 |

### 6.3 数据刷新

- 官方日历变动很慢（月度/年度级别）⇒ **每天抓一次足够**，由既有 cron 侧调 `python -m scripts.sync_econ_calendar`
- 新闻叙事层（若做 P3）独立按天抓
- **抓取必须容错**：单个源失败 → 保留既有数据 + 记 `failed`，**不清空**（照 `/api/econ` 的"失败不缓存"反向：这里是"失败不覆盖"）

### 6.4 验收断言（新增 `TL-*`）

| 断言 | 内容 |
|---|---|
| TL-1 | `/timeline` 200 且页面模块骨架齐全 |
| TL-2 | `/api/timeline` 的**已发生**事件数 == 服务端从 db 直算的数（独立口径对齐） |
| TL-3 | 事件种类 ∈ 归一化枚举（**不得出现未归一化的原始事件名**，防 §4.2 漏配） |
| TL-4 | **无 `CANCELLED` 事件出现在页面上**（§3.2 过滤生效） |
| TL-5 | **同 `(date, kind)` 不重复渲染**（§3.3 去重生效） |
| TL-6 | forward 为 `null` 时渲染 `—`/`待走满`，**不得显示 `0.00%`**（防"None 显示成 0"这类既有缺陷） |
| TL-7 | 含"不构成因果"标注；页面不含"因/导致/利好/利空"等因果措辞 |
| TL-8 | 375 / 768 / 1280 / 1920 四视口**无横向溢出** |
| TL-9 | nav 项 12 且 `timeline` active 正确（与 navCount 改动联动） |

⚠️ 断言标签**禁用 GBK 外字符**（`⇒` 等）——会让整个脚本 `UnicodeEncodeError` 中途死掉（pitfalls 专条，本周刚踩过）。

---

## 7. 诚实边界（必须写在页面上）

1. **日历时间是"排定/估计"值，不是数据真正公开的时刻**（抄 OpenBB 文档的提示，原文很准确）。
2. **镜像源需标注**：BLS / BEA / Census 的事件来自第三方镜像，**原始来源标注为 bls.gov / bea.gov / census.gov**。
3. **新闻热度是检索口径**：受 Google 索引与**每次 100 条上限**影响，只能读作"**至少**这么多篇"。
4. **时间先后不构成因果**：事件与行情并列展示，**不生成"因 X 所以 Y"**、不打"利好/利空"标签。
5. **"事件后 +3 日 −1.37%" 只说明同期表现，不说明是事件造成的** —— 这是点对点口径的固有局限，
   要能说"异常影响"需升级到 AR/CAR（§8 二期）。

---

## 8. 分期实施

| 期 | 内容 | 交付物 |
|---|---|---|
| **P1** | `econ_calendar.py`（双源抓取 + 归一化 + 过滤去重）+ `storage` 建表 + 落盘脚本 | **可用命令行查询的事件日历**（含未来），**不碰前端** |
| **P2** | `/api/timeline` + 页面 + nav + `TL-*` 断言 | 可看的页面 |
| **P3** | 新闻叙事层接入（Google News 检索 → 挂到事件上）+ 日常增量 cron | 事件带上"当时在谈什么" |
| **P4（评估）** | 影响口径升级为 **AR / CAR**（事件研究法：估计窗口回归 → 异常收益 → 显著性检验） | 统计上站得住的"影响" |

**P1 先做的理由**：① 它是唯一的**外部依赖**步骤（源可能变动）② 没有它，P2 无数据可渲染 ③ 成本低（两个抓取器 + 一个表）。

⚠️ P4 的取舍：需要因子数据（Fama-French）与新统计代码。项目当前"零新依赖"纪律下，
**市场模型的 OLS 可以纯 Python 实现**，但因子数据要另想办法 ⇒ **P4 单独立项评估，不预设在本次范围**。

---

## 9. ⚠️ 两个架构代价（与前几版一致，未变）

1. **shell 逻辑变成第 4 份副本**（主题初始化 / 市场状态 / 抽屉 / 顶栏数据日）。
   建议本次照惯例复制（`AGENTS.md` 要求 diff 最小），抽 `shell.js` **另开任务**，不要混进同一个 diff。
2. **`navCount == 11` 写死在验收脚本两处**（915 / 1907），加 nav 项必须同步改。

---

## 10. 明确不做

- ❌ 不抓 BLS/BEA 网站正文或文章（只取**日程**，尊重数据源）
- ❌ 不引入 `icalendar` 等新依赖（.ics 用 stdlib 正则 + `email.utils` 解析即可）
- ❌ 不做因果推断 / 不生成事件解读 / 不自动打"利好利空"
- ❌ 不接商业 API（TradingEconomics / FMP / Finnhub / sifting.io）—— 留作以后要 `impact` 分档时的选项
- ❌ 不改既有 `/`、`/macro`、`/macro/cn` 三页行为
- ❌ 不做事件重要性的人工标定（P1~P3 不用任何重要性分档；要分档就接有官方分档的源，不自己发明阈值）

---

## 11. 风险

| 风险 | 处置 |
|---|---|
| 镜像站不可用 / 改结构 | 抓取失败**保留既有数据**不清空；`source` 字段记录来源便于排查；必要时启用备选（B 生产直连 BLS / C 商业 API） |
| Fed 页面改版 | 解析器失败 → 该源标记 `failed`，页面其余部分不受影响（两源独立） |
| 归一化表漏配 → 同一事件重复出现 | TL-3 断言锁枚举；`normalize_kind` 未命中时**记 warning 并归入 `其他`**，不静默丢弃 |
| 事件与行情对不上（时区/交易日） | 事件日按**美东**归档，与 db 的 A 股/美股映射各自处理；"未走满"逐键判断 |
| 未来事件过期后仍显示 | "即将到来"按 `date >= today` 过滤，过期自动落入"已发生" |

---

## 12. 提交清单

```
src/econ_calendar.py
src/timeline.py
src/storage.py
scripts/sync_econ_calendar.py
web/app.py
web/templates/timeline.html
web/templates/_sidebar.html
web/static/timeline.js
web/static/style.css
tests/test_econ_calendar.py
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
docs/frontend-structure.md
tasks/2026-09-18-event-timeline-page/plan.md
tasks/2026-09-18-event-timeline-page/research.md
tasks/2026-09-18-event-timeline-page/journal.md
```

⚠️ `git add <具体路径>`，**不用** `-A`（仓库外 cron 仍全量 add，别留半成品）。
⚠️ `docs/user-guide.md`（本日另一任务）与 `tasks/2026-09-18-macro-quadrant-matrix/`（另一个计划）**不要混入本次提交**。
