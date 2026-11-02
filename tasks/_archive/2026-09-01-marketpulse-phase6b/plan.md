# 实施计划 — MarketPulse 六期 B「A 股大盘监控」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase6b/prd.md`。六期 A 已落地（127 条测试全绿，README 中 113 为过期值）。

## 任务概要

- **目标**（引用 PRD Goal）：在六期 A（美股大盘 GSPC/IXIC + 波动率 VIX/VXN/MOVE）基础上，新增 A 股大盘（上证指数 `000001.SS`、深证成指 `399001.SZ`），日报扩为「美股大盘 + A 股大盘 + 波动率指数」三板块，告警/历史/context 同步扩展。
- **Python 侧职责**：`SYMBOLS` 5→7；A 股趋势复用六期 A 的 streak 机制（`compute_streaks`/`trend_label` 零新增逻辑）；日报/快照渲染拆三板块；A 股休市显示规则；告警阈值 SH/SZ ±4%；history/context 扩展字段；零新依赖，全部走 Yahoo。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，基线 127，更新后 + 新增）
  - `venv/Scripts/python daily_report.py` / `snapshot_report.py`（两入口手动矩阵）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| SYMBOLS 注册表 | `src/fetcher.py` 5 键 GSPC/IXIC/VIX/VXN/MOVE（大盘在前），`STOCK_SYMBOLS = {"GSPC","IXIC"}`；`fetch_all()` 遍历 SYMBOLS、源间 sleep(2s)。**SYMBOLS 扩到 7 后取数自动覆盖** |
