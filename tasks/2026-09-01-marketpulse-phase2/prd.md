# Task Handoff：MarketPulse 第二期 — 盘中感知 + 可视化

> 复制到 `tasks/2026-09-01-marketpulse-phase2/prd.md`


## Goal

在现有每日收盘日报的基础上，增加两个新能力：
1. **盘中快照**：在美东时间 12:30 生成一份午盘简报，记录当日中间状态
2. **趋势图**：用 `matplotlib` 生成 VIX/VXN/MOVE 的历史趋势图，附在报告末尾或单独推送

目标是让市场情绪感知从"次日早上看结果"升级为"盘中跟踪 + 可视化回顾"。


## Current Understanding

### 现有基础

- `daily_report.py`：300行单文件，15个函数，纯 Python + requests
- `reports/YYYY-MM-DD.md`：每日收盘报告
- `data/last_values.json`：仅存昨日值（用于涨跌幅计算）
- Hermes cron：每天早8点运行一次（对应美东收盘后）

### 新增能力

**能力一：盘中快照**

| 检查点 | 美东时间 | 北京时间 | 输出 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| 午盘快照 | 12:30 | 次日 00:30 | `reports/snapshots/YYYY-MM-DD-noon.md` | 仅记录数据，不推送（静默） |
| 收盘日报 | 16:30 | 次日 04:30 | `reports/YYYY-MM-DD.md` | 完整日报（Hermes 推送） |

**能力二：趋势图**

- 在每日收盘报告中嵌入一张趋势图（VIX/VXN/MOVE 近30日走势）
- 图以 Markdown 图片链接方式引用（或保存为 PNG，由 Hermes 推送时带上）
- 需新建 `data/history.json` 存储历史数据（每日一条记录）


## Requirements

### 必须实现

1. **历史数据存储**
   - 新建 `data/history.json`，存储格式：
     ```json
     [
       {"date": "2026-08-01", "vix": 22.3, "vxn": 26.1, "move": 72.5},
       {"date": "2026-08-02", "vix": 21.8, "vxn": 25.7, "move": 71.2}
     ]
     ```
   - 每次运行（含收盘）追加当日记录
   - 若历史数据超过90天，自动滚动（仅保留最近90天）
   - `last_values.json` 维持不变（仅作涨跌幅基准，不扩展）

2. **盘中快照**（新增独立脚本 `snapshot_report.py`）
   - 仅获取 VIX/VXN/MOVE 当前值
   - 不计算涨跌幅（因为没有前值对比）
   - 生成 `reports/snapshots/YYYY-MM-DD-noon.md`
   - **向 Hermes 报告生成后的快照路径，由 Hermes 通过新增 cron 在次日 00:30 触发运行（配置文件里加一步），可选用户查看**
   - 运行方式：`python snapshot_report.py`（可手动运行，也可由 Hermes 定时触发）

3. **趋势图**（在 `daily_report.py` 中增强）
   - 读取 `data/history.json` 最近30天数据
   - 用 `matplotlib` 生成趋势图，保存为 `reports/charts/YYYY-MM-DD-trend.png`
   - 在 Markdown 报告中追加一个 `## 📉 近30日趋势` 章节，引用该图
   - 图片路径使用相对路径：`./charts/YYYY-MM-DD-trend.png`
   - **趋势图标签一律使用英文**（如 "VIX (30D)"、"VXN"、"MOVE"、"Date"、"Value"），避免中文字体在各平台渲染不一致的问题

4. **结构演进**（保持可维护）
   - 将 `daily_report.py` 拆分为三个模块（保持总计 ≤ 600 行）：
     - `src/fetcher.py`：数据获取（含重试/退避）
     - `src/analyzer.py`：状态分类、涨跌幅计算
     - `src/reporter.py`：报告渲染（含趋势图生成）
   - `daily_report.py` 变成仅约 50 行的编排入口
   - `snapshot_report.py` 复用 `fetcher.py`，独立编排

### 必须保持

- 容错原则：任一步骤失败不中断整体流程
- 测试全绿：新增代码需补测试，覆盖率不低于现有水平（32项）
- 依赖新增：仅增加 `matplotlib>=3.7.0`（用于趋势图）
- **调度**：
  - 收盘日报：Hermes cron 仍只跑 `daily_report.py`（早8点，由 cron 读取 `reports/*.md` 并连同 `reports/charts/*.png` 作为附件一起推送）
  - 午盘快照：新增一个 Hermes cron，在北京时间次日 00:30 跑 `snapshot_report.py`（本 PRD 的调度要求包含这一项，请确认 Hermes 侧需配置该新 cron）


