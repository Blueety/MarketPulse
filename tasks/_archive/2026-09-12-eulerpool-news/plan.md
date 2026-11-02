# 计划：Eulerpool 新闻源接入（含 PRD 事实更正）

- **日期**：2026-09-12
- **任务目录**：`tasks/2026-09-12-eulerpool-news/`
- **输入**：`Eulerpool News Agency 集成 Handoff`（外部撰写）
- **架构师职责**：比对 PRD 与真实代码 → 更正事实错误 → 解决设计冲突 → 出可落地方案

---

## 1. 结论先行

**PRD 的技术方向可以接，但它对当前代码有 4 处事实性错误、1 个不成立的核心前提。照 PRD 直做会改错文件、并推翻刚验收的中文宏观新闻成果。**

| 判定 | 内容 |
|---|---|
| ❌ **PRD 前提不成立** | 「新闻写入 `context.json` 供 Hermes 归因」—— **`context.json` 里根本没有 news 字段**。Hermes 读的是 `search_keywords` |
| ❌ **4 处事实错误** | 文件归属、函数位置、测试文件、落点全错（见 §2） |
| ⚠️ **1 个严重设计冲突** | `search_news` 有两个语义相反的调用点，统一路由会同时污染它们（见 §3） |
| ⚠️ **会推翻既有成果** | 中文宏观查询词刚验收产出高质量结果，切英文源会回退（见 §4） |
| ✅ **建议做法** | **配置化旁路 + Gate 0 阻塞验证**：先证伪再动手，主/备可 env 切换，不碰已验收链路 |

**核心建议：不要让 Eulerpool 成为主源，先做成「可一键开关的旁路」。** 理由见 §4.3（该源的不确定性远高于 PRD 描述）。

---

## 2. PRD 的 4 处事实性错误（实测更正）

| # | PRD 说法 | 实测结果 |
|---|---|---|
| **E1** | `src/news_fetcher.py` **新建** | **已存在**：Tavily 单源，已有 `search_news(query: str, timeout: int = 10)`、`main()` CLI、`.env` 读取链 |
| **E2** | `analyzer.py` 中 `generate_context()` 调用 Tavily | `generate_context` 在 **`src/reporter.py:937`**（不在 analyzer.py）。且它**不调 Tavily** —— 只调 `build_search_keywords(date, breaches, sector_heat)`（`:981`）**生成关键词**，搜索发生在别处 |
| **E3** | 修改 `tests/test_analyzer.py` 更新 mock | 搜索调用点在 **`daily_report.py`**，对应测试是 `tests/test_phase24.py:191` / `test_phase25.py:66` / `test_phase27.py:248`（均为 `lambda q: [...]` 形式） |
| **E4** | 「`context.json` 中新闻数据的字段格式」 | context 实际键：`date, indices, history_30d, breach, sector_heat, us_sector_heat, search_keywords, correlation, watchlist`。**无 `news` 键** |

### 2.1 新闻的真实落点（PRD 未识别到）

```
daily_report.py:91   search_news(f"{label} {symbol} {direction} 新闻")     ← 个股归因（中文）
        ↓ st["news"]
reporter.py:248-250  f"- 📰 **{label} ({symbol})**：{news}"                 ← 落进日报 watchlist 段

daily_report.py:168  search_news(MACRO_NEWS_QUERY)                          ← 宏观新闻
        ↓ save_news()
data/news.json       → web/app.py:/api/news → 前端「最新资讯」卡片
```

**两条链路的查询语言、目标、消费方完全不同。**

### 2.2 Hermes 实际怎么拿到"归因素材"

```
analyzer.py:228  build_search_keywords(date, breaches, sector_heat)
        ↓ 产出如 "通信/电子 drop 2026-09-11 | 军工 drop 2026-09-11 | ..."
reporter.py:981  context["search_keywords"] = ...
        ↓
Hermes 读 context.json 的 search_keywords → 自己决定怎么搜
```

→ **Hermes 消费的是「关键词」，不是「新闻正文」。** PRD 想做的「把 Eulerpool 新闻塞进 context 供 Hermes 归因」**当前没有落点**。

---

## 3. 设计冲突：`search_news` 有两个语义相反的调用点

