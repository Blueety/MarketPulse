# Journal：宏观事件时间线页 `/timeline`（P1 + P2 + P3）

> 需求（2026-09-18）："影响市场的新闻事件，比如加息议会、非农数据什么什么的"
> 方案：`plan.md`（v3 定稿）｜调研：`research.md`（业界三类做法 + 本机可达性实测）
> **本轮范围（用户裁定）**：**P1+P2+P3 全做**（P4 AR/CAR 单独立项，不做）；
> 历史深度：**按数据实际覆盖**展示，不做额外回填。

---

## 1. 一句话交付

**事件日期用官方发布日历（提前公告、精确、含未来），市场影响用本地行情（事后实测），新闻作叙事补充** ——
落成 `/timeline` 页（「即将到来 / 已发生 / 口径与来源」三块）+ `/api/timeline` + 逐日落盘脚本 + 16 条 `TL-*` 验收。

## 2. 数据源实测（侦察阶段，全部本机跑过）

| 源 | 形态/地址 | 实测结果 |
|---|---|---|
| **Fed FOMC 日历** | `federalreserve.gov/monetarypolicy/fomccalendars.htm`（HTML） | 200 / 165 KB；`<h4>` 顺序 = 2026,2025,2024,2023,2022,2021,**2027**；`fomc-meeting__month` + `fomc-meeting__date` 锚点；**共 57 场会议（2021-01 ~ 2027-12）** |
| **镜像 .ics** | `smartcalendars.ai/cal/8d6bda5f…1152c.ics`（**hash 路径，不可猜**） | 200 / 87 KB；**185 个 VEVENT**，`STATUS:CANCELLED 75 / TENTATIVE 3`；`DTSTART` 159 条带 UTC 时刻 + 26 条纯日期 |
| **Google News RSS** | `news.google.com/rss/search?q=…+after:D+before:D+1` | 200；单次上限 **100 条**（⇒ 热度只能读作"至少 N 篇"） |

**找 .ics 地址的过程**（写进代码注释了，防失效后重找）：首页与 sitemap 都没有 →
`/en/feeds/c/finance` 列出 feed slug（`us-economic-calendar`）→ 抓 `/en/feeds/us-economic-calendar`
的 **RSC 载荷**里拿到 `webcal://…/cal/<64 位 hash>.ics`。

**存活口径**：185 条里 FOMC 家族 45 条（按源分工丢弃）+ CANCELLED 75 条（过滤）⇒ **镜像侧 65 条**
（PCE 14 / 非农 11 / PPI 11 / GDP 10 / CPI 7 / 零售 6 / 工业产出 6），**全部带时刻**（08:30×59、09:15×6
—— 与 BLS/BEA/Fed 的公开惯例逐一吻合，可当作解析正确性的交叉验证）。
两源合流去重后 **103 条**（Fed 57 + 镜像 65 − 同 `(date,kind)` 重复 19）。

## 3. 关键设计决策（都带理由）

| 决策 | 理由 |
|---|---|
| **FOMC 由官方页单独负责，镜像的 FOMC 家族整族丢弃** | 镜像把一次会议拆成 `Day 1` / `Day 2` / `Rate Decision` / `Press Conference` / `Minutes`（同次会议 3~4 条，Day1 与 Day2 还是不同日期）⇒ 不丢会与官方源撞成重复；plan §2 的分工表本来就是"Fed 页 = FOMC" |
| **归一化到 8 类 + `其他`**（`normalize_kind`） | 同一非农在不同源写成 3 种名字；不归一化页面上会出现三四遍。未命中**记 warning 归 `其他`**，不静默丢 |
| 去重键 = `(日期, 归一化类型)`；同键时 `fed > mirror`，再按标题信息量/长度 | 实测镜像内部同一天有两条非农、两条 PPI；库里保留两源便于对账，页面只出一条 |
| `time_et`：UTC → **America/New_York**；Fed 会议无时刻（`None`） | 12:30Z→08:30、18:00Z→14:00、13:15Z→09:15，与公开惯例吻合 |
| **每标的"交易日轴"**（只保留"非空且与前值不同"的行） | 🔴 见 §5.1：`history` 表休市日带沿用值，按行序 +h 会算出**假的 0.00%** |
| 叙事层**按 `(date, kind)`** 存（不是按日期） | 同一天可能有两个事件（09-30 GDP + PCE），各有各的检索口径，共用一条会串味 |
| 新闻抓取只抓**已发生**的事件（`date <= today`） | 未来事件没有新闻，抓了也是空 —— 省一半请求（本轮 13 次请求） |
| 「加载更早」= 90 天 → 1 年 → 3.3 年 → 10 年，到库内最早事件自动隐藏 | plan §5.2 要求"可加载更早"；按钮文案直接报下一档，避免"点了没反应" |

