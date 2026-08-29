# 实施计划 — MarketPulse 四期「AI 解读 + 异动归因分析」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase4/prd.md`

## 任务概要

- **目标**（引用 PRD Goal）：在每日日报基础上增加两个 AI 驱动能力——(1) **常规解读**：对当日市场状态生成自然语言解读（200-300 字）；(2) **异动归因**：当任一指数变化超过阈值时，AI 自动检索并分析可能的事件原因。实现"数据 → 洞察 → 原因"完整链路。
- **Python 侧职责**：新增 `generate_context()` 产出 `context/YYYY-MM-DD.json`（indices + history_30d + breach + search_keywords），供 Hermes 全自动读取 → 常规解读 →（异动日）tavily 搜索归因 → 追加到日报并推送。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，原 72 + 新增 context 测试）
  - `venv/Scripts/python daily_report.py`（收盘闭环 + context 生成）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| `src/reporter.py` | 纯渲染层（Markdown 日报/快照 + 趋势图），**无 json/os 导入、无 context 相关代码**；已有 `TREND_DAYS = 30` 可复用为 history_30d 窗口 |
| `src/alerter.py` | 91 行；`run_alert_checks` 逐指数 `check_breach` → 去重过滤 → 写告警文件 → 标记 alerts.log；**异动判断逻辑已在三期实现，本期只需导出纯计算函数** |
| `src/analyzer.py` | 三期 +47 行后含 `check_breach()`（纯函数）、路径常量、`load_history()`（90 天滚动）——`CONTEXT_DIR` 常量与 `build_search_keywords()` 纯函数落位处 |
| `daily_report.py` | 编排入口；末尾顺序为 `run_alert_checks → append_history → save_last_values → return 0`；`values/changes/statuses/last_values` 在函数内均已就绪，可直接传给 `generate_context` |
| `context/` | **不存在**，`generate_context()` 不存在（四期新增，PRD 原稿假设已存在） |
| `.gitignore` | 已排除 `reports/`、`data/`、`alerts/`；**缺 `context/`** |
| 测试 | 72 条全绿（三期 journal 实证：原 49 + 新增 23）；无 test_daily_report.py（仅残留 pyc） |
| 依赖 | requests / matplotlib / pytest；context 生成只需标准库（json/os/pathlib），**零新增依赖** |
| Hermes 侧 | 已有二期收盘 cron（早 8 点）与告警推送链路；tavily 内置插件可用（keyless / TAVILY_API_KEY） |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **方案 Y（结构化上下文）**：新增 `generate_context()`，产出 `context/YYYY-MM-DD.json`（indices + history_30d + breach + search_keywords）。
2. **全自动触发**：收盘 cron 跑完脚本后，Hermes 自动读 `context/` 当日 JSON →（异动日）联网搜索 → 常规解读 + 异动归因 → 追加日报并推送。
3. **频率**：每交易日 Hermes 做常规解读（200-300 字）；**仅异动日**做归因。
4. **搜索工具**：归因用 tavily search（Hermes 侧，keyless 或 TAVILY_API_KEY）。
5. **告警文件对齐现状**：`alerts/YYYY-MM-DD-{type}.md`（noon / close）不变；异动判断以 alerter 导出的 breach 状态为准。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | `alerter.py` 新增纯计算导出 `collect_breaches(values, last_values)`：全量遍历 `check_breach`，**不写告警文件、不改 alerts.log**（幂等）；`run_alert_checks` 重构为复用它（去重/写文件/标记逻辑原样保留） | PRD 要求"breach 从 alerter 导出、复用三期判断、幂等"；单一事实来源，不重复实现判断循环；重构后行为等价，既有 23 条 alerter 测试不变 |
| B | `context/` 的 `breach.indices` 按 PRD 示例字段映射（`name/current/previous/change_pct/threshold/level`），值取自 `check_breach` 原始 dict；`change_pct` 四舍五入 2 位；`level` 沿用 alerter 的 `"WARN"/"ALERT"`（示例小写仅示意，与告警文件 frontmatter 保持一致） | context 是 Hermes 的公共契约，字段名按 PRD 定稿；映射为纯函数（≤10 行）可单测锁定；幂等性由 collect_breaches 保证 |
| C | `search_keywords` 方向感知：异动词为 `"{SYM} surge {date}"`（变化率 ≥0）/ `"{SYM} drop {date}"`（<0）；再加 `"market volatility {date}"`、`"economic data {date}"`，异动日合计 3-5 个（3 指数最多 3 个异动词 + 2 个定向词 = 5）；非异动日 1 个 `"market summary {date}"` | PRD 示例只给了正向 "surge"；方向感知对 tavily 搜索相关性更关键（VIX -22% 时搜 "VIX drop" 才能命中下跌原因），直接服务归因质量。若坚持字面示例可去掉方向判断 |
| D | `generate_context(date, values, changes, statuses, last_values)` 落在 `src/reporter.py`（PRD 指定位置），内部调用 `collect_breaches` + `load_history`（**须在 `append_history` 之后调用**，history_30d 才含当日）；临时文件 + `os.replace` 原子写 | PRD 文件清单指定 reporter.py；history_30d 含当日对 Hermes 趋势参考更有用；原子写避免 Hermes 读到半截 JSON |
| E | `generate_context` 不在内部吞异常，由 `daily_report.py` 末尾调用方 try/except 兜底（沿用决策 H 模式） | 失败路径可见、可测；context 生成失败不影响日报主流程（PRD 容错要求） |
| F | context 仅收盘入口生成，`snapshot_report.py` 不动 | PRD 工作流图仅 daily_report.py → generate_context；Hermes 仅收盘后读取 |
| G | Hermes 侧 Prompt / 归因配置为**交付配置项（非仓库文件）**，实施完成后与用户确认落地；Python 侧不引入任何 LLM/搜索 SDK | PRD 明确约束 |