## Context Pointers

### 现有文件

- `daily_report.py`：300行，15个函数
- `data/last_values.json`：单条缓存
- `reports/YYYY-MM-DD.md`：输出示例

### 需新增/修改的文件

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `src/fetcher.py` | 新建 | 从 daily_report.py 中抽离获取逻辑 |
| `src/analyzer.py` | 新建 | 状态分类、计算、历史数据读写 |
| `src/reporter.py` | 新建 | 报告渲染 + 趋势图生成 |
| `daily_report.py` | 重构 | 仅编排调用 |
| `snapshot_report.py` | 新建 | 独立入口，仅拉取数据生成午盘快照 |
| `data/history.json` | 新建 | 存储每日历史数据 |
| Hermes cron 配置 | 新增 | 北京时间次日 00:30 触发 `snapshot_report.py`；收盘 cron 改为同时推送趋势图 PNG |


## Constraints

- **依赖**：仅新增 `matplotlib>=3.7.0`，其余依赖不变
- **代码行数**：拆分后三个模块 + 两个入口，总计 ≤ 600 行
- **趋势图标签用英文**（避免中文字体跨平台渲染不一致），不用中文
- **历史数据**：90天滚动，避免无限膨胀
- **快照不推送**：Hermes 不为快照配置推送，快照仅存盘，由用户按需查看


## Done When

- [ ] `src/fetcher.py`、`src/analyzer.py`、`src/reporter.py` 三个模块拆分完成，`daily_report.py` 成为轻量编排入口
- [ ] `python snapshot_report.py` 能成功生成 `reports/snapshots/YYYY-MM-DD-noon.md`
- [ ] `python daily_report.py` 能成功生成 `reports/charts/YYYY-MM-DD-trend.png`，并在报告中正确引用
- [ ] 历史数据 `data/history.json` 在每次运行时正确追加当日记录
- [ ] 所有测试通过（含新增测试），覆盖率不下降
- [ ] Hermes 早8点跑完后，QQ 收到的报告包含趋势图（图片正常推送到 QQ）


## Verification

- [ ] 手动运行 `python snapshot_report.py`，检查午盘快照是否正确生成
- [ ] 手动运行 `python daily_report.py`，检查趋势图是否生成、报告中是否正确引用
- [ ] 检查 `data/history.json` 是否按日追加，且90天滚动生效
- [ ] 模拟断网运行，确认容错机制仍生效
- [ ] 确认 Hermes 推送后，趋势图在 QQ 端正常显示


## Risks

| 风险 | 应对 |
| :--- | :--- |
| 趋势图标签字体在各平台渲染不一致 | **趋势图全程用英文标签**（已写入 Constraints，避免中文字体问题） |
| 历史数据文件在并行运行时冲突 | Hermes 只跑早8点一次，无并发冲突风险；多时点快照不写历史，避免冲突 |
| 趋势图生成时间过长 | matplotlib 绘图限时 3 秒；若超时则跳过绘图，仅生成报告 |
| 盘中快照调度未落地（Hermes 00:30 cron） | 已列入 Requirements 必须实现项，交付时需在 Hermes 侧新增该 cron，否则快照不会自动生成 |


## 📎 附录：报告更新格式

```markdown
# 📊 市场情绪日报

**日期**：YYYY-MM-DD（美东时间）
**类型**：收盘报告

---

## 📈 核心指数

| 指数 | 收盘价 | 涨跌幅 | 状态 |
| :--- | :--- | :--- | :--- |
| VIX（恐慌指数） | {vix} | {vix_change} | {vix_status} |
| VXN（科技波动） | {vxn} | {vxn_change} | {vxn_status} |
| MOVE（债市波动） | {move} | {move_change} | {move_status} |

---

## 📉 近30日趋势

![VIX/VXN/MOVE 近30日趋势](./charts/YYYY-MM-DD-trend.png)

---

## 🏷️ 市场状态

**VIX 当前值：{vix} → 状态：{vix_status_label}**

> {vix_status_description}

---

## 📝 总结

{summary}

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*