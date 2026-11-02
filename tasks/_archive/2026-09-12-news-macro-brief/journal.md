# 执行日志 · 最新资讯改造（宏观/世界要闻「一句话新闻条」）

> 对应计划：`tasks/2026-09-12-news-macro-brief/plan.md`（391 行）
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）
> 执行顺序：**N-7 断言先行（先红后绿）** → N-1 → N-2 → N-3 → N-4 → N-5 → N-6 → N-8

## 会话记录

### 2026-09-12 · N-0 ~ N-8 全部执行

**目标**：把「最新资讯」从「加粗标题 + 80 字碎片摘要」改成**每行一句话的宏观/世界要闻列表**，并把搜索源从 A 股个股公告切换为**全球宏观 + 全球股市大事件**。

### N-0 · 备份与基线

- 备份：`%TEMP%\news.backup.json`（SHA256 `481BFAD7…`，刷新前唯一回滚点）
- 基线：`pytest tests/ -q` → **514 passed**；`verify_ui.py` → 断言 1~12 全绿

**⚠️ N-0 补齐的三项 DOM 实测（架构师未完成，plan §7.2/§N-0 要求）——发现基线已破护栏**：

```
1920 页面总高 ≤ 1240  (actual = 1257)      ← 已经超标 17px（非本任务引入）
#news=232  #alerts=232  itemH=57  #news-body client=169 scroll=169  maxH=none  ovf=visible
a weight=600  whiteSpace=normal  textOverflow=clip
```

- **根因**：资讯卡（3 条 × 57px + h2 + padding = 232）成为 `.row-news` 行高的决定方（告警侧被 `max-height:132px` 裁住 = 193）→ 行高 195 → **232**，总高 1216 → **1257**。这正是 plan N-G6/R9 预言的机制，且在**基线就已发生**（并发任务加的资讯卡所致，非本任务引入）。
- **结论**：本任务的 **N-5（`#news-body{max-height:132px}`）同时是「内容改造」与「护栏修复」**。

### N-1 · 取数层加时效参数（**实测通过**，plan R2 的降级分支未触发）

`src/news_fetcher.py` payload：`max_results: 5→8` + **`topic:"news"`** + **`days:2`**。
实测 `search_news('美联储 通胀 地缘政治')` → 返回 3 条、`published_date` 有值、**无 4xx** → 两键被账号接受，保留。

### 查询词 A/B 实测（plan R11 授权调词；数据驱动，不猜）

| query | 条数 | 内容 |
|---|---|---|
| `美联储 通胀 就业数据 地缘政治 全球股市 异动 要闻`（plan 定稿） | **3** | 其中 **2 条同一标的**（纽元/美元）+ 1 条汇率 |
| `美联储 利率决议 通胀数据 非农 地缘冲突 美股 异动` | **1** | 黄金，过窄 |
| **`全球市场要闻 美联储 欧洲央行 通胀 地缘政治 原油 股市`（采用）** | **8** | 全球市场早餐 / 油价+美联储欧央行 / 地缘风险+通胀 / 全球市场脆弱 / 美股休市油价狂飙 / 欧央行加息 / 德银警告 / 日元异动 —— 全部命中 plan §1 范围，无个股、无重复标的 |

→ `MACRO_NEWS_QUERY` 采用第三版（A/B 结论已写入 `daily_report.py` 注释）。

### N-2 · 落盘层：切句 + 去噪声 + `[:8]`

`src/news_saver.py` 新增/修改：

| 项 | 内容 |
|---|---|
| `_first_sentence()` | 按 `[。！？；!?;\n]` 取首句；首句 < `MIN_FIRST_SENTENCE=12` 字且存在第二句 → 拼接（补回句号） |
| `_strip_tail_noise()` | `TAIL_NOISE = ["智通财经","视野环球","鉅亨網","美股股市新聞","富途牛牛"]`；**仅当 `idx > len(text) * 0.5`** 才截断（不加门槛会砍掉正文前段的机构名） |
| `_clean_summary()` | 在原有清洗**之后**：去脚注标记 `\[\d+(?:\.\d+)*\]` → 尾部噪声 → 切句 → 再剥一次噪声 → 截到 `MAX_SUMMARY_LEN = 60`（截断放最后，否则「…」计入长度） |
| 落盘上限 | `valid[:5]` → **`valid[:8]`**（与 `max_results:8` 配套，plan R3 的跨文件耦合）；`summary[:80]` → `[:MAX_SUMMARY_LEN]` |

