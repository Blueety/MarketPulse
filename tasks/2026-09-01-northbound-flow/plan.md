# 执行计划：A股北向资金监控（Northbound Flow）

> 本计划由架构师制定，执行者按步骤逐一实施。每步完成后运行验证命令。

## 目标

为 MarketPulse 增加 A 股北向资金（沪深港通）监控能力：获取当日北向资金净流入数据，在日报中展示，并在异常流入时触发独立告警。

## 核心约束

- **容错第一**：数据获取失败时显示「数据暂缺」，不中断日报生成
- **无需 API Key**：优先使用 `adata`（免费）
- **告警独立**：北向资金告警与 VIX/大盘告警分开记录和推送
- **测试覆盖**：新增代码需包含单元测试，覆盖成功和失败场景

## 涉及文件清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `requirements.txt` | 修改 | 增加 `adata` |
| `src/northbound.py` | **新建** | 北向资金获取模块，含多源降级逻辑 |
| `src/config.py` | 修改 | 增加北向资金告警阈值配置项 |
| `src/fetcher.py` | 修改 | 不修改——北向资金独立模块，不在 fetch_all 循环内 |
| `src/analyzer.py` | 修改 | 增加北向资金历史键 + 告警阈值检查函数 |
| `src/reporter.py` | 修改 | 日报模板中增加北向资金行 + context 增加键 |
| `src/alerter.py` | 修改 | 增加北向资金独立告警规则和去重 |
| `daily_report.py` | 修改 | 编排入口调用北向资金模块 |
| `tests/test_northbound.py` | **新建** | 北向资金模块单元测试 |
| `.env.example` | 修改 | 增加北向资金相关环境变量 |

---

## 实施步骤

### 步骤 1：`requirements.txt` — 增加 adata 依赖

**文件**：`requirements.txt`

**改动**：
- 追加一行 `adata>=1.0.0`（或实际可用版本）

**注意事项**：
- 先 `venv/Scripts/pip install adata` 确认可安装，再写入 requirements.txt
- adata 约 20-30MB，可接受

**验证**：`venv/Scripts/pip install -r requirements.txt`

---

### 步骤 2：`src/config.py` — 增加北向资金阈值配置

**文件**：`src/config.py`

**改动**：
1. 在 `DEFAULTS` 字典中增加北向资金告警阈值：
   ```python
   "northbound": {"alert_threshold": 100.0},  # 亿元，净流入绝对值超过此值触发告警
   ```
   位置：与 `analysis`、`alert`、`trend` 等同级

2. 在 `ENV_MAP` 中增加环境变量映射：
   ```python
   "ALERT_NORTHBOUND_THRESHOLD": ("northbound", "alert_threshold"),
   ```

3. 在 `_merge_valid` 调用处或 `load_config` 返回后，确保新键被正确合并

**注意事项**：
- 阈值单位是**亿元**（绝对值），不是百分比——与现有 VIX 等变化率阈值不同
- env 优先级链不变：`ALERT_NORTHBOUND_THRESHOLD` > config.json > 内置默认 100
- 环境变量非法/非正回退默认值（复用 `env_float`）

**验证**：`venv/Scripts/python -c "from src.config import load_config; c=load_config(); print(c['northbound'])"`

---

### 步骤 3：`src/northbound.py` — 新建北向资金获取模块（核心）

**文件**：`src/northbound.py`（新建）

**结构设计**：

```python
"""北向资金获取模块：多源降级策略获取沪深港通资金流向。

降级链：adata → 返回 None
所有源失败时返回 None，不抛出异常（容错第一）。
"""
```

**核心函数**：

```python
def fetch_northbound_flow(date: str = None) -> dict | None:
    """获取北向资金当日净流入数据。
    
    返回格式：
    {
        "net_inflow": float,  # 北向资金净流入合计（亿元）
        "sh_net": float,      # 沪股通净流入（亿元）
        "sz_net": float,      # 深股通净流入（亿元）
        "date": str,          # YYYY-MM-DD
    }
    失败返回 None。
    """
```

**实现细节**：

1. **adata 数据源**：
   - 使用 `adata` 库获取北向资金数据
   - API 参考：`adata.stock.hsgt.north_net_flow_in_em()` 或类似接口
   - 需要处理：接口返回空/异常/列名变化
   - 超时：15 秒（复用 `TIMEOUT` 或独立常量 `NORTHBOUND_TIMEOUT = 15`）

2. **容错处理**：
   - 每个数据源独立 try/except，失败记日志返回 None
   - 所有源失败返回 None，不抛异常
   - 日志级别：数据源失败用 `warning`，最终降级用 `info`

