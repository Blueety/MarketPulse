# 实施计划 — MarketPulse 二期「盘中感知 + 可视化」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase2/prd.md`

## 任务概要

- **目标**（引用 PRD Goal）：在现有每日收盘日报基础上增加两个新能力 ——
  1. **盘中快照**：美东 12:30 生成午盘简报（`reports/snapshots/YYYY-MM-DD-noon.md`），仅记录数据不推送；
  2. **趋势图**：matplotlib 生成 VIX/VXN/MOVE 近 30 日走势图，嵌入收盘报告。
  同时完成结构演进：`daily_report.py` 拆为 `src/fetcher.py` + `src/analyzer.py` + `src/reporter.py`，入口变约 50 行编排，`snapshot_report.py` 复用 fetcher。市场情绪感知从「次日看结果」升级为「盘中跟踪 + 可视化回顾」。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md）：
  - `venv/Scripts/pip install -r requirements.txt`（装 matplotlib）
  - `venv/Scripts/python -m pytest tests/ -v`（全部测试）
  - `venv/Scripts/python daily_report.py`（收盘闭环）
  - `venv/Scripts/python snapshot_report.py`（午盘快照）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| `daily_report.py` | 300 行，15 个函数：常量（SYMBOLS/阈值/路径/TZ）→ 纯逻辑层（classify/compute/build_*）→ 格式化（fmt_*）→ 数据获取层（fetch_*）→ 缓存层（load/save_last_values）→ 渲染（render_report）→ 编排（main） |
| `tests/test_daily_report.py` | 182 行，32 个测试，全部 `import daily_report as dr` 调用纯逻辑函数（不联网） |
| matplotlib | 未安装；venv 为 Python 3.14（cpython-314），安装时需确认 cp314 wheel |
| `.gitignore` | 已排除 `reports/`、`data/` → `reports/charts/`、`reports/snapshots/`、`data/history.json` 自动不入库，无需改 |
| `src/` | 空目录（脚手架占位，本项目此前不用，二期启用） |

## 模块划分决策（关键设计）

- **SYMBOLS 放 `fetcher.py`**（symbol→ticker/source 的注册表，fetcher 是数据源归属方），analyzer/reporter 从 fetcher 导入；状态阈值（VIX_CALM 等）放 analyzer。
- **路径常量放 `analyzer.py`**：`BASE_DIR = Path(__file__).resolve().parent.parent`，`REPORTS_DIR`/`DATA_DIR`/`LAST_VALUES_FILE`/`HISTORY_FILE` 全在此定义，reporter 与入口导入，避免三处重复计算。
- **格式化函数（fmt_value/fmt_change）放 analyzer**：`build_summary` 内部用到 `fmt_value`，reporter 需用时从 analyzer 导入。
- **src 内模块互引用用相对导入**（`from .fetcher import ...`）；两个入口脚本在项目根，用绝对导入 `from src import ...`（脚本目录在 sys.path，Hermes 任意 cwd 运行均可靠）。新增空 `src/__init__.py` 显式包化，规避命名空间包在个别工具下的路径坑。
- **图表懒加载 + 超时保护**：`matplotlib.use("Agg")` 与 `pyplot` 导入放在 `render_trend_chart` 函数内部（Agg 无头后端，适配 Hermes 无显示环境；懒加载避免快照/失败路径被拖慢）。**Windows 无 signal.SIGALRM**，3 秒限时用「daemon 线程 + `join(3)`」实现：超时记日志、跳过绘图，报告趋势章节改为文字说明（不产生死链）。
- **history.json 写策略**：每日收盘运行追加当日记录；**同日重复运行按 date 键覆盖**（不产生重复条目）；仅保留最近 90 条；任一指数取数失败存 null（趋势图按 NaN 断点处理）；追加采用「临时文件 + os.replace」原子写，避免半截 JSON。**快照不写 history.json**（避免多时点写冲突，PRD 已定）。

## 文件清单

### 新增

