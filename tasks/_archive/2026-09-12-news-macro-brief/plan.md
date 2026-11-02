# 计划：最新资讯改造 —— 宏观/世界要闻「一句话新闻条」

- **日期**：2026-09-12
- **任务目录**：`tasks/2026-09-12-news-macro-brief/`
- **性质**：前端渲染改造 + 取数层搜索源切换（跨 5 个文件）
- **前置任务**：`2026-09-11-frontend-bento-redesign` ✅ / `2026-09-11-glassmorphism-fix` ✅ / `2026-09-12-glass-texture-tuning` ✅ / `2026-09-11-chart-hover-crosshair` ✅
- **并行冲突**：`2026-09-12-visual-fidelity`（也改 `app.js` / `style.css`）→ **必须串行**（见 R10）

---

## 1. 任务目标

把「最新资讯」卡片从**「标题 + 80 字碎片摘要」**改成**「每行一句话的宏观/世界要闻列表」**，并把搜索源从 A 股个股公告切换为**全球宏观 + 全球股市大事件**。

**已确认的决策（需求方 2026-09-12）**：

| 项 | 决策 |
|---|---|
| 显示形态 | **多行列表，每行一句话，不自动滚动，可手动滚动**（不做跑马灯/轮播动画） |
| 标题 | **不显示**；完整标题保留在 `<a title="...">` 原生 tooltip 里，信息不丢失 |
| 语言/源 | **中文国际新闻**（财联社 / 华尔街见闻 / 新浪财经等） |
| 内容范围 | **宏观 + 全球股市大事件**：央行政策与利率、CPI/非农等经济数据、地缘冲突、汇率与大宗商品；外加三大指数级别异动与系统性风险事件。**不含个股、不含公司财报** |
| 刷新时机 | **改完立刻手动刷一次 `data/news.json`**，当天就能看到新内容 |

---

## 2. 现状与根因（实测 + 代码取证）

### 2.1 渲染表现根因（用户实际看到什么）

`data/news.json`（`date=2026-09-12`，**3 条**）实际内容：

| # | title（加粗显示） | summary（2 行截断显示） |
|---|---|---|
| 1 | 操盘必读：影响股市利好或利空消息 | `捷荣技术公告，涉及AI液冷…比重极低。**11、ST萃华公告**，无法按期披露半年报，股票今起停牌。**12、香山股份公告**，拟…` |
| 2 | 今日股市最新消息 | `隔夜美股 美国8月CPI加速上涨 三大指数本周收跌 美油累涨近10% 周五，三大指数上涨…` |
| 3 | 美股 NFLX收购WBD利好利空？… | `美股 NFLX收购WBD利好利空？…30年国债收益率涨回200日均！**视野环球财经 315000 s…**` |

→ 用户看到的是「**加粗的门户栏目名 + 一段读不通的碎片**」：第 1 条塞了 3 家不同公司的公告，第 3 条尾巴上是 YouTube 频道名 + 播放量。`source` / `published` **三条全空**，所以来源行根本没渲染。

### 2.2 代码逻辑根因（为什么是现在这样）

| # | 机制根因 | 位置 |
|---|---|---|
| **N-G1** | **查询词决定了内容**：`"A股 美股 今日 重大新闻 政策 利好 利空"` 命中「利好利空」，Tavily 优先返回门户站的《操盘必读》栏目与个股公告合集 | `daily_report.py:163`（且 `f"..."` 前缀多余，无插值） |
| **N-G2** | **请求体无时效约束**：只有 `query / max_results=5 / search_depth=basic`，**没传 `topic` 与 `days`** → 通用搜索，不保证时效，能搜到拼盘旧文 | `src/news_fetcher.py:49-54` |
| **N-G3** | **摘要是硬截断，不是一句话**：`_clean_summary` 只是把 snippet 砍到 80 字，砍在哪算哪，**从不按句切分** | `src/news_saver.py:47-69` |
| **N-G4** | **`_is_junk` 只过滤 title，不检查 summary**：`save_news` 里只有 `if _is_junk(title): continue`。`JUNK_KEYWORDS` 里明明有「智通财经」「视野环球」，但只作用于标题 → 第 3 条 summary 的「视野环球 315000」因此残留 | `src/news_saver.py:16-26, 91-96` |
| **N-G5** | **前端无"取一句话"能力**：`renderNews` 直接输出 `title`（加粗 600）+ `summary`（2 行 clamp），把"标题"当成主信息 | `web/static/app.js:324-342` |
| **N-G6** | **`#news-body` 无高度约束**：与它并排的 `.alert-list` 有 `max-height:132px; overflow-y:auto`，而 news 侧完全没有 → **条数一多就撑高整个 `.row-news` 行** | `web/static/style.css:462`（有）vs `#news-body`（无规则） |

