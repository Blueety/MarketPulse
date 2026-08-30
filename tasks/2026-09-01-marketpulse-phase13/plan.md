# MarketPulse 十三期：回测验证 — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`src/analyzer.py`（load_history 90 行滚动、check_breach 严格大于语义、alert_threshold env 复核、REPORTS_DIR 常量）、`src/config.py`（阈值默认 20/20/15/4/4.5/4/4）、`data/history.json`（实测 90 行，键 = date + 小写符号 gspc/ixic/sh/sz/cyb/vix/vxn/move/gld/btc）、`daily_report.py`（告警检查位于 save_last_values 之前）。

## 目标

- 独立回测脚本 `scripts/backtest.py`：基于 `data/history.json` 历史收盘价，按生产同一套告警语义（`check_breach`：严格大于阈值、env/config 实时阈值、缺口断开）回放触发事件。
- 输出每标的：告警次数 / 年化频率 / WARN-ALERT 分布 / 触发后 1/3/5/10 交易日平均涨跌幅 / 胜率 / 有效触发率。
- 产出 `reports/backtest_report.md` + 终端摘要；只读历史数据（仅写报告文件）；数据不足 30 个有效交易日时优雅退出；全程 <5 秒（纯 Python 计算，90 行 × 7 标的，不联网）。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `scripts/backtest.py` | 新增（新建 `scripts/` 目录，PRD 定稿路径）：独立回测脚本 |
| `tests/test_backtest.py` | 新增（约 8 条）：触发检测 / 前向收益 / 胜率 / 有效触发率 / 门槛退出纯逻辑 |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步 |

不改：`daily_report.py`、`snapshot_report.py`、`src/*`、`config.json`、`requirements.txt`（零新依赖）、`data/`、`alerts/`、`context/`（回测只读，绝不写）。

## 核心设计

### 1. 脚本骨架：独立入口，复用 analyzer 单一事实来源

```python
#!/usr/bin/env python
"""独立回测脚本：验证告警阈值有效性。只读 history，仅写 reports/backtest_report.md。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 项目根入 path，支持 from src.analyzer import ...

import argparse
from src.analyzer import REPORTS_DIR, check_breach, load_history
```

- `--history PATH` 可选参数：默认 `analyzer.HISTORY_FILE`；用于无污染验证「数据不足」路径（临时小文件，不动真实数据）。
- 只导入 `load_history` / `check_breach` / `alert_threshold` / `REPORTS_DIR` 等只读能力；**绝不 import** `append_history` / `save_last_values` / `generate_context`（回测零副作用）。
- 回测标的 = PRD 表 7 个：`["VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ"]`（常量 `BACKTEST_SYMBOLS`，模块级便于测试覆盖）。CYB 有阈值但 PRD 表未列，默认不纳入（见决策 A）。

### 2. 数据准备与触发检测（复用生产语义）

- `history = load_history()` 后按 `date` 升序排序（load_history 不保证有序，append 顺序通常有序但防御排序）。
- 对每标的取小写键值列（六期B 纪律：history 存 `gspc` 等小写键），相邻两行 `(prev, cur)` 均为有效数值时调 `check_breach(sym, cur, prev)` —— **与生产完全同一触发函数**：严格大于阈值（等于不触发）、阈值经 `alert_threshold(sym)` 实时读 env/config、缺口断开链。返回 dict 即触发事件（含 `change` / `threshold` / `level`）。
- 触发事件记录：`{date, symbol, change, threshold, level, price}`，连同该日在前向窗口中的索引位，供后效统计。

### 3. 指标定义（纯函数，可单测）