| 文件 | 内容 | 预估行数 |
|---|---|---|
| `src/__init__.py` | 空包标记 | ~1 |
| `src/fetcher.py` | SYMBOLS、TIMEOUT/RETRIES、_SESSION、fetch_with_retry、fetch_vix_vxn、fetch_all | ~80 |
| `src/analyzer.py` | get_us_eastern_date、classify_vix/move、compute_changes、build_statuses、build_summary、fmt_value/fmt_change、路径常量、load/save_last_values、history 读写 + 90 天滚动 | ~130 |
| `src/reporter.py` | render_report（含趋势章节）、render_trend_chart（Agg + 3s 限时）、save_report、save_snapshot | ~120 |
| `snapshot_report.py` | 独立入口：取数 → 分类 → 渲染午盘快照 → 落盘（不读缓存/不算涨跌幅/不写历史/不推送） | ~40 |
| `tests/test_analyzer.py` | 迁移 classify/compute/statuses/summary/date/fmt 测试 + 新增 history 追加/覆盖/90 天滚动/损坏容错测试 | ~120 |
| `tests/test_reporter.py` | 迁移 render_report 测试 + 新增趋势图 PNG 生成/引用路径/空历史跳过/快照渲染测试 | ~90 |

### 修改

| 文件 | 改动 |
|---|---|
| `daily_report.py` | 重写为 ~50 行编排：取数 → 读 last_values/history → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 追加 history → 写 last_values |
| `requirements.txt` | 仅新增 `matplotlib>=3.7.0` |
| `docs/architecture.md` | 模块划分/数据流/关键决策/约束同步二期结构 |
| `docs/commands.md` | 新增 snapshot 命令与 charts 验证点 |
| `docs/pitfalls.md` | 任务完成后追加可复用规则（按 AGENTS.md 要求） |
| `README.md` | 运行方式补 snapshot_report.py |
| `AGENTS.md` | 项目地图补 src/、snapshot_report.py、history.json |

### 删除

| 文件 | 说明 |
|---|---|
| `tests/test_daily_report.py` | 内容按函数归属迁入 test_analyzer.py / test_reporter.py 后删除（git 视为 rename+edit） |

### Hermes 侧配置（非仓库文件，交付时需确认落地，否则快照不会自动生成）

