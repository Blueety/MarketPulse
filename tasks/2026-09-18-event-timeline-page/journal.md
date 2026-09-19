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

---

## 10. 追加（2026-09-19 00:2x）：用户可见名改为「市场日历」，并接手同名占位项

**用户指令**：「把这个页面换到市场日历那边，名字就叫 市场日历」。

**背景（用户提问"这个和市场日历有什么区别"引出的）**：侧栏「市场日历」是 2026-09-12
效果图复刻时留下的**占位项**（当时裁定见 `tasks/2026-09-12-visual-fidelity/plan.md` §12 Q1：
"删掉真实内容的导航入口是损失，造死链接是缺陷，占位是折中"）——**无定义、不可点**。
而 `plan.md` §6.2 只规定了新项放「告警记录」之后，**没说旧占位怎么办**，于是出现"一个灰占位 + 一个可用页"
并存的重复感。用户裁定：**占位删掉、这一项搬到它的位置、名字改成「市场日历」**。

**改动（全部只动"用户可见的名字与位置"）**：

| 文件 | 改动 |
|---|---|
| `web/templates/_sidebar.html` | 删除 `is-disabled` 的「市场日历」占位；把 `/timeline` 项**移到位（中国宏观之后 / 设置之前）**、标签 `事件时间线` → **`市场日历`** |
| `web/templates/timeline.html` | `<title>` 与 `<h1>` → **市场日历** |
| `verify_ui.py` | `F-5`：`navCount` 12→**11**、`navDisabled` 2→**1**（注释写明 12→11 的原因）；`CN-7`：11；**`TL-9`：active == 「市场日历」** |
| `docs/frontend-structure.md` | §1 速览页名、§2 文件清单角色、§3.4 侧栏 11 项清单与断言数字、§3.5 标题加"接手同名占位项"说明、§8 占位表只剩「设置」 |
| `web/static/style.css` | V5 占位注释：原三占位中两个已被 `/macro`、`/timeline` 接手，只剩「设置」 |

**保持不变的内部命名（有意为之）**：路由 `/timeline`、`timeline.js`、`#tl-*` 类名、`TL-*` 断言、
`econ_events` / `econ_event_news` 表、任务目录名 —— 改名只发生在**用户可见层**，避免为一次文案变更
翻动 380 行 JS 与 16 条断言。

**验证**：TL 组复跑 **16 PASS / 0 FAIL**（`TL-9 侧栏 11 项且本页 active = 市场日历`）；
本地页面 `title / h1 / active` 三处均为「市场日历」，侧栏 11 项顺序
`… 告警记录 | 宏观数据 | 中国宏观 | 市场日历 | 设置(占位)`；全量见 §11。

## 11. 全量（改名后）

见本轮运行日志：`ALL PASSED`（0 traceback、汇总行在）。`navCount`/`navDisabled`/`TL-9`
三处判据已同步，无新增红。

**仍未做（用户未指示）**：URL 仍是 `/timeline`（名字叫「市场日历」但地址是 timeline）。
若要把地址也改成 `/calendar`，需要新增路由（+保留 `/timeline` 兼容）并同步 `verify_ui` 里
所有 `url + "timeline"` 的引用与 docs —— 属独立小改动，等用户点头。

## 12. 全量首轮红了一条（B-6b）—— 定位为**断言侧竞态**并加固

改名后首次全量：**652 PASS / 1 FAIL**，唯一红条 = `B-6b 回绕后继续前进（循环未停住）`
（`actual=(-1, 0, 424)`、`回绕采样 period=777 first=0 last=424 drops=[]`）。

**排查（按纪律做 A/B，不靠猜）**：

1. `wrap_js` 的逻辑是"先把 scrollTop 顶到周期 − 2px，再采样找回绕"。`first=0` ⇒ **预置位没生效**。
2. 隔离副本 A/B（`git archive HEAD`，含 timeline 但**未含改名**）同一断言 **3/3 通过**（`first=777`）；
   工作区（已改名）**1/3 通过** ⇒ 确实与本次改动**有相关性**。
3. 把"加载后静默期"从 1.5s 拉到 5s ⇒ 工作区 **3/3 通过**。
4. 读 `app.js`：页面 TTL 刷新会重建 ticker DOM，而 `renderAlerts/renderNews` 里都有 `body.scrollTop = 0`
   ⇒ **预置位会被页面自己的一次重渲染冲掉**。改名让侧栏少一行（页面高度变），恰好把那次刷新的落点
   推进了断言窗口。**功能本身没坏**（周期 777、速率都一致；线上/本地 ticker 正常滚动）。

