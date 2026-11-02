# 四期实施日志 — MarketPulse「AI 解读 + 异动归因分析」

> 日期：2026-08-29（实施日）/ 2026-09-01（任务目录日期）
> 计划：`plan.md`（架构师 K2.7 产出、用户已审阅）；本日志供下次会话快速接手。

## 目标

在收盘日报链路末端新增 `context/YYYY-MM-DD.json`（indices + history_30d + breach + search_keywords），
供 Hermes 全自动读取 → 常规解读 →（异动日）tavily 搜索归因 → 追加日报并推送。
Python 侧只做数据产出，不引入任何 LLM/搜索 SDK（决策 G）。

## 改动文件清单

| 文件 | 改动 | 验证 |
|---|---|---|
| `src/analyzer.py` | +17：`CONTEXT_DIR` 常量 + `build_search_keywords()` 纯函数（方向感知 surge/drop，异动日 3-5 词、常规日 1 词） | 导入 + 14 条新测试 |
| `src/alerter.py` | +9：新增 `collect_breaches()` 纯计算导出（不写文件/不改 alerts.log，幂等）；`run_alert_checks` 重构复用（去重/写文件/标记逻辑原样） | 既有 23 条 alerter 测试全绿 |
| `src/reporter.py` | +62：导入 json/os/新符号；`_breach_item()` 字段映射（PRD 契约）+ `generate_context()`（append_history 后调用，临时文件 + os.replace 原子写） | 导入 + 14 条新测试 + 全量回归 |
| `daily_report.py` | +7：末尾（save_last_values 后、return 0 前）接入 `generate_context`，try/except 兜底 | 完整闭环运行退出码 0 |
| `tests/test_context.py` | 新增 190 行 / 14 条：关键词边界（0/1/2/3 异动、方向、计数 3-5）、_breach_item 精度、generate_context 端到端（常规/异动/全源失败/幂等/30 日窗口/原子写，tmp 不联网） | 14 passed |
| `.gitignore` | +1：`context/` | check-ignore 验证 |
| `docs/architecture.md` | 概览/模块表（上下文输出行）/数据流/关键决策补四期 A-G/行数约束（四期后 832） | 与代码核对 |
| `docs/commands.md` | 验证要点 +5（context 异动模拟/常规日/断网/幂等/恢复） | 与实现核对 |
| `docs/pitfalls.md` | +8：四期易错点（CONTEXT_DIR 导入绑定补丁、原子写、append_history 时序、方向词语义、breach 字段契约、collect_breaches 无副作用） | 与实现核对 |
| `AGENTS.md` | 项目地图补 context/、generate_context、collect_breaches、test_context.py | 与实现核对 |

**未改**：`src/fetcher.py`、`snapshot_report.py`（决策 F）、`requirements.txt`（零新依赖）、`.env`/`.env.example`（TAVILY_API_KEY 属 Hermes 侧）、既有渲染/分析函数。

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 1 analyzer | `python -c "from src.analyzer import build_search_keywords, CONTEXT_DIR"` | 通过（方向/计数正确） |
| 2 alerter | `python -c "from src.alerter import collect_breaches"` + `pytest tests/test_alerter.py` | 通过（23/23） |
| 3 reporter | `python -c "from src.reporter import generate_context"` | 通过 |
| 4 入口闭环 | `python daily_report.py` | 退出码 0，context 生成（当时 Yahoo 403 限流全源失败 → 天然覆盖"断网/全源失败"场景：日报正常、breach=false、退出码 0） |
| 5 新测试 | `pytest tests/test_context.py -v` | 14/14 |
| 全量回归 | `pytest tests/ -q` | **86/86 全绿**（原 72 + 新增 14） |
| 手动矩阵 | `manual_matrix.py`（stub 取数 + 恢复基准缓存，见下） | ALL PASS（16 项断言） |

### 手动验证矩阵（stub 说明）