1. **新增 cron**：北京时间次日 00:30（美东 12:30）运行 `python snapshot_report.py` —— 仅生成 `reports/snapshots/YYYY-MM-DD-noon.md`，**不推送**，用户按需查看。
2. **收盘 cron（早 8 点）改造**：推送时把当日 `reports/charts/YYYY-MM-DD-trend.png` 作为图片附件一并推给 QQ。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | requirements.txt 加 `matplotlib>=3.7.0` 并安装 | requirements.txt | cp314 无 wheel → 报错退出，需换版本 | `venv/Scripts/pip install -r requirements.txt` + `venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"` |
| 2 | 建 `src/__init__.py` + `src/fetcher.py`，迁移 fetch 层与 SYMBOLS | src/__init__.py, src/fetcher.py | 无（纯搬移，逻辑不变） | `venv/Scripts/python -c "from src.fetcher import fetch_all, SYMBOLS"` |
| 3 | 建 `src/analyzer.py`，迁移纯逻辑层 + 格式化 + 缓存层，新增 history 读写/滚动 | src/analyzer.py | history 日期键语义、损坏文件容错 | `venv/Scripts/python -c "from src.analyzer import classify_vix, load_history"` + 后续 pytest 迁移测试 |
| 4 | 建 `src/reporter.py`，迁移 render_report（加趋势章节占位），新增 render_trend_chart / save_snapshot | src/reporter.py | matplotlib 冷启动超时 → 3s 线程限时兜底 | `venv/Scripts/python -c "from src.reporter import render_report, render_trend_chart"` |
| 5 | 重写 `daily_report.py` 为编排入口（追加 history + 嵌入趋势图） | daily_report.py | 断网/单源失败时 history 记 null 不中断 | `venv/Scripts/python daily_report.py` → 检查 reports/YYYY-MM-DD.md 含趋势章节、reports/charts/YYYY-MM-DD-trend.png 存在、data/history.json 已追加 |
| 6 | 新建 `snapshot_report.py` 独立入口 | snapshot_report.py | 无（只读数据不写历史） | `venv/Scripts/python snapshot_report.py` → 检查 reports/snapshots/YYYY-MM-DD-noon.md 内容 |
| 7 | 测试迁移 + 新增（history 滚动、趋势图生成、快照渲染、空历史跳过） | tests/test_analyzer.py, tests/test_reporter.py, 删 tests/test_daily_report.py | 迁移遗漏断言 → 逐类对照原 32 测试 | `venv/Scripts/python -m pytest tests/ -v` 全绿且用例数 ≥ 32 + 新增 |
| 8 | 专项验证：断网容错、90 天滚动、行数预算、git diff 审查 | 全部 | 见风险表 | 断网运行不崩且报告标注失败；构造 95 条 history 运行后剩 90；`wc -l` 五文件 ≤ 600；`git diff` 审查改动范围 |
| 9 | 文档同步（architecture/commands/pitfalls/README/AGENTS.md） | docs/, README.md, AGENTS.md | 文档与实现漂移 | 逐份核对内容与最终代码一致 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| 趋势图中文标签跨平台渲染不一致 | 图表全程英文标签（"VIX (30D)" / "VXN" / "MOVE" / "Date" / "Value"），PRD 强制约束 |
| matplotlib 冷启动/渲染超时 | Agg 后端 + 懒加载；Windows 无 SIGALRM → daemon 线程 join(3) 超时则跳过绘图，报告趋势章节写文字说明，不中断整体 |
| history.json 损坏 / 半截写入 / 同日重复运行 | 原子写（临时文件 + os.replace）；解析失败按空历史处理；按 date 键覆盖当日记录 |
| history.json 无限膨胀 | 每次追加后裁剪至最近 90 条（单元测试覆盖） |
| 快照与收盘并发写历史冲突 | 快照不写 history.json（PRD 已定），唯一写入方是收盘 cron 单次运行 |
| src 导入路径问题（Hermes cwd 不确定） | 入口脚本留在项目根，`from src import ...` 依赖脚本目录入 sys.path；空 `src/__init__.py` 显式包化 |
| 趋势图数据含 null（单源失败） | 每线过滤非有限值，按 NaN 断点绘制，不中断 |
| 行数超 600 预算 | 模块划分已定行数目标（合计约 400，余量充足），步骤 8 用 wc -l 硬校验 |
| 盘中快照调度未落地 | 已列入「Hermes 侧配置」交付项，实施完成后向用户确认两条 cron 均生效 |

## 不做什么

- 不修改 `.env`、生产配置、`data/` 与 `reports/` 下既有生成文件。
- 不扩展 `last_values.json` 结构（仍只作涨跌幅基准）。
- 不引入 matplotlib 之外的任何新依赖。
- 不实现推送逻辑（推送是 Hermes 职责，脚本只产出文件）。
- 不重构 SYMBOLS 的 `source` 字段（保留作来源标注，一期 journal 已注明）。
- 不改动已有纯逻辑行为（classify 阈值、涨跌幅公式、报告模板主体）。

## 预估 diff 范围

- **新增文件**：`src/__init__.py`、`src/fetcher.py`、`src/analyzer.py`、`src/reporter.py`、`snapshot_report.py`、`tests/test_analyzer.py`、`tests/test_reporter.py`（另运行时生成 `data/history.json`、`reports/charts/`、`reports/snapshots/`，均被 .gitignore 排除）
- **修改文件**：`daily_report.py`（300→约 50 行重写）、`requirements.txt`（+1 行）、`docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`README.md`、`AGENTS.md`
- **删除文件**：`tests/test_daily_report.py`（内容迁入两个新测试文件）

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理
- [ ] 没有遗漏测试
- [ ] 没有引入不必要依赖
