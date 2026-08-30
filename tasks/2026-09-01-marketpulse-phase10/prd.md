# Task Handoff：MarketPulse 第十期 — 黄金 & 比特币监控

> 复制到 `tasks/2026-09-01-marketpulse-phase10/prd.md`


## Goal

新增黄金(GLD)和比特币(BTC-USD)两个另类资产的日度监控，纳入日报和趋势图。

## 新增标的

| 资产 | Yahoo 代码 | 说明 |
|------|-----------|------|
| 黄金 | GLD | SPDR Gold Trust ETF（比期货连续合约更平滑） |
| 比特币 | BTC-USD | Bitcoin 兑美元（7×24交易） |

## 数据源

Yahoo Finance（沿用现有，零新依赖）

## 日报展示

在"A 股大盘"之后新增"💰 另类资产"板块：
- 收盘价 + 涨跌幅 + 趋势（连续涨跌天数）

## 趋势图

新增"另类资产趋势图"（2×1 双面板）：
- 上：GLD 近30日走势
- 下：BTC-USD 近30日走势
- 输出：reports/charts/YYYY-MM-DD-alts-trend.png

## history.json

新增字段：gld, btc

## Constraints

- 零新依赖（Yahoo 已有）
- 比特币7×24交易，日度收盘用 Yahoo 提供的值
- 黄金/比特币告警与现有告警分离
- 趋势图每个子图独立 y 轴

## Done When

- [ ] fetcher 支持 GLD 和 BTC-USD
- [ ] analyzer 增加涨跌幅和趋势判断
- [ ] reporter 日报新增"另类资产"板块
- [ ] reporter 新增 alts 趋势图（2×1）
- [ ] history.json 包含 gld/btc 字段
- [ ] pytest 全绿

## Verification

- [ ] 运行 daily_report.py 检查日报含另类资产
- [ ] 检查 alts-trend.png 生成
- [ ] 断网运行不崩溃
