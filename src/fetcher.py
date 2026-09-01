"""数据获取层：从 Yahoo Finance 拉取 VIX / VXN / MOVE 收盘价。

每个数据源独立容错，单源失败不影响其他源。
"""

from __future__ import annotations

import re
import logging
import threading
from datetime import datetime, timedelta
from time import monotonic, sleep
from urllib.parse import quote

try:
    from zoneinfo import ZoneInfo
    _EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - 仅极老 Python 回退
    from datetime import timezone
    _EASTERN_TZ = timezone.utc

import requests

log = logging.getLogger("marketpulse")

# ---- 常量 ----
# SYMBOLS 顺序：美股大盘（GSPC/IXIC）在前，波动率指数（VIX/VXN/MOVE）在后；
# 顺序决定 context indices、告警收集与报告板块的输出顺序（大盘板块在报告前部）。
SYMBOLS = {
    "GSPC": {"label": "标普500", "source": "yahoo", "ticker": "^GSPC"},
    "IXIC": {"label": "纳斯达克", "source": "yahoo", "ticker": "^IXIC"},
    "SH": {"label": "上证指数", "source": "yahoo", "ticker": "000001.SS"},
    "SZ": {"label": "深证成指", "source": "yahoo", "ticker": "399001.SZ"},
    "CYB": {"label": "创业板指", "source": "yahoo", "ticker": "399006.SZ"},
    "VIX": {"label": "VIX（恐慌指数）", "source": "yahoo", "ticker": "^VIX"},
    "VXN": {"label": "VXN（科技波动）", "source": "yahoo", "ticker": "^VXN"},
    "MOVE": {"label": "MOVE（债市波动）", "source": "yahoo", "ticker": "^MOVE"},
    "GLD": {"label": "黄金 ETF（GLD）", "source": "yahoo", "ticker": "GLD"},
    "BTC": {"label": "比特币（BTC-USD）", "source": "yahoo", "ticker": "BTC-USD"},
}
# 另类资产分组（十期）：不参与告警、不参与波动率板块；纳入日报「💰 另类资产」板块与趋势图。
# 追加在 MOVE 之后（与报告板块顺序一致），历史键自动派生为 gld / btc（daily_report.py 推导覆盖）。
ALT_SYMBOLS = frozenset({"GLD", "BTC"})
# 大盘指数分组（与 SYMBOLS 同处数据注册表）；波动率组 = SYMBOLS 中排除本集合。
# 顺序：美股大盘（GSPC/IXIC）在前、A 股大盘（SH/SZ/CYB）居中、波动率（VIX/VXN/MOVE）在后；
# 该顺序决定 context indices、告警收集与报告板块的输出顺序（六期 B 三板块同序）。
STOCK_SYMBOLS = frozenset({"GSPC", "IXIC", "SH", "SZ", "CYB"})
# A 股大盘分组：用于报告板块拆分（美股 / A 股 / 波动率）与休市判定（六期 B）。
A_SHARE_SYMBOLS = frozenset({"SH", "SZ", "CYB"})
# 七期：快照按市场取子集。PRD 定稿：us 仅大盘（GSPC/IXIC），不含波动率。
MARKETS = {
    "a-share": frozenset({"SH", "SZ", "CYB"}),
    "us": frozenset({"GSPC", "IXIC"}),
    "alt": frozenset({"GLD", "BTC"}),  # 十期：另类资产单板块快照（不参与告警）
}
# 11 个 SPDR 行业 ETF（代码 → 中文行业名），用于美股板块领涨/领跌（与 A 股板块逻辑一致）
US_SECTOR_ETFS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "医疗健康",
    "XLI": "工业",
    "XLP": "必需消费",
    "XLY": "可选消费",
    "XLU": "公用事业",
    "XLB": "原材料",
    "XLRE": "房地产",
    "XLC": "通信服务",
}

# 十五期：开盘分析实时行情注册表（新浪 hq.sinajs.cn）。
REALTIME_URL = "https://hq.sinajs.cn/list={codes}"
# 市场 → {SYMBOLS 键: (新浪代码, 期望名称)}。
# A 股字段序：0名称 1今开 2昨收 3当前价 4最高 5最低 … 30日期 31时间
# 美股字段序：0名称 1当前价 2涨跌幅% 3时间 4涨跌额 5昨收 6今开 7最高 8最低
REALTIME_MARKETS = {
    "a-share": {
        "SH": ("sh000001", "上证指数"),
        "SZ": ("sz399001", "深证成指"),
        "CYB": ("sz399006", "创业板指"),
    },
    "us": {
        "GSPC": ("gb_inx", "标普500指数"),
        "IXIC": ("gb_ixic", "纳斯达克"),
    },
}

