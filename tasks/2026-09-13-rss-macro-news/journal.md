# 执行日志 · 改用 RSS 双源供宏观新闻流

> 对应计划：`tasks/2026-09-13-rss-macro-news/plan.md`（299 行）
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）
> 执行顺序：R-0 → R-1 → R-2 → R-3 → R-4 → R-5 → R-6 → R-7

## 目标

需求方反馈「Tavily 显示的内容像从文章里截取的，看着不完整」。根因不是截断参数，而是**数据源形态不匹配**：搜索 API 返回「网页中含关键词的任意窗口」（碎片、常与标题无关），新闻流展示需要「编辑写好的、自含上下文的句子」。故**链路 B（新闻流）改用 RSS 双源**，**链路 A（个股归因）保留 Tavily**。

## R-0 · 基线

```
venv/Scripts/python -m pytest tests/ -q          → 531 passed
verify_ui.py                                      → ALL PASSED / scrollH@1920 = 1220
备份：%TEMP%\news.backup.20260913.json
```
（plan 写「基线 459 passed」为早期数字，实际已 531。）

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| **`src/rss_fetcher.py`** | **新建**（约 230 行） | 双源 RSS 拉取/解析（stdlib `ElementTree`）、`_strip_html`、`_split_source`（双层后缀）、`_drop_trailing_source`、标题/URL 归一化去重、宏观白名单、交错合并、日期倒序 |
| `daily_report.py` | +8 / −2 | 新增 `from src.rss_fetcher import fetch_macro_news`；资讯块改「RSS 主源 → 空则降级 Tavily」 |
| `src/news_saver.py` | +3 | `_clean_summary` 开头加 `re.sub(r'<[^>]+>', ' ', summary)` 兜底剥 HTML |
| `tests/test_rss_fetcher.py` | **新建**（17 条） | 纯函数 / XML 解析 / 单源失败 / 双源全败 / 去重 / 白名单 / 上限 / `_is_junk` 防误杀 / 与 `save_news` 契约 |
| `data/news.json` | 生成物 | R-4 真跑覆盖（已先备份） |
| `docs/pitfalls.md` | +6 条 | 见 R-7 |
| `tasks/2026-09-13-rss-macro-news/journal.md` | 新增 | 本文件 |

**未改**：`src/news_fetcher.py`（链路 A 不动）、`web/static/app.js`、`web/static/style.css`、`web/app.py`。

## R-1 · 源实测

| 源 | HTTP | 条数 | 形态 |
|---|---|---|---|
| 华尔街见闻 `dedicated.wallstreetcn.com/rss.xml` | 200 | **55** | 编辑级标题 + `description` = **全文**（实测 1000~4100 字，含 HTML）→ 首句天然自含 |
| Google News 中文检索 | 200 | **100** | 各媒体原标题（` - 媒体名`）+ `description` = 标题复述 + 媒体名（非摘要）|

**最终配置**（模块常量，可调）：
```python
RSS_MACRO_QUERY    = "美联储 OR 通胀 OR 央行 OR 地缘政治 OR 全球股市"
PER_FEED_CAP       = 12    # 单源合并前上限
MAX_SOURCE_SUFFIX  = 2     # 标题后缀最多剥两层
MACRO_FILTER_ENABLED = True
```
**宏观白名单**（仅作用于华尔街见闻侧，25 词）：美联储/央行/欧洲央行/日本央行/通胀/CPI/PPI/非农/就业/利率/加息/降息/衰退/地缘/关税/原油/黄金/汇率/美元/美债/PMI/GDP/制裁/全球市场/股市/指数/经济。

> ⚠️ **R2 未触发**：白名单过滤后华尔街见闻侧仍有 ~20 条（≥3 条阈值），未放宽、未关闭。

## R-2 · `news_saver`

- 已在 `_clean_summary` 开头加 HTML 兜底剥离（防御：换 feed 时漏清洗也不至于把 `<p style=…>` 落盘）。
- **`valid[:5] → [:8]` 无需改**：代码里早已是 `valid[:8]`（plan 依据的是旧版）。

## R-3 · 接线

```python
try:
    news_results = fetch_macro_news()            # RSS 主源
    if not news_results:
        log.info("RSS 无结果，降级 Tavily 备源")
        news_results = search_news(MACRO_NEWS_QUERY)
    save_news(news_results, date)
except Exception as exc:
    log.warning("资讯落盘失败，跳过: %s", exc)
```

