# Task Brief：波动率监控系统 MVP

> 本任务面向**本地 Agent**，用于指导第一版可运行脚本的开发。
> 项目名称：`marketpulse`


## Goal

**实现一个可独立运行的 Python 脚本，每天获取 VIX、VXN、MOVE 三个指数数据，生成 Markdown 报告文件，由 Hermes 读取并推送至 QQ 机器人。**

目标是在 1-2 天内跑通“数据获取 → 报告生成 → 推送”的最小闭环，先让自己每天稳定收到市场情绪数据，为后续扩展打基础。


## User / Scenario

- **用户**：你本人（个人投资者/开发者）
- **场景**：每个美股交易日收盘后（美东时间下午 5:30，对应北京时间凌晨 5:30），自动收到一份关于当日市场情绪的报告。
- **使用方式**：早上醒来打开 QQ，查看机器人推送的波动率日报，了解当前市场状态，辅助当日投资决策。


## Requirements

### 必须实现

1. **数据获取**
   - VIX（标普500波动率）：Yahoo Finance (`^VIX`)
   - VXN（纳斯达克100波动率）：Yahoo Finance (`^VXN`)
   - MOVE（国债波动率）：FRED API (`series_id=MOVE`)
   - API 超时设置 15 秒，失败时自动重试 1 次

2. **市场状态判断**（基于 VIX）
   - VIX < 20 → "平静"
   - 20 ≤ VIX < 30 → "警惕"
   - VIX ≥ 30 → "恐慌"

3. **报告生成**
   - 格式：Markdown（模板见下方附录）
   - 存放路径：`reports/YYYY-MM-DD.md`
   - 内容：日期、三项指数（值+涨跌幅+状态）、VIX 状态标签、总结

4. **数据持久化**
   - 保存当日数据到 `data/last_values.json`
   - 格式：`{"date": "2026-08-29", "vix": 22.3, "vxn": 26.1, "move": 72.5}`
   - 首次运行时自动创建，涨跌幅显示"首次运行，暂无历史对比"

5. **错误处理**
   - 任一数据源失败时，记录错误但尽可能继续运行
   - 最终报告在数据缺失处标注"数据暂缺"
   - 脚本不因单个数据源失败而整体崩溃

### 必须保持

- 代码量控制在 200-300 行以内（单文件）
- 运行方式：`python daily_report.py`
- 所有敏感信息通过环境变量配置：`FRED_API_KEY`
- 依赖清单明确版本号


## Out of Scope

- 盘中多次检查（午盘/开盘监控）
- 基线快照和变化率告警
- Hermes 的配置和调试（已完成）
- Web 界面或仪表盘
- 历史数据存储与趋势图（仅保留 `last_values.json` 用于计算涨跌幅）
- Docker 容器化
- 多市场股票分析
- 任何形式的自动交易或下单


## Context Pointers

- `daily_report.py`：主脚本（待创建）
- `reports/YYYY-MM-DD.md`：报告输出（待生成）
- `data/last_values.json`：前一日数据缓存（首次运行不存在，脚本应自动创建）
- `.env`：环境变量（需复制 `.env.example` 并填入 `FRED_API_KEY`）
- `requirements.txt`：依赖清单（待创建）


## Constraints

- **代码风格**：遵循 PEP 8，函数职责单一，有基本的 docstring
- **错误处理**：任一数据源失败时，应记录错误但尽可能继续运行，不整体崩溃
- **首次运行**：`last_values.json` 不存在时，自动创建，涨跌幅显示"首次运行，暂无历史对比"
- **依赖清单**：`requirements.txt` 必须包含所有依赖及明确版本号
- **超时设置**：API 请求超时时间不超过 15 秒
- **时区**：使用 UTC 时间，报告中日期显示为美东日期


## Done When

以下条件全部满足时，本任务完成：

- [ ] `python daily_report.py` 能在 30 秒内成功运行并退出（退出码 0）
- [ ] 运行后，`reports/` 目录下生成 `YYYY-MM-DD.md` 文件，内容符合附录中的报告模板
- [ ] 终端输出清晰的执行日志（含数据获取状态、报告生成路径）
- [ ] `data/last_values.json` 在首次运行后自动创建，内容结构正确
- [ ] 断开网络后运行一次，脚本不崩溃，输出明确的错误提示
- [ ] 删除 `data/last_values.json` 后运行一次，涨跌幅显示"首次运行，暂无历史对比"
- [ ] Hermes 定时任务已配置，并至少成功推送一次报告至 QQ


## Verification

- [ ] 运行 `python daily_report.py`，手动检查终端输出和生成的文件内容
- [ ] 检查 `data/last_values.json` 格式是否正确（JSON valid）
- [ ] 检查 `reports/YYYY-MM-DD.md` 内容是否包含所有必需字段
- [ ] 断开网络后运行一次，确认错误处理生效、脚本不崩溃
- [ ] 删除 `data/last_values.json` 后运行一次，确认首次运行逻辑正常
- [ ] 通过 QQ 确认 Hermes 已成功推送报告


## Risks

| 风险 | 影响 | 应对措施 |
| :--- | :--- | :--- |
| Yahoo Finance 接口变动或封禁 | 无法获取 VIX/VXN | 脚本捕获异常并明确提示；备选 FRED 的 VIX 数据 |
| FRED API Key 未配置 | 无法获取 MOVE | 脚本检测环境变量，若缺失则跳过 MOVE 并提示 |
| 网络超时 | 数据获取失败 | 设置 15 秒超时 + 1 次重试，失败后记录日志 |
| 时区混淆 | 报告中日期与预期不符 | 统一使用 UTC，在报告生成时转换为美东日期 |


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

状态描述映射
VIX 区间	标签	描述
< 20	✅ 平静	市场情绪稳定，风险偏好正常
20-30	⚠️ 警惕	市场存在不确定性，建议保持关注
≥ 30	🚨 恐慌	市场恐慌情绪显著，需警惕进一步波动