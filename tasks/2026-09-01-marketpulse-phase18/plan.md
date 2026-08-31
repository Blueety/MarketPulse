# MarketPulse 十八期 Plan — 板块聚合

## 待确认决策

| # | 决策 | 选项与推荐 | 理由 |
|---|---|---|---|
| 1 | **聚合范围与实现位置** | 推荐 **方案一：`fetch_sector_heat` 内部默认聚合**（不再返回概念 Top5，直接返回 11 个大类的 gainers/losers）。备选方案二：加 `aggregate: bool = False` 参数，仅 `snapshot_report.py` 传 `True` | `fetch_sector_heat` 内部已取全量板块（akshare 一次取全表，仅后处理切片 Top5），聚合在取数层一次完成，日报 🔥 章节 / 快照 / 开盘分析 / context / web 五个消费点自动全部变为大类，零入口改动、零 mock 签名破坏。方案二下 web 无聚合数据源（web 只读 context，context 仅存 Top5+Top5，无法自行聚合），必须额外新增 context 键 + 改 generate_context / daily_report，改动面反而更大，且日报与快照/看板展示不一致。**代价**：日报板块章节与开盘分析板块展示语义从「概念板块」变为「大类」（超出 PRD 文件表字面，需确认接受）；Hermes 的 `search_keywords` 板块词变为大类名 |
| 2 | 聚合行 `top_stock`（领涨股）取法 | 推荐 **类别内成交额最大的子板块的领涨股**（代表类别主权重）。备选：\|change\| 最大子板块 | PRD 未规定；成交额最大者最能代表该大类的市场主成分，且与权重语义一致 |
| 3 | 板块章节标题/表头文案 | 推荐 **保持「🔥 A 股热点板块 Top 5」不动**。备选：改「大类板块 Top 5」 | 最小 diff；表头四列（板块/涨跌幅/成交额/领涨股）对大类名同样成立；改文案需同步日报、快照、开盘分析三处渲染与多处测试断言 |
| 4 | 「其他」类展示 | 推荐 **参与 Top5 排序正常展示**（10 映射类 + 其他 = 11 类，≤15 不超限）。备选：聚合后剔除隐藏 | PRD 约束「未匹配的概念板块归入'其他'」要求归入；隐藏则 175 板块的聚合结果不完整，信息丢失 |
| 5 | 概念名匹配策略 | 推荐 **精确匹配 `SECTOR_MAPPING` 列表**（未命中自然归「其他」）。备选：包含/前缀模糊匹配 | 约束「未匹配归入其他」已天然兜底漏配，精确匹配零误伤；实施第一步实跑核对新浪全量板块名与 PRD 表 30 个概念名的命中率，必要时在映射表补别名（如「猪肉」vs「猪肉概念」）——属数据层调整，逻辑不变 |

## 影响分析

### 核心事实（已核实）

- `fetch_sector_heat(top_n=5)` 内部经 `ak.stock_sector_spot(indicator="概念")` 一次取**全量**概念板块（~175 条），`_build_rows` 构建 `[{name, change, turnover: "X.X亿", top_stock}]` 后仅返回 Top5 涨 + Top5 跌。**取数与校验逻辑不动，聚合只需替换后处理切片**。
- 行契约 `{name, change: float, turnover: str "X.X亿", top_stock}` 被 `test_phase8.py` 精确 dict 断言锁定（如 `gainers[0] == {"name": "生物育种", "change": 5.2, ...}`），**聚合行必须保持同构字段**，否则 `render_report` / `render_snapshot` / `generate_context` / `build_search_keywords` / `_load_sector_heat` / 前端 index.html 全部消费点零改动即可显示大类。
- `build_search_keywords(date, breaches, sector_heat)` 展平 gainers+losers 的 name 注入方向词 `"{name} surge|drop {date}"` —— 聚合后自动变为大类名（如 `半导体/芯片 drop 2026-09-01`），搜索语义仍有效。
- web `/api/latest` 的 sector_heat 来自 context `sector_heat` 键（`{gainers, losers}`），context 由日报入口 `generate_context` 写入 —— 只要日报取数层聚合，web 自动获得聚合数据。
- 聚合权重需要成交额**数值**，而行内 turnover 是格式化字符串 —— 新增 `_parse_turnover("13.7亿") → 1.37e9`（格式是本项目自产 `元÷1e8 保留1位`，解析确定性）。**不在行内加 raw 键**（保持行契约不变，避免 test_phase8 精确断言破坏）。
- 调用点清单：`daily_report.py:45`、`snapshot_report.py:40`、`opening_analyzer.py:100`（三处均无参调用，方案一下零改动）。测试 mock：`test_phase7.py:249`（已带 `top_n=5` 形参）、`test_phase8.py:222` / `test_phase12.py:247` / `test_phase14.py:365` / `test_phase15.py:228,246`（无参 lambda）——方案一下均无需改签名。

