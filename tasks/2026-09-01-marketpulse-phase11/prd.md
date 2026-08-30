# Task Handoff：MarketPulse 第十一期 — Web 看板

> 复制到 `tasks/2026-09-01-marketpulse-phase11/prd.md`


## Goal

为 MarketPulse 开发 Web 看板，通过浏览器展示最近 7 天市场数据（趋势图、指数表格、板块热度、告警记录）。

## 数据来源（只读）

| 数据 | 文件路径 |
|------|---------|
| 历史行情 | data/history.json |
| 告警记录 | alerts/*.md |
| 板块热度 | 从 history.json 最新条目或单独 JSON |

## 看板模块

1. **市场概览**：最新一天所有指数收盘价+涨跌幅表格
2. **趋势图**：所有指数近7天走势（Chart.js）
3. **板块热度**：当日热点板块 Top5
4. **告警记录**：最近10条告警

## 技术栈

- 后端：FastAPI + uvicorn + jinja2
- 前端：HTML + CSS + Chart.js（CDN）
- 数据：直接读取现有 JSON 文件，无数据库

## 文件结构

```
web/
├── app.py              # FastAPI 主应用
├── templates/
│   └── index.html      # 前端页面
└── static/             # 预留
```

## API 端点

- GET / → HTML 页面
- GET /api/history → 最近7天数据
- GET /api/alerts → 最近10条告警
- GET /api/latest → 最新一天摘要

## Constraints

- 轻量级：无数据库，直接读 JSON
- 单页应用：所有内容一个页面
- 响应式：适配桌面和手机
- 数据只读
- Chart.js CDN 加载

## Done When

- [ ] uvicorn web.app:app --reload 能启动
- [ ] 浏览器访问 localhost:8000 能看完整看板
- [ ] 趋势图显示多条折线
- [ ] 手机浏览器布局自适应
- [ ] pytest 全绿

## Verification

- [ ] 启动服务无报错
- [ ] 页面正常加载
- [ ] 数据与 history.json 一致
- [ ] 手机模拟布局正常
