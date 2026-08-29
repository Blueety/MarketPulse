# 命令说明

> 列出项目所有验证命令。Agent 完成修改后必须运行相关命令。
> 所有命令需先激活 venv（Windows: `venv/Scripts/activate`），或直接调用 `venv/Scripts/python`。

## 快速检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 运行单元测试 | 改了函数逻辑 / 提交前 |
| `venv/Scripts/python daily_report.py` | 运行主脚本（完整闭环：取数→报告→趋势图→写历史→写缓存） | 改了数据获取/报告生成/错误处理逻辑 |
| `venv/Scripts/python snapshot_report.py` | 运行午盘快照（取数→快照→落盘） | 改了快照逻辑 |

## 完整检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/pip install -r requirements.txt` | 安装/校验依赖 | 环境变更 / 提交前 |
| `venv/Scripts/python -m pytest tests/ -v` | 完整测试套件 | 提交前 |
| `venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"` | 校验 matplotlib 可用（Agg 无头后端） | 环境变更 / 提交前 |

## 何时跑什么

| 改动类型 | 必须运行 |
|---|---|
| 数据获取逻辑（VIX/VXN/MOVE） | 主脚本 + 相关单元测试 |
| 报告/快照/趋势图生成 | 主脚本 + 快照脚本（检查输出内容与 PNG） |
| 状态判断/涨跌幅计算 | 相关单元测试 |
| history 读写/滚动 | 相关单元测试（test_analyzer.py TestHistory） |
| 错误处理/离线容错 | 主脚本（断网场景） |

## 验证要点（对应任务 prd 的 Verification Plan）

- 首次运行 `daily_report.py`，`reports/YYYY-MM-DD.md`、`data/last_values.json`、`data/history.json` 应自动生成；history 只有 1 条时无趋势图（数据不足 2 条跳过）。
- 删除 `data/last_values.json` 后运行，涨跌幅应显示"首次运行，暂无历史对比"。
- 断网时运行，脚本不崩溃、输出明确错误提示、报告标注获取失败、history 记录 null。
- 有 ≥2 条历史数据（不含当日）时运行 `daily_report.py`，应生成 `reports/charts/YYYY-MM-DD-trend.png`，且报告中含「## 📉 近30日趋势」章节引用 `./charts/YYYY-MM-DD-trend.png`。
-- 修改 `data/last_values.json` 模拟变化率超阈值（如 VIX 基准 = 当前值/1.22，即 +22%）后运行 `daily_report.py`，应生成 `alerts/YYYY-MM-DD-close.md`，内容含当前值/昨日收盘/变化率/阈值/状态/建议/报告路径，格式为 frontmatter + 标题 + 字段的附录块。
- 先跑 `snapshot_report.py` 触发午盘告警再跑 `daily_report.py`（同一 +22% 模拟）：收盘不再生成含该指数的 close 文件（午盘触发则收盘跳过，`data/alerts.log` 记当日已告警）。
- `ALERT_THRESHOLD_VIX=30 venv/Scripts/python daily_report.py`（+22% 模拟）：VIX 不再告警（22 < 30），env 覆盖默认 20 生效。
- 删除/移走 `data/last_values.json` 或断网时运行两入口：不崩溃、退出码 0、无告警文件（check_breach 对缺失数据返回 None）。
- 验证后必须恢复 `data/last_values.json` 原值（备份/恢复）。
- history.json 超过 90 条时自动滚动（仅保留最近 90 条）；同日重复运行按 date 覆盖，不产生重复条目。
- 趋势图渲染超过 3 秒时跳过绘图，报告趋势章节改为文字说明，不中断整体流程。
- 运行 `daily_report.py` 后应生成 `context/YYYY-MM-DD.json`；改 `data/last_values.json` 模拟 VIX +22% 后运行，`breach.triggered` 应为 `true` 且 `breach.indices` 含 VIX 明细（name/current/previous/change_pct/threshold/level），`search_keywords` 3-5 个含 "VIX surge/drop {date}"。
- 恢复正常基准后运行，`breach.triggered=false`、`breach.indices=[]`、`search_keywords == ["market summary {date}"]`。
- 断网/取数全失败时运行：日报正常生成、退出码 0；context 生成失败仅记日志（或生成 breach=false 的 context），不中断主流程。
- 连续两次运行同一场景：当日 context 被覆盖且 JSON 有效；`alerts/` 无新增文件、`data/alerts.log` 前后一致（collect_breaches 纯计算不触碰）。
- 验证后必须恢复 `data/last_values.json` 原值并清理验证期临时文件（context/ 为生成物可保留当日真实状态）。
- **阈值配置化（五期）**：`config.json` 缺失/损坏 → 回退内置默认、退出码 0、不崩溃；`ALERT_THRESHOLD_*` / `STATUS_THRESHOLD_*` / `TREND_CHART_DAYS` / `HISTORY_RETENTION_DAYS` 经 env 覆盖生效（调用时复核）；改 `config.json` 的 vix 为 22/35 后运行 `daily_report.py`，VIX 状态标签按新阈值输出（验证后恢复 20/30）；pytest 在 conftest 隔离下恒用默认，不读用户 config.json。
- **配置加载单测**：`venv/Scripts/python -m pytest tests/test_config.py -v` 覆盖默认/加载/类型校验/env 三级链/CONFIG_PATH/模块接线/STATUS env。

## 已知问题

<!-- 记录不稳定测试、环境依赖、跳过的检查等 -->
- （暂无）
