# 架构说明（MarketPulse — 波动率监控系统）

> 描述项目的模块边界、数据流和关键设计决策。
> Agent 修改架构相关代码前必须先读这份文档。

## 概览

Python 项目。每个交易日有两个运行点：

1. **收盘日报**：`daily_report.py`（美东收盘后运行），从 Yahoo Finance 拉取 VIX / VXN / MOVE 三个波动率指数，生成 Markdown 日报（含近 30 日趋势图），追加历史数据并缓存当日值，生成 `context/YYYY-MM-DD.json` 上下文（供 Hermes 常规解读/异动归因），交由 Hermes 读取并推送到 QQ 机器人。
2. **午盘快照**：`snapshot_report.py`（美东 12:30 运行），仅取数 → 分类 → 生成午盘简报存盘，检查告警阈值（只读缓存基准），不推送。

告警：两入口各自检查当日变化率是否超过阈值（默认 VIX/VXN ±20%、MOVE ±15%，env 可覆盖），
触发则生成 `alerts/YYYY-MM-DD-{type}.md`（type = noon / close），由 Hermes 检测并独立推送一条警报消息；
同一指数当日只告警一次（午盘触发则收盘跳过），去重状态记在 `data/alerts.log`。

**脚本自身不包含推送逻辑。** AI 常规解读与异动归因由 Hermes 读取 `context/` 后生成（交付配置项，非仓库文件）。

## 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| 编排入口 | `daily_report.py` | 收盘流程编排：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 追加历史 → 写缓存 → 生成 context |
| 编排入口 | `snapshot_report.py` | 午盘快照流程编排：取数 → 分类 → 渲染快照 → 落盘（只读缓存作告警基准，不算涨跌幅、不写 history、不推送） |
| 告警 | `src/alerter.py` | 告警文件渲染（附录块格式）、alerts.log 去重状态读写、`collect_breaches` 纯计算导出、`run_alert_checks` 编排（逐指数容错） |
| 数据获取 | `src/fetcher.py` | Yahoo 取数（含重试/退避/源间节流），SYMBOLS 注册表 |
| 纯逻辑 + 持久化 | `src/analyzer.py` | 状态分类、涨跌幅、格式化、路径常量（含 CONTEXT_DIR）、last_values 缓存、history 读写（90 天滚动、原子写、损坏容错）、`build_search_keywords` |
| 报告渲染 | `src/reporter.py` | Markdown 日报 / 午盘快照渲染、趋势图（matplotlib 懒加载 + 3s 线程限时）、落盘、context 上下文 JSON（`generate_context`，原子写） |
| 报告输出 | `reports/YYYY-MM-DD.md`、`reports/snapshots/YYYY-MM-DD-noon.md`、`reports/charts/YYYY-MM-DD-trend.png` | 生成的 Markdown / 图片（美东日期） |
| 上下文输出 | `context/YYYY-MM-DD.json` | Hermes 解读/归因输入（indices + history_30d + breach + search_keywords，运行时生成，gitignore 排除） |
| 告警输出 | `alerts/YYYY-MM-DD-noon.md`、`alerts/YYYY-MM-DD-close.md`、`data/alerts.log` | 告警文件 / 当日去重标记（运行时生成，gitignore 排除） |
| 数据持久化 | `data/last_values.json`（涨跌幅基准）、`data/history.json`（近 90 日历史） | 运行时生成，gitignore 排除 |
| 测试 | `tests/test_analyzer.py`、`tests/test_reporter.py`、`tests/test_alerter.py`、`tests/test_context.py` | 纯逻辑 / 渲染 / 趋势图 / 历史滚动 / 告警 / context 单元测试 |

## 数据流

