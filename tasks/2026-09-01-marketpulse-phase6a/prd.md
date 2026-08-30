# Task Handoff：MarketPulse 第六期 A — 美股大盘监控

> 复制到 `tasks/2026-09-01-marketpulse-phase6a/prd.md`


## Goal

在现有 VIX/VXN/MOVE 波动率监控基础上,增加美股(标普 500、纳斯达克)大盘指数的日度监控,生成包含"美股大盘 + 波动率指数"两个板块的合并日报,通过 QQ 统一推送。

A 股(上证/深证)留到六期 B,本次不做。

## 已确认的设计决策（用户定稿）

1. **仅加美股,A 股暂缓** — 先验证 Yahoo 对美股指数的数据质量,再决定 A 股。
2. **零新依赖** — 全部走 Yahoo Finance,不加新包。
3. **告警独立** — 大盘告警和 VIX 告警分开记录,互不干扰。
4. **向下兼容** — 在现有日报上加板块,不破坏已有内容。
5. **context 复用 `generate_context()`** — 不新建 context_builder.py,扩展 reporter.py 已有函数。

## 新增监控标的

| 市场 | 指数 | Yahoo 代码 | 告警阈值 |
|------|------|-----------|---------|
| 美股 | 标普 500 | `^GSPC` | ±4% |
| 美股 | 纳斯达克 | `^IXIC` | ±4.5% |

## 现有标的（保持不变）

| 指数 | Yahoo 代码 | 告警阈值 |
|------|-----------|---------|
| VIX | `^VIX` | ±20% |
| VXN | `^VXN` | ±20% |
| MOVE | `^MOVE` | ±15% |

## 报告结构（两板块）

```
# 📊 全市场情绪日报
## 🌏 美股大盘 (标普500 + 纳斯达克, 收盘价+涨跌幅+趋势)
## 📈 波动率指数 (VIX/VXN/MOVE, 收盘价+涨跌幅+状态)
## 🤖 AI 市场解读 (扩展上下文,含美股数据)
```

## Requirements

### 数据获取层
- `src/fetcher.py` — SYMBOLS 扩展:新增 `^GSPC`/`^IXIC`,保持统一获取逻辑
- 单次运行从 3→5 指数,仍远低于 Yahoo 限流阈值
- 大盘数据格式与 VIX/VXN/MOVE 一致(value/change_pct/status)

### 分析层
- `src/analyzer.py` — 大盘涨跌幅计算复用 `compute_changes()`
- 趋势判断:连续 N 日涨跌(N 初始为 3),基于 history.json
- 大盘数据写入 `data/history.json`(扩展字段,向下兼容)

### 报告层
- `src/reporter.py` — 日报模板增加"美股大盘"板块(位于波动率之前)
- 趋势图暂不包含大盘(仅保留 VIX/VXN/MOVE 三面板)
- 每个指数:收盘价 + 涨跌幅 + 趋势描述

### 告警层
- `src/alerter.py` — 大盘告警阈值:GSPC ±4%, IXIC ±4.5%
- `check_breach()` 已支持任意阈值,只需在 SYMBOLS 中配置
- 告警文件共用 `alerts/YYYY-MM-DD-{type}.md`,但按指数分块

### Context 与 AI
- `generate_context()` 扩展,indices 包含 5 个指数
- history_30d 包含大盘数据
- Hermes prompt 更新,AI 解读中自然包含美股大盘描述

### 测试
- 新增大盘获取/涨跌幅/告警/趋势测试
- 既有 113 项测试不受影响

## Constraints

- 零新依赖
- 调度不变(Hermes cron 早 8 点)
- 向下兼容(现有 VIX/VXN/MOVE 内容不变)
- 首次运行无大盘历史时,趋势列显示"数据积累中"
- 交易日判断:简单规则(周末不交易),节假日暂不处理

## Done When

- [ ] SYMBOLS 扩展为 5 个指数(GSPC/IXIC + VIX/VXN/MOVE)
- [ ] fetcher 获取 5 个指数数据,单次运行 ≤15 秒
- [ ] analyzer 计算大盘涨跌幅 + 连续涨跌天数趋势
- [ ] reporter 日报包含"美股大盘"板块(格式正确)
- [ ] alerter 大盘告警阈值(GSPC ±4%, IXIC ±4.5%)生效
- [ ] history.json 包含大盘数据(向下兼容)
- [ ] context JSON 包含 5 个指数
- [ ] 所有测试通过(原 113 + 新增)

## Verification

- [ ] 运行 daily_report.py,检查日志输出 5 个指数
- [ ] reports/*.md 包含两个板块(美股大盘 + 波动率)
- [ ] history.json 包含 GSPC/IXIC 数据
- [ ] 模拟 GSPC 变化率超 ±4%,确认告警生成
- [ ] context JSON 包含 5 个指数的 indices
- [ ] pytest tests/ -v 全绿

## Risks

| 风险 | 应对 |
|------|------|
| Yahoo 对 ^GSPC/^IXIC 数据延迟 | 日频数据够用,收盘后几小时才推送 |
| 报告信息量增大(5 指数) | 保持表格格式简洁,不加长段落 |
| 大盘+波动率告警同时触发 | 告警文件按指数分块,推送时合并 |
| history.json 字段扩展兼容 | 新字段 optional,旧数据不受影响 |