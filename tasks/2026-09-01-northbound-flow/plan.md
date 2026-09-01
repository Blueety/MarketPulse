# 北向资金监控 — 实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 为 MarketPulse 增加北向资金（沪深港通）日度监控，日报展示 + 异常告警。

**Architecture:** 新建 `src/northbound.py` 独立模块（多源降级链：adata → akshare fallback → 返回 None），通过 `fetch_all()` 附加调用获取数据。告警、报告、去重复用现有框架扩展。

**Tech Stack:** adata（主源）、pandas（adata 依赖）、akshare（备用）、pytest（测试）

---

## Task 1: 依赖安装

**Objective:** 安装 adata 和 pandas 到 requirements.txt

**Files:**
- Modify: `requirements.txt`

**Step 1: 安装 adata 和 pandas**

```bash
cd D:/AGENT/MarketPulse
venv/Scripts/pip install adata pandas
```

**Step 2: 冻结依赖到 requirements.txt**

```bash
venv/Scripts/pip freeze > requirements.txt
```

或手动在 requirements.txt 追加：
```
adata>=0.2.0
pandas>=2.0.0
```

**Step 3: 验证安装**

```bash
venv/Scripts/python -c "import adata; import pandas; print('OK')"
```

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add adata and pandas dependencies for northbound flow"
```

---

## Task 2: 北向资金获取模块（TDD）

**Objective:** 创建 `src/northbound.py`，实现多源降级获取北向资金数据

**Files:**
- Create: `src/northbound.py`
- Create: `tests/test_northbound.py`

### 步骤 1: 编写失败测试

创建 `tests/test_northbound.py`：

```python
"""北向资金模块单元测试。"""
from unittest.mock import patch, MagicMock
import pandas as pd


class TestFetchNorthboundFlow:
    """fetch_northbound_flow() 核心测试。"""

    def test_returns_dict_with_required_fields(self):
        """成功获取时返回格式正确的 dict。"""
        from src.northbound import fetch_northbound_flow, NorthboundData
        result = fetch_northbound_flow()
        # 无论实际是否获取到数据，返回值要么是 NorthboundData 要么是 None
        if result is not None:
            assert isinstance(result, dict)
            assert "net_inflow" in result
            assert "sh_net" in result
            assert "sz_net" in result
            assert "date" in result
            assert "source" in result

    def test_returns_none_on_all_failure(self):
        """所有数据源失败时返回 None。"""
        from src.northbound import fetch_northbound_flow
        with patch("src.northbound._fetch_from_adata", return_value=None), \
             patch("src.northbound._fetch_from_akshare_fallback", return_value=None):
            result = fetch_northbound_flow()
            assert result is None

    def test_adata_success(self):
        """adata 成功获取数据时返回 NorthboundData。"""
        from src.northbound import fetch_northbound_flow
        fake_data = {
            "net_inflow": 32.15,
            "sh_net": 18.20,
            "sz_net": 13.95,
            "date": "2026-09-01",
            "source": "adata",
        }
        with patch("src.northbound._fetch_from_adata", return_value=fake_data):
            with patch("src.northbound._fetch_from_akshare_fallback", return_value=None):
                result = fetch_northbound_flow()
                assert result is not None
                assert result["net_inflow"] == 32.15
                assert result["sh_net"] == 18.20
                assert result["sz_net"] == 13.95
                assert result["source"] == "adata"

    def test_akshare_fallback(self):
        """adata 失败时降级到 akshare。"""
        from src.northbound import fetch_northbound_flow
        fake_data = {
            "net_inflow": -12.50,
            "sh_net": -8.30,
            "sz_net": -4.20,
            "date": "2026-09-01",
            "source": "akshare",
        }
        with patch("src.northbound._fetch_from_adata", return_value=None), \
             patch("src.northbound._fetch_from_akshare_fallback", return_value=fake_data):
            result = fetch_northbound_flow()
            assert result is not None
            assert result["source"] == "akshare"

    def test_format_net_inflow_positive(self):
        """正净流入格式化。"""
        from src.northbound import format_northbound
        result = format_northbound({"net_inflow": 32.15, "sh_net": 18.20, "sz_net": 13.95})
        assert "净流入" in result
        assert "32.15" in result
        assert "18.20" in result
        assert "13.95" in result

    def test_format_net_inflow_negative(self):
        """负净流出格式化。"""
        from src.northbound import format_northbound
        result = format_northbound({"net_inflow": -12.50, "sh_net": -8.30, "sz_net": -4.20})
        assert "净流出" in result
        assert "12.50" in result

    def test_format_none(self):
        """None 输入格式化为数据暂缺。"""
        from src.northbound import format_northbound
        result = format_northbound(None)
        assert "数据暂缺" in result

    def test_check_northbound_breach_over_threshold(self):
        """超过阈值时返回告警 dict。"""
        from src.northbound import check_northbound_breach
        alert = check_northbound_breach(135.20, threshold=100.0)
        assert alert is not None
        assert alert["abs_inflow"] == 135.20
        assert alert["direction"] == "净流入"

    def test_check_northbound_breach_under_threshold(self):
        """未超阈值时返回 None。"""
        from src.northbound import check_northbound_breach
        alert = check_northbound_breach(50.0, threshold=100.0)
        assert alert is None

    def test_check_northbound_breach_negative_over_threshold(self):
        """负净流出超阈值时返回告警 dict。"""
        from src.northbound import check_northbound_breach
        alert = check_northbound_breach(-120.0, threshold=100.0)
        assert alert is not None
        assert alert["abs_inflow"] == 120.0
        assert alert["direction"] == "净流出"
