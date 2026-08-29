# MarketPulse — 波动率监控系统 MVP

每天获取美国市场情绪数据（VIX / VXN / MOVE），生成 Markdown 日报，由 Hermes 读取并推送到 QQ 机器人。

## 运行方式

```bash
# 激活虚拟环境（Windows）
venv/Scripts/activate

# 运行主脚本（取数 → 生成报告 → 写缓存）
venv/Scripts/python daily_report.py
```

运行 `daily_report.py` 后在 `reports/YYYY-MM-DD.md` 生成日报（含 `## 📉 近30日趋势` 章节引用 `reports/charts/YYYY-MM-DD-trend.png`），并在 `data/last_values.json` 缓存当日数据（次日作涨跌幅基准）、向 `data/history.json` 追加当日记录（90 天滚动）。

```bash
# 午盘快照（仅取数 → 快照 → 落盘，不推送；美东 12:30 由 Hermes cron 触发）
venv/Scripts/python snapshot_report.py
```

运行 `snapshot_report.py` 后在 `reports/snapshots/YYYY-MM-DD-noon.md` 生成午盘快照。

## 环境变量

无需任何 API 密钥，数据全部来自 Yahoo Finance 公开接口（`^VIX` / `^VXN` / `^MOVE`），开箱即用。

> 脚本不读取 `.env`（已移除 dotenv 依赖），`.env` 若存在也可忽略。

## 数据源

| 指数 | 来源 | 说明 |
|---|---|---|
| VIX | Yahoo Finance (`^VIX`) | 标普500波动率，市场恐慌指标 |
| VXN | Yahoo Finance (`^VXN`) | 纳斯达克100波动率 |
| MOVE | Yahoo Finance (`^MOVE`) | 美国国债波动率（Yahoo 标名有误，但数值真实，与 Investing.com 一致） |

## 依赖

见 `requirements.txt`（requests / matplotlib / pytest）。

## 目录结构

```
daily_report.py          # 收盘日报编排入口
snapshot_report.py       # 午盘快照入口（美东 12:30）
src/                     # 模块化实现（fetcher / analyzer / reporter）
requirements.txt         # 依赖清单
.env.example             # 说明：无需任何密钥
reports/                 # 报告输出（YYYY-MM-DD.md / snapshots/ / charts/）
data/                    # 数据（last_values.json 基准；history.json 近90日）
tests/                   # 单元测试（test_analyzer / test_reporter）
docs/                    # 项目知识（architecture / commands / pitfalls）
tasks/                   # 任务交接（prd / plan / journal）
```

## 测试

```bash
venv/Scripts/python -m pytest tests/ -v
```

## 工作流

开发遵循 `WORKFLOW.md` 流程：架构师（K2.7 模型 = opencode-go DeepSeek v4 flash）出 plan，执行者（Hy3）实现并验证，经验沉淀到 `docs/`。