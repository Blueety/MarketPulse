# Task Handoff：MarketPulse 第四期 — AI 解读 + 异动归因分析

> 复制到 `tasks/2026-09-01-marketpulse-phase4/prd.md`


## Goal

在每日日报基础上，增加两个 AI 驱动能力：
1. **常规解读**：对当日市场状态生成自然语言解读（200-300字）
2. **异动归因**：当任一指数变化超过阈值时，AI 自动检索并分析可能的事件原因，生成"异动归因报告"

目标是实现"数据 → 洞察 → 原因"的完整链路，让用户不仅知道市场在波动，还理解"为什么波动"。


## 已确认的设计决策（用户定稿，勿改）

1. **方案 Y（结构化上下文）**：新增 `generate_context()`，产出 `context/YYYY-MM-DD.json`（指数 + history_30d + breach + search_keywords）。本函数与 context/ 目录为第四期新增（PRD 原稿假设其已存在，实际需补建）。
2. **触发方式（全自动）**：收盘 cron 跑完脚本后，Hermes 自动读取 `context/` 当日 JSON →（异动日）联网搜索 → 生成常规解读 + 异动归因 → 追加到日报并推送。
3. **频率**：每个交易日 Hermes 都做常规 AI 解读（200-300字）；**仅异动日**额外做异动归因分析。
4. **搜索工具**：归因用 **tavily search**（Hermes 内置插件，keyless 可用、限速；可配 TAVILY_API_KEY 提升额度）。
5. **告警文件对齐现状**：告警文件为 `alerts/YYYY-MM-DD-{type}.md`（type = noon / close），按检查点命名、多指数合一个文件。异动判断以 `alerter.py` 导出的 breach 状态为准。


## Current Understanding

### 现有基础（三期后实际状态）

- 日报生成（含三面板趋势图），`daily_report.py` 编排入口
- 阈值告警已实现：`src/alerter.py`、`src/analyzer.py` 的 `check_breach()`，默认阈值 VIX/VXN ±20% / MOVE ±15%，env 覆盖
- 告警文件 `alerts/YYYY-MM-DD-{type}.md`（noon / close）；`data/alerts.log` 记录当日去重状态
- **无 `context/` 目录、无 `generate_context()`**（第四期新增）
- Hermes Agent 具备联网搜索（tavily）与生成解读能力

### 新增能力：AI 解读 + 异动归因

**工作流**：

```
daily_report.py 运行完毕
        │
        ▼
generate_context() 产出 context/YYYY-MM-DD.json
（含 indices / history_30d / breach / search_keywords）
        │
        ▼
Hermes 全自动：
  读取 context → 常规解读(200-300字) →（异动日）tavily 搜索归因
        │
        ▼
  解读/归因追加到日报末尾 → 推送 QQ
```

## Requirements

### 必须实现（Python 侧）

1. **增强上下文生成**（在 `src/reporter.py` 新增 `generate_context()`）
   - 输出 `context/YYYY-MM-DD.json`，格式：
     ```json
     {
       "date": "2026-08-29",
       "indices": { "VIX": {"value": 14.43, "change_pct": 0.0, "status": "平静"}, ... },
       "history_30d": { "dates": [...], "vix": [...], "vxn": [...], "move": [...] },
       "breach": {
         "triggered": true,
         "indices": [ { "name": "VIX", "current": 26.4, "previous": 22.3, "change_pct": 18.4, "threshold": 20, "level": "warning" } ]
       },
       "search_keywords": ["VIX surge 2026-08-29", "market volatility today"]
     }
     ```
   - **search_keywords 生成规则**：若 `breach.triggered == true`，自动生成 3-5 个关键词（基于指数名 + 日期 + 定向词，如 "VIX surge 2026-08-29"、"market volatility today"、"economic data 2026-08-29"）；非异动日生成常规关键词（如 "market summary 2026-08-29"）。
   - **breach 数据来源**：从 `alerter.py` 导出的异动状态读取（三期已实现判断逻辑，第四期复用，幂等：不影响告警文件本身）
   - context/ 为运行时生成，加入 `.gitignore`

2. **历史序列导出**：`generate_context()` 需从 `history.json` 取近 30 日序列（dates + 三指数数组），供 Hermes 参考趋势

### Hermes 侧配置（非 Python 代码，交付时落地）

3. **市场分析师 Prompt 模板**：Hermes 读取 context.json 后，按下列结构生成：
   - **任务一（常规解读，每日）**：200-300 字市场情绪解读
   - **任务二（异动归因，仅 breach.triggered=true）**：异动事实 → tavily 搜索当日新闻/经济事件/联储/地缘 → 相关性判断 → 归因结论 1-2 条 → 后续关注
   - **容错**：AI 归因失败（搜索无结果/超时）时，日报仍正常推送，标注"异动归因分析暂时无法获取，请稍后重试"
   - 搜索源：tavily search（keyless 或 TAVILY_API_KEY）
   - 归因报告末尾标注"*本归因由 AI 基于公开信息生成，仅供参考，不构成投资建议*"

