# 补丁：美股板块领涨/领跌(11个SPDR Sector ETF)

## 目标

美股日报新增"🔥 美股板块领涨 Top 5"和"📉 美股板块领跌 Top 5"表格,与 A 股板块逻辑一致。

## 数据源

Yahoo Finance 11个 SPDR Sector ETF(代码:XLK/XLF/XLE/XLV/XLI/XLP/XLY/XLU/XLB/XLRE/XLC)

## 改动范围

### src/fetcher.py
- 新增 `fetch_us_sector_heat(top_n=5) -> tuple[list[dict], list[dict]]`
- 用 Yahoo chart REST 获取 11 个 ETF 涨跌幅
- 返回 `(gainers, losers)`,格式与 A 股板块一致
- 失败/超时返回 `([], [])`

### src/reporter.py
- `render_report()` 新增 `us_sector_heat=None` 参数
- 美股大盘表格下方新增领涨+领跌两个表格
- 美股快照(`render_snapshot`)也支持板块数据

### daily_report.py
- 调用 `fetch_us_sector_heat()`,传递给 reporter

### context
- `generate_context()` 扩展 `us_sector_heat` 字段

### 测试
- 新增 test_us_sector.py 或扩展 test_phase8.py

## 验证

- 运行 daily_report.py,检查日报含美股板块表格
- pytest tests/ -v 全绿
