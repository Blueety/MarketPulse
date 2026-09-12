# Plan — 看板「最新资讯」接真数据（契约先行：Hermes 落盘 + web 消费）

> 日期：2026-09-12 ｜ 角色：架构师 ｜ 状态：待用户确认后交执行者
> 与 risk-appetite / market-relation 两任务无同卡冲突（本任务改行 4 的 `#news` 卡），可并行；仅 app.js 的 `PLACEHOLDERS` 注册表各行相距远，合并冲突风险低。

## 0. 结论先行

**做法**：定义资讯 JSON 契约 → **Hermes 侧**（用户改 cron prompt，非仓库代码）在 tavily 搜索后把结构化结果落盘 `data/news.json` → **仓库侧**新增 `/api/news` 只读端点 + 前端渲染，坏文件/缺文件全部优雅空态。卡片在 Hermes 接入前显示「暂无资讯」，接入后自动点亮——repo 侧可独立先行交付。

**关键事实**（已核实，决定了方案走向）：
1. **日报里现在没有 AI 解读章节**（`reports/2026-09-12.md` 章节列表止于「📝 总结」）——「解析日报 md」方案连数据源都不存在，直接排除；
2. `context/` 与 `data/` **都被 git 追踪**（auto-push 随行 → Railway 可见），资讯文件放哪都能到 Railway；
3. tavily 搜索只存在于 Hermes 侧（决策 G：Python 侧不引入搜索 SDK，不可逾越）——**资讯的唯一生产者只能是 Hermes**。

**选型**（替代方案对比）：

| 方案 | 说明 | 取舍 |
|---|---|---|
| **B 契约先行：Hermes 落盘 `data/news.json`（选定）** | 定义 schema，Hermes 搜索后顺带写文件；web 只读消费 + 空态 | 结构化、可渲染标题/链接/摘要；依赖用户改一次 Hermes prompt（交付侧一步，schema 已备好） |
| A 解析日报 AI 解读章节 | 读 `reports/*.md` 的「解读」章节当资讯 | **已证伪**：章节是否存在取决于 Hermes 当日运行，prose 无法拆成资讯条目，格式漂移即碎 |
| C Python 侧直连 tavily | fetcher 加搜索源 | 违反决策 G（PRD 硬约束），否决 |
| D Hermes 写进 `context/*.json` | 复用每日 context | **双写者冲突**：`context/YYYY-MM-DD.json` 由 Python `generate_context` 覆盖写（快照 cron 也会写），Hermes 写它会被当日后续快照运行清掉 |

**文件位置定为 `data/news.json`**（单文件、最新快照语义）：与 `data/watchlist.json`（最新自选快照）/`data/last_values.json` 同范式；所有权清晰——**`context/*.json` 归 Python 写、`data/news.json` 归 Hermes 写**，两域互不越界（记 pitfalls）。

**资讯契约**（Hermes 交付规格，写入 docs 供用户更新 cron prompt）：

```json
{
  "date": "2026-09-12",
  "items": [
    {"title": "VIX spikes 20% as ...", "url": "https://…", "source": "Reuters",
     "published": "2026-09-12", "summary": "一句话摘要（≤80 字）"}
  ]
}
```

约定：`items` 按重要性排序、3~8 条；`title/url` 必填；Hermes 写入用 tmp + rename 原子替换（防半截 JSON）。**web 侧防御性读取**：坏 JSON/缺文件/条目缺 title 或 url 非 http(s) 开头 → 逐条过滤/整体空态，HTTP 200 不 500。

## 1. 任务目标

`#news` 卡（行 4 宽卡）从 `data-placeholder` 占位点亮为真实资讯流：每条 = 标题链接（新窗口打开）+ 来源·日期小字 + 摘要（两行截断），卡头显示数据日期；无数据/坏数据显示「暂无资讯」不隐藏、不崩。

## 2. 要改的文件列表

