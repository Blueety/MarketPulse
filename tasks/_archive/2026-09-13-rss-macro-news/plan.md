# 计划：改用 RSS 双源（华尔街见闻 + Google News）供宏观新闻流

- **日期**：2026-09-13
- **任务目录**：`tasks/2026-09-13-rss-macro-news/`
- **触发**：需求方反馈「Tavily 显示的内容像从文章里截取的，看着不完整」
- **决策**：需求方选 **C（两个源都接）**

---

## 1. 结论先行

**根因不是截断参数，是数据源形态不匹配。** Tavily 返回的是「网页中**含关键词的任意窗口**」，天然碎片且与标题无关；新闻流展示需要「**编辑写好的、自含上下文的句子**」。这两者是不同产品形态，调参修不好。

**方案：新闻流链路（B）改用 RSS，个股归因链路（A）保留 Tavily。**

| 链路 | 源 | 理由 |
|---|---|---|
| **A · 个股归因**（`daily_report.py:91`） | **Tavily 保留** | 按 symbol 精确搜；消费方是 Hermes/AI，碎片可接受；RSS 干不了 |
| **B · 新闻流展示**（`daily_report.py:168`） | **RSS 替换** | 直接给用户看，必须编辑级完整句子 |

**GDELT / Eulerpool 放弃**（GDELT 实测成功率 ~1/10 且无摘要；Eulerpool Key 未验证）。

---

## 2. 根因：实测证据

当前 `data/news.json`（8 条）逐条核对：

| # | title | summary | 问题 |
|---|---|---|---|
| 2 | 油价与柴油价格上涨搅动全球市场（**油价**） | 情报报告称西方退役特种兵可能在保加利亚训练俄军（**俄军**） | **话题完全无关** |
| 3 | 全球市场进入脆弱阶段 | 在欧洲，债务发行也比往常提前 | **"在欧洲"缺上文** |
| 5 | 炮火与代码的狂舞 | 中国方面，央行连续22个月增持黄金 | **"中国方面"缺上文** |
| 6 | 欧洲央行年内第二次加息 | 数据公布后，市场重新定价… | **"数据公布后"不知指什么数据** |
| 7 | 通胀与利率预期严重错位？德银警告 | 该行进一步表示，欧洲央行也面临… | **"该行"无先行词** |
| 8 | 欧元多头寄望欧洲央行（**欧元**） | 日元突然狂飙7%（**日元**） | **话题不匹配** |

→ 8 条里 6 条有缺陷。这是 **Tavily snippet 的结构性特征**（搜索引擎返回"命中词的正文窗口"），不是清洗逻辑能修的。

**架构师自我修正**：昨日我判定「Tavily 已验证产出高质量中文宏观新闻」—— 从**主题对不对**（宏观 vs 个股）看成立，但从**句子是否自含可读**看**不成立**。本任务补上后者。

---

## 3. 数据源实测（本轮亲自跑的）

| 源 | HTTP | 条数 | title | description | 链接 |
|---|---|---|---|---|---|
| **华尔街见闻** `dedicated.wallstreetcn.com/rss.xml` | 200 | **55** | 编辑写的完整标题 | **全文带 HTML**（~4800 字） | **原文直链** ✅ |
| **Google News 中文检索** `news.google.com/rss/search?q=…` | 200 | **100** | **各媒体原标题**（财联社/东方财富/新浪） | ❌ 是 Google 跳转 HTML，非摘要 | ⚠️ 经 Google 跳转 |
| 新浪财经滚动 | 200 | **0** | — | — | ❌ 已停更 |
| Reuters top | **401** | 0 | — | — | ❌ 需授权 |

Google News 真实返回（**正是需求要的形态**）：

```text
美国中期选举还剩7周，国内通胀毫无缓和，美联储9月加息几成定局 - 新浪新闻
美联储下周会否加息？今明两天，两份重磅通胀报告将定调 - 财联社
美国8月通胀数据提升美联储加息预期 国际金价不跌反涨 - 东方财富
```

华尔街见闻 description 的真实开头（**文章导语，天然自含**）：

```text
全球原油市场正站在一个关键节点上。库存加速去化、中国需求强势回归、中东…
华尔街正被“高息恐慌”笼罩，30年期美债收益率飙升至5.3%的近20年…
```