| **天然透传点（零改动自动生效）** | `daily_report.py` 的 history record `{k.lower(): values[k] for k in SYMBOLS}`；`compute_streaks`/`_stock_has_data`/`check_breach`/`build_statuses` 均按 `STOCK_SYMBOLS` 成员判定——**SH/SZ 加入 `STOCK_SYMBOLS` 后 streak、趋势标签、大盘告警（恒 WARN/异动）全部自动接线**；`alerter.collect_breaches` 遍历 SYMBOLS + `.get()` 容忍缺失，告警独立（alerts.log 按 symbol 行式去重）天然满足 |
| **必须改的点** | ① `load_history` 投影硬编码 {date,vix,vxn,move,gspc,ixic} 六键 → 补 `sh`/`sz`；② `render_report`/`render_snapshot` 大盘表只有「美股大盘」一块（`STOCK_SYMBOLS` 4 键会挤进同一张表）→ 需拆「美股/A 股」两块；③ `generate_context` 的 `history_30d` 缺 `sh`/`sz` 数组；④ `config.py` DEFAULTS.alert 缺 sh/sz、ENV_MAP 缺两条；⑤ `seed_history.py` 的 `save_last_values` 硬编码 `("vix","vxn","move")` 三键（**六期 A 遗留**：回填后大盘基准丢失，次日大盘涨跌幅显示「—」） |
| **休市显示缺口** | 现状 value None → 状态/渲染一律「获取失败」。PRD 要求 A 股 None → 显示「休市」（简单规则，与取数失败同判）。需在 build_statuses None 分支按 `A_SHARE_SYMBOLS` 特判 + 渲染单元格特判 |
| `build_summary` | 六期 A 已泛化为「全部市场指数数据获取完整，无异常」——**零改动**（PRD 的"文案扩展"在 6A 已完成） |
| `render_trend_chart` | 显式三面板（move/vxn/vix），与 SYMBOLS 解耦——**零改动**，PRD 要求 A 股/美股不入趋势图 |
| 配置 | 五期 `ALERT_THRESHOLDS` 由 `{sym: float(_CFG["alert"][sym.lower()]) for sym in SYMBOLS}` 派生——**DEFAULTS 补 sh/sz 后自动接线**；用户现有 config.json 缺键（连 gspc/ixic 都没有）由白名单深合并补默认 |
| 既有测试 | 127 条。**受影响面**：`test_phase6a.py` 的 `TestSymbolsAndConfig`（`set(SYMBOLS)` 5 键、`STOCK_SYMBOLS == {"GSPC","IXIC"}` 精确断言——**必改**）、`TestReportSections`/`TestSnapshot`/`TestContextExtension`（values 5 键 dict，render/context 直接索引 → **KeyError**）；`test_reporter.py` 的 `sample_data()`/快照 fixtures（5 键）、`first_run` 计数 5；`test_context.py` 全部 `TestGenerateContext`（values 5 键 + history_30d 等长断言链）；`test_analyzer.py::TestHistory::test_append_and_load`（精确六键相等）；`test_alerter.py`/`test_context.py`/`test_phase6a.py` 的 `clean_thresholds` delenv 集合。其余（classify/趋势图/告警渲染）经 `.get()` 或逐键断言天然存活 |
| 文档 | architecture.md（5 指数两板块）、commands.md、pitfalls.md、AGENTS.md、README.md（**已过期**：仍写 3 指数/113 测试/五期能力表，六期 A 未同步）均需更新 |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **仅加 A 股** — `000001.SS`/`399001.SZ` 走 Yahoo，数据已验证（上证 3952/深证 13953）。
2. **零新依赖** — 继续走 Yahoo chart REST。
3. **复用 streak 机制** — A 股同样用连续涨跌天数趋势（`compute_streaks`/`trend_label`/`_stock_has_data` 按 `STOCK_SYMBOLS` 自动覆盖）。
4. **告警独立** — A 股与美股/VIX 分开记录（alerts.log 按 symbol 去重机制已天然满足）。
5. **向下兼容** — 在六期 A 两板块日报上加第三板块，既有内容不变。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **分组常量补丁放 fetcher**：`STOCK_SYMBOLS` 扩为 `{"GSPC","IXIC","SH","SZ"}`（streak/状态/告警分支自动覆盖）；新增 `A_SHARE_SYMBOLS = frozenset({"SH","SZ"})` 用于报告板块拆分与休市判定；SYMBOLS 顺序 GSPC/IXIC/SH/SZ/VIX/VXN/MOVE（context indices、告警收集顺序三板块同序） | 单处定义、与 6A 分组同址；扩展集合而非新建机制 |
| B | **A 股休市规则**：`build_statuses` None 分支按 `A_SHARE_SYMBOLS` 特判 → 状态 `("休市", "A 股休市或数据缺失。")`；渲染 A 股板块收盘价单元格 None → 「休市」（涨跌幅/趋势列沿用 `—`/状态标签）。美股/波动率 None 行为不变（仍「获取失败」） | PRD「值为 None → 显示休市」的简单规则；与取数失败同判是 PRD 明示取舍（无复杂日历） |
| C | **报告三板块**：`## 🌏 美股大盘`（GSPC/IXIC）→ `## 🇨🇳 A 股大盘`（SH/SZ）→ `## 📈 波动率指数`（VIX/VXN/MOVE）；A 股表头/行格式与美股完全一致（`\| 指数 \| 收盘价 \| 涨跌幅 \| 趋势 \|`），标题不含括注（与 6A 落地风格一致）；快照同构拆分 | PRD 报告结构定稿；波动率板块行格式与现版逐字一致，保既有断言 |
| D | **`build_search_keywords` 总数上限 5**（`return words[:5]`）：7 指数最多 7 个异动 → 9 个词，突破四期定稿的「异动日 3-5 个」契约；1-3 个异动时现行为不变 | 维持 context 契约 + 限制 tavily 搜索次数；既有断言（3 异动 → 5 词）不受影响，需补 4+ 异动用例 |
| E | **`seed_history.py` 修复**：`save_last_values` 键集合由硬编码 `("vix","vxn","move")` 改为派生自 SYMBOLS（`[k.lower() for k in SYMBOLS]`） | 六期 A 遗留 bug：回填后大盘（含 A 股）基准丢失，次日涨跌幅错显「—」；本次同文件同函数顺带修复，属 6B 扩展同一行的必要收尾 |
| F | **PRD 勘误**：深证成指 Yahoo ticker 为 `399001.SZ`（深交所后缀 .SZ；PRD 需求段写 `399001.SS` 系笔误，上海才是 .SS）。**实施一律用 `399001.SZ`** | 用错后缀取不到深证成指数据 |

## config.json 结构扩展

