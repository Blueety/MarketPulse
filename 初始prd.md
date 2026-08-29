# Task Handoff：波动率监控系统 MVP

> 复制到 `tasks/2026-08-29-marketpulse/prd.md`，然后交给本地 Agent。


## Goal

**实现一个可独立运行的 Python 脚本，每天获取 VIX、VXN、MOVE 三个指数数据，生成 Markdown 报告文件，由 Hermes 读取并推送至 QQ 机器人。**

目标：1-2 天内跑通“数据获取 → 报告生成 → 推送”的最小闭环，让自己每天稳定收到市场情绪数据，为后续扩展打基础。


## Current Understanding

### 产品行为

1. **数据获取**：
   - VIX、VXN：Yahoo Finance（`^VIX`, `^VXN`）
   - MOVE：FRED API（`series_id=MOVE`），需 `FRED_API_KEY` 环境变量

2. **市场状态判断**（基于 VIX）：
   - VIX < 20 → "平静"
   - 20 ≤ VIX < 30 → "警惕"
   - VIX ≥ 30 → "恐慌"

3. **报告内容**：
   - 日期（美东时间）
   - 三项指数（值 + 涨跌幅 + 状态）
   - VIX 状态标签 + 描述
   - 总结

4. **报告格式**：Markdown，存放于 `reports/YYYY-MM-DD.md`

5. **推送方式**：Hermes 已配置 QQ 机器人，负责读取报告文件并推送
   - Python 脚本完全不涉及推送逻辑

6. **运行方式**：`python daily_report.py`（手动执行）

### 技术方向

- 单文件脚本（`daily_report.py`），约 200-300 行
- 依赖：`yfinance`, `requests`, `python-dotenv`, `pytest`
- 环境变量：`FRED_API_KEY`
- 数据存储：`data/last_values.json`（存前一日数据）
- 报告输出：`reports/YYYY-MM-DD.md`


## Context Pointers

### 需要创建的文件

| 文件 | 职责 |
| :--- | :--- |
| `daily_report.py` | 主脚本（所有逻辑） |
| `requirements.txt` | 依赖清单 |
| `.env.example` | 环境变量模板 |
| `README.md` | 使用说明（可选） |

### 需要创建的目录

- `reports/`：报告输出
- `data/`：数据存储
- `tests/`：测试（预留）


## Constraints

- **代码风格**：PEP 8，函数职责单一，有 docstring
- **错误处理**：单数据源失败时记录错误但继续运行，不整体崩溃
- **首次运行**：`last_values.json` 不存在时自动创建，涨跌幅显示"首次运行，暂无历史对比"
- **超时设置**：API 请求超时 ≤ 15 秒 + 1 次重试
- **时区**：内部用 UTC，报告显示美东日期
- **依赖版本**：`requirements.txt` 必须锁定明确版本号


## Out of Scope

- 盘中多次检查（午盘/开盘监控）
- 基线快照和变化率告警
- Hermes 的配置和调试（已完成）
- Web 界面或仪表盘
- 历史数据存储与趋势图
- Docker 容器化
- 多市场股票分析
- 任何形式的自动交易或下单


## Done When

- [ ] `python daily_report.py` 在 30 秒内运行成功并退出（退出码 0）
- [ ] `reports/` 下生成 `YYYY-MM-DD.md`，内容符合报告模板
- [ ] 终端输出清晰日志（数据状态、报告路径）
- [ ] `data/last_values.json` 在首次运行后自动创建，JSON 格式有效
- [ ] 断开网络运行一次，脚本不崩溃，输出明确错误提示
- [ ] 删除 `last_values.json` 后运行一次，涨跌幅显示"首次运行，暂无历史对比"
- [ ] Hermes 定时任务已配置，并至少成功推送一次报告至 QQ


## Verification

- [ ] `python daily_report.py` 终端输出和报告文件内容检查通过
- [ ] `data/last_values.json` JSON 格式验证通过
- [ ] 断网运行测试：脚本不崩溃
- [ ] 删除 `last_values.json` 后运行测试：首次运行逻辑正常
- [ ] QQ 确认 Hermes 已成功推送报告


## Risks

| 风险 | 应对措施 |
| :--- | :--- |
| Yahoo Finance 接口变动 | 捕获异常并提示；备选 FRED 的 VIX 数据 |
| FRED_API_KEY 未配置 | 检测环境变量，缺失则跳过 MOVE 并提示 |
| 网络超时 | 15 秒超时 + 1 次重试，失败后记录日志 |
| 时区混淆 | 统一 UTC，报告生成时转美东日期 |


## 📎 附录：报告模板

```markdown
# 📊 市场情绪日报

**日期**：YYYY-MM-DD（美东时间）

---

## 📈 核心指数

| 指数 | 收盘价 | 涨跌幅 | 状态 |
| :--- | :--- | :--- | :--- |
| VIX（恐慌指数） | {vix} | {vix_change} | {vix_status} |
| VXN（科技波动） | {vxn} | {vxn_change} | {vxn_status} |
| MOVE（债市波动） | {move} | {move_change} | {move_status} |

---

## 🏷️ 市场状态

**VIX 当前值：{vix} → 状态：{vix_status_label}**

> {vix_status_description}

---

## 📝 总结

{summary}

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance & FRED*