**关键洞察**：文章**开头**是自含的，中间片段不是。Tavily 给"命中词的窗口"（可能在中间），RSS description 给"文章开头"（必定自含）。这直接解决需求方的抱怨。

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| **`src/rss_fetcher.py`** | **新建** | RSS 拉取 + 解析 + HTML 清洗 + 去重 + 统一格式 |
| `daily_report.py` | 改 ~8 行 | `:168` 改调 `fetch_macro_news()`，失败降级 Tavily |
| `src/news_saver.py` | 改 ~6 行 | `_clean_summary` 前置 HTML 剥离（防御）；`valid[:5]`→`[:8]` |
| `src/news_fetcher.py` | **不动** | 链路 A 继续用它 |
| `web/static/app.js` | **原则上不动** | `oneLine(summary, title)` 已兼容；仅当需调 42 字上限才动 |
| `web/static/style.css` | **不动** | — |
| **`tests/test_rss_fetcher.py`** | **新建** | 解析/降级/去重/清洗/白名单 |
| `tasks/2026-09-13-rss-macro-news/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 | 2 条 |

---

## 5. 实现步骤（每步可独立验证）

### R-0 · 基线

```text
venv/Scripts/python -m pytest tests/ -v                                       # 基线 459 passed
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py     # EXIT=0，scrollH@1920=1220
cp data/news.json $env:TEMP/news.backup.json                                  # 回滚点
```

### R-1 · 新建 `src/rss_fetcher.py`

**零新增依赖**：用 `xml.etree.ElementTree`（stdlib）+ `html.unescape` + `re`。

```text
RSS_FEEDS = [
  {"name": "wallstreetcn", "url": "https://dedicated.wallstreetcn.com/rss.xml"},
  {"name": "google_news",  "url": GOOGLE_NEWS_TMPL.format(q=RSS_MACRO_QUERY)},
]
GOOGLE_NEWS_TMPL = "https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
RSS_MACRO_QUERY  = "美联储 OR 通胀 OR 央行 OR 地缘政治 OR 全球股市"   # 可配置，需实测调
```

核心函数（伪代码，只描述契约）：

```text
def _strip_html(s):                      # 华尔街见闻 description 带 <p style=…>
    re.sub(r'<[^>]+>', ' ', s) → html.unescape → 压空白 → strip

def _split_source(title):                # ★ 必须做，见 R-1 说明
    匹配尾部 " - XXX" / " | XXX" → 返回 (纯净标题, 来源)

def fetch_rss(url, timeout=10):          # ElementTree 解析 <item>
    → [{"title","snippet","link","date","source"}]

def fetch_macro_news(timeout=10):        # 两源合并
    逐源 try/except（单源失败不中断）→ HTML 清洗 → 来源剥离
    → 宏观白名单过滤（华尔街见闻侧）→ 去重 → 返回前 8 条
```

**★ `_split_source` 为什么必须做**：`_is_junk` 的 JUNK_KEYWORDS 含「东方财富」「同花顺」「雪球」「腾讯证券」「智通财经」「鉅亨網」。Google News 标题普遍带 ` - 东方财富` 这类后缀 —— **若不先把后缀剥离，这些标题会被 `_is_junk` 整条过滤掉**。而现有 `_clean_title`（`news_saver.py:85`）只硬编码了 7 个后缀，**「 - 财联社」「 - 新浪新闻」不在其中**，会带着来源名进标题。

→ 在 **fetcher 侧**剥离（不动 `news_saver`，blast radius 最小），把来源名填进 `source` 字段（该字段目前恒为空，顺带修复）。

**去重**：标题归一化（去标点空白、全角转半角、小写）后判等；URL 归一化后判等。两源命中同一条时保留 `source` 更明确的那条。

**宏观白名单**（华尔街见闻侧，默认开启、可配置）：
`美联储 / 央行 / 欧洲央行 / 通胀 / CPI / PPI / 非农 / 就业 / 利率 / 加息 / 降息 / 衰退 / 地缘 / 关税 / 原油 / 黄金 / 汇率 / 美元 / 美债 / PMI / GDP / 制裁 / 全球市场`
⚠️ 若实测过滤后条数 < 3，放宽或关闭白名单（记入 journal）。

**统一输出格式**（与 `_make_result` 兼容，`save_news` 可直接吃）：
`{"title": str, "snippet": str, "link": str, "date": str, "source": str}`

### R-2 · `_clean_summary` 前置 HTML 剥离（防御）

`news_saver.py:_clean_summary` 开头加一步 `re.sub(r'<[^>]+>', ' ', summary)`。

⚠️ 即使 R-1 已清洗也要加：防止将来换 feed 时漏清洗，且 `save_news` 是唯一落盘口，在此兜底最稳。

`valid[:5]` → `valid[:8]`（双源合并后条数更充裕，前端 `#news-body` 已限高 132px 可滚动）。

