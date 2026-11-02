# 计划：GDELT 宏观新闻源接入（含 PRD 事实更正 + 实测证伪）

- **日期**：2026-09-13
- **任务目录**：`tasks/2026-09-13-gdelt-news/`
- **输入**：`GDELT 集成 Handoff`（Eulerpool 方案的替换版，属同一模板改源名）
- **架构师职责**：比对 PRD 与真实代码 / 真实 API → 更正事实 → 解决冲突 → 出可落地方案

---

## 1. 结论先行

**不建议按 PRD 直接开工。** GDELT 相比 Eulerpool 有巨大优势（免 Key、无 Cloudflare），但我做了实测，**PRD 的核心优势描述「免费额度：无限制」被证伪**，且它有三个会直接影响现有功能的硬伤。

| 判定 | 内容 |
|---|---|
| ❌ **PRD 的「无限制」不成立** | GDELT 明确限流，返回 429 + "Please limit requests to one every 5 seconds"；**实测 6 次仅成功 1 次，间隔 30 秒仍 429** |
| ❌ **继承 Eulerpool PRD 的 4 处事实错误** | 文件归属、函数位置、测试文件、context 落点全错（与昨日 Eulerpool 版**完全相同**，见 §2） |
| ⚠️ **GDELT 无摘要字段** | 只有 `title`。PRD 自己的解法是 `snippet = title` —— **这会直接推翻刚完成的「一句话新闻条」改造** |
| ⚠️ **多语言混杂已实测到** | 成功那次返回的标题含阿拉伯字母（`\u062c`），非拉丁语系占比不低 |
| ✅ **免 Key / 无 Cloudflare** | 这两条 PRD 说对了，是相对 Eulerpool 的真实优势 |
| ✅ **建议做法** | **降级为第三源 + 严格节流 + 断路器**；**不用于前端新闻卡**；先做只读探针再决定是否接线 |

---

## 2. PRD 的 4 处事实性错误（与 Eulerpool 版完全相同）

本 PRD 是 Eulerpool 版的**同源模板改源名**，因此昨日已更正的 4 处错误**原样继承**：

| # | PRD 说法 | 实测结果 |
|---|---|---|
| **E1** | `src/news_fetcher.py` **新建** | **已存在**：Tavily 单源，已有 `search_news(query, timeout=10)`、CLI、`.env` 读取链 |
| **E2** | `analyzer.py` 中 `generate_context()` 调 Tavily | `generate_context` 在 **`src/reporter.py:937`**，且**不调搜索** —— 只调 `build_search_keywords()`（`:981`）生成关键词 |
| **E3** | 修改 `tests/test_analyzer.py` | 搜索调用点在 `daily_report.py`，对应 `tests/test_phase24.py:191` / `test_phase25.py:66` / `test_phase27.py:248` |
| **E4** | 「新闻写入 `context.json`」 | context 实际键：`date, indices, history_30d, breach, sector_heat, us_sector_heat, search_keywords, correlation, watchlist`。**无 `news` 键** |

**Hermes 消费的是 `search_keywords`（关键词列表），不是新闻正文** —— 「把 GDELT 新闻写进 context 供 Hermes 归因」**没有落点**。

---

## 3. 实测：GDELT 的真实可用性（本轮亲自跑的）

```text
端点 https://api.gdeltproject.org/api/v2/doc/doc  mode=artlist  format=json
```

| # | 查询 | 间隔 | 结果 |
|---|---|---|---|
| 1 | `Federal Reserve inflation` | 并行 | **SSL EOF**（握手被断） |
| 2 | `美联储 通胀` | 并行 | **429** |
| 3 | `Federal Reserve inflation`（带 UA） | 0s | **429** |
| 4 | `Federal Reserve inflation` | 7s | **429** |
| 5 | `美联储 通胀` | 7s | **200 但非 JSON**（空 body） |
| 6 | `theme:ECON_INFLATION` | 7s | **429** |
| 7 | `inflation sourcecountry:China` | 7s | **429** |
| 8 | `Federal Reserve` / `timespan=7d` | 20s | ✅ **200 / 3085 bytes**（唯一成功） |
| 9 | `Federal Reserve` | 20s | **429** |
| 10 | `Federal Reserve` | 30s | **429** |