### 2.3 因果链

```text
[查询词 = A股/利好利空]  N-G1
      ↓
[Tavily 返回门户栏目 + 个股公告拼盘]  ← N-G2 无 topic/days，不保证时效
      ↓
[落盘：summary 硬砍 80 字，不切句]  N-G3
      ↓
[噪声残留：_is_junk 只查 title]  N-G4
      ↓
[前端：加粗标题 + 2 行碎片]  N-G5
      ↓
[用户看到：读不通的个股公告碎片]  ← 且 N-G6 让卡片高度随条数失控
```

**关键结论**：
1. 只做"隐藏标题"（纯前端）**会更糟** —— 剩下的 80 字碎片比加粗标题更难读。
2. **必须同时改查询词（治本）+ 加切句能力（治标）**，缺一不可。

---

## 3. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/news_fetcher.py` | **改** | 请求体加 `topic:"news"` + `days:2`；`max_results` 5 → 8 |
| `src/news_saver.py` | **改** | `_clean_summary` 加按句切分 + 尾部平台噪声剥离；`valid[:5]` → `[:8]` |
| `daily_report.py` | **改** | 查询词改宏观；提为模块级常量 `MACRO_NEWS_QUERY`；去掉多余 `f` 前缀 |
| `web/static/app.js` | **改** | `renderNews` 重写：不显示 title，新增 `oneLine()` 切句，整行 `<a>` 可点 |
| `web/static/style.css` | **改** | `.news-item` 改单行 ellipsis；**新增 `#news-body { max-height:132px; overflow-y:auto }`**；删 `.news-meta` / `.news-summary` |
| `tests/` | **增/改** | 切句函数单测 + `renderNews` 相关断言（若有） |
| `tasks/2026-09-12-news-macro-brief/plan.md` | 新增 | 本文件 |
| `tasks/2026-09-12-news-macro-brief/journal.md` | 新增 | 执行完成后写 |

**不改**：`web/app.py`（`_load_news` 的过滤契约不变）、`web/templates/index.html`（结构不变）、`src/analyzer.py` / `src/reporter.py`。

---

## 4. 实现步骤（每步可独立验证）

### N-0 · 备份与基线（必做，先做）

```text
cp data/news.json  $env:TEMP/news.backup.json     # 刷新前的唯一回滚点
venv/Scripts/python -m pytest tests/ -v            # 基线：459 passed
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # 基线：EXIT=0，scrollHeight=1216
```

⚠️ **架构师本轮未完成 `#news` 的 DOM 实测**（执行中被中断）。下面的判据以**代码 + 数据文件取证**为准。执行者必须在 N-0 **补齐三项测量**再动手：
- `#news` 卡片 `offsetHeight`、`#news-body` 的 `clientHeight / scrollHeight / overflowY`
- `.news-item` 单条高度、`#alerts` 卡片 `offsetHeight`（判断哪侧决定行高）
- 当前 `scrollHeight` 与 1240 的余量

### N-1 · 取数层：加时效参数

`src/news_fetcher.py:49-54`：

