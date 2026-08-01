"""
股票投资选择 Web App — Flask 后端
"""
import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sector_scanner import scan_consecutive_inflow
from stock_analyzer import analyze_stock
from trade_advisor import advise
from data_fetcher import get_market_indices, get_sector_major_stocks, _PT_SECTOR_MAP, _curl_text

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"


# ---- 自选股池工具 ----

def _load_watchlist() -> list[dict]:
    if WATCHLIST_FILE.exists():
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return []


def _save_watchlist(data: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 页面 ----

@app.route("/")
def index():
    return render_template("index.html")


# ---- API ----

@app.route("/api/market")
def api_market():
    """大盘概览 — 主要指数行情"""
    try:
        data = get_market_indices()
        return jsonify({"code": 0, "data": data})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": []})


@app.route("/api/sectors")
def api_sectors():
    """扫描板块"""
    try:
        sectors = scan_consecutive_inflow(min_days=2)
        return jsonify({"code": 0, "data": sectors, "count": len(sectors)})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": []})


@app.route("/api/stock/<code>")
def api_stock_analyze(code: str):
    """个股深度分析"""
    try:
        result = analyze_stock(code)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": None})


@app.route("/api/sector/<name>/stocks")
def api_sector_stocks(name: str):
    """某板块全部成分股（从缓存查，自动模糊匹配申万←东财行业名）"""
    try:
        from build_stock_map import load_cache

        cache = load_cache()
        if not cache:
            return jsonify({"code": -1, "msg": "行业映射缓存未就绪，请稍后重试", "data": []})

        # 申万一级行业 → 东财行业关键词映射
        keywords = _get_industry_keywords(name)
        if not keywords:
            return jsonify({"code": -1, "msg": f"未找到「{name}」板块映射", "data": []})

        stocks = []
        for code, info in cache.items():
            ind = info.get("industry", "")
            for kw in keywords:
                if kw in ind:
                    stocks.append({"代码": code, "名称": info["name"], "行业": ind})
                    break

        if not stocks:
            return jsonify({"code": -1, "msg": f"「{name}」板块无匹配成分股", "data": []})

               # 补实时行情
        codes = [s["代码"] for s in stocks]
        quote_map = _batch_quote(codes[:300])

        result = []
        for s in stocks:
            code = s["代码"]
            q = quote_map.get(code, {})
            result.append({
                "代码": code, "名称": q.get("名称", s["名称"]),
                "最新价": q.get("最新价", 0), "涨跌幅": q.get("涨跌幅", 0),
                "评分": 0, "评分明细": {}, "推荐": "",
            })
        result.sort(key=lambda x: x["涨跌幅"], reverse=True)
        return jsonify({"code": 0, "data": result, "count": len(result)})

    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": []})


def _get_industry_keywords(sector_name: str) -> list[str]:
    """申万一级行业 → 东财行业关键词"""
    mapping = {
        "电子": ["半导体","电子元件","光学光电子","消费电子","其他电子"],
        "计算机": ["互联网服务","软件服务","软件开发","计算机设备","IT服务"],
        "通信": ["通讯行业","通信设备","通信服务"],
        "医药生物": ["医疗器械","医药制造","生物制品","中药","医疗服务","医药"],
        "房地产": ["房地产"],
        "有色金属": ["有色金属","小金属","贵金属","能源金属","金属"],
        "社会服务": ["旅游酒店","教育","专业服务"],
        "机械设备": ["专用设备","通用设备","机械行业","仪器仪表"],
        "综合": ["综合行业","综合"],
        "银行": ["银行"],
        "汽车": ["汽车行业","汽车零部件","汽车"],
        "家用电器": ["家电行业","家电"],
        "食品饮料": ["食品饮料","食品","饮料","酿酒"],
        "农林牧渔": ["农牧饲渔","农业","牧渔"],
        "基础化工": ["化工行业","化学原料","化学制品","化学"],
        "钢铁": ["钢铁行业","钢铁"],
        "公用事业": ["电力行业","燃气","水务"],
        "纺织服饰": ["纺织服装","纺织"],
        "商贸零售": ["商业百货","零售","贸易"],
        "轻工制造": ["造纸印刷","包装材料","家用轻工"],
        "交通运输": ["交运物流","交运设备","交通运输"],
        "建筑装饰": ["工程建设","装修装饰"],
        "建筑材料": ["装修建材","水泥建材","玻璃"],
        "电力设备": ["输配电气","电网设备","光伏设备","电池","风电"],
        "国防军工": ["航天航空","船舶制造","军工"],
        "非银金融": ["券商信托","保险","多元金融"],
        "石油石化": ["石油行业","石化"],
        "煤炭": ["煤炭"],
        "美容护理": ["美容","化妆"],
        "环保": ["环保工程","环保行业"],
        "传媒": ["文化传媒","影视","游戏"],
    }
    return mapping.get(sector_name, [sector_name])


def _batch_quote(codes: list[str]) -> dict:
    """批量获取腾讯行情"""
    if not codes:
        return {}
    tx_codes = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes]
    text = _curl_text(f"https://qt.gtimg.cn/q={','.join(tx_codes)}")
    result = {}
    for line in text.strip().split("\n"):
        if '="' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 5:
            continue
        code = parts[2]
        cur = float(parts[3]) if parts[3] else 0
        prev = float(parts[4]) if parts[4] else cur
        result[code] = {
            "名称": parts[1], "最新价": cur,
            "涨跌幅": round((cur - prev) / prev * 100, 2) if prev else 0,
        }
    return result


@app.route("/api/stock/<code>/advise")
def api_stock_advise(code: str):
    """交易建议"""
    try:
        analysis = analyze_stock(code)
        result = advise(analysis)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": None})


@app.route("/api/kline/<code>")
def api_kline(code: str):
    """个股K线数据 — 供纯前端调用"""
    days = request.args.get("days", "120")
    try:
        from data_fetcher import get_sina_klines_batch
        klines_map = get_sina_klines_batch([code])
        klines = klines_map.get(code, {})
        return jsonify({"code": 0, "data": klines})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e), "data": {}})


# ---- 自选股池 ----

@app.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
def api_watchlist():
    if request.method == "GET":
        return jsonify({"code": 0, "data": _load_watchlist()})

    elif request.method == "POST":
        body = request.get_json(force=True)
        code = body.get("code", "").strip()
        name = body.get("name", "").strip()
        if not code:
            return jsonify({"code": -1, "msg": "缺少股票代码"})
        wl = _load_watchlist()
        if any(item["code"] == code for item in wl):
            return jsonify({"code": -1, "msg": f"{code} 已在自选池中"})
        wl.append({"code": code, "name": name, "added_at": request.args.get("t", "")})
        _save_watchlist(wl)
        return jsonify({"code": 0, "data": wl})

    elif request.method == "DELETE":
        code = request.args.get("code", "")
        if not code:
            body = request.get_json(force=True) if request.is_json else {}
            code = body.get("code", "")
        wl = _load_watchlist()
        wl = [item for item in wl if item["code"] != code]
        _save_watchlist(wl)
        return jsonify({"code": 0, "data": wl})

    return jsonify({"code": -1, "msg": "不支持的方法"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