TIMEOUT = 15          # 单次请求超时（秒）
SECTOR_TIMEOUT = 10   # 板块热度获取限时（秒）；新浪接口无 timeout，超时返回 [] 不中断日报
RETRIES = 1           # 失败重试次数（共尝试 2 次）

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def fetch_with_retry(name, fn, retries: int = RETRIES):
    """带重试地执行取数函数；全部失败返回 None 并记录日志（不抛给上层）。重试间退避 1s，避免突发限流。"""
    for attempt in range(1, retries + 2):
        try:
            value = fn()
            if value is None:
                raise ValueError("返回空数据")
            return value
        except Exception as exc:
            log.warning("%s 获取失败(第%d次): %s", name, attempt, exc)
            if attempt <= retries:
                sleep(1)
    return None


def fetch_from_akshare(symbol: str) -> float:
    """从 AkShare 新浪接口获取 A 股指数实时价格。"""
    import akshare as ak
    # 转换 ticker 格式：000001.SS → sh000001, 399001.SZ → sz399001
    if symbol.endswith(".SS"):
        ak_symbol = f"sh{symbol[:-3]}"
    elif symbol.endswith(".SZ"):
        ak_symbol = f"sz{symbol[:-3]}"
    else:
        raise ValueError(f"不支持的 AkShare ticker: {symbol}")
    
    # 优先用新浪实时接口（延迟低，代理兼容性好）
    try:
        df = ak.stock_zh_index_spot_sina()
        row = df[df["代码"] == ak_symbol]
        if not row.empty:
            return float(row.iloc[0]["最新价"])
    except Exception:
        pass
    
    # 降级到日线接口
    df = ak.stock_zh_index_daily(symbol=ak_symbol)
    if df.empty:
        raise ValueError(f"AkShare 返回空数据: {symbol}")
    return float(df.iloc[-1]["close"])


def fetch_vix_vxn(symbol: str) -> float:
    """获取指数最近收盘价。A 股走 AkShare（实时性更好），美股/波动率走 Yahoo。"""
    # A 股走 AkShare
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return fetch_from_akshare(symbol)
    # 美股/波动率走 Yahoo
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=TIMEOUT)
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError("Yahoo 返回空图表数据")
    meta = result[0].get("meta", {})
    close = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
    if close is not None:
        return float(close)
    # 兜底：meta 缺价时解析 close 序列最后一个非空收盘（应对 Yahoo 降级响应）
    quote_series = result[0].get("indicators", {}).get("quote", [{}])
    closes = quote_series[0].get("close", []) if quote_series else []
    for v in reversed(closes):
        if v is not None:
            return float(v)
    raise ValueError("Yahoo 返回数据无收盘价")


def fetch_all(market: str | None = None) -> tuple[dict, dict]:
    """依次获取指数；market 指定时仅取该市场子集（a-share/us），None 取全量。
    每个源独立容错，单源失败/跳过不影响其他源。源间节流 2s，降低 Yahoo 突发限流概率。"""
    subset = MARKETS.get(market) if market else None
    values, errors = {}, {}
    first = True
    for sym, meta in SYMBOLS.items():
        if subset is not None and sym not in subset:
            continue
        if not first:
            sleep(2)
        first = False
        ticker = meta["ticker"]
        fetch = lambda t=ticker: fetch_vix_vxn(t)  # noqa: E731
        values[sym] = fetch_with_retry(sym, fetch)
        if values[sym] is None:
            errors[sym] = "获取失败（已重试）"
            log.warning("%s 最终无数据", sym)
        else:
            log.info("%s 收盘价: %.2f", sym, values[sym])
    return values, errors


