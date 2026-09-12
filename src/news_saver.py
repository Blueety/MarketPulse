"""资讯落盘：将 Tavily 搜索结果整理写入 data/news.json。"""
import json
import logging
import os
from datetime import date
from pathlib import Path

log = logging.getLogger("news_saver")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NEWS_FILE = DATA_DIR / "news.json"
NEWS_TMP = DATA_DIR / "news.json.tmp"


def save_news(results: list[dict],当天日期: str | None = None) -> bool:
    """将搜索结果写入 news.json。

    - 筛选 3~8 条有效新闻（title+url 必填，url 以 http 开头）
    - 原子写入：先写 .tmp 再 rename
    - 搜索失败或不足 3 条→不写文件（保留上一次）
    - 返回 True 表示成功写入
    """
    if not results:
        log.info("[NewsSaver] 无搜索结果，跳过写入")
        return False

    # 筛选有效条目
    valid = []
    for item in results:
        title = (item.get("title") or "").strip()
        url = (item.get("link") or item.get("url") or "").strip()
        if not title or not url:
            continue
        if not url.startswith("http"):
            continue
        valid.append({
            "title": title,
            "url": url,
            "source": item.get("source") or "",
            "published": item.get("date") or item.get("published_date") or "",
            "summary": (item.get("snippet") or item.get("summary") or "")[:80],
        })

    if len(valid) < 3:
        log.info("[NewsSaver] 有效条目不足 3 条（%d 条），跳过写入", len(valid))
        return False

    # 取前 8 条
    valid = valid[:8]

    # 构建文件内容
    data = {
        "date": 当天日期 or date.today().strftime("%Y-%m-%d"),
        "items": valid,
    }

    # 原子写入
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        NEWS_TMP.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(NEWS_TMP, NEWS_FILE)
        log.info("[NewsSaver] 已写入 %s（%d 条）", NEWS_FILE, len(valid))
        return True
    except Exception as exc:
        log.warning("[NewsSaver] 写入失败: %s", exc)
        return False
