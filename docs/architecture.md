# 架构说明（MarketPulse — 波动率监控系统）

> 描述项目的模块边界、数据流和关键设计决策。
> Agent 修改架构相关代码前必须先读这份文档。

## 概览

Python 项目。每个交易日有两个运行点：

1. **收盘日报**：`daily_report.py`（美东收盘后运行），从 Yahoo Finance 拉取 VIX / VXN / MOVE 三个波动率指数，生成 Markdown 日报（含近 30 日趋势图），追加历史数据并缓存当日值，交由 Hermes 读取并推送到 QQ 机器人。
2. **午盘快照**：`snapshot_report.py`（美东 12:30 运行），仅取数 → 分类 → 生成午盘简报存盘，不推送。

**脚本自身不包含推送逻辑。**

## 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| 编排入口 | `daily_report.py` | 收盘流程编排：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 追加历史 → 写缓存 |
| 编排入口 | `snapshot_report.py` | 午盘快照流程编排：取数 → 分类 → 渲染快照 → 落盘（不读缓存/不算涨跌幅/不写历史/不推送） |
| 数据获取 | `src/fetcher.py` | Yahoo 取数（含重试/退避/源间节流），SYMBOLS 注册表 |
| 纯逻辑 + 持久化 | `src/analyzer.py` | 状态分类、涨跌幅、格式化、路径常量、last_values 缓存、history 读写（90 天滚动、原子写、损坏容错） |
| 报告渲染 | `src/reporter.py` | Markdown 日报 / 午盘快照渲染、趋势图（matplotlib 懒加载 + 3s 线程限时）、落盘 |
| 报告输出 | `reports/YYYY-MM-DD.md`、`reports/snapshots/YYYY-MM-DD-noon.md`、`reports/charts/YYYY-MM-DD-trend.png` | 生成的 Markdown / 图片（美东日期） |
| 数据持久化 | `data/last_values.json`（涨跌幅基准）、`data/history.json`（近 90 日历史） | 运行时生成，gitignore 排除 |
| 测试 | `tests/test_analyzer.py`、`tests/test_reporter.py` | 纯逻辑 / 渲染 / 趋势图 / 历史滚动单元测试 |

## 数据流

```text
Yahoo Finance (^VIX, ^VXN) ──┐
                             ├──> daily_report.py ──> reports/YYYY-MM-DD.md ──> Hermes ──> QQ 推送
Yahoo Finance (^MOVE) ───────┘          │
                                        ├──> reports/charts/YYYY-MM-DD-trend.png（报告中引用）
                                        ├──> data/history.json（按 date 追加/覆盖，90 天滚动）
                                        └──> data/last_values.json（今日值，次日作涨跌幅基准）

Yahoo Finance ──> snapshot_report.py ──> reports/snapshots/YYYY-MM-DD-noon.md（仅存盘，不推送）
```

## 关键决策

| 决策 | 选择 | 原因 | 日期 |
|---|---|---|---|
| 模块拆分 | `daily_report.py` 300 行拆为 `src/` 三模块 + 约 50 行编排入口 | 二期新增快照与趋势图后单文件不可维护；`snapshot_report.py` 复用 fetcher | 2026-09-01 |
| 数据源 | 三指数均用 Yahoo：^VIX / ^VXN / ^MOVE | FRED 公开 API 无 MOVE 序列；^MOVE 标名有误但数值真实（与 Investing.com 一致） | 2026-08-29 |
| 时区 | 内部 UTC，报告显示美东日期 | 避免时区混淆导致日期错 | 2026-08-29 |
| 容错 | 单数据源失败继续运行，不整体崩溃；任一指数取数失败在 history 中存 null | 一个源挂了不能吞掉整个日报；趋势图按 NaN 断点处理 | 2026-08-29 / 2026-09-01 |
| 历史存储 | `data/history.json` 列表按 date 键追加/覆盖，仅保留最近 90 条，临时文件 + `os.replace` 原子写，损坏按空历史处理 | 趋势图数据来源；避免无限膨胀与半截写入 | 2026-09-01 |
| 趋势图 | matplotlib（Agg 后端 + 懒加载）；Windows 无 SIGALRM，用 daemon 线程 `join(3)` 限时，超时跳过绘图、报告不产生死链 | 无头环境渲染；冷启动/渲染超时不中断整体流程 | 2026-09-01 |
| 图表语言 | 趋势图标签一律英文（"VIX (30D)" / "VXN" / "MOVE" / "Date" / "Value"） | 中文字体跨平台渲染不一致（PRD 强制约束） | 2026-09-01 |
| 快照 | 独立入口脚本，不读缓存、不算涨跌幅、不写 history、不推送 | 避免多时点并发写历史冲突；PRD 已定 | 2026-09-01 |
| 相对导入 | src 内模块互引用用相对导入；根目录入口用 `from src import ...` | 入口脚本目录在 sys.path，Hermes 任意 cwd 运行均可靠 | 2026-09-01 |

## 约束

- 不修改的模块/文件: `.env`，`reports/`，`data/`（均为运行时生成/用户配置）。
- 必须保持的兼容性: `python daily_report.py` / `python snapshot_report.py` 全程可手动运行。
- 安全边界: 无需任何 API 密钥，数据全部来自 Yahoo Finance 公开接口。
- 依赖边界: 仅 `requests` / `matplotlib` / `pytest`，不引入其他依赖。
- 行数预算: 三模块 + 两入口合计 ≤ 600 行。

## 目录级规则

- `reports/` 与 `data/` 为生成物，默认 `.gitignore` 排除或运行时自动创建。
- 每个函数只做一件事，带 docstring。