```json
{
  "analysis": { "vix": {…}, "move": {…} },          /* 不动 */
  "alert": {
    "vix": 20, "vxn": 20, "move": 15,
    "gspc": 4, "ixic": 4.5,
    "sh": 4, "sz": 4                                  /* 新增 */
  },
  "trend": { "chart_days": 30, "streak_days": 3 },    /* 不动 */
  "history": { "retention_days": 90 }                 /* 不动 */
}
```

| env（最高优先级） | 覆盖路径 | 消费方 |
|---|---|---|
| `ALERT_THRESHOLD_SH` / `ALERT_THRESHOLD_SZ` | `alert.sh` / `alert.sz` | `alert_threshold()`（调用时 + import 快照） |

用户现有 config.json 缺 sh/sz 键 → 白名单深合并补默认 4.0，不破坏（与 gspc/ixic 同机制，实测无需迁移）。

## 文件清单

### 修改

| 文件 | 改动 | 预估 |
|---|---|---|
| `src/fetcher.py` | SYMBOLS 增 SH（label「上证指数」、ticker `000001.SS`）/ SZ（label「深证成指」、ticker `399001.SZ`），置于 IXIC 之后 VIX 之前；`STOCK_SYMBOLS` 扩为 4 键；新增 `A_SHARE_SYMBOLS` | +6 |
| `src/config.py` | DEFAULTS.alert 增 `sh: 4.0, sz: 4.0`；ENV_MAP 增 `ALERT_THRESHOLD_SH`/`ALERT_THRESHOLD_SZ` | +4 |
| `src/analyzer.py` | `load_history` 投影补 `sh`/`sz`（旧记录 → None，向下兼容）；`build_statuses` None 分支 A 股特判「休市」（设计 B）。`compute_streaks`/`trend_label`/`check_breach`/`build_summary` 零改动 | +5 |
| `src/reporter.py` | `render_report` 拆三板块（设计 C，A 股板块含休市单元格）；`render_snapshot` 同构拆分；`generate_context` history_30d 增 `sh`/`sz` 数组 | +12 |
| `seed_history.py` | `save_last_values` 键集合派生自 SYMBOLS（设计 E） | +1 |
| `tests/test_phase6a.py` | `TestSymbolsAndConfig` 集合断言 5→7 / STOCK_SYMBOLS 4 键 + SH/SZ ticker；`test_config_defaults_phase6a` 补 SH/SZ 阈值；`TestReportSections`/`TestSnapshot` values 7 键 + 三板块断言；`TestContextExtension` values 7 键 + sh/sz 数组；`clean_thresholds` 补 SH/SZ | ~-2/+10 |
| `tests/test_reporter.py` | `sample_data()` 补 SH/SZ（values/changes/statuses）；`test_first_run_change_text` 计数 5→7；`TestSnapshot` 两处 values 7 键 | ~-0/+8 |
| `tests/test_context.py` | 各 `TestGenerateContext` values dict 补 SH/SZ；history_30d 等长断言链补 sh/sz；`test_all_sources_failed` 7 键 None | ~-0/+8 |
| `tests/test_analyzer.py` | `TestHistory::test_append_and_load` 期望 dict 补 `"sh": None, "sz": None` | +1 |
| `tests/test_alerter.py` | `clean_thresholds` delenv 集合补 SH/SZ | +2 |
| `docs/architecture.md` | 概览/数据流（7 指数三板块）/模块表/决策表补六期 B 决策（A 股分组、休市规则、三板块渲染、seed_history 修复） | — |
| `docs/commands.md` | 验证矩阵补 A 股场景（7 指数日志、三板块检查、SH ±4% 告警、env 覆盖） | — |
| `docs/pitfalls.md` | 六期 B 小节：`399001.SZ` 非 `.SS`、休市与取数失败同判、A 股休市日 Yahoo 返回最近收盘（streak 平坦日自然续算不打断）、fixtures 需 7 键、seed_history 键派生、search_keywords 上限 5 | — |
| `AGENTS.md` | 项目地图补 7 指数三板块 | — |
| `README.md` | **补齐六期 A + 六期 B**：能力表（六/七期）、7 指数表（含 A 股 ±4%）、三板块报告结构、config/env 表补 sh/sz、测试数 113→更新后实际数、数据流图 | — |

### 新增

