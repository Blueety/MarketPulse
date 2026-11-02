# 动态告警阈值（Phase 27）— 架构方案

> 架构师只读分析产出：目标、设计决策、涉及文件、实施步骤、验证命令、风险与决策记录。
> 分析基线：`src/config.py`（DEFAULTS["alert"] + ENV_MAP 白名单 + _merge_valid 叶值校验）、`src/analyzer.py`（L42 ALERT_THRESHOLDS / L120 alert_threshold / L125 check_breach）、`src/alerter.py`（L63 collect_breaches / L82 run_alert_checks）、`src/reporter.py`（L943 generate_context）、`daily_report.py`（L122 load_history、L200-209 append→告警顺序）、`snapshot_report.py`（L43/50）、`scripts/backtest.py`（L84 collect_triggers）、`tests/`（test_analyzer/test_alerter/test_context/test_phase6b/test_phase7/test_backtest 对阈值语义与告警 dict 的既有锁定）、`data/history.json`（键 = date + 小写符号，含当日行仅在 append 之后）。

## 1. 任务目标

引用 `tasks/2026-09-02-dynamic-threshold/prd.md` Goal：将固定阈值改为**基于历史波动率的动态阈值**，使告警灵敏度自适应市场环境。

验收要点（PRD 需求 1-6）：
1. 滚动窗口：过去 N 个交易日日收益率标准差（建议 20-30 天）
2. 阈值 = rolling_mean + k × rolling_std（k 默认 2.0）
3. 数据来源：复用 `data/history.json`（已有 90 天滚动）
4. 配置兼容：`config.json` 保留原 `alert` 阈值为 fallback；新增 `alert.dynamic`（默认 true）、`alert.lookback_days`（默认 20）、`alert.k_factor`（默认 2.0）；历史不足 lookback_days 时回退固定阈值
5. 告警 dict 增加动态阈值标注字段
6. 向后兼容：现有测试全绿、API 不变

## 2. 结论先行：核心设计决策

### 决策 D1：动态阈值 = 各标的自有日收益率分布的 trailing 窗口估计（推荐）

**机制**：`alert.dynamic=true` 且该标的最近连续历史样本充足时，按标的分列计算：

```
窗口行 = history（不含候选当日）升序，从最新往回取连续有效收盘，
        遇该列非数值行（None/缺口）即停
收益序列 = 窗口内相邻行 (p[i]-p[i-1])/p[i-1]×100，取最新 lookback_days 个
mean = 序列均值；std = statistics.stdev（样本标准差 ddof=1）
动态阈值 = mean + k_factor × std
触发条件不变：|change| > 生效阈值（严格大于，等于不触发）
```

生效阈值优先级：**动态（启用且样本充足）> 固定阈值 `alert_threshold(symbol)`（env > config > 默认）**。样本不足 / 关闭 / 零方差 / 计算值 ≤0 → 一律回退固定阈值，不崩溃。

**替代方案对比**：

| 方案 | 说明 | 否决原因 |
|---|---|---|
| A. 每标的滚动窗口（推荐） | PRD 字面：各指数自己的收益分布 | 唯一符合 PRD 需求 1/2 语义 |
| B. 用 VIX 状态缩放固定阈值 | 波动率指数做全局调节器 | 跨市场耦合（A 股阈值被美股恐慌放缩）、需重新校准 8 个标的、非 PRD 语义 |
| C. EWM 指数加权 std | 对近期波动更敏感 | 需新增 decay 参数，PRD 定稿为等权窗口，拒绝额外配置面 |

**公式落地（F1 vs F2）**：PRD 需求 2 字面 = `threshold = mean + k×std`，配合既有 `abs(change) > threshold` 判定 → **F1（推荐）**：单值阈值、正负号对称、渲染 `±X%` 与 context `threshold` 字段零改动。F2（双边：`change > mean+k×std` 或 `< mean-k×std`，阈值按方向取界）数学上更严谨，但产出方向不对称阈值、破坏 `±` 渲染语义、实现与测试成本更高。日收益率均值 ≈0（远小于 k×std），F1 与 F2 数值差异可忽略。**选 F1**。