## R-4 · 落盘验证（**核心验收**）

真跑（**只跑资讯链路**，不动 history/context —— 今天是周日，跑 `daily_report.py` 会 append 非交易日工件）：
```text
venv/Scripts/python -c "from src.rss_fetcher import fetch_macro_news as f; from src.news_saver import save_news as s; s(f())"
→ fetched 8 / saved True
```

**逐条判读 `data/news.json`（8 条，全部 2026-09-12）**：

| # | source | title | summary |
|---|---|---|---|
| 1 | 华尔街见闻 | 石油市场已达“转折点”？ | 全球原油市场正站在一个关键节点上 |
| 2 | 华尔街见闻 | 高盛也“改口”了：下周美联储会加息！ | 高盛也“改口”了：下周美联储会加息 |
| 3 | 华尔街见闻 | 高盛最新判断：利率上升≠美股下跌，盈利增长才是牛市关键 | 华尔街正被“高息恐慌”笼罩，30年期美债收益率飙升至5.3%的近20年高点，10年期逼近5% |
| 4 | 金十数据 | 美国8月核心CPI月率意外高于预期！美联储下周加息概率逼近90% | 美国8月核心CPI月率意外高于预期 |
| 5 | 华尔街见闻 | 高盛TMT大会第三天：黄仁勋回击“循环融资”质疑——“投1块拿回100块？那就多来点” | 人工智能基础设施投资浪潮正在提速，而非降温 |
| 6 | 中国日报网 | 加息预期升温，美联储的难题为何不止利率？ | 加息预期升温，美联储的难题为何不止利率 |
| 7 | 华尔街见闻 | 交易员警惕线上移：10年期美债收益率破6%，才是个人投资组合的真正红线 | 十年期美债收益率在消化CPI数据后已从5%附近关口回落，但最新调查显示，交易员愿意等到收益率突破6%甚至更高，才会着手调整个人持仓 |
| 8 | 东方财富 | 美联储陷入“死局”：加息没用？但也得加！ | 美联储陷入“死局”：加息没用 |

对照 plan §R-4 清单：

| 判据 | 结果 |
|---|---|
| 无「标题讲 A、摘要讲 B」话题错配 | ✅ 8/8 同题（对比：Tavily 版 8 条里 2 条完全无关） |
| 无「在欧洲…」「该行进一步…」缺上文碎片 | ✅ 全部自含 |
| `source` 不再恒空 | ✅ 4 个来源（华尔街见闻 / 金十数据 / 中国日报网 / 东方财富） |
| ≥6/8 条独立可读完整句 | ✅ **8/8** |
| 主题为宏观/世界要闻 | ✅ 全部美联储/CPI/美债/原油 |

## R-5 · 前端复核（**判定为无需改动**）

- **plan 的「42 字上限」已过时**：`app.js` 现为 `NEWS_MAX_LEN = 120` + 单行横向滚动（`overflow-x:auto`，不再用省略号吞字），`verify_ui` 的 N-2 口径是 **≤121**。
- 实测 8 条 summary 长度 `[16, 17, 46, 17, 21, 19, 65, 14]` → 超 42 的仅 **2/8**、超 50 的 **1/8** → **不构成「普遍截断」**，按 plan 的分支判定**不改** `app.js`（前端零改动）。
- plan §R-5 要求的断言（文本长度上限 / `title` 属性非空 / `scrollH ≤1240` / `scrollWidth === innerWidth` / console error 0）**已由既有 N-2 / N-5 / N-10 / F-6a / P-7 覆盖**，重复新增只会造成双份维护 → 不新增。

`verify_ui.py` 终跑：**ALL PASSED**（N-1「DOM `.news-item` 数 == `/api/news` items 数」= 8 == 8；N-7 summary ≤120；三视口无横溢；console error 0）。

## R-6 · 测试

```
venv/Scripts/python -m pytest tests/test_rss_fetcher.py -v   → 17 passed
venv/Scripts/python -m pytest tests/ -q                      → 548 passed
```
（531 基线 + 17 新增；`test_phase24/25/27` 全绿 —— `search_news` 语义未变，链路 A 零影响。）

