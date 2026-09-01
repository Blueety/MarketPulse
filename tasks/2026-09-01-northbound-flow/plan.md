# 北向资金监控功能 — 执行计划

## 目标

为 MarketPulse 增加 A 股北向资金（沪深港通）监控能力，在每日日报中展示当日北向资金净流入/流出数据，并在异常流入（如单日净流入超 100 亿）时触发独立告警。

---

## 核心约束（贯穿所有步骤）

- **容错第一**：北向数据获取失败时，报告中显示「数据暂缺」，**不中断日报生成**
- **无需 API Key**：优先使用 `adata`（免费）
- **告警独立**：北向资金告警与现有 VIX/大盘告警分开记录和推送
- **不引入新设计模式**：复用现有降级容错（try/except + log + 静默跳过）

---

## 涉及文件清单

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `requirements.txt` | **修改** | 增加 `adata` |
| `src/northbound.py` | **新建** | 北向资金获取模块，含多源降级逻辑 |
| `src/fetcher.py` | **修改** | 在 `daily_report.py` 调用链中接入北向资金获取 |
| `src/analyzer.py` | **修改** | 北向资金格式化函数 + 告警阈值配置 |
| `src/reporter.py` | **修改** | 日报模板中增加北向资金行 |
| `src/alerter.py` | **修改** | 北向资金独立告警逻辑 |
| `daily_report.py` | **修改** | 编排入口中接入北向资金获取与告警 |
| `tests/test_northbound.py` | **新建** | 北向资金模块单元测试 |
| `.env.example` | **修改** | 增加北向资金告警阈值配置说明 |
| `config.json` | **修改** | 增加 `alert.northbound` 默认阈值 |
| `src/config.py` | **修改** | DEFAULTS + ENV_MAP 增加 northbound 阈值 |

---

## 实施步骤

### 步骤 1：依赖与配置基建

**文件**: `requirements.txt` / `src/config.py` / `config.json` / `.env.example`

1. `requirements.txt` 末尾追加 `adata`
2. `src/config.py` 的 `DEFAULTS["alert"]` 增加 `"northbound": 100.0`
3. `src/config.py` 的 `ENV_MAP` 增加 `"ALERT_NORTHBOUND_THRESHOLD": ("alert", "northbound")`
4. `config.json` 的 `alert` 增加 `"northbound": 100`
5. `.env.example` 追加注释：`# 北向资金告警阈值（单日净流入绝对值超此值触发告警，单位：亿元）`
   `# ALERT_NORTHBOUND_THRESHOLD=100`

**注意事项**:
- `_valid_number` 已排除 bool，northbound 阈值 100 > 0，正常通过
- `load_config()` 返回的 `cfg["alert"]["northbound"]` 可被 env 覆盖

**验证命令**: `cd D:\AGENT\MarketPulse && venv/Scripts/python -c "from src.config import load_config; print(load_config()['alert'])"` 确认含 northbound 键

---

### 步骤 2：新建北向资金获取模块

**文件**: `src/northbound.py`（新建）

核心函数 `fetch_northbound_flow()` 返回 `dict | None`：
```python
{
    "net_inflow": float,     # 北向资金净流入合计（亿元，正=流入 负=流出）
    "sh_net": float,         # 沪股通净流入（亿元）
    "sz_net": float,         # 深股通净流入（亿元）
    "date": str,             # YYYY-MM-DD
}
```
失败返回 `None`（不抛异常）。

**降级链实现**:

```python
def fetch_northbound_flow() -> dict | None:
    """获取北向资金数据，按优先级降级：adata → 返回 None。
    
    所有源失败时返回 None，不抛异常（容错第一）。
    """
    # 1. 尝试 adata
    try:
        data = _fetch_via_adata()
        if data and data.get("net_inflow") is not None:
            return data
    except Exception as exc:
        log.warning("adata 北向资金获取失败: %s", exc)
    
    # 2. 所有源失败
    log.warning("所有北向资金数据源均失败，返回 None")
    return None
```

**`_fetch_via_adata()` 实现要点**:
- `import adata`（函数内懒加载，避免 import 时强依赖）
- adata 的北向资金接口：`adata.stock.market.stock_hsgt_north_net_flow_in_em()`（需确认 API 名）
- 超时：用 `threading.Thread.join(15)` 实现（复用项目 Windows 无 SIGALRM 模式）
- 返回值解析：取最新一日的 `net_buy_amount`（沪+深合计），以及 `sh_net_buy_amount`、`sz_net_buy_amount`
- 字段映射需实测 adata 返回结构后确认
- 若返回空 DataFrame / 值为 0 / 格式不符 → 视为失败，降级到 None