| 文件 | 改动 |
|---|---|
| `web/app.py` | 模块级 `NEWS_FILE = DATA_DIR / "news.json"`（**定义在使用方 web.app**，monkeypatch 纪律）；纯函数 `_load_news()`（读/校验/过滤/cap 8，容错返回空结构）；新端点 `GET /api/news` → `{date, items, count}` |
| `web/templates/index.html` | `#news` 移除 `data-placeholder="1"`；卡头 h2 旁加 `<span class="h2-sub" id="news-date"></span>`；body 保留 `id="news-body"` |
| `web/static/app.js` | `PLACEHOLDERS` 注册表移除 `news`（**与 data-placeholder 同一提交摘除**，双点同步坑）；新增 `fetchNews()`（并行 fetch，同 wlFetch/mcFetch 模式）+ `renderNews(payload)`（`escapeHtml` 全量转义、`<a target="_blank" rel="noopener noreferrer">`、空态「暂无资讯」） |
| `web/static/style.css` | `.news-item`（标题行 + meta 行 + 摘要 `line-clamp:2`）、hover 态；复用既有 token，高度预算见 §4 |
| `tests/test_web.py` | `/api/news` 用例：文件缺失→200 空结构 / 合法→过滤 cap / 坏 JSON→空 / 缺 title 条目被滤 / url 非 http 被滤（monkeypatch 打 `web.app.NEWS_FILE`） |
| `docs/architecture.md` `AGENTS.md` `docs/pitfalls.md` `docs/commands.md`（收尾） | 决策行（资讯契约 + 所有权边界）/ web API 计数 5→6 / 双写者坑 + 双点同步坑 / 新端点验证命令 |

**交付侧（用户执行，非仓库代码）**：按 §0 契约更新 Hermes「每日数据更新」cron prompt——搜索完成后将 3~8 条结果写 `data/news.json`（tmp+rename）。**本任务 repo 侧不阻塞于此**：未接入前卡片空态即验收态。

**零改动**：`src/*`、`context/` 写入链、其余占位区块、`daily_report.py`（资讯不进日报）。

## 3. 实现步骤（每步可独立验证）

### S1 后端端点
1. `_load_news()`：

   ```text
   try 读 NEWS_FILE → json.loads
   非法（IO 错/坏 JSON/非 dict/无 items 列表）→ {"date": None, "items": [], "count": 0}
   items 过滤：dict 且 title 非空 且 url 以 http(s):// 开头，保留 source/published/summary（缺省 ""）
   截前 8 条 → {"date": payload.get("date"), "items": [...], "count": len}
   ```

2. `@app.get("/api/news")` 返回上述结构（**HTTP 200 恒定**，与 `/api/alerts` 空目录容错同纪律）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（新增用例全绿）。

### S2 前端渲染
1. `index.html`：摘除 `data-placeholder="1"` + 加 `#news-date` 小字位；app.js `PLACEHOLDERS` 同提交删 `news` 项。
2. `app.js`：`fetchNews()` 并行（`Promise` 链与 alerts 同款，失败仅 console + 空态）；`renderNews(payload)`——

   ```text
   payload.date 存在 → #news-date.textContent = '· ' + payload.date
   items 空 → news-body = '<p class="ph-note">暂无资讯</p>'
   否则逐条 → <div class="news-item">
                <a href(url) target=_blank rel="noopener noreferrer">{escapeHtml(title)}</a>
                <div class="news-meta">{source} · {published}</div>
                <p class="news-summary">{escapeHtml(summary)}</p>
              </div>
   ```

3. `style.css`：`.news-item` 间距 12px、标题 13px 600、meta 11px muted、摘要 `display:-webkit-box; -webkit-line-clamp:2` 两行截断。

**验证**：`verify_ui.py` 三视口（硬规定）；新端口 uvicorn 手测——真实文件未接入前看空态；**临时构造样例 `data/news.json`（2~3 条）验证渲染，验完必须删除**（pitfalls：验证期数据恢复纪律；该文件会被下次 auto-push 扫入，删干净再收工）。

### S3 全量回归 + 文档收尾
- `venv/Scripts/python -m pytest tests/ -v` 全绿；`git diff` 范围核对；
- docs 四处收尾（含把 §0 契约原文落进 architecture.md 决策行，作为用户改 Hermes prompt 的唯一依据）；
- 提醒用户：Hermes prompt 更新后，跑一次「每日数据更新」cron 验证 `data/news.json` 落盘，看板自动点亮。

## 4. UI 专项说明

