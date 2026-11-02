# 补丁：A 股领跌板块 Top 5

> 八期已完成领涨板块,本次补丁增加领跌板块。

## 改动范围

### src/fetcher.py
- `fetch_sector_heat()` 返回值从 `list[dict]` 改为 `tuple[list[dict], list[dict]]`
- 返回 `(gainers, losers)`,一次取数两路排序(降序+升序)
- 失败/超时返回 `([], [])`

### src/reporter.py
- `render_report` 接收 tuple 格式的 sector_heat
- 新增"📉 A 股领跌板块 Top 5"表格(位于领涨表格之后)
- 表格格式与领涨一致(板块/涨跌幅/成交额/领涨股)

### daily_report.py
- 无需改动(直接透传 sector_heat tuple)

### context
- sector_heat 字段改为 `{gainers: [...], losers: [...]}` 格式

### 测试
- 更新 test_phase8.py:mock 返回 tuple
- 新增领跌测试用例

## 验证

- 运行 daily_report.py,检查日报含领跌表格
- pytest tests/ -v 全绿