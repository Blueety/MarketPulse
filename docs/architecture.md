# 架构说明（MarketPulse — 波动率监控 MVP）

> 描述项目的模块边界、数据流和关键设计决策。
> Agent 修改架构相关代码前必须先读这份文档。

## 概览

单文件 Python 脚本项目。每个交易日收盘后运行 `daily_report.py`，从 Yahoo Finance 拉取 VIX / VXN / MOVE 三个波动率指数，生成 Markdown 日报并缓存当日值，交由 Hermes 读取并推送到 QQ 机器人。**脚本自身不包含推送逻辑。**

## 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| 主脚本 | `daily_report.py` | 所有逻辑：配置读取、取数、状态判断、报告生成、缓存读写、错误处理 |
| 报告输出 | `reports/YYYY-MM-DD.md` | 生成的 Markdown 日报（美东日期） |
| 数据缓存 | `data/last_values.json` | 存前一日各指数收盘值，用于计算今日涨跌幅 |
| 测试 | `tests/` | 预留单元测试（对状态判断、涨跌幅、报告格式等纯逻辑做测试） |
| 环境配置 | `.env.example` | 无需任何 API 密钥（说明文件） |

## 数据流

```text
Yahoo Finance (^VIX, ^VXN) ──┐
                             ├──> daily_report.py ──> reports/YYYY-MM-DD.md ──> Hermes ──> QQ 推送
Yahoo Finance (^MOVE) ───────┘          │
                                        └──> data/last_values.json（今日值，次日作涨跌幅基准）
```

## 关键决策

| 决策 | 选择 | 原因 | 日期 |
|---|---|---|---|
| 单文件脚本 | `daily_report.py` 约 200-300 行 | MVP 最小闭环，先从每天稳定收到报告开始 | 2026-08-29 |
| 数据源 | 三指数均用 Yahoo：^VIX / ^VXN / ^MOVE | FRED 公开 API 无 MOVE 序列；^MOVE 标名有误但数值真实（与 Investing.com 一致） | 2026-08-29 |
| 时区 | 内部 UTC，报告显示美东日期 | 避免时区混淆导致日期错 | 2026-08-29 |
| 容错 | 单数据源失败继续运行，不整体崩溃 | 一个源挂了不能吞掉整个日报 | 2026-08-29 |
| 持久化 | 仅 `last_values.json`（不做历史存储/趋势图） | Out of Scope | 2026-08-29 |

## 约束

- 不修改的模块/文件: `.env`，`reports/`，`data/`（均为运行时生成/用户配置）。
- 必须保持的兼容性: `python daily_report.py` 全程可手动运行。
- 安全边界: 无需任何 API 密钥，数据全部来自 Yahoo Finance 公开接口。

## 目录级规则

- `reports/` 与 `data/` 为生成物，默认 `.gitignore` 排除或运行时自动创建。
- `daily_report.py` 职责单一：每个函数只做一件事，带 docstring。