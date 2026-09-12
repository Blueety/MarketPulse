"""资讯落盘：将 Tavily 搜索结果整理写入 data/news.json。"""
import json
import logging
import os
import re
from datetime import date
from pathlib import Path

log = logging.getLogger("news_saver")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NEWS_FILE = DATA_DIR / "news.json"
NEWS_TMP = DATA_DIR / "news.json.tmp"

# 垃圾内容关键词（标题包含则丢弃）
JUNK_KEYWORDS = [
    "APP下载", "登录", "自选股", "手机新浪", "富途牛牛", 
    "东方财富", "同花顺", "雪球", "腾讯证券", "开户", "注册",
    "提供者", "智通财经", "视野环球", "鉅亨網",
]


def _is_junk(text: str) -> bool:
    """检查是否为垃圾"""
    return any(kw in text for kw in JUNK_KEYWORDS)


def _clean_title(title: str) -> str:
    """清理标题"""
    # 去除网站名后缀
    for suffix in [" - 新浪财经", " - 富途牛牛", " - 东方财富", " - 同花顺", " - 雪球", " - 腾讯证券", " | 鉅亨網"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)]
    # 去除 _ 分隔的网站名
    if "_" in title:
        parts = title.split("_")
        title = parts[0]
    # 去除特殊字符
    title = re.sub(r'[‌\u200c\u200d\u200e\u200f]', '', title)
    # 截断
    if len(title) > 50:
        title = title[:47] + "..."
    return title.strip()


def _clean_summary(summary: str) -> str:
    """清理摘要"""
    # 去除表格碎片
    if "|" in summary:
        parts = summary.split("|")
        summary = " ".join(p.strip() for p in parts if p.strip() and not p.strip()[0].isdigit())
    # 去除 markdown
    for prefix in ["##", "###", "**", "*", "+", "#"]:
        summary = summary.replace(prefix, "")
    # 去除特殊字符
    summary = re.sub(r'[‌\u200c\u200d\u200e\u200f]', '', summary)
    # 去除换行
    summary = " ".join(summary.split())
    # 截断
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return summary.strip()


def save_news(results: list[dict],当天日期: str | None = None) -> bool:
    """将搜索结果写入 news.json。"""
    if not results:
        log.info("[NewsSaver] 无搜索结果，跳过写入")
        return False

    # 筛选有效条目
    valid = []
    for item in results:
        title = (item.get("title") or "").strip()
        url = (item.get("link") or item.get("url") or "").strip()
        summary = (item.get("snippet") or item.get("summary") or "").strip()

        if not title or not url:
            continue
        if not url.startswith("http"):
            continue

        # 清理
        title = _clean_title(title)
        summary = _clean_summary(summary)

        # 过滤垃圾标题
        if _is_junk(title):
            continue

        # 标题太短（可能是网站名）
        if len(title) < 5:
            continue

        valid.append({
            "title": title,
            "url": url,
            "source": item.get("source") or "",
            "published": item.get("date") or item.get("published_date") or "",
            "summary": summary[:80] if summary else "",
        })

    if len(valid) < 1:
        log.info("[NewsSaver] 无有效条目，跳过写入")
        return False

    # 取前 5 条
    valid = valid[:5]

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