## 4. 改动清单

| 文件 | 角色 |
|---|---|
| `src/econ_calendar.py` **新** | 两个抓取器（Fed HTML / 镜像 .ics，纯 stdlib 正则）+ `normalize_kind` + CANCELLED 过滤 + `(date,kind)` 去重 + 容错（单源失败记 `failed`，不抛） |
| `src/timeline.py` **新** | 事件 × 行情 × 叙事 → payload；`trading_axes` / `same_day_changes` / `forward_returns`（+1/3/5/10 交易日，逐键判空）；`fetch_event_news` / `parse_news_rss` |
| `scripts/sync_econ_calendar.py` **新** | 落盘（`--dry-run/--from/--to/--skip-news/--news-window`）；两源全失败才退 2 |
| `src/storage.py` | 新表 `econ_events`（PK `date,kind,source`）+ `econ_event_news`（PK `date,kind`）+ 读写函数 |
| `web/app.py` | `/api/timeline`（TTL 6h、按 `(days,future_days)` 分键、**全空不缓存**）+ `/timeline` 路由 + `_ASSET_FILES` 加 `timeline.js` |
| `web/templates/timeline.html` **新** / `web/static/timeline.js` **新** | 页面 + 第 4 份 shell 副本（主题/抽屉/市场状态**逐字复制**，含互指注释） |
| `web/templates/_sidebar.html` | nav 第 12 项「事件时间线」（跨页链接，`href="/timeline"`，**不写 data-target**） |
| `web/static/style.css` | `.tl-*` 段（998-1074；只用 token，含 `.tl .up/.down` 与两档响应式） |
| `tasks/.../verify_ui.py` | `TL-*` 16 条 + `navCount` 11→12（`F-5` / `CN-7` 两处） |
| `tests/test_econ_calendar.py` **新** | 21 条单测（归一化 / ics 过滤 / Fed 年份与跨月 / 去重 / **沿用值不算 0.00%** / payload 组装 / storage 往返） |
| `docs/` | `frontend-structure.md`（§1/§2/§3.5/§4/§5.4/§6/§7-14）、`pitfalls.md`（新增「数据层」节）、`architecture.md`（决策行） |

## 5. 过程中踩到/修掉的四个问题

### 5.1 🔴 `history` 休市日"沿用值" → 假的 `0.00%`（**本轮最实质的缺陷**）

实测：
```
2026-09-04 Fri  gspc=7718.6    sh=3930.1164
2026-09-05 Sat  gspc=None      sh=3930.1164   <- 沿用周五
2026-09-06 Sun  gspc=7718.6    sh=3930.1164   <- 沿用周五
2026-09-07 Mon  gspc=7718.6    sh=3932.6992   <- 美国劳动节，继续沿用
```
按 `row[i+h]` 算 +1 交易日 ⇒ 09-04 的 `sh` 得到 **`0.0`（假）**、`gspc` 得 `None`；
"当日涨跌"在周一也会拿休市日的沿用值当"前收"。**修法**：每个标的建**交易日轴**
（只保留"非空且与前值不同"的行），轴上取 `pos+h`。修后 09-04：`+1 gspc -0.584% / sh +0.066%`，
轴长 gspc 255 / sh 248（差 7 天 = A 股节假日），全部合理。
> ⚠️ **同类风险不在本次范围**：`scripts/backtest.py:29 HORIZONS` 用的是同样的"按行序"口径，
> 也会被沿用行污染（表现为前向收益里出现 0.00%）。**已记录，未改**（plan 未列它；改动会影响既有回测口径）。

### 5.2 🔴 Fed 跨月会议月份写 `Jan/Feb` → 静默漏 3 场会议

只认全名月份（`January`）时，`Jan/Feb`/`Oct/Nov`/`Apr/May` 三行被跳过：2023 只解析出 6 场、2024 只 7 场。
**发现手法**：逐块把"原始 anchor 数（`fomc-meeting__date` 出现次数）"与"解析条数"对账 → 57 vs 55/54。
**修法**：月份 token 支持 `A/B`（决议月取**后一个**），标题写成 `FOMC Meeting - Jan 31-Feb 1, 2023`。
修后 57/57 与原始 anchor 逐一吻合。

### 5.3 🔴 红跑里 6 条"真空绿"（老坑新犯）→ 补前置合取项

首轮红跑（HEAD 副本，页与 API 都不存在）结果是 **9 FAIL / 7 PASS** —— 7 条 PASS 里只有
`TL-2c econ_events 表可查` 是真前置条件，其余 6 条全是**空集相等 / 无事可做**型真空绿
（DOM 0 条 vs API 0 条、两侧类型集都空、没有天就"无重复"、没有 pageerror 的 404 页……）。
**修法**：逐条补"前置状态存在"（`dom_ev >= 1`、`api_kinds` 非空、`dayCount >= 1`、`api["past"]` 非空、
`resp.status == 200`）⇒ 复跑红跑 **15 FAIL / 1 PASS**，唯一 PASS 就是那条前置条件。