```text
payload = {
    "api_key": api_key,
    "query": query,
    "max_results": 8,        # 5 → 8（过滤后会淘汰，且多行列表更饱满）
    "search_depth": "basic",
    "topic": "news",         # ← 新增：新闻 topic，时效性更强
    "days": 2,               # ← 新增：只回溯近 2 天
}
```

**验证**（这一步必须实测，不能假设）：
```text
venv/Scripts/python -c "from src.news_fetcher import search_news; import json; print(json.dumps(search_news('美联储 通胀 地缘政治'), ensure_ascii=False)[:600])"
```
- 返回非空 → `topic`/`days` 被接受，继续。
- 返回 `[]` 且日志有 4xx → **该账号 API 版本不支持**，去掉 `topic`/`days` 两个键，仅保留 `max_results:8`，并在 journal 记录。

### N-2 · 落盘层：切句 + 去噪声

`src/news_saver.py`：

1. **`_clean_summary` 加按句切分**（在现有清洗**之后**、80 字截断之前）：
   - 按 `[。！？；\n]` 切分，取第一句
   - 若首句 < 12 字且存在第二句 → 拼接第二句（补回标点）
   - 总长截到 **60 字**（比前端的 42 宽，给前端留余量）

2. **尾部平台噪声剥离**（新增，补 N-G4）：
   - 新增 `TAIL_NOISE = ["智通财经", "视野环球", "鉅亨網", "美股股市新聞", "富途牛牛"]`
   - 对每个词：`idx = summary.rfind(kw)`，**仅当 `idx > len(summary) * 0.5`** 才截断到该位置
   - ⚠️ 为什么加 50% 门槛：`JUNK_KEYWORDS` 里的「东方财富」「同花顺」等可能出现在正文前段，无条件截断会**把整句砍没** → 只处理中后段噪声

3. **`valid = valid[:5]` → `valid[:8]`**（`news_saver.py:115`），与 N-1 的 `max_results` 保持一致

**验证**：`venv/Scripts/python -m pytest tests/ -v`（既有断言不应破）+ 跑一次 N-6 刷新后 `cat data/news.json` 目视 `summary` 是否已成单句。

### N-3 · 入口层：查询词改宏观

`daily_report.py`：

```text
# 模块级常量（便于 monkeypatch / 测试；勿硬编码进函数体）
MACRO_NEWS_QUERY = "美联储 通胀 就业数据 地缘政治 全球股市 异动 要闻"

# 第 163 行
news_results = search_news(MACRO_NEWS_QUERY)     # 去掉多余的 f 前缀
save_news(news_results, date)
```

⚠️ **不会破测试**：`tests/test_phase24.py:191` / `test_phase25.py:66` / `test_phase27.py:248` 都是 `lambda q: [...]` 形式，**不捕获也不断言 query 内容**。

**验证**：`venv/Scripts/python -m pytest tests/test_phase24.py tests/test_phase25.py tests/test_phase27.py -v`

### N-4 · 前端：只显示一句话

`web/static/app.js:324-342` 重写 `renderNews`，并新增辅助函数：

```text
// 取一句话：按句末标点切分 → 首句（过短则补第二句）→ 截到 42 字
function oneLine(s, fallback) {
  if (!s) return fallback || '';
  s = String(s).trim();
  var parts = s.split(/[。！？；!?;]/);
  var first = (parts[0] || '').trim();
  if (first.length < 12 && parts[1]) first = (first + '。' + parts[1]).trim();
  if (first.length > 42) first = first.slice(0, 41) + '…';
  return first || fallback || '';
}

// 渲染：整行就是一句话，标题只留在 tooltip
body.innerHTML = items.map(function (n) {
  var text = oneLine(n.summary, n.title);          // ← summary 空/太短则回退 title
  return '<div class="news-item">' +
    '<a href="' + escapeHtml(n.url) + '" target="_blank" rel="noopener noreferrer"' +
    ' title="' + escapeHtml(n.title) + '">' + escapeHtml(text) + '</a>' +
    '</div>';
}).join('');
```