- **有效交易日**：至少一个回测标的有相邻可计算变化的行数。全局门槛：< 30 → 终端输出「历史有效交易日不足 30 天（N），跳过回测」+ 退出码 0，不写报告（PRD「数据不足 30 天时优雅退出」）。
- **单标的有效点**：该标的有相邻可计算变化的行数；< 30 → 该标的统计段标注「样本不足」，仅输出有效点数与告警次数，不出后效/胜率/有效触发率（避免小样本误导）。
- **告警次数**：触发事件总数；**年化频率** = 次数 / 该标的有效数据跨度天数 × 365（跨度 = 首个有效点日期到末个有效点日期）。
- **WARN/ALERT 分布**：按 `level` 计数（顺带免费获得，`check_breach` 已给出）。
- **后效（1/3/5/10 交易日）**：对每个触发 t，前向收益 = `(p[t+h] - p[t]) / p[t] * 100`，要求 t+h 存在有效值；缺口不阻断（点对点收益，与触发检测的相邻链语义分开）。统计：平均前向收益、样本数 n（窗口不足的触发不计入该窗口，n 透明展示）。
- **胜率（每窗口）**：前向收益与告警当日 `change` 同号（方向延续）的触发占比。
- **有效触发率**：触发后 5 个交易日内出现任意单日 |变化率| ≥ 1% 的触发占比 —— 衡量「告警是否捕捉到真实持续波动」（阈值合理性核心指标；1% 为可配置常量 `MEANINGFUL_MOVE_PCT`，见决策 C）。

### 4. 报告与终端摘要

- `reports/backtest_report.md`（`REPORTS_DIR.mkdir(parents=True, exist_ok=True)` 后直接写，不引入 reporter 依赖）：
  - 元信息：运行日期、数据窗口（首末日期）、有效交易日数、各标的实际阈值表（`alert_threshold(sym)` 实时值，注明「阈值来自 config/env 实时配置」）。
  - 每标的章节：阈值、有效点数、告警次数、年化频率、WARN/ALERT 分布、有效触发率、1/3/5/10 日平均后效表（收益 / 胜率 / n）。
  - 总览对比表（7 行：标的 × 告警次数 × 年化 × 有效触发率 × 各窗口平均后效）。
  - 方法说明块：触发语义 = 生产 `check_breach`（严格大于）、数据源 = history.json、缺口处理、样本门槛。
- 终端摘要：每标的一行（告警次数 / 年化 / 胜率@1日 / 有效触发率）+ 总耗时 + 报告路径。

## 实施步骤

1. **scripts/backtest.py 骨架**：sys.path、`--history` 参数、load_history + 排序、`BACKTEST_SYMBOLS` 常量。验证：`venv/Scripts/python -m pytest tests/ -v` 不回归（新文件不触碰既有模块）。
2. **纯函数**：`collect_triggers(history, symbols)`（触发事件列表，内部调 check_breach）、`forward_stats(triggers, history, symbols, horizons)`（每窗口 平均收益/胜率/n）、`effective_trigger_rate(triggers, history)`、`annualized_frequency(triggers, history, symbol)`。验证：`venv/Scripts/python -m pytest tests/test_backtest.py -v` 绿。
3. **报告渲染 + 终端摘要**：`render_report(...) -> str` 与 `print_summary(...)`。验证：`venv/Scripts/python scripts/backtest.py` 实际跑通，检查报告与摘要。
4. **tests/test_backtest.py 新增**（约 8 条，见下）。验证：全绿。
5. **全量回归**：`venv/Scripts/python -m pytest tests/ -v`（既有 231 条不回归 + 新增全绿）。
6. **实跑 + 数据不足验证**：正常实跑 + `--history` 指向临时 20 行小文件验证优雅退出（退出码 0、无报告生成、不写任何数据文件）。
7. **文档同步**：architecture.md（模块表加 scripts/backtest.py 行）、commands.md（回测运行命令）、pitfalls.md（回测纪律：复用 check_breach 不重写阈值逻辑、历史键小写、缺口断开、只读边界、阈值实时性）、AGENTS.md（project map 补 scripts/ 说明）。

## 新增测试 tests/test_backtest.py（约 8 条）

构造小型 history 夹具（日期升序、含缺口行），验证：