def _sina_realtime_get(url: str) -> str:
    """单次 GET 新浪实时行情，带 Referer 头；失败抛异常由调用方重试/容错。"""
    resp = _SESSION.get(
        url,
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.text


def _to_float(s: str) -> float | None:
    """字段转 float；空串/0 视为缺失（None，避免跳空除零）；非数值抛 ValueError（由调用方判整行无效）。"""
    s = s.strip()
    if not s:
        return None
    v = float(s)
    return v if v != 0 else None


def parse_sina_realtime(text: str, market: str) -> dict | None:
    """解析单条新浪实时行情 `var hq_str_xxx="..."`（A 股 / 美股两套字段序）。

    返回 {current, prev_close, open}（float）；空串 / 字段不足 / 数值非法 → None（可单测，全 mock）。
    """
    m = re.search(r'=\s*"(.*?)";', text, re.DOTALL)
    if not m:
        return None
    parts = m.group(1).split(",")
    try:
        if market == "a-share":
            # 0名称 1今开 2昨收 3当前价 …
            if len(parts) < 4:
                return None
            return {
                "open": _to_float(parts[1]),
                "prev_close": _to_float(parts[2]),
                "current": _to_float(parts[3]),
            }
        # 美股：0名称 1当前价 2涨跌幅% 3时间 4涨跌额 5昨收 6今开 …
        if len(parts) < 7:
            return None
        return {
            "current": _to_float(parts[1]),
            "prev_close": _to_float(parts[5]),
            "open": _to_float(parts[6]),
        }
    except (ValueError, IndexError):
        return None


def _extract_block(text: str, code: str) -> str | None:
    """从新浪整体响应中提取单个代码对应的 `var hq_str_xxx="..."` 整行。"""
    m = re.search(r'var hq_str_' + re.escape(code) + r'="(.*?)";', text, re.DOTALL)
    return m.group(0) if m else None


def fetch_vix_realtime() -> tuple[float | None, float | None]:
    """取 VIX 实时/最近收盘价与昨收（Yahoo meta regularMarketPrice / chartPreviousClose）。

    新浪无 VIX 数据，开盘情绪走 Yahoo 兜底；失败返回 (None, None) 不抛（设计：降级「数据暂缺」）。
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
        resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=TIMEOUT)
        resp.raise_for_status()
        result = resp.json()["chart"].get("result")
        if not result:
            return None, None
        meta = result[0].get("meta", {})
        current = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")
        return (
            float(current) if current is not None else None,
            float(prev) if prev is not None else None,
        )
    except Exception as exc:
        log.warning("VIX 实时获取失败（开盘情绪降级）: %s", exc)
        return None, None


def fetch_realtime_quotes(market: str) -> tuple[dict, dict]:
    """取开盘分析实时行情：新浪直连指数 + VIX 走 Yahoo 兜底。

    返回 (quotes, errors)；quotes[sym] = {current, prev_close, open}，并含 "VIX" 键（open=None）。
    A 股/美股任一指数解析失败记 errors 不中断；VIX 缺失进 errors、大盘方向仍可用；整体失败返回空 dict + errors。
    """
    quotes: dict = {}
    errors: dict = {}
    mapping = REALTIME_MARKETS.get(market, {})
    if mapping:
        codes = ",".join(code for code, _ in mapping.values())
        url = REALTIME_URL.format(codes=codes)
        try:
            text = fetch_with_retry(f"sina-realtime-{market}", lambda: _sina_realtime_get(url))
        except Exception as exc:
            text = None
            errors["sina"] = str(exc)
        if text is None:
            if "sina" not in errors:
                errors["sina"] = "新浪实时行情获取失败"
        else:
            for sym, (code, _name) in mapping.items():
                block = _extract_block(text, code)
                parsed = parse_sina_realtime(block, market) if block else None
                if parsed is None:
                    errors[sym] = "解析失败"
                else:
                    quotes[sym] = parsed
    # VIX：Yahoo 兜底（新浪无 VIX）
    vix_cur, vix_prev = fetch_vix_realtime()
    if vix_cur is not None:
        quotes["VIX"] = {"current": vix_cur, "prev_close": vix_prev, "open": None}
    else:
        errors["VIX"] = "VIX 获取失败"
    return quotes, errors


# 十八期：概念板块 → 大类聚合映射。键为 10 大类；值为命中即归入该类的概念名列表。
# 以 PRD 表 30 个概念名为基础，叠加新浪实际板块命名别名（实跑 175 板块核对后补，逻辑不变）。
SECTOR_MAPPING: dict[str, list[str]] = {
    "通信/电子": [
        "5G概念", "华为概念", "消费电子", "物联网",
        "华为海思", "华为鸿蒙", "苹果概念", "小米概念", "无线耳机", "智能穿戴",
    ],
    "光伏/新能源": [
        "光伏", "光伏概念", "新能源", "锂矿", "锂电池", "盐湖提锂",
        "氢能源", "氢燃料", "充电桩", "固态电池", "钠电池", "钒电池",
        "风电", "风能", "风能概念", "HIT电池", "TOPCon", "BC电池", "钙钛矿", "电解液",
    ],
    "半导体/芯片": ["芯片", "半导体", "集成电路"],
    "军工": ["国防军工", "军工航天", "军民融合", "卫星导航", "大飞机", "海工装备"],
    "医药": [
        "创新药", "仿制药", "免疫治疗", "CRO概念",
        "CXO概念", "基因概念", "基因测序", "生物疫苗", "抗癌", "民营医院", "超级细菌", "甲型流感",
    ],
    "消费": ["白酒", "食品饮料", "新零售", "白酒概念", "电商概念"],
    "金融": ["券商", "银行", "保险", "券商重仓", "民营银行", "保险重仓", "互联金融", "参股金融", "金融改革"],
    "地产/基建": ["房地产", "基建", "水泥", "土地流转"],
    "资源/有色": ["黄金概念", "有色金属", "稀土", "煤炭", "稀缺资源"],
    "农业": [
        "农业", "养殖", "猪肉",
        "生态农业", "乡村振兴", "鸡肉", "水产品", "生物育种",
    ],
}


def _parse_turnover(text: str) -> float:
    """将板块成交额字符串还原为元：'X.X亿' → ×1e8、'X.X万' → ×1e4、纯数字原值。

    解析失败或空值返回 0.0（权重为 0 的子板块自然不贡献加权）。
    """
    if not text:
        return 0.0
    s = str(text).strip()
    try:
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        return float(s)
    except ValueError:
        return 0.0


def aggregate_sectors(rows: list[dict], top_n: int = 5) -> tuple[list[dict], list[dict]]:
    """将概念板块行聚合为大类板块。

    分组：行 name 命中 SECTOR_MAPPING 任一概念名 → 对应大类；否则归『其他』。
    大类涨跌幅 = Σ(子板块 change × 子板块成交额[元]) / Σ(子板块成交额[元])；
    若 Σ 成交额 == 0（全 0 / 全缺失）→ 该大类简单平均 mean(change)（PRD 约束）。
    top_stock = 类别内成交额最大子板块的 top_stock（代表主权重，决策 2）。
    turnover = 类别合计元 ÷ 1e8 保留 1 位，复用 'X.X亿' 格式（行契约同构）。
    输出：10 映射类 + 『其他』共 11 类（≤15 满足 PRD），gainers 降序 TopN、losers 升序 TopN。
    空输入返回 ([], [])。
    """
    if not rows:
        return ([], [])

    groups: dict[str, list[dict]] = {}
    for r in rows:
        cat = "其他"
        for category, names in SECTOR_MAPPING.items():
            if r["name"] in names:
                cat = category
                break
        groups.setdefault(cat, []).append(r)

    aggregated: list[dict] = []
    for cat, members in groups.items():
        weights = [_parse_turnover(m["turnover"]) for m in members]
        total = sum(weights)
        if total == 0:
            change = sum(m["change"] for m in members) / len(members)
        else:
            change = sum(m["change"] * w for m, w in zip(members, weights)) / total
        top_member = max(members, key=lambda m: _parse_turnover(m["turnover"]))
        aggregated.append({
            "name": cat,
            "change": round(change, 2),
            "turnover": f"{total / 1e8:.1f}亿",
            "top_stock": top_member["top_stock"],
        })

    gainers = sorted(aggregated, key=lambda r: r["change"], reverse=True)[:top_n]
    losers = sorted(aggregated, key=lambda r: r["change"])[:top_n]
    return (gainers, losers)

def fetch_sector_heat(top_n: int = 5) -> tuple[list[dict], list[dict]]:
    """从 AkShare 取全量概念板块，按 SECTOR_MAPPING 聚合为大类后返回（领涨 / 领跌各 Top N，一次取数两路排序）。

    数据源为新浪（money.finance.sina.com.cn），akshare 内部 requests 无 timeout，
    故用 daemon 线程 + join(SECTOR_TIMEOUT) 限时；超时 / 异常 / 缺必需列均返回 ([], [])，
    不中断日报主流程。返回 (gainers, losers)：
      - gainers：按涨跌幅降序 Top N，[{name, change, turnover, top_stock}]
      - losers：按涨跌幅升序 Top N，字段同（most-negative 在前）
    turnover 为「X.X亿」（总成交额[元] ÷ 1e8 保留 1 位）。
    """
    required_cols = ["板块", "涨跌幅", "总成交额", "股票名称"]
    holder: dict = {}

    def _build_rows(df) -> list[dict]:
        rows = []
        for _, r in df.iterrows():
            change = float(r["涨跌幅"])
            turnover_yuan = float(r["总成交额"])
            rows.append({
                "name": str(r["板块"]),
                "change": round(change, 2),
                "turnover": f"{turnover_yuan / 1e8:.1f}亿",
                "top_stock": str(r["股票名称"]),
            })
        return rows


    def _worker() -> None:
        try:
            import akshare as ak
            df = ak.stock_sector_spot(indicator="概念")
            if df is None or len(df) == 0:
                raise ValueError("AkShare 概念板块返回空数据")
            for col in required_cols:
                if col not in df.columns:
                    raise KeyError(f"概念板块数据缺少必需列: {col}")
            all_rows = _build_rows(df)
            gainers, losers = aggregate_sectors(all_rows, top_n)
            holder["rows"] = (gainers, losers)
        except Exception as exc:
            log.warning("板块热度获取失败: %s", exc)
            holder["rows"] = ([], [])

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(SECTOR_TIMEOUT)
    if t.is_alive():
        log.warning("板块热度获取超时（>%ds），跳过", SECTOR_TIMEOUT)
        return ([], [])
    return holder.get("rows", ([], []))


def _fmt_us_volume(dollars: float) -> str:
    """美股 ETF 美元成交额格式化：$X.XB / $X.XM / $X.XK。"""
    if dollars >= 1e9:
        return f"${dollars / 1e9:.1f}B"
    if dollars >= 1e6:
        return f"${dollars / 1e6:.1f}M"
    if dollars >= 1e3:
        return f"${dollars / 1e3:.1f}K"
    return f"${dollars:.0f}"


def fetch_us_sector_heat(top_n: int = 5) -> tuple[list[dict], list[dict]]:
    """从 Yahoo Finance 获取 11 个 SPDR 行业 ETF 涨跌幅，返回 (gainers, losers)。

    每个 ETF 独立线程并行取数（Yahoo chart REST），整体限时 SECTOR_TIMEOUT；
    超时 / 异常 / 缺必需字段均返回 ([], [])，不中断日报主流程。
    返回格式与 A 股板块一致：[{name, change, turnover, top_stock}]，
    name 为「行业 (代码)」，top_stock 为 ETF 代码。
    """
    results: list[dict] = []
    lock = threading.Lock()

    def _one(ticker: str, label: str) -> None:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
            resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=TIMEOUT)
            resp.raise_for_status()
            r = resp.json()["chart"].get("result")
            if not r:
                raise ValueError("Yahoo 返回空图表数据")
            meta = r[0].get("meta", {})
            change = meta.get("regularMarketChangePercent")
            price = meta.get("regularMarketPrice")
            volume = meta.get("regularMarketVolume")
            if change is None or price is None:
                raise ValueError("Yahoo 缺涨跌幅/价格")
            dollar_vol = float(volume) * float(price) if volume else 0.0
            row = {
                "name": f"{label} ({ticker})",
                "change": round(float(change), 2),
                "turnover": _fmt_us_volume(dollar_vol),
                "top_stock": ticker,
            }
            with lock:
                results.append(row)
        except Exception as exc:
            log.warning("美股板块 %s 获取失败: %s", ticker, exc)

    threads = [
        threading.Thread(target=_one, args=(t, l), daemon=True)
        for t, l in US_SECTOR_ETFS.items()
    ]
    for t in threads:
        t.start()
    deadline = monotonic() + SECTOR_TIMEOUT
    for t in threads:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        t.join(remaining)
    if any(t.is_alive() for t in threads):
        log.warning("美股板块获取超时（>%ds），跳过", SECTOR_TIMEOUT)
        return ([], [])
    if not results:
        return ([], [])
    gainers = sorted(results, key=lambda r: r["change"], reverse=True)[:top_n]
    losers = sorted(results, key=lambda r: r["change"])[:top_n]
    return (gainers, losers)


# ---- 二十四期：自选股/持仓取数 ----
def _fetch_yahoo_watch(symbol: str) -> tuple[float, list]:
    """Yahoo chart REST 取美股/ETF 当日价 + 近 30 日收盘序列（range=1mo, interval=1d）。

    当日价取 meta.regularMarketPrice（缺失回退序列末值）；序列时间戳转美东日期，
    与 history.json 美东 date 键对齐。返回 (value, [(date, close), ...])。
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    resp = _SESSION.get(url, params={"interval": "1d", "range": "1mo"}, timeout=TIMEOUT)
    resp.raise_for_status()
    r = resp.json()["chart"].get("result")
    if not r:
        raise ValueError("Yahoo 返回空图表数据")
    res = r[0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    quotes = res.get("indicators", {}).get("quote", [{}])
    closes = quotes[0].get("close", []) if quotes else []
    series = []
    for t, c in zip(ts, closes):
        if c is None or t is None:
            continue
        dt = datetime.fromtimestamp(t, _EASTERN_TZ).strftime("%Y-%m-%d")
        series.append((dt, float(c)))
    if not series:
        raise ValueError("Yahoo 序列为空")
    value = meta.get("regularMarketPrice")
    if value is None:
        value = series[-1][1]
    return float(value), series


def _fetch_a_share_watch(symbol: str) -> tuple[float, list]:
    """AkShare 东财日线取 A 股(.SS/.SZ) 当日收盘价 + 近 ~30 交易日序列。

    symbol 去掉后缀作 AkShare 代码；取 70 个自然日确保覆盖 ≥30 交易日。日期列与
    history.json 美东 date 键同日对齐（A 股 15:00 北京 = 美东当日）。返回 (value, [(date, close), ...])。
    """
    import akshare as ak
    code = symbol[:-3]  # 去掉 .SS / .SZ
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=70)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="")
    if df is None or len(df) == 0:
        raise ValueError(f"AkShare 返回空数据: {symbol}")
    series = []
    for _, row in df.iterrows():
        d = row["日期"]
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        series.append((d_str, float(row["收盘"])))
    if not series:
        raise ValueError(f"AkShare 序列为空: {symbol}")
    return float(series[-1][1]), series


