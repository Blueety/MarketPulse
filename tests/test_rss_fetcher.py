"""RSS 宏观新闻抓取测试（三十四期）：解析 / HTML 清洗 / 来源剥离 / 白名单 / 去重 / 降级。

对应 plan `tasks/2026-09-13-rss-macro-news/plan.md` R-6。
**全部用 XML 夹具 + monkeypatch，不联网**（`fetch_rss` 的 XML 解析用假 requests.Response；
合并逻辑直接替换 `fetch_rss`）。
"""
import json

import src.news_saver as ns
import src.rss_fetcher as rf

# 夹具形态 = `fetch_rss` 的**输出**（HTML 已剥离），因为合并逻辑拿到的就是这一层
WSCN_ITEM = {
    "title": "美联储加息预期升温",
    "snippet": "美联储 下周或加息。",
    "link": "https://wallstreetcn.com/articles/1",
    "date": "2026-09-12",
}
WSCN_OTHER_ITEM = {
    "title": "某品牌发布新车",
    "snippet": "新车上市。",
    "link": "https://wallstreetcn.com/articles/2",
    "date": "2026-09-12",
}
GN_CPI_ITEM = {
    "title": "美国8月CPI超预期 - 东方财富",
    "snippet": "美国8月CPI超预期 东方财富",     # 尾部带媒体名（标题无句末标点时不会被切句切掉）
    "link": "https://news.google.com/rss/articles/AAA",
    "date": "2026-09-12",
}
GN_DUP_ITEM = {                       # 与 WSCN_ITEM 同一话题（用于去重）
    "title": "美联储加息预期升温 - 财联社",
    "snippet": "<a href='y'>美联储加息预期升温</a>",
    "link": "https://news.google.com/rss/articles/BBB",
    "date": "2026-09-12",
}

WSCN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>美联储加息预期升温</title>
    <link>https://wallstreetcn.com/articles/1</link>
    <description>&lt;p style="color:red"&gt;美联储&lt;/p&gt;&lt;p&gt;下周或加息。&lt;/p&gt;</description>
    <pubDate>Sat, 12 Sep 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>无链接的坏条目</title>
    <description>应当被跳过</description>
  </item>