**注意事项**:
- adata 的 API 可能随版本变化，需在安装后实际测试接口名
- 若 adata 接口返回的是历史全量数据，取最新一行（日期为今天或最近交易日）
- 单位：adata 返回值若已是亿元则直接用，若为元需 ÷1e8
- 线程限时超时后线程继续后台运行（daemon），不阻塞主流程

**验证命令**: `cd D:\AGENT\MarketPulse && venv/Scripts/python -c "from src.northbound import fetch_northbound_flow; print(fetch_northbound_flow())"` 确认能返回数据或 None

---

### 步骤 3：修改 fetcher.py 接入北向资金

**文件**: `src/fetcher.py`

**不修改 `fetch_all()`**（它的返回契约是 `tuple[dict, dict]`，北向资金格式不同）。

在 `src/fetcher.py` 顶部新增导入：
```python
from .northbound import fetch_northbound_flow
```

或者**更好的做法**：在 `daily_report.py` 中直接导入 `fetch_northbound_flow`（从 `src.northbound`），不在 `fetcher.py` 中引入依赖。这样 `northbound.py` 完全独立，方便单独测试。

**决定**: 不改 `fetcher.py`，在 `daily_report.py` 中直接导入 `src.northbound.fetch_northbound_flow`。

---

### 步骤 4：修改 daily_report.py 编排入口

**文件**: `daily_report.py`

在 `main()` 中增加北向资金获取逻辑（独立容错）：

```python
from src.northbound import fetch_northbound_flow

# 在 fetch_all() 之后、render_report() 之前：
northbound_data = None
try:
    northbound_data = fetch_northbound_flow()
    if northbound_data:
        log.info("北向资金: 净流入 %.2f 亿元", northbound_data["net_inflow"])
    else:
        log.info("北向资金数据暂缺（所有数据源失败）")
except Exception as exc:
    log.warning("北向资金获取异常（不影响日报）: %s", exc)
    northbound_data = None
```

将 `northbound_data` 传入 `render_report()` 和 `generate_context()`：
```python
report = render_report(..., northbound=northbound_data)
```

将 `northbound_data` 传入北向资金告警检查：
```python
# 在现有 run_alert_checks 之后：
try:
    from src.alerter import check_northbound_alert
    check_northbound_alert(date, northbound_data, report_path)
except Exception as exc:
    log.warning("北向资金告警检查失败（不影响日报）: %s", exc)
```

**注意事项**:
- 北向资金获取失败 = `northbound_data = None`，不影响后续任何流程
- 退出码恒 0（与现有设计一致）

---

### 步骤 5：修改 analyzer.py 增加格式化函数

**文件**: `src/analyzer.py`

新增北向资金相关函数：

```python
def fmt_northbound(data: dict | None) -> str:
    """格式化北向资金显示文本。
    
    返回示例：
    - "净流入 32.15 亿元"（正值）
    - "净流出 12.50 亿元"（负值）
    - "数据暂缺"（None）
    """
    if data is None:
        return "数据暂缺"
    net = data["net_inflow"]
    if net >= 0:
        return f"净流入 {net:.2f} 亿元"
    else:
        return f"净流出 {abs(net):.2f} 亿元"

def fmt_northbound_detail(data: dict | None) -> str:
    """格式化北向资金明细（沪股通/深股通）。
    
    返回示例："沪股通 +18.20 / 深股通 +13.95"
    """
    if data is None:
        return "—"
    sh = data["sh_net"]
    sz = data["sz_net"]
    return f"沪股通 {sh:+.2f} / 深股通 {sz:+.2f}"
```

**注意事项**:
- 函数需有 docstring（项目规范）
- `fmt_value` / `fmt_change` 可复用，但北向资金格式不同，需要独立函数

---

### 步骤 6：修改 reporter.py 日报模板

**文件**: `src/reporter.py`

在 `render_report()` 签名中增加 `northbound=None` 参数。

在 A 股大盘表格**之后**增加北向资金行：

```python
# 在 a_share_table 之后：
northbound_block = ""
if northbound is not None or True:  # 始终显示行，无数据时显示「数据暂缺」
    nb_display = fmt_northbound(northbound)
    nb_detail = fmt_northbound_detail(northbound)
    northbound_block = f"| **北向资金** | **{nb_display}** | {nb_detail} |"
```

在 `body` 模板中 A 股大盘 `a_share_table` 后面插入：
```python
{a_share_table}{northbound_block}{cn_trend_block}
```

**PRD 附录效果**:
```markdown
| **北向资金** | **净流入 32.15 亿元** | 沪股通 +18.20 / 深股通 +13.95 |
```