### 方案一影响面

- **fetcher.py**（核心，~64 行净增）：`SECTOR_MAPPING`（10 大类 × 30 概念名，PRD 表原文）+ `_parse_turnover` + `aggregate_sectors(rows, top_n=5) -> (gainers, losers)` 纯函数 + `fetch_sector_heat` 后处理替换（切片 Top5 → `aggregate_sectors(all_rows, top_n)`）。
- **reporter.py / web/app.py / daily_report.py / snapshot_report.py / opening_analyzer.py**：零代码改动（数据流自动生效；PRD 文件表中这两处由数据流满足，不硬改文件凑字面）。
- **tests/test_phase8.py**：`TestFetchSectorHeat` 3-4 条契约测试重写（mock 的 6 个板块名如「生物育种」均不在映射表 → 全归「其他」，输出变为单类聚合行）；其余手工构造 sector_heat 的渲染/context/keywords 测试不受影响。
- **tests/test_phase18.py**（新增 ~15 条，全 mock 不联网）：覆盖加权公式、零成交额简单平均、未匹配归其他、类别数 ≤15、排序、top_stock 取法、单成员类别、全未匹配、fetch 集成、快照渲染、关键词注入。
- **docs**：architecture.md（模块表 fetcher 职责 + 决策表十八期行）、pitfalls.md（十八期小节）、AGENTS.md（fetcher 职责行）、tasks journal.md。

### 计算公式（PRD 原文实现）

```
聚合类涨跌幅 = Σ(子板块 change × 子板块成交额[元]) / Σ(子板块成交额[元])
```
- 子板块成交额经 `_parse_turnover` 还原为元；`Σ == 0`（含全 0 / 全缺失）→ 该类简单平均 `mean(change)`（PRD「成交额为0时用简单平均」）；个别子板块 0 权重自然不贡献。
- 聚合行：`change` round(2)；`turnover` = 类别合计元 `÷1e8 保留 1 位` 复用既有格式；`top_stock` = 类别内成交额最大子板块的 top_stock（决策 2）。
- 输出：10 映射类 + 「其他」共 11 类，gainers 按 change 降序 TopN、losers 升序 TopN（11 ≤ 15，满足 PRD 约束）。

## 修改清单

| 文件 | 修改内容 | 量级 |
|---|---|---|
| `src/fetcher.py` | ① 新增 `SECTOR_MAPPING: dict[str, list[str]]`（10 大类，PRD 表原文 30 个概念名）；② 新增 `_parse_turnover(text: str) -> float`（"X.X亿"→×1e8、"X.X万"→×1e4、纯数字原值；解析失败/空→0.0）；③ 新增 `aggregate_sectors(rows: list[dict], top_n: int = 5) -> tuple[list[dict], list[dict]]`（归组→加权→排序，空输入返回 `([], [])`）；④ `fetch_sector_heat` 后处理：`all_rows` 构建后由「Top5 切片」改为 `aggregate_sectors(all_rows, top_n)`；docstring 更新（返回大类 gainers/losers，字段契约不变） | +64 行 |
| `tests/test_phase8.py` | `TestFetchSectorHeat` 契约测试重写：mock DataFrame 改为跨 3+ 类别板块（含映射命中与未命中），断言聚合输出（类别名、加权值、11 类上限、top_stock） | 重写 3-4 条 |
| `tests/test_phase18.py` | 新增：`SECTOR_MAPPING` 完整性（10 类 / 30 名，与 PRD 表一致）；`aggregate_sectors` 单测（加权公式 `(3×10+5×30)/40=4.5` / Σ=0 简单平均 / 未匹配归其他 / 单成员 / 全未匹配 / 空输入 / 排序与 TopN / top_stock 取成交额最大 / turnover 合计格式 / 类别数 ≤15）；`fetch_sector_heat` 集成（mock akshare 全量 df）；`render_snapshot` 聚合行渲染（表格含大类名）；`build_search_keywords` 大类方向词注入；`generate_context` sector_heat 落盘聚合 | +15 条 / ~200 行 |
| `docs/architecture.md` | 模块表 fetcher 职责补「aggregate_sectors 大类聚合」；关键决策表加十八期行（聚合公式 / 方案一单点聚合 / 未匹配归其他 / 零成交额简单平均） | — |
| `docs/pitfalls.md` | 十八期小节：聚合必须发生在取数层（web 只读 context 无聚合源）、turnover 字符串需还原为元加权、聚合行契约与概念行同构、未匹配归其他兜底漏配、改 `fetch_sector_heat` 返回语义需同步 test_phase8 契约测试 | — |
| `AGENTS.md` | 项目地图 fetcher.py 职责行补「SECTOR_MAPPING + aggregate_sectors 大类聚合」 | — |
| `tasks/2026-09-01-marketpulse-phase18/journal.md` | 任务日志（目标/改动清单/验证结果/注意） | — |

