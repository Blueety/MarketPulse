# 实施计划 — MarketPulse 九期「趋势图扩展（分市场双图）」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase9/prd.md`。八期已落地（186 条测试全绿）。
> 注：PRD 称「不修改现有 generate_trend_chart()」，代码中实际函数名为 `render_trend_chart`（`src/reporter.py`）——本次不动其函数体。

## 任务概要

- **目标**（引用 PRD Goal）：在现有 VIX/VXN/MOVE 三面板趋势图基础上，新增两张按市场拆分的趋势图：
  1. 美股大盘趋势图（2×1）：标普500（gspc）、纳斯达克（ixic）→ `reports/charts/YYYY-MM-DD-us-trend.png`
  2. A股大盘趋势图（3×1）：上证（sh）、深证（sz）、创业板（cyb）→ `reports/charts/YYYY-MM-DD-cn-trend.png`
- **Python 侧职责**：`src/reporter.py` 新增通用趋势图函数 `render_market_trend_chart(history, date, market)`（支持 2×1/3×1 布局、独立 5s 限时、子图数据不足显示占位文案）；`render_report` 新增两个图表引用章节；`daily_report.py` 接线生成两张新图并传入报告；复用现有绘图风格；**不改** `render_trend_chart`；零新依赖、零新配置。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，基线 186，新增 test_phase9.py）
  - `venv/Scripts/python daily_report.py`（日报闭环，检查 reports/charts/ 三张图 + 报告三处引用）
  - 新图真实渲染检查：`inspect_image` 确认线条/标签/端点样式与波动率图一致、无中文乱码

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| `render_trend_chart`（`src/reporter.py`） | 三面板（move/vxn/vix）趋势图：matplotlib 懒加载（Agg）、daemon 线程 + `join(CHART_TIMEOUT=15)` 限时（Windows 无 SIGALRM）、排除当日记录、取最近 `TREND_DAYS=30`、行数 <2 返回 None、图表文本一律英文、datetime x 轴（`%m-%d` + `DayLocator(7)`）、figsize (10, 7.6)、dpi=150、`tight_layout` + `bbox_inches="tight"`。**本次函数体不动**（PRD 约束） |
| `render_report`（`src/reporter.py`） | 单 f-string 模板：美股大盘表 + 条件 `us_sector_block` → A 股大盘表 → A 股热点/领跌板块 → 波动率表 → 条件「## 📉 近30日趋势」章节 → 市场状态 → 总结。**新章节插点**：us 图插在美股大盘板块（含 sector block）之后；cn 图插在 A 股大盘表之后 |
| `daily_report.py` 编排 | `render_trend_chart(load_history(), date)` 与 `build_statuses(..., load_history())` 各读一次 history——可收敛为单次 `load_history()` 复用（1 行改动，不改变行为） |
| history 数据形态 | 记录 `{"date", gspc, ixic, sh, sz, cyb, vix, vxn, move}`（小写键），单源取数失败当日存 null → 市场序列可能整列 null 或断点；`load_history()` 90 天滚动、损坏按空历史 |
| 测试基线 | 186 条全绿；`TestTrendChart` 用真实 matplotlib 渲染到 tmp_path（monkeypatch `rep.CHARTS_DIR`）；`make_history` 只填 vix/vxn/move 键，新测试需自建市场键历史辅助函数 |
| 文档漂移（顺带修正） | `docs/architecture.md`/`docs/pitfalls.md`/`docs/commands.md` 记载趋势图限时 3s（`join(3)`），**代码实为 `CHART_TIMEOUT=15`**——本次触碰趋势图文档时顺带修正为 15s，并补新图 5s |

## 设计决策

### PRD 已确认约束（直接落实，不可改）