**注意事项**:
- `northbound=None` 时行仍显示「数据暂缺」（PRD 约束：不中断，但要告知）
- 北向资金行**不是**标准 4 列表格（无涨跌幅/趋势列），需要调整列结构
  - 方案 A：将北向资金行做成独立行，只有 3 列（指数 / 净流入 / 明细），不放入表格
  - 方案 B：北向资金作为 A 股表格的特殊行，但与标准行的 4 列不同
  - **推荐方案 A**：在 A 股表格下方单独一行，用粗体标记，列数与表格一致但内容不同
- 改 `render_report` 输出结构（新增行）需同步回归 `tests/test_reporter.py`
- 同时更新 `generate_context()` 签名，传入 `northbound` 数据并写入 context JSON

---

### 步骤 7：修改 alerter.py 北向资金告警

**文件**: `src/alerter.py`

新增北向资金告警函数（独立于现有指数告警）：

```python
def check_northbound_alert(date: str, northbound_data: dict | None, report_path) -> list[dict]:
    """检查北向资金异动：净流入绝对值超过阈值时触发告警。
    
    独立于 collect_breaches，与 VIX/大盘告警分开记录和推送。
    失败仅记日志（决策 H）。
    """
    if northbound_data is None:
        return []
    
    threshold = load_config()["alert"]["northbound"]  # 默认 100 亿
    net = northbound_data["net_inflow"]
    if abs(net) <= threshold:
        return []
    
    # 当日去重：用 "NORTHBOUND" 作为 symbol 标记
    alerted = _load_alerted(date)
    if "NORTHBOUND" in alerted:
        log.info("北向资金当日已告警，跳过")
        return []
    
    # 生成告警
    direction = "净流入" if net > 0 else "净流出"
    alert_msg = f"💰 北向资金异动：今日{direction} {abs(net):.2f} 亿元"
    
    alert = {
        "symbol": "NORTHBOUND",
        "level": "ALERT",
        "net_inflow": net,
        "sh_net": northbound_data["sh_net"],
        "sz_net": northbound_data["sz_net"],
        "threshold": threshold,
        "message": alert_msg,
    }
    
    # 写告警文件（独立文件，不与指数告警混放）
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ALERTS_DIR / f"{date}-northbound.md"
    path.write_text(
        f"---\ntype: northbound\ndate: {date}\nlevel: ALERT\n---\n\n"
        f"## 💰 北向资金异动告警\n\n"
        f"- 方向：**{direction}**\n"
        f"- 金额：{abs(net):.2f} 亿元\n"
        f"- 沪股通：{northbound_data['sh_net']:+.2f} 亿元\n"
        f"- 深股通：{northbound_data['sz_net']:+.2f} 亿元\n"
        f"- 阈值：{threshold:.0f} 亿元\n"
        f"- 相关报告：{report_path.name}\n",
        encoding="utf-8",
    )
    _mark_alerted(date, alerted | {"NORTHBOUND"})
    log.info("北向资金告警文件已生成: %s", path)
    return [alert]
```

**注意事项**:
- 去重复用现有 `_load_alerted` / `_mark_alerted`，用 `"NORTHBOUND"` 作为 symbol
- 告警文件独立：`alerts/YYYY-MM-DD-northbound.md`，与 `close.md` / `a-share-close.md` 不冲突
- 阈值用 `load_config()["alert"]["northbound"]`，支持 env 覆盖
- 绝对值 `abs(net)` 超阈值才触发（净流入/净出均可）

---

### 步骤 8：修改 generate_context 传入北向资金

**文件**: `src/reporter.py`（`generate_context` 函数）

在 `generate_context` 签名中增加 `northbound=None`，在 payload 中增加：
```python
"northbound": northbound_data,  # dict 或 None
```

在 `daily_report.py` 的 `generate_context` 调用中传入 `northbound=northbound_data`。

---

### 步骤 9：新建单元测试

**文件**: `tests/test_northbound.py`（新建）

测试覆盖：

