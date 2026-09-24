"""告警层：告警文件渲染、去重状态（alerts.log）读写、检查编排。

告警文件 alerts/YYYY-MM-DD-{type}.md（type = noon / close），多指数同日触发时各占
一个附录块（frontmatter + 标题 + 字段）。alerts.log 行式记录 "YYYY-MM-DD SYMBOL"，
每次写入原子重写为仅当日行。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .analyzer import ALERTS_DIR, ALERTS_LOG, check_breach
from .config import load_config
from .fetcher import SYMBOLS, ALT_SYMBOLS

log = logging.getLogger("marketpulse")

#: 告警块起始（`render_alert` 输出的 frontmatter 前四行；symbol 值随后单独捕获）。
_BLOCK_HEAD = "---\ntype: %s\ndate: %s\nsymbol: "


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


def _read_existing_blocks(path: Path, date: str, alert_type: str) -> "tuple[dict[str, str], list[str]]":
    """读回同 `(date, alert_type)` 告警文件的既有块 → ({symbol: 块文本}, 其它内容片段)。

    ⚠️ 2026-09-24（BUG-006）：文件是「多块 Markdown 顺序拼接」的既有格式（块 = frontmatter
    `---/type/date/symbol` + 标题 + 字段），这里按 frontmatter 定界切回块。
    **除块以外的任何内容**（人工加的分隔符/尾注、半截块、格式不符的块）原样收进 fragments，
    绝不丢；文件缺失/读不到 → 空结果（按「无既有块」处理，调用方仍会正常新建）。
    """
    if not path.exists():
        return {}, []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("告警文件读回失败，按无既有块处理: %s", exc)
        return {}, []
    pattern = re.compile(
        re.escape(_BLOCK_HEAD % (alert_type, date)) + r"(?P<symbol>[^\n]+)\n.*?(?=\n---\ntype: |\Z)",
        re.S,
    )
    blocks: dict[str, str] = {}
    fragments: list[str] = []
    pos = 0
    for match in pattern.finditer(text):
        gap = text[pos:match.start()]
        if gap.strip():
            fragments.append(gap.strip("\n"))
        blocks[match.group("symbol")] = match.group(0)
        pos = match.end()
    tail = text[pos:]
    if tail.strip():
        fragments.append(tail.strip("\n"))
    return blocks, fragments


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
    # ⚠️ 2026-09-24（BUG-006）：原来**只用 pending 整段重写**文件 —— 同日同 type 重跑且触发集合
    #    变化时，上一次写入的块被抹掉；而 alerts.log 已把该 symbol 记成「当日已告警」（不再补写）
    #    ⇒ 那条告警当日**永久丢失**。改为写前读回既有块，按 symbol 合并后再写（同 symbol 以本次
    #    渲染为准；既有顺序保留，新块追加）。文件里块以外的内容（分隔符/尾注）原样保留。
    merged, fragments = _read_existing_blocks(path, date, alert_type)
    for alert in pending:
        merged[alert["symbol"]] = render_alert(alert, date, alert_type, report_path)
    text = "\n".join(merged.values())
    if fragments:
        text += "\n" + "\n".join(fragments)
    path.write_text(text, encoding="utf-8")
    _mark_alerted(date, alerted | {a["symbol"] for a in pending})
    log.info("告警文件已生成: %s（%d 项 / 文件共 %d 块）", path, len(pending), len(merged))
    return pending

