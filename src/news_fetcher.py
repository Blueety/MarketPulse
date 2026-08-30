"""新闻搜索：Tavily 单源。

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

import requests

log = logging.getLogger("news_fetcher")


def _load_env(key: str) -> str:
    """从环境变量或 .env 文件读取 key（环境变量优先）。"""
    val = os.environ.get(key, "")
    if val:
        return val
    for dotenv in [Path(__file__).resolve().parent.parent / ".env",
                   Path(r"D:/hermes/.env"),
                   Path.home() / ".hermes" / ".env"]:
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line[len(key) + 1:].strip().strip("'\"")
    return ""


def _make_result(title: str, snippet: str, link: str, date: str = "") -> dict:
    return {"title": title, "snippet": snippet, "link": link, "date": date}


def search_news(query: str, timeout: int = 10) -> list[dict]:
    """通过 Tavily 搜索新闻。返回统一格式结果列表。"""
    api_key = _load_env("TAVILY_API_KEY")
    if not api_key:
        log.warning("[News] TAVILY_API_KEY 未配置，跳过搜索")
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": 5,
        "search_depth": "basic",
    }
    try:
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
        log.info("[News] Tavily 搜索成功，%d 条结果", len(results))
        return results
    except Exception as exc:
        log.warning("[News] Tavily 搜索失败: %s", exc)
        return []


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