1. 新增两张图：美股 2×1（gspc/ixic）、A股 3×1（sh/sz/cyb）；文件名定稿 `YYYY-MM-DD-us-trend.png` / `YYYY-MM-DD-cn-trend.png`。
2. 复用现有绘图风格（颜色、字体、网格、日期格式）。
3. 独立失败：任一图失败不影响其他图和日报。
4. 数据不足时子图显示占位文案。
5. 绘图时间 ≤5 秒（单图）。
6. 不修改现有 `render_trend_chart`（PRD 称 generate_trend_chart）。
7. 日报中新增两个引用章节。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **通用函数 + 市场注册表**：`render_market_trend_chart(history, date, market)`，market ∈ {"us", "cn"}；模块级注册表 `MARKET_CHART_PANELS`（键/标签/配色）+ `MARKET_CHART_TITLES`（图标题）+ 文件名 `{date}-{market}-trend.png`，行数由面板数推导（2→(10, 5.4)，3→(10, 7.6)）。**不开放任意 panels/layout 参数** | PRD「新增通用趋势图函数，支持 2×1 和 3×1 布局」；注册表式满足通用性又不过度抽象；行数推导保证两布局比例协调。注意：图表市场键 `us`/`cn` 与 fetcher 快照 `MARKETS` 的 `a-share`/`us` 不同——PRD 文件名定稿 `-us`/`-cn`，以图表自身键为准，两者互不引用 |
| B | **占位文案用英文 "Insufficient Data"**（PRD 写「数据不足」）：有限数据点 <2 的子图中央显示灰色 "Insufficient Data"，不画线 | 既有硬约束「趋势图标签一律英文」（pitfalls：中文字体跨平台渲染不一致）；PRD 中文表述需确认按英文渲染。有限点判定：该序列（排除当日、窗口内）非 null 点 <2 → 占位；≥2 正常画线 + 端点 + 当前值（与现有面板一致） |
| C | **整体跳过规则**：排除当日、窗口内行数 <2 → 返回 None，报告**省略**该图表章节（不放占位图） | 与既有 `render_trend_chart` 行为一致（首跑不产生死链、不生成全占位空图）；PRD「子图显示占位」约束的是**部分序列缺数据**场景（如 gspc 全 null 而 ixic 正常 → 1 线 + 1 占位） |
| D | **配色扩展**（与既有三色同属柔和现代色系，实施时可微调）：us → GSPC `#2b6de8`（蓝，同 VIX）、IXIC `#1a9e6c`（绿）；cn → SH `#d1495b`（红，A股涨红惯例）、SZ `#e07600`（橙，同 MOVE）、CYB `#7b5ce0`（紫） | 风格一致（填充 alpha 0.10、lw 2.3、端点圆点、面板左上标签/右上当前值、无上右边框）与既有面板逐项对齐 |
| E | **限时独立常量**：`MARKET_CHART_TIMEOUT = 5`（PRD ≤5s/图），新函数用 daemon 线程 + `join(5)`；既有 `CHART_TIMEOUT=15` 不动。三图**串行**渲染（start→join 各自独立） | 改 `CHART_TIMEOUT` 会动既有波动率图（违反约束 6）；串行避免 matplotlib 并发绘图竞争（非线程安全） |
| F | **独立失败接线**：`daily_report.py` 对两张新图各自 try/except（记 warning → None）；`render_trend_chart` 既有调用保持原样 | 渲染函数本身线程模型不抛（超时/线程死亡 → None），try/except 为防御同步异常（非法 market 键等）；任一图失败不影响其他图与日报（约束 3） |
| G | **`render_report` 扩展**：追加默认参数 `us_trend_chart=None, cn_trend_chart=None`（位置在 `us_sector_heat` 之后）；非 None 时插入条件章节块：us 图 → 「## 📈 美股大盘近30日趋势」+ `![美股大盘近30日趋势](./charts/...)`，插在美股大盘板块后；cn 图 → 「## 📈 A股大盘近30日趋势」+ `![A股大盘近30日趋势](./charts/...)`，插在 A 股大盘表后。既有波动率章节「## 📉 近30日趋势」位置与文案不动 | 默认参数 → 既有 186 条测试与调用零改动；章节就近其市场板块（数据与图同读）；标题含「近30日趋势」但与既有精确断言 `"## 📉 近30日趋势"` 不碰撞（测试核对过） |
| H | **`daily_report.py` 单次加载 history**：`history = load_history()` 一次，供 `build_statuses` 与三张图共用 | 消除 3 次重复文件读取（原代码 chart 与 statuses 各读一次）；同数据、零行为变化，属本次直接相关的最小收敛 |

