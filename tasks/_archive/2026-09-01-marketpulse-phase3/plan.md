# 实施计划 — MarketPulse 三期「阈值告警」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase3/prd.md`

## 任务概要

- **目标**（引用 PRD Goal）：在现有日报基础上增加**主动监控能力** —— 当 VIX/VXN/MOVE 的当日变化率超过预设阈值（默认 ±20% / ±20% / ±15%）时，生成独立告警文件 `alerts/YYYY-MM-DD-{type}.md`，由 Hermes 检测并独立推送一条警报消息，实现"被动收日报 → 主动收警报"。午盘快照（12:30）与收盘日报（16:30）均检查告警；同一指数当日只告警一次（午盘触发则收盘跳过）。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，含新增告警测试）
  - `venv/Scripts/python daily_report.py`（收盘闭环 + 收盘告警）
  - `venv/Scripts/python snapshot_report.py`（午盘快照 + 午盘告警）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| `snapshot_report.py` | 39 行，当前**不读 last_values、不算涨跌幅** —— 三期需新增只读缓存作为告警基准（决策 1） |
| `daily_report.py` | 69 行编排；`last_values` 在开头加载、末尾才写回 —— 告警检查必须**在 save_last_values 之前**使用已加载的旧缓存 |
| `src/analyzer.py` | 已有 `compute_changes`（涨跌幅）、`classify_vix/move`（状态）、路径常量（BASE_DIR/DATA_DIR）—— `check_breach()` 落位处 |
| 路径常量 | 二期决策"路径常量放 analyzer.py"：`ALERTS_DIR` / `ALERTS_LOG` 延续此约定，alerter/reporter 从 analyzer 导入 |
| 依赖 | requests / matplotlib / pytest，告警逻辑只需标准库（os/json/pathlib），**零新增依赖** |
| `.gitignore` | 已排除 `reports/`、`data/`；`alerts/` 需新增一行排除 |
| `data/alerts.log` | 不存在，三期新建；`data/` 已被 gitignore 覆盖，无需额外配置 |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **告警基准**：统一用 `data/last_values.json`（昨收缓存）。午盘快照读取该缓存做告警判断，**只读、不写 history.json**。
2. **去重时序**：午盘触发则收盘跳过同一指数，午盘未触发则收盘正常判断。当日已触发状态记在 `data/alerts.log`。
3. **默认阈值**：VIX ±20% / VXN ±20% / MOVE ±15%。环境变量 `ALERT_THRESHOLD_VIX` 等为覆盖后的值，未设置时用默认值。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | `check_breach()` 触发判定：`abs(变化率) > 阈值`（"超过"取严格大于，恰好等于**不**触发） | PRD 措辞"变化幅度超过此值时触发"；边界由测试锁定 |
| B | 告警级别：触发即 `WARN`；当前值处于恐慌区间（`classify` 返回"恐慌"）升级为 `ALERT` | PRD 要求输出 WARN/ALERT 但未定义语义；复用已确认的 classify 区间，零新增配置 |
| C | `alerts.log` 行式文本 `YYYY-MM-DD SYMBOL`，每次写入原子重写为**仅当日行**；缺失/损坏按空处理 | 满足"当日、简单文本"；文件不无限膨胀；容错风格与 last_values/history 一致 |
| D | 一个检查点一个文件 `alerts/YYYY-MM-DD-{type}.md`（type = noon / close）；同文件内多指数各占一个附录块（frontmatter + 标题 + 字段），块间 `---` 分隔 | PRD 固定文件名 `{type}`；多指数同日触发不冲突 |
| E | "相关报告"引用本次运行刚生成的文件（午盘 → 快照文件；收盘 → 日报文件） | 诚实引用；午盘检查时收盘日报尚不存在 |
| F | 建议文案按状态分档（平静/警惕/恐慌各一句，≤ 1 行） | PRD"简短建议不超过 2 行"；确定性文案，可单测断言 |
| G | 告警检查位置：收盘在 `save_report` 之后、`append_history`/`save_last_values` 之前，用开头已加载的旧 `last_values` 作基准 | PRD 执行顺序"取数→报告→检查告警→写告警文件"；避免误用当日新缓存 |
| H | 容错：`run_alert_checks` 内逐指数 try/except，调用方再包一层 try/except | PRD"告警逻辑失败不影响日报生成"，任何告警异常只记日志 |

## 文件清单

### 新增