**成功率 ≈ 1/10。** 429 的返回体是：

```text
Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com
for larger queries. All high-traffic users should switch to our ngrams dataset...
```

### 3.1 三个由实测确立的实现约束

| # | 发现 | 对实现的要求 |
|---|---|---|
| **D1** | **限流远严于声明**。名义 1 req/5s，实测 20~30s 间隔仍 429 | 必须有**全局节流器 + 断路器**：连续 N 次 429 后**本轮直接跳过 GDELT**，不再重试 |
| **D2** | **HTTP 200 + 非 JSON（空 body）= 无结果**，不是错误 | `r.json()` 前必须判断 body 非空；空 → 返回 `[]`，**不要当异常、不要触发降级**（否则每次无结果都会白跑一次 Tavily） |
| **D3** | **多语言混杂已实测**（阿拉伯字母 `\u062c` 出现在 `Federal Reserve` 查询结果里） | 查询必须带 `sourcelang:` 或 `sourcecountry:` 过滤；且**不能直接进中文前端** |

---

## 4. 与既有决策的冲突（比 Eulerpool 更严重）

### 4.1 GDELT 无摘要 → 直接推翻「一句话新闻条」

`news-macro-brief` 任务（昨日刚完成并验收）的核心产出是：

```js
oneLine(n.summary, n.title)     // 优先一句话摘要，标题只留 tooltip
```

而 GDELT `artlist` 返回字段只有 `url / title / seendate / domain / language / sourcecountry`，**没有正文摘要**。PRD 的解法是：

```python
'snippet': item.get('title', '')   # GDELT 无摘要，用标题代替
```

→ 一旦 GDELT 成为主源，`summary == title`，**前端就退回成"只显示标题"** —— 正是用户明确要求改掉的那个形态。

**结论：GDELT 绝不能接入 `data/news.json` 这条链路。**

### 4.2 中文查询词未验证

`MACRO_NEWS_QUERY` 是中文（`"美联储 通胀 就业数据 地缘政治 全球股市 异动 要闻"`）。实测第 5 次用 `美联储 通胀` 查询拿到 200 但**空 body** —— **未证实 GDELT 支持中文检索**。

### 4.3 两个 `search_news` 调用点仍会被统一路由污染

| 调用点 | 查询串 | 语义 |
|---|---|---|
| **A** `daily_report.py:91` | `f"{label} {symbol} {direction} 新闻"` →「苹果 AAPL 大涨 新闻」 | 个股归因，中文 |
| **B** `daily_report.py:168` | `MACRO_NEWS_QUERY`（中文） | 宏观新闻，中文 |

PRD 的统一路由会让 A、B 同时走 GDELT —— 中文查询 + 无摘要 + 限流，**两链路同时劣化**。

---

## 5. 建议方案

### 5.1 定位：第三源，不是主源

```text
Tavily（主源，已有 Key，已验证产出）
   ↓ 失败 / 无结果
GDELT（第三源，best-effort，节流 + 断路器）
   ↓ 失败 / 限流
[]
```

**为什么不是 PRD 说的「GDELT 主 → Tavily 备」**：
- Tavily 是当前**唯一被验证能产出高质量中文宏观新闻**的源（昨日三条：新西兰元/中国进口/PPI-CPI）
- GDELT 无摘要、限流严重、中文未验证
- **把已验证的源降级、把未验证的源升级，是风险倒置**

### 5.2 三条硬规则

1. **不接 `data/news.json` 链路（B）** —— 保住「一句话新闻条」成果。
2. **必须节流 + 断路**：全局最小间隔（建议 ≥10s，可按实测调整）+ 连续 2 次 429 后本轮熔断。
3. **必须过滤语言/来源**：查询串拼 `sourcelang:english` 或 `sourcecountry:US`（可配置）。

### 5.3 分阶段（Gate 0 仍是阻塞门）

