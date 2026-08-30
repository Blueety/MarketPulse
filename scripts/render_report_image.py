#!/usr/bin/env python
"""独立重渲染入口：Hermes 追加 AI 解读到 md 后，调用 render_report_image 重新生成含解读区的图片。

用法:
    python scripts/render_report_image.py --date YYYY-MM-DD

脚本不含推送逻辑（由 Hermes 读取图片推送 QQ）。缺 md / 渲染失败 / imgkit 不可用
→ 退出码 0（不影响定时任务），与 daily_report 同款容错纪律。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 项目根入 path（支持 `python scripts/render_report_image.py` 与 `from scripts.render_report_image import ...`）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyzer import get_us_eastern_date
from src.image_renderer import render_report_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def main(argv=None) -> int:
    """重渲染指定日期的日报图片（含可能已追加的 AI 解读章节）。"""
    parser = argparse.ArgumentParser(description="重渲染日报图片（含 AI 解读）")
    parser.add_argument("--date", default=None, help="美东日期 YYYY-MM-DD，默认今日")
    args = parser.parse_args(argv)

    date = args.date or get_us_eastern_date()
    log.info("重渲染日报图片: %s", date)

    image_path = render_report_image(date)
    if image_path is None:
        log.warning("图片未生成（缺 md / 渲染失败 / imgkit 不可用）；跳过推送")
        return 0
    size_kb = image_path.stat().st_size / 1024
    log.info("图片已生成: %s (%.1f KB)", image_path, size_kb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