### R-3 · `daily_report.py` 接线 + 降级

```text
# :168 附近
try:
    news_results = fetch_macro_news()                 # RSS 主源
    if not news_results:
        news_results = search_news(MACRO_NEWS_QUERY)  # Tavily 备源
    save_news(news_results, date)
except Exception as exc:
    log.warning("资讯落盘失败，跳过: %s", exc)
```

⚠️ **保留 Tavily 备源**：RSS 挂了不至于让新闻卡全空。

### R-4 · 落盘验证（**这一步是核心验收**）

```text
AUTO_PUSH=0 venv/Scripts/python daily_report.py       # 只跑资讯链路，或手动调 fetch_macro_news
```

**逐条人工判读 `data/news.json`**，对照 §2 的缺陷清单：

- [ ] 不再出现「标题讲 A、摘要讲 B」的话题不匹配
- [ ] 不再出现「在欧洲…」「该行进一步…」这类缺上文的碎片
- [ ] `source` 字段不再恒空
- [ ] 至少 6/8 条是**独立可读的完整句子**
- [ ] 主题确为宏观/世界要闻（非个股公告）

若不满足 → 优先调 `RSS_MACRO_QUERY` 与白名单，而不是加清洗规则。

### R-5 · 前端复核（预期零改动）

`oneLine(n.summary, n.title)` 的兼容路径：

| 源 | summary | 前端实际显示 |
|---|---|---|
| Google News | 空 | → **fallback 到 title**（编辑写的完整标题）✅ |
| 华尔街见闻 | 清洗后的导语首句 | → 摘要 ✅ |

**唯一可能要调的**：42 字上限。若实测一句话普遍被截断（目视出现 `…`），提到 **50**（`#news-body` 限高 132px + 单行 ellipsis，改字数不改变高度，**不触发 scrollHeight 护栏**）。

断言（追加到 `verify_ui.py`，**只扩展不覆盖**）：
- `.news-item a` 文本长度 ≤ 43（若改 50 则 ≤51）
- 每条 `title` 属性非空（完整标题仍在 tooltip）
- 回归：`scrollH@1920 ≤1240`、`scrollWidth === innerWidth`、console error 0

### R-6 · 测试

`tests/test_rss_fetcher.py`（用 XML 夹具，不联网）：

| 用例 | 期望 |
|---|---|
| 正常解析 RSS XML | 统一格式，字段齐全 |
| `_strip_html` | `<p style=…>` 被剥离 |
| `_split_source` | ` - 东方财富` 被剥离且进 `source`（**关键：防 `_is_junk` 误杀**）|
| 单源失败 | 另一源仍返回结果 |
| 两源都失败 | 返回 `[]` → 降级 Tavily |
| 去重 | 两源同一条只保留一条 |
| 宏观白名单 | 非宏观条目被过滤 |
| 回归 | `test_phase24/25/27` 全绿（`search_news` 语义未变）|

### R-7 · 记录

- `tasks/2026-09-13-rss-macro-news/journal.md`：R-4 判读结果 + 最终 query / 白名单配置。
- `docs/pitfalls.md` 追加：
  1. **搜索引擎 snippet ≠ 新闻摘要**：前者是"正文命中窗口"（碎片、与标题无关），后者需"编辑写好的自含句"。展示型新闻流必须用 RSS/新闻 API，不要用搜索 API。
  2. **`_is_junk` 与标题后缀的相互作用**：标题里的来源名（`- 东方财富`）会触发 JUNK 过滤，必须先剥离后缀再判 junk。

---

