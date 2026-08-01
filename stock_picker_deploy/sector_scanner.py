"""
板块扫描器 — 腾讯实时行情 + 新浪代表股K线历史
直接判断连续上涨天数，不依赖本地缓存。
"""
from datetime import datetime

from data_fetcher import get_sector_fund_flow


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def scan_consecutive_inflow(min_days: int = 2) -> list[dict]:
    """
    扫描连续上涨 >= min_days 的板块。
    基于代表个股的新浪日K线数据 + 腾讯板块实时行情。
    """
    try:
        rows = get_sector_fund_flow()
    except Exception:
        return []

    if not rows:
        return []

    today = _today_str()
    result = []
    for row in rows:
        name = row["板块名称"]
        consecutive = int(row.get("连续上涨天数", 0))
        chg_pct = float(row.get("涨跌幅", 0))
        sector_code = str(row.get("板块代码", ""))

        if consecutive >= min_days and chg_pct > 0:
            result.append({
                "板块名称": name,
                "板块代码": sector_code,
                "涨跌幅": round(chg_pct, 2),
                "连续流入天数": consecutive,
                "扫描时间": today,
            })

    result.sort(key=lambda x: x["连续流入天数"], reverse=True)
    return result