### 决策 D2：动态窗口必须「排除候选当日」，且两个告警通道用同一份行集（关键）

`check_breach` 是纯函数、无 I/O、无日期参数——**动态窗口由调用方以 `history` 参数传入，函数只认"传进来的行都早于候选日"**。逐通道事实（已核实源码时序）：

- `daily_report.py`：L122 `history = load_history()` 为内存快照；L200-205 **先 `append_history`**，L206-209 才 `run_alert_checks`——文件已含当日，但**内存 `history` 变量不含当日** → 直接传内存变量即天然排除当日 ✓
- `generate_context`（L943 内部 `load_history()`）：调用晚于 append，文件**含当日行** → 必须 `[r for r in rows if r.get("date") != date]` 剔除后再传给 `collect_breaches`，否则当日自身涨跌混入分布（大异动日 std 被自身抬高 → 自我削弱触发），且与告警文件通道判定不一致
- `snapshot_report.py`：从不 append → 文件恒无当日 → 直接传即可
- `scripts/backtest.py`：回放第 i 对 (rows[i-1], rows[i]) 时传 `rows[:i]`（排除候选行 i，窗口含到 prev 行为止的收益，等价于生产"昨日收益是分布最新成员"）

**两通道一致性是既有幂等契约**（test_context `test_idempotent_no_alert_side_effects`、commands.md「连续两次运行同一场景」）的前提——本设计逐通道满足，见决策 D4 接线。

### 决策 D3：API 兼容 = 全部新参数带默认值、新键只增不改

```python
# analyzer.py —— 新增纯函数
def dynamic_alert_threshold(symbol: str, history: list[dict] | None,
                            lookback_days: int | None = None,
                            k_factor: float | None = None) -> float | None:
    """计算动态阈值（%）。样本不足/零方差/缺口/计算值<=0 → None（调用方回退固定）。纯计算、可单测。"""
    # lookback/k 缺省用模块常量 ALERT_LOOKBACK_DAYS / ALERT_K_FACTOR

def check_breach(symbol, current, last, history: list[dict] | None = None) -> dict | None:
    """…新增可选 history：非空且启用动态且动态值可算 → threshold=动态值、threshold_mode="dynamic"；
    否则 threshold=alert_threshold(symbol)、threshold_mode="fixed"。
    告警 dict 新增两键（PRD 需求 5）：
      "threshold_mode": "dynamic" | "fixed"      # 显式标注
      "dynamic_threshold": float | None          # 本次动态计算值；fixed 模式为 None
    既有键（threshold 存生效值）与两个返回分支（STOCK_SYMBOLS / 波动率）的 level/state/suggestion 逻辑原样。"""
```

```python
# alerter.py —— 参数透传
def collect_breaches(values, last_values, history: list[dict] | None = None) -> list[dict]: …
def run_alert_checks(date, values, last_values, alert_type, report_path, history=None) -> list[dict]: …
```

不传 `history`（既有全部测试路径）→ 恒回退固定阈值，**存量 382+ 条测试行为零漂移**。

### 决策 D4：消费点接线一览

| 调用方 | 现状 | 改动 |
|---|---|---|
| `daily_report.py` L197 | `run_alert_checks(date, values, last_values, "close", report_path)` | 加第 6 参 `history`（L122 内存变量，天然不含当日） |
| `snapshot_report.py` | L43 `load_history()` 内联即弃 | 提升为变量复用，传入 `run_alert_checks`（文件恒无当日） |
| `reporter.generate_context` | L943 `load_history()` + L944 `collect_breaches(values, last_values)` | 单次 load；`rows_pre = [r for r in rows if r.get("date") != date]` 传入 collect_breaches（当日剔除）；`history_30d` 仍用含当日行（既有语义不动） |
| `scripts/backtest.py` `collect_triggers` | L84 `check_breach(sym, cur, prev)` | 改传 `history[:i]`；触发记录增 `threshold_mode`；报告阈值表语义更新（见 §4） |

### 决策 D5：配置（config.py）