## 6. 验证命令（引自 `docs/commands.md`）

```text
venv/Scripts/python -m pytest tests/ -v
venv/Scripts/python -m pytest tests/test_rss_fetcher.py -v
AUTO_PUSH=0 venv/Scripts/python daily_report.py
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
curl http://localhost:<port>/api/news
```

⚠️ 本地跑 `daily_report.py` **一律 `AUTO_PUSH=0`**。

---

## 7. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **`_is_junk` 误杀带来源后缀的标题** | **高** | R-1 的 `_split_source` 是必需项；测试专门覆盖 |
| **R2** | 华尔街见闻宏观白名单过滤过狠 → 条数不足 | **中** | 实测条数 <3 则放宽/关闭；记入 journal |
| **R3** | Google News 链接是 Google 跳转 | **中** | 本机有 Clash 可用；**若部署到无代理环境会失效** —— 需确认运行环境 |
| **R4** | RSS 源停更/改版（新浪已是 0 条） | **中** | 保留 Tavily 备源；R-4 落盘验证能第一时间发现 |
| **R5** | 华尔街见闻 description 是全文（4800 字） | **低** | `fetcher` 侧清洗 + `_clean_summary` 兜底，双重保障 |
| **R6** | `pubDate` 为 RFC822 格式 | **低** | 用 `email.utils.parsedate_to_datetime`（stdlib）转 `YYYY-MM-DD` |
| **R7** | 前端 42 字截断 | **低** | 目视；必要时提到 50（不改变高度，不触发护栏）|
| **R8** | auto-commit cron 抢先提交 | **低** | 临时产物落 `$env:TEMP` |
| **R9** | 真跑 daily_report 触发 push | **低** | 一律 `AUTO_PUSH=0` |

---

## 8. UI 验收（本任务前端改动极小，此处为复核项）

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | `.row-news`=195、`#alerts`=195、`#news`=195 不变；新闻每行一句话、单行无省略号（或仅个别超长截断）；`scrollH ≤1240` |
| **1280×720** | `.row-news` 单列堆叠；单行仍够宽；`scrollWidth === 1280` |
| **375×812** | `<768px` 放行 2 行；无横向溢出 |
| **双主题** | 文字色沿用现有 token，无新增 |

**box-sizing**：全局 `border-box`，本任务不改盒模型；改 42→50 字只改 JS 截断长度，**不影响任何尺寸**。

---

## 9. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 新建 | `src/rss_fetcher.py` | 约 140 行 |
| 新建 | `tests/test_rss_fetcher.py` | 约 130 行 |
| 修改 | `daily_report.py` | +约 8 / −2 行 |
| 修改 | `src/news_saver.py` | +约 6 / −1 行 |
| 修改（可能） | `web/static/app.js` | 0~1 行（42→50，仅当实测需要） |
| 修改（扩展） | `verify_ui.py` | +约 12 行 |
| 新增 | `tasks/2026-09-13-rss-macro-news/plan.md` / `journal.md` | 本文件 / R-4 判读 |
| 追加 | `docs/pitfalls.md` | 2 条 |

**净代码变更估算**：约 **+300 行**（其中测试 130）。

---

## 10. 不做什么

- 不动链路 A（个股归因，Tavily 保留）。
- 不接 GDELT / Eulerpool（实测不可行 / 未验证）。
- 不引入 `feedparser` 等新依赖（用 stdlib `ElementTree`）。
- 不改 `save_news` 的输出契约与前端渲染结构。
- 不改 `#news-body` 的 132px 限高（已与 `.alert-list` 对齐，护栏已守）。

---

## 11. 确认

- [ ] 已确认根因是**数据源形态不匹配**，不是截断参数
- [ ] 已确认链路 A 保留 Tavily、链路 B 换 RSS
- [ ] 已确认 `_split_source` 是**必需项**（防 `_is_junk` 误杀，R1）
- [ ] 已确认保留 Tavily 作为降级备源
- [ ] 已知悉 **Google News 链接依赖代理**（R3），需确认运行环境
- [ ] 已确认 R-4 需**人工逐条判读**新闻质量（这是本任务的核心验收）
- [ ] 已确认本地跑 `daily_report.py` 一律 `AUTO_PUSH=0`
