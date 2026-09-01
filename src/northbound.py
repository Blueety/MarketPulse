"""北向资金获取模块：A 股沪深港通净流入数据。

降级链：adata → 返回 None。所有源失败时返回 None，不抛异常（容错第一）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

log = logging.getLogger("marketpulse")


def fetch_northbound_flow() -> dict | None:
    """获取北向资金数据，按优先级降级：adata → 返回 None。

    所有源失败时返回 None，不抛异常（容错第一）。
    """
    # 1. 尝试 adata
    try:
        data = _fetch_via_adata()
        if data is not None and data.get("net_inflow") is not None:
            return data
    except Exception as exc:
        log.warning("adata 北向资金获取失败: %s", exc)

    # 2. 所有源失败
    log.warning("所有北向资金数据源均失败，返回 None")
    return None


def _fetch_via_adata() -> dict | None:
    """通过 adata 获取北向资金数据（线程限时 15s）。

    返回统一格式 dict 或 None（失败/超时/空数据）。
    """
    import adata.sentiment  # 懒加载

    result: list = [None]

    def _do_fetch():
        try:
            df = adata.sentiment.north.north_flow()
            result[0] = df
        except Exception as exc:
            result[0] = exc

    t = threading.Thread(target=_do_fetch, daemon=True)
    t.start()
    t.join(15)

    if isinstance(result[0], Exception):
        raise result[0]
    if result[0] is None:
        log.warning("adata 北向资金获取超时（15s）")
        return None

    df = result[0]
    if df is None or df.empty:
        return None

    # 取最新一行（第一行是最新日期）
    row = df.iloc[0]

    # 获取日期
    trade_date = row.get("trade_date", "")
    if not trade_date:
        return None

    # net_tgt = 合计净买入金额（元），需转换为亿元
    # net_hgt = 沪港通净买入金额（元）
    # net_sgt = 深港通净买入金额（元）
    net_tgt = row.get("net_tgt", 0)
    net_hgt = row.get("net_hgt", 0)
    net_sgt = row.get("net_sgt", 0)

    # 如果所有值都是 NaN，视为数据缺失
    if net_tgt is None or (isinstance(net_tgt, float) and str(net_tgt) == "nan"):
        return None

    # 转换为亿元
    net_inflow = float(net_tgt) / 1e8
    sh_net = float(net_hgt) / 1e8
    sz_net = float(net_sgt) / 1e8

    # 格式化日期
    date_str = str(trade_date)[:10]  # YYYY-MM-DD

    log.info("北向资金获取成功: 日期=%s 净流入=%.2f亿", date_str, net_inflow)
    return {
        "net_inflow": net_inflow,
        "sh_net": sh_net,
        "sz_net": sz_net,
        "date": date_str,
    }