Yahoo 对本机 IP 持续 403/429 限流（pitfalls 已知），取数必失败 → `daily_report.main()` 内
`load_last_values()` 读真实缓存作告警基准，故矩阵脚本每次运行前把 `data/last_values.json`
写回基准态（VIX 20.0 / VXN 18.0 / MOVE 75.0），stub `fetch_all` 返回固定收盘值，精确构造场景：

- **异动日**（VIX +22%、VXN +22.2%）：退出码 0；`breach.triggered=true`；VIX 明细精确匹配
  `{name, current:24.4, previous:20.0, change_pct:22.0, threshold:20.0, level:WARN}`；
  search_keywords 4 个含 "VIX surge 2026-08-29"；告警文件 `alerts/2026-08-29-close.md` 生成。
- **幂等**：恢复基准重跑同场景 → context 覆盖、JSON 有效、breach 保持；`alerts/` 目录无新增；
  `data/alerts.log` 前后一致；无 `.json.tmp` 残留。
- **常规日**（VIX +5% 等）：`triggered=false`、`indices=[]`、`search_keywords==["market summary 2026-08-29"]`。
- **恢复**：还原 `data/history.json` / `data/last_values.json`（VIX 14.43）/ `reports/2026-08-29.md` /
  `context/2026-08-29.json` 备份，删除验证期产物（`alerts.log`、`alerts/2026-08-29-close.md`、
  `charts/2026-08-29-trend.png`）。`git status` 干净，无生成物残留。

### 行数预算

四模块 + 两入口：三期基线 738 → 四期后 **832**（增量 94）。计划预算 ≤ ~80，超 14 行，
主因 reporter 导入展开（单行 → 多行 10 个符号，+10）与 JSON payload 结构；`docs/architecture.md`
行数约束已按实际值修正（四期起 ≤ ~840，context 增量 ≤ ~95）。

## 遇到的问题

1. **edit 工具块替换多次误吞相邻代码**：daily_report.py 的 `save_last_values` 块被删、
   `return 0` 重复；reporter.py 的 `save_snapshot`/`render_snapshot` 函数体被吞；
   AGENTS.md/architecture.md/commands.md/pitfalls.md 编辑时锚定行被替换。
   全部已通过逐文件 diff 修复并全量回归确认（86 全绿）。**教训：多行编辑优先用 write 整体重写，
   或严格使用 `⟪old│new⟫` 内联选择，避免无标记块。**
2. **daily_report.py 曾误删 fetcher 导入**（同属编辑事故），运行时报 `NameError: fetch_all`，
   py_compile 不报（运行时才暴露）——修复后已用完整闭环验证。
3. **矩阵脚本预期错误**（非实现 bug）：首次断言假设 last=20.0 但 main() 读真实缓存（VIX 14.43，
   +69.09%）——修正为"每次运行前恢复基准缓存"后符合矩阵语义。

## 下次注意什么

- **Yahoo 限流持续**：本机取数 403/429，手动验证异动场景必须用 stub 取数（见
  `tasks/2026-09-01-marketpulse-phase4/tmp/manual_matrix.py`，gitignore 排除）。
- **context 契约变更**：`_breach_item` 字段名 / `search_keywords` 方向词是 Hermes Prompt 的输入，
  改代码必须同步 Hermes Prompt（交付配置项，非仓库文件，尚未落地——需与用户确认）。
- **Hermes 侧待办**（交付项 G）：market-analyst Prompt（常规解读 200-300 字 / 异动归因 300-400 字
  + 免责声明）、收盘 cron 接线（读 context → 解读 → 异动日 tavily 归因 → 追加日报 → 推送，
  AI 归因 ≤30 秒超时跳过）、容错（context 读取失败跳过 AI 解读仍推送）。详见 plan.md「Hermes 侧配置」。
- **未 commit**：按执行规范等待用户审阅 diff 后再提交。
