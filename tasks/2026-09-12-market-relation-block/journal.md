# Journal — 看板「市场关系」子块接真数据（显著相关对 pills）

- 日期：2026-09-12
- 角色：编码执行者；按 `plan.md`（方案 A：context 显著对直通）实施；前置 risk-appetite 已合入
- 基线：pytest 505 passed / verify_ui ALL PASSED（开工时点）

## 目标

`#market-relation` 子块从 4 个写死 disabled 胶囊点亮为数据驱动 pills：`/api/latest` 新增
`correlation` 键（ctx 显著对直通，恒有键），前端按 |r| 降序渲染（正=红/同向、负=绿/对冲、
hover 提示样本数），空数组 → muted 空态文案。零计算零取数零 src/ 改动。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/app.py` | +12 行 | `_correlation_payload(ctx)`（list 直通 / None / 坏类型 → []，容错同 `_sector_payload`，不做逐条字段校验）；`api_latest` 两分支恒含 `correlation` 键 |
| `web/templates/index.html` | -4/+1 行 | `.pill-row` 清空静态 4 胶囊（容器保留，JS 填充） |
| `web/static/app.js` | +20 行 | `renderMarketRelation(latest)`（\|r\| 降序 cap 5、pos/neg 色、`title="近{n}个交易日"`、空态 `.ph-note`）；refresh 链 renderRiskAppetite 后接入 |
| `web/static/style.css` | +5 行 | `.pill.pos`(红)/`.pill.neg`(绿) 提色 + `.pill-row .ph-note` 行高（原 .pill 灰态是禁用 button 装饰） |
| `tests/test_web.py` | +38 行 | 5 条：直通 / None / 坏类型 / 空	ctx 键恒有 / ctx 带对透出（TestClient + CONTEXT_DIR patch） |
| `AGENTS.md` / `docs/pitfalls.md` | 收尾 | web 行补 correlation 键 / 「未打标的的死块」+「周六冒烟工件」两条坑 |

## 验证结果（全部实际运行）

| 项 | 结果 |
|---|---|
| 红跑 | 4 条新用例 FAIL（函数未实现/键缺失） |
| S1 绿 | test_web **73 passed** |
| S2 | verify_ui **ALL PASSED**（scrollH 1220，pill-row 24px 单行） |
| S3 | `pytest tests/` **509 passed** |
| 运行时 | pills 渲染与最新 context 逐条一致：`VIX ↔ 标普500 -0.80`(neg)、`MOVE ↔ VIX +0.70`(pos)、\|r\| 降序、title=近23个交易日、row 高 24px |

## 遇到的问题

1. **冒烟工件污染对照源**：13:37 的周六 daily 冒烟生成了非交易日的 `context/2026-09-12.json`
   （ET 日期=当天周六），`_load_latest_context` 选中它 → 我的对照断言（拿 09-11 文件）失败。
   API 行为正确，是**对照参照选错 + 冒烟工件**两个问题叠加。处置：删 09-12 工件（与 history
   行同类），对照改为**最新日期** context 文件。教训已进 pitfalls。
2. **「市场关系」是未打标的的死块**：grep `data-placeholder` 的占位盘点从不含它（4 个写死
   disabled 胶囊、无标记）。本块点亮后全站占位剩 2（资金流向/最新资讯），后续点亮需先人工
   页面盘点，不能只信标记 grep（已记 pitfalls）。
3. **同卡叠加高度**：#sectors 在 risk-appetite 加高后本任务再叠加，实测 pill-row 24px 单行、
   #sectors 252（仅 +1），scrollH 1220 ≤ 1240，无需触发 cap 5→4 回退开关。

## 下次注意什么

- 「API 与 context 对照」必须取**最新日期**的 context 文件——冒烟/实验工件可能比预期日期新。
- 显著对着色语义：正 r=红（同向联动/风险集中）、负 r=绿（对冲），与日报相关性表一致。
- 点亮死块前先页面人工盘点 + grep 双确认（`data-placeholder` 只覆盖打了标记的）。
- 后续备忘：宏观序列落盘后可补算「股指 vs 美债」等三对故事 pill，与本渲染函数直接兼容。
