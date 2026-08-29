# 实施计划 — MarketPulse 五期「阈值配置化」

> 架构师只读分析产出，用户确认后再实施。引用 PRD：`tasks/2026-09-01-marketpulse-phase5/prd.md`

## 任务概要

- **目标**（引用 PRD Goal）：将 `analyzer.py` 中硬编码的阈值移到统一的 `config.json`，支持"改配置不改代码"，为后续加股票分析、新指标打好配置基础设施。
- **Python 侧职责**：新增 `src/config.py`（`load_config()`：JSON + env 覆盖 + 内置默认），改造 `analyzer.py` / `reporter.py` 从配置读阈值；`config.json` 放项目根并入 `.gitignore`。
- **相关文件**：见下方「文件清单」。
- **验证命令**（引用 docs/commands.md 实际命令）：
  - `venv/Scripts/python -m pytest tests/ -v`（全量测试，原 86 + 新增配置测试）
  - `venv/Scripts/python daily_report.py` / `snapshot_report.py`（两入口手动矩阵）

## 现状盘点（只读分析结论）

| 项 | 现状 |
|---|---|
| 阈值实际落点 | **全部在 `src/analyzer.py`**：`VIX_CALM=20.0`/`VIX_WARN=30.0`/`MOVE_CALM=100.0`/`MOVE_WARN=130.0`（`classify_vix`/`classify_move` 调用时读模块常量）、`ALERT_THRESHOLDS={"VIX":20,"VXN":20,"MOVE":15}`（`alert_threshold()` 的默认值，env 调用时读）、`HISTORY_MAX=90`（`append_history` 裁剪用） |
| `src/alerter.py` | **无任何阈值代码**：从 analyzer 导入 `check_breach`，阈值经 `alert_threshold()` 流入。PRD 表格写"alerter.py 改造"系位置误记，实际**零改动** |
| `src/reporter.py` | `TREND_DAYS=30` 模块常量，`render_trend_chart`（`rows[-TREND_DAYS:]`）与 `generate_context`（`history[-TREND_DAYS:]`）共用 |
| 入口 | `daily_report.py` / `snapshot_report.py` 不直接引用阈值常量，仅经 analyzer/reporter 函数间接使用——**入口零改动**（PRD 方案 b：模块自行加载配置） |
| env 机制 | `alert_threshold()` 已支持 `ALERT_THRESHOLD_<SYM>` 调用时覆盖（非法/非正回退默认，有日志）；`STATUS_THRESHOLD_*` / `TREND_CHART_DAYS` / `HISTORY_RETENTION_DAYS` 不存在 |
| 既有测试 | 86 条：classify 边界值写死（20/30/100/130）、alert 默认 20/20/15 + env 覆盖（`clean_thresholds` fixture delenv）、`TestHistory.test_rolling_90` 断言恰好 90、`test_context.py:189` 断言 history_30d 窗口 35→30——**全部依赖默认阈值** |
| tests/ | 仅 4 个测试文件，**无 conftest.py**；测试模块在 collection 时导入 analyzer/reporter（阈值 import 时快照） |
| 依赖 | requests / matplotlib / pytest；配置加载只用标准库（json/os/logging/pathlib），**零新增依赖** |
| 文档 | architecture.md / commands.md / pitfalls.md / README.md 均需同步；README 无配置章节 |

## 设计决策

### 已确认决策（用户定稿，直接落实，不可改）

1. **JSON 不用 YAML** — 零新增依赖；`config.json` 放项目根目录。
2. **优先级链**：env > config.json > 内置默认；`ALERT_THRESHOLD_*` 保留并扩展到状态/趋势/历史阈值。
3. **向后兼容**：config.json 不存在 → 内置默认值，系统不崩溃。
4. **模块简化**：无 `config/` 子目录，直接 `src/config.py` + 项目根 `config.json`。
5. **环境变量覆盖保留并扩展**：`CONFIG_PATH` 指定配置文件路径。

### 本计划新增的设计选择（需确认）

