"""宏观新闻 RSS 双源（华尔街见闻 + Google News 中文检索）→ 新闻流展示用。

**为什么用 RSS 而不是搜索 API（本模块的存在理由）**：
Tavily 之类的搜索 API 返回的是「网页中**含关键词的任意窗口**」——片段可能落在正文中段，
因而天然碎片化、且常与标题无关（实测 8 条里 6 条有缺陷：标题讲油价、摘要讲俄军）。
新闻流要给人看，需要「**编辑写好的、自含上下文的句子**」；RSS 的 `description` 是**文章开头**
（必定自含），`title` 是编辑定的完整标题。二者是不同产品形态，调截断参数修不好。

**链路分工（plan §1）**：
- 链路 A · 个股归因（`daily_report._attrib_watchlist_news`）→ **保留 Tavily**（按 symbol 精确搜，消费方是 AI）。
- 链路 B · 新闻流展示（本模块）→ **RSS**。

零新增依赖：`xml.etree.ElementTree` / `html` / `email.utils` / `unicodedata` / `re` 全为 stdlib。

用法：
    python -m src.rss_fetcher            # 打印抓取结果（调试）
    python -m src.rss_fetcher --json     # 输出统一格式 JSON
"""
from __future__ import annotations

import html
import json
import logging
import re
import sys
import unicodedata
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("rss_fetcher")

# 华尔街见闻专用 RSS（编辑级标题 + 文章导语，原文直链）
WALLSTREETCN_URL = "https://dedicated.wallstreetcn.com/rss.xml"

# Google News 中文检索（返回各媒体原标题，链接经 Google 跳转）
GOOGLE_NEWS_TMPL = "https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

# 检索词：宏观/世界要闻（可调整；改词后必须重跑 R-4 逐条判读，而不是加清洗规则）
RSS_MACRO_QUERY = "美联储 OR 通胀 OR 央行 OR 地缘政治 OR 全球股市"

# 抓取源（`filter_macro`：是否套用宏观白名单 —— Google 侧检索词已是宏观，无需二次过滤）
RSS_FEEDS = [
    {"name": "华尔街见闻", "url": WALLSTREETCN_URL, "filter_macro": True},
    {"name": "Google News", "url": GOOGLE_NEWS_TMPL.format(q=RSS_MACRO_QUERY), "filter_macro": False},
]

# 宏观白名单（华尔街见闻侧）：该源是综合财经站，含大量商品/个股/基金内容，需筛出宏观要闻
MACRO_KEYWORDS = [
    "美联储", "央行", "欧洲央行", "日本央行", "通胀", "CPI", "PPI", "非农", "就业",
    "利率", "加息", "降息", "衰退", "地缘", "关税", "原油", "黄金", "汇率", "美元",
    "美债", "PMI", "GDP", "制裁", "全球市场", "股市", "指数", "经济",
]
MACRO_FILTER_ENABLED = True     # 实测过滤后条数 < 3 时改 False（或放宽 MACRO_KEYWORDS）

PER_FEED_CAP = 12               # 单源合并前的取条上限（防第一源把 8 条名额占满，双源都要露面）
MAX_SOURCE_SUFFIX = 2           # 标题尾部来源后缀最多剥几层（实测有 `原标题-站名 - 发布方` 双层）
DEFAULT_LIMIT = 8               # 最终条数（与 news_saver 的 [:8] 配套）