def fetch_watchlist(stocks: list[dict]) -> tuple[dict, dict, dict]:
    """取自选股数据：返回 (values, series, errors)。

    values[symbol]=当日收盘价；series[symbol]=[(date, close), ...] 近 30 日（含当日）；
    errors[symbol]=错误信息（取数失败/超时）。逐标的并行线程 + 整体限时 SECTOR_TIMEOUT，
    单标的失败置 None 不中断，全失败返回空 dict。美股/ETF 走 Yahoo；A 股(.SS/.SZ) 走 AkShare。
    """
    results: dict = {}
    lock = threading.Lock()

    def _one(item: dict) -> None:
        sym = item.get("symbol")
        entry = {"value": None, "series": None, "error": None}
        try:
            if not sym:
                raise ValueError("条目缺 symbol")
            if sym.endswith(".SS") or sym.endswith(".SZ"):
                entry["value"], entry["series"] = _fetch_a_share_watch(sym)
            else:
                entry["value"], entry["series"] = _fetch_yahoo_watch(sym)
        except Exception as exc:
            entry["error"] = str(exc)
            log.warning("自选股 %s 获取失败: %s", sym, exc)
        with lock:
            results[sym] = entry

    threads = [threading.Thread(target=_one, args=(it,), daemon=True) for it in stocks]
    for t in threads:
        t.start()
    deadline = monotonic() + SECTOR_TIMEOUT
    for t in threads:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        t.join(remaining)
    if any(t.is_alive() for t in threads):
        log.warning("自选股获取超时（>%ds），未完成标的信息缺失", SECTOR_TIMEOUT)

    values, series, errors = {}, {}, {}
    for it in stocks:
        sym = it.get("symbol")
        r = results.get(sym)
        if r is None or r["value"] is None:
            errors[sym] = r["error"] if r else "未完成（超时/未返回）"
        else:
            values[sym] = r["value"]
            series[sym] = r["series"]
    return values, series, errors
