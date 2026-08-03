"""
推荐评分引擎 — 多维度打分，辅助选股决策
v2: 研报过滤 + 流动性过滤
"""
import json
import math


def score_stocks(
    codes: list[str],
    kline_data: dict,
    quotes: dict,
    research_data: dict = None,
    liquidity_data: dict = None,
) -> list[dict]:
    """
    对一批股票打分，返回带评分的结果列表。

    codes: 股票代码列表
    kline_data: {code: {klines_20d, klines_60d}} — 来自 Sina K 线
    quotes: {code: {名称, 最新价, 涨跌幅, 换手率, 量比, 总股本}} — 来自腾讯
    research_data: {code: {count, buy_ratio, ratings}} — 可选，用于研报过滤
    liquidity_data: {code: avg_turnover_wan} — 可选，用于流动性过滤
    """
    research_data = research_data or {}
    liquidity_data = liquidity_data or {}

    results = []
    for code in codes:
        kd = kline_data.get(code, {})
        q = quotes.get(code, {})
        name = q.get("名称", code)

        # 硬过滤1：流动性不足
        avg_turnover = liquidity_data.get(code, 0)
        if avg_turnover and avg_turnover < 3000:
            continue  # 5日均成交额 < 3000万 → 踢出

        # 硬过滤2：0研报覆盖
        rd = research_data.get(code, {})
        report_count = rd.get("count", -1)
        if report_count == 0:
            continue  # 过去90天无研报 → 不进候选

        score, detail = _score_one(code, q, kd)

        # 研报减半分：买入比 < 50%
        if report_count > 0 and rd.get("buy_ratio", 0) < 0.5:
            score = max(score // 2, 10)
            detail["研报"] = f"买入比{rd['buy_ratio']*100:.0f}%→减半"

        results.append({
            "代码": code,
            "名称": name,
            "最新价": q.get("最新价", 0),
            "涨跌幅": q.get("涨跌幅", 0),
            "评分": score,
            "评分明细": detail,
            "推荐": "⭐" if score >= 60 and not _is_st(name) else "",
        })
    results.sort(key=lambda x: x["评分"], reverse=True)
    return results


def _is_st(name: str) -> bool:
    return "ST" in name.upper() or "*ST" in name.upper()


def _score_one(code: str, quote: dict, kline: dict) -> tuple:
    """返回 (总分, 明细)"""
    detail = {}
    total = 0

    if not kline:
        return total, detail

    k20 = kline.get("klines_20d", [])
    k60 = kline.get("klines_60d", [])
    k120 = kline.get("klines_120d", [])

    if not k20:
        return total, detail

    closes_20 = [k["close"] for k in k20]
    closes_60 = [k["close"] for k in k60] if k60 else closes_20
    closes_120 = [k["close"] for k in k120] if k120 else closes_60
    volumes_20 = [k["volume"] for k in k20]

    cur = quote.get("最新价", closes_20[-1] if closes_20 else 0)

    # === 1. 趋势强度 (25分) ===
    cons_up = 0
    for i in range(len(closes_20) - 1, 0, -1):
        if closes_20[i] > closes_20[i - 1]:
            cons_up += 1
        else:
            break
    if cur > closes_20[-1]:
        cons_up += 1
    trend_score = min(cons_up * 6, 25)
    detail["趋势"] = f"{cons_up}天连续上涨"
    total += trend_score

    # === 2. 短期动量 (15分) ===
    if len(closes_20) >= 5:
        chg_5d = (closes_20[-1] - closes_20[-5]) / closes_20[-5] * 100
    else:
        chg_5d = 0
    momentum_score = min(max(int(chg_5d * 3 + 5), 0), 15)
    detail["动量"] = f"5日涨{chg_5d:+.1f}%"
    total += momentum_score

    # === 3. 均线位置 (15分) ===
    if closes_60:
        ma60 = sum(closes_60) / len(closes_60)
        dev = (cur - ma60) / ma60 * 100
        if -5 <= dev <= 5:
            ma_score = 15
        elif -15 <= dev <= 15:
            ma_score = 10
        else:
            ma_score = 5
        detail["均线"] = f"偏离60日线{dev:+.0f}%"
    else:
        ma_score = 7
        detail["均线"] = "数据不足"
    total += ma_score

    # === 4. 主力资金代理 (20分) ===
    vol_score = 0
    if len(volumes_20) >= 5:
        avg_vol_5 = sum(volumes_20[-5:]) / 5
        today_vol = volumes_20[-1]
        vol_ratio = today_vol / avg_vol_5 if avg_vol_5 > 0 else 1
        if vol_ratio > 1.5:
            vol_score += 12
            detail["量"] = f"放量{vol_ratio:.1f}x"
        elif vol_ratio > 1.2:
            vol_score += 8
            detail["量"] = f"温和放量{vol_ratio:.1f}x"
        elif vol_ratio > 0.8:
            vol_score += 4
            detail["量"] = "量能正常"
        else:
            detail["量"] = "缩量"

        # 连续放量天数
        vol_up_days = 0
        for i in range(len(volumes_20) - 1, 0, -1):
            if volumes_20[i] > volumes_20[i - 1]:
                vol_up_days += 1
            else:
                break
        vol_score += min(vol_up_days * 2, 8)
    detail["资金"] = detail.get("量", "") + ("+" + str(vol_up_days) + "天放量" if vol_up_days > 0 else "")
    total += vol_score

    # === 5. 真实业绩代理 (15分) ===
    quality_score = 0
    # 非 ST
    if not _is_st(quote.get("名称", "")):
        quality_score += 5
        detail["ST"] = "正常"
    else:
        detail["ST"] = "⚠ST"
    # 均线多头排列：20日线 > 60日线
    if closes_20 and closes_60:
        ma20_val = sum(closes_20[-20:]) / min(20, len(closes_20))
        ma60_val = sum(closes_60) / len(closes_60)
        if ma20_val > ma60_val:
            quality_score += 5
            detail["均线排列"] = "多头"
        else:
            detail["均线排列"] = "空头"
    # 120日涨幅 > 0
    if len(closes_120) >= 2:
        chg_120 = (closes_120[-1] - closes_120[0]) / closes_120[0] * 100
        if chg_120 > 0:
            quality_score += 5
        detail["业绩代理"] = f"120日涨{chg_120:+.1f}%"
    else:
        detail["业绩代理"] = "数据不足"
    total += quality_score

    # === 6. 换手活跃 (10分) ===
    turnover = quote.get("换手率", 0)
    if 1 <= turnover <= 5:
        turnover_score = 10
    elif 0.5 <= turnover <= 10:
        turnover_score = 6
    else:
        turnover_score = 2
    detail["换手"] = f"{turnover:.1f}%"
    total += turnover_score

    return total, detail