| 文件 | 内容 | 预估 |
|---|---|---|
| `tests/test_phase6b.py` | A 股专项测试（见下「测试设计」） | ~+110 |

**不改**：`src/alerter.py`（按 symbol 分块/去重零改动，仅测试 fixture 补 env）、`render_trend_chart`（三面板不动）、`daily_report.py`/`snapshot_report.py`（record 派生自 SYMBOLS 自动 7 键；两入口已传 history 供 streak）、`requirements.txt`、`.env` / `.env.example`、告警文件格式、context 五键顶层结构、Hermes cron 调度。

## 测试设计

### 既有测试更新（只扩 fixture/常量断言，不动既有断言语义）

- `test_phase6a.py`：`test_symbols_order_stock_first` → `list(SYMBOLS)[:4] == ["GSPC","IXIC","SH","SZ"]`、`set(SYMBOLS)` 7 键、`STOCK_SYMBOLS == {"GSPC","IXIC","SH","SZ"}`、`A_SHARE_SYMBOLS == {"SH","SZ"}`、ticker 断言 `000001.SS`/`399001.SZ`；`test_config_defaults_phase6a` 补 `alert_threshold("SH") == 4.0`/`("SZ") == 4.0`；`TestReportSections` values 7 键 + 断言顺序 美股 < A 股 < 波动率；`TestSnapshot` values 7 键；`TestContextExtension` values 7 键 + `history_30d["sh"]`/`["sz"]` 断言。
- `test_reporter.py`：`sample_data()` values/changes/statuses 补 `SH: 3100.0 / SZ: 10000.0`（statuses 补趋势标签，如 `("连涨1日", "大盘连续上涨1日。")`）；`first_run` 断言 5→7；`TestSnapshot.test_render_complete` values 7 键 + A 股 label 断言；`test_render_failed_fetch` 补 SH/SZ None（A 股显示休市）。
- `test_context.py`：各 values dict 补 `"SH": 3100.0, "SZ": 10000.0`；`test_non_breach_day` 等长断言链补 `len(...["sh"]) == len(...["sz"])`；`test_all_sources_failed` 补 `"SH": None, "SZ": None`。
- `test_analyzer.py`：`test_append_and_load` 期望 dict 补 `"sh": None, "sz": None`（其余 History 用例用 `data[0]["vix"]` 逐键断言，天然存活）。
- `test_alerter.py` / `test_context.py` / `test_phase6a.py` / `test_phase6b.py`：`clean_thresholds` delenv 集合补 `SH/SZ`。

### 新增 tests/test_phase6b.py