三个要点：
1. **`oneLine(n.summary, n.title)` 的 fallback 是必须的** —— Tavily 的 `content` 可能为空，没有 fallback 会渲染出空行。
2. **`title` 属性保留完整标题** —— 用户 hover 仍能看到原标题，信息不丢失。
3. **顺手修 XSS 隐患**：原代码 `'<a href="' + n.url + '"'` **未转义**。`_load_news` 只校验了 `url.startswith("http")`（挡住了 `javascript:`），但 `"` 仍可突破属性边界 → 加 `escapeHtml(n.url)`。

**验证**：`curl http://localhost:<port>/api/news` 看 items；目视每行一句话。

### N-5 · 样式：单行省略 + 高度约束

`web/static/style.css`（替换现有 373-382 行的 `.news-*` 规则）：

```text
/* 新闻条：每行一句话；与 .alert-list 同高（132px），超出的部分手动滚动 */
#news-body { max-height: 132px; overflow-y: auto; }

.news-item { padding: 7px 0; border-bottom: 1px solid var(--border); }
.news-item:last-child { border-bottom: none; }
.news-item a {
  display: block; font-size: 13px; font-weight: 400;   /* ← 600 → 400，它不再是标题而是正文 */
  color: var(--text-secondary); text-decoration: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.news-item a:hover { color: var(--blue); }

/* 小屏放行 2 行：一行放不下时不要整句被省略号吞掉 */
@media (max-width: 768px) {
  .news-item a {
    white-space: normal; display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
  }
}
```

- **删除** `.news-meta` 与 `.news-summary` 两条规则（`source`/`published` 恒空，且 N-4 不再输出这些元素）—— 留着是死代码。
- **132px 不是随手选的**：`.alert-list` 就是 132px（`:462`）。两侧等高 → `.row-news` 行高稳定 → `scrollHeight` 不随新闻条数漂移。

**验证**：目视单行为主；8 条时出现滚动条；`scrollHeight` 仍 ≤1240。

### N-6 · 立刻刷新 news.json（需求方已确认要做）

```text
# 0) 备份（N-0 已做则跳过）
cp data/news.json $env:TEMP/news.backup.json

# 1) 只刷新资讯，不触发取数/报告/推送
venv/Scripts/python -c "from src.news_fetcher import search_news; from src.news_saver import save_news; save_news(search_news('美联储 通胀 就业数据 地缘政治 全球股市 异动 要闻'))"

# 2) 核对
curl http://localhost:<port>/api/news
```

- **`save_news` 无副作用**：只写 `data/news.json`（原子写 `tmp` + `os.replace`），不碰 `history` / `context` / `alerts` / `reports`。
- **失败是安全的**：无结果时 `save_news` 返回 `False` 且**不写盘** → 旧数据保留。
- ⚠️ **依赖 `TAVILY_API_KEY` 与网络**。失败就退回旧数据，并在 journal 记录原因，不要强行造数据。
- ⚠️ **风险**：若只搜回 1 条非垃圾结果，会把 3 条覆盖成 1 条 → 备份是唯一回滚点，务必先备份。

### N-7 · 断言与回归

在 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` **追加**（**只扩展，禁止覆盖** —— 该文件已 756 行，含 bento + 玻璃化 + 纹理 + crosshair 全部既有断言）：

| # | 断言 | 期望 |
|---|---|---|
| **N-1** | `#news` 内 `.news-item` 数 === `/api/news` 的 `items` 数（>0 时） | 相等 |
| **N-2** | 每个 `.news-item a` 的文本长度 | ≤ 43（含 `…`） |
| **N-3** | `.news-item` 内**不存在** `.news-meta` / `.news-summary` | 0 个 |
| **N-4** | `#news-body` 的 `overflowY === 'auto'` 且 `maxHeight === '132px'` | true |
| **N-5** | 每个 `.news-item a`：href 以 `http` 开头，且 `title` 属性非空 | true |
| **N-6** | 回归：`scrollHeight` @1920 ≤1240、`scrollWidth === innerWidth`、console error 0、backdrop 11/11 | 不变 |
| **N-7** | 接口层：`/api/news` 每条 `summary` 长度 ≤ 60（N-2 落盘切句生效） | true |

