# Task Handoff：MarketPulse 第十五期 — 开盘分析

> 复制到 `tasks/2026-09-01-marketpulse-phase15/prd.md`


## Goal

在每日开盘时(9:30 A股/21:30 美股)生成开盘分析,对比昨收价分析开盘表现。

## 分析内容

1. **开盘跳空**:与昨收价对比,分析跳空幅度
2. **板块轮动**:开盘时热点板块变化
3. **市场情绪**:结合VIX等指标判断开盘情绪
4. **AI解读**:简短的开盘分析(100-200字)

## 输出

- 独立的开盘分析报告(reports/opening/YYYY-MM-DD.md)
- 可选:推送到QQ

## Constraints

- 数据来源:实时行情(新浪接口)
- 分析时间:开盘后15-30分钟
- 容错:数据不足时优雅降级

## Done When

- [ ] opening_analyzer.py 实现
- [ ] 开盘分析报告生成
- [ ] 日报中引用开盘分析
- [ ] pytest 全绿
