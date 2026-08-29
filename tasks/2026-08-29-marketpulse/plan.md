# 实施计划：波动率监控系统 MVP

> 由架构师在只读分析后产出，人确认后再实施。

## 任务概要

- **目标**（引用 prd.md Goal）：**实现一个可独立运行的 Python 脚本，每天获取 VIX、VXN、MOVE 三个指数数据，生成 Markdown 报告文件，由 Hermes 读取并推送至 QQ 机器人。** 跑通"数据获取 → 报告生成 → 推送"最小闭环。
- **相关文件**：见下方"文件清单"
- **验证命令**：见"验证命令"（引用 docs/commands.md 实际命令）

## 现状分析（只读结论）

| 项目 | 状态 |
|---|---|
| `daily_report.py` | 不存在，待新建（本次主交付物） |
| `requirements.txt` | 存在但用 `>=`，**违反 PRD"锁定明确版本号"约束**，需改为 `==` |
| `.env.example` / `.env` | 已存在；`.env` 是用户配置，**不改** |
| `reports/`、`data/`、`tests/` | 目录已建（空），脚本运行时自动生成产物 |
| `.gitignore` | 已排除 `.env`、`reports/`、`data/`、`venv/`，无需改动 |
| venv 已装版本 | yfinance 1.7.0 / requests 2.34.2 / python-dotenv 1.2.3 / pytest 9.1.1 |
| Hermes / QQ 推送 | 已完成（Out of Scope），脚本不含推送逻辑 |

## 设计决策

| # | 决策 | 选型 | 理由 | 替代方案（弃用原因） |
|---|---|---|---|---|
| 1 | VXN/MOVE 的状态列 | VIX、VXN 共用 20/30 阈值（同量级波动率指数）；**MOVE 用 100/130 阈值**（经调研，用户确认） | PRD 只定义 VIX 阈值；MOVE 量级约 60-200，套 VIX 的 20/30 无意义，故按 MOVE 历史中枢与危机水平设 100/130 | 三列都标 VIX 状态（误导）；MOVE 显示 "—"（用户要求给出阈值） |
| 2 | 单源失败 / 全源失败时 | 记录错误、继续运行；**仍生成报告**（失败项标注"获取失败"+ 原因），**退出码恒为 0** | PRD 明确"单源失败继续运行不崩溃"；Hermes 定时任务依赖退出码，恒 0 避免误报警 | 全失败退出非 0（会触发 Hermes 报警噪音，需用户确认才可改） |
| 3 | 时区实现 | 内部 `datetime.now(timezone.utc)`；报告日期用标准库 `zoneinfo.ZoneInfo("America/New_York")` 转换 | PRD 要求 UTC 内部 + 美东显示；零额外依赖 | pytz（python-dotenv 已依赖它，但 zoneinfo 更现代且标准） |
| 4 | 缓存结构 | `{"date": "YYYY-MM-DD", "values": {"VIX": .., "VXN": .., "MOVE": ..}}`，存美东日期 | date 字段为同日重复运行检测留余地（MVP 不实现检测，仅存储） | 纯 `{symbol: value}`（无法区分同日重跑） |
| 5 | 测试策略 | 纯逻辑（状态判断/涨跌幅/报告渲染/日期）进 `pytest`，**不碰网络**；联网场景走手动验证 | 测试确定性、离线可跑；PRD 的断网/首跑验证本质是运行时行为 | mock yfinance/requests（过度设计，MVP 不必） |
| 6 | 依赖锁定 | `requirements.txt` 全部改为 `==`，版本 = venv 已装版本 | PRD 硬约束；与实测环境一致 | 锁定旧版（与已装环境不符，重装会漂移） |
| 7 | 涨跌幅基准 | 今日值 vs `last_values.json` 缓存值 | PRD 约定（缓存前一日值作基准） | 每次拉历史两日（与 PRD 数据流不符） |

## 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `daily_report.py` | **新建** | 主脚本（全部逻辑，200-300 行） |
| `requirements.txt` | **修改** | 版本锁定：`yfinance==1.7.0`、`requests==2.34.2`、`python-dotenv==1.2.3`、`pytest==9.1.1` |
| `tests/test_daily_report.py` | **新建** | 纯逻辑单元测试（不联网） |
| `tasks/2026-08-29-marketpulse/plan.md` | 新建 | 本计划 |
| `tasks/2026-08-29-marketpulse/journal.md` | 执行者交付 | 任务日志（AGENTS.md 要求） |