| 文件 | 内容 | 预估行数 |
|---|---|---|
| `src/alerter.py` | 告警文件渲染（附录格式，含 frontmatter）、去重状态读写（alerts.log）、`run_alert_checks` 编排（逐指数 check_breach → 去重过滤 → 写文件 → 标记已告警） | ~90 |
| `tests/test_alerter.py` | check_breach 边界/触发/级别/env 覆盖、去重当日与跨日、渲染格式断言、run_alert_checks 端到端（tmp 目录，不联网） | ~90 |

### 修改

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | 新增常量 `ALERT_THRESHOLDS`（VIX 20 / VXN 20 / MOVE 15）、`ALERTS_DIR`、`ALERTS_LOG`；新增 `alert_threshold()`（env 覆盖 + 默认 + 非法值回退）、`check_breach()`（纯函数） | ~35 |
| `daily_report.py` | `save_report` 后调用 `run_alert_checks(date, values, last_values, "close", report_path)`，try/except 包住 | +5 |
| `snapshot_report.py` | 新增 `load_last_values()` 只读（不写任何缓存），快照落盘后调用 `run_alert_checks(..., "noon", snapshot_path)`，try/except 包住 | +6 |
| `.gitignore` | 新增 `alerts/` 一行（运行时生成） | +1 |
| `.env.example` | 补三个阈值环境变量示例（含"覆盖默认 20/20/15"注释） | +5 |
| `docs/architecture.md` | 模块表加 alerter、数据流加告警分支、关键决策加三期三条已确认决策 + 设计选择 A/B/D/G | — |
| `docs/commands.md` | 验证要点补告警 5 项（对应 PRD Verification） | — |
| `docs/pitfalls.md` | 追加：告警基准须在 save_last_values 前使用、alerts.log 仅保留当日、测试需 `monkeypatch.delenv` 隔离阈值 env、路径常量打补丁位置 | — |
| `AGENTS.md` | 项目地图补 `src/alerter.py`、`alerts/`、`data/alerts.log` | — |

**不改**：`src/fetcher.py`、`src/reporter.py`、`requirements.txt`（无新依赖）、`.env`、`README.md`（运行方式不变，复用两入口）。

### Hermes 侧配置（交付项，非仓库文件，实施完成后需确认落地）

1. **午盘 cron**（北京时间次日 00:30，二期已建）：运行完 `snapshot_report.py` 后检测 `alerts/YYYY-MM-DD-noon.md`，存在则独立推送该文件内容（与快照简报分开）。
2. **收盘 cron**（早 8 点，二期已建）：推送日报时检测 `alerts/YYYY-MM-DD-close.md`（及当日可能遗漏的 noon 文件），存在则**独立推送一条告警消息**。
3. 告警文件按日期命名天然隔离，次日 cron 不会误检旧文件；建议 Hermes 推送后删除当日文件，防止 `alerts/` 无限增长（可选清理策略，Hermes 侧定）。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | `analyzer.py` 新增常量 + `alert_threshold()` + `check_breach()` | src/analyzer.py | env 非法值、边界等于阈值 | `venv/Scripts/python -c "from src.analyzer import check_breach, alert_threshold"` + 步骤 4 测试 |
| 2 | 新建 `src/alerter.py`（渲染/去重/编排） | src/alerter.py | 路径常量导入绑定坑 | `venv/Scripts/python -c "from src.alerter import run_alert_checks"` + 步骤 4 测试 |
| 3 | 两入口接入告警（收盘/午盘），try/except 兜底 | daily_report.py, snapshot_report.py | 告警异常中断主流程 | `venv/Scripts/python daily_report.py`、`snapshot_report.py` 均退出码 0 |
| 4 | 新建 `tests/test_alerter.py` + 全量回归 | tests/test_alerter.py | env 变量泄漏进测试 | `venv/Scripts/python -m pytest tests/ -v` 全绿（原 49 + 新增） |
| 5 | 手动验证（PRD Verification 5 项） | data/last_values.json（临时改，事后恢复） | Yahoo 限流致取数失败 → 数据缺失跳过属设计行为 | 见下方「手动验证矩阵」 |
| 6 | 行数预算 + git diff 审查 | 全部 | — | `wc -l` 告警相关增量 ≤ 150；`git diff` 核对改动范围 |
| 7 | 文档同步 + journal.md | docs/, AGENTS.md, .gitignore, .env.example | 文档与实现漂移 | 逐份核对与最终代码一致 |