- **TestSymbolsPhase6b**：SYMBOLS 7 键、顺序 GSPC/IXIC/SH/SZ 在前、ticker `000001.SS`/`399001.SZ`、`STOCK_SYMBOLS` 4 键、`A_SHARE_SYMBOLS == {"SH","SZ"}`（纯常量断言，不联网）。
- **TestA股Streak**：历史 SH 连涨 3 日 + 今日涨 → 4 → `上升趋势`；平坦日（Yahoo 休市日返回昨收，涨跌 0）不打断 streak（去尾 0 语义）；无 SH 历史 → `数据积累中`。
- **Test休市**：`build_statuses({"SH": None, ...})` → `("休市", ...)`；美股 GSPC None → 仍 `获取失败`；`render_report` A 股行含 `| 上证指数 | 休市 | — | 休市 |`。
- **TestA股Breach**：SH +4.1% 触发（level WARN、state 异动、threshold 4.0）、+4.0% 恰好不触发（严格大于）；SZ 阈值独立（+4.1% 触发）；`ALERT_THRESHOLD_SH=5` env → +4.1% 不触发；SH 与 VIX 同触发 → 告警文件两个附录块、alerts.log 两行，午盘 SH 触发后收盘 SH 跳过但 VIX 仍可触发（告警独立）。
- **TestReportThreeSections**：日报 `## 🌏 美股大盘` < `## 🇨🇳 A 股大盘` < `## 📈 波动率指数` 顺序；A 股表 4 列（收盘价/涨跌幅/趋势）；波动率行格式与现版一致；快照三板块。
- **TestHistoryProjectionPhase6b**：旧记录（无 sh 键）→ `load_history` 返回 `sh: None`；append 含 sh/sz 的记录 → 原样读回。
- **TestContextPhase6b**：indices 7 键；`history_30d` 七数组等长（含 sh/sz）。
- **TestSearchKeywordsCap**（设计 D）：4 个异动 → 总词数 5（截断）；3 个异动 → 5（不截断，既有行为）。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | fetcher：SYMBOLS + STOCK_SYMBOLS + A_SHARE_SYMBOLS | src/fetcher.py | 顺序错乱影响输出顺序；ticker 后缀笔误 | `venv/Scripts/python -c "from src.fetcher import SYMBOLS, STOCK_SYMBOLS, A_SHARE_SYMBOLS; print(list(SYMBOLS), STOCK_SYMBOLS, A_SHARE_SYMBOLS)"` |
| 2 | config：DEFAULTS/ENV_MAP 扩展 | src/config.py | 键名与消费方漂移 | `venv/Scripts/python -m pytest tests/test_config.py -v` 全绿 |
| 3 | analyzer：load_history 投影 + build_statuses 休市分支 | src/analyzer.py | 美股 None 行为被误改；旧记录缺键 | `venv/Scripts/python -m pytest tests/test_analyzer.py tests/test_alerter.py -v`（先跑既有，再逐步加新用例） |
| 4 | reporter：三板块拆分 + context 数组 | src/reporter.py | 波动率行格式漂移破坏既有断言 | `venv/Scripts/python -m pytest tests/test_reporter.py tests/test_context.py -v`（先更新 fixtures 再断言语义） |
| 5 | seed_history 键派生修复 | seed_history.py | 无（纯键集合来源替换） | 阅读 diff 确认；不跑联网回填 |
| 6 | 既有测试 fixture 更新 + 新增 test_phase6b.py | tests/ | fixture 漏改致 KeyError | `venv/Scripts/python -m pytest tests/ -v` 全绿（基线 127 更新后 + 新增 ≈ 145+） |
| 7 | 文档同步（architecture/commands/pitfalls/AGENTS/README） | 上述 5 文件 | 文档与实现漂移 | 逐份核对最终代码 |
| 8 | 手动验证矩阵 + 行数预算 + `git diff` 审查 | 全部 | 增量超预算 | 见下方矩阵；源码增量 ≤ ~30 行 |

### 手动验证矩阵（步骤 8，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 正常闭环 | 运行 `daily_report.py` | 日志输出 7 个指数收盘价（含 上证指数/深证成指）；`reports/YYYY-MM-DD.md` 三板块且顺序 美股 < A 股 < 波动率；`history.json` 记录含 sh/sz；`context/YYYY-MM-DD.json` indices 7 键、history_30d 含 sh/sz 数组 |
| A 股告警 | 备份 `data/last_values.json`，模拟 SH 基准 = 当前值/1.042（+4.2%），运行 `daily_report.py` | 生成 `alerts/YYYY-MM-DD-close.md`，含 SH 附录块（level WARN、阈值 ±4.0%、state 异动）；alerts.log 记 SH |
| env 覆盖 | `ALERT_THRESHOLD_SH=5 venv/Scripts/python daily_report.py`（+4.2% 模拟） | SH 不再告警（4.2 < 5） |
| 午盘 A 股告警 | 先跑 `snapshot_report.py` 触发 SH 午盘告警，再跑 `daily_report.py` | 收盘跳过 SH；VIX（若异动）仍可触发——A 股与波动率去重独立 |
| 快照三板块 | 运行 `snapshot_report.py` | 快照含美股/A 股/波动率三板块；不写 history |
| 休市显示 | 单测锁定（模拟值 None → `休市`）；手动运行以真实数据为准 | **说明**：Yahoo 对 A 股休市日返回最近收盘（regularMarketPrice 非 None），手动运行正常显示数值；`None→休市` 路径由 Test休市 覆盖，手动无法干净模拟单源失败 |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（无网络） |
| 恢复 | 恢复 `last_values.json` 原值；清理验证期告警文件 | 生产数据无残留 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| **PRD ticker 笔误**（`399001.SS` vs `399001.SZ`） | 设计 F：深证成指用 `399001.SZ`；TestSymbolsPhase6b ticker 断言锁定 |
| 测试 fixtures 漏 7 键 → render/context 直接索引 KeyError | 设计清单逐一核对 `test_phase6a/test_reporter/test_context` 三处 values dict（共 ~8 处）；步骤 6 全量回归兜底 |
| 休市与取数失败同判（A 股断网也显示休市） | PRD 明示的简单规则取舍（设计 B），写入 pitfalls；美股/波动率 None 行为不变 |
| A 股休市日 streak 语义 | Yahoo 返回最近收盘 → 当日涨跌 0 → 去尾 0 不打断既有 streak（现机制天然正确），TestA股Streak 平坦日用例锁定 |
| 用户 config.json 无 sh/sz 键 | 深合并补默认 4.0，与 gspc/ixic 同机制，实测无需迁移 |
| 7 指数拉取超时 | 6 个源间 sleep(2s)=12s + 7 请求 ≈ 16-19s，PRD 明示可接受；若实测超预算，单处降低源间 sleep 为 1s |
| A 股+美股+波动率同日多告警 | 告警文件按 symbol 分块机制已支持多块；推送合并为 Hermes 侧职责，Python 侧零改动 |
| context 契约变更被 Hermes Prompt 忽略 | Hermes Prompt 同步列入交付清单（外部配置项），AGENTS.md 契约表同步 |
| 旧 history 记录无 sh/sz | load_history 投影 `.get()` → None；趋势显示「数据积累中」直至积累（与 6A 大盘同机制） |
| seed_history 回填后大盘基准丢失（6A 遗留） | 设计 E 同函数修复，键集合派生自 SYMBOLS |
| search_keywords 超 5 词契约 | 设计 D 总数截断 5；TestSearchKeywordsCap 锁定 |
| 行数超预算 | 步骤 8 硬校验：源码增量 ≤ ~30 行（fetcher 6 + config 4 + analyzer 5 + reporter 12 + seed_history 1） |