## 文件清单

### 新增

| 文件 | 内容 | 预估行数 |
|---|---|---|
| `tests/test_context.py` | `build_search_keywords` 纯函数（0/1/2/3 异动、方向词、计数 3-5）+ `generate_context` 端到端（tmp 目录，不联网）：非异动/异动/全源失败/幂等（不产告警文件、alerts.log 不动）/JSON 结构断言 | ~80 |

### 修改

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | 新增路径常量 `CONTEXT_DIR = BASE_DIR / "context"`；新增纯函数 `build_search_keywords(date, breaches) -> list[str]`（设计 C） | ~14 |
| `src/alerter.py` | 新增 `collect_breaches(values, last_values) -> list[dict]`（设计 A）；`run_alert_checks` 重构：pending 计算改用 collect_breaches，去重/写文件/标记逻辑原样 | ~+10 / -3 |
| `src/reporter.py` | 新增 `generate_context(date, values, changes, statuses, last_values) -> Path`（设计 D）+ 私有 `_breach_item(alert)` 字段映射（设计 B）；导入 json/os、`CONTEXT_DIR`/`load_history`/`build_search_keywords`/`collect_breaches` | ~45 |
| `daily_report.py` | 末尾（`save_last_values` 之后、`return 0` 之前）接入 `generate_context`，try/except 兜底并记日志（设计 E） | +7 |
| `.gitignore` | 运行时生成区新增 `context/` 一行 | +1 |
| `docs/architecture.md` | 模块表 reporter 职责补 context；数据流加 generate_context 分支；关键决策补四期决策 A-G；行数约束更新（四期后四模块+两入口约 810 行） | — |
| `docs/commands.md` | 验证要点补 context 3 项（异动模拟检查 breach、正常日 triggered=false、失败/断网容错） | — |
| `docs/pitfalls.md` | 追加：CONTEXT_DIR 导入绑定补丁位置、context 原子写、generate_context 须在 append_history 后、search_keywords 方向词语义、breach 字段契约为 Hermes Prompt 的输入 | — |
| `AGENTS.md` | 项目地图补 `context/`、`generate_context()`、`collect_breaches` | — |

**不改**：`src/fetcher.py`、`src/snapshot_report.py`（设计 F）、`requirements.txt`（零新依赖）、`.env`、`.env.example`（TAVILY_API_KEY 为 Hermes 侧配置，不属 Python 进程）、`README.md`（运行方式不变）、reporter 既有渲染函数、analyzer 既有函数。

### Hermes 侧配置（交付项，非仓库文件，实施完成后需确认落地）

1. **market-analyst Prompt 模板**（按 PRD Requirements #3）：任务一常规解读（每日，200-300 字，输入 context 的 indices/history_30d）；任务二异动归因（仅 `breach.triggered=true`）：异动事实 → tavily 搜索当日新闻/经济事件/联储/地缘（关键词用 `search_keywords`）→ 相关性判断 → 归因结论 1-2 条 → 后续关注；归因 300-400 字；末尾固定标注"*本归因由 AI 基于公开信息生成，仅供参考，不构成投资建议*"。
2. **收盘 cron 接线**（早 8 点，二期已建）：`daily_report.py` 跑完后读 `context/YYYY-MM-DD.json` → 常规解读 → 异动日 tavily 搜索归因 → 追加到 `reports/YYYY-MM-DD.md`（`## 🤖 AI 市场解读` 与 `## 🔍 异动归因分析` 章节，位于页脚前）→ 推送 QQ。**AI 归因总时长 ≤ 30 秒**，超时跳过、日报先推送，归因章节标注"异动归因分析暂时无法获取，请稍后重试"。
3. **容错**：context 读取失败/JSON 解析失败 → 跳过 AI 解读仍推送日报；tavily 无结果/超时 → 标注重试提示。
4. **可选**：`TAVILY_API_KEY`（提升额度，keyless 亦可）。