## 执行步骤

1. **实跑核对映射**：`venv/Scripts/python -c "from src.fetcher import fetch_sector_heat; print(fetch_sector_heat())"` 前先临时打印全量板块名，核对 PRD 表 30 个概念名与新浪实际板块名命中率；不命中的在 `SECTOR_MAPPING` 补别名（数据层，逻辑不变）。
2. **fetcher.py**：新增 `SECTOR_MAPPING` → `_parse_turnover` → `aggregate_sectors`（纯函数，逐类归组加权）→ `fetch_sector_heat` 后处理替换为聚合；`_worker` 的 akshare 调用 / 必需列校验 / 异常与 10s 线程限时**原样不动**（满足 PRD「不修改概念板块数据获取逻辑」）。
3. **重写 test_phase8 契约测试**：mock df 构造跨类别板块（如「锂电池」→光伏/新能源、「创新药」→医药、「猪肉」→农业、未匹配名→其他），断言聚合输出。
4. **新增 tests/test_phase18.py**：按上表 ~15 条，全部 mock akshare / 手工构造，不联网。
5. **验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿；`venv/Scripts/python snapshot_report.py --market a-share --time midday` 与 `venv/Scripts/python daily_report.py` 实跑（联网）；web 看板启动验证 `/api/latest`。
6. **docs 同步 + journal.md**；`git diff` 检查改动范围（本轮改动集中在 fetcher.py + 两个测试文件 + docs）。

## 验证方法

1. **单测**：`venv/Scripts/python -m pytest tests/ -v` 全绿（基线 186 + 新增 ~15 − 重写 4 条）；重点断言：加权公式数值、Σ=0 简单平均、未匹配归其他、`len(gainers)+len(losers) ≤ 10` 且类别全集 ≤11（≤15 约束）、聚合行字段键集 == 概念行键集（`{name, change, turnover, top_stock}`）。
2. **快照实跑**（联网）：`venv/Scripts/python snapshot_report.py --market a-share --time midday` → `reports/snapshots/2026-08-31-a-share-midday.md` 板块表行名为大类（如「半导体/芯片」「医药」「其他」），不再是「生物育种」等概念名；成交额为合计、领涨股为类别内成交额最大子板块的领涨股。
3. **日报实跑**（联网）：`venv/Scripts/python daily_report.py` 退出码 0 → `reports/YYYY-MM-DD.md` 🔥 章节为大类；`context/YYYY-MM-DD.json` 的 `sector_heat.gainers/losers` 为聚合行（≤5/边），`search_keywords` 含 `"{大类名} surge|drop {date}"`。
4. **Web**：`venv/Scripts/python -m uvicorn web.app:app` → `GET /api/latest` 的 `sector_heat` 为聚合大类；浏览器开首页板块区正常渲染（字段契约未变）。
5. **回归**：开盘分析 `opening_analyzer.py` 板块章节自动为大类（同一取数层）；快照 `--market us`（无板块）与 alt 路径不受影响；失败/超时仍返回 `([], [])` 显示「数据暂缺」。
6. **边界**：聚合类别数 ≤15 断言；「其他」类参与排序；成交额全 0 类别走简单平均。
