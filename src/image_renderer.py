"""日报图片化：Markdown 日报 → 结构化数据 → Jinja2 模板 → imgkit/wkhtmltoimage 转 PNG。

设计为不侵入主流程的容错模块：
- 渲染失败 / 超时 / 缺少 imgkit / wkhtmltoimage 不可用 / md 缺失 → 一律返回 None 并记日志，
  不影响 daily_report.py 主流程与退出码（决策 E）。
- 所有纯函数（parse_report / parse_alerts / _png_dimensions）不依赖 imgkit/wkhtmltoimage，
  可独立测试（Windows 无 SIGALRM，用 daemon 线程 join 实现限时，与趋势图渲染同模式）。
"""

from __future__ import annotations

import logging
import re
import struct
import threading
from pathlib import Path

from .analyzer import ALERTS_DIR, BASE_DIR, IMAGES_DIR, REPORTS_DIR

log = logging.getLogger("marketpulse")

# ---- 固定约束（PRD 定稿，常量化不配置化）----
IMAGE_WIDTH = 600                 # PRD 固定宽度（px）
MAX_IMAGE_BYTES = 800 * 1024      # PRD 文件上限（≤800KB）
RENDER_TIMEOUT = 15               # imgkit 渲染限时（秒），超时跳过
RETRY_ZOOM = 0.8                 # 尺寸超标降级重试缩放

# 索引表章节 → 类别（用于卡片着色与排序，随 md 出现顺序收集）
_INDEX_SECTIONS = (
    ("美股大盘", "us"),
    ("A 股大盘", "a_share"),
    ("波动率指数", "vol"),
    ("另类资产", "alt"),
)

_TIMEOUT = object()  # _run_with_timeout 的超时哨兵


