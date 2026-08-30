# Task Handoff：MarketPulse 第八期 — A 股板块热度监控

> 复制到 `tasks/2026-09-01-marketpulse-phase8/prd.md`


## Goal

接入 AkShare 概念板块数据,在日报中展示当日最热门 Top 5 概念板块(名称、涨跌幅、成交额、领涨股),丰富市场情绪感知。

## 已确认设计决策

1. **数据来源**:AkShare `stock_sector_spot(indicator="概念")`,已验证可用
2. **展示数量**:Top 5 按涨跌幅排序
3. **展示位置**:日报"A 股大盘"表格下方,新增"🔥 A 股热点板块 Top 5"
4. **容错**:AkShare 失败时返回空列表,不影响日报
5. **context 扩展**:板块数据写入 context.json 供 AI 解读
6. **不加新告警**:板块异动写入 search_keywords,不触发独立告警

## AkShare 实际 API

```python
df = ak.stock_sector_spot(indicator="概念")  # 175 个概念板块
# 实际列名(非 PRD 假设):
# 板块, 涨跌幅, 总成交额(元), 股票名称, 个股-涨跌幅
# 成交额需格式化为"亿"(÷1e8)
```

## 返回格式

```python
[
    {"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"},
    {"name": "生物育种", "change": 3.63, "turnover": "72.2亿", "top_stock": "敦煌种业"},
    ...
]
```

## Requirements

### fetcher.py
- 新增 `fetch_sector_heat(top_n=5) -> list[dict]`
- 失败返回空列表,不抛异常
- 成交额格式化为"X.X亿"

### reporter.py
- 日报 A 股板块后新增"🔥 A 股热点板块 Top 5"表格
- 表格列:板块 | 涨跌幅 | 成交额 | 领涨股

### context
- `generate_context()` 扩展,新增 `sector_heat` 字段
- AI 解读时可参考板块热点

### daily_report.py
- 传递板块数据到 reporter

## Constraints

- 零新依赖(AkShare 已安装)
- 板块获取超时 ≤10 秒
- 失败时显示"数据暂缺",不中断日报
- 测试覆盖 fetch_sector_heat 的成功/失败场景

## Done When

- [ ] fetch_sector_heat() 返回 Top 5 概念板块
- [ ] 日报包含"🔥 A 股热点板块 Top 5"表格
- [ ] context.json 包含 sector_heat 字段
- [ ] AkShare 失败时日报正常生成
- [ ] 所有测试通过

## Verification

- [ ] 运行 daily_report.py,检查日报含板块表格
- [ ] 检查 context.json 含 sector_heat
- [ ] 断网运行,确认容错
- [ ] pytest tests/ -v 全绿