1. `collect_triggers` 复用 check_breach 语义：恰好等于阈值不触发、严格大于触发（构造 ±阈值边界）；
2. 缺口（None）断开：缺口两侧不产生跨缺口触发；
3. 触发事件字段齐全（date/symbol/change/threshold/level/price）；
4. `forward_stats`：1/3/5/10 窗口平均收益正确（手算期望），窗口不足的触发不计入（n 正确）；
5. 胜率：方向延续占比正确（构造同号/反号混合）；
6. `effective_trigger_rate`：构造含/不含 ≥1% 单日波动的场景；
7. `annualized_frequency` 正确；
8. 有效交易日 <30 → 主函数优雅退出路径（monkeypatch `--history` 小文件，断言退出码 0 且不写报告）。

## 验证命令

1. `venv/Scripts/python -m pytest tests/test_backtest.py -v` — 新增全绿。
2. `venv/Scripts/python -m pytest tests/ -v` — 既有全量不回归 + 新增。
3. `venv/Scripts/python scripts/backtest.py` — 终端摘要输出、`reports/backtest_report.md` 生成、总耗时 <5s、退出码 0。
4. 数据不足：`venv/Scripts/python scripts/backtest.py --history <临时20行.json>` — 优雅退出（退出码 0、提示信息、无报告文件、data/ 无任何写入）。

## 待确认决策

- **A（默认采纳）**：回测标的 = PRD 表 7 个（VIX/VXN/MOVE/GSPC/IXIC/SH/SZ），CYB 不纳入（PRD 表未列，尽管有阈值 5.0）。备选：纳入 CYB（`BACKTEST_SYMBOLS` 加一行即可）。
- **B（默认采纳）**：阈值取 `alert_threshold(sym)` 实时值（config.json/env 当前生效阈值），非 PRD 固定值——回测目的正是验证当前阈值有效性；报告注明实际使用值。备选：硬编码 PRD 表，与用户定制配置脱钩。
- **C（默认采纳）**：有效触发率 = 触发后 5 个交易日内出现任意单日 |变化率| ≥ 1%（`MEANINGFUL_MOVE_PCT = 1.0`）的触发占比。备选：≥0.5% 或与标的阈值挂钩（如 ≥ 阈值的一半）——挂钩方案对 VIX 20% 阈值过严，固定 1% 更稳健。
- **D（默认采纳）**：胜率 = 前向收益与告警当日变化同号占比（方向延续性，回答「大波动后延续还是反转」）。备选：前向收益为正占比（不区分方向）。
- **E（默认采纳）**：样本门槛 = 全局有效交易日 ≥30（不足优雅退出）+ 单标的有效点 ≥30（不足仅输出计数与「样本不足」标注）。

## 风险与边界

- **小样本误导**：90 天窗口内单标的触发次数预计个位数（VIX ±20% 属极端事件），后效均值为小样本统计——报告必须透明展示 n 与数据窗口，脚本不输出任何「结论性」评语（只给事实数字，阈值合理与否由用户判断）。
- **触发语义漂移**：必须复用 `check_breach` 而非重写比较逻辑（严格大于、level、缺口处理），否则回测与生产行为脱节——纯函数测试锁定。
- **阈值实时性**：`alert_threshold` 读 env/config 快照；回测报告注明实际阈值与运行时刻，避免「配置已改、报告仍是旧值」的误解。
- **只读边界**：脚本只写 `reports/backtest_report.md`；`--history` 参数仅用于指定只读输入，不提供写回能力。
- **5 秒约束**：纯 Python 90 行 × 7 标的，预计 <0.5s；不联网、不启动 matplotlib，无超时风险。
- **history 排序**：load_history 返回存储顺序，回测前按 date 排序，避免乱序造成伪触发。

## PRD Done When 对照

- scripts/backtest.py 能读取 history.json → 核心设计 1/2 + 步骤 1
- 计算每个指数告警后平均表现 → 核心设计 3（1/3/5/10 日平均后效）+ 步骤 2
- 输出总告警次数/年化/胜率/有效触发率 → 核心设计 3/4 + 步骤 2-3
- 生成 backtest_report.md → 核心设计 4 + 步骤 3
- 数据不足 30 天时优雅退出 → 核心设计 3（全局门槛）+ 步骤 6
