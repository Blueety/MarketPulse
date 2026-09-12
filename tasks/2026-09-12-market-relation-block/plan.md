# Plan — 看板「市场关系」子块接真数据（显著相关对 pills）

> 日期：2026-09-12 ｜ 角色：架构师 ｜ 状态：待用户确认后交执行者
> **执行顺序依赖**：与 [risk-appetite-block](../2026-09-12-risk-appetite-block/plan.md) 同改一张卡（`#sectors`）和同一渲染链，**必须在 risk-appetite 合入后开工**，避免同卡冲突。

## 0. 结论先行

**做法**：`/api/latest` 响应新增 `correlation` 键（把 api_latest 已加载的 context `correlation` 透传出来），前端把 `#market-relation` 里 4 个写死的 `disabled` 胶囊替换为**数据驱动的显著相关对 pills**（`{pair} {r:+0.2f}`，按 |r| 降序，正红负绿沿用日报配色惯例）。零新增计算、零新增取数、零改动 `src/`。

**选型理由**（替代方案对比）：

| 方案 | 说明 | 取舍 |
|---|---|---|
| **A 直通 context 显著对（选定）** | context `correlation` 键已有 5 对固定组合中 \|r\|>0.5 的记录 `{a,b,pair,r,n}`，`pair` 是现成中文标签（「标普500 ↔ 上证」） | 零计算零取数；缺点：4 个原设计故事对（股指 vs 美债 / 美元 vs 黄金 / 原油 vs 经济）多数覆盖不了 |
| B 补算故事对（含美债/美元/原油） | 需 ^TNX / DX-Y.NYB / CL=F 序列——**只在 `/api/macro` 实时取数里有**（90s TTL），要么请求路径联网（违背 api_latest 瞬时只读原则），要么先做宏观序列持久化（≈自选股文件化量级的新任务） | 留作后续任务（macro 序列落盘后一次补齐），本任务不做 |
| C 前端拿两个 API 响应自己算相关 | app.js 组合 history + macro 序列算 Pearson | 业务逻辑进 JS、不可单测，与风险偏好任务的分层决策相悖，否决 |

**数据事实**（已核实）：`CORRELATION_PAIRS`（analyzer.py:68）= VIX↔GSPC / VIX↔SH / GSPC↔SH / IXIC↔CYB / MOVE↔VIX 五对固定组合；context 只写 `|r|>0.5` 显著对，字段 `{a, b, pair, r, n}`，`r` 两位小数、`pair` 为 `SYMBOLS label` 拼的中文展示串（如「恐慌指数(VIX) ↔ 标普500」）。原 4 个静态胶囊中的「VIX vs 股市」由第 1 对覆盖；其余故事对搁置（见 B 方案备注）。

**响应契约**（`/api/latest` 新增键，向后兼容）：

```json
"correlation": [ {"a": "VIX", "b": "GSPC", "pair": "…↔…", "r": -0.62, "n": 28} ]
```

ctx 缺失 / 键缺失 / 非列表 → `[]`（与 `_sector_payload` 同款容错）。前端空数组 → 子块显示一行 muted「暂无显著相关对（近30日 \|r\|≤0.5）」。

## 1. 任务目标

`#market-relation` 子块（「市场情绪 & 资金流向」卡第三个子块）从 4 个写死 `disabled` 胶囊点亮为真实显著相关对展示：每 pill 一对关系 + 相关系数值，颜色表达联动方向（正=红/同向联动，负=绿/对冲——与日报相关性表同一着色语义），hover 提示样本数 `n`。

## 2. 要改的文件列表

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增 `_correlation_payload(ctx) -> list`（list 直通 / 其余 `[]`）；`api_latest` 响应加 `"correlation": ...` |
| `web/templates/index.html` | `#market-relation` 的 `.pill-row` 清空静态 4 胶囊（容器保留，JS 填充）；与 risk-appetite 任务一样**不加** data-placeholder（本块有自己的空态文案） |
| `web/static/app.js` | 新增 `renderMarketRelation(latest)`：correlation 按 `abs(r)` 降序（最多 5 个）→ pill span（`pos`/`neg` 色 + `title="近{n}个交易日"`）；空 → `.ph-note` 一行文案；在 `/api/latest` 渲染链接入（`renderSector` 之后，与 risk-appetite 渲染同点顺延） |
| `web/static/style.css` | pill 现有样式复用为主；仅补 `.pill.pos { color: var(--red) }` `.pill.neg { color: var(--green) }`（现状 pill 是 disabled button 灰态，需给活 pill 提色）；加 `.pill-row .ph-note` 行高 |
| `tests/test_web.py` | `_correlation_payload` 纯函数用例（直通/None/坏类型→[]）+ `api_latest` 含 `correlation` 键（复用既有 ctx fixture） |
| `docs`（收尾） | pitfalls 记一条：**「grep data-placeholder 盘点占位会漏掉未打标的的死块」**（market-relation 即实例）；AGENTS.md web 行补 correlation 键 |

**零改动**：`src/*`（`compute_correlation`/`CORRELATION_PAIRS` 只被消费）、daily/snapshot 链路、`#fund-flow`/`#news` 等其余占位、前端数据获取链。

## 3. 实现步骤（每步可独立验证）