### N-3 · 入口层：查询词提为模块级常量

`daily_report.py`：新增 `MACRO_NEWS_QUERY`（含 A/B 记录注释）；L163 `search_news(MACRO_NEWS_QUERY)`（去掉多余的 `f` 前缀）。
既有测试不破：`test_phase24/25/27` 都是 `lambda q: [...]`，不捕获 query 内容（已实测 529 passed）。

### N-4 · 前端：只显示一句话（+ XSS 修复）

`web/static/app.js`：新增 `oneLine(summary, fallback)`（切句 → 首句 <12 字补第二句 → **一律**截 42 字，**回退路径也截断**）；`renderNews` 重写为「整行 `<a>`」，不输出 `title` / `.news-meta` / `.news-summary`，完整标题进 `title` 属性（tooltip 保信息）。
**顺手修 XSS 隐患**：`n.url` 未转义 → 改 `escapeHtml(n.url)`（`_load_news` 只挡了 `javascript:`，`"` 仍可突破属性边界）。

### N-5 · 样式：单行省略 + 高度约束

`web/static/style.css`：新增 **`#news-body { max-height:132px; overflow-y:auto }`**（与 `.alert-list` 同值）；`.news-item` padding 6→7px；`.news-item a` `font-weight 600→400`、`display:block` + `nowrap/overflow:hidden/text-overflow:ellipsis`；新增 `<768px` 放行 2 行（`white-space:normal` + `-webkit-line-clamp:2`）；**删除** `.news-meta` / `.news-summary`（死代码）。

### N-6 · 刷新 `data/news.json`（需求方已确认执行）

- 首次刷新（plan 原词）：3 条、切句生效、噪声已清，但 2 条同一标的（见 A/B 表）→ 调词后重刷
- **最终刷新：8 条**（`save_news -> True`），`summary` 长度 `[60,60,60,14,27,56,57,60]`
- 内容样例：`美国8月消费者通胀同比持稳于3.4%，而核心CPI环比上涨0.3%，同比放缓至2.4%，使得下周美联储的利率决议备受关注` / `美股周二收跌，标普500指数下滑0.58%至7673.52点…` / `数据公布后，市场重新定价美联储加息预期，利率市场押注美联储9月加息的概率超过70%…`

### N-7 · 断言（先红 → 后绿）

在既有 `verify_ui.py` 上**只扩展不覆盖**（该文件当时已 851 行），新增 `NEWS_JS` + `assert_news()`（N-1~N-10）。

**基线（改代码前）**：`FAILED` 中含 **6 条 N 断言红** —— N-2（maxLen 50>43）、N-3（`.news-summary` 3 个）、N-4（`maxHeight none` / `ovf visible`）、N-5（3 个 `<a>` 无 `title`）、N-7（`sumLens=[80,80,80]`）、N-8（`weight 600`）；N-1/N-9/N-10 绿（N-1 是条数一致性校验，与 G-1 的 1b 同性质）→ **先红后绿成立**。

**最终（全绿）**：

```
api items=8  sumLens=[60,60,60,14,27,56,57,60]  | dom items=8  maxLen=42
#news=195  #alerts=195  itemH=34  body client=132 scroll=270  maxH=132px  ovf=auto
a weight=400  whiteSpace=nowrap  textOverflow=ellipsis  |  scrollH = 1220
```