# --------------------------------------------------------------------------- #
# 纯函数：Markdown 解析
# --------------------------------------------------------------------------- #
def parse_report(md_text: str, md_path: "Path | None" = None) -> dict:
    """解析日报 md → 结构化数据（date / cards / charts / interpretation）。

    坏 md（缺日期 / 无表 / 非法内容）不抛异常，返回可渲染的降级结构。
    """
    text = md_text or ""
    data: dict = {
        "date": None,
        "cards": [],
        "charts": [],
        "interpretation": None,
    }

    # 日期：**日期**：2026-08-29（美东时间）
    m = re.search(r"\*\*日期\*\*[:：]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        data["date"] = m.group(1)

    # 按二级标题切分章节
    headings = list(re.finditer(r"(?m)^##\s+(.*)$", text))
    sections: list[tuple[str, str]] = []
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append((h.group(1).strip(), text[start:end]))

    for heading, body in sections:
        kind = next((k for kw, k in _INDEX_SECTIONS if kw in heading), None)
        if kind:
            for row in _parse_index_rows(body):
                label = row[0]
                value = row[1] if len(row) > 1 else ""
                change = row[2] if len(row) > 2 else ""
                trend = row[3] if len(row) > 3 else ""
                data["cards"].append({
                    "label": label,
                    "value": value,
                    "change": change,
                    "trend_or_status": trend,
                    "sign": _sign_from_change(change),
                    "kind": kind,
                })
            continue
        # 解读章节：标题含「解读」（Hermes 追加的 AI 解读契约）
        if "解读" in heading:
            data["interpretation"] = body.strip()

    # 图表：文档内全部图片引用，相对路径基于 md 所在目录解析
    base = md_path.parent if md_path else REPORTS_DIR
    for alt, rel in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        src = (base / rel).resolve()
        data["charts"].append({
            "alt": alt,
            "src": str(src),
            "uri": src.as_uri(),
            "missing": not src.exists(),
        })

    return data


def _parse_index_rows(body: str) -> list[list[str]]:
    """从章节正文解析 Markdown 表格数据行（跳过表头与分隔行）。"""
    rows: list[list[str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        # 分隔行：每格均为 :--- 形态
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    # 首行若为表头（指数/资产/板块）则跳过
    if rows and rows[0][0] in ("指数", "资产", "板块"):
        rows = rows[1:]
    return rows


def _sign_from_change(change: str) -> str:
    """涨跌幅符号 → up / down / flat（用于卡片着色）。"""
    c = (change or "").strip()
    if c.startswith("+"):
        return "up"
    if c.startswith("-"):
        return "down"
    return "flat"


def parse_alerts(date: str) -> list[dict]:
    """解析 alerts/{date}-close.md 附录块 → 告警列表。

    文件缺失 / 读取失败 / 坏文件 → 返回 []（仅记日志，不抛）。
    """
    path = ALERTS_DIR / f"{date}-close.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("告警文件读取失败，跳过错报解析: %s", exc)
        return []

    alerts: list[dict] = []
    for fm, body in re.findall(r"(?ms)^---\n(.*?)\n---\n(.*?)(?=\n---\n|\Z)", text):
        fm_fields: dict[str, str] = {}
        for line in fm.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm_fields[k.strip()] = v.strip()
        symbol = fm_fields.get("symbol")
        if not symbol:
            continue
        change = threshold = state = suggestion = None
        cm = re.search(
            r"变化率[:：]\s*([+-]?\d+(?:\.\d+)?)%\s*[（(]?阈值\s*±\s*(\d+(?:\.\d+)?)%",
            body,
        )
        if cm:
            change, threshold = cm.group(1), cm.group(2)
        sm = re.search(r"市场状态[:：]\s*(.+)", body)
        if sm:
            state = sm.group(1).strip()
        gm = re.search(r"建议[:：]\s*(.+)", body)
        if gm:
            suggestion = gm.group(1).strip()
        alerts.append({
            "symbol": symbol,
            "level": fm_fields.get("level"),
            "change": change,
            "threshold": threshold,
            "state": state,
            "suggestion": suggestion,
        })
    return alerts


def _png_dimensions(path: "Path | str") -> tuple[int, int]:
    """纯 Python 读 PNG IHDR，返回 (width, height)；非 PNG 抛 ValueError。"""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    width = struct.unpack(">I", head[16:20])[0]
    height = struct.unpack(">I", head[20:24])[0]
    return width, height


# --------------------------------------------------------------------------- #
# 渲染：Jinja2 模板
# --------------------------------------------------------------------------- #
_ENV = None


def _jinja_env():
    global _ENV
    if _ENV is None:
        from jinja2 import Environment, FileSystemLoader

        _ENV = Environment(
            loader=FileSystemLoader(str(BASE_DIR / "web" / "templates")),
            autoescape=True,
        )
    return _ENV


def render_html(data: dict) -> str:
    """用 report_card.html 渲染图片长图 HTML。"""
    template = _jinja_env().get_template("report_card.html")
    return template.render(**data)


# --------------------------------------------------------------------------- #
# 限时执行（Windows 无 SIGALRM）
# --------------------------------------------------------------------------- #
def _run_with_timeout(fn, timeout: int):
    """在 daemon 线程执行 fn，join(timeout)；超时返回 _TIMEOUT，异常上抛。"""
    box: dict = {}

    def _target() -> None:
        try:
            box["v"] = fn()
        except Exception as exc:  # noqa: BLE001 — 线程内异常需回传主线程
            box["e"] = exc

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return _TIMEOUT
    if "e" in box:
        raise box["e"]
    return box.get("v")


# --------------------------------------------------------------------------- #
# 编排：md → PNG
# --------------------------------------------------------------------------- #
def render_report_image(date: str) -> "Path | None":
    """将日报 md 渲染为 reports/images/{date}.png。

    任意失败（md 缺失 / imgkit 未装 / wkhtmltoimage 不可用 / 超时 / 渲染异常）
    → 记日志并返回 None，不影响调用方主流程。
    """
    md_path = REPORTS_DIR / f"{date}.md"
    if not md_path.exists():
        log.warning("日报 md 缺失，跳过图片渲染: %s", md_path)
        return None

    try:
        import imgkit  # 延迟导入：未安装时仅跳过图片，不影响日报
    except ImportError:
        log.warning("imgkit 未安装，跳过图片渲染（日报不受影响）")
        return None

    try:
        md_text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("日报 md 读取失败，跳过图片渲染: %s", exc)
        return None

    data = parse_report(md_text, md_path)
    data["alerts"] = parse_alerts(date)
    try:
        html = render_html(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("图片 HTML 渲染失败，跳过: %s", exc)
        return None

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMAGES_DIR / f"{date}.png"

    options = {
        "width": IMAGE_WIDTH,
        "disable-smart-width": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "format": "png",
    }

    def _render(opts: dict) -> None:
        imgkit.from_string(html, str(out_path), options=opts)

    try:
        res = _run_with_timeout(lambda: _render(options), RENDER_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — wkhtmltoimage 不可用等
        log.warning("imgkit 渲染失败，跳过图片: %s", exc)
        return None
    if res is _TIMEOUT:
        log.warning("图片渲染超时 %ds，跳过", RENDER_TIMEOUT)
        return None
    if not out_path.exists():
        log.warning("图片未生成: %s", out_path)
        return None

    # 尺寸守卫：超 800KB → zoom 重试一次；仍超标保留文件 + 记日志（不崩溃）
    try:
        size = out_path.stat().st_size
    except OSError:
        return out_path
    if size > MAX_IMAGE_BYTES:
        log.warning(
            "图片 %dKB 超 %dKB，zoom=%s 重试",
            size // 1024,
            MAX_IMAGE_BYTES // 1024,
            RETRY_ZOOM,
        )
        try:
            res2 = _run_with_timeout(
                lambda: _render({**options, "zoom": RETRY_ZOOM}), RENDER_TIMEOUT
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("重试渲染失败，保留原图: %s", exc)
        else:
            if res2 is _TIMEOUT:
                log.warning("重试渲染超时，保留原图")
    return out_path
