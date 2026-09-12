"""资讯落盘测试（三十四期）：一句话切分 / 尾部噪声 / 脚注清扫 / 条数上限 / 无结果不写盘。

对应 plan `tasks/2026-09-12-news-macro-brief/plan.md` N-2（落盘层：切句 + 去噪声）。
monkeypatch 落点：`src.news_saver` 自身的模块级路径常量（`save_news` 直接引用本模块名字，
故打在定义方 `src.news_saver` 即生效）。
"""
import json

import src.news_saver as ns


# ---- 纯函数：一句话切分 ----

def test_first_sentence_basic():
    """首句 ≥12 字 → 只取首句（句末标点被切掉）。"""
    assert ns._first_sentence("美联储宣布加息二十五个基点。市场反应平淡。") == "美联储宣布加息二十五个基点"


def test_first_sentence_short_merges_second():
    """首句 <12 字 → 补第二句并补回句号（中文无空格分词，防首句过短无信息量）。"""
    assert ns._first_sentence("加息了。市场反应平淡，纳指收涨1.2%。") == "加息了。市场反应平淡，纳指收涨1.2%"


def test_first_sentence_no_punctuation():
    """无句末标点 → 原样返回。"""
    assert ns._first_sentence("全球市场要闻汇总") == "全球市场要闻汇总"


# ---- 纯函数：尾部噪声（50% 门槛）----

def test_strip_tail_noise_after_half():
    """噪声出现在后半段 → 截断到噪声起点。"""
    s = "美股三大指数收跌，纳指跌1.2%，市场关注下周美联储决议。视野环球财经 315000"
    assert ns._strip_tail_noise(s) == "美股三大指数收跌，纳指跌1.2%，市场关注下周美联储决议。"


def test_strip_tail_noise_keeps_early_keyword():
    """噪声关键词出现在前半段（<50%）→ 不动，避免把正文前段的机构名砍没。"""
    s = "东方财富报道，全球市场波动加剧，投资者观望情绪浓厚，等待通胀数据公布"
    assert ns._strip_tail_noise(s) == s


# ---- 组合：_clean_summary ----

def test_clean_summary_caps_and_keeps_first_sentence():
    s = "美联储主席表示通胀仍高于目标。" + "后续内容很长很长，" * 10
    out = ns._clean_summary(s)
    assert len(out) <= ns.MAX_SUMMARY_LEN
    assert out.startswith("美联储主席表示通胀仍高于目标")


def test_clean_summary_truncation_appends_ellipsis():
    out = ns._clean_summary("美联储宣布加息二十五个基点" + "非常长的补充说明" * 20)
    assert len(out) == ns.MAX_SUMMARY_LEN
    assert out.endswith("…")


def test_clean_summary_strips_footnote_markers():
    """[1] / [1.3.3] 脚注必须清掉，否则截断后残留半截中括号（如 "…30% […"）。"""
    out = ns._clean_summary("中国8月进口同比增长28.2%，不及市场预期的30% [1.3.3]")
    assert "[" not in out and "]" not in out


def test_clean_summary_strips_platform_noise():
    out = ns._clean_summary("30年国债收益率涨回200日均！视野环球财经 315000 订阅")
    assert "视野环球" not in out


def test_clean_summary_empty():
    assert ns._clean_summary("") == ""


# ---- save_news：条数上限 / 无结果不写盘 / 过滤 ----

def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(ns, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ns, "NEWS_FILE", tmp_path / "news.json")
    monkeypatch.setattr(ns, "NEWS_TMP", tmp_path / "news.json.tmp")


def _item(i: int) -> dict:
    return {
        "title": f"宏观要闻第{i}条足够长",
        "link": f"https://example.com/{i}",
        "snippet": f"这是第{i}条摘要内容。补充说明。",
    }


def test_save_news_caps_at_8(monkeypatch, tmp_path):
    """与 news_fetcher 的 max_results:8 配套（plan R3：两处是跨文件耦合）。"""
    _patch_paths(monkeypatch, tmp_path)
    assert ns.save_news([_item(i) for i in range(12)], "2026-09-12") is True
    data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
    assert len(data["items"]) == 8
    assert data["date"] == "2026-09-12"


def test_save_news_writes_one_sentence_summary(monkeypatch, tmp_path):
    """落盘即为一句话且 ≤MAX_SUMMARY_LEN（前端单行展示的前提）。"""
    _patch_paths(monkeypatch, tmp_path)
    ns.save_news([_item(1)], "2026-09-12")
    data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
    summary = data["items"][0]["summary"]
    assert len(summary) <= ns.MAX_SUMMARY_LEN


def test_save_news_empty_results_no_write(monkeypatch, tmp_path):
    """无结果 → 返回 False 且不写盘（旧数据保留，plan R5）。"""
    _patch_paths(monkeypatch, tmp_path)
    assert ns.save_news([], "2026-09-12") is False
    assert not (tmp_path / "news.json").exists()


def test_save_news_all_junk_no_write(monkeypatch, tmp_path):
    """全为垃圾标题 → 无有效条目 → 不写盘。"""
    _patch_paths(monkeypatch, tmp_path)
    junk = [{"title": "东方财富APP下载开户", "link": "https://example.com/x", "snippet": "x"}]
    assert ns.save_news(junk, "2026-09-12") is False
    assert not (tmp_path / "news.json").exists()


def test_save_news_skips_non_http_and_missing_fields(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    results = [
        {"title": "有效宏观要闻标题", "link": "https://example.com/ok", "snippet": "内容。"},
        {"title": "协议不符", "link": "javascript:alert(1)", "snippet": "x。"},
        {"title": "", "link": "https://example.com/no-title", "snippet": "x。"},
    ]
    assert ns.save_news(results, "2026-09-12") is True
    data = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
    assert len(data["items"]) == 1
    assert data["items"][0]["url"] == "https://example.com/ok"