| 调用点 | 查询串 | 语义 | 消费方 |
|---|---|---|---|
| **A** `daily_report.py:91` | `f"{label} {symbol} {direction} 新闻"` → 如「苹果 AAPL 大涨 新闻」 | **个股归因**，中文，含 symbol | 日报 watchlist 段 |
| **B** `daily_report.py:168` | `MACRO_NEWS_QUERY` = `"美联储 通胀 就业数据 地缘政治 全球股市 异动 要闻"` | **宏观新闻**，中文 | `data/news.json` → 前端 |

**PRD 的方案（把 `search_news` 改成统一的多源路由）会让 A、B 同时走 Eulerpool，两个都会坏**：

1. **A 会坏**：Eulerpool 端点是 `research/news/{ticker}`，**按股票代码检索**。把「苹果 AAPL 大涨 新闻」整串塞进 `{ticker}` 位 → 404 或空。
2. **B 会坏**：Eulerpool 是全球财经社（英文为主）。用**中文**关键词查**英文**库 → 大概率空或无关。

→ **必须拆分，不能统一路由。**

---

## 4. 与既有决策的冲突

### 4.1 中文源决策刚验收

`news-macro-brief` 任务（本日刚完成）把查询词从 `"A股 美股 今日 重大新闻 政策 利好 利空"` 换成 `MACRO_NEWS_QUERY`（中文），刷新后产出：

```text
新西兰元兑美元下跌，主要是由于新西兰联储与美联储之间的货币政策预期分歧进一步扩大…
中国进口需求令人失望：中国最新的贸易帐数据显示，8月进口同比增长28.2%，不及市场预期…
市场的焦点明确指向本周即将发布的两组重量级数据：周四的PPI和周五的CPI…
```

**质量已被验证。** 把主源换成英文的 Eulerpool，等于推翻刚验收的成果。

### 4.2 前端「最新资讯」已按中文排版

`oneLine()` 截 42 字、单行 ellipsis、`<768px` 放行 2 行 —— 都是按**中文**单行可容纳的字数设计的。英文一句话普遍更长，会大面积触发省略号。

### 4.3 Eulerpool 的不确定性远高于 PRD 描述

| 不确定项 | 状况 |
|---|---|
| **端点形态** | 官方文档在 Cloudflare 人机验证后，**无法从外部证实**；PRD 自己也标注「通用搜索端点未明确」 |
| **是否支持关键词/类别** | 未证实。`research/news/{ticker}` 是 **ticker 维度**，不是关键词搜索 |
| **Key 有效性** | PRD 引社区反馈「可能返回 not authorized」 |
| **额度** | PRD 自述「10 万 / 1 万 / 1000 三种说法」，未定 |
| **公开 RSS** | 实测 `https://eulerpool.com/news/feed.xml` **10 秒超时**，未取到内容 |
| **语言** | 未证实是否覆盖中文 |

→ **在以上任一项被证实前，不应让它成为主源。**

---

## 5. 建议方案

### 5.1 三条原则

1. **先证伪再动手**：Gate 0 拿不到有效结果就**停在这里**，不写业务代码。
2. **可配置、可一键关闭**：主/备顺序走 env，改顺序不需要改代码、不需要重新部署逻辑。
3. **不碰已验收链路 B**：Eulerpool 若接入，只走**新增的独立链路**或在链路 A 上做增强。

### 5.2 形态：配置化旁路（而非改 `search_news` 语义）

**不要**把现有 `search_news(query, timeout)` 改造成多源路由（会同时污染 A、B）。改为：

```text
# 新增：显式命名的源函数，各自独立、可单独测试
search_eulerpool(query, timeout)      # 新增，只处理英文/ticker 场景
search_tavily(query, timeout)         # 现有 search_news 改名/包一层

# 新增：显式编排（只有调用方明确要求时才走多源）
search_news_multi(query, sources, timeout)

# 保留：现有 search_news 语义不变（仍是 Tavily 单源），A/B 两个调用点零改动
search_news(query, timeout)           # ← 不动
```

**源顺序配置化**：

```text
# .env / config.json
NEWS_SOURCE_ORDER=eulerpool,tavily    # 默认 tavily（保守）；验证通过后再手动切
```

