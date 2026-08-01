"""
交易建议 — 基于均线价格
"""
import math


def advise(stock_analysis: dict) -> dict:
    avg_60 = float(stock_analysis.get("60日均价", 0))
    avg_5 = float(stock_analysis.get("近5日均价", 0))
    cur_price = float(stock_analysis.get("最新价", 0))

    # 基准价格：优先60日均线，其次5日均线
    if avg_60 > 0:
        base_price = avg_60
    elif avg_5 > 0:
        base_price = avg_5
    else:
        return {"建议买点": "数据不足", "止损价": "数据不足", "止盈档位": [], "风险提示": ["均线数据缺失"]}

    buy_price = round(base_price * 0.98, 2)
    stop_loss = round(base_price * 0.95, 2)

    take_profit = [
        {"价格": round(base_price * 1.05, 2), "涨幅": "+5%", "说明": "第一档：回到均线上方，减仓1/3"},
        {"价格": round(base_price * 1.10, 2), "涨幅": "+10%", "说明": "第二档：脱离成本区，再减1/3"},
        {"价格": round(base_price * 1.20, 2), "涨幅": "+20%", "说明": "第三档：趋势延续，清仓"},
    ]

    risks = []
    if cur_price > 0 and base_price > 0:
        ratio = (cur_price - base_price) / base_price * 100
        if ratio > 20:
            risks.append(f"当前价高于均线{ratio:.0f}%，追高风险较大")
        elif ratio < -15:
            risks.append(f"当前价低于均线{ratio:.0f}%，可能继续下跌")

    consecutive = int(stock_analysis.get("连续上涨天数", 0))
    if consecutive < 3 and consecutive > 0:
        risks.append(f"仅连续上涨{consecutive}天，趋势确认偏弱")
    elif consecutive == 0:
        risks.append("近期无连续上涨，资金面信号不足")

    return {
        "建议买点": buy_price,
        "止损价": stop_loss,
        "止盈档位": take_profit,
        "风险提示": risks if risks else ["无显著风险信号"],
    }
