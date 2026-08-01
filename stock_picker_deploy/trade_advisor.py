"""
交易建议 — ATR 波动率自适应算法
"""
import math


def advise(stock_analysis: dict, klines: list[dict] = None) -> dict:
    """
    基于 ATR(14) 的智能止损止盈。
    买点取 MA20 附近（不低于 20 日低点）
    止损 = 买点 − 1.5×ATR（不低于 20 日最低点）
    止盈 = 买点 + 2×ATR / 3×ATR / 60日最高点
    """
    cur = float(stock_analysis.get("最新价", 0))
    if cur <= 0:
        return _empty()

    # 取K线数据
    if klines is None:
        klines = stock_analysis.get("近5日K线", [])  # 不足，需要更多
    if len(klines) < 20:
        # fallback：从新浪K线取更长的数据
        from data_fetcher import get_sina_klines_batch
        code = stock_analysis.get("代码", "")
        if code:
            kmap = get_sina_klines_batch([code])
            kb = kmap.get(code, {})
            klines = (kb.get("klines_60d") or kb.get("klines_20d") or [])

    if len(klines) < 14:
        return _fallback(cur)

    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]

    # ATR(14)
    tr_list = []
    for i in range(1, len(klines)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr_list.append(max(hl, hc, lc))
    atr = sum(tr_list[-14:]) / 14

    # 支撑位：MA20 或 20日最低点
    c20 = closes[-20:]
    ma20 = sum(c20) / len(c20)
    low20 = min(lows[-20:])

    # 买点：当前位置决定
    if cur <= ma20:
        # 当前价低于均线 → 逢低买入，取当前价附近但不低于20日低点
        buy = max(cur, low20)
    elif cur <= ma20 * 1.05:
        # 均线附近 → 以均线为买点
        buy = ma20
    else:
        # 远高于均线 → 等回调买均线
        buy = ma20
    buy = round(buy, 2)

    # 止损：买点 − 1.5×ATR，不低于 20 日最低点
    stop = max(buy - 1.5 * atr, low20)
    stop = round(stop, 2)

    # 止盈
    tp1 = round(buy + 2 * atr, 2)
    tp2 = round(buy + 3 * atr, 2)
    high60 = max(highs[-60:]) if len(highs) >= 60 else max(highs)
    tp3 = round(min(buy + 5 * atr, high60), 2)

    # 盈亏比
    risk = buy - stop
    reward1 = tp1 - buy
    rr = round(reward1 / risk, 1) if risk > 0 else 0

    # 风险提示
    risks = []
    dev = (cur - buy) / buy * 100 if buy > 0 else 0
    if dev > 10:
        risks.append(f"当前价高于建议买点{dev:.0f}%，追高风险较大")
    elif dev < -5:
        risks.append(f"当前价低于建议买点{dev:.0f}%，已触发止损参考区")
    if stop >= buy:
        risks.append("止损价高于买点，波动过大，建议观望")

    return {
        "建议买点": round(buy, 2),
        "止损价": stop,
        "止盈档位": [
            {"价格": tp1, "涨幅": f"+{round(tp1/buy*100-100,1)}%", "说明": "第一档: 2×ATR，减仓1/3"},
            {"价格": tp2, "涨幅": f"+{round(tp2/buy*100-100,1)}%", "说明": "第二档: 3×ATR，再减1/3"},
            {"价格": tp3, "涨幅": f"+{round(tp3/buy*100-100,1)}%", "说明": f"第三档: 逼近60日高点，清仓"},
        ],
        "盈亏比": f"1:{rr}" if rr > 0 else "数据不足",
        "ATR": round(atr, 2),
        "风险提示": risks if risks else ["无显著风险信号"],
    }


def _empty():
    return {"建议买点": "数据不足", "止损价": "数据不足", "止盈档位": [], "盈亏比": "数据不足", "风险提示": ["K线数据缺失"]}


def _fallback(cur: float):
    return {
        "建议买点": round(cur * 0.98, 2),
        "止损价": round(cur * 0.95, 2),
        "止盈档位": [
            {"价格": round(cur * 1.05, 2), "涨幅": "+5%", "说明": "第一档: 固定5%"},
            {"价格": round(cur * 1.10, 2), "涨幅": "+10%", "说明": "第二档: 固定10%"},
        ],
        "盈亏比": "数据不足",
        "风险提示": ["ATR数据不足，使用固定比例"],
    }