3. **交易日判断**：
   - 若当日为非交易日（节假日/休市），返回 `{"net_inflow": 0, "sh_net": 0, "sz_net": 0, "date": date}`
   - 或返回 None + 日志标注「非交易日」
   - 建议：先尝试获取，返回空值/None 时判断是否为交易日

**注意事项**：
- adata 的 API 签名需实测确认（不同版本可能有差异）
- 返回值统一为**亿元**单位（如 adata 返回万元需 ÷10000）
- 不引入 MCP 服务依赖（PRD 说 cn-funds-mcp/akshare-stock-mcp 是备选，但 v1 先只实现 adata）
- 参考项目既有风格：独立模块、函数级容错、logging 记录

**验证**：`venv/Scripts/python -c "from src.northbound import fetch_northbound_flow; print(fetch_northbound_flow())"`

---

### 步骤 4：`src/analyzer.py` — 增加北向资金逻辑

**文件**：`src/analyzer.py`

**改动**：

1. **历史记录增加北向资金键**：
   - `load_history()` 中增加 `northbound`、`sh_net`、`sz_net` 键的读取
   - `append_history()` 的 record 参数需包含北向资金字段
   - 在 `load_history` 返回的 dict 中增加：
     ```python
     "northbound": rec.get("northbound"),
     "sh_net": rec.get("sh_net"),
     "sz_net": rec.get("sz_net"),
     ```

2. **北向资金告警检查函数**（新函数）：
   ```python
   def check_northbound_alert(northbound_data: dict | None) -> dict | None:
       """判断北向资金是否触发告警（净流入绝对值超过阈值）。
       
       返回告警 dict 或 None。阈值从 env/config 读取。
       """
   ```
   - 阈值逻辑：`abs(net_inflow) > threshold`（严格大于，等于不触发）
   - 阈值来源：`env_float("ALERT_NORTHBOUND_THRESHOLD", 100.0)`
   - 返回格式（与 `check_breach` 同构但字段不同）：
     ```python
     {
         "type": "northbound",
         "net_inflow": float,
         "sh_net": float,
         "sz_net": float,
         "threshold": float,
         "level": "WARN",  # 北向资金恒为 WARN，无恐慌区间
         "direction": "流入" | "流出",
     }
     ```

3. **format 北向资金显示值**（可选辅助函数）：
   ```python
   def fmt_northbound(value: float | None) -> str:
       """北向资金格式化：净流入 32.15 亿元 / 净流出 12.50 亿元 / 数据暂缺。"""
   ```

**注意事项**：
- 北向资金告警**不走 `check_breach`**——因为 check_breach 是基于变化率（百分比），而北向资金是绝对值（亿元）
- 北向资金在 `build_statuses` 中不需要状态分类（它不是指数，不走 classify_vix）
- 历史记录中北向资金字段为 `null` 时不报错（休市/获取失败场景）

**验证**：运行现有测试确保不破坏：`venv/Scripts/python -m pytest tests/test_analyzer.py -v`

---

### 步骤 5：`src/alerter.py` — 增加北向资金独立告警

**文件**：`src/alerter.py`

**改动**：

1. **导入新函数**：
   ```python
   from .analyzer import check_northbound_alert
   ```

2. **新增北向资金告警渲染函数**：
   ```python
   def render_northbound_alert(alert: dict, date: str, alert_type: str, report_path: "Path") -> str:
       """渲染北向资金告警附录块。"""
   ```
   - 格式示例：
     ```
     ---
     type: northbound-close
     date: 2026-09-01
     level: WARN
     ---
     
     ## 💰 北向资金异动
     
     - 级别：**WARN**
     - 方向：净流入
     - 合计净流入：135.20 亿元
     - 沪股通：+80.50 亿元
     - 深股通：+54.70 亿元
     - 阈值：100 亿元
     - 相关报告：2026-09-01.md
     ```

3. **新增北向资金告警检查编排**：
   ```python
   def run_northbound_alert_checks(date: str, northbound_data: dict | None,
                                     alert_type: str, report_path: "Path") -> list[dict]:
       """检查北向资金告警：check_northbound_alert → 去重 → 写文件 → 标记。
       
       去重使用 alerts.log，符号标记为 "NORTHBOUND"（与指数告警共用去重机制）。
       """
   ```
   - 去重逻辑：复用 `_load_alerted` / `_mark_alerted`，符号用 `"NORTHBOUND"` 常量
   - 告警文件名：`alerts/YYYY-MM-DD-northbound-{alert_type}.md`（与指数告警文件名区分）
   - 去重与指数告警独立：`NORTHBOUND` 标记不影响 `SH`/`GSPC` 等的去重