| # | 选择 | 理由 |
|---|---|---|
| A | **import 时快照 + 调用时 env 复核**：`analyzer.py`/`reporter.py` 导入时 `_CFG = load_config()` 一次，把阈值常量（`VIX_CALM`/`ALERT_THRESHOLDS`/`HISTORY_MAX`/`TREND_DAYS`）算成模块常量（名字不变，测试 monkeypatch 路径不变）；`classify_vix`/`classify_move`/`alert_threshold` **调用时**再经 `config.env_float()` 复核各自 env——与三期 `alert_threshold` 行为完全一致，`STATUS_THRESHOLD_*` 用同一机制扩展。env 双重应用（import 快照一次 + 调用一次）幂等无害 | cron 每次全新进程，import 快照语义正确；调用时复核让 `STATUS_THRESHOLD_*` 可用现有 `monkeypatch.setenv` 风格直接单测（无需模块 reload）；模块常量名保留使既有 86 条测试的 `monkeypatch.setattr` 模式零迁移 |
| B | **tests/conftest.py 强制隔离**：conftest 顶层 `os.environ["CONFIG_PATH"] = tests/_nonexistent_config.json`（collection 前生效），全量测试恒用内置默认运行——**用户定制过 config.json 后跑 pytest 不破坏既有断言** | config.json 入 gitignore 后用户必会定制；若无隔离，import 时快照会把用户阈值读进测试，classify 边界/90 天滚动/30 天窗口断言全崩。PRD 风险表"测试混用生产配置"的正解 |
| C | `src/config.py` 提供 `env_float(name, default)` 共享助手（解析 + 非法/非正回退 + 日志），`alert_threshold` 内联逻辑收敛到它（行为等价，既有 4 条 env 测试不动） | 三期 `alert_threshold` 已有该逻辑，抽取后 classify 复用同一语义；消除两处重复实现 |
| D | **retention 裁剪只在 `append_history`**：`history.retention_days` 只供 `append_history` 的 `[-HISTORY_MAX:]`（`load_history` 本身不裁剪、不传参） | 与现实现一致；PRD 措辞"load_history 使用 retention_days"按实际落点实现，行为不变 |
| E | `load_config()` 白名单合并：只认 DEFAULTS 已知路径；文件缺键 → 补默认；未知键 → 忽略（向前兼容）；叶值须为**非 bool 的数字**（`isinstance(v, bool)` 排除——bool 是 int 子类）且 >0，否则回退默认并 `log.warning`；env 非法同样回退下一优先级 | PRD 类型校验要求；bool 陷阱不排除会把 `true` 当 1 |
| F | 入口零改动（模块自加载），`load_config()` 不缓存（每次调用读文件，cron 每进程只调几次，性能无虞）；`env_float` 每次调用查 `os.environ.get`（与三期同量级开销） | PRD 方案 b 允许；保持入口签名稳定 |
| G | 配置→模块接线用 `importlib.reload` 集成测试验证（写临时 config.json → setenv CONFIG_PATH → reload(an) → 断言常量 → finally 恢复 env + reload），同时断言 hermetic 默认值接线（`an.VIX_CALM == DEFAULTS...`） | 只测 load_config 不测接线会出现"配置加载对但没用上"的假绿；reload 测试在 finally 恢复，不污染后续用例 |

## config.json 结构与 env 映射

```json
{
  "analysis": {
    "vix": { "peaceful": 20, "panic": 30 },
    "move": { "normal": 100, "tight": 130 }
  },
  "alert": {
    "vix": 20, "vxn": 20, "move": 15
  },
  "trend": { "chart_days": 30 },
  "history": { "retention_days": 90 }
}
```

