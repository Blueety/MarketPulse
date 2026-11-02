# journal — MarketPulse 三期「阈值告警」

日期：2026-09-01（美东 2026-08-29）
执行者：编码执行者（按架构师 plan.md 实施，未改架构）

## 目标

两入口（收盘/午盘）按阈值检查 VIX/VXN/MOVE 当日变化率，触发则生成独立告警文件
`alerts/YYYY-MM-DD-{type}.md`（type = noon / close），同日只告警一次（午盘触发则收盘跳过），
Hermes 检测并独立推送。默认阈值 VIX/VXN ±20%、MOVE ±15%，env `ALERT_THRESHOLD_<SYM>` 覆盖。

## 改动文件清单

新增：
- `src/alerter.py`（91 行）：告警文件渲染（附录块格式）、alerts.log 去重状态读写（原子重写仅当日行）、`run_alert_checks` 编排（逐指数 try/except）
- `tests/test_alerter.py`（184 行）：check_breach 边界/级别/env、去重当日与跨日、渲染格式、编排端到端（tmp 不联网）

修改：
- `src/analyzer.py`（+47）：ALERTS_DIR/ALERTS_LOG/ALERT_THRESHOLDS/ALERT_SUGGESTIONS 常量、`alert_threshold()`（env 覆盖+非法回退）、`check_breach()`（纯函数，严格大于触发，恐慌区间=ALERT）
- `daily_report.py`（+8）：save_report 后、save_last_values 前调用 `run_alert_checks(..., "close", ...)`，try/except 兜底
- `snapshot_report.py`（+8）：新增 `load_last_values()` 只读基准，落盘后 `run_alert_checks(..., "noon", ...)` 兜底
- `.gitignore`（+1：`alerts/`）、`.env.example`（+5：三个阈值示例）
- `docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`AGENTS.md`（三期内容同步）

未改：`src/fetcher.py`、`src/reporter.py`、`requirements.txt`、`.env`、`README.md`。

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 导入检查 | `python -c "from src.analyzer import check_breach, alert_threshold"` | 通过 |
| 导入检查 | `python -c "from src.alerter import run_alert_checks"` | 通过 |
| 新增测试 | `pytest tests/test_alerter.py -v` | 23 passed |
| 全量回归 | `pytest tests/ -v` | 72 passed（原 49 + 新增 23），2 个既有 reporter tight_layout warning |
| 收盘闭环 | `python daily_report.py` | 退出码 0，生成 close 告警（VIX/VXN） |
| 午盘快照 | `python snapshot_report.py` | 退出码 0，生成 noon 告警 |
| 语法 | `python -m py_compile` 4 文件 | 通过 |

### 手动验证矩阵 5 项

1. 触发告警：改缓存模拟 +42.9% → daily 生成 `alerts/2026-08-29-close.md`（VIX/VXN 各一块，MOVE +11.1% 未触发）✓
2. 午盘→收盘去重：snapshot 触发 noon 告警 → daily 日志「VIX/VXN 当日已告警（alerts.log），跳过」，未生成新 close 文件 ✓
3. env 覆盖：`ALERT_THRESHOLD_VIX=30` + 模拟 +26% → VIX 不告警（<30），VXN 仍告警 ✓
4. 数据缺失/断网路径：移走 last_values.json 运行两入口 → 退出码 0、无告警文件、alerts.log 无残留 ✓
5. 恢复：last_values.json 恢复原值（VIX 14.43 / VXN 19.92 / MOVE 70.965），验证期临时文件（alerts/、alerts.log、备份）已清理 ✓

## 遇到的问题

1. **edit 工具锚点事故（3 次）**：`daily_report.py` 用 ASCII `+` 被当字面量写入（add-line 需全角 `＋`）；`src/analyzer.py` 两次 edit 的 MATCH 块缺 `»`/REWRITE 或锚行重复，导致 `compute_changes`、`classify_move` 两分支、`LAST_VALUES_FILE`/`HISTORY_FILE`/`DATA_DIR` 常量被误删。
   处理：`daily_report.py` 用 write 整体重写；`analyzer.py` 基于最后完整读取内容用 write 整体重写恢复，随后 git diff 确认恢复后 diff 干净（仅三期新增 +47 行）。修复后全量测试验证无残留破坏。
2. **告警行数超预算**：告警相关增量 156 行 vs 计划硬校验 ≤150（超 6 行，4%）。原因：计划未计入 ALERT_SUGGESTIONS 建议文案（6 行，设计 F 产物）与 check_breach 完整返回 dict（12 行）。已做一轮保持行为不变的精简（合并 env 回退分支、压缩 docstring/折行），再压需牺牲可读性（超长行），未继续。请用户审阅 diff 时定夺。
3. **Yahoo 限流未遇到**：本次执行时段取数全部成功（VIX 14.43 / VXN 19.92 / MOVE 70.97），限流路径由单测（check_breach 对 None 返回 None）与场景 4 覆盖。

## 下次注意什么

- 本任务对 `src/analyzer.py`/`daily_report.py` 做过多行块 edit 时优先 `write` 整体重写或单行 `⟪old│new⟫`，避免长 MATCH 块模糊匹配误删（已录入 pitfalls 思路，编辑时谨记）。
- 手动验证告警后，先备份 `data/last_values.json` 再模拟，结束务必恢复（本次已恢复）。
- 交付项未落地：Hermes 侧需配置告警检测与推送（午盘 cron 检测 `alerts/YYYY-MM-DD-noon.md`、收盘 cron 检测 `close.md`，推送后建议清理）；此为非仓库改动，需用户确认。

## diff 摘要

- `git diff --stat`：daily_report.py +10/-2、snapshot_report.py +11/-3、src/analyzer.py +47/-0
- 新增：src/alerter.py（91）、tests/test_alerter.py（184）
- 行数预算：告警相关增量 156 行（目标 ≤150，偏差 6 行，见上）