4. **修改 `collect_breaches`**：
   - 不需要修改——北向资金不走 `check_breach`，它有自己的检查链

**注意事项**：
- 北向资金告警文件名用 `northbound-close` 而非 `close`，避免与指数告警文件碰撞
- `alerts.log` 中北向资金标记为 `NORTHBOUND`，与指数 SYMBOLS 命名空间不冲突
- 告警消息格式：`💰 北向资金异动：今日净流入 135.20 亿元`

**验证**：运行现有测试：`venv/Scripts/python -m pytest tests/test_alerter.py -v`

---

### 步骤 6：`src/reporter.py` — 日报模板增加北向资金行

**文件**：`src/reporter.py`

**改动**：

1. **导入**：
   ```python
   from .analyzer import fmt_northbound
   ```

2. **`render_report` 函数签名增加参数**：
   ```python
   def render_report(..., northbound=None, ...) -> str:
   ```
   - `northbound`：`dict | None`，格式 `{"net_inflow": float, "sh_net": float, "sz_net": float}`

3. **在 A 股大盘表格中增加北向资金行**：
   - 位置：在 `a_share_table` 最后一行（CYB 行）之后
   - 格式（PRD 附录定义）：
     ```markdown
     | **北向资金** | **净流入 32.15 亿元** | 沪股通 +18.20 / 深股通 +13.95 |
     ```
   - 数据缺失时显示：
     ```markdown
     | **北向资金** | **数据暂缺（接口限制）** | — |
     ```

4. **格式化逻辑**：
   - 正值：`净流入 X.XX 亿元`（绿色/正号）
   - 负值：`净流出 X.XX 亿元`（红色/负号）
   - 零值：`净流入 0.00 亿元`
   - None：`数据暂缺（接口限制）`
   - 沪股通/深股通格式：`沪股通 +18.20 / 深股通 +13.95`

5. **`generate_context` 增加北向资金键**：
   - payload 中增加：
     ```python
     "northbound": northbound_data,  # None 或 {net_inflow, sh_net, sz_net, date}
     ```
   - 这样 Hermes 可以在解读中引用北向资金数据

**注意事项**：
- 北向资金行在 A 股大盘表格**内部**（不是独立板块），与 PRD 附录一致
- `render_snapshot`（快照）不增加北向资金行（PRD 只要求日报）
- 占位文案用中文「数据暂缺（接口限制）」与项目风格一致

**验证**：运行现有测试：`venv/Scripts/python -m pytest tests/test_reporter.py -v`

---

### 步骤 7：`daily_report.py` — 编排入口调用北向资金模块

**文件**：`daily_report.py`

**改动**：

1. **导入**：
   ```python
   from src.northbound import fetch_northbound_flow
   from src.alerter import run_northbound_alert_checks
   ```

2. **在 `main()` 中调用北向资金获取**：
   - 位置：在 `fetch_all()` 之后、`render_report()` 之前
   - 独立 try/except 包裹，失败不影响主流程：
     ```python
     northbound_data = None
     try:
         northbound_data = fetch_northbound_flow(date)
     except Exception as exc:
         log.warning("北向资金获取失败，跳过: %s", exc)
     ```

3. **传入 `render_report`**：
   ```python
   report = render_report(..., northbound=northbound_data, ...)
   ```

4. **北向资金告警检查**：
   - 位置：在现有 `run_alert_checks` 之后（告警独立）
   - 独立 try/except：
     ```python
     try:
         run_northbound_alert_checks(date, northbound_data, "close", report_path)
     except Exception as exc:
         log.warning("北向资金告警检查失败，不影响日报: %s", exc)
     ```

5. **历史记录增加北向资金字段**：
   ```python
   record = {
       "date": date,
       **{k.lower(): values[k] for k in SYMBOLS},
       "northbound": northbound_data["net_inflow"] if northbound_data else None,
       "sh_net": northbound_data["sh_net"] if northbound_data else None,
       "sz_net": northbound_data["sz_net"] if northbound_data else None,
   }
   ```

6. **context 生成传入北向资金**：
   ```python
   generate_context(..., northbound=northbound_data, ...)
   ```

**注意事项**：
- 北向资金获取失败 → `northbound_data = None` → 报告显示「数据暂缺」→ 历史存 null → context 中 `northbound: null`
- 不改变现有退出码逻辑（恒为 0）
- 北向资金获取与指数取数**串行**（不并行），避免额外线程复杂度

**验证**：`venv/Scripts/python daily_report.py`

---

### 步骤 8：`tests/test_northbound.py` — 单元测试

**文件**：`tests/test_northbound.py`（新建）

**测试用例**：