不改：`.env`、`.env.example`、`README.md`（已覆盖用法）、`.gitignore`、`docs/*`。

## 实现步骤

每步独立可验证；按顺序执行。

### 步骤 1：锁定依赖版本
- 改 `requirements.txt`：`>=` 全部改为 `==`（版本取 venv 实测版本）
- **验证**：`venv/Scripts/pip install -r requirements.txt` 成功且 `venv/Scripts/pip show yfinance` 版本不变

### 步骤 2：实现纯逻辑层（daily_report.py 上半部分）
- 常量：`SYMBOLS`、阈值（20/30）、超时（15s）、重试（1 次）、路径
- `get_us_eastern_date()`：UTC now → America/New_York → `YYYY-MM-DD`
- `classify_vix(value) -> (label, description)`：`<20` 平静 / `20≤x<30` 警惕 / `≥30` 恐慌；对 VXN 复用
- `classify_move(value) -> (label, description)`：`<100` 平静 / `100≤x<130` 警惕 / `≥130` 恐慌（MOVE 阈值 100/130，经调研用户确认）
- `compute_changes(current, last_values) -> {symbol: {"change_pct": float|None}}`：None 表示无历史（首跑）
- `render_report(data) -> str`：严格按 prd 附录模板，占位符全部替换，无残留 `{xxx}`
- `build_summary(...)`：基于 VIX 状态 + 数据完整性（哪些源失败/缺失）拼确定性总结
- 伪代码：
```python
def compute_changes(current, last):
    for sym, val in current.items():
        if sym in last:  change = (val - last[sym]) / last[sym] * 100
        else:            change = None   # 首跑
```
- **验证**：步骤 3 的单元测试

### 步骤 3：编写并运行单元测试
- `tests/test_daily_report.py`：
  - `classify_vix` 边界：19.99/20.00/29.99/30.00
  - `compute_changes`：正常、除零保护（last 为 0）、首跑 None
  - `render_report`：含日期、表格三行、状态标签、无未替换占位符
  - `get_us_eastern_date`：格式正则 `\d{4}-\d{2}-\d{2}`
- **验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿

### 步骤 4：实现数据获取层
- `fetch_vix_vxn()`：`yf.Ticker("^VIX"/"^VXN").history(period="5d", auto_adjust=False, timeout=15)`，取 `.iloc[-1]` 收盘价（5d 覆盖周末/节假日）
- `fetch_move()`：`requests.get(FRED_API, params=..., timeout=15)`，`sort_order=desc&limit=2` 取最新观测值；**无 `FRED_API_KEY` 时跳过并提示，不报错**
- 每个源包 `with_retry(fn, retries=1)`：try/except → 记录错误 → 返回 `None`（不抛给 main）
- 伪代码：
```python
def fetch_with_retry(name, fn):
    for attempt in (0, 1):
        try:    return fn()
        except Exception as e:
            log(f"{name} 获取失败(第{attempt+1}次): {e}")
    return None   # 源级失败，整体继续
```
- **验证**：步骤 6 联网实测；步骤 8 断网实测

### 步骤 5：实现缓存层
- `load_last_values()`：文件不存在 → 返回 `{}`（首跑）；JSON 损坏 → 记警告、按首跑处理
- `save_last_values(values, date)`：写入 `data/last_values.json`（UTF-8，缩进 2）
- **验证**：步骤 6 首跑后检查文件 + 步骤 8 删缓存重跑

### 步骤 6：实现 main 编排 + 完整联调
- 流程：加载 `.env`（`dotenv.load_dotenv()`）→ 取数（每源独立）→ 读缓存 → 算涨跌幅 → 渲染 → 写报告 → 写缓存 → 日志
- 日志（`logging` INFO）：每指数"值 或 失败原因"、报告路径；`reports/`、`data/` 用 `os.makedirs(exist_ok=True)` 兜底
- **验证**：`venv/Scripts/python daily_report.py` 30 秒内退出码 0；检查终端输出 + `reports/YYYY-MM-DD.md` 内容 + `data/last_values.json` 有效性：
  `venv/Scripts/python -c "import json; json.load(open('data/last_values.json', encoding='utf-8'))"`