```python
DEFAULTS["alert"] 追加：{"dynamic": True, "lookback_days": 20, "k_factor": 2.0}
# analyzer 模块常量（import 时快照，沿用 ALERT_THRESHOLDS/HISTORY_MAX 范式）：
ALERT_DYNAMIC / ALERT_LOOKBACK_DAYS / ALERT_K_FACTOR
```

- **_merge_valid 需扩展 bool 叶值分支**：现校验 `_valid_number` 显式排除 bool（JSON `true` 被当 1 的坑），导致 `alert.dynamic=false` 会被当非法回退默认、**用户无法在 config.json 关动态**。新增：`isinstance(base_val, bool)` → 接受 `isinstance(raw_val, bool)`，否则记日志回退 base。对既有键零影响（现有 DEFAULTS 无 bool 叶值）。
- **不加 ENV_MAP 新键**（PRD 未要求；避免 env 面膨胀）。`ALERT_THRESHOLD_<SYM>` 语义保留为**回退阈值覆盖**——文档需写明新优先级（决策 D1）。SZ 无 env 键的历史缺口（十六期记录）不在本期修。
- `lookback_days < 2` 时 `statistics.stdev` 无定义 → 恒回退固定（配置校验仍收 >0，语义下限 2，不崩溃、无特殊分支）。

### 决策 D6：需求 5 字段命名（B1 推荐 + B2 并留）

- **B1（推荐）**：`threshold_mode: "dynamic" | "fixed"` 显式标注模式（渲染/测试/回测可直读）。
- **B2**：另加 `dynamic_threshold: float | None`，字段名字面对应 PRD「dynamic_threshold 字段」，None=固定回退，隐式标注。
- 实施按 **两键同加**（一行成本，杜绝 PRD 字面合规争议）；`threshold` 恒为生效值 → `render_alert` / `_breach_item` / 回测消费方**零改动**自动携带动态值。若 Hy3 认为冗余，可只留其一，测试断言跟着改。
- **不改告警文件文本格式**（PRD 需求 5 是"告警 dict"数据层；加行会动 image_renderer 解析面与 render 测试，超范围）。
- **context breach.indices 键不动**：`threshold` 值自动变动态数（Hermes Prompt 输入语义变化，见 §7 文档同步）；`threshold_mode` 不入 context（改契约须同步 Hermes Prompt，PRD 非目标无此要求）。

## 3. 要改的文件列表

| 文件 | 改动性质 | 内容 |
|---|---|---|
| `src/config.py` | 改 | DEFAULTS["alert"] +3 键；`_merge_valid` bool 叶值分支；docstring/注释 |
| `src/analyzer.py` | 改 | 模块常量 ALERT_DYNAMIC/LOOKBACK/K_FACTOR；新纯函数 `dynamic_alert_threshold`（+内部 `_trailing_returns` 辅助）；`check_breach` 加 `history=None` 参数与模式解析、dict 新键 |
| `src/alerter.py` | 改 | `collect_breaches` / `run_alert_checks` 加 `history=None` 透传（纯接线） |
| `src/reporter.py` | 改 | `generate_context`：单次 load_history，剔除当日行后传 collect_breaches（见 D4） |
| `daily_report.py` | 改 | `run_alert_checks(...)` 加第 6 参 `history`（1 行） |
| `snapshot_report.py` | 改 | history 变量复用并传入（约 +2 行） |
| `scripts/backtest.py` | 改 | `collect_triggers` 传 `history[:i]`；触发记录 + `threshold_mode`；报告阈值章节与统计更新 |
| `tests/test_phase27.py` | 新增 | 见 §6（约 28-32 条） |
| `tests/test_backtest.py` | 改（待审计） | 若既有 fixture 行数 > lookback_days，动态模式激活使断言偏移 → 收敛行数或用显式关闭路径（见 §7 风险 R4） |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 改 | 文档同步（§7） |

不动的文件：`src/fetcher.py`（无告警逻辑）、`src/git_ops.py`、`web/`（PRD 非目标：UI/看板层）、`src/image_renderer.py`（告警文件格式不变）、`.env.example`/`README.md`（无新 env）。