## context/YYYY-MM-DD.json 契约（字段表）

```json
{
  "date": "2026-08-29",
  "indices": {
    "VIX": { "value": 14.43, "change_pct": 0.0, "status": "平静" },
    "VXN": { "value": 19.92, "change_pct": 1.2, "status": "平静" },
    "MOVE": { "value": 70.97, "change_pct": -0.5, "status": "平静" }
  },
  "history_30d": {
    "dates": ["2026-07-30", "..."],
    "vix": [14.0, null, "..."],
    "vxn": ["..."],
    "move": ["..."]
  },
  "breach": {
    "triggered": true,
    "indices": [
      { "name": "VIX", "current": 26.4, "previous": 22.3,
        "change_pct": 18.39, "threshold": 20.0, "level": "WARN" }
    ]
  },
  "search_keywords": ["VIX surge 2026-08-29", "market volatility 2026-08-29", "economic data 2026-08-29"]
}
```

| 字段 | 来源 | 说明 |
|---|---|---|
| `indices.<SYM>.value` | `values[sym]` | 取数失败为 `null` |
| `indices.<SYM>.change_pct` | `changes[sym]` | 首跑/无基准为 `null` |
| `indices.<SYM>.status` | `statuses[sym][0]` | 平静/警惕/恐慌/获取失败 |
| `history_30d` | `load_history()` 最近 30 条（含当日，因在 append_history 后调用） | 三数组与 dates 等长；缺数据为 `null` |
| `breach.triggered` | `bool(collect_breaches(...))` | 任一指数超阈值即 true；**纯计算，不依赖 alerts.log 去重**（午盘已告警的指数，收盘 context 仍标记异动，归因针对市场异动本身） |
| `breach.indices` | `_breach_item(alert)` 映射 | 字段名按 PRD 示例；level 沿用 WARN/ALERT 大写 |
| `search_keywords` | `build_search_keywords(date, breaches)` | 异动日 3-5 个（设计 C）；常规日 1 个 |

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | analyzer.py 新增 `CONTEXT_DIR` + `build_search_keywords()` | src/analyzer.py | 关键词计数/方向边界 | `venv/Scripts/python -c "from src.analyzer import build_search_keywords, CONTEXT_DIR"` + 步骤 5 测试 |
| 2 | alerter.py 新增 `collect_breaches()`，`run_alert_checks` 重构复用 | src/alerter.py | 重构引入行为偏差（去重/日志/顺序） | `venv/Scripts/python -c "from src.alerter import collect_breaches"` + 既有 test_alerter.py 23 条全绿 |
| 3 | reporter.py 新增 `_breach_item` + `generate_context()`（原子写） | src/reporter.py | 循环导入（alerter 不导 reporter，无环）；字段映射漂移 | `venv/Scripts/python -c "from src.reporter import generate_context"` + 步骤 5 测试 |
| 4 | daily_report.py 末尾接入 `generate_context`（try/except） | daily_report.py | context 异常中断主流程 | `venv/Scripts/python daily_report.py` 退出码 0，生成 context 文件 |
| 5 | 新建 `tests/test_context.py` + 全量回归 | tests/test_context.py | env 阈值变量泄漏、路径常量绑定 | `venv/Scripts/python -m pytest tests/ -v` 全绿（原 72 + 新增） |
| 6 | `.gitignore` + 文档同步（architecture/commands/pitfalls/AGENTS.md） | 上述 4 文件 + .gitignore | 文档与实现漂移 | 逐份核对与最终代码一致 |
| 7 | 手动验证矩阵（见下） | data/last_values.json（临时改，事后恢复） | Yahoo 限流致取数失败（属设计行为） | 见下方矩阵 |
| 8 | 行数预算 + git diff 审查 | 全部 | 增量超预算 | `wc -l` 源码增量 ≤ ~80；`git diff` 核对范围 |