# 标题尾部来源后缀：` - 新浪新闻` / ` | 财联社`
# ⚠️ 必须做，见 `_split_source` 的 docstring（否则标题会被 JUNK 过滤误杀）
_SOURCE_TAIL_RE = re.compile(r"\s*[-–—|｜]\s*([^\s\-–—|｜\d]{2,20})\s*$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)


def _strip_html(s: str) -> str:
    """剥离 HTML 标签并反转义实体（华尔街见闻 description 带 `<p style=…>` 全文）。"""
    if not s:
        return ""
    text = _TAG_RE.sub(" ", s)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _split_source(title: str) -> tuple[str, str]:
    """把标题尾部的来源后缀（` - 财联社`）拆出来 → `(纯净标题, 来源)`。

    ★ 为什么必须做：`news_saver.JUNK_KEYWORDS` 含「东方财富 / 同花顺 / 雪球 / 腾讯证券 /
    智通财经 / 鉅亨網」等站点名，而 Google News 标题普遍带 ` - 东方财富` 这类后缀 ——
    若不先剥离，整条新闻会被 `_is_junk` 当垃圾**误杀**。`news_saver._clean_title` 只硬编码了
    7 个后缀且不含「财联社 / 新浪新闻」，故剥离必须放在 fetcher 侧（blast radius 最小）。
    来源名同时填进 `source` 字段（该字段此前恒为空，顺带修复）。
    """
    t = (title or "").strip()
    src = ""
    for _ in range(MAX_SOURCE_SUFFIX):      # 实测存在双层后缀：`原标题-市场参考 - 金十数据`
        m = _SOURCE_TAIL_RE.search(t)
        if not m:
            break
        head = t[:m.start()].strip()
        if len(head) < 6:                   # 剥完太短 → 认为这不是来源后缀
            break
        if not src:                         # 只记最外层（Google 注册的发布方）
            src = m.group(1).strip()
        t = head
    return t, src


def _drop_trailing_source(text: str, src: str) -> str:
    """剥掉正文尾部的媒体名（Google News 的 description 形如 `标题&nbsp;&nbsp;<font>来源</font>`）。

    标题若恰好以 `！`/`？` 结尾，`_clean_summary` 按句切分时天然切掉来源；但标题没有句末标点
    时来源会留在摘要里（`美国8月CPI超预期 东方财富`）→ 这里按已知来源名精确剥除。
    """
    if not src or not text:
        return text
    t = text.strip()
    if t.endswith(src):
        return t[: -len(src)].strip(" \u3000|—-·")
    return text


def _norm_key(s: str) -> str:
    """标题归一化去重键：NFKC（全角→半角）+ 小写 + 去所有标点空白。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return _NON_WORD_RE.sub("", s)


def _norm_url(u: str) -> str:
    """URL 归一化去重键：去 query/fragment、去尾斜杠、小写。"""
    return re.sub(r"[#?].*$", "", (u or "").strip().lower()).rstrip("/")


def _to_date(pub_date: str) -> str:
    """RFC822（`Wed, 09 Sep 2026 15:00:00 GMT`）→ `YYYY-MM-DD`；失败返回空串。"""
    try:
        return parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 —— 任何格式/时区异常都不该中断抓取
        return ""


def _is_macro(text: str) -> bool:
    """宏观白名单判定（华尔街见闻侧用）。"""
    return any(kw in text for kw in MACRO_KEYWORDS)


def _item_text(node: ET.Element, tag: str) -> str:
    """取 `<item>` 子元素文本（缺失 / 空 → 空串）。"""
    el = node.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def fetch_rss(url: str, timeout: int = 10, source_name: str = "") -> list[dict]:
    """拉取并解析单个 RSS feed → 统一格式列表；失败返回 `[]`（不抛异常）。"""
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPulse/1.0; +rss)"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 单源失败不能中断整体（plan R4）
        log.warning("[RSS] %s 拉取/解析失败: %s", source_name or url, exc)
        return []

    items: list[dict] = []
    for node in root.iter("item"):
        title, link = _item_text(node, "title"), _item_text(node, "link")
        if not title or not link:
            continue
        items.append({
            "title": title,
            "snippet": _strip_html(_item_text(node, "description")),
            "link": link,
            "date": _to_date(_item_text(node, "pubDate")),
            "source": source_name,
        })
    log.info("[RSS] %s 取得 %d 条", source_name or url, len(items))
    return items


def fetch_macro_news(timeout: int = 10, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """双源合并 → 清洗 → 来源剥离 → 白名单 → 去重 → 按日期倒序取前 `limit` 条。

    契约（与 `news_fetcher._make_result` 兼容，`news_saver.save_news` 可直接消费）：
    `{"title": str, "snippet": str, "link": str, "date": str, "source": str}`
    单源失败不影响另一源；全部失败返回 `[]`（调用方降级 Tavily）。
    """
    merged: list[dict] = []
    per_feed: list[list[dict]] = []
    for feed in RSS_FEEDS:
        items = fetch_rss(feed["url"], timeout=timeout, source_name=feed["name"])
        if feed.get("filter_macro") and MACRO_FILTER_ENABLED:
            items = [it for it in items if _is_macro(it["title"] + " " + it["snippet"])]
        per_feed.append(items[:PER_FEED_CAP])

    # 交错合并（`A[0], B[0], A[1], B[1] …`）：两源都按各自的新旧序排，直接拼接会让排在前面的源
    # 独吞 8 条名额（实测华尔街见闻 55 条把 Google News 全部挤出）。交错保证双源都露面。
    if per_feed:
        for i in range(max(len(b) for b in per_feed)):
            for bucket in per_feed:
                if i < len(bucket):
                    merged.append(bucket[i])

    if not merged:
        return []

    out: list[dict] = []
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    for it in merged:
        title, src = _split_source(it["title"])
        if not title:
            continue
        it = {**it, "title": title,
              "snippet": _drop_trailing_source(it["snippet"], src),
              "source": src or it.get("source") or ""}
        key, url_key = _norm_key(title), _norm_url(it["link"])
        if key in seen_keys or url_key in seen_urls:
            continue                # 两源命中同一条 → 只保留先出现的那条
        seen_keys.add(key)
        seen_urls.add(url_key)
        out.append(it)

    # 新的在前（无日期排末尾）。稳定排序 → 同一天内保留上面的交错顺序（双源仍然交替露面）。
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out[:limit]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = fetch_macro_news()
    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    print(f"共 {len(results)} 条")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['source']}] {r['title']}  ({r['date']})")
        print(f"   {r['snippet'][:100]}")
        print(f"   {r['link']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
