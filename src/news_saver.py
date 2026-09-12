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

# 垃圾内容关键词
JUNK_KEYWORDS = [
    "APP下载", "登录", "自选股", "手机新浪", "富途牛牛", 
    "东方财富", "同花顺", "雪球", "腾讯证券", "开户", "注册",
    "提供者", "智通财经", "视野环球", "鉅亨網", "美股股市新聞",
    "智通财经APP",
]


def _is_junk(text: str) -> bool:
    """检查是否为垃圾"""
    return any(kw in text for kw in JUNK_KEYWORDS)


# 尾部平台噪声（补 N-G4：_is_junk 只作用于 title，summary 侧的噪声会直接漏到前端）
TAIL_NOISE = ["智通财经", "视野环球", "鉅亨網", "美股股市新聞", "富途牛牛"]
TAIL_NOISE_POSITION = 0.5   # 仅当噪声出现位置 > 50% 时才截断
MAX_SUMMARY_LEN = 60        # 一句话上限（比前端的 42 字宽，给前端留余量）
MIN_FIRST_SENTENCE = 12     # 首句短于该长度 → 补第二句


def _strip_tail_noise(text: str) -> str:
    """剥离出现在**中后段**的平台噪声（如「…200日均！视野环球财经 315000 s…」）。

    ⚠️ 为什么加 50% 门槛：`JUNK_KEYWORDS` 里的「东方财富」「同花顺」等可能出现在正文前段，
    无条件截断会**把整句砍没** → 只处理中后段噪声。
    """
    cut = len(text)
    for kw in TAIL_NOISE:
        idx = text.rfind(kw)
        if idx > len(text) * TAIL_NOISE_POSITION:
            cut = min(cut, idx)
    return text[:cut].strip()


def _first_sentence(text: str) -> str:
    """按句末标点切出「一句话」；首句过短则补第二句（补回句号）。"""
    parts = re.split(r'[。！？；!?;\n]', text)
    first = (parts[0] or "").strip()
    if len(first) < MIN_FIRST_SENTENCE and len(parts) > 1 and parts[1].strip():
        first = (first + "。" + parts[1].strip()).strip()
    return first


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
    title = re.sub(r'[\u200c\u200d\u200e\u200f]', '', title)
    # 截断
    if len(title) > 50:
        title = title[:47] + "..."
    return title.strip()


def _clean_summary(summary: str) -> str:
    """清理摘要 → **一句话**（供前端单行展示）。

    顺序：去表格碎片/markdown/特殊字符/固定碎片 → 压空白 → **尾部噪声剥离** → **按句切分**
    → 再剥一次噪声 → 截到 `MAX_SUMMARY_LEN`。切句必须在清洗之后（否则残留标记会破坏句边界
    判断），截断必须放最后（否则会把「…」也算进长度）。
    """
    # 去除表格碎片
    if "|" in summary:
        parts = summary.split("|")
        summary = " ".join(p.strip() for p in parts if p.strip() and not p.strip()[0].isdigit())
    # 去除 markdown
    for prefix in ["##", "###", "**", "*", "+", "#"]:
        summary = summary.replace(prefix, "")
    # 去除特殊字符
    summary = re.sub(r'[\u200c\u200d\u200e\u200f]', '', summary)
    # 去除"提供者...•"碎片
    summary = re.sub(r'提供者.*?•\s*', '', summary)
    # 去除"智通财经APP..."碎片
    summary = re.sub(r'智通财经APP.*?，', '', summary)
    # 去除数字编号开头（如"10、"）
    summary = re.sub(r'^\d+、', '', summary)
    # 去除换行
    summary = " ".join(summary.split())
    # N-G3 修复：硬截断 → 一句话（先剥尾部噪声，再切句，必要时再剥一次）
    summary = _first_sentence(_strip_tail_noise(summary))
    summary = _strip_tail_noise(summary)
    # 截断
    if len(summary) > MAX_SUMMARY_LEN:
        summary = summary[:MAX_SUMMARY_LEN - 1] + "…"
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
            "summary": summary[:MAX_SUMMARY_LEN] if summary else "",
        })

    if len(valid) < 1:
        log.info("[NewsSaver] 无有效条目，跳过写入")
        return False

    # 取前 8 条（与 news_fetcher 的 max_results:8 配套；两处是跨文件耦合，见 plan R3）
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
