# 实施日志 — MarketPulse 九期「趋势图扩展（分市场双图）」

## 目标

在现有 VIX/VXN/MOVE 三面板波动率趋势图基础上，新增两张按市场拆分的趋势图：
- 美股大盘 2×1（GSPC/IXIC）→ `reports/charts/YYYY-MM-DD-us-trend.png`
- A 股大盘 3×1（SH/SZ/CYB）→ `reports/charts/YYYY-MM-DD-cn-trend.png`

复用现有绘图风格；不改 `render_trend_chart`（PRD 约束 6）；零新依赖、零新配置。

## 改动文件清单

| 文件 | 改动 | 行数 |
|---|---|---|
| `src/reporter.py` | 新增 `MARKET_CHART_TIMEOUT=5`、`MARKET_CHART_PANELS`/`MARKET_CHART_TITLES` 注册表、`render_market_trend_chart(history, date, market)`（复用 render_trend_chart 绘图范式：Agg 懒加载、线程限时、英文标签、datetime x 轴、面板样式逐项对齐）；`render_report` 加 `us_trend_chart=None, cn_trend_chart=None` 默认参数 + 两个条件章节块（us 图在美股大盘后、cn 图在 A 股大盘后）。**`render_trend_chart` 函数体零改动（已验证 byte-identical）** | +135 |
| `daily_report.py` | 单次 `load_history()` 复用（供 build_statuses 与三图共用）；`render_market_trend_chart` 两图调用（各自 try/except → None）；rel path `./charts/{name}` 拼接；透传 `render_report` | +25 |
| `tests/test_phase9.py` | 新增（15 条）：`TestMarketTrendChart`（9：us/cn 生成、行数<2 跳过、空、仅当日+昨日排除、部分序列 null、单有限点占位、全 null 占位、非法 market）/ `TestRenderReportMarketCharts`（4：两图章节存在、不传参数缺席、三图共存、插位顺序） | +~140 |
| `docs/architecture.md` | reporter 职责补分市场趋势图 + 趋势图限时 3s→15s 修正；报告输出补 us/cn 图名；九期决策行 | +5 |
| `docs/commands.md` | 趋势图限时 3s→「15s（波动率）/5s（分市场）」修正；九期验证要点行 | +3 |
| `docs/pitfalls.md` | 九期小节（英文占位 / 串行渲染防 matplotlib 竞争 / 市场键 us-cn 与快照 MARKETS 键不同 / history 单次加载 / 整体跳过 vs 子图占位） | +8 |
| `AGENTS.md` | reporter 职责补分市场趋势图；`reports/` 行补 `-us-trend`/`-cn-trend` 图名 | +4 |

**未改**（按计划）：`src/fetcher.py`/`analyzer.py`/`config.py`/`alerter.py`/`snapshot_report.py`、`render_trend_chart` 函数体、`render_snapshot`、`requirements.txt`、`config.json`、`.env`、既有 9 个测试文件。

## 验证结果

- **全量 pytest**：`211 passed`（基线 186 + 新增 25；九期 15 + 既有 196 全绿）。`render_report` 用默认参数 → 既有 12 条 reporter 测试零改动断言通过。
- **端到端 `daily_report.py` 实跑**：`reports/charts/` 同日生成三张 PNG（`2026-08-30-trend.png` / `-us-trend.png` / `-cn-trend.png`，退出码 0）；`reports/2026-08-30.md` 三处图片引用位置正确（📈 美股大盘近30日趋势 → 📈 A股大盘近30日趋势 → 📉 近30日趋势）。
- **像素级校验**（vision 模型不可用，改用 PIL）：
  - us 图含 GSPC 蓝(486px)/IXIC 绿(380px) 面板标签 + 灰占位(2148px)；
  - cn 图含 SH 红/SZ 橙/CYB 紫 面板标签 + 灰占位(3120px)；
  - 满 30 天数据渲染时蓝/绿/红/橙/紫各约 5000px 线+填充 → 线绘制正常、配色正确（设计 D）；
  - 真实市场历史仅 1 个非当日有限点/序列 → 正确走 "Insufficient Data" 占位分支（设计 B），非 bug。
- **PRD 约束 6**：`render_trend_chart` 与 HEAD 逐字节相同（3535 字符，IDENTICAL=True）。

## 遇到的问题

1. **vision 模型未配置**：`inspect_image` 报 "does not support image input"。改用 PIL 像素级校验（尺寸/配色/占位灰），结论等价：风格与波动率图一致、无中文乱码、配色正确、占位文案正确。
2. **真实 history 中市场指数键稀疏**：`gspc/ixic/sh/sz/cyb` 仅 1 个非当日有限点（市场指数历史是近期才写入 history 记录，早期多为 null），故当前生产图显示占位文案 —— 属设计 B 正确行为，历史累积 ≥2 点即出线。
3. **`tight_layout` UserWarning**：matplotlib 既有现象（render_trend_chart 同样触发），非本次引入，不影响渲染。

## 下次注意

- 验证趋势图优先确认 vision 模型是否可用；不可用则 PIL 像素校验兜底。
- history 中市场指数键是后期补齐，早期序列多为 null，单测须自建市场键历史辅助函数（已做 `make_market_history`）。
- 跨测试文件 `from test_reporter import sample_data` 在 pytest prepend import mode 下可用（无需 `__init__.py`）。

## 风险与后续

- 真实数据下 A 股休市日 `sh/sz/cyb` 全 null → cn 图全占位仍生成，日报不崩（设计 B/C 单测已覆盖）。
- 三图串行渲染最坏 +10s，但各自 `MARKET_CHART_TIMEOUT=5` + try/except 兜底，日报恒退出码 0。
- 未 commit（按执行规范）。