⚠️ **默认值必须是 `tavily`** —— 新 Key 缺失或失效时零影响（PRD 的「向后兼容」约束）。

### 5.3 Eulerpool 的正确定位（按验证结果分叉）

| Gate 0 验证结果 | 定位 |
|---|---|
| **只有 ticker 维度**（无关键词搜索） | ❌ **不能做宏观源**。只能用于**链路 A 的增强**：用 `symbol` 查 Eulerpool 拿英文个股新闻，与 Tavily 中文结果并列 |
| **支持关键词 + 有宏观类别** | ✅ 可作为**英文宏观补充源**，走**新增链路**写 `data/news_en.json`（与中文 `news.json` 并存，前端暂不消费或后续加 tab） |
| **Key 无效 / 端点不通** | ❌ **停止接入**，保留 `search_eulerpool` 空实现 + 跳过逻辑，等 Key 修复后再启用 |

**⚠️ 无论哪种结果，都不改链路 B（中文宏观）的主源。**

---

## 6. 要改的文件列表（更正 PRD）

| 文件 | 动作 | PRD 说的 | 更正说明 |
|---|---|---|---|
| `src/news_fetcher.py` | **修改**（非新建） | ❌ 新建 | 已存在；新增 `search_eulerpool` / `search_news_multi`，**保留** `search_news` 语义 |
| `daily_report.py` | **改 0~1 处** | ❌ 未提 | 真正的调用点在这里（`:91` 链路 A、`:168` 链路 B）。**链路 B 不动** |
| `src/reporter.py` | **不动** | ❌ 说改 `analyzer.py` | `generate_context` 在这里，但**它不调搜索**，无需改 |
| `src/analyzer.py` | **不动** | ❌ 说改它 | 只有 `build_search_keywords`（`:228`），与新闻源无关 |
| `.env.example` | 修改 | ✅ | 增加 `EULERPOOL_API_KEY` + `NEWS_SOURCE_ORDER` |
| `requirements.txt` | **不改** | ❌ 说加 `eulerpool` | `requests==2.34.2` 已在，**不引入 SDK** |
| `tests/test_news_fetcher.py` | 新建 | ✅ | 多源降级逻辑测试 |
| `tests/test_phase24/25/27.py` | **可能微调** | ❌ 说改 `test_analyzer.py` | 仅当链路 A 改动时 |

---

## 7. 实施步骤（Gate 0 是阻塞门）

### Gate 0 · 验证（**不通过则停止，不写业务代码**）

| # | 验证项 | 方法 | 通过标准 |
|---|---|---|---|
| **G0-1** | Key 有效性 | `curl -H "Authorization: Bearer $K" "https://api.eulerpool.com/api/1/research/news/AAPL"` | 200 且返回非空 |
| **G0-2** | **是否支持关键词** | 同上，把 `AAPL` 换成 `macro` / `fed` / `inflation` | 200 且返回**宏观**新闻（不是空、不是 404） |
| **G0-3** | 语言与格式 | 看返回 JSON 的字段名与 `title` 语言 | 能映射到 `title/snippet/link/date` |
| **G0-4** | 中文检索 | 用 `MACRO_NEWS_QUERY` 试 | 明确「是否支持中文」 |
| **G0-5** | 实际额度 | 注册后看账户页 | 记录真实数字 |

> ⚠️ G0-2 是**决定性**的：若不支持关键词搜索，Eulerpool **不能做宏观源**，方案退回 §5.3 第一行。
> 📌 **G0 结果请贴回本文件或 journal，供后续决策。**

### S-1 · 新增 `search_eulerpool`（用 `requests`，不装 SDK）

```text
# 伪代码：只描述契约
def search_eulerpool(query, timeout=10):
    key = _load_env("EULERPOOL_API_KEY")     # 复用现有 _load_env（支持 .env / D:/hermes/.env）
    if not key: return []                     # Key 缺失 → 静默跳过，不抛
    # 端点与参数以 Gate 0 实测为准
    ...
    return [{"title":…, "snippet":…, "link":…, "date":…}]   # 统一格式
```