### 手动验证矩阵（步骤 5，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 触发告警 | 编辑 `data/last_values.json` 使 VIX 基准 ≈ 当前值 / 1.22（模拟 +22%），运行 `daily_report.py` | 生成 `alerts/YYYY-MM-DD-close.md`，内容含 VIX 当前值/昨日收盘/变化率/阈值/状态/建议/报告路径，格式符合附录 |
| 午盘→收盘去重 | 先跑 `snapshot_report.py` 触发 VIX 午盘告警，再跑 `daily_report.py`（同 +22% 场景） | close 文件不含 VIX；VIX 变化率超阈值但被 `alerts.log` 跳过 |
| env 覆盖 | `ALERT_THRESHOLD_VIX=30 venv/Scripts/python daily_report.py`（+22% 场景） | 不再生成 VIX 告警（22 < 30），覆盖生效 |
| 数据缺失/断网 | 断网或取数全失败时运行两入口 | 不崩溃、退出码 0、无告警文件（check_breach 对缺失数据返回 None） |
| 恢复 | 验证完成后恢复 `data/last_values.json` 原值 | 缓存回归真实值（pitfalls 既有教训：验证后必须恢复） |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| 告警基准误用当日新缓存 | 决策 G：告警检查固定用开头加载的旧 `last_values`，且置于 `save_last_values` 之前；测试覆盖该语义 |
| 路径常量打补丁不生效 | 沿用二期教训：alerter 导入时绑定 `ALERTS_DIR`/`ALERTS_LOG`，测试必须 `monkeypatch.setattr(al, "ALERTS_DIR", ...)`；写入 pitfalls |
| 阈值 env 变量泄漏进测试 | 测试用 `monkeypatch.delenv("ALERT_THRESHOLD_VIX", raising=False)` 隔离；写入 pitfalls |
| Yahoo 限流致取数失败 | 数据缺失 → `check_breach` 返回 None 跳过，不产生告警文件（设计行为）；手动验证用改缓存模拟，不依赖网络 |
| 阈值过敏感频繁触发 | 默认 20% 已过滤日常波动；用户可 env 调高 |
| 告警逻辑异常拖垮日报 | 决策 H：逐指数 try/except + 调用方兜底，仅记日志，退出码恒 0 |
| 告警代码超 150 行预算 | 目标 ~130 行（alerter 90 + analyzer 35 + 入口 5），步骤 6 用 wc -l 硬校验 |
| Hermes 告警推送未落地 | 列为交付项；实施完成后与二期 cron 一并确认生效 |

## 不做什么

- 不实现推送（Hermes 负责检测 `alerts/` 并推送，QQ 渠道沿用）。
- 不新增第三方依赖（告警逻辑只用标准库）。
- 不修改 `.env`、生产配置、`reports/`、`data/` 既有生成文件（验证期临时改 `last_values.json` 后恢复）。
- 不改 classify 阈值、报告模板、fetcher/reporter 行为。
- 快照不写 history.json（决策 1，保持二期行为）。
- 告警级别不做第二档阈值配置（WARN/ALERT 语义见设计选择 B；如需可后续加配置）。

## 预计影响范围

- **新增文件**：`src/alerter.py`（~90 行）、`tests/test_alerter.py`（~90 行）；运行时生成 `alerts/`（gitignore 排除）、`data/alerts.log`（data/ 已排除）。
- **修改文件**：`src/analyzer.py`（+~35 行）、`daily_report.py`（+5 行）、`snapshot_report.py`（+6 行）、`.gitignore`（+1 行）、`.env.example`（+5 行）、`docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`AGENTS.md`。
- **不受影响**：`src/fetcher.py`、`src/reporter.py`、`requirements.txt`、`.env`、`README.md`、Hermes 二期 cron（三期仅在其上追加告警检测与推送）。

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理
- [ ] 设计选择 A（严格大于触发）/ B（恐慌区间=ALERT）/ C（alerts.log 行式仅当日）/ D（多指数合一个文件）/ E（报告引用本次文件）/ F（建议文案按状态分档）已确认
- [ ] Hermes 侧配置（检测 `alerts/` 并独立推送、推送后清理）为交付项，实施完成后需落地
- [ ] 没有遗漏测试（check_breach 边界/去重/渲染/编排全覆盖，联网场景手动验证）
- [ ] 没有引入不必要依赖