## config.json 结构

**不新增任何配置段。** 窗口复用既有 `TREND_DAYS`（config `trend.chart_days`=30）；新图限时用常量 `MARKET_CHART_TIMEOUT=5`（不接入 env/config，与八期 `SECTOR_ALERT_PCT` 同先例——PRD 未要求配置化，保持 diff 最小）。

## 文件清单

### 修改

| 文件 | 改动 | 预估 |
|---|---|---|
| `src/reporter.py` | 新增 `MARKET_CHART_TIMEOUT = 5`、`MARKET_CHART_PANELS`/`MARKET_CHART_TITLES` 注册表、`render_market_trend_chart(history, date, market)`（复用 render_trend_chart 的绘图范式：Agg 懒加载、线程限时、英文标签、datetime x 轴、面板样式逐项对齐）；`render_report` 加 `us_trend_chart=None, cn_trend_chart=None` + 两个条件章节块 | +85 |
| `daily_report.py` | `history = load_history()` 单次加载；两个新图调用（各自 try/except → None）+ rel path 拼接（`./charts/{name}`），与既有 `trend_chart` 同模式；三处传给 `render_report` | +8 |
| `docs/architecture.md` | 模块表 reporter 职责补分市场趋势图；「报告输出」行补 us/cn 图名；决策表加九期行（设计 A-E/G）；**顺带修正 3s → 15s 漂移** | — |
| `docs/commands.md` | 验证矩阵补：三图生成、报告三处引用、子图占位、5s 限时 | — |
| `docs/pitfalls.md` | 九期小节：图表文本英文（"Insufficient Data"）、串行渲染防 matplotlib 竞争、市场键 us/cn 与快照键 a-share/us 不同、history 单次加载 | — |
| `AGENTS.md` | 项目地图：reporter 职责补分市场趋势图；`reports/` 行补 `charts/YYYY-MM-DD-{us,cn}-trend.png` | — |

### 新增

| 文件 | 内容 | 预估 |
|---|---|---|
| `tests/test_phase9.py` | 九期专项测试（见下「测试设计」） | ~+120 |

**不改**：`src/fetcher.py`、`src/analyzer.py`、`src/config.py`、`src/alerter.py`、`snapshot_report.py`、`render_trend_chart`（函数体）、`render_snapshot`、`requirements.txt`、`config.json`、`.env`、既有测试文件（`render_report` 走默认参数，零改动）。

## 测试设计

### 新增 tests/test_phase9.py（不联网，真实 matplotlib 渲染到 tmp_path）

- **TestMarketTrendChart**（monkeypatch `rep.CHARTS_DIR` = tmp_path，自建市场键历史辅助 `make_market_history(n, start, keys)`）：
  - us：30 行 gspc/ixic → 返回 `tmp_path / "2026-09-01-us-trend.png"` 且文件存在。
  - cn：30 行 sh/sz/cyb → `tmp_path / "2026-09-01-cn-trend.png"` 且存在。
  - 行数 <2（1 行 / 空列表）→ None（整体跳过，设计 C）。
  - 仅当日 + 昨日 → 排除当日后 <2 → None。
  - gspc 全 null、ixic 有数据 → 图仍生成（gspc 面板走占位分支，不中断）。
  - 某序列仅 1 个有限点（行数 ≥2）→ 图仍生成（该面板占位，设计 B 边界）。
  - 两序列全 null → 图仍生成（全占位图，不抛异常）。
  - 非法 market（如 "eu"）→ None（防御，不抛）。
