# Task Handoff：MarketPulse 第二十七期 — 资讯落盘

> 复制到 `tasks/2026-09-06-marketpulse-phase27/prd.md`


## Goal

Tavily 搜索完成后,把结果整理写入 `data/news.json`,供 Web 看板"最新资讯"卡片展示。

## 核心需求

1. **筛选**:从搜索结果中挑 3~8 条与今日行情最相关、最重要的新闻,按重要性降序排列
2. **字段**:
   - `title`(必填):新闻标题,保留原文
   - `url`(必填):原文链接,必须以 http:// 或 https:// 开头
   - `source`(选填):媒体名
   - `published`(选填):发布日期,格式 YYYY-MM-DD
   - `summary`(选填):一句话中文摘要,不超过 80 字
3. **文件结构**:
   ```json
   {"date": "YYYY-MM-DD", "items": [...]}
   ```
4. **原子写入**:先写 `news.json.tmp`,再重命名为 `news.json`
5. **边界处理**:
   - title 或 url 缺失/为空的条目直接丢弃
   - url 不是 http(s) 开头的条目直接丢弃
   - 搜索失败或可用结果不足 3 条→不写文件(保留上一次的资讯)
   - 只允许写 `data/news.json` 这一个文件

## 改动量

- 新增 `src/news_saver.py`:~50 行
- 修改 `daily_report.py`:~10 行(调用 news_saver)
- 零后端/测试/依赖变更