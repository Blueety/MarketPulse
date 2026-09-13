# Journal — 黄金展示位换 COMEX 期货（GC=F）：概览卡 + 另类资产趋势图

- 日期：2026-09-13（凌晨）
- 角色：编码执行者；按 `plan.md`（方案 A：前端叠加 /api/macro 序列）实施
- 背景：概览卡原显示 GLD×10=3,987.70（×10 是画图缩放非金价，语义错位）；用户确认两处黄金
  展示位换 GC=F（COMEX 期货实时 ~4,3xx）

## 目标

① 概览卡黄金位显示 GC=F 实时报价；② 另类资产趋势图黄金线换 gc=f 实时序列（图例「黄金 COMEX」），
BTC 不动；GLD 保留在 history/SQLite 作 EOD 历史；零 src/ 改动。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/app.py` | +1 行 | `_MACRO_DEFAULT` 加第 4 项 `{"symbol": "GC=F", "label": "黄金COMEX"}` |
| `web/static/app.js` | ±35 行 | ① `SERIES_VAR` 加 `"gc=f": "--c-gld"`（金色沿用 GLD token，meta/数据集同色）；② `OVERVIEW_CARDS` GLD 条目 → `GC=F`（source: macro、去 scale）；③ `ICON_COLORS` 补 `"GC=F": "--c-gld"`；④ `GROUPS` alt 组 `keys:["btc"]` + `macroGold:"gc=f"`；⑤ `renderMainChart` alt 分支：日期轴 history ∪ macro 并集（周末过滤同 buildTradingAxis）、gc=f 逐日投影 + filled 前向填充（spanGaps 等价）、数据集沿用 `buildLineDataset`；⑥ macro fetch 成功回调补 `renderMainChart()`（覆盖 macro 晚到且停在 alt tab 的时序）；`renderTrendMeta` alt 组 meta 2 条 |
| `tests/test_web.py` | ±8 行 | 内置默认 3→4 标的断言（4 处 len/列表断言同步） |
| `AGENTS.md` / `docs/architecture.md` / `docs/pitfalls.md` | 收尾 | /api/macro 描述加黄金 / 决策行 / 「画图缩放≠展示换算」坑 |

## 验证结果（全部实际运行）

| 项 | 结果 |
|---|---|
| 红跑 | 宏观默认断言 2 条 FAIL（3→4） |
| S1 | test_web **78 passed**；配置覆盖检查：config.json 无 macro.stocks、env MACRO_STOCKS 未设 → 内置默认生效（**Railway env 需用户自查**，若设了 MACRO_STOCKS 须把 GC=F 补进那份列表） |
| S2/S3 | verify_ui **ALL PASSED** |
| 运行时 | `/api/macro` stocks 含 **GC=F=4408.9**（实时）；gc=f trend 30 点 + change_7d +8.89%；概览黄金卡 =「黄金 · COMEX / 4,408.90」；alt 图 2 数据集（比特币 30 点 + 黄金COMEX 30 点） |
| 回归 | `pytest tests/` **548 passed**（并行会话新增用例含在内） |

## 遇到的问题

1. **宏观默认断言漏扫**：首轮只改了 2 处 `== ["DX-Y.NYB",...]` / `len==3`，实际共 4 处
   （env 非法用例的第二段 + config 抛异常用例）——grep 断言关键字（`len(_load_macro_stocks())`）
   全量清点后再动手。
2. **并行会话并行推进**：本任务执行期间仓库出现另一执行者的任务（rss-macro-news、
   frontend-polish，+34 条新测试、`src/news_saver.py`/`rss_fetcher.py`、news.json 已有真数据
   ——news 任务的 Hermes 侧交付已完成）。动手前 grep 确认共享文件无他人未提交改动叠加；
   本任务四点改动应用干净无冲突。
3. **macro 窗口 30 天 vs 趋势图 1Y**：gc=f 序列仅 ~30 交易日，1Y 视图下金线只覆盖最近 30 天
   （诚实呈现，非 bug）；后续若要全窗，需 macro 序列按 state.days 拉长（另议）。

## 下次注意什么

- 「展示位」与「画图缩放」分离：GLD×10 是归一化画图系数，报价位必须用品种实时报价链路。
- 改「内置默认」类配置时，grep 该默认的全部断言（含 len 型）+ 检查 config/env 覆盖链——
  覆盖存在时改默认不生效。
- 趋势图叠加外部序列：日期轴并集 + 逐日投影 + filled 前向填充三步，直接复用 buildLineDataset
  （label/key/color 由 SERIES_VAR token 提供）。
- 多执行者并行环境：开工先 `git log --oneline -5` 摸清并行任务，改共享文件前 grep 现状。