⚠️ **先红后绿**：改代码前先跑一次 N-1~N-5、N-7，确认**断言是红的**（否则说明断言写错了，等于没断言）。

### N-8 · 记录

- 写 `tasks/2026-09-12-news-macro-brief/journal.md`（含刷新前后的 `summary` 对比、Tavily 是否接受 `topic`/`days`、最终 query 有效性）。
- 追加 `docs/pitfalls.md`：
  1. 「摘要按句切分」—— 搜索引擎 snippet 硬截断会产生碎片，落盘层与展示层都要切句。
  2. 「`_is_junk` 只查 title 不查 summary」—— 噪声会从 summary 侧漏出。
  3. 「并排卡片的等高约束」—— 一侧有 `max-height`、另一侧没有时，行高会被无约束侧拖高，撑破总高护栏。

---

## 5. 验证命令（引自 `docs/commands.md`）

| 命令 | 用途 | 何时跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 单元测试 | N-0 基线 / N-2 / N-3 / 提交前 |
| `venv/Scripts/python -m uvicorn web.app:app --port 8018` | 启动看板（**换新端口**，防 CSS 缓存假阴性） | N-4 / N-5 / N-6 |
| `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **Web UI 验收（改动前端必跑）**：自动挑空闲端口，三视口断言，退出码 0=全通过 | N-0 基线 / N-7 |
| `curl http://localhost:<port>/api/news` | 资讯端点（`data/news.json` 只读） | N-4 / N-6 / N-7 |

---

## 6. 风险评估与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R1** | **只隐藏标题会更糟** | **高** | 80 字碎片比加粗标题更难读。**必须 N-3（换词）+ N-2/N-4（切句）同做**，缺一不可 |
| **R2** | `topic` / `days` 不被该 Tavily 账号支持 → 4xx | **中** | N-1 **必须实测**；失败则去掉两键，仅保留 `max_results:8`，并在 journal 记录 |
| **R3** | `max_results` 与 `valid[:5]` 不一致 | **中** | N-1 改 8、N-2 必须同步 `valid[:8]`，否则请求 8 条只存 5 条。两处是跨文件耦合 |
| **R4** | 刷新把 3 条覆盖成 1 条 | **中** | N-0 **先备份** `data/news.json`；`save_news` 无结果时不写盘（安全），但"1 条垃圾结果"会覆盖 |
| **R5** | `TAVILY_API_KEY` 缺失 / 断网 | **中** | `search_news` 返回 `[]` → `save_news` 返回 `False` 不写盘 → 旧数据保留。**不要**为了看到效果而伪造数据 |
| **R6** | 单行 ellipsis 在窄屏变成一整行省略号 | **中** | N-5 已加 `<768px` 放行 2 行；42 字上限也控制了这个风险 |
| **R7** | `summary` 为空 → 渲染空行 | **中** | N-4 的 `oneLine(n.summary, n.title)` **fallback 到 title** 是必须的 |
| **R8** | 切句把中文切碎 | **中** | 「首句 <12 字则补第二句」就是为此。但中文无空格分词，极限情况仍可能不理想 → N-6 刷新后**必须目视** 3-8 条的实际效果 |
| **R9** | `#news-body` 撑高破坏总高护栏 | **中** | `scrollHeight` 现为 1216，余量仅 24px。N-5 的 `max-height:132px` 是**必需项不是可选项** |
| **R10** | 与 `visual-fidelity` 任务并行改 `app.js` / `style.css` | **中** | **必须串行**。本任务改 `renderNews` + `.news-item`，对方改 `OVERVIEW_CARDS` + 品牌字 + 头像 + nav，区域不重叠但同文件 |
| **R11** | 查询词效果不达预期 | **低** | `MACRO_NEWS_QUERY` 提为常量就是为了便于调整。刷新后若仍是个股/栏目内容，**优先调 query** 而不是加过滤规则 |
| **R12** | 既有 XSS 隐患 | **低** | N-4 顺手给 `n.url` 加 `escapeHtml` |
| **R13** | auto-commit cron 抢先提交 | **低** | 外部「每日数据更新」cron 会 `git add -A`。临时截图/JSON 落 `$env:TEMP`，仓库内不留 |