1. **`test_fetch_northbound_flow_success`**：mock adata 返回有效数据，断言返回格式正确
2. **`test_fetch_northbound_flow_empty`**：mock adata 返回空 DataFrame，断言返回 None
3. **`test_fetch_northbound_flow_exception`**：mock adata 抛异常，断言返回 None 不抛
4. **`test_fetch_northbound_flow_non_trading_day`**：非交易日场景（可选）
5. **`test_check_northbound_alert_above_threshold`**：净流入超阈值，返回告警 dict
6. **`test_check_northbound_alert_below_threshold`**：净流入低于阈值，返回 None
7. **`test_check_northbound_alert_equal_threshold`**：恰好等于阈值，返回 None（严格大于）
8. **`test_check_northbound_alert_none_data`**：数据为 None，返回 None
9. **`test_northbound_alert_dedup`**：同一天不重复告警（复用 alerts.log 机制）
10. **`test_northbound_in_report`**：render_report 包含北向资金行
11. **`test_northbound_in_context`**：generate_context 包含 northbound 键

**测试风格**：
- 遵循项目既有风格：纯函数测试 + monkeypatch 路径常量
- mock 落点在**使用方模块**（如 mock `src.northbound.adata`）
- conftest.py 已隔离 CONFIG_PATH，测试用内置默认阈值

**验证**：`venv/Scripts/python -m pytest tests/test_northbound.py -v`

---

### 步骤 9：`.env.example` — 增加北向资金配置说明

**文件**：`.env.example`

**改动**：追加注释行：
```
# 北向资金告警阈值（亿元，净流入绝对值超过此值触发告警，默认 100）
# ALERT_NORTHBOUND_THRESHOLD=100
```

**验证**：无（仅文档）

---

### 步骤 10：全量回归验证

**验证命令**：
```bash
# 1. 安装依赖
venv/Scripts/pip install -r requirements.txt

# 2. 运行全量测试
venv/Scripts/python -m pytest tests/ -v

# 3. 运行日报生成（完整闭环）
venv/Scripts/python daily_report.py

# 4. 检查日报中是否出现北向资金行
# 查看 reports/YYYY-MM-DD.md 中 A 股大盘表格

# 5. 模拟北向资金超阈值告警（可选，需修改 last_values 或手动触发）
```

---

## 实施顺序与依赖关系

```
步骤 1 (requirements.txt)
  ↓
步骤 2 (config.py)  ←  无依赖，可与步骤 1 并行
  ↓
步骤 3 (northbound.py)  ←  依赖步骤 1（adata 已安装）
  ↓
步骤 4 (analyzer.py)  ←  依赖步骤 2（config 键已定义）
  ↓
步骤 5 (alerter.py)  ←  依赖步骤 4（check_northbound_alert）
  ↓
步骤 6 (reporter.py)  ←  依赖步骤 4（fmt_northbound）
  ↓
步骤 7 (daily_report.py)  ←  依赖步骤 3/5/6
  ↓
步骤 8 (tests)  ←  依赖步骤 3/4/5/6
  ↓
步骤 9 (.env.example)  ←  无依赖
  ↓
步骤 10 (全量回归)
```

## 风险与注意事项

| 风险 | 应对 |
|---|---|
| adata API 接口签名与文档不符 | 实测确认后再写代码；若 adata 不可用，降级返回 None |
| 北向资金数据为 0（节假日） | 判断是否为交易日；若休市返回 0 或 None，报告显示「休市」 |
| 北向资金告警阈值 100 亿过于敏感 | 支持 env 覆盖，用户可调整 |
| history.json 增加新键影响旧数据 | 旧记录中键缺失返回 None（`rec.get("northbound")`），不破坏 |
| 测试 mock adata 的方式 | 参考项目既有 mock 模式（monkeypatch / mock.patch） |
| `render_report` 签名变更影响 snapshot | snapshot 不传 northbound 参数（默认 None），零影响 |

## Done When（验收标准）

- [ ] `adata` 已添加到 `requirements.txt` 并可安装
- [ ] `src/northbound.py` 实现 `fetch_northbound_flow()` 函数，返回统一格式
- [ ] 数据获取失败时返回 None，记录日志，不抛出异常
- [ ] `src/reporter.py` 日报模板中在 A 股大盘表格增加「北向资金」行
- [ ] 北向资金数据显示格式正确（净流入/净流出 + 亿元）
- [ ] `src/alerter.py` 增加北向资金独立告警
- [ ] 阈值支持环境变量覆盖：`ALERT_NORTHBOUND_THRESHOLD=80`
- [ ] `tests/test_northbound.py` 覆盖成功和失败场景
- [ ] `pytest tests/ -v` 全绿
- [ ] `python daily_report.py` 日报中出现北向资金行