1. **`test_fetch_northbound_flow_success`**：mock adata 返回有效数据，断言返回结构正确
2. **`test_fetch_northbound_flow_adata_empty`**：mock adata 返回空 DataFrame，断言返回 None
3. **`test_fetch_northbound_flow_adata_error`**：mock adata 抛异常，断言返回 None
4. **`test_fetch_northbound_flow_timeout`**：mock adata 超时，断言返回 None
5. **`test_fmt_northbound_positive`**：正值 → "净流入 X.XX 亿元"
6. **`test_fmt_northbound_negative`**：负值 → "净流出 X.XX 亿元"
7. **`test_fmt_northbound_zero`**：零值 → "净流入 0.00 亿元"
8. **`test_fmt_northbound_none`**：None → "数据暂缺"
9. **`test_fmt_northbound_detail`**：明细格式化
10. **`test_check_northbound_alert_triggered`**：超过阈值 → 生成告警
11. **`test_check_northbound_alert_not_triggered`**：未超阈值 → 无告警
12. **`test_check_northbound_alert_dedup`**：同日重复调用 → 跳过
13. **`test_check_northbound_alert_none_data`**：数据为 None → 跳过

**注意事项**:
- 所有网络调用必须 mock（`monkeypatch`）
- 路径常量 patch 落点：`monkeypatch.setattr(northbound, "ALERTS_DIR", tmp_path / "alerts")`
- 遵循 `tests/conftest.py` 的 CONFIG_PATH 隔离
- 用 `pytest` 运行，覆盖成功和失败场景

**验证命令**: `cd D:\AGENT\MarketPulse && venv/Scripts/python -m pytest tests/test_northbound.py -v`

---

### 步骤 10：回归测试与全流程验证

**验证命令**:

```bash
# 1. 单元测试全绿
cd D:\AGENT\MarketPulse && venv/Scripts/python -m pytest tests/ -v

# 2. 手动测试北向资金模块
venv/Scripts/python -c "from src.northbound import fetch_northbound_flow; print(fetch_northbound_flow())"

# 3. 运行日报，确认北向资金行出现
venv/Scripts/python daily_report.py

# 4. 检查生成的日报中是否含「北向资金」行
grep -i "北向资金" reports/$(date +%Y-%m-%d).md

# 5. 检查 context JSON 中是否含 northbound 键
python -c "import json; d=json.load(open('context/$(date +%Y-%m-%d).json')); print('northbound' in d)"

# 6. 模拟北向资金超过阈值，确认告警文件生成
# （需临时修改 northbound.py 或 mock 数据验证）
```

---

## 实施顺序与依赖关系

```
步骤1（配置基建）
    ↓
步骤2（northbound.py 新建）← 可独立验证
    ↓
步骤5（analyzer.py 格式化）← 无依赖
    ↓
步骤6（reporter.py 模板）← 依赖步骤5
    ↓
步骤7（alerter.py 告警）← 依赖步骤2
    ↓
步骤8（context 传入）← 依赖步骤2
    ↓
步骤4（daily_report.py 编排）← 依赖步骤2/6/7/8
    ↓
步骤9（单元测试）← 依赖步骤2/5/7
    ↓
步骤10（全流程验证）
```

---

## 风险与应对

| 风险 | 应对 |
| :--- | :--- |
| adata API 名称/格式与预期不符 | 实测后调整 `_fetch_via_adata` 解析逻辑；保留降级到 None |
| adata 安装失败或依赖冲突 | requirements.txt 已含 akshare，adata 依赖可能重叠；pip install 时注意 |
| 北向资金表格列数与现有 4 列不一致 | 用独立行（非表格行）渲染，避免破坏 Markdown 表格解析 |
| image_renderer.py 解析破坏 | 北向资金行格式简单（`| **北向资金** | ...`），不匹配现有正则不影响 |
| 北向资金为 0（节假日） | 返回含 0 的数据（不视为 None），报告正常显示「净流入 0.00 亿元」 |
| 告警阈值 100 亿过于敏感 | 支持 env 覆盖 `ALERT_NORTHBOUND_THRESHOLD=80`，用户可调 |

---

## Done When

- [ ] `adata` 已添加到 `requirements.txt`
- [ ] `src/northbound.py` 实现 `fetch_northbound_flow()` 函数，返回统一格式数据
- [ ] 数据获取采用降级链：`adata` → 返回 None
- [ ] 所有数据源失败时，返回 `None`，记录日志，不抛出异常
- [ ] `src/reporter.py` 日报模板中在「A股大盘」表格下方增加「北向资金」行
- [ ] 北向资金数据显示格式：`净流入 32.15 亿元` 或 `净流出 12.50 亿元`
- [ ] `src/alerter.py` 增加北向资金告警：当净流入绝对值超过阈值（默认 100 亿）时触发
- [ ] 告警消息独立推送，格式：`💰 北向资金异动：今日净流入 135.20 亿元`
- [ ] 阈值支持环境变量覆盖：`ALERT_NORTHBOUND_THRESHOLD=80`
- [ ] 所有测试通过（含新增 test_northbound.py）
- [ ] `pytest tests/ -v` 全绿