---

## 7. 复现路径与关键测量点（UI 类必填）

### 7.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8018`（**换新端口** —— 同端口会命中陈旧 CSS 副本产生假阴性，`docs/pitfalls.md:200`）
3. 打开 `http://127.0.0.1:8018/`，硬刷新 `Ctrl+Shift+R`
4. 滚到底部，右侧「**最新资讯**」卡片（在 `.row-news` 的 2.4fr 列，与左侧「告警记录」并排）
5. **现状可观察**：3 条；每条 = 加粗标题一行 + 灰色摘要两行；第 1 条是多份公告拼接；第 3 条尾巴带「视野环球 315000」；卡片高度随手风琴无明显滚动
6. 刷新数据：`curl http://127.0.0.1:8018/api/news`

### 7.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| `#news` 卡片 `offsetHeight` | `document.querySelector('#news').offsetHeight` | 与 `#alerts` 等高（≤约 200px），**不随新闻条数漂移** |
| `#news-body` 的 `maxHeight` / `overflowY` | `getComputedStyle(...)` | `132px` / `auto` |
| `#news-body` 的 `clientHeight` vs `scrollHeight` | DOM 属性 | 3 条时 `scrollHeight ≤ clientHeight`（无滚动）；8 条时 `scrollHeight > clientHeight`（有滚动） |
| 单条 `.news-item` 高度 | `offsetHeight` | 约 30px（`padding 7+7` + 13px 行高） |
| `.news-item a` 文本长度 | `textContent.length` | ≤ 43 |
| `.news-item a` 的 `white-space` / `text-overflow` | `getComputedStyle` | `nowrap` / `ellipsis`（<768px 为 `normal` + `line-clamp:2`） |
| `.news-item a` 的 `font-weight` | `getComputedStyle` | `400`（原 600） |
| **回归：`scrollHeight` @1920×1080** | `document.documentElement.scrollHeight` | **≤1240**（基线 1216） |
| **回归：`scrollWidth === innerWidth`** | — | 必须 true |
| **回归：`console.error` 数** | — | **0** |

> ⚠️ **架构师未实测声明**：本方案 N-0 之前的 DOM 实测**未完成**（执行中被中断）。上表的 `#news` / `#alerts` 具体高度值以代码推演为准，**执行者必须在 N-0 先补齐测量**，若实测与推演不符（例如 `#news` 已超过 132px 很多，或两卡不等高），以实测为准并回头调整 N-5 的 `max-height`。

### 7.3 box-sizing 说明

`web/static/style.css:51` 仍为 `* { margin:0; padding:0; box-sizing:border-box }`，**全局 border-box，无例外**。对本任务的具体影响：

1. **`#news-body` 的 `max-height:132px` 在 border-box 下含 padding 与 border** —— 所以**不要**给 `#news-body` 加 padding/border，否则可视内容区会被压缩到 132px 以下，与 `.alert-list` 视觉上不等高。
2. **`.news-item` 的 `padding: 7px 0` 不影响宽度**（垂直 padding 在 border-box 下只增加高度），单行 ellipsis 的可用宽度 = 卡片内容宽，不受影响。
3. **`overflow-y: auto` 出现滚动条时会占用宽度**（Windows Chromium 约 15px）→ 单行文字的可用宽度减少，可能更早触发 ellipsis。这是可接受的轻微代价；若在意可加 `scrollbar-width: thin`。
4. **`-webkit-line-clamp` 与 `white-space: nowrap` 互斥**：小屏放行 2 行时必须把 `white-space` 改回 `normal`（N-5 已处理），否则 `nowrap` + `line-clamp` 组合下第二行不生效。
5. **`text-overflow: ellipsis` 生效的三个前提**：`white-space: nowrap` + `overflow: hidden` + 元素有确定宽度（`display: block` + 块级容器满足）。三者缺一不可 —— 这是"加了 ellipsis 却没效果"最常见的原因。