| 阶段 | 内容 | 门槛 |
|---|---|---|
| **Phase 0 · 只读探针** | 新增 `search_gdelt()`，**不接任何生产链路**，只做单次探测 + 落日志 | 在不同时段各跑 5 次，**成功率 ≥ 60%** 才进 Phase 1 |
| **Phase 1 · 接线（可选）** | 仅在链路 A（个股归因）或**新增的英文宏观旁路**上启用，作为第三源 | 需确认消费方 |
| **Phase 2 · 评估** | 攒够样本后决定是否提升为主源 | — |

⚠️ **Phase 0 成功率 < 60% 就停在 Phase 0**，代码保留但不接线（与 Eulerpool 同样的处置）。

---

## 6. 要改的文件列表（更正 PRD）

| 文件 | 动作 | PRD 说的 | 更正 |
|---|---|---|---|
| `src/news_fetcher.py` | **修改**（非新建） | ❌ 新建 | 已存在；新增 `search_gdelt()` + 节流器 + 断路器，**保留** `search_news` 语义 |
| `daily_report.py` | **Phase 0 不改** | ❌ 未提 | 真正的调用点在 `:91`(A) / `:168`(B) |
| `src/analyzer.py` | **不动** | ❌ 说改它 | 只有 `build_search_keywords`（`:228`），与新闻源无关 |
| `src/reporter.py` | **不动** | ❌ 说改 analyzer | `generate_context` 在这里但不调搜索 |
| `tests/test_news_fetcher.py` | 新建 | ✅ | 含 429 降级 / 空 body / 节流 / 熔断用例 |
| `.env.example` | **不改** | ✅（PRD 说无需改） | GDELT 免 Key，这条 PRD 是对的 |
| `requirements.txt` | **不改** | ✅（PRD 说无需改） | `requests==2.34.2` 已足够 |

---

## 7. 实施步骤

### G-0 · 只读探针（**先做这一步，别急着接线**）

```text
def search_gdelt(query, timeout=10):
    # 1. 断路器：本轮已连续 2 次 429 → 直接返回 []
    # 2. 全局节流：距上次请求 < MIN_INTERVAL(10s) → sleep 补足
    # 3. 查询串拼 sourcelang/sourcecountry 过滤（可配置）
    # 4. 请求；非 200 → 记 429/其他，返回 []
    # 5. body 为空 → 返回 []（**不是异常，不触发降级**）  ← D2
    # 6. 解析：title / url / seendate / domain / language / sourcecountry
    #    ⚠️ snippet 字段不存在，不要伪造 snippet=title（会污染前端）
```

**验证**：`venv/Scripts/python -m pytest tests/test_news_fetcher.py -v`

### G-1 · 分时段可靠性采样（决定要不要进 Phase 1）

在不同时段各跑 5 次（间隔 ≥30s），记录成功率。

| 成功率 | 决策 |
|---|---|
| ≥ 80% | 可作为**第三源**接线 |
| 60~80% | 可接线，但必须保留断路器 |
| < 60% | **停在 Phase 0**，不接生产链路 |

⚠️ 另需说明：本机走 Clash 代理（`127.0.0.1:7890`），429 可能与**共享出口 IP** 有关。若 `daily_report.py` 实际运行在其他网络（如部署环境），**应在运行环境复测**，不要只用本机数据下结论。

### G-2 · 接线（仅当 G-1 通过）

- **链路 B（宏观中文）：永不接 GDELT**（§4.1）。
- 可选落点：链路 A 的英文增强，或新增 `data/news_en.json`（前端暂不消费）。

### G-3 · 测试

| 用例 | 期望 |
|---|---|
| GDELT 成功 | 统一格式，日志记 `使用 gdelt` |
| GDELT 429 | 断路器计数 +1；未熔断则降级，已熔断则直接 `[]` |
| GDELT 200 空 body | 返回 `[]`，**不记异常、不误触发降级** |
| GDELT 超时（>10s） | 降级 |
| 所有源失败 | `[]`，日报不中断 |
| `search_news` 行为不变 | **回归**：`test_phase24/25/27` 全绿 |

### G-4 · 记录

