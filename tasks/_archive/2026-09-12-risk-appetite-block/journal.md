# Journal — 看板「风险偏好」子块接真数据（点亮第一个占位）

- 日期：2026-09-12
- 角色：编码执行者；按 `plan.md`（方案 B：后端纯函数合成）实施
- 基线：pytest 498 passed / verify_ui ALL PASSED（SQLite 迁移任务刚完成）

## 目标

`#risk-appetite` 子块从静态占位点亮为真实风险偏好仪表：`/api/latest` 新增 `risk_appetite`
（纯函数 `_compute_risk_appetite` 合成：VIX 状态 + MOVE 状态 + VIX 5 日变化三点打分），
前端只渲染。零新增取数、零 src/ 改动、context 契约不动。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/app.py` | +52 行 | `_compute_risk_appetite(indices, records)` 纯函数（classify_vix/classify_move 词表复用；5 日=最近 6 个非 None 收盘首尾比，±5% 阈值模块常量 `_RISK_VIX_5D_PCT`）；`api_latest` 接线：`_last_records(7)→(10)`、两分支恒含 `risk_appetite` 键 |
| `web/templates/index.html` | ±1 行 | `#risk-appetite` 摘 `data-placeholder="1"`（div 保留） |
| `web/static/app.js` | +24/-2 行 | `PLACEHOLDERS` 摘 risk-appetite 项（双点同步）；`renderRiskAppetite(latest)`（level→标签+pos/neg/muted 色；factors→12px 小字行；null→「数据暂缺」不隐藏）；`refresh()` 的 renderSector 后接入 |
| `web/static/style.css` | +11 行 | `.ra-label`（15px/600 + pos/neg/muted token）+ `.ra-factors`（flex-wrap 紧凑单双行，12px） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 同步 | G9 与视口断言占位计数 3→2（两处） |
| `tests/test_web.py` | +75 行 | 7 条纯函数用例（high/low/neutral/level-null/5日不足/None 间隙/端点键） |
| `AGENTS.md` / `docs/pitfalls.md` | 收尾 | 占位计数 3→2 + 点亮说明 / 双点同步坑 |

## 验证结果（全部实际运行）

| 项 | 结果 |
|---|---|
| 红跑 | 7 条新用例 FAIL（函数未实现/键缺失） |
| S1 绿 | test_web **69 passed**（7 新用例全绿） |
| S2 | verify_ui **ALL PASSED**（占位计数 2、scrollHeight@1920=**1219** 仅 +3、三视口无溢出） |
| S3 | `pytest tests/` **505 passed** |
| 运行时 | `/api/latest` risk_appetite = neutral/0（VIX 15.84 平静 +1、MOVE 82.2 平静 0、5 日 +9% -1），**与概览表 VIX 同源一致**（15.84） |

## 遇到的问题

1. **测试数据两处自伤**：①VIX indices 缺失时断言 factors 只含 MOVE——实际 5 日因子由 records
   独立计算（plan「factors 尽列可得项」的正确结果）；②None 间隙序列只给 5 个非 None（差 1）。
   都是我的测试写错，实现符合 plan。
2. **高度预算**：plan §4 预警子块 40→70px 会顶破 scrollHeight 1240——采用紧凑设计
   （factors flex-wrap 单双行）后实测仅 +3px（#sectors 249→251，scrollH 1216→1219），无需二次压缩。
3. **verify_ui 的 G9/视口占位计数断言硬编码 3**——plan §2 文件清单漏列 verify_ui.py，实际必须
   同步（两处断言点：assert_g9 + assert_viewport）。已记 pitfalls。

## 下次注意什么

- 点亮占位块 = 双点同步（HTML 摘属性 + app.js 注册表删项）+ verify_ui 占位计数断言，三处一批改。
- 合成型小部件的测试数据：records 与 indices 是两个独立输入，缺失场景要分别覆盖。
- 高度预算先算后写：子块增高 × 行 3 卡数会进 scrollHeight 预算，flex-wrap 紧凑排版可把
  +30px 压到 +3px。
