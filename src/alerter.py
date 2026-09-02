"""告警层：告警文件渲染、去重状态（alerts.log）读写、检查编排。

告警文件 alerts/YYYY-MM-DD-{type}.md（type = noon / close），多指数同日触发时各占
一个附录块（frontmatter + 标题 + 字段）。alerts.log 行式记录 "YYYY-MM-DD SYMBOL"，
每次写入原子重写为仅当日行。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .analyzer import ALERTS_DIR, ALERTS_LOG, check_breach
from .config import load_config
from .fetcher import SYMBOLS, ALT_SYMBOLS

log = logging.getLogger("marketpulse")


def _load_alerted(date: str) -> set[str]:
    """读取当日已告警的 symbol 集合；文件缺失/损坏按空处理。"""
    if not ALERTS_LOG.exists():
        return set()
    try:
        lines = ALERTS_LOG.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("alerts.log 读取失败，按空处理: %s", exc)
        return set()
    return {line.split(" ", 1)[1] for line in lines if line.startswith(date + " ")}


def _mark_alerted(date: str, symbols: set[str]) -> None:
    """原子重写 alerts.log 为仅当日已告警行（旧日行自动清除）。"""
    ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(f"{date} {sym}" for sym in symbols)
    tmp = ALERTS_LOG.with_name(ALERTS_LOG.name + ".tmp")
    tmp.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    os.replace(tmp, ALERTS_LOG)


def render_alert(alert: dict, date: str, alert_type: str, report_path: "Path") -> str:
    """渲染单个告警附录块（frontmatter + 标题 + 字段），返回完整块文本。"""
    meta = SYMBOLS[alert["symbol"]]
    return (
        "---\n"
        f"type: {alert_type}\n"
        f"date: {date}\n"
        f"symbol: {alert['symbol']}\n"
        f"level: {alert['level']}\n"
        "---\n\n"
        f"## ⚠️ {meta['label']}告警\n\n"
        f"- 级别：**{alert['level']}**\n"
        f"- 当前值：{alert['current']:.2f}\n"
        f"- 昨日收盘：{alert['last']:.2f}\n"
        f"- 变化率：{alert['change']:+.2f}%（阈值 ±{alert['threshold']:.1f}%）\n"
        f"- 市场状态：{alert['state']}\n"
        f"- 建议：{alert['suggestion']}\n"
        f"- 相关报告：{report_path.name}\n"
    )


def collect_breaches(values: dict, last_values: dict, history: list[dict] | None = None) -> list[dict]:
    """纯计算：遍历 SYMBOLS 调 check_breach 收集告警 dict，不写文件、不改 alerts.log（幂等）。

    run_alert_checks 与 generate_context 共用的单一事实来源；单指数异常仅记日志跳过。
    history 透传给 check_breach 以支持动态阈值（不传则回退固定阈值）。"""
    breaches = []
    for sym in SYMBOLS:
        if sym in ALT_SYMBOLS:
            continue
        try:
            alert = check_breach(sym, values.get(sym), last_values.get(sym), history)
        except Exception as exc:
            log.warning("告警检查 %s 失败: %s", sym, exc)
            continue
        if alert is not None:
            breaches.append(alert)
    return breaches


def run_alert_checks(date: str, values: dict, last_values: dict,
                     alert_type: str, report_path: "Path",
                     history: list[dict] | None = None) -> list[dict]:
    """检查各指数告警：check_breach → 当日去重过滤 → 写文件 → 标记已告警。

    单指数异常仅记日志；调用方应再包 try/except（决策 H）。返回本次触发的告警列表。
    history 透传给 collect_breaches（动态阈值窗口，不含候选当日）。"""
    alerted = _load_alerted(date)
    pending = []
    for alert in collect_breaches(values, last_values, history):
        if alert["symbol"] in alerted:
            log.info("%s 当日已告警（alerts.log），跳过", alert["symbol"])
            continue
        pending.append(alert)
    if not pending:
        return []
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ALERTS_DIR / f"{date}-{alert_type}.md"
    path.write_text(
        "\n".join(render_alert(a, date, alert_type, report_path) for a in pending),
        encoding="utf-8",
    )
    _mark_alerted(date, alerted | {a["symbol"] for a in pending})
    log.info("告警文件已生成: %s（%d 项）", path, len(pending))
    return pending

