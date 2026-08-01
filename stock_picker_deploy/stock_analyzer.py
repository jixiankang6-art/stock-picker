"""
个股深度分析器
"""
import json
import math
from datetime import datetime

from data_fetcher import (
    get_stocks_quote_extra,
    get_stock_business,
    get_stock_concepts,
    _curl_text,
)


def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (ValueError, TypeError):
        return default


def analyze_stock(code: str) -> dict:
    result = {"代码": code, "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 1. 腾讯增强行情
    quotes = get_stocks_quote_extra([code])
    q = quotes.get(code, {})

    result["股票简称"] = q.get("名称", code)
    result["最新价"] = q.get("最新价", 0)
    result["换手率"] = q.get("换手率", 0)
    result["量比"] = q.get("量比", 0)
    result["总股本"] = q.get("总股本", 0)

    # 计算市值
    if result["总股本"] > 0 and result["最新价"] > 0:
        mcap = result["总股本"] * result["最新价"]
        if mcap > 1000e8:
            result["市值量级"] = "大盘股 (>1000亿)"
        elif mcap > 300e8:
            result["市值量级"] = "中盘股 (300-1000亿)"
        elif mcap > 50e8:
            result["市值量级"] = "小盘股 (50-300亿)"
        else:
            result["市值量级"] = "微盘股 (<50亿)"
    else:
        result["市值量级"] = "未知"

    # 2. 新浪 K线
    klines = _get_sina_klines_raw(code, 60)
    k20 = klines[-20:] if len(klines) >= 20 else klines
    k60 = klines[-60:] if len(klines) >= 60 else klines
    k120 = klines[-120:] if len(klines) >= 120 else klines

    closes_20 = [k["close"] for k in k20]
    closes_60 = [k["close"] for k in k60]
    closes_120 = [k["close"] for k in k120]

    result["近5日K线"] = k20[-5:] if len(k20) >= 5 else k20

    # 连续上涨天数
    cons = 0
    for i in range(len(closes_20) - 1, 0, -1):
        if closes_20[i] > closes_20[i - 1]:
            cons += 1
        else:
            break
    if result["最新价"] > closes_20[-1] if closes_20 else 0:
        cons += 1
    result["连续上涨天数"] = cons

    # 3日/5日涨幅
    result["3日涨幅"] = _calc_chg(closes_20, 3)
    result["5日涨幅"] = _calc_chg(closes_20, 5)

    # MA5/10/20
    result["MA5"] = round(sum(closes_20[-5:]) / min(5, len(closes_20)), 2) if closes_20 else 0
    result["MA10"] = round(sum(closes_20[-10:]) / min(10, len(closes_20)), 2) if len(closes_20) >= 10 else 0
    result["MA20"] = round(sum(closes_20[-20:]) / min(20, len(closes_20)), 2) if len(closes_20) >= 20 else 0

    # 近5日均价 / 60日均价
    result["近5日均价"] = round(sum(closes_20[-5:]) / min(5, len(closes_20)), 2) if closes_20 else 0
    if closes_60:
        ma60 = sum(closes_60) / len(closes_60)
        result["60日均价"] = round(ma60, 2)
        if result["最新价"] > 0:
            dev = (result["最新价"] - ma60) / ma60 * 100
            result["偏离60日线"] = f"{dev:+.1f}%"
            if dev < -15: result["筹码信号"] = "深度超跌，底部区域"
            elif dev < -5: result["筹码信号"] = "低于均线，偏低估"
            elif dev < 5: result["筹码信号"] = "均线附近，均衡"
            elif dev < 15: result["筹码信号"] = "高于均线，偏强势"
            else: result["筹码信号"] = "大幅高于均线，注意回调"

    # 3. 业务描述（emweb）
    biz = _try(lambda: get_stock_business(code)) or {}
    result["公司简介"] = biz.get("简介", "")
    result["经营范围"] = biz.get("经营范围", "")
    result["主营业务"] = biz.get("主营业务", "")
    result["所属行业"] = biz.get("所属行业", "")

    # 4. 概念板块
    concepts = _try(lambda: get_stock_concepts(code)) or []
    result["概念板块"] = concepts[:10]

    return result


def _get_sina_klines_raw(code: str, count: int) -> list[dict]:
    symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={count}"
    )
    text = _curl_text(url, timeout=10)
    if not text:
        return []
    try:
        data = json.loads(text)
        return [
            {"date": k["day"], "open": float(k["open"]), "high": float(k["high"]),
             "low": float(k["low"]), "close": float(k["close"]), "volume": int(k["volume"])}
            for k in data if k.get("close")
        ]
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def _calc_chg(closes: list, days: int) -> float:
    if len(closes) <= days:
        return 0
    return round((closes[-1] - closes[-days-1]) / closes[-days-1] * 100, 2)


def _try(func, default=None):
    try:
        return func()
    except Exception:
        return default