## 4. 关键逻辑伪代码

### 4.1 analyzer.py：动态阈值（纯函数）

```python
def _trailing_returns(symbol, history, lookback_days):
    """从最新往回收集连续有效日收益（%）。遇该列非数值行即停（缺口中断，不跨期混算）。
    返回最新 lookback_days 个收益；样本不足时返回全部（由调用方判门槛）。"""
    lower = symbol.lower()
    rows = sorted((r for r in (history or []) if r.get("date")), key=lambda r: r["date"])
    closes = []
    for row in reversed(rows):                # 最新 → 最旧
        v = row.get(lower)
        if isinstance(v, (int, float)):
            closes.append(float(v))
        else:
            break                             # 缺口：更老数据跨期，混入会扭曲分布
    rets = [(closes[i - 1] - closes[i]) / closes[i] * 100.0
            for i in range(len(closes) - 1, 0, -1)]   # 相邻日收益，新→旧
    return rets[:lookback_days]

def dynamic_alert_threshold(symbol, history, lookback_days=None, k_factor=None):
    lookback_days = ALERT_LOOKBACK_DAYS if lookback_days is None else int(lookback_days)
    k_factor = ALERT_K_FACTOR if k_factor is None else float(k_factor)
    rets = _trailing_returns(symbol, history, lookback_days)
    if len(rets) < lookback_days or len(rets) < 2:
        return None                           # 样本不足 → 回退固定
    try:
        mean = sum(rets) / len(rets)
        std = statistics.stdev(rets)          # 样本标准差 ddof=1；零方差/异常 → 回退
    except statistics.StatisticsError:
        return None
    value = mean + k_factor * std
    return value if value > 0 else None       # ≤0（高 drift 病理）无意义 → 回退
```

### 4.2 analyzer.py：check_breach 模式解析

```python
def check_breach(symbol, current, last, history=None):
    if current is None or last is None or last == 0:
        return None
    change = (current - last) / last * 100.0
    threshold, mode, dyn_val = alert_threshold(symbol), "fixed", None
    if ALERT_DYNAMIC and history:
        dyn = dynamic_alert_threshold(symbol, history)
        if dyn is not None:
            threshold, mode, dyn_val = dyn, "dynamic", dyn
    if abs(change) <= threshold:
        return None
    … # 既有两个分支（STOCK_SYMBOLS / 波动率）原样，仅在返回 dict 追加
    #   "threshold_mode": mode, "dynamic_threshold": dyn_val
```

### 4.3 reporter.py generate_context（当日剔除）

```python
rows = load_history()                        # 单次读（原两次）
pre = [r for r in rows if r.get("date") != date]   # 动态窗口排除候选当日
breaches = collect_breaches(values, last_values, pre)
history_30d = rows[-TREND_DAYS:]             # 含当日，既有语义不动
```

## 5. 实施步骤（每步可独立验证）

1. **config.py**：DEFAULTS["alert"] +3 键；_merge_valid bool 叶值分支。
   验证：`venv/Scripts/python -m pytest tests/test_config.py tests/test_phase6a.py -v`（含新增 bool 关闭用例见 §6）。
2. **analyzer.py**：常量 + `_trailing_returns` / `dynamic_alert_threshold` / `check_breach` 扩展。
   验证：`venv/Scripts/python -m pytest tests/test_analyzer.py tests/test_alerter.py tests/test_phase6b.py tests/test_phase7.py tests/test_context.py -v`（既有调用不传 history → 全 fixed，应零漂移全绿）。
3. **alerter.py 透传 + reporter/daily/snapshot 接线**（D4）。
   验证：`venv/Scripts/python -m pytest tests/test_alerter.py tests/test_context.py tests/test_phase12.py tests/test_phase24.py tests/test_phase25.py -v`（入口 monkeypatch 为 `lambda *a, **k`，参数增加不破）。
4. **scripts/backtest.py**：collect_triggers 窗口化 + 报告语义更新。
   验证：`venv/Scripts/python -m pytest tests/test_backtest.py -v`（先审计 fixture 行数，见 §7 R4）。