用例覆盖：`_strip_html` / `_split_source`（含双层与单字符不剥）/ `_drop_trailing_source` / `_norm_key`·`_norm_url` / `_to_date` / `fetch_rss` 解析（无 link 跳过）/ 坏 XML / 网络异常 / 双源交错合并 / 白名单过滤 / 跨源去重 / 单源失败 / 双源全败 → `[]` / 条数上限 / **`_is_junk` 防误杀** / 与 `save_news` 的落盘契约。

## 遇到的问题（含实现期自我修正）

1. **双源合并初版「8 条全来自华尔街见闻」**（首跑实测：`[华尔街见闻×8]`）——顺序拼接 + 按日期稳定排序让第一源独吞名额，与「双源都接」（决策 C）相反。改为**单源各取上限后交错合并**（`A0,B0,A1,B1…`），复跑得到 5+3 双源混合。
2. **`_split_source` 我先改成「只剥一层」，结果退化**：真实样本 `美国8月核心CPI月率意外高于预期！…90%-市场参考 - 金十数据` 是**双层后缀**（内层是文章标题自带站名）→ 单层剥离会把 `-市场参考` 留在标题里（tooltip/回退文本都脏）。改回「最多剥两层 + `source` 只记最外层」。
3. **Google 侧摘要会残留媒体名**：`description` 形态 `标题&nbsp;&nbsp;<font>来源</font>`；标题带 `！`/`？` 时切句正好切掉来源，**不带句末标点时就会漏进摘要**（`美国8月CPI超预期 东方财富`）。新增 `_drop_trailing_source`（按已知来源名精确剥尾部），不再依赖标点运气。
4. **两处失败用例是我自己写错的期望**（`_split_source("标题 - A - B")`：单字符不满足 ≥2 字下限；`http` vs `https` 本就不等价）→ 修正期望而非改实现。

## 与 plan 的偏差

| # | 项 | 说明 |
|---|---|---|
| **D1** | `PER_FEED_CAP` + 交错合并 | plan 伪代码只写「两源合并 → 去重 → 前 8 条」，照做会让第一源独吞（见问题 1）。新增两个常量（`PER_FEED_CAP=12`、`MAX_SOURCE_SUFFIX=2`）。 |
| **D2** | 新增 `_drop_trailing_source` | plan 只提 `_split_source`；实测 Google 摘要尾部媒体名会漏出（问题 3）。属「来源剥离」的同一意图。 |
| **D3** | R-2 的 `valid[:5]→[:8]` 未改 | 代码早已是 `[:8]`，plan 依据旧版。 |
| **D4** | R-5 **零改动**，且**未新增断言** | plan 的 42 字口径过时（现 120+横滚）；实测截断不普遍；要求的断言已被既有 N/F/P 覆盖。 |
| **D5** | R-4 未跑 `daily_report.py` 全链路 | plan 允许「或手动调 `fetch_macro_news`」。今天周日，跑完整日报会 append 非交易日 history/context 工件（已知坑）→ 只跑资讯链路。 |
| **D6** | `RSS_MACRO_QUERY` 采用 plan 字面值 | 未做 A/B（plan 未要求）；实测 8 条主题全部命中宏观，暂无需调词。 |

## R-7 · 记录

- 本 journal。
- `docs/pitfalls.md` 追加「模块 src/rss_fetcher.py（RSS 宏观新闻流，2026-09-13）」6 条：搜索 snippet ≠ 新闻摘要 / `_is_junk` 与标题后缀 / 双层后缀必须剥净 / 双源合并必须交错 / Google 摘要尾部媒体名 / **文档参数可能过时先读代码**。

## 下次注意

- **「内容不完整」类反馈先问「是不是源形态不对」**，再去调截断参数：搜索 API 给的是正文窗口，展示型新闻流必须用 RSS/新闻 API。
- **多源合并默认要交错**：只要下游有「取前 N 条」，顺序拼接就等于只有一个源。
- **来源后缀剥离要做在 fetcher 侧**（`_is_junk` 是下游，误杀不可逆），且要按实测样本的**层数**来剥。
- **plan 里的前端数值（字号/字数上限/断点）可能已漂移**，动手前先 grep 代码与既有断言。
- 本地真跑一律 `AUTO_PUSH=0`；验证只跑必要链路，避免周日产生非交易日工件。
