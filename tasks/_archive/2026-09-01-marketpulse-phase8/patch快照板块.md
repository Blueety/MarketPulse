# 补丁：A 股收盘快照加板块领涨/领跌

## 目标

A 股收盘快照(15:00)和午盘快照(11:30)加上"🔥 领涨 Top5"和"📉 领跌 Top5"表格,与日报格式一致。

## 改动范围

### snapshot_report.py
- 调用 `fetch_sector_heat()` 获取板块数据
- 传递给 `save_snapshot()` 渲染

### src/reporter.py
- `render_snapshot()` 新增 `sector_heat=None` 参数
- A 股快照中渲染领涨+领跌两个表格(格式与日报一致)
- 美股快照不受影响(无板块数据)

### 测试
- 更新 test_snapshot 相关用例

## 验证

- 运行 `snapshot_report.py --market a-share --time close`,检查快照含板块表格
- pytest tests/ -v 全绿