**必须遵守**：
- 超时 ≤10s，异常一律 `log.warning` + 返回 `[]`（**不抛**，与现有 Tavily 一致）
- 日志形如 `[News] Eulerpool 搜索成功/失败: {query}`
- 返回格式与 Tavily **完全一致**（PRD 的统一格式约束是对的）

### S-2 · 新增 `search_news_multi`（显式编排，顺序可配）

```text
def search_news_multi(query, timeout=10, order=None):
    for name in (order or NEWS_SOURCE_ORDER):   # 默认 tavily
        fn = {"eulerpool": search_eulerpool, "tavily": search_tavily}[name]
        try:
            r = fn(query, timeout)
            if r: log(f"[News] 使用 {name}"); return r
        except Exception as e:
            log(f"[News] {name} 失败: {e}"); continue
    return []
```

⚠️ **PRD 伪代码的一个 bug 要避免**：它是 `if not is_key_configured: continue` **在外层** —— 这没问题；但真实实现里**每个源都要独立 try/except**，否则单源异常会中断整条链（PRD 自己列为 Constraint「单源失败不影响其他源」，伪代码没体现全）。

### S-3 · 接线（**最小改动**）

- **链路 B（宏观中文）：不动。** `daily_report.py:168` 保持 `search_news(MACRO_NEWS_QUERY)`。
- **仅当 Gate 0 证明可行**，才在链路 A（`:91`）或新增链路上试用 `search_news_multi`。

### S-4 · 测试

| 用例 | 期望 |
|---|---|
| Eulerpool 成功 | 返回统一格式，日志记 `使用 eulerpool` |
| Eulerpool 失败（错 Key / 超时） | 自动降级 tavily，不抛异常 |
| 所有源失败 | 返回 `[]`，日报不中断 |
| `EULERPOOL_API_KEY` 缺失 | 静默跳过该源 |
| `search_news` 行为不变 | **回归**：既有 `test_phase24/25/27` 断言全绿 |

**验证命令**（引自 `docs/commands.md`）：
```text
venv/Scripts/python -m pytest tests/ -v
venv/Scripts/python -m pytest tests/test_news_fetcher.py -v
AUTO_PUSH=0 venv/Scripts/python daily_report.py      # 本地务必关自动推送
```

### S-5 · 记录

- `tasks/2026-09-12-eulerpool-news/journal.md`：Gate 0 逐项结果 + 最终定位决策。
- `docs/pitfalls.md` 追加：
  1. **同名的 `search_news` 承载两种语义**（个股归因 / 宏观新闻），扩展多源前必须先拆调用点。
  2. **Hermes 消费的是 `search_keywords` 不是新闻正文** —— 想给 AI 喂新闻，先确认落点存在。
  3. **外部数据源接入前先证伪**：官方文档在 Cloudflare 后、额度说法不一、社区反馈 Key 无效时，不要让它成为主源。

---

## 8. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **PRD 前提不成立**（context 无 news 落点） | **高** | 已更正；若确需给 Hermes 喂新闻，须**先确认 Hermes 会消费哪个键**，否则写了也没用 |
| **R2** | **统一路由同时污染链路 A/B** | **高** | 不改造 `search_news`；新增显式 `search_news_multi`，A/B 默认零改动 |
| **R3** | **切英文源推翻中文宏观成果** | **高** | 链路 B 主源保持 Tavily；`NEWS_SOURCE_ORDER` 默认 `tavily` |
| **R4** | **Key 无效 / 端点不通** | **高** | Gate 0 阻塞；失败则只留空实现 + 跳过逻辑，不接线 |
| **R5** | 端点只有 ticker 维度 → 做不了宏观 | **中** | G0-2 决定；若如此，仅用于链路 A 的个股英文增强 |
| **R6** | 引入 `eulerpool` SDK 破坏零依赖 | **中** | 明确用 `requests`（已在 requirements.txt），**不改依赖** |
| **R7** | 单源异常中断整条降级链 | **中** | 每源独立 try/except；PRD 伪代码此处不完整 |
| **R8** | 降级链最坏 20s 拖慢日报 | **中** | 每源 ≤10s；建议 Eulerpool 超时降到 6s（它是新源、风险高） |
| **R9** | 改造 `search_news` 破坏既有测试 | **中** | 保持 `search_news` 语义不变；`test_phase24/25/27` 作为回归护栏 |
| **R10** | 英文新闻进前端导致大面积省略号 | **低** | 前端按 42 字中文设计；英文源暂不进 `news.json` |
| **R11** | 真跑 `daily_report.py` 触发 push | **低** | 本地一律 `AUTO_PUSH=0` |