- `tasks/2026-09-13-gdelt-news/journal.md`：G-1 采样表（时段 / 次数 / 成功率）+ 最终决策。
- `docs/pitfalls.md` 追加：
  1. **GDELT 名义 1 req/5s，实测远严**；且 **200 + 空 body = 无结果**，不是错误。
  2. **GDELT 无摘要字段**，`snippet=title` 的写法会污染任何「摘要优先」的展示层。
  3. **外部源接入前先测成功率**，不要只看文档写的额度——PRD 写「无限制」，实测 1/10。

---

## 8. 验证命令（引自 `docs/commands.md`）

```text
venv/Scripts/python -m pytest tests/ -v
venv/Scripts/python -m pytest tests/test_news_fetcher.py -v
AUTO_PUSH=0 venv/Scripts/python daily_report.py        # 本地一律关自动推送
curl "https://api.gdeltproject.org/api/v2/doc/doc?query=Federal+Reserve&mode=artlist&maxrecords=5&format=json&timespan=7d"
```

⚠️ curl 手动测试**每次之间至少隔 10 秒**，否则必然 429，会让人误判"API 挂了"。

---

## 9. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **GDELT 无摘要 → 推翻一句话新闻条** | **高** | 绝不接入链路 B；不伪造 `snippet=title` |
| **R2** | **限流导致日报显著变慢** | **高** | 节流 + 断路器；PRD 的「最坏 20 秒」**不成立**，实际可能几十秒 |
| **R3** | **200 + 空 body 被误判为错误** | **高** | D2：空 body → `[]`，不触发降级 |
| **R4** | 中文检索未验证 | **中** | G-0 明确验证；不支持则只查英文关键词 |
| **R5** | 多语言垃圾进前端 | **中** | 强制 `sourcelang` / `sourcecountry` 过滤；**不进前端** |
| **R6** | PRD 统一路由污染链路 A/B | **中** | 不改造 `search_news`；新增显式 `search_gdelt` |
| **R7** | 本机 429 是代理/共享 IP 导致，结论不普适 | **中** | G-1 需在**实际运行环境**复测后再决策 |
| **R8** | `seendate` 格式 `20260913T080000Z` 需解析 | **低** | 统一转成 `YYYY-MM-DD` |
| **R9** | 真跑 `daily_report.py` 触发 push | **低** | 一律 `AUTO_PUSH=0` |

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `src/news_fetcher.py` | +约 70 / −3 行（`search_gdelt` + 节流器 + 断路器） |
| 新建 | `tests/test_news_fetcher.py` | 约 110 行 |
| 修改 | `daily_report.py` | **Phase 0 为 0 行**（G-1 通过后再定） |
| 不动 | `src/analyzer.py` / `src/reporter.py` / `.env.example` / `requirements.txt` / `web/*` | — |
| 新增 | `tasks/2026-09-13-gdelt-news/plan.md` / `journal.md` | 本文件 / G-1 采样结果 |
| 追加 | `docs/pitfalls.md` | 3 条 |

**净代码变更估算**：Phase 0 约 **+180 行**（含测试）；若 G-1 未通过，生产链路 **0 改动**。

---

## 11. 不做什么

- **不把 GDELT 设为主源**（默认仍是 Tavily）。
- **不接入 `data/news.json` / 前端「最新资讯」**（无摘要会退化为标题）。
- **不改造 `search_news` 为统一路由**（避免污染链路 A/B）。
- **不伪造 `snippet=title`**。
- **不给 `context.json` 加 `news` 字段**（无落点）。
- 不引入新依赖（`requests` 已足够）。

---

## 12. 确认（阻塞项）

- [ ] 已知悉 **PRD 的「无限制」被实测证伪**（成功率 ≈1/10）
- [ ] 已确认 **GDELT 不接前端新闻卡**（R1，护住一句话成果）
- [ ] 已确认 **200 + 空 body ≠ 错误**（D2/R3）
- [ ] 已确认 PRD 继承的 4 处事实错误已更正（§2）
- [ ] 已确认 **先做 Phase 0 只读探针**，成功率 ≥60% 才接线
- [ ] 已确认 G-1 需在**实际运行环境**（不只本机）复测
- [ ] 已确认本地跑 `daily_report.py` 一律带 `AUTO_PUSH=0`