## 不做什么

- 不加除 A 股外的新指数、不加新依赖、不改 Yahoo 取数机制、不加推送逻辑。
- 不改趋势图（保持 VIX/VXN/MOVE 三面板）、不改告警文件格式/去重机制、不改 context 五键顶层结构。
- 不做 A 股复杂休市日历（PRD 简单规则 None→休市）、不做 A 股恐慌区间分级（大盘恒 WARN，6A 语义延续）。
- 不改 `daily_report.py`/`snapshot_report.py`/`src/alerter.py`（record/告警派生自 SYMBOLS，自动覆盖）。
- 不改 `.env`、`requirements.txt`、Hermes cron 调度。

## 预计影响范围

- **新增文件**：`tests/test_phase6b.py`（~110）。
- **修改文件**：`src/fetcher.py`（+6）、`src/config.py`（+4）、`src/analyzer.py`（+5）、`src/reporter.py`（+12）、`seed_history.py`（+1）、既有 5 个测试文件（fixture/常量断言扩展，既有断言语义不变）、docs 4 份 + README。
- **不受影响**：`src/alerter.py`、`daily_report.py`、`snapshot_report.py`、`render_trend_chart`、`requirements.txt`、`.env`、告警文件/context 顶层契约结构、Hermes cron。
- **交付清单（非仓库文件）**：Hermes Prompt 同步 context 契约（indices 7 键、history_30d 增 sh/sz、日报三板块）。

## 确认

- [ ] 人已审阅计划
- [ ] 设计选择 A（STOCK_SYMBOLS 扩 4 键 + A_SHARE_SYMBOLS）/ B（休市规则）/ C（三板块渲染，波动率行格式不变）/ D（search_keywords 上限 5）/ E（seed_history 键派生修复）/ F（`399001.SZ` 勘误）已确认
- [ ] 既有 127 条测试的实际影响面已如实标注（fixture/常量断言扩展，断言语义不变）
- [ ] config 扩展（sh 4 / sz 4 + env 映射）已确认
- [ ] 休市与取数失败同判的取舍已确认（PRD 简单规则）
- [ ] seed_history 遗留修复（6A 引入）纳入本次范围已确认
- [ ] 没有遗漏测试（符号表/streak 平坦日/休市/A 股告警/三板块渲染/历史投影/context 数组/关键词上限/告警独立全覆盖）
- [ ] 没有引入不必要依赖或额外配置段