**修法（修在探针侧，判据一条没放松）**：`wrap_js` 改为**验证预置生效 + 可重试**
（起始帧未落到位则重新预置，最多 20 帧且不计入样本），并返回 `armTries` 供诊断。
**验证**：主动注入"采样前归零"模拟重渲染 ⇒ **修前必红、修后 `armTries=1` 且通过**（强制竞态 2 轮全过）；
原条件（1.5s）复跑 3/3 通过。已写入 `docs/pitfalls.md`。

> 教训归类：这是**断言脆弱**（harness 的预置位与页面异步任务竞争），不是产品缺陷 ——
> 与 pitfalls「先分清方案不可行 vs 断言脆弱」同一条纪律：**补强判据/修 harness，而不是删断言或调宽阈值**。

## 13. 追加（2026-09-19 01:0x）：事件名中文化

**用户指令**：「我想把事件名称改成中文的，英文看不懂」。

**做法（服务端生成 + 原文不丢）**：

| 层 | 改动 |
|---|---|
| `src/econ_calendar.py` | 新增 `zh_title()` / `_period_zh()` / `_stage_zh()` / `_fomc_span_zh()` / `_month_en()`：按「类型 + 数据期 + 估计阶段」**模板生成**中文名，**只翻译结构、不翻译内容**，零机器翻译、零编造 |
| `src/timeline.py` | payload 每条事件加 `title_zh`（页面主显），`title`（源站英文）**保留** |
| `web/static/timeline.js` | 主显 `title_zh`；英文原文挂 `data-title-en` + `title=`（悬停可见） |
| `verify_ui.py` | 新增 **TL-10**（API `title_zh` 非空且含中文 + 页面标题无英文骨架词）与 **TL-10b**（DOM `data-title-en` == API `title`，**原文不丢**） |
| `tests/test_econ_calendar.py` | 新增 6 条：8 类全枚举、无数据期不猜、跨年带年份、`其他` 不译、无控制字符回归、payload 双字段 |

**成果样例**（真实库数据）：`美国 8 月 CPI（消费者物价指数）` / `美国 9 月非农就业报告` /
`美国 2026 年 Q2 GDP 终值` / `美国 8 月零售销售（初值）` / `美联储议息会议（9 月 15-16 日）`。

**过程中修掉的三个问题**（都在"只翻译结构"这条纪律下）：

1. **FOMC 会期只解析出 3/57** —— `_month_en` 只认全名月份，而源站日期段全是缩写（`Sep 15-16`）。
   补缩写匹配后 57/57（含跨月 `Jan 31-Feb 1` 与单日 `Aug 22`）。
2. **语序与空格**：初版产出 `美国 CPI（消费者物价指数） 8 月`、`美国 工业产出…`、`美国8 月非农就业报告`。
   统一规则：**「美国」与「数据期」后是否加空格，只看下半截是否是拉丁字母/数字**。
3. 🔴 **正则的 B 边界在"经 shell heredoc 打补丁"时退化成了不可见的退格符（0x08）** ⇒ 数据期解析
   **静默失效**（标题里月份全丢，而编译/单测骨架都正常）。改用零反斜杠转义写法
   （`[^A-Za-z]` / `[ ]` / `[.]`）并加"标题不得含控制字符"的回归单测；教训写入 `docs/pitfalls.md`。

**未做（有意）**：`其他` 类不猜中文名（原样英文，避免误译）；源标题无数据期时不拿发布日期顶替；
**新闻标题不翻译**（Google News 检索原文，翻译即二次加工）。

**验证**：单测 27 条（`tests/` 全量 **690 passed**）；TL 组红跑（先写断言）→ 绿跑
**18 PASS / 0 FAIL**；全量见 §14。

## 14. 追加（2026-09-19 11:2x）：给 cron 的提示词 + 修掉"自动推送其实一直没推上去"

**用户要求**：「给我调整 cron 的提示词」。

### 14.1 🔴 起因：端到端验证时发现自动 push 是坏的

为写提示词先做端到端验证，结果 `scripts/sync_econ_calendar.py` 落盘后自动推送**失败**：

```
[master 4e65474] auto: 2026-09-19 econ-calendar
fatal: could not read Username for 'https://github.com': terminal prompts disabled
[auto-push] Failed: Command '['git','push','origin','master']' returned non-zero exit status 128
```

**根因（两个姿势今天同时失效，得分开看）**：

