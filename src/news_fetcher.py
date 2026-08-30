"""多新闻源降级搜索：Tavily → SerpAPI → Anspire → 空结果。

用法：
    python -m src.news_fetcher "VIX surge 2026-08-29"
    python -m src.news_fetcher --json "market volatility today"

输出 JSON 格式的搜索结果列表。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from time import sleep

import requests

log = logging.getLogger("news_fetcher")


def _load_env(key: str) -> str:
    """从环境变量或 .env 文件读取 key（环境变量优先）。"""
    val = os.environ.get(key, "")
    if val:
        return val
    # 尝试从 .env 文件读取（搜索常见位置）
    for dotenv in [Path(__file__).resolve().parent.parent / ".env",
                   Path(r"D:/hermes/.env"),
                   Path.home() / ".hermes" / ".env"]:
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line[len(key) + 1:].strip().strip("'\"")
    return ""

# ---- 统一结果格式 ----

def _make_result(title: str, snippet: str, link: str, date: str = "") -> dict:
    return {"title": title, "snippet": snippet, "link": link, "date": date}


# ---- Tavily ----

def _search_tavily(query: str, timeout: int = 10) -> list[dict]:
    """通过 Tavily API 搜索。返回统一格式结果列表。"""
    api_key = _load_env("TAVILY_API_KEY")
    if not api_key:
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": 5,
        "search_depth": "basic",
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("results", []):
        results.append(_make_result(
            title=item.get("title", ""),
            snippet=item.get("content", "")[:200],
            link=item.get("url", ""),
            date=item.get("published_date", ""),
        ))
    return results


# ---- SerpAPI (Google) ----

def _search_serpapi(query: str, timeout: int = 10) -> list[dict]:
    """通过 SerpAPI (Google) 搜索。返回统一格式结果列表。"""
    api_key = _load_env("SERPAPI_API_KEY")
    if not api_key:
        return []
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": api_key,
        "engine": "google",
        "num": 5,
    }
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("organic_results", []):
        results.append(_make_result(
            title=item.get("title", ""),
            snippet=item.get("snippet", "")[:200],
            link=item.get("link", ""),
            date=item.get("displayed_link", ""),
        ))
    return results


# ---- Anspire ----

def _search_anspire(query: str, timeout: int = 10) -> list[dict]:
    """通过 Anspire 搜索 API。返回统一格式结果列表。"""
    api_key = _load_env("ANSPIRE_API_KEY")
    if not api_key:
        return []
    url = "https://plugin.anspire.cn/api/ntsearch/search"
    params = {"query": query, "top_k": 5}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("results", data.get("data", [])):
        content = item.get("content", "")
        results.append(_make_result(
            title=item.get("title", ""),
            snippet=content[:200] if content else "",
            link=item.get("url", ""),
            date=item.get("date", ""),
        ))
    return results


# ---- 降级搜索 ----

SOURCES = [
    {"name": "Tavily", "func": _search_tavily},
    {"name": "SerpAPI", "func": _search_serpapi},
    {"name": "Anspire", "func": _search_anspire},
]


def search_news(query: str, timeout: int = 10) -> list[dict]:
    """按优先级搜索新闻，命中即停。

    降级链：Tavily → SerpAPI → Anspire → 空列表。
    每个源独立超时和错误捕获，单源失败不影响其他源。
    """
    for source in SOURCES:
        try:
            results = source["func"](query, timeout)
            if results:
                log.info("[News] 使用 %s 搜索成功，%d 条结果", source["name"], len(results))
                return results
            log.info("[News] %s 无结果，尝试下一源", source["name"])
        except Exception as exc:
            log.warning("[News] %s 失败: %s", source["name"], exc)
    log.warning("[News] 所有新闻源均失败或无结果")
    return []


# ---- CLI 入口 ----

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args = sys.argv[1:]
    as_json = "--json" in args
    if as_json:
        args.remove("--json")

    query = " ".join(args) if args else "market volatility today"
    results = search_news(query)

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("未获取到新闻数据")
        else:
            for i, r in enumerate(results, 1):
                print(f"{i}. {r['title']}")
                print(f"   {r['snippet'][:100]}...")
                print(f"   {r['link']}")
                print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