- **TestRenderReportMarketCharts**（`render_report(**sample_data(), us_trend_chart=..., cn_trend_chart=...)`）：
  - 两图同传 → 报告含「## 📈 美股大盘近30日趋势」+ `![美股大盘近30日趋势](./charts/2026-09-01-us-trend.png)`、「## 📈 A股大盘近30日趋势」+ cn 图引用。
  - 不传新参数 → 两个新章节标题均不存在（回归既有行为，与 `test_no_trend_section_without_chart` 互证）。
  - 三图同传（trend_chart + us + cn）→ 既有「## 📉 近30日趋势」与两个新标题并存、互不干扰。
  - 章节顺序：us 图在「## 🌏 美股大盘」之后、「## 🇨🇳 A 股大盘」之前；cn 图在 A 股大盘之后、「## 🔥 A 股热点板块 Top 5」之前（锁插位）。

### 既有测试影响

- `render_report` 追加默认参数 → 既有调用（`**sample_data()` + 关键字）零改动。
- `test_trend_section_with_chart` 断言精确串 `"## 📉 近30日趋势"` / `![VIX/VXN/MOVE 近30日趋势](...)`——新章节标题含「近30日趋势」子串但不含该精确串，不碰撞（已核对源码断言）。
- `test_no_trend_section_without_chart` 断言 `"近30日趋势" not in report`——sample_data 不含新键（默认 None），不渲染新章节，断言依旧成立。
- `daily_report.py` 无单测文件（编排由手动验证覆盖，与八期同）。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | reporter：`render_market_trend_chart` + 注册表 + 常量（不改 render_trend_chart） | src/reporter.py | 样式细节与既有图不一致 | `venv/Scripts/python -m pytest tests/test_phase9.py -v`（TestMarketTrendChart）+ 真实渲染 inspect_image 对比 |
| 2 | reporter：`render_report` 加两参数 + 两条件章节块 | src/reporter.py | 章节插位破坏既有模板断言 | `venv/Scripts/python -m pytest tests/test_reporter.py -v`（既有 12 条全绿）+ TestRenderReportMarketCharts |
| 3 | daily_report.py 接线（单次 load_history + 两图调用 + try/except + rel path） | daily_report.py | 参数未透传 / 图未生成 | `venv/Scripts/python daily_report.py` 实际运行，检查三张 PNG + 报告三处引用 |
| 4 | 新增 tests/test_phase9.py | tests/test_phase9.py | 线程限时测试 flaky（本设计不测真实超时，只测返回路径） | `venv/Scripts/python -m pytest tests/test_phase9.py -v` |
| 5 | 文档同步（architecture/commands/pitfalls/AGENTS，顺带修正 3s→15s 漂移） | 上述 4 文件 | 文档与实现漂移 | 逐份核对最终代码 |
| 6 | 手动验证矩阵 + 源码增量核对 + `git diff` 审查 | 全部 | 增量超预算 / 误改 render_trend_chart | 见下方矩阵；`git diff` 确认 render_trend_chart 函数体零改动；源码增量 ≤ ~95 行（reporter 85 + daily 8） |

### 手动验证矩阵（步骤 3/6，实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 三图生成 | `venv/Scripts/python daily_report.py` | `reports/charts/` 同日出现 3 个 PNG：`-trend.png`（原波动率）、`-us-trend.png`、`-cn-trend.png` |
| 报告章节 | 检查 `reports/{date}.md` | 3 处图片引用：📉 近30日趋势（既有）、📈 美股大盘近30日趋势、📈 A股大盘近30日趋势；章节位置正确 |
| 图样检查 | `inspect_image` 分别看 us/cn 图 | 线条/填充/网格/端点/左上标签/右上当前值/日期格式与波动率图一致；标签全英文、无乱码；有数据面板无 "Insufficient Data" |
| 原图回归 | `git diff` | `render_trend_chart` 函数体零改动（PRD 约束 6） |
| 数据不足 | 单测覆盖（<2 行 → None；部分/全部序列 null → 占位不中断） | 见测试设计；真实数据下 A 股休市日 sh/sz/cyb 全 null → cn 图全占位仍生成，日报不崩 |
| 限时 | 代码评审 + 既有线程模式单测 | `MARKET_CHART_TIMEOUT=5`；超时返回 None 不中断日报 |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（基线 186 + 新增 ≈ 200） |
| 恢复 | 图表只读 history，不写任何持久化 | 无模拟数据残留，生产数据无影响 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| **matplotlib 并发绘图竞争**（非线程安全） | 设计 E：三图串行渲染（各自 start→join），不并行起线程 |
| **中文「数据不足」渲染乱码** | 设计 B：占位文案用英文 "Insufficient Data"（既有图表语言约束）；需用户确认 |
| **PRD 函数名与代码不符**（generate_trend_chart vs render_trend_chart） | 按代码实际函数名 `render_trend_chart` 执行"不修改"，已在计划开头标注 |
| **报告章节插入破坏既有模板断言** | 设计 G：默认参数 + 新标题与既有精确断言串不碰撞（已核对）；步骤 2 先跑既有 test_reporter.py |
| **三图顺序渲染最坏 +10s**（两新图各 5s 上限） | PRD 约束 ≤5s/图；断图/超时由 try/except + 线程返回 None 兜底，日报恒退出码 0 |
| **验证 daily_report.py 触发 Yahoo 限流**（既有风险） | 与既有流程同风险、不新增请求数（仍 8 指数取数）；429 时报告缺数据属已知容错，不影响图表功能验证 |
| **文档 3s/15s 漂移** | 本次触碰趋势图文档，顺带修正为代码实值 15s + 新图 5s，防后续误导 |

