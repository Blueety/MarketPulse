"""日报图片化：Markdown 日报 → 结构化数据 → Jinja2 模板 → Playwright 截图 → PNG。

设计为不侵入主流程的容错模块：
- 渲染失败 / 超时 / 缺少 playwright / md 缺失 → 一律返回 None 并记日志，
  不影响 daily_report.py 主流程与退出码。
"""

from __future__ import annotations

import logging
import re
import struct
from pathlib import Path

from .analyzer import ALERTS_DIR, BASE_DIR, IMAGES_DIR, REPORTS_DIR

log = logging.getLogger("marketpulse")

# ---- 固定约束 ----
IMAGE_WIDTH = 600
MAX_IMAGE_BYTES = 800 * 1024
RENDER_TIMEOUT = 15

# 索引表章节 → 类别
_INDEX_SECTIONS = (
    ("美股大盘", "us"),
    ("A 股大盘", "a_share"),
    ("波动率指数", "vol"),
    ("另类资产", "alt"),
)


# ---------------------------------------------------------------------------
# 纯函数：Markdown 解析
# ---------------------------------------------------------------------------
def parse_report(md_text: str, md_path: "Path | None" = None) -> dict:
    """解析日报 md → 结构化数据（date / cards / charts / interpretation）。"""
    text = md_text or ""
    data: dict = {
        "date": None,
        "cards": [],
        "charts": [],
        "interpretation": None,
    }

    m = re.search(r"\*\*日期\*\*[:：]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        data["date"] = m.group(1)

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
        if "解读" in heading:
            data["interpretation"] = body.strip()

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
    rows: list[list[str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    if rows and rows[0][0] in ("指数", "资产", "板块"):
        rows = rows[1:]
    return rows


def _sign_from_change(change: str) -> str:
    c = (change or "").strip()
    if c.startswith("+"):
        return "up"
    if c.startswith("-"):
        return "down"
    return "flat"


def parse_alerts(date: str) -> list[dict]:
    """解析 alerts/{date}-close.md 附录块 → 告警列表。"""
    path = ALERTS_DIR / f"{date}-close.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("告警文件读取失败: %s", exc)
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
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    width = struct.unpack(">I", head[16:20])[0]
    height = struct.unpack(">I", head[20:24])[0]
    return width, height


# ---------------------------------------------------------------------------
# 渲染：Jinja2 模板
# ---------------------------------------------------------------------------
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
    """用 report_card.html 渲染图片长图 HTML。将图表转为 base64 内嵌。"""
    import base64
    # 将图表路径转为 base64 data URI
    for chart in data.get("charts", []):
        if not chart.get("missing"):
            src_path = chart.get("src")
            if src_path and Path(src_path).exists():
                try:
                    img_bytes = Path(src_path).read_bytes()
                    b64 = base64.b64encode(img_bytes).decode()
                    chart["uri"] = f"data:image/png;base64,{b64}"
                except Exception:
                    chart["missing"] = True
    template = _jinja_env().get_template("report_card.html")
    return template.render(**data)


# ---------------------------------------------------------------------------
# 编排：md → PNG（Playwright）
# ---------------------------------------------------------------------------
def render_report_image(date: str, interpretation: str = None) -> "Path | None":
    """将日报 md 渲染为 reports/images/{date}.png。

    interpretation: 可选的 AI 解读文本，传入则渲染到图片中。
    """
    md_path = REPORTS_DIR / f"{date}.md"
    if not md_path.exists():
        log.warning("日报 md 缺失，跳过图片渲染: %s", md_path)
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright 未安装，跳过图片渲染（日报不受影响）")
        return None

    try:
        md_text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("日报 md 读取失败: %s", exc)
        return None

    data = parse_report(md_text, md_path)
    data["alerts"] = parse_alerts(date)
    # 如果传入了解读文本，使用它；否则尝试从 md 解析
    if interpretation:
        data["interpretation"] = interpretation
    try:
        html = render_html(data)
    except Exception as exc:
        log.warning("图片 HTML 渲染失败: %s", exc)
        return None

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMAGES_DIR / f"{date}.png"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": IMAGE_WIDTH, "height": 800})
            page.set_content(html, wait_until="networkidle")
            # 等待所有图片加载完成
            page.wait_for_timeout(3000)
            # 检查图片是否加载
            for img in page.query_selector_all("img"):
                natural_width = img.evaluate("el => el.naturalWidth")
                if natural_width == 0:
                    log.warning("图片加载失败: %s", img.get_attribute("src"))
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        log.info("日报图片已生成: %s", out_path)
        return out_path
    except Exception as exc:
        log.warning("playwright 渲染失败: %s", exc)
        return None