5. **tests/test_phase27.py 新增**（§6）全绿。
6. **全量回归**：`venv/Scripts/python -m pytest tests/ -v`（存量 382+ 全绿 + 新增全绿）。
7. **实跑验证**（AUTO_PUSH=0 关闭自动推送）：
   - `AUTO_PUSH=0 venv/Scripts/python daily_report.py`：真实 90 日历史下动态生效——改 `data/last_values.json` 模拟大幅异动后运行，`alerts/YYYY-MM-DD-close.md` 中「阈值 ±X%」为动态数量级（波动率指数阈值 ≈ 其 20 日收益 2σ、大盘 ≈ 1-3% 量级），`context/*.json` breach.indices[].threshold 与之一致且 `search_keywords` 正常；验证后恢复基准。
   - 关闭路径：临时 `config.json` 置 `alert.dynamic=false` 重跑同一模拟 → 回退固定阈值（如 VIX ±20%），验证后恢复配置。
   - `AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market a-share --time midday`：单板块告警同样动态生效、无副作用。
8. **回测实跑**：`venv/Scripts/python scripts/backtest.py` 与 `--history <临时小文件>`（<30 交易日优雅退出）路径均过。
9. **文档同步**（§7）后 `git diff` 复核改动范围，写 journal.md。

## 6. 新增测试 tests/test_phase27.py（约 28-32 条）

- **config**：DEFAULTS["alert"] 含 dynamic=True / lookback_days=20 / k_factor=2.0；config.json `alert.dynamic=false` 被接受（bool 合并分支）；非法值（字符串/0/缺键）回退默认不崩溃。
- **analyzer 纯函数**：确定性序列手算 mean/stdev/阈值（如收盘 100,101,99,102,105 → 手算收益 %、断言阈值 = mean+2×stdev，`pytest.approx`）；样本 < lookback_days → None；`lookback_days=1` → None（stdev 无定义）；全零方差 → None；窗口内缺口（None 行）中断取不到足够样本 → None；缺口在窗口之外不影响；计算值 ≤0 → None；k/lookback 参数显式传入覆盖模块常量（monkeypatch analyzer.ALERT_* 亦验）。
- **check_breach 模式**：传 21+ 行低波动 history（std 小 → 动态阈值 < 固定）→ 小异动触发且 `threshold_mode=="dynamic"`、`dynamic_threshold == pytest.approx(threshold)`；高波动 history → 大异动仍不触发；不传 history / 传空 / `ALERT_DYNAMIC=False`（monkeypatch）→ fixed 模式、`dynamic_threshold is None`；缺历史传 None 与固定阈值行为与旧版逐位一致（回归锚）。
- **接线**：collect_breaches / run_alert_checks 透传 history（monkeypatch check_breach 断言参数）；daily_report.main 把 L122 history 传入 run_alert_checks（monkeypatch 断言第 6 参）；generate_context 剔除当日行——构造 history 含当日巨幅行（若混入会使阈值剧变），断言 context breach 判定等价于剔除当日后的判定（两通道幂等）；snapshot 透传。
- **backtest**：collect_triggers 对长历史窗口化（断言触发记录带 threshold_mode，早段样本不足回退 fixed、晚段 dynamic）；报告含动态参数行与回退阈值表。
- 纪律：所有涉及 history 的用例显式传行列表（不依赖真实文件）；monkeypatch.delenv("ALERT_THRESHOLD_<SYM>", raising=False) 沿用 clean_thresholds 范式。

