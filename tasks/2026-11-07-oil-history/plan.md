# 实施计划

## 任务概要

- **档位**: `T3 — 22 文件 / 0 外部调用方（但改动 3 个跨层消费点 + 1 次不可逆数据写入） / 行为有变 / 前端无既有覆盖，靠 verify_ui TM-5/13/14/15 兜底 / 预估 +250 −200 行`
- **类型**: 加功能
- **目标**: 原油（CLF）从「macro 5 年序列」改为「history 10 年标的」，另类资产组 / 自选 chip /
  点位视图三处同一数据源；10Y 档能真的拉到 2016 年。
- **相关文件**:
  - `src/fetcher.py`（SYMBOLS/ALT_SYMBOLS/MARKETS）、`src/storage.py`（HISTORY_KEYS）
  - `src/reporter.py`（另类资产表/趋势图面板、context `history_30d`）
  - `web/static/app.js`（点位下拉、自选 chip、另类组 `order`、删 macro 分支）
  - `scripts/verify/verify_ui.py`（TM-5a/13/14/15）
  - `tests/`（14 文件夹具 + 计数断言）、`docs/{pitfalls,commands,architecture}.md`、`CONTEXT.md`
- **验证命令**:
  - `venv/Scripts/python.exe -m pytest tests/ -q`
  - `venv/Scripts/python.exe scripts/verify/verify_ui.py`
  - `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py`

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 注册表加 CLF（SYMBOLS / ALT_SYMBOLS / MARKETS.alt / HISTORY_KEYS） | `src/fetcher.py`、`src/storage.py` | 高：连带 `/api/latest`、日报板块、快照、告警集合 | `pytest tests/test_phase6a/6b/7` + `/api/latest` 11 项 |
| 2 | 备份 DB（checkpoint + 复制到仓库外）→ 回填 10 年 | `scripts/backfill_history.py`、`data/marketpulse.db` | 高：不可逆数据写入 | `--dry-run` 计划数 == 实跑写入数（2515）；`clf` 行 2515、2016-11-07 起 |
| 3 | 前端切 history 源，删 macro 原油分支，`order` 钉住组内顺序 | `web/static/app.js` | 中：空态/meta 顺序/自定义组 | 本地起服点三个位置（另类组/自选/点位 10Y） |
| 4 | 闸门对齐 + 新断言 | `scripts/verify/verify_ui.py` | 中：断言写松=假绿 | `verify_ui.py` 全量 |
| 5 | 测试夹具补 CLF、计数断言改派生 | `tests/` | 中：误把「迎合实现」写成断言 | `pytest tests/ -q` |
| 6 | 文档同步（含 pitfalls 重写冲突条目） | `docs/`、`CONTEXT.md` | 低 | `sh scripts/check-gates.sh` |

## 测试 Seam

- **要测的 seam**:
  1. `web/app.py::_build_history_payload`（`/api/history?symbols=CLF&days=2600`）——注册表 → 序列的投影
  2. `src/reporter.py::generate_context` 的 `history_30d`——逐符号手抄清单必须覆盖 `HISTORY_KEYS`
  3. `verify_ui` TM-15——点位视图 10Y 的**起点与点数**（回填的端到端证据）
- **公开接口是什么**: `/api/history`（JSON 形状不变，只是多一个 series）、`/api/latest`（indices 由 10 → 11）、
  context JSON 的 `history_30d.clf` 新键
- **错误与边界**: 该标的在别的市场交易日为 `null`（保持语义）；`MARKETS["alt"]` 变更影响快照 `--market alt`；
  告警必须跳过（`ALT_SYMBOLS`）
- **为什么选这个 seam**（而不是更浅的那个）: 只断言「SYMBOLS 里有 CLF」无法证明数据真的流到图上；
  点位 10Y 的起点/点数是唯一能同时证明「注册表 → DB → API → 前端渲染」全链路的观测点，
  且期望值可由 `/api/history` 响应独立复算（不复用页面钩子）

## 修 bug 时必填

- 不适用（类型 = 加功能；过程中发现并修掉的三个自身 bug 已在 journal「遇到的问题」记录）

## 确认

- [x] 人已审阅计划（用户 2026-11-07「那回填一下，肯定要填啊」= 批准回填与入册）
- [x] 档位声明与实际文件范围一致（22 文件 / +250 −200 行 / 1 次 DB 回填）
- [x] 文件范围合理（注册表 → 存储键 → 报表/context → 前端三消费点 → 闸门 → 夹具 → 文档）
- [x] 没有遗漏测试（`test_context` 新增 history_30d 覆盖全集不变量；TM-15e 覆盖回填端到端）
- [x] 测试 seam 已写入本节（见「## 测试 Seam」）
- [x] 没有引入不必要依赖（全程标准库 + 既有 PyYAML-free 栈）
