# Journal — 2026-09-17 前端体验走查

## 目标
以「前端体验官」8 维度框架走查 `/`、`/macro`、`/macro/cn`。

## 改动文件清单
- 新增 `tasks/2026-09-17-frontend-ux-review/plan.md`、`report.md`、本文件。
- **零源码改动**（纯只读走查）。
- 探针（不落仓库）：`%TEMP%\mp_review\{audit.py,extra.py,audit.json,extra.json,*.png}`。

## 验证结果
- 服务：`AUTO_PUSH=0 uvicorn web.app:app --port 8731`，12 个端点全部 200。
- Playwright 4 视口 × 3 页：0 console 错误、0 失败请求、0 真实横向溢出、骨架 0 残留。
- 交互：tab/范围/板块 tab/主题（含 reload 持久化）/锚点 全通过；refresh 无反馈（发现项）。
- 对比度：浅色主题系统性 2.19–2.54（P1）；深色仅 2 处 3.68。

## 遇到的问题
- **探针误报两处，均已回查排除**：① promo 卡「白字对比度 1.06」——实际背景是不透明渐变（探针只读 backgroundColor）；② w390 的 66 条溢出——全部是 off-canvas 侧栏（left<-240）。
- `#macro-vars` 在 evaluate 里 null 崩了一次 → 取 DOM 文本必须全部走 null 安全包装。
- 趋势 tab 实际文案是「A 股大盘」（含空格），`:has-text('A股')` 匹配不到。

## 下次注意
- 上游 403 时代看板常驻降级态：**红条数≠回归**，验收必须基线 A/B（记忆已有条目，本次再次验证）。
- 对比度探针必须解析 `background-image` 渐变，否则会把不透明渐变卡误判成低对比。
- `refresh()` 的 `catch(){}` 静默吞错是 P1，修复时顺手补 aria-live（全页 0 个）。