```

### 步骤 2: 运行测试确认失败

```bash
cd D:/AGENT/MarketPulse
venv/Scripts/python -m pytest tests/test_northbound.py -v
```

预期：全部 FAIL（ImportError）

### 步骤 3: 实现 `src/northbound.py`

```python
"""北向资金（沪深港通）获取模块。

多源降级链：adata → akshare fallback → 返回 None。
所有源均失败时返回 None，记录日志，不抛出异常。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from time import monotonic

from .config import env_float

log = logging.getLogger("marketpulse")

# 默认告警阈值（亿元）
DEFAULT_NORTHBOUND_THRESHOLD = 100.0
NORTHBOUND_TIMEOUT = 15  # 单源请求超时（秒）


def _get_threshold() -> float:
    """获取北向资金告警阈值（亿元），支持环境变量覆盖。"""
    return env_float("ALERT_NORTHBOUND_THRESHOLD", DEFAULT_NORTHBOUND_THRESHOLD)


def _fetch_from_adata() -> dict | None:
    """数据源 1：adata（免费，无需 API Key）。

    返回 {"net_inflow", "sh_net", "sz_net", "date", "source"} 或 None。
    """
    try:
        from adata.stock.market import market_hsgt
        df = market_hsgt()
        if df is None or df.empty:
            log.info("adata 北向资金返回空数据")
            return None

        # 取最新一行
        row = df.iloc[-1]
        date_str = str(row.get("date", datetime.now().strftime("%Y-%m-%d")))
        # adata 字段名可能为 net_inflow / sh_net / sz_net，具体以实际返回为准
        net_inflow = float(row.get("net_inflow", row.get("net_buy", 0)))
        sh_net = float(row.get("sh_net", row.get("net_buy_sh", 0)))
        sz_net = float(row.get("sz_net", row.get("net_buy_sz", 0)))

        # 验证数据有效性（非全零才认为有效）
        if net_inflow == 0 and sh_net == 0 and sz_net == 0:
            log.info("adata 北向资金全为 0，视为无效")
            return None

        return {
            "net_inflow": net_inflow,
            "sh_net": sh_net,
            "sz_net": sz_net,
            "date": date_str,
            "source": "adata",
        }
    except ImportError:
        log.info("adata 未安装，跳过")
        return None
    except Exception as exc:
        log.warning("adata 北向资金获取失败: %s", exc)
        return None


def _fetch_from_akshare_fallback() -> dict | None:
    """数据源 2：akshare fallback（stock_hsgt_hist_em）。

    ⚠ 2024年8月后该接口可能返回全 0，仅作为备用。
    """
    try:
        import akshare as ak
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            log.info("akshare 北向资金返回空数据")
            return None

        row = df.iloc[-1]
        date_str = str(row.get("日期", datetime.now().strftime("%Y-%m-%d")))
        net_inflow = float(row.get("当日净流入", row.get("当日资金流入", 0)))

        # akshare 可能没有分沪/深的字段，用 0 占位
        sh_net = float(row.get("沪股通净流入", 0))
        sz_net = float(row.get("深股通净流入", 0))

        if net_inflow == 0 and sh_net == 0 and sz_net == 0:
            log.info("akshare 北向资金全为 0，视为无效（政策限制）")
            return None

        return {
            "net_inflow": net_inflow,
            "sh_net": sh_net,
            "sz_net": sz_net,
            "date": date_str,
            "source": "akshare",
        }
    except ImportError:
        log.info("akshare 未安装，跳过")
        return None
    except Exception as exc:
        log.warning("akshare 北向资金获取失败: %s", exc)
        return None


def fetch_northbound_flow() -> dict | None:
    """获取北向资金日度数据（多源降级链）。

    返回 {"net_inflow", "sh_net", "sz_net", "date", "source"} 或 None。
    所有源失败 → 返回 None，不抛出异常。
    """
    # 降级链：adata → akshare
    for fetcher in [_fetch_from_adata, _fetch_from_akshare_fallback]:
        result = fetcher()
        if result is not None:
            log.info("北向资金获取成功 [%s]: 净流入 %.2f 亿元",
                     result["source"], result["net_inflow"])
            return result

    log.warning("北向资金所有数据源均失败，返回 None")
    return None


def format_northbound(data: dict | None) -> str:
    """格式化北向资金为 Markdown 表格行。

    返回如：净流入 32.15 亿元（沪股通 +18.20 / 深股通 +13.95）
    或：数据暂缺
    """
    if data is None:
        return "数据暂缺"

    net = data["net_inflow"]
    sh = data["sh_net"]
    sz = data["sz_net"]

    if net > 0:
        direction = "净流入"
        sign = "+"
    elif net < 0:
        direction = "净流出"
        sign = ""
        net = abs(net)
        sh = abs(sh)
        sz = abs(sz)
    else:
        direction = "持平"
        sign = ""

    return (
        f"{direction} {net:.2f} 亿元"
        f"（沪股通 {sign}{sh:.2f} / 深股通 {sign}{sz:.2f}）"
    )


def check_northbound_breach(net_inflow: float, threshold: float | None = None) -> dict | None:
    """判断北向资金净流入是否超过告警阈值。

    超过阈值返回 {"abs_inflow", "direction", "net_inflow", "threshold"}；
    未超过返回 None。
    """
    if threshold is None:
        threshold = _get_threshold()

    abs_val = abs(net_inflow)
    if abs_val <= threshold:
        return None

    direction = "净流入" if net_inflow > 0 else "净流出"
    return {
        "abs_inflow": abs_val,
        "direction": direction,
        "net_inflow": net_inflow,
        "threshold": threshold,
    }
```

### 步骤 4: 运行测试确认通过

```bash
cd D:/AGENT/MarketPulse
venv/Scripts/python -m pytest tests/test_northbound.py -v
```

预期：全部 PASS

### 步骤 5: Commit

```bash
git add src/northbound.py tests/test_northbound.py
git commit -m "feat: add northbound flow module with multi-source fallback"
```

---

## Task 3: 集成到数据获取层

**Objective:** 在 `daily_report.py` 中调用北向资金获取，数据传入报告和告警

**Files:**
- Modify: `daily_report.py`

**Step 1: 在 main() 中增加北向资金调用**

在 `daily_report.py` 的 `main()` 函数中，在 `fetch_all()` 之后添加：

```python
from src.northbound import fetch_northbound_flow

# 在 values, errors = fetch_all() 之后
northbound = fetch_northbound_flow()
```

**Step 2: 将 northbound 传入 render_report**

修改 `render_report()` 调用，增加 `northbound=northbound` 参数。

**Step 3: 将 northbound 传入告警检查**

在 `run_alert_checks` 调用前后，增加北向资金告警逻辑。

**Step 4: 验证**

```bash
venv/Scripts/python -c "from src.northbound import fetch_northbound_flow; print(fetch_northbound_flow())"
```

**Step 5: Commit**

```bash
git add daily_report.py
git commit -m "feat: integrate northbound flow into daily report"
```

---

## Task 4: 报告渲染集成

**Objective:** 在日报 A 股大盘表格下方增加北向资金行

**Files:**
- Modify: `src/reporter.py`

**Step 1: 修改 render_report 函数签名**

增加 `northbound=None` 参数。

**Step 2: 在 A 股大盘表格后插入北向资金行**

在 `a_share_table` 渲染之后，添加北向资金行：

```python
# 北向资金行
nb_row = ""
if northbound is not None or True:  # 始终显示（有数据或"数据暂缺"）
    from .northbound import format_northbound
    nb_text = format_northbound(northbound)
    nb_row = f"| **北向资金** | **{nb_text}** | — | — |"
```

在 body 模板中，在 `{a_share_table}` 之后插入 `{nb_row}`。

**Step 3: 验证**

```bash
venv/Scripts/python daily_report.py
```

检查 `reports/YYYY-MM-DD.md` 中是否出现"北向资金"行。

**Step 4: Commit**

```bash
git add src/reporter.py
git commit -m "feat: add northbound flow row to A-share section of report"
```

---

## Task 5: 告警集成

**Objective:** 增加北向资金独立告警逻辑

**Files:**
- Modify: `src/alerter.py`

**Step 1: 添加北向资金告警检查函数**

在 `src/alerter.py` 中添加：

```python
def run_northbound_alert(date: str, northbound: dict | None,
                         alert_type: str, report_path: "Path") -> list[dict]:
    """北向资金独立告警：净流入超阈值时触发，与现有指数告警分开记录。"""
    from .northbound import check_northbound_breach, _get_threshold

    if northbound is None:
        return []

    threshold = _get_threshold()
    breach = check_northbound_breach(northbound["net_inflow"], threshold)
    if breach is None:
        return []

    # 去重：复用 alerts.log，key 用 "NORTHBOUND"
    alerted = _load_alerted(date)
    if "NORTHBOUND" in alerted:
        log.info("北向资金当日已告警，跳过")
        return []

    # 渲染告警
    direction = breach["direction"]
    abs_val = breach["abs_inflow"]
    alert_msg = (
        f"---\n"
        f"type: {alert_type}\n"
        f"date: {date}\n"
        f"symbol: NORTHBOUND\n"
        f"level: WARN\n"
        f"---\n\n"
        f"## 💰 北向资金异动\n\n"
        f"- 方向：**{direction}**\n"
        f"- 金额：{abs_val:.2f} 亿元（阈值 {threshold:.0f} 亿元）\n"
        f"- 沪股通：{northbound['sh_net']:.2f} 亿元\n"
        f"- 深股通：{northbound['sz_net']:.2f} 亿元\n"
        f"- 数据来源：{northbound['source']}\n"
        f"- 相关报告：{report_path.name}\n"
    )

    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ALERTS_DIR / f"{date}-northbound-{alert_type}.md"
    path.write_text(alert_msg, encoding="utf-8")

    _mark_alerted(date, alerted | {"NORTHBOUND"})
    log.info("北向资金告警已生成: %s", path)
    return [breach]
```

**Step 2: 在 daily_report.py 中调用**

在 `run_alert_checks` 之后添加：

```python
try:
    from src.alerter import run_northbound_alert
    run_northbound_alert(date, northbound, "close", report_path)
except Exception as exc:
    log.warning("北向资金告警检查失败: %s", exc)
```

**Step 3: 验证**

模拟超阈值数据测试：

```bash
venv/Scripts/python -c "
from src.alerter import run_northbound_alert
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
nb = {'net_inflow': 135.20, 'sh_net': 80.10, 'sz_net': 55.10, 'date': date, 'source': 'test'}
run_northbound_alert(date, nb, 'close', Path('reports/test.md'))
print('告警文件已生成')
"
```

**Step 4: Commit**

```bash
git add src/alerter.py daily_report.py
git commit -m "feat: add northbound alert with dedup"
```

---

## Task 6: 配置与环境变量

**Objective:** 增加北向资金相关配置到 config 和 .env.example

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`

**Step 1: 在 DEFAULTS 中增加北向资金配置**

在 `src/config.py` 的 `DEFAULTS` 字典中添加：

```python
"northbound": {"alert_threshold": 100.0},
```

**Step 2: 在 ENV_MAP 中增加环境变量映射**

```python
"ALERT_NORTHBOUND_THRESHOLD": ("northbound", "alert_threshold"),
```

**Step 3: 更新 .env.example**

```
# 北向资金告警阈值（亿元，超过此值触发告警）
# ALERT_NORTHBOUND_THRESHOLD=100
```

**Step 4: 更新 northbound.py 中的 _get_threshold()**

改为从 config 读取：

```python
def _get_threshold() -> float:
    """获取北向资金告警阈值（亿元），支持环境变量覆盖。"""
    from .config import load_config
    cfg = load_config()
    default = cfg.get("northbound", {}).get("alert_threshold", 100.0)
    return env_float("ALERT_NORTHBOUND_THRESHOLD", default)
```

**Step 5: 验证**

```bash
venv/Scripts/python -c "from src.config import load_config; print(load_config().get('northbound'))"
```

**Step 6: Commit**

```bash
git add src/config.py .env.example src/northbound.py
git commit -m "feat: add northbound config and env var support"
```

---

## Task 7: 全量测试

**Objective:** 运行全部测试确保无回归

**Step 1: 运行全部测试**

```bash
cd D:/AGENT/MarketPulse
venv/Scripts/python -m pytest tests/ -v
```

预期：全部 PASS（包括 test_northbound.py 和既有测试）

**Step 2: 运行日报验证**

```bash
venv/Scripts/python daily_report.py
```

检查输出中是否包含"北向资金"相关日志。

**Step 3: 检查报告文件**

```bash
ls -la reports/$(date +%Y-%m-%d).md
```

确认报告中包含"北向资金"行。

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: northbound flow feature complete, all tests pass"
```

---

## Task 8: 更新 AGENTS.md

**Objective:** 更新项目文档

**Files:**
- Modify: `AGENTS.md`

**Step 1: 在 Project Map 中增加 northbound 模块说明**

```
- `src/northbound.py`: 北向资金获取模块（多源降级：adata → akshare fallback → None）+ 格式化 + 告警判断。
```

**Step 2: 在 tasks/ 下写 journal**

创建 `tasks/2026-09-01-northbound-flow/journal.md`，记录改动。

**Step 3: Commit**

```bash
git add AGENTS.md tasks/2026-09-01-northbound-flow/
git commit -m "docs: update AGENTS.md with northbound module"
```

---

## 风险与回退

| 风险 | 应对 |
|:---|:---|
| adata 接口变更 | 降级到 akshare；最终降级到"数据暂缺" |
| akshare 返回全 0 | 判断全零视为无效，返回 None |
| 告警误触发 | 支持 `ALERT_NORTHBOUND_THRESHOLD` 环境变量覆盖 |
| 新依赖安装失败 | adata/pandas 为可选依赖，缺失时 graceful skip |
