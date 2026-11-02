# Plan — 2026-09-17 前端体验走查（MarketPulse web 看板）

## 目标
以「前端体验官」8 维度框架对 `/`、`/macro`、`/macro/cn` 三页做实证走查，产出报告。

## 涉及文件
- 只读：`web/templates/*.html`、`web/static/*.js|css`、`web/app.py`、`config.json`
- 产出：`tasks/2026-09-17-frontend-ux-review/report.md`（交付物）
- 探针（不落仓库）：`%TEMP%\mp_review\audit.py|extra.py|audit.json|extra.json|*.png`

## 方法
1. `AUTO_PUSH=0 uvicorn web.app:app --port 8731` 起服务（探针自选端口）。
2. Playwright 4 视口（1500/1024/769/390）× 3 页：截图 + DOM 量化
   （横向溢出、骨架残留、坏文本、可聚焦元素命名、焦点环、landmark、对比度、console/失败请求）。
3. 交互取证：趋势 tab、时间范围、板块双 tab、主题切换（含 reload 持久化）、refresh 反馈、移动端抽屉。
4. 探针口径复核：低对比度逐条回查 CSS 真实背景（promo 卡渐变 → 误报剔除）；
   w390 溢出 66 条全部为 off-canvas 侧栏（left<-240，探针口径内非真实溢出）。

## 验证命令
`venv/Scripts/python %TEMP%\mp_review\audit.py` → 退出码 0 且 `audit.json` 生成。