---

## 9. 对你三个问题的答复

### Q1 · 用 `research/news/{ticker}` 还是通用搜索端点？

**先别选 —— 这两个可能都不是我们要的。**

- `research/news/{ticker}` 是 **ticker 维度**，语义是「某只股票的新闻」，**不是「按关键词搜新闻」**。拿它搜 `macro`/`fed` 属于**误用**。
- 「通用搜索端点」—— **我在 PRD 里没看到出处**，官方文档又在 Cloudflare 后面抓不到，**我无法证实它存在**。

→ **必须由 Gate 0 的 G0-2 实测决定**。若证实只有 ticker 维度，那 Eulerpool **本质上不适合做宏观新闻源**，只能做个股归因增强 —— 那它的价值就比 PRD 预期小很多。

### Q2 · 是否引入 `eulerpool` SDK？

**不引入。** 用 `requests`：
- `requests==2.34.2` 已在 `requirements.txt`，**零新增依赖**；
- 我们只需要一个 GET，SDK 带来的类型提示/pandas 支持用不上；
- PRD 自己的 Constraint 也写了「不新增复杂依赖」—— 这条是对的，保持。

### Q3 · 要不要先验证 API 可用性？

**要，而且必须做成阻塞门。** 我已在 §7 设了 Gate 0。

补充一个我**已经试过但失败**的验证：`https://eulerpool.com/news/feed.xml`（PRD 给的免 Key RSS）**10 秒超时**，`https://eulerpool.com/developers` 返回 Cloudflare 人机验证页。**所以目前关于该 API 的一切信息都来自 PRD 自述，零外部佐证。**

→ 在没有一条来自真实调用的证据前，我不会让它在方案里承担主源角色。

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `src/news_fetcher.py` | +约 55 / −3 行（`search_eulerpool` + `search_news_multi` + 顺序配置） |
| 修改 | `.env.example` | +约 8 行 |
| 新建 | `tests/test_news_fetcher.py` | 约 90 行 |
| 修改 | `daily_report.py` | **+0~3 行**（视 Gate 0 结果；链路 B 不动） |
| 不动 | `src/analyzer.py` / `src/reporter.py` / `requirements.txt` / `web/*` | — |
| 新增 | `tasks/2026-09-12-eulerpool-news/plan.md` / `journal.md` | 本文件 / Gate 0 结果 |
| 追加 | `docs/pitfalls.md` | 3 条 |

**净代码变更估算**：约 **+150 行**（Gate 0 未通过时仅约 +70 行空实现）。

---

## 11. 不做什么

- 不改 `search_news` 的既有语义（避免污染链路 A/B）。
- 不把 Eulerpool 设为默认主源（默认 `NEWS_SOURCE_ORDER=tavily`）。
- 不动链路 B（中文宏观）与前端「最新资讯」。
- 不引入 `eulerpool` SDK / 不改 `requirements.txt`。
- 不给 `context.json` 加 `news` 字段（**落点未确认，写了 Hermes 也不消费**）。
- 不做多源结果合并去重（沿用 PRD 的 Out of Scope）。

---

## 12. 确认（阻塞项）

- [ ] **先执行 Gate 0**，把 G0-1~G0-5 结果贴回（**这是开工前置**）
- [ ] 已确认 PRD 的 4 处事实错误已更正（§2）
- [ ] 已确认**不给 context.json 加 news**（无落点，R1）
- [ ] 已确认 `search_news` **不被改造成统一路由**（R2）
- [ ] 已确认链路 B 主源保持 Tavily、`NEWS_SOURCE_ORDER` 默认 `tavily`（R3）
- [ ] 已确认**不引入 SDK**（Q2）
- [ ] 已确认本地跑 `daily_report.py` 一律带 `AUTO_PUSH=0`
