# Task Handoff：MarketPulse 第十四期 — 日报图片化推送

> 复制到 `tasks/2026-09-01-marketpulse-phase14/prd.md`


## Goal

将每日 Markdown 日报+趋势图转换为一张完整图片,由 QQ 机器人推送。

## 目标图片结构(手机竖屏长图)

1. 头部:项目标题+日期
2. 核心指数卡片区:2列网格(数值+涨跌幅+颜色)
3. 趋势图区:嵌入已有 trends PNG
4. AI 市场解读区:200-300字
5. 告警区:如有告警
6. 脚注:数据来源

## 技术选型

- imgkit(HTML→图片)
- Jinja2 模板
- wkhtmltopdf 系统工具

## Constraints

- 宽度600px,高度自适应
- 图片≤800KB
- PNG 格式
- 中文字体(PingFang SC/Microsoft YaHei)
- 渲染≤15秒
- 容错:趋势图缺失显示"暂缺"
- 保留 .md 文件,推送用 .png

## Done When

- [ ] src/image_renderer.py 实现
- [ ] web/templates/report_card.html 模板
- [ ] daily_report.py 调用渲染
- [ ] reports/images/ 生成图片
- [ ] QQ 收到图片
- [ ] 图片手机可读
- [ ] pytest 全绿