| env（最高优先级） | 覆盖路径 | 消费方 |
|---|---|---|
| `ALERT_THRESHOLD_VIX/VXN/MOVE` | `alert.vix/vxn/move` | `alert_threshold()`（调用时 + import 快照） |
| `STATUS_THRESHOLD_VIX_CALM` / `STATUS_THRESHOLD_VIX_PANIC` | `analysis.vix.peaceful` / `.panic` | `classify_vix`（调用时 + import 快照） |
| `STATUS_THRESHOLD_MOVE_CALM` / `STATUS_THRESHOLD_MOVE_WARN` | `analysis.move.normal` / `.tight` | `classify_move`（调用时 + import 快照） |
| `TREND_CHART_DAYS` | `trend.chart_days` | `reporter.TREND_DAYS`（import 快照） |
| `HISTORY_RETENTION_DAYS` | `history.retention_days` | `analyzer.HISTORY_MAX`（import 快照） |
| `CONFIG_PATH` | 配置文件路径（非阈值） | `load_config()` 路径解析 |

**优先级链**：env（调用时复核 + import 快照已含）> config.json（import 快照）> 内置默认。config.json 缺失/损坏/类型非法 → 对应键回退默认，仅 `log.warning`，不崩溃。

## 文件清单

### 新增

| 文件 | 内容 | 预估行数 |
|---|---|---|
| `src/config.py` | `DEFAULTS`（与当前硬编码一致）+ `ENV_MAP`（env 名→路径）+ `env_float()` + `load_config(path=None)`：路径解析（显式 > `CONFIG_PATH` > 项目根 `config.json`）→ 读文件（缺失/损坏/非 dict 降级默认）→ 白名单类型校验合并 → env 覆盖 → 返回完整 dict | ~75 |
| `config.json` | 上节结构，全部与当前硬编码一致的示例值（用户可改，gitignore 排除） | ~14 |
| `tests/conftest.py` | 顶层 `os.environ["CONFIG_PATH"] = tests/_nonexistent_config.json`（collection 前生效，隔离生产配置） | ~6 |
| `tests/test_config.py` | 见下「测试设计」 | ~120 |

### 修改

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | 删 4 个状态阈值常量定义与 `HISTORY_MAX=90`、`ALERT_THRESHOLDS` 字面量 → `_CFG = load_config()` 后派生同名常量（`VIX_CALM = float(_CFG["analysis"]["vix"]["peaceful"])` 等，`ALERT_THRESHOLDS = {sym: float(_CFG["alert"][sym.lower()]) for sym in SYMBOLS}`，`HISTORY_MAX = int(...)`）；`classify_vix`/`classify_move` 开头各加 2 行 `env_float("STATUS_THRESHOLD_*", 常量)` 复核；`alert_threshold` 内联 env 逻辑换 `config.env_float`（行为等价）；`append_history` 不动（已用 `HISTORY_MAX`） | ~+10 / -7 |
| `src/reporter.py` | `TREND_DAYS = 30` → `TREND_DAYS = int(load_config()["trend"]["chart_days"])`（加 import）；`render_trend_chart`/`generate_context` 不动（已引用 TREND_DAYS） | +3 |
| `.gitignore` | 新增 `config.json`（注释"用户自定义配置，不入库"） | +2 |
| `README.md` | 新增「⚙️ 配置说明」章节：config.json 结构、env 覆盖表、优先级链、CONFIG_PATH、gitignore 说明；能力一览表加五期行 | ~+35 |
| `docs/architecture.md` | 模块表加 `src/config.py`；关键决策补五期决策（配置优先级链/import 快照+调用时 env/conftest 隔离）；约束行数更新（832 → 约 920） | — |
| `docs/commands.md` | 验证要点补 config 场景（见验证矩阵） | — |
| `docs/pitfalls.md` | 五期小节：conftest 隔离、reload 测试须 finally 恢复、env 双重应用幂等、bool 是 int 子类、retention 裁剪只在 append_history、CONFIG_PATH 解析顺序 | — |
| `AGENTS.md` | 项目地图补 `src/config.py` 与 `config.json` | — |

**不改**：`src/alerter.py`（无阈值，PRD 位置误记，见现状盘点）、`src/fetcher.py`、`daily_report.py` / `snapshot_report.py`（设计 F）、`requirements.txt`（零新依赖）、`.env` / `.env.example`、既有 86 条测试（conftest 隔离后默认值行为不变）。

## 测试设计（tests/test_config.py）