### 手动验证矩阵（步骤 7，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 异动日 | 备份 `data/last_values.json`，编辑使 VIX 基准 ≈ 当前值/1.22（模拟 +22%），运行 `daily_report.py` | `context/YYYY-MM-DD.json` 中 `breach.triggered=true`、indices 含 VIX 明细（current/previous/change_pct/threshold/level）、`search_keywords` 3-5 个含 "VIX surge/drop {date}" |
| 常规日 | 恢复原值后运行 `daily_report.py` | `breach.triggered=false`、`breach.indices=[]`、`search_keywords == ["market summary {date}"]` |
| 断网/全源失败 | 断网或取数全失败时运行 | 日报正常生成、退出码 0；context 生成失败仅记日志（或生成 breach=false 的 context），不中断主流程 |
| 幂等 | 连续两次运行同一场景 | 当日 context 文件被覆盖、JSON 有效；`alerts/` 无新增文件、`data/alerts.log` 前后一致（collect_breaches 纯计算不触碰） |
| JSON 校验 | `venv/Scripts/python -c "import json; d=json.load(open('context/YYYY-MM-DD.json', encoding='utf-8')); print(d['date'], d['breach']['triggered'])"` | 解析成功、字段齐全 |
| 恢复 | 验证完成后恢复 `data/last_values.json` 原值，清理验证期临时文件 | 缓存回归真实值 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| Hermes 读到半截/损坏 JSON | 设计 D：临时文件 + `os.replace` 原子写；JSON 契约由单测断言锁定 |
| `run_alert_checks` 重构破坏三期行为 | 重构仅替换 pending 计算循环为 `collect_breaches`（等价遍历），去重过滤/写文件/标记/日志顺序原样；既有 23 条 alerter 测试 + 手动矩阵场景 2/3 回归锁定 |
| 字段契约漂移（Hermes Prompt 按字段表编写） | 契约表（上文）+ `_breach_item` 单测锁定字段名/精度；Hermes Prompt 作为交付项按此表编写 |
| context 生成失败连累日报 | 设计 E：调用方 try/except，仅记日志，退出码恒 0 |
| 关键词方向与 PRD 示例字面不一致 | 设计 C 已标注：方向感知为推荐项，需确认；若坚持 "surge" 字面，单函数内一处改动 |
| 常规日关键词仅 1 个（3-5 规则只约束异动日） | 常规日不做搜索（决策 3 频率），关键词仅供完整性；PRD 原文"非异动日生成常规关键词"示例即单数 |
| 测试路径常量绑定坑 | CONTEXT_DIR 由 reporter 导入时绑定，测试须 `monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")`；`load_history` 同理打补丁；env 阈值用 `monkeypatch.delenv` 隔离——写入 pitfalls |
| 行数超预算 | 四期源码增量目标 ≤ ~80 行（analyzer 14 + alerter 10 + reporter 45 + 入口 7），步骤 8 用 wc -l 硬校验；architecture.md 行数约束同步更新（三期 750 上限 → 四期后约 810） |
| Yahoo 限流致取数失败 | 数据缺失 → indices value=null、breach=false，context 照常生成；手动验证用改缓存模拟，不依赖网络 |
| AI 归因不准确（相关性≠因果性） | PRD Prompt 强调"基于公开信息推测" + 免责声明；搜索关键词限定日期 + 定向词降低噪音 |
| 搜索费用/限速 | 仅异动日触发搜索（月预计 <5 次），keyless 可用 |

## 不做什么

- 不实现解读/归因的生成与推送（Hermes 侧 Prompt + tavily 为交付配置项）。
- 不引入任何 LLM/搜索 SDK、不新增 Python 依赖。
- 不修改 `snapshot_report.py`（context 仅收盘生成）。
- 不修改告警去重/文件/阈值逻辑（`run_alert_checks` 仅内部复用 collect_breaches，行为不变）。
- 不修改 `.env`/`.env.example`（TAVILY_API_KEY 属 Hermes 侧）。
- 不改既有渲染函数、analyzer 既有函数、报告模板、classify 阈值。
- context 文件不追加除 PRD 五键外的字段（保持契约最小）。

## 预计影响范围

- **新增文件**：`tests/test_context.py`（~80 行）；运行时生成 `context/`（gitignore 排除）。
- **修改文件**：`src/reporter.py`（+~45）、`src/analyzer.py`（+~14）、`src/alerter.py`（+~10 / -3 重构）、`daily_report.py`（+7）、`.gitignore`（+1）、`docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`AGENTS.md`。
- **不受影响**：`src/fetcher.py`、`snapshot_report.py`、`requirements.txt`、`.env`、`.env.example`、`README.md`、既有 72 条测试（重构后全绿）、Hermes 二期/三期 cron（四期在其上追加 context 读取与解读推送）。

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理
- [ ] 设计选择 A（collect_breaches 纯计算导出 + run_alert_checks 复用重构）/ B（breach 字段映射按 PRD 示例）/ C（search_keywords 方向感知）/ D（reporter.py 落位 + append_history 后调用 + 原子写）/ E（调用方兜底）/ F（仅收盘生成）/ G（Hermes Prompt 为交付项）已确认
- [ ] context JSON 契约表（indices/history_30d/breach/search_keywords）已确认，Hermes Prompt 按此编写
- [ ] 没有遗漏测试（build_search_keywords 边界 + generate_context 异动/常规/全源失败/幂等全覆盖，联网场景手动验证）
- [ ] 没有引入不必要依赖
