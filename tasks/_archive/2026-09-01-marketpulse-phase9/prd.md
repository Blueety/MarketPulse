# Task Handoff：趋势图扩展（分市场双图）

> 复制到 `tasks/2026-09-01-marketpulse-phase9/prd.md`


## Goal

在现有 VIX/VXN/MOVE 三面板趋势图基础上，新增两张按市场拆分的趋势图：
1. 美股大盘趋势图（2×1）：标普500、纳斯达克
2. A股大盘趋势图（3×1）：上证指数、深证成指、创业板指


## 实际数据字段（history.json）

```json
["date", "gspc", "ixic", "sh", "sz", "cyb", "vix", "vxn", "move"]
```

| 图表 | 数据字段 | 布局 | 输出文件 |
|------|---------|------|---------|
| 美股大盘趋势图 | `gspc`、`ixic` | 2×1 | `reports/charts/YYYY-MM-DD-us-trend.png` |
| A股大盘趋势图 | `sh`、`sz`、`cyb` | 3×1 | `reports/charts/YYYY-MM-DD-cn-trend.png` |


## Constraints

- 复用现有绘图风格（颜色、字体、网格、日期格式）
- 独立失败：任一图失败不影响其他图和日报
- 数据不足时子图显示"数据不足"
- 绘图时间 ≤5 秒
- 不修改现有 generate_trend_chart()


## Done When

- [ ] 新增通用趋势图函数，支持 2×1 和 3×1 布局
- [ ] 美股趋势图正常生成（gspc/ixic）
- [ ] A股趋势图正常生成（sh/sz/cyb）
- [ ] 日报中新增两个引用章节
- [ ] pytest tests/ -v 全绿


## Verification

- [ ] 运行 daily_report.py，检查 reports/charts/ 下生成两张新图
- [ ] 原有 VIX/VXN/MOVE 趋势图未受影响
