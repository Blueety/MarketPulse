# MarketPulse — 波动率监控系统 MVP

每天获取美国市场情绪数据（VIX / VXN / MOVE），生成 Markdown 日报，由 Hermes 读取并推送到 QQ 机器人。

## 运行方式

```bash
# 激活虚拟环境（Windows）
venv/Scripts/activate

# 运行主脚本（取数 → 生成报告 → 写缓存）
venv/Scripts/python daily_report.py
```

运行后在 `reports/YYYY-MM-DD.md` 生成日报，并在 `data/last_values.json` 缓存当日数据（次日作涨跌幅基准）。

## 环境变量

复制 `.env.example` 为 `.env` 并填入你的 FRED API Key：

```
FRED_API_KEY=your_fred_api_key_here
```

> `.env` 已被 `.gitignore` 排除，不会进 git。

## 数据源

| 指数 | 来源 | 说明 |
|---|---|---|
| VIX | Yahoo Finance (`^VIX`) | 标普500波动率，市场恐慌指标 |
| VXN | Yahoo Finance (`^VXN`) | 纳斯达克100波动率 |
| MOVE | FRED API (`MOVE`) | 美国国债波动率，需 FRED API Key |

## 依赖

见 `requirements.txt`（yfinance / requests / python-dotenv / pytest）。

## 目录结构

```
daily_report.py          # 主脚本（所有逻辑）
requirements.txt         # 依赖清单
.env.example / .env      # FRED_API_KEY 配置
reports/                 # 日报输出（YYYY-MM-DD.md）
data/                    # 当日数据缓存（last_values.json）
tests/                   # 单元测试（预留）
docs/                    # 项目知识（architecture / commands / pitfalls）
tasks/                   # 任务交接（prd / plan / journal）
```

## 测试

```bash
venv/Scripts/python -m pytest tests/ -v
```

## 工作流

开发遵循 `WORKFLOW.md` 流程：架构师（K2.7 模型 = opencode-go DeepSeek v4 flash）出 plan，执行者（Hy3）实现并验证，经验沉淀到 `docs/`。