### 5.4 🟡 两处显示细节（特写截图发现）

① 2026-07-02 的 `+0.0037%` 被渲染成**绿色 `+0.00%`** ⇒ `fmtPct`/`cls` 改成**按四舍五入后的方向**判色
（`|v| < 0.005` 不写符号、不染方向色）。② 未来事件也渲染「事件后 +1/3/5/10 日 待走满」（4 个"待走满"是噪声，
还容易被读成"数据缺"）⇒ 未来（含当日）**不显示** `事件后` 行。

## 6. 验证

| 项 | 结果 |
|---|---|
| V0 语法 | `node --check timeline.js` ✔ / `py_compile app.py·econ_calendar.py·timeline.py` ✔ |
| V1 后端单测 | `pytest tests/test_econ_calendar.py` **21 passed**；全量 `pytest tests/` **684 passed** |
| V2 落盘脚本实跑 | `--dry-run` 103 条 / 无失败源；正式落盘写入 103 条事件 + **13 条叙事**（0 失败） |
| V3 数据自洽 | db 独立核算（sqlite3 直查）= API `stats` = 页面 DOM：**past 21 / upcoming 8** 三方一致 |
| V4 **TL 组红跑**（`git archive HEAD` 隔离副本） | **15 FAIL / 1 PASS**（带完成标记、0 崩溃；唯一 PASS = 前置条件） |
| V5 **TL 组绿跑** | **16 PASS / 0 FAIL**（带完成标记） |
| V6 全量 | 见 §7（0 traceback、汇总行在；与当日基线比集合） |
| V7 视觉 | 双主题 × 1440 / 1280 / 375 截图留档；「即将到来」「已发生」「口径与来源」三块 + 「加载更早」实测 18→27→47 天（标签 近 90 天→1 年→3.3 年→10 年，无 pageerror） |
| V8 几何 | 375/768/1280/1920 四视口 `scrollWidth - innerWidth == 0`（TL-8） |

## 7. 全量结果

- 新增断言组后：**653 PASS / 0 FAIL（`ALL PASSED`）**，0 traceback ⇒ 跑完。
  `653 = 604（当日基线） + 33（QM） + 16（TL）`；**新增红 0**（与基线集合差为空）。
- `navCount` 由 11 → 12：`F-5` / `CN-7` 两处已同步（含注释说明为何是"断言脆弱"而非"方案不可行"）。

## 8. 遗留 / 交接（未做，已记录）

1. **P4（AR/CAR 事件研究法）**：plan §8 明确"单独立项评估"；要因子数据 + 新统计代码，本次不做。
2. **每日增量同步要挂到 cron 侧**（plan §6.3）：本轮的 `scripts/sync_econ_calendar.py` 需由仓库外的
   Hermes cron 每天调一次（`python -m scripts.sync_econ_calendar`）；**本轮未改任何 cron**（它不在仓库里）。
   在此之前，页面数据是**一次性快照**（103 条 + 13 条叙事）。
3. **`scripts/backtest.py` 同样受"沿用值"影响**（§5.1 末尾）：未改，待评估。
4. **镜像 2027+ 的日程几乎全被标为 CANCELLED** ⇒ 存活数据只到 2026-12-23（"即将到来"的可见深度
   未来约 3 个月）；Fed 侧 FOMC 到 2027-12。**这是源的实际覆盖，不是解析问题**（已写在页面的
   `#tl-scope` 与 `docs/frontend-structure.md`）。
5. 新闻热度是**检索口径**（单次上限 100 条）⇒ 页面上固定写「至少 N 篇」（plan §7-3）。

## 9. 提交清单（plan §12）

```
src/econ_calendar.py            （新）
src/timeline.py                 （新）
src/storage.py
scripts/sync_econ_calendar.py   （新）
web/app.py
web/templates/timeline.html     （新）
web/templates/_sidebar.html
web/static/timeline.js          （新）
web/static/style.css
tests/test_econ_calendar.py     （新）
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
docs/frontend-structure.md
docs/pitfalls.md                （超出 plan §12，AGENTS.md 要求沉淀规则）
docs/architecture.md            （同上）
tasks/2026-09-18-event-timeline-page/plan.md
tasks/2026-09-18-event-timeline-page/research.md
tasks/2026-09-18-event-timeline-page/journal.md
```

⚠️ 用 `git add <具体路径>`，**不用** `-A`。
⚠️ **不混入**：`docs/user-guide.md`（本日另一任务）、`data/`（由既有 cron 负责提交）。