## 7. 风险评估与注意事项

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | **行为变更（特性本身）**：默认 dynamic=true，已有 config.json 无新键 → 存量用户阈值语义静默切换；用户手工调过的 `alert.vix=22/35` 之类仅剩 fallback 角色 | 中 | PRD 明确默认 true；文档与 commands.md 明写优先级与关闭方法；发布说明突出 |
| R2 | **既有验证场景失真**：commands.md「+22% 模拟、ALERT_THRESHOLD_VIX=30 不告警」在动态默认下不成立（env 只压 fallback；真实历史下 +22% 远超动态阈值必告警） | 高（文档错位） | commands.md 验证要点改写：env 覆盖 drill 须先 `alert.dynamic=false`；新增「动态生效」「关闭回退」两条 drill |
| R3 | **当日行混入窗口**：generate_context 在 append 之后重读，若忘剔除 → 大异动自我削弱 + 与告警文件通道不一致，破坏幂等契约 | 高 | D2/D4 显式接线 + §6 当日剔除专项测试锁定 |
| R4 | **backtest 既有测试漂移**：fixture 行数 > 20 时动态模式激活，触发集/阈值断言偏离 | 中 | 步骤 4 先审计 `tests/test_backtest.py` fixture 长度；>20 行的 fixture 或截短（保 fixed 语义）或按动态值重算断言 |
| R5 | **缺口/样本不足语义**：连缺多日、新标的冷启动期回退固定——与「90 日滚动」数据现实冲突面 | 低 | 回退即设计；backtest 报告 dynamic/fixed 计数让用户可见回退占比 |
| R6 | **_merge_valid bool 分支**：新增泛化分支若误伤现有数字叶值 | 低 | 分支条件严格 `isinstance(base_val, bool)`；既有键无 bool，全量回归兜底 |
| R7 | **告警 dict 加键**：任何断言全 dict 相等的测试会破 | 低 | 已核实既有测试均为键级断言（test_alerter/test_context/test_phase6b/7 抽查）；全量回归确认 |
| R8 | **阈值 ≤0 / 零方差病理**（高 drift 资产、停牌期） | 低 | 函数内双守卫回退 fixed（§4.1） |

**文档同步清单**：
- `AGENTS.md` project map：src/config.py / src/analyzer.py / src/alerter.py / scripts/backtest.py 行描述补「动态阈值」；任务完成后按 Working Rules 追加可复用规则到 `docs/pitfalls.md`。
- `docs/architecture.md`：模块表职责行、关键决策表新增「动态告警阈值」行（窗口排除当日 / 缺口中断 / 优先级 / 两通道一致性 / 字段标注），五期约束段补 alert.dynamic 新键。
- `docs/commands.md`：回测命令描述（阈值表变回退表 + 动态参数）；验证要点 R2 改写 + 新增「动态阈值（二十七期）」段落。
- `docs/pitfalls.md`：新规则——动态窗口须排除候选当日（两通道同一行集）；缺口中断不跨期；env/config 固定阈值退居 fallback；stdev 样本下限 2；动态值 ≤0/零方差回退；backtest 夹具行数 > lookback 会激活动态；generate_context 剔除当日行。
- **Hermes Prompt（交付配置项，非仓库文件）**：提示 breach.indices[].threshold 现为动态值（mean+k×std），可选展示 threshold_mode——需人工同步，plan 阶段只记录。

**预计影响范围**：8 个源码/脚本文件 + 1 个新测试文件 + 可能 1 个存量测试文件微调 + 4 个文档；`src/fetcher.py`、`web/`、`src/image_renderer.py`、`src/git_ops.py` 零接触。行为影响面 = 告警判定（告警文件/context breach/回测），报告与看板仅 threshold 数值展示自动更新。

## 8. 决策记录（备选与选型）

- **A**：窗口按标的自有收益分布（D1，采纳）↔ VIX 全局缩放 / EWM（否决，理由见 §2 表）。
- **B**：`threshold_mode` + `dynamic_threshold` 双键（D6，采纳）↔ 仅其一（若 Hy3 觉得冗余可删，测试同步）。
- **C**：公式 F1 单值对称阈值（采纳）↔ F2 方向取界（否决：渲染/context 契约破坏、成本高、数值差可忽略）。
- **D**：缺口「遇 None 即停」连续窗口（采纳）↔ 跳过 None 跨期混算（否决：混合收益期限、std 失真）。
- **E**：不加 ENV_MAP 新键（采纳）↔ 加 `ALERT_DYNAMIC/LOOKBACK/K` env（PRD 未要求；如需运维快速开关，后续一行接入）。