| 姿势 | 结果 |
|---|---|
| 直连（无代理） | ❌ `Failed to connect to github.com:443 after 21120 ms` —— **昨天还通，今天不通** |
| 代理 7890 + 默认凭据助手（`git_ops._push` 的现有姿势） | ❌ 网络通、**凭据取不到**（PortableGit `helper-selector` → GCM 在非交互子进程里阻塞/失败） |
| 代理 7890 + `gh` 凭据助手 | ✅ `279936d..4e65474  master -> master` |

⚠️ **影响面**：`daily_report` / `snapshot_report` / `opening_analyzer` / 新 synс **四个入口的 push 全都在失败**
（提交只落本地）。远端之所以一直是最新的，**只是因为人工推送把本地提交顺带带上去了** —— 这是典型的
"红得不明显"，靠日志才会发现。

### 14.2 修法（`src/git_ops.py`，最小改动 + 兜底）

`_push` 改为**两级尝试**：① 现有姿势（代理 + 默认凭据助手）→ ② 失败则用 `gh` 凭据助手重试
（`-c credential.helper=` 先清空再设 `!<gh 绝对路径> auth git-credential`；路径**必须加引号**，
含空格的 `C:/Program Files/GitHub CLI/gh.exe` 不加引号会被 sh 切断）。找不到 `gh` → 保持原行为（原样抛）。
**契约变化**：第一次 push 失败、兜底成功 ⇒ `auto_commit_push` 现在返回 **True**（原为 False）——
既有用例 `test_push_failure_calledprocess` 因此变红，按"保住原意图"改：fixture 改用 `"push" in args`
识别 push（旧写法 `args[:2] == ["git","push"]` 认不出兜底那次 `git -c … push` ⇒ 会**假绿**），
并新增 `test_push_fallback_rescues_after_first_failure` 钉住新契约。

### 14.3 `scripts/sync_econ_calendar.py` 自带提交（与另三个入口同口径）

新增 `--no-push`；默认在落盘后调用 `git_ops.auto_commit_push(today, "econ-calendar")`
（路径白名单 `data/context/alerts`、消息 `auto: {date} econ-calendar`）。**cron 侧因此只需一条命令。**

### 14.4 cron 提示词（可直接粘贴）

```text
【任务】同步 MarketPulse 经济事件日历（Fed FOMC 官方页 + 第三方镜像 .ics）与新闻叙事层，并发布到线上。

【工作目录】D:\AGENT\MarketPulse

【执行】venv\Scripts\python -m scripts.sync_econ_calendar

脚本流程：抓两源 → 归一化/去重 → upsert 进 data/marketpulse.db（表 econ_events / econ_event_news）
→ 抓最近 45 天"已发生"事件的 Google News 叙事层 → 自动 commit+push（触发 Railway 重部署）。

【判据】stdout 三段必须都看：
  1) [1/3] 抓取：事件 N 条（正常 100~110；失败源应为「无」）
  2) [news] 写入 M 条（正常 5~20）
  3) [git] 自动提交推送：应为「已提交并推送」或「未提交（无改动 …）」
退出码：0=正常；1=有源失败（脚本保留既有数据、仍会提交）；2=两源全失败（未写库、未提交）

【异常判定与处置】
  - 出现 [git] 未提交 且伴随 [auto-push] Failed ⇒ 推送没成功（线上仍是旧数据）。
    先等下一次运行重试；连续两次都失败再通知我，不要自行改动仓库。
  - 退出码 2（两源全失败）⇒ 立刻通知我（Fed 页与镜像同时不可用意味着数据源出了结构性问题）。
  - 事件条数骤降（如 <50）或出现「其他」类型暴增 ⇒ 通知我（多半是源改名，归一化没覆盖）。

【禁止】不要 git add 源码/文档/测试（本任务只产 data/）；不要跑 verify_ui.py；不要改任何代码或配置；
        不要手动删库或清表。

【回报（≤5 行）】时间 / [1/3] 事件 N 条（失败源）/ [news] M 条 / [git] 提交推送结果 / 异常与处置
```

**建议频率**：每天一次即可（日历是月度/年度级变动；新闻按天抓）。北京时间 **09:00** 跑一次可覆盖
"前一日美股事件 + 当天排定日程"；若想当天美盘数据（08:30 ET = 20:30 北京）当天就带上叙事层，
再加一次 **23:30**。**同日重复运行是幂等的**（事件按 `(date,kind,source)`、新闻按 `(date,kind)` upsert）。