### S1 后端透出
1. `_correlation_payload(ctx)`：`isinstance(ctx, dict) and isinstance(ctx.get("correlation"), list)` → 原样返回，否则 `[]`（不做逐条字段校验——生产端 `_watchlist_context` 式契约已保证，web 侧过度防御反而藏错）。
2. `api_latest` 响应加 `"correlation": _correlation_payload(ctx)`（**恒有键**，含 indices 全 None 的空壳 context 路径——空壳 context 的 correlation 也可能是旧值或空，前端空态兜底）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（新增用例 + 既有零改动通过）。

### S2 前端渲染
1. `index.html`：删 4 个静态 `<button class="pill" disabled>`，`.pill-row` 置空（保留 h3「市场关系」与容器）。
2. `app.js` `renderMarketRelation(latest)`：

   ```text
   list = (latest.correlation || []).slice().sort((x,y) => abs(y.r) - abs(x.r)).slice(0, 5)
   list 空 → pillRow.innerHTML = '<p class="ph-note">暂无显著相关对（近30日 |r|≤0.5）</p>'
   否则逐条 → <span class="pill pos|neg" title="近{n}个交易日">{pair} {r>=0?'+':''}{r.toFixed(2)}</span>
   ```

3. 调用点：`refresh()` 的 `/api/latest` 成功分支，`renderRiskAppetite(latest)` 之后。
4. `style.css`：活 pill 提色（`.pill.pos{color:var(--red)}` / `.pill.neg{color:var(--green)}`）；确认 pill 换行间距在 5 个时仍为两行内。

**验证**：`verify_ui.py` 三视口（硬规定）+ 新端口 uvicorn 人工核对：pill 值与 `context/最新.json` 的 correlation 逐条一致；空态路径（临时把 ctx 键改名模拟）显示 muted 文案。

### S3 全量回归 + 文档收尾
- `venv/Scripts/python -m pytest tests/ -v` 全绿；`git diff` 范围核对；pitfalls/AGENTS.md 记录（含「未打标的的死块」教训）。

## 4. UI 专项说明

**复现路径（改前）**：起 uvicorn（新端口）→ 行 3「市场情绪 & 资金流向」卡 → 第三子块「市场关系」→ 4 个灰色禁用胶囊（股指 vs 美债 / 美元 vs 黄金 / VIX vs 股市 / 原油 vs 经济），永不变化。

**关键测量点**：
- `.pill-row` 高度：改前静态 4 pill ≈ 2 行；改后 5 pill（最坏全显著）仍应 ≈ 2 行——若折 3 行则**减 pill 上限到 4**（plan 默认 cap 5，此处为回退开关）；
- `#sectors` 卡 `scrollHeight ≤ clientHeight`（与 risk-appetite 任务共用同一护栏，**两任务叠加后必须复测整卡高度**）；
- pill 文本最长对（如「恐慌指数(VIX) ↔ 标普500 -0.62」）在窄卡不溢出：`.pill` 白空间处理沿用现状（wrap 允许），必要时 title 已带全文。

**box-sizing**：全局 `border-box`（style.css:72），pill 用 padding 自适应，无固定 height，无撑高陷阱。

**多尺寸验收**：
- **720p**：三卡并排变窄，pills 允许折行，子块不溢出、无横向滚动；
- **1080p**：5 pill 最多两行，与上邻「风险偏好」「资金流向（占位）」子块高度协调。

## 5. 风险评估和注意事项

1. **同卡叠加风险**：`#sectors` 卡在本任务前刚被 risk-appetite 加高，两改动叠加后整卡高度必须复测（§4 回退开关：cap 5→4）。
2. **显著对数量波动**：行情平静月份可能 0 对显著 → 空态文案是常态路径不是异常；反向地，5 对全显著也合法（context 最多 5 条）。
3. **空壳 context 旧值**：全源取数失败日的空壳 context 若 correlation 带旧值（generate_context 覆盖写，实为当日计算结果——取数全失败时 r=None 被过滤为空），空态兜底已覆盖，无额外处理。
4. **着色语义勿反**：正 r = 同向联动 = 红（风险集中），负 r = 对冲 = 绿——与日报相关性表一致，别按「涨红跌绿」直觉写反。
5. **pill 从 button 变 span**：原静态是禁用 button（纯装饰）；活 pill 是展示性 span（无点击行为），不要加 cursor:pointer 假交互。
6. **测试隔离**：`api_latest` 测试复用既有 ctx fixture，新增键断言用「键存在 + 值类型」，勿加全键集全等断言（防后续加键连环崩）。

## 6. 验证命令（引用 docs/commands.md）

| 用途 | 命令 |
|---|---|
| 单测 | `venv/Scripts/python -m pytest tests/test_web.py -v` |
| 全量 | `venv/Scripts/python -m pytest tests/ -v` |
| 手测 | `venv/Scripts/python -m uvicorn web.app:app --port 8018`（新端口）→ 浏览器看子块 + 对照 `context/最新日期.json` correlation |
| UI 验收（必跑） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |

## 7. 预计影响的文件范围

`web/app.py`（+~12 行）、`web/templates/index.html`（−4/+1 行）、`web/static/app.js`（+~20 行）、`web/static/style.css`（+~6 行）、`tests/test_web.py`（+~35 行）、AGENTS.md / docs/pitfalls.md（收尾各 1 条）。**不动**：`src/*`、其余占位区块、数据生产链路。

**后续任务备忘**（本计划不做）：宏观序列持久化（`/api/macro` 的 ^TNX / DX-Y / CL=F 落盘）后，可补算原设计的「股指 vs 美债」「美元 vs 黄金」「原油 vs 股市」三对故事 pill，与本块渲染函数直接兼容（往 correlation 数组里追加即可）。