- **TestDefaults**：`load_config()` 指向不存在文件 → 返回值与当前硬编码一致（20/30/100/130、alert 20/20/15、30、90）。
- **TestLoadFile**：合法临时 config.json → 各值生效；**部分键**（如只有 alert）→ 缺失键回退默认（深合并）。
- **TestInvalidFile**：损坏 JSON / 根非 dict / 文件不可读 → 默认值 + 不抛异常。
- **TestTypeValidation**：字符串 / bool / 0 / 负数 → 回退默认；int 正常接受。
- **TestEnvOverride**：`ENV_MAP` 每项逐一 setenv 覆盖文件值；env 非法 → 保留文件/默认值；env > 文件 > 默认三级链各取一例。
- **TestConfigPath**：显式 `path=` 参数优先于 `CONFIG_PATH`；`CONFIG_PATH` 优先于项目根默认。
- **TestWiring**（设计 G）：hermetic 断言 `an.VIX_CALM == 20.0` / `an.HISTORY_MAX == 90` / `rep.TREND_DAYS == 30` / `an.ALERT_THRESHOLDS == {...}`；reload 集成（临时 config 22/35 + `importlib.reload(an)` → 常量更新 → finally 恢复 env + reload）。
- **TestStatusEnv**：`monkeypatch.setenv("STATUS_THRESHOLD_VIX_CALM", "22")` → `classify_vix(21.0)` 为"平静"；非法值回退默认（行为与默认一致）。
- **TREND/HISTORY env**：setenv + reload 断言 `rep.TREND_DAYS` / `an.HISTORY_MAX` 更新，finally 恢复。

## 实施步骤（每步独立可验证）

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 新建 `src/config.py`（DEFAULTS/ENV_MAP/env_float/load_config） | src/config.py | 合并/校验逻辑边界 | `venv/Scripts/python -c "from src.config import load_config; print(load_config()['alert'])"` 输出默认值 |
| 2 | analyzer.py 接线：常量派生 + classify env 复核 + alert_threshold 收敛 | src/analyzer.py | 行为偏差（默认值必须与旧值逐位一致） | `venv/Scripts/python -m pytest tests/test_analyzer.py tests/test_alerter.py -v` 全绿 |
| 3 | reporter.py `TREND_DAYS` 接线 | src/reporter.py | import 循环（config 不依赖任何 src 模块，无环） | `venv/Scripts/python -m pytest tests/test_reporter.py tests/test_context.py -v` 全绿 |
| 4 | 新建 `config.json` + `.gitignore` 加行 | config.json, .gitignore | 键名与 DEFAULTS 漂移 | `venv/Scripts/python -c "from src.config import load_config; print(load_config())"` 显示文件值 |
| 5 | 新建 `tests/conftest.py` + `tests/test_config.py` | tests/ | reload 污染、env 泄漏 | `venv/Scripts/python -m pytest tests/ -v` 全绿（86 + 新增） |
| 6 | README + docs 同步（architecture/commands/pitfalls/AGENTS.md） | 上述 5 文件 | 文档与实现漂移 | 逐份核对与最终代码一致 |
| 7 | 手动验证矩阵（见下） | data/last_values.json（不改，仅配置矩阵） | Yahoo 限流致取数失败（属设计行为） | 见下方矩阵 |
| 8 | 行数预算 + `git diff` 审查 | 全部 | 增量超预算 | `wc -l` 源码增量 ≤ ~95；`git diff` 核对范围 |

### 手动验证矩阵（步骤 7，全部实际运行）