```text
Yahoo Finance (^VIX, ^VXN) ──┐
                             ├──> daily_report.py ──> reports/YYYY-MM-DD.md ──> Hermes ──> QQ 推送
Yahoo Finance (^MOVE) ───────┘          │
                                        ├──> reports/charts/YYYY-MM-DD-trend.png（报告中引用）
                                        ├──> data/history.json（按 date 追加/覆盖，90 天滚动）
                                        ├──> data/last_values.json（今日值，次日作涨跌幅基准）
                                        └──> context/YYYY-MM-DD.json（indices + history_30d + breach + search_keywords）
                                              └──> Hermes 常规解读 /（异动日）tavily 搜索归因 ──> 追加日报 ──> QQ 推送

两入口（收盘/午盘）另检查变化率告警（基准 data/last_values.json 旧缓存，只读）：

    daily/snapshot ──> src/alerter.run_alert_checks ──> alerts/YYYY-MM-DD-{type}.md ──> Hermes ──> QQ 独立推送
                                        └──> data/alerts.log（当日已告警标记，午盘触发则收盘跳过）

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
| 告警基准 | 统一用 `data/last_values.json` 旧缓存；快照只读不写 history；收盘告警检查置于 save_last_values 之前 | 避免误用当日新缓存；多时点不并发写（已确认决策 1/决策 G） | 2026-09-01 |
| 告警去重 | 当日已触发状态记 `data/alerts.log`（行式 "YYYY-MM-DD SYMBOL"，原子重写仅当日行）；午盘触发则收盘跳过同一指数 | 同一指数当日只告警一次（已确认决策 2/设计 C） | 2026-09-01 |
| 告警阈值 | 默认 VIX/VXN ±20%、MOVE ±15%；env `ALERT_THRESHOLD_<SYM>` 覆盖；触发条件为变化率**严格大于**阈值 | 默认值已确认；env 非法/非正回退默认（已确认决策 3/设计 A） | 2026-09-01 |
| 告警级别 | 触发即 WARN；当前值处于恐慌区间（classify 判定）升级为 ALERT | PRD 要求 WARN/ALERT，复用已确认 classify 区间，零新增配置（设计 B） | 2026-09-01 |
| 告警文件 | `alerts/YYYY-MM-DD-{type}.md`（type = noon / close），多指数各占一个附录块（frontmatter + 标题 + 字段） | PRD 固定文件名 {type}；多指数同日触发不冲突（设计 D） | 2026-09-01 |
| 告警容错 | run_alert_checks 内逐指数 try/except，调用方再包一层 try/except，仅记日志 | 告警逻辑失败不影响日报生成，退出码恒 0（决策 H） | 2026-09-01 |
| context 计算单一来源 | alerter 新增纯计算导出 `collect_breaches(values, last_values)`（遍历 check_breach，不写文件/不改 alerts.log，幂等）；`run_alert_checks` 重构为复用它（去重/写文件/标记逻辑原样） | breach 判断单一事实来源，context 生成不产生副作用；既有 23 条 alerter 测试行为等价锁定（决策 A） | 2026-09-01 |
| context 契约 | `context/YYYY-MM-DD.json` 五键：date / indices（value/change_pct/status）/ history_30d（dates+vix+vxn+move 等长数组，含当日）/ breach（triggered + indices 字段 name/current/previous/change_pct/threshold/level，level 沿用 WARN/ALERT）/ search_keywords | PRD 字段表定稿，Hermes Prompt 按此编写；`_breach_item` 纯映射单测锁定（决策 B） | 2026-09-01 |
| 搜索关键词 | `build_search_keywords(date, breaches)` 方向感知：异动指数变化率 >=0 用 "surge"、<0 用 "drop"，加 market volatility / economic data 定向词，异动日 3-5 个；常规日 1 个 "market summary {date}" | 方向感知直接服务归因搜索相关性（VIX 下跌时搜 "VIX drop" 才能命中下跌原因）（决策 C） | 2026-09-01 |
| context 生成时机 | `generate_context` 在 `append_history` 之后、`save_last_values` 之后调用（history_30d 含当日）；临时文件 + `os.replace` 原子写；仅收盘入口生成，snapshot 不动 | 含当日的 30 日趋势对 Hermes 参考更完整；原子写避免读到半截 JSON（决策 D/F） | 2026-09-01 |
| context 容错 | `generate_context` 不吞异常，`daily_report.py` 调用方 try/except 兜底仅记日志，退出码恒 0 | 失败路径可见可测；context 失败不影响日报主流程（决策 E） | 2026-09-01 |
| AI 解读/归因 | Hermes 侧 Prompt + tavily 搜索为交付配置项（非仓库文件）；Python 侧不引入 LLM/搜索 SDK | PRD 明确约束（决策 G） | 2026-09-01 |

## 约束

- 不修改的模块/文件: `.env`，`reports/`，`data/`（均为运行时生成/用户配置）。
- 必须保持的兼容性: `python daily_report.py` / `python snapshot_report.py` 全程可手动运行。
- 安全边界: 无需任何 API 密钥，数据全部来自 Yahoo Finance 公开接口。
- 依赖边界: 仅 `requests` / `matplotlib` / `pytest`，不引入其他依赖。
- 四期起合计 ≤ ~840 行（三期 738 + context 增量 94，实际 832）；context 增量
  （analyzer 关键词 + alerter 导出 + reporter 生成与导入 + 入口接入）≤ ~95 行。
- 四期起合计 ≤ ~810 行（三期 750 + context 增量约 60）；context 增量
  （analyzer 关键词 + alerter 导出 + reporter 生成 + 入口接入）≤ ~80 行。

## 目录级规则

- `reports/`、`data/`、`alerts/` 与 `context/` 为生成物，默认 `.gitignore` 排除或运行时自动创建。
- 每个函数只做一件事，带 docstring。