## 不做什么

- 不改 `render_trend_chart` 函数体（PRD 约束 6）、`render_snapshot`、`snapshot_report.py`、`src/fetcher.py`、`src/analyzer.py`、`src/config.py`、`src/alerter.py`。
- 不加新依赖、不新增 config 段/环境变量（限时用常量，窗口复用 `TREND_DAYS`）。
- 快照入口不加趋势图（PRD 只要求日报）。
- 不重构既有绘图代码提取公共样式函数（动 render_trend_chart 即违反约束；接受新函数与其部分样式重复，已在设计 A 说明）。
- 不改变 context/告警/历史/缓存任何行为（图表只读 history）。
- 不处理图片在 QQ/Hermes 的渲染问题（与既有 `-trend.png` 完全同模式）。

## 预计影响范围

- **新增文件**：`tests/test_phase9.py`（~120 行）。
- **修改文件**：`src/reporter.py`（+85）、`daily_report.py`（+8）、docs 4 份（architecture/commands/pitfalls/AGENTS）。
- **不受影响**：`src/fetcher.py`、`src/analyzer.py`、`src/config.py`、`src/alerter.py`、`snapshot_report.py`、`requirements.txt`、`config.json`、`.env`、既有 9 个测试文件、context JSON 契约（无字段变更）。
- **交付清单（非仓库文件）**：Hermes Prompt 无需改动——context 结构不变；日报新增两个图表引用章节供解读参考（与既有波动率图同模式）。

## 确认

- [ ] 人已审阅计划
- [ ] 设计 A（通用函数 + 市场注册表 us/cn，图表键与快照 MARKETS 键不同）/ B（占位文案英文 "Insufficient Data"，有限点 <2 判定）/ C（整体 <2 行 → None 省略章节；部分序列缺数据 → 子图占位）/ D（配色：GSPC 蓝、IXIC 绿、SH 红、SZ 橙、CYB 紫，可微调）/ E（`MARKET_CHART_TIMEOUT=5` 新常量，既有 15s 不动，串行渲染）/ F（两新图各自 try/except 独立失败）/ G（`render_report` 默认参数 + 章节插位：us 图在美股大盘后、cn 图在 A 股大盘后）/ H（daily_report 单次 load_history 复用）已确认
- [ ] PRD「数据不足」按英文 "Insufficient Data" 渲染已确认（图表语言英文是既有硬约束）
- [ ] 既有 `render_trend_chart` 函数体零改动（PRD 约束 6）已确认
- [ ] 既有 186 条测试零改动（`render_report` 默认参数）已确认
- [ ] 没有遗漏测试（两图生成/文件名/整体跳过/当日排除/部分序列占位/全 null 占位/非法 market/报告章节存在与缺席/三图共存/插位顺序全覆盖）
- [ ] 没有引入不必要依赖或额外配置段