</channel></rss>"""


class _Resp:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def _patch_feeds(monkeypatch, by_url: dict[str, list[dict]]):
    """把 RSS_FEEDS 换成两个假源，并按 url 返回夹具（无网）。"""
    monkeypatch.setattr(rf, "RSS_FEEDS", [
        {"name": "A源", "url": "u1", "filter_macro": True},
        {"name": "B源", "url": "u2", "filter_macro": False},
    ])

    def fake_fetch(url, timeout=10, source_name=""):
        return [dict(it, source=source_name) for it in by_url.get(url, [])]

    monkeypatch.setattr(rf, "fetch_rss", fake_fetch)


# ---- 纯函数：HTML 清洗 / 来源剥离 / 归一化 / 日期 ----

def test_strip_html_removes_tags_and_unescapes():
    out = rf._strip_html("<p style='color:red'>美联储</p><p>下周或加息。</p>")
    assert out == "美联储 下周或加息。"
    assert rf._strip_html("A&amp;B") == "A&B"            # 实体要反转义（不是丢弃）


def test_split_source_strips_trailing_media_name():
    assert rf._split_source("美国8月CPI超预期 - 东方财富") == ("美国8月CPI超预期", "东方财富")
    assert rf._split_source("加息预期升温 | 财联社") == ("加息预期升温", "财联社")
    # 双层后缀（实测形态）→ 全部剥掉，source 记最外层发布方
    assert rf._split_source("加息预期升温 - 财联社 - 新浪") == ("加息预期升温", "新浪")
    assert rf._split_source(
        "美国8月核心CPI月率意外高于预期！美联储下周加息概率逼近90%-市场参考 - 金十数据"
    ) == ("美国8月核心CPI月率意外高于预期！美联储下周加息概率逼近90%", "金十数据")
    # 单字符尾段不算来源名（正则要求 ≥2 个字）
    assert rf._split_source("标题 - A") == ("标题 - A", "")


def test_drop_trailing_source_from_snippet():
    """Google 侧 description 尾部带媒体名，标题无句末标点时须剥掉，否则摘要会拖一条来源名。"""
    assert rf._drop_trailing_source("美国8月CPI超预期 东方财富", "东方财富") == "美国8月CPI超预期"
    assert rf._drop_trailing_source("与来源无关的正文", "东方财富") == "与来源无关的正文"
    assert rf._drop_trailing_source("正文", "") == "正文"


def test_split_source_keeps_titles_without_source():
    t = "标普500指数下滑0.58%至7673.52点"
    assert rf._split_source(t) == (t, "")
    # 纯数字尾段不算来源（防误伤「... - 0.58%」这类）
    assert rf._split_source("油价上涨 - 12.5%") == ("油价上涨 - 12.5%", "")


def test_norm_key_and_url():
    assert rf._norm_key("ＡＢＣ，加息！") == rf._norm_key("abc加息")
    assert rf._norm_url("https://a.com/x/?q=1#f") == rf._norm_url("HTTPS://A.com/x/")


def test_to_date_rfc822_to_ymd():
    assert rf._to_date("Sat, 12 Sep 2026 08:00:00 GMT") == "2026-09-12"
    assert rf._to_date("坏日期") == ""


# ---- fetch_rss：XML 解析 / 失败容错 ----

def test_fetch_rss_parses_items(monkeypatch):
    monkeypatch.setattr(rf.requests, "get", lambda *a, **k: _Resp(WSCN_XML.encode("utf-8")))
    items = rf.fetch_rss("http://x/rss.xml", source_name="华尔街见闻")
    assert len(items) == 1                                  # 第二条无 link → 跳过
    it = items[0]
    assert set(it) == {"title", "snippet", "link", "date", "source"}
    assert it["title"] == "美联储加息预期升温"
    assert it["date"] == "2026-09-12"
    assert it["source"] == "华尔街见闻"
    assert "<" not in it["snippet"]


def test_fetch_rss_bad_xml_returns_empty(monkeypatch):
    monkeypatch.setattr(rf.requests, "get", lambda *a, **k: _Resp(b"not xml"))
    assert rf.fetch_rss("http://x/rss.xml") == []


def test_fetch_rss_network_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("unreachable")

    monkeypatch.setattr(rf.requests, "get", boom)
    assert rf.fetch_rss("http://x/rss.xml") == []


# ---- fetch_macro_news：合并 / 白名单 / 去重 / 降级 / 上限 ----

def test_fetch_macro_news_merges_both_sources(monkeypatch):
    _patch_feeds(monkeypatch, {"u1": [WSCN_ITEM], "u2": [GN_CPI_ITEM]})
    out = rf.fetch_macro_news()
    assert [x["source"] for x in out] == ["A源", "东方财富"]   # 交错 + 后缀来源覆盖
    assert out[1]["title"] == "美国8月CPI超预期"
    assert out[1]["snippet"] == "美国8月CPI超预期"             # 尾部媒体名已剥除


def test_fetch_macro_news_macro_filter_drops_non_macro(monkeypatch):
    """华尔街见闻侧（filter_macro=True）非宏观条目被白名单过滤。"""
    _patch_feeds(monkeypatch, {"u1": [WSCN_ITEM, WSCN_OTHER_ITEM], "u2": []})
    out = rf.fetch_macro_news()
    assert [x["title"] for x in out] == ["美联储加息预期升温"]


def test_fetch_macro_news_dedupes_across_sources(monkeypatch):
    """两源同一条（标题归一化后相同）只保留一条。"""
    _patch_feeds(monkeypatch, {"u1": [WSCN_ITEM], "u2": [GN_DUP_ITEM]})
    out = rf.fetch_macro_news()
    assert len(out) == 1 and out[0]["link"] == WSCN_ITEM["link"]


def test_fetch_macro_news_single_feed_failure(monkeypatch):
    _patch_feeds(monkeypatch, {"u1": [], "u2": [GN_CPI_ITEM]})
    out = rf.fetch_macro_news()
    assert len(out) == 1 and out[0]["source"] == "东方财富"


def test_fetch_macro_news_all_fail_returns_empty(monkeypatch):
    _patch_feeds(monkeypatch, {"u1": [], "u2": []})
    assert rf.fetch_macro_news() == []


def test_fetch_macro_news_respects_limit(monkeypatch):
    items = [dict(WSCN_ITEM, link=f"https://wallstreetcn.com/{i}", title=f"美联储观察第{i}期")
             for i in range(20)]
    _patch_feeds(monkeypatch, {"u1": items, "u2": []})
    assert len(rf.fetch_macro_news()) == rf.DEFAULT_LIMIT


# ---- 契约：输出可直接被 news_saver 消费（R1 核心：来源后缀剥离防 _is_junk 误杀）----

def test_split_source_prevents_junk_kill():
    """带 ` - 东方财富` 后缀的标题必须先剥离，否则会被 JUNK_KEYWORDS 整条误杀。"""
    raw = "美国8月CPI超预期 - 东方财富"
    assert ns._is_junk(raw) is True              # 不剥离 → 命中 JUNK
    title, _ = rf._split_source(raw)
    assert ns._is_junk(title) is False           # 剥离后 → 不误杀


def test_rss_output_feeds_save_news(monkeypatch, tmp_path):
    """统一格式契约：fetch_macro_news 的产出能被 save_news 直接落盘。"""
    _patch_feeds(monkeypatch, {"u1": [WSCN_ITEM], "u2": [GN_CPI_ITEM]})
    monkeypatch.setattr(ns, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ns, "NEWS_FILE", tmp_path / "news.json")
    monkeypatch.setattr(ns, "NEWS_TMP", tmp_path / "news.json.tmp")
    assert ns.save_news(rf.fetch_macro_news(), "2026-09-13") is True
    data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
    assert data["date"] == "2026-09-13"
    assert len(data["items"]) == 2
    assert all(it["source"] for it in data["items"])                 # source 不再恒空
    assert all(len(it["summary"]) <= ns.MAX_SUMMARY_LEN for it in data["items"])
