# Task Handoff：MarketPulse 第五期 — 阈值配置化

> 复制到 `tasks/2026-09-01-marketpulse-phase5/prd.md`


## Goal

将 `analyzer.py` 和 `alerter.py` 中硬编码的阈值移到统一的配置文件(`config.json`)中,支持"改配置不改代码"。为后续加股票分析、新指标等扩展打好配置基础设施。

## 已确认的设计决策（用户定稿，勿改）

1. **用 JSON 不用 YAML** — 零新增依赖(`json` 标准库已有),`config.json` 放项目根目录。
2. **优先级链**:环境变量 > config.json > 代码内置默认值。已有的 `ALERT_THRESHOLD_*` env 机制保留并扩展到状态判断阈值。
3. **向后兼容**:config.json 不存在时用内置默认值,系统不崩溃。
4. **模块简化**:不需要 `config/` 子目录,直接 `src/config.py` + 项目根 `config.json`。

## 当前硬编码阈值

| 位置 | 硬编码值 | 文件 |
|------|----------|------|
| VIX 状态 | <20 平静 / 20-30 警惕 / ≥30 恐慌 | analyzer.py |
| MOVE 状态 | <100 平静 / 100-130 警惕 / ≥130 恐慌 | analyzer.py |
| 告警阈值 | VIX ±20% / VXN ±20% / MOVE ±15% | alerter.py(已支持 env 覆盖) |
| 趋势图天数 | 30 | reporter.py |
| 历史保留天数 | 90 | analyzer.py |

## config.json 结构

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

环境变量覆盖(最高优先级):
```
ALERT_THRESHOLD_VIX=25    → 覆盖 alert.vix
ALERT_THRESHOLD_VXN=25    → 覆盖 alert.vxn
ALERT_THRESHOLD_MOVE=18   → 覆盖 alert.move
STATUS_THRESHOLD_VIX_CALM=22  → 覆盖 analysis.vix.peaceful
STATUS_THRESHOLD_VIX_PANIC=35 → 覆盖 analysis.vix.panic
STATUS_THRESHOLD_MOVE_CALM=90 → 覆盖 analysis.move.normal
STATUS_THRESHOLD_MOVE_WARN=120→ 覆盖 analysis.move.tight
TREND_CHART_DAYS=60       → 覆盖 trend.chart_days
HISTORY_RETENTION_DAYS=120→ 覆盖 history.retention_days
```

## Requirements

### 必须实现

1. **配置加载模块** (`src/config.py`, ~60行)
   - `load_config(path=None) -> dict`: 读取 config.json,失败/缺失用内置默认值
   - 优先级: env > config.json > 内置默认
   - 内置默认值与当前硬编码一致(保证向后兼容)
   - 类型校验:读到非数字时回退默认值
   - 支持 `CONFIG_PATH` 环境变量指定配置文件路径

2. **analyzer.py 改造**
   - 移除 `VIX_CALM/VIX_WARN/MOVE_CALM/MOVE_WARN/HISTORY_MAX` 硬编码常量
   - `classify_vix()` / `classify_move()` 从配置读取阈值
   - `HISTORY_MAX` 从配置读取
   - `load_history()` 使用配置的 retention_days

3. **alerter.py 改造**
   - `ALERT_THRESHOLDS` 从配置读取(替代硬编码)
   - 已有的 `alert_threshold()` env 覆盖机制保留(仍为最高优先级)

4. **reporter.py 改造**
   - `TREND_DAYS` 从配置读取

5. **入口改造**
   - `daily_report.py` / `snapshot_report.py` 初始化时调用 `load_config()` 并传递给各模块
   - 或:各模块自行调用 `load_config()` (更简单,不改入口签名)

6. **config.json 放项目根目录**,加入 `.gitignore`(用户可自定义阈值,不入库)

7. **测试**
   - 新增 `tests/test_config.py`: 加载成功/失败/环境变量覆盖/类型校验
   - 既有 analyzer/alerter 测试不受影响(内置默认值与原硬编码一致)
   - 测试中使用 `monkeypatch` 注入配置或 mock `load_config`

### 必须保持

- 不新增任何 Python 依赖
- config.json 不存在时系统正常运行(用默认值)
- 环境变量覆盖机制保留且优先级最高
- 既有 86 项测试全绿(配置化后行为不变)

## Context Pointers

### 需新增/修改的文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `config.json` | 新建 | 配置文件(项目根) |
| `src/config.py` | 新建 | 配置加载模块 |
| `src/analyzer.py` | 修改 | 阈值从配置读取 |
| `src/alerter.py` | 修改 | 阈值从配置读取 |
| `src/reporter.py` | 修改 | TREND_DAYS 从配置读取 |
| `.gitignore` | 修改 | 新增 config.json |
| `tests/test_config.py` | 新建 | 配置加载测试 |
| `README.md` | 修改 | 新增"配置说明"章节 |

### 不影响的部分

- `src/fetcher.py`: 无需修改
- `daily_report.py` / `snapshot_report.py`: 入口可能微调(初始化配置),或不改(模块自行加载)
- `docs/`: 架构/命令/pitfalls 同步更新

## Constraints

- 零新增依赖
- 向后兼容(config.json 不存在不崩溃)
- 环境变量优先级最高
- 测试使用独立配置或 mock,不依赖生产 config.json
- 配置加载失败静默降级(记日志,用默认值)

## Done When

- [ ] `src/config.py` 实现, `load_config()` 支持 JSON + env 覆盖 + 默认值
- [ ] `config.json` 创建,包含所有阈值
- [ ] `analyzer.py` / `alerter.py` / `reporter.py` 从配置读取阈值
- [ ] config.json 入 .gitignore
- [ ] 所有测试通过(原 86 + 新增配置测试)
- [ ] 删除 config.json 运行不崩溃(用默认值)
- [ ] env 覆盖测试通过

## Verification

- [ ] 运行 `daily_report.py`,确认使用 config.json 中的阈值
- [ ] 删除 config.json,运行脚本,确认用默认值且不崩溃
- [ ] 设置 `ALERT_THRESHOLD_VIX=25`,确认 env 覆盖 config.json
- [ ] 修改 config.json 中 VIX 阈值为 22/35,运行脚本确认新阈值生效
- [ ] `pytest tests/ -v` 全绿
- [ ] 检查 `reports/*.md` 状态标签按新阈值输出

## Risks

| 风险 | 应对 |
|------|------|
| JSON 格式错误 | load_config 捕获异常,降级默认值+记日志 |
| 配置值类型错误 | 基本类型校验,异常用默认值 |
| 测试混用生产配置 | mock load_config 或用临时配置文件 |
| config.json 路径不一致 | 支持 CONFIG_PATH 环境变量 |