| 判据 | 目标 | 实测 |
|---|---|---|
| N-1 DOM 条数 == /api/news 条数 | 相等 | **8 == 8** |
| N-2 每行 ≤43 字 | ≤43 | **42** |
| N-3 无 `.news-meta`/`.news-summary` | 0 | **0 / 0** |
| N-4 `max-height`/`overflow-y` | `132px`/`auto` | **`132px`/`auto`**（`scroll 270 > client 132` → 8 条时出现滚动条，符合"可手动滚动"） |
| N-5 href/title | 全部合法且非空 | **0 违规** |
| N-7 落盘 summary ≤60 | ≤60 | **全部 ≤60** |
| N-8 字重 | 400 | **400** |
| N-10 `#news` 与 `#alerts` 等高 | ±2px | **195 == 195** |
| **回归** `scrollHeight`@1920 | ≤1240 | **1220**（基线 **1257** → 修复并回落到护栏内） |
| **回归** 三视口无溢出 / console / backdrop 全覆盖 / 玻璃判据 | 不变 | **全 PASS**（`verify_ui.py` 退出码 0） |
| `pytest tests/ -q` | 全绿 | **529 passed**（514 + 新增 15 条 `test_news_saver.py`） |

### N-8 · 记录

- 本 journal；`docs/pitfalls.md` 追加「模块 src/news_*」段（7 条：snippet 须切句 / `_is_junk` 只查 title / 首尾元数据与脚注 / 查询词须 A/B / `topic+days` 会减条数 / **并排卡等高约束** / `max_results` 与落盘上限跨文件耦合）。
- **未提交**（按纪律等需求方确认）：见文末「待确认」。

---

## 与 plan 的偏差 / 待确认

| # | 项 | 说明 |
|---|---|---|
| **D1** | `MACRO_NEWS_QUERY` 采用 **第三版**词（非 plan 字面值） | plan R11 明确授权「优先调 query」；基于 3 词 A/B 实测（3 / 1 / 8 条）。A/B 结论已写入 `daily_report.py` 注释 |
| **D2** | `_clean_summary` **额外**去掉了脚注标记 `[1]`/`[1.3.3]` | plan N-2 未提；实测截断后留下半截中括号（`…30% […`）属明显碎片，按「补 N-G4 噪声残留」意图处理 |
| **D3** | ⚠️ **未修**：snippet 首尾「发布时间/栏目名」元数据碎片 | 实测残留：`10 9月 2026, 09:13 情报报告称…`（首部）、`…揭开背后线索 09-09 08:22 9月9日财经早餐：…`（尾部）。plan 未覆盖（`TAIL_NOISE` 是关键词表，不匹配这类格式）；**需需求方确认是否追加模式清理**（约 3 行 regex，会再触发一次刷新） |
| **D4** | `itemH` 实测 **34px**（plan §7.2 预测 ~30px） | 差异来自 `.news-item` padding 按 plan N-5 取 7px（13px 行高 + 14px padding + 1px 边框 ≈ 33~34）→ 无需调整，已如实记录 |
| **D5** | `topic:news + days:2` 下 `max_results:8` 只回 3 条（plan 原词） | 属 Tavily 侧匹配度限制（今天周六、近 2 天新闻少）；**不**通过调大 `max_results` 解决，改词后已回满 8 条 |
| **D6** | 未新增 `data/news.json` 之外的取数源 | 遵 plan §9「不新增新闻源」 |

## 下次注意

- **并排卡片的高度约束必须成对加**：本次基线 1257 的破护栏就是"只给 `.alert-list` 加了 `max-height`、`#news-body` 没有"造成的；加约束时先看同排另一侧有没有。
- **改 `news_fetcher.max_results` 必须同步 `news_saver` 的落盘上限**（两处跨文件耦合，静默丢数据）。
- **切句能力要落两层**（落盘 60 字 + 展示 42 字）：只在展示层切会让长文本在窄屏反复截断，只落盘切则前端无法兜底。
- **断言先行**（N-7 先红后绿）这次又直接抓出 6 处待改点，且暴露了基线已有的护栏破损 —— 顺序不要反过来。
- 外部 auto-commit cron 仍会 `git add -A` 抢提交；临时产物一律落 `$env:TEMP`（本次备份在 `%TEMP%\news.backup.json`）。