### 7.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | `.row-news` 为 `1fr 2.4fr`；news 卡约 1140px 宽，每行一句话**单行完整显示、无省略号**（42 字内）；8 条时 `#news-body` 出现纵向滚动条；`#news` 与 `#alerts` 等高；**`scrollHeight` 仍 ≤1240** |
| **1280×720** | `<1400px` 断点生效，`.row-news` 改单列堆叠（`style.css:502-504`），news 卡全宽约 1030px；单行更宽松；`scrollWidth === 1280`；两卡上下排列，高度各自独立 |
| **375×812** | 卡片单列；`<768px` 断点放行 2 行 `-webkit-line-clamp:2`，一句话不会被整行省略号吞掉；`scrollWidth === 375`；侧栏抽屉（z=60）与 `.nav-backdrop`（z=55）层叠不受影响 |
| **两主题** | `.news-item a` 用 `--text-secondary`，深色/浅色均已定义；hover 色 `--blue` 双主题可读；切换主题后目视复查文字对比度 |

---

## 8. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/app.js` | +约 20 / −10 行：`oneLine()` + `renderNews` 重写 |
| 修改 | `web/static/style.css` | +约 18 / −4 行：`#news-body` 高度约束 + `.news-item` 单行省略 + 小屏断点 |
| 修改 | `src/news_fetcher.py` | +2 行：`topic` / `days` / `max_results` |
| 修改 | `src/news_saver.py` | +约 18 / −2 行：切句逻辑 + 尾部噪声 + `[:5]`→`[:8]` |
| 修改 | `daily_report.py` | +2 / −1 行：`MACRO_NEWS_QUERY` 常量 + 调用替换 |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +约 30 行（N-1~N-7 断言） |
| 新增 | `tasks/2026-09-12-news-macro-brief/plan.md` | 本文件 |
| 新增 | `tasks/2026-09-12-news-macro-brief/journal.md` | 执行完成后写 |
| 新增 | `docs/pitfalls.md` 追加段 | 3 条（摘要须切句 / `_is_junk` 未覆盖 summary / 并排卡片等高约束） |
| 数据（生成物） | `data/news.json` | 被 N-6 覆盖（**先备份**） |

**净代码变更估算**：约 **+90 / −20 行**（不含测试与断言）。

---

## 9. 不做什么

- 不做跑马灯 / 轮播动画（需求方已明确选「多行列表不滚动」）。
- 不新增新闻源（Tavily 单源不变）。
- 不改 `web/app.py` 的 `_load_news` 过滤契约（仍要求 `title` 非空 + `url` 以 http 开头；title 是**过滤条件**，不是显示内容）。
- 不动 `data/news.json` 的所有权（仍归 Hermes，web 只读）。
- 不改 Hermes cron 的抓取频率。
- 不动玻璃化 / 纹理 / 布局栅格 / 断点 / crosshair 成果。

---

## 10. 确认

- [ ] 人已审阅本计划
- [ ] 已确认「只隐藏标题会更糟」，**换查询词 + 切句必须同做**（R1）
- [ ] 已确认 `#news-body { max-height:132px }` 是**必需项**（R9）
- [ ] 已确认 N-6 刷新前**先备份** `data/news.json`（R4）
- [ ] 已确认 N-1 的 `topic`/`days` **必须实测**，不支持则去掉（R2）
- [ ] 已确认本任务与 `2026-09-12-visual-fidelity` **串行**（R10）
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**（现 756 行）
- [ ] 已知悉**架构师未完成 `#news` DOM 实测**，执行者须在 N-0 补齐（§7.2）
- [ ] 已确认回归护栏（`scrollHeight ≤1240`、无横向溢出、0 console error）不得回退