### 必须保持

- Python 代码**不引入任何 LLM/搜索 SDK**（搜索与生成全在 Hermes 侧）
- 归因分析失败不影响日报主流程（容错）
- 不新增 Python 依赖
- 保持三期的测试全绿（新增第四期测试）

### 归因报告格式（追加到日报末尾）

```markdown
## 🔍 异动归因分析

**异动指数**：VIX
**变化**：22.30 → 26.40（+18.4%，触发阈值 ±20%）

**相关事件扫描**：
- 08:30 AM 美东：美国 7 月 CPI 数据公布（+3.2%，超预期 0.2%）
- ...

**归因结论**：
1. CPI 数据超预期引发对美联储继续加息的担忧
2. ...

**后续关注**：
- 明日初请失业金数据
- ...

*本归因由 AI 基于公开信息生成，仅供参考，不构成投资建议*
```


## Context Pointers

### 需新增/修改的文件

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `src/reporter.py` | 修改 | 新增 `generate_context()` + context 写入 |
| `src/alerter.py` | 修改 | 导出异动状态（breach 数据），供 reporter 生成 context |
| `src/analyzer.py` | 修改（可能） | 若需导出历史序列/状态帮助函数 |
| `.gitignore` | 修改 | 新增 `context/` 一行 |
| Hermes 侧 | 配置 | market-analyst Prompt + tavily 搜索接线 |


## Constraints

- **Python 侧**：不引入 LLM/搜索 SDK；不新增第三方依赖；context 生成失败不影响日报主流程；context/ 运行时生成入 .gitignore
- **搜索**：tavily search（keyless 或 TAVILY_API_KEY）
- **归因长度**：300-400 字（Hermes Prompt 控制）
- **频率**：每日常规解读 + 仅异动日归因
- **超时**：AI 归因总时长 ≤ 30 秒；超时跳过，日报先推送


## Done When

- [ ] `generate_context()` 实现，产出 `context/YYYY-MM-DD.json` 格式正确
- [ ] 异动时 `search_keywords` 自动生成（3-5 个，基于指数名+日期+关键词）
- [ ] breach 数据从 alerter 正确导出（异动日 triggered=true 且含 index 明细）
- [ ] 非异动日 `breach.triggered=false`，search_keywords 为常规词
- [ ] context/ 入 .gitignore，不提交
- [ ] 所有测试通过（原 72 + 新增 context 测试）
- [ ] Hermes 能基于 context.json 执行 tavily 搜索并生成归因（交付链路，验证时人工触发确认）


## Verification

- [ ] 模拟 VIX 异动（临时改 last_values 使变化率超阈值），运行脚本检查 `context/` 中 breach 字段
- [ ] 检查 `search_keywords` 合理性（异动/常规两类）
- [ ] context.json 生成失败时，日报仍正常生成推送
- [ ] 正常日（无异动）运行，breach.triggered=false
- [ ] 断开网络运行，归因逻辑（Hermes 侧）跳过且 Python 端不报错
- [ ] 无新增 Python 依赖，测试全绿


## Risks

| 风险 | 应对 |
| :--- | :--- |
| AI 归因不准确（相关性≠因果性） | Prompt 强调"基于公开信息推测"，输出标注仅供参考、不构成投资建议 |
| 搜索结果噪音大 | 搜索关键词限定时间范围（今日）+ 定向词（VIX+原因） |
| 搜索 API 费用/限速 | 仅异动日触发搜索（每月预计 <5 次），keyless 可用 |
| 归因延迟 | 30 秒超时；超时先推送日报，归因标注"暂不可用" |
| context 生成失败连累日报 | generate_context 独立 try/except，失败记日志、不中断日报生成 |


## 📎 附录：更新后的日报格式

```markdown
# 📊 市场情绪日报
...（一期/二期/三期原有部分不变）

---

## 🤖 AI 市场解读
{常规 AI 解读，200-300 字}

---

## 🔍 异动归因分析（仅异动日，Hermes 追加）
**异动指数**：VIX
**变化**：22.30 → 26.40（+18.4%，触发阈值 ±20%）
**相关事件扫描**：...
**归因结论**：...
**后续关注**：...
*本归因由 AI 基于公开信息生成，仅供参考，不构成投资建议*

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*
```

---

Created: 2026-08-29 | Next: 将本卡交给本地 Agent 开始编码