### 步骤 7：边界场景实测（手动）
- 删除 `data/last_values.json` → 重跑 → 涨跌幅列显示"首次运行，暂无历史对比"
- **验证**：报告文件内容核对

### 步骤 8：断网/缺 Key 容错实测（手动）
- 断开网络 → 运行 → 不崩溃、退出码 0、日志明确提示各源失败原因、报告含"获取失败"标注
- 临时移除 `FRED_API_KEY` 环境变量 → 运行 → MOVE 被跳过并提示，VIX/VXN 正常
- **验证**：终端输出与报告内容

### 步骤 9：收尾
- `git diff` 检查改动范围（应只有 `daily_report.py`、`requirements.txt`、`tests/`、`tasks/` 新增）
- 写 `tasks/2026-08-29-marketpulse/journal.md`（目标/改动/验证结果/问题/下次注意）
- 提取可复用教训 → 追加 `docs/pitfalls.md`（如 yfinance 版本坑、pandas 3.0 兼容）

## 验证命令（引用 docs/commands.md）

| 命令 | 场景 |
|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 状态判断/涨跌幅/报告渲染逻辑（步骤 3） |
| `venv/Scripts/python daily_report.py` | 完整闭环（步骤 6） |
| `venv/Scripts/python -c "import json; json.load(open('data/last_values.json', encoding='utf-8'))"` | 缓存 JSON 有效性（步骤 6） |
| `venv/Scripts/pip install -r requirements.txt` | 锁定版本可安装校验（步骤 1） |
| `git diff` | 改动范围检查（步骤 9） |
| 手动断网运行 + 删缓存重跑 | 容错与首跑逻辑（步骤 7/8） |

## 风险评估

| 风险 | 等级 | 应对 |
|---|---|---|
| yfinance 1.7.0 接口变动（`auto_adjust` 默认值翻转、返回 MultiIndex 列） | 中 | 显式传 `auto_adjust=False`；取数用 `.iloc[-1]` + 列名兼容处理；失败走源级容错 |
| pandas 3.0.5 与 yfinance 兼容性 | 低 | 当前已装且是 yfinance 1.7.0 官方支持代；实测为准，异常进 pitfalls |
| FRED 返回最新观测为旧日期（周末/假日） | 低 | 取 `limit=2` 最新值即可，MVP 接受 |
| 同日重复运行导致涨跌幅为 0.0% | 低 | 缓存带 date 字段；MVP 不做检测，风险记录，后续可加"同日跳过/提示" |
| 全源失败仍退出码 0，Hermes 可能推送空报告 | 低 | 符合"不崩溃"约束；若用户希望全失败非 0 退出，需确认后调整 |
| 周末运行：Yahoo 返回最后交易日收盘，涨跌幅对比的是缓存（可能同一值） | 低 | 预期行为，报告日期仍为美东当日 |
| MOVE 状态列显示 "—" 与模板观感 | 低 | 已列设计决策 1，用户可确认或改 |

## 预计影响范围

- 新增：`daily_report.py`（~250 行）、`tests/test_daily_report.py`（~80 行）、本 plan.md、journal.md
- 修改：`requirements.txt`（4 行版本号 `>=` → `==`）
- 运行时生成（不入 git）：`reports/YYYY-MM-DD.md`、`data/last_values.json`
- 不影响：`.env`、`.env.example`、`README.md`、`.gitignore`、`docs/architecture.md`、`docs/commands.md`、Hermes 配置

## 不做什么

- 不实现推送逻辑（Hermes 负责）
- 不做盘中多次检查、告警、历史存储、趋势图、Web 界面、Docker（prd Out of Scope）
- 不加新依赖（zoneinfo 用标准库；不引入 mock 库）
- 不修改 `.env` 与生成物
- 不为 VXN 编造独立阈值（复用 VIX 20/30）；MOVE 阈值 100/130（<100 平静 / 100-130 警惕 / ≥130 恐慌）

## 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理（新增 2 文件 + 修改 1 文件）
- [x] 设计决策 1（MOVE 阈值 100/130，已调研+用户确认）与决策 2（全失败退出码 0，用户已确认）
- [ ] 没有遗漏测试（纯逻辑已覆盖，联网场景手动验证）
- [ ] 没有引入不必要依赖