| 场景 | 操作 | 预期 |
|---|---|---|
| 默认配置 | `config.json` 存在且为示例值，运行 `daily_report.py` | 日志显示加载配置路径；报告状态标签与三期一致（VIX 15/25/35 → 平静/警惕/恐慌） |
| 缺失降级 | 移走 `config.json` 运行 `daily_report.py` | 不崩溃、退出码 0、日志 warning、报告用默认值正常生成；验证后恢复文件 |
| env 覆盖 | `ALERT_THRESHOLD_VIX=25 venv/Scripts/python daily_report.py` | env 生效（日志或告警行为按 25 判断）；`STATUS_THRESHOLD_VIX_PANIC=35` 时 VIX 31 状态为"警惕" |
| 改配置生效 | 编辑 `config.json` 的 vix 为 22/35，运行 `daily_report.py` | 报告状态标签按新阈值输出（如 VIX 21 → 平静、31 → 警惕）；验证后恢复 20/30 |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -v` | 全绿（86 + 新增，无网络） |
| JSON 校验 | `venv/Scripts/python -c "import json; json.load(open('config.json', encoding='utf-8'))"` | 解析成功 |

## 风险评估与注意事项

| 风险 | 应对 |
|---|---|
| 测试混用用户定制的 config.json（import 快照读进测试，classify/90 天/30 天断言全崩） | 设计 B：`tests/conftest.py` 顶层强制 `CONFIG_PATH` 指向不存在文件，collection 前生效；写入 pitfalls |
| reload 集成测试污染模块常量 | 设计 G：测试 finally 恢复 env 原值 + 再次 reload；写入 pitfalls |
| env 双重应用（import 快照 + 调用时复核）语义混淆 | 幂等无害（同一 env 同值）；设计 A 文档化；alert_threshold 收敛到 `env_float` 后语义单一 |
| bool 被 `isinstance(v, int)` 放过（`true` → 1） | 设计 E：校验显式排除 bool；TestTypeValidation 覆盖 |
| 部分键配置（用户只写 alert 段）丢默认 | 白名单深合并：缺失键补默认；TestLoadFile 覆盖 |
| 阈值默认值与旧硬编码漂移 | 步骤 2 验证命令逐位断言 + TestDefaults 锁定 20/30/100/130/20/20/15/30/90 |
| PRD 表格"alerter.py 改造"误导实施 | 现状盘点已更正：阈值全在 analyzer.py，alerter.py 零改动；步骤 2 验证覆盖 |
| 行数超预算 | 步骤 8 `wc -l` 硬校验（源码 832 → 约 920，含 config.py 75） |
| 改配置后需重启才生效 | cron 每进程全新启动，无影响；README 注明"配置变更对下次运行生效" |

## 不做什么

- 不改 `src/alerter.py`（无阈值代码）、`src/fetcher.py`、两入口、`.env`/`.env.example`、`requirements.txt`。
- 不引入 YAML/第三方配置库/任何新依赖。
- 不把配置文件读取放进热路径（`check_breach`/`build_statuses` 每次调用不重读文件；env 复核仅 `os.environ.get` 量级）。
- 不做 env 通配/动态键（`ENV_MAP` 白名单固定，未知 env 忽略）。
- 不改 context JSON 契约、告警文件格式、报告模板、告警去重逻辑。
- 不改既有 86 条测试（新增 conftest + test_config 实现隔离与覆盖）。

## 预计影响范围

- **新增文件**：`src/config.py`（~75）、`config.json`（~14，gitignore 排除）、`tests/conftest.py`（~6）、`tests/test_config.py`（~120）。
- **修改文件**：`src/analyzer.py`（~+10 / -7）、`src/reporter.py`（+3）、`.gitignore`（+2）、`README.md`（+~35）、`docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`AGENTS.md`。
- **不受影响**：`src/alerter.py`、`src/fetcher.py`、`daily_report.py`、`snapshot_report.py`、`requirements.txt`、`.env`、既有 86 条测试、Hermes cron（配置化后运行行为不变）。

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理（alerter.py 零改动已更正 PRD 位置误记）
- [ ] 设计选择 A（import 快照 + 调用时 env 复核）/ B（conftest 隔离）/ C（env_float 收敛）/ D（retention 裁剪只在 append_history）/ E（白名单校验 + 排除 bool）/ F（入口零改动）/ G（reload 接线测试）已确认
- [ ] config.json 结构与 env 映射表已确认（与 PRD 一致）
- [ ] 没有遗漏测试（默认值/加载/类型/env 三级链/CONFIG_PATH/接线/STATUS env 全覆盖）
- [ ] 没有引入不必要依赖