**复现路径（改前）**：起 uvicorn（新端口）→ 行 4 右侧「最新资讯」宽卡 → 灰色小字「数据未接入」（`renderPlaceholders` 写入）。

**关键测量点**：
- `#news` 卡高度由行 4 栅格决定（`row-news` 两卡同行，告警卡窄资讯卡宽）——改后 8 条满载时卡高 = 8 × (标题 18 + meta 14 + 摘要 2×18 + 间距 12) ≈ 480px；**与左邻告警卡（10 条简行）高度差不作强约束**（行 4 允许卡高不齐），但**满载时页面不得出现新滚动条**——若超，cap 从 8 降到 6（回退开关）；
- `.news-item a` 溢出：长标题 `word-break: break-word`（外链标题不可控）；
- 摘要 line-clamp 2 行高度恒定 → 条目高度均一，视觉整齐。

**box-sizing**：全局 `border-box`（style.css:72）；item 用 padding+margin 自适应，无固定高度，无陷阱。

**多尺寸验收**：
- **720p**：资讯卡宽度收窄，标题单行截断省略号（加 `text-overflow: ellipsis; white-space: nowrap`? 否——标题允许两行 wrap，仅摘要 clamp），无横向溢出；
- **1080p**：8 条完整展示、两行摘要、右侧留白正常。

## 5. 风险评估和注意事项

1. **Hermes 侧未接入前为常驻空态**——设计即如此（空态是验收态之一），repo 侧先行交付无阻塞；用户改完 prompt 即点亮。
2. **Hermes 写坏文件**（半截 JSON/字段缺失/条目超量）——读取端逐层容错（§3 S1），永不 500；交付规格里明确 tmp+rename，双保险。
3. **双写者边界**：`context/*.json` 只归 Python（generate_context）、`data/news.json` 只归 Hermes——Hermes 绝不写 context（会被快照运行覆盖），Python 绝不写 news（无搜索能力）；记 pitfalls 防未来有人破坏。
4. **外链安全**：所有插值 `escapeHtml`（既有纪律）；`target="_blank"` 必配 `rel="noopener noreferrer"`；url 服务端校验 http(s) 前缀（防 `javascript:` 注入）。
5. **自动提交时序**：Hermes 写 `data/news.json` 发生在当日 auto-push 之后 → 该文件最早随下一次 Python 入口的 auto_commit 入库（A 股午盘 11:30 前后）→ **Railway 侧资讯延迟数小时属预期**；本地 web 即时可见。备选：Hermes 侧自带 commit（不推荐，混入 auto-push 语义）。
6. **验证期样例文件必须删除**：`data/news.json` 在 git 追踪范围内，手测样例不删会被下次 cron 自动提交成假资讯。
7. **双点同步**（沿用风险偏好任务教训）：`data-placeholder`（HTML）与 `PLACEHOLDERS`（app.js）同提交摘除。

## 6. 验证命令（引用 docs/commands.md）

| 用途 | 命令 |
|---|---|
| 单测 | `venv/Scripts/python -m pytest tests/test_web.py -v` |
| 全量 | `venv/Scripts/python -m pytest tests/ -v` |
| 手测（空态 + 样例态） | `venv/Scripts/python -m uvicorn web.app:app --port 8019`（新端口）→ `curl http://localhost:8019/api/news`；样例文件验后删除 |
| UI 验收（必跑） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |
| Hermes 侧（用户） | 更新 cron prompt 后跑一次「每日数据更新」，`git status` 应见 `data/news.json`，看板自动出真资讯 |

## 7. 预计影响的文件范围

`web/app.py`（+~45 行）、`web/templates/index.html`（±4 行）、`web/static/app.js`（+~45/-1 行）、`web/static/style.css`（+~30 行）、`tests/test_web.py`（+~55 行）、docs 四处收尾。**不动**：`src/*`、日报链路、其余占位区块（`#fund-flow` 留给最后的资金流向任务）。

**剩余占位盘点（本任务后）**：`#fund-flow`（资金流向，需 AkShare 北向/板块资金数据源，最大硬骨头）+ `#promo-global`（装饰位，可永久保留）+ us-sectors「查看全部」死按钮（可顺手移除或做板块详情，另议）。
