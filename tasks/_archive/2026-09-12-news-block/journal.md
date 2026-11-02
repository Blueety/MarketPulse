# Journal — 看板「最新资讯」接真数据（契约先行：Hermes 落盘 + web 消费）

- 日期：2026-09-12
- 角色：编码执行者；按 `plan.md`（方案 B：契约先行）实施；前置 risk-appetite / market-relation 已合入
- 基线：pytest 509 passed / verify_ui ALL PASSED（开工时点）

## 目标

`#news` 卡点亮为资讯流：定义资讯 JSON 契约 → Hermes 侧（用户改 cron prompt，**非仓库代码**）
落盘 `data/news.json` → 仓库侧新增 `/api/news` 只读端点 + 前端渲染。坏文件/缺文件全空态、
HTTP 200 恒定。repo 侧独立交付，未接入前空态即验收态。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/app.py` | +48 行 | `NEWS_FILE` 常量（**定义在使用方 web.app**，monkeypatch 纪律）；`_load_news()`（容错空态 / 条目过滤 title 非空 + url http(s) 前缀 / 缺省字段补 "" / cap 8）；`GET /api/news` → `{date, items, count}` |
| `web/templates/index.html` | ±3 行 | `#news` 摘 `data-placeholder="1"`；h2 加 `<span id="news-date">`；body 去 ph-body 类 |
| `web/static/app.js` | +20/-1 行 | `PLACEHOLDERS` 摘 news（双点同步）；`renderNews`（escapeHtml 全量、`target=_blank rel=noopener noreferrer`、空态「暂无资讯」）；init 块 `fetchNews`（alerts 同款模式） |
| `web/static/style.css` | +12 行 | `.news-item`（标题 13px 600 / meta 11px muted / 摘要 line-clamp 2 / hover 蓝） |
| `tests/test_web.py` | +58 行 | 6 条：缺失文件 / 合法过滤+cap+键集 / 坏 JSON / 非 dict / 缺 items 键 |
| `docs` 四处 | 收尾 | architecture 决策行（**契约原文落档**，作为用户改 Hermes prompt 的唯一依据）/ AGENTS（6 API、占位 1、data/news 行）/ pitfalls（双写者边界）/ commands（/api/news） |

## 验证结果（全部实际运行）

| 项 | 结果 |
|---|---|
| 红跑 | 5 条新用例 FAIL（端点缺失） |
| S1 | test_web **78 passed** |
| S2 样例验证 | 临时 `data/news.json`（2 条合法 + 1 条缺 url）→ API **count=2**（坏条目被滤）→ Playwright 渲染：`#news-date`=「· 2026-09-12」、链接 `target=_blank` + `rel=noopener noreferrer`、meta 行就位 → **样例文件已删除**（git 追踪范围，防 cron 提交假资讯） |
| S3 | `pytest tests/` **514 passed**；verify_ui **ALL PASSED**（占位计数 2→1 同步断言，仅剩资金流向） |

## 遇到的问题

1. **首版测试块有草稿残留**（不存在的 helper、怪异条件）——整体删掉重写为干净版本（`_write_news`
   helper + tmp_path 隔离），教训：追加式写测试也要一次写成成品。
2. **plan §2 未列 verify_ui.py**：占位计数断言 2→1 是点亮任务的必然连带（同 G9 两处断言点），
   与 risk-appetite 任务同类偏差，本任务提前预料并同步。

## 交付侧提醒（用户执行，非仓库代码）

按 `docs/architecture.md` 决策行的契约更新 Hermes「每日数据更新」cron prompt——tavily 搜索
完成后将 3~8 条结果写 `data/news.json`（tmp+rename 原子写，title/url 必填）。之后跑一次 cron：
`git status` 应见 `data/news.json`，看板自动出真资讯。未接入前卡片显示「暂无资讯」为正常空态。

## 下次注意什么

- 点亮占位三件套：HTML 摘属性 + PLACEHOLDERS 删项 + verify_ui 占位计数断言，一批完成。
- 外部生产者落盘的文件（Hermes 的 news.json）：读端逐层容错 + 写入口格式校验（url http(s) 前缀
  防 javascript: 注入）+ cap 防超量，永不 500。
- git 追踪范围内的「验证期样例文件」用完即删（本机 cron 每 ~5 分钟 git add -A，样例会被提交成
  假数据）。
- 追加式写测试/文档也要成品质量——草稿残留会进仓库。
