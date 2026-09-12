"""资讯落盘：将 Tavily 搜索结果整理写入 data/news.json。"""
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("news_saver")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NEWS_FILE = DATA_DIR / "news.json"
NEWS_TMP = DATA_DIR / "news.json.tmp"

# 垃圾内容关键词（标题或摘要包含则丢弃）
JUNK_KEYWORDS = [
    "操盘必读", "今日股市", "股票新闻", "美股新聞", "提供者", "APP",
    "APP下载", "登录", "自选股", "行情走势", "实时行情", "手机新浪",
    "富途牛牛", "东方财富", "同花顺", "雪球", "腾讯证券",
    "|", "##", "###", "下载", "注册", "开户",
]


def _is_junk(title: str, summary: str) -> bool:
    """检查是否为垃圾内容"""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in JUNK_KEYWORDS)


def _clean_title(title: str) -> str:
    """清理标题：截断、去除网站名"""
    # 去除网站名后缀
    for suffix in [" - 新浪财经", " - 富途牛牛", " - 东方财富", " - 同花顺", " - 雪球"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)]
    # 截断
    if len(title) > 50:
        title = title[:47] + "..."
    return title.strip()


def _clean_summary(summary: str) -> str:
    """清理摘要：截断、去除表格碎片"""
    # 去除表格碎片
    if "|" in summary:
        parts = summary.split("|")
        summary = " ".join(p.strip() for p in parts if p.strip() and not p.strip()[0].isdigit())
    # 去除 markdown
    for prefix in ["##", "###", "**", "*"]:
        summary = summary.replace(prefix, "")
    # 截断
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return summary.strip()


def save_news(results: list[dict],当天日期: str | None = None) -> bool:
    """将搜索结果写入 news.json。

    - 筛选 3~8 条有效新闻
    - 过滤垃圾内容（标题/摘要包含关键词）
    - 原子写入
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
        summary = (item.get("snippet") or item.get("summary") or "").strip()

        if not title or not url:
            continue
        if not url.startswith("http"):
            continue

        # 清理
        title = _clean_title(title)
        summary = _clean_summary(summary)

        # 过滤垃圾
        if _is_junk(title, summary):
            continue

        # summary 必须非空
        if not summary:
            continue

        valid.append({
            "title": title,
            "url": url,
            "source": item.get("source") or "",
            "published": item.get("date") or item.get("published_date") or "",
            "summary": summary[:80],
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
