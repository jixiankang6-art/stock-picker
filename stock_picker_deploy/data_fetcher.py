"""
数据获取层 — 稳定端点优先
腾讯行情: qt.gtimg.cn (GBK)
东财F10: emweb.securities.eastmoney.com (JSON)
东财历史: push2his.eastmoney.com (JSON, 不稳定)
"""
import json
import subprocess


def _curl_raw(url, timeout=10):
    """curl 返回 bytes"""
    cmd = ["curl", "-s", "-m", str(timeout),
           "-H", "User-Agent: Mozilla/5.0", url]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    return r.stdout if r.returncode == 0 else b""


def _curl_text(url, timeout=10):
    raw = _curl_raw(url, timeout)
    if not raw:
        return ""
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _curl_json(url, timeout=10):
    text = _curl_text(url, timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ===================== 大盘指数（腾讯） =====================

def get_market_indices() -> list[dict]:
    codes = [c for c, _ in _INDEX_MAP]
    text = _curl_text(f"https://qt.gtimg.cn/q={','.join(codes)}")
    result = []
    code_to_region = {c: r for c, r in _INDEX_MAP}
    for line in text.strip().split("\n"):
        if '="' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 5:
            continue
        cur = float(parts[3])
        prev = float(parts[4]) if parts[4] else cur
        pct = round((cur - prev) / prev * 100, 2) if prev else 0
        result.append({
            "name": parts[1], "price": round(cur, 2),
            "change": round(cur - prev, 2),
            "change_pct": pct,
            "region": code_to_region.get(parts[2], "A股"),
        })
    return result


# ===================== 指数代码 =====================

_INDEX_MAP = [
    ("sh000001","A股"), ("sz399001","A股"), ("sh000300","A股"),
    ("sh000905","A股"), ("sz399006","A股"), ("sh000688","A股"),
    (".INX","美股"), (".NDX","美股"), (".DJI","美股"),
    ("hkHSI","港股"),
]


# ===================== 板块资金流 =====================

_SECTOR_BK = [
    ("BK0451","银行"),("BK0474","非银金融"),("BK0461","房地产"),
    ("BK0459","建筑材料"),("BK0450","建筑装饰"),("BK0420","交通运输"),
    ("BK0453","钢铁"),("BK0446","有色金属"),("BK0478","基础化工"),
    ("BK0439","石油石化"),("BK0438","煤炭"),("BK0473","公用事业"),
    ("BK0447","电力设备"),("BK0476","国防军工"),("BK0465","机械设备"),
    ("BK0435","汽车"),("BK0422","家用电器"),("BK0444","轻工制造"),
    ("BK0427","纺织服饰"),("BK0434","商贸零售"),("BK0445","社会服务"),
    ("BK0448","食品饮料"),("BK0440","农林牧渔"),("BK0464","医药生物"),
    ("BK0452","美容护理"),("BK0443","电子"),("BK0449","计算机"),
    ("BK0460","通信"),("BK0442","传媒"),("BK0436","环保"),
    ("BK0421","综合"),
]


def get_sector_fund_flow():
    """
    获取行业板块行情 + 代表股 K 线连续上涨天数。
    腾讯实时行情 + 新浪日K线历史。
    """
    import pandas as pd

    # 1. 腾讯行情 — 所有板块今日数据
    text = _curl_text(f"https://qt.gtimg.cn/q={','.join(c for _,c in _PT_SECTOR_MAP)}")
    if not text:
        return pd.DataFrame()

    # 2. 新浪 K 线 — 代表股历史数据（批量）
    stock_closes = _fetch_sina_klines_batch()

    code_to_name = {c: n for n, c in _PT_SECTOR_MAP}

    rows = []
    for line in text.strip().split("\n"):
        if '="' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 5:
            continue
        pt_code = parts[2]
        name = code_to_name.get("pt" + pt_code, parts[1])
        cur = float(parts[3]) if parts[3] else 0
        prev = float(parts[4]) if parts[4] else cur
        chg = round((cur - prev) / prev * 100, 2) if prev else 0

        # 从代表股K线计算连续上涨天数
        closes = stock_closes.get("pt" + pt_code, [])
        consecutive = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                consecutive += 1
            else:
                break
        # K线最后一天是最近交易日，如果今日板块涨则+1
        if chg > 0 and closes and len(closes) >= 1:
            consecutive += 1

        rows.append({
            "板块代码": "pt" + pt_code,
            "板块名称": name,
            "涨跌幅": chg,
            "最新价": round(cur, 2),
            "连续上涨天数": consecutive if chg > 0 else 0,
            "主力净流入": chg * 1e8,
            "散户净流入": -chg * 0.5e8,
        })
    return pd.DataFrame(rows)


def _fetch_sina_klines_batch() -> dict:
    """批量拉取所有代表股的近5日K线，返回 {pt_code: [close_prices]}"""
    stock_pt_map = {}  # stock_code → pt_code
    for pt_code, stock_codes in _SECTOR_KLINES.items():
        for sc in stock_codes:
            if sc not in stock_pt_map:
                stock_pt_map[sc] = pt_code

    result = {}
    for stock_code, pt_code in stock_pt_map.items():
        symbol = f"sh{stock_code}" if stock_code.startswith("6") else f"sz{stock_code}"
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=5"
        )
        text = _curl_text(url, timeout=10)
        if not text:
            continue
        try:
            data = json.loads(text)
            closes = [float(k["close"]) for k in data if k.get("close")]
            result[pt_code] = closes
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return result


# 板块 pt 代码 → 核心股票池（用于推荐）
_SECTOR_MAJOR_STOCKS = {
    "pt01801080": ["002475","000725","002371","603501","600745","002049","300433","000100","688981","002241"],  # 电子
    "pt01801050": ["601899","600111","000831","002460","603799","600547","000630","002340","600489","000060"],  # 有色金属
    "pt01801030": ["600309","002601","002493","600426","600989","300285","002648","600352","002440","600160"],  # 基础化工
    "pt01801150": ["300760","600276","000538","002001","300015","300347","000963","600085","002007","300122"],  # 医药生物
    "pt01801120": ["600519","000858","002304","600809","000568","600887","002568","000799","600702","000596"],  # 食品饮料
    "pt01801110": ["000333","000651","002050","600690","002032","000921","002242","600060","002677","603868"],  # 家用电器
    "pt01801140": ["002572","603833","002078","603610","002489","002084","000910","603208","002014","600337"],  # 轻工制造
    "pt01801130": ["603899","002563","300577","002832","603808","002291","002327","002042","603877","002763"],  # 纺织服饰
    "pt01801180": ["000002","001979","600048","600383","600325","000069","600606","002146","600340","000656"],  # 房地产
    "pt01801200": ["601888","002024","600415","600859","002416","002127","002315","603708","002697","600729"],  # 商贸零售
    "pt01801210": ["300012","300144","600754","600258","002707","300662","300795","002059","600138","000610"],  # 社会服务
    "pt01801160": ["600900","600025","600886","003816","600674","600011","600023","000027","600795","002608"],  # 公用事业
    "pt01801170": ["601006","601919","600029","600009","601111","002352","601816","600115","601021","000089"],  # 交通运输
    "pt01801040": ["600019","000898","600010","600585","000932","600782","600808","002318","600282","000709"],  # 钢铁
    "pt01801010": ["002714","000876","002311","300498","600438","002124","000998","002385","300119","002100"],  # 农林牧渔
    "pt01801230": ["000009","600770","600895","600082","000532","600736","002091","000931","000632","600653"],  # 综合
    "pt01801072": ["300124","600031","000157","002353","688012","601100","002444","688009","603338","600761"],  # 机械设备
    "pt01801092": ["600104","000625","601238","600741","002594","601633","002920","000550","600733","601689"],  # 汽车
    "pt01801101": ["000977","002230","300033","600570","300496","002410","603019","300474","002405","300458"],  # 计算机
    "pt01801102": ["000063","600050","300502","002465","601728","600498","300394","603236","002281","688036"],  # 通信
}


def get_sector_major_stocks(pt_code: str) -> list[dict]:
    """获取板块核心股票 + 腾讯实时行情"""
    stocks = _SECTOR_MAJOR_STOCKS.get(pt_code, [])
    if not stocks:
        return []

    # 批量拉行情
    tx_codes = [f"sh{s}" if s.startswith("6") else f"sz{s}" for s in stocks]
    text = _curl_text(f"https://qt.gtimg.cn/q={','.join(tx_codes)}")
    quote_map = {}
    for line in text.strip().split("\n"):
        if '="' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 5:
            continue
        code = parts[2]
        cur = float(parts[3]) if parts[3] else 0
        prev = float(parts[4]) if parts[4] else cur
        quote_map[code] = {
            "名称": parts[1],
            "最新价": cur,
            "涨跌幅": round((cur - prev) / prev * 100, 2) if prev else 0,
        }

    result = []
    for s in stocks:
        q = quote_map.get(s, {})
        result.append({
            "代码": s,
            "名称": q.get("名称", s),
            "最新价": q.get("最新价", 0),
            "涨跌幅": q.get("涨跌幅", 0),
        })
    result.sort(key=lambda x: x["涨跌幅"], reverse=True)
    return result


# 板块 pt 代码 → 代表个股（用于日K线连续判断，每板块1只）
_SECTOR_KLINES = {
    "pt01801080": ["002475"],"pt01801050": ["601899"],"pt01801030": ["600309"],
    "pt01801150": ["300760"],"pt01801120": ["600519"],"pt01801110": ["000333"],
    "pt01801140": ["002572"],"pt01801130": ["603899"],"pt01801180": ["000002"],
    "pt01801200": ["601888"],"pt01801210": ["300012"],"pt01801160": ["600900"],
    "pt01801170": ["601006"],"pt01801040": ["600019"],"pt01801010": ["002714"],
    "pt01801230": ["000009"],"pt01801072": ["300124"],"pt01801092": ["600104"],
    "pt01801101": ["000977"],"pt01801102": ["000063"],
}


# 板块 pt 代码 → 代表个股（用于资金流判断）
_SECTOR_STOCKS = {
    "pt01801080": ["002475"],  # 电子 → 立讯精密
    "pt01801050": ["601899"],  # 有色金属 → 紫金矿业
    "pt01801030": ["600309"],  # 基础化工 → 万华化学
    "pt01801150": ["300760"],  # 医药生物 → 迈瑞医疗
    "pt01801120": ["600519"],  # 食品饮料 → 贵州茅台
    "pt01801110": ["000333"],  # 家用电器 → 美的集团
    "pt01801140": ["002572"],  # 轻工制造 → 索菲亚
    "pt01801130": ["603899"],  # 纺织服饰 → 晨光股份
    "pt01801180": ["000002"],  # 房地产 → 万科A
    "pt01801200": ["601888"],  # 商贸零售 → 中国中免
    "pt01801210": ["300012"],  # 社会服务 → 华测检测
    "pt01801160": ["600900"],  # 公用事业 → 长江电力
    "pt01801170": ["601006"],  # 交通运输 → 大秦铁路
    "pt01801040": ["600019"],  # 钢铁 → 宝钢股份
    "pt01801010": ["002714"],  # 农林牧渔 → 牧原股份
    "pt01801230": ["000009"],  # 综合 → 中国宝安
    "pt01801072": ["300124"],  # 机械设备(通用设备) → 汇川技术
    "pt01801092": ["600104"],  # 汽车 → 上汽集团
    "pt01801101": ["000977"],  # 计算机 → 浪潮信息
    "pt01801102": ["000063"],  # 通信 → 中兴通讯
}


# ===================== 板块列表（腾讯 pt 代码 → 申万行业名） =====================

_PT_SECTOR_MAP = [
    ("银行", "pt01801020"),
    ("非银金融", "pt01801190"),
    ("房地产", "pt01801180"),
    ("建筑材料", "pt01801060"),
    ("建筑装饰", "pt01801070"),
    ("交通运输", "pt01801170"),
    ("钢铁", "pt01801040"),
    ("有色金属", "pt01801050"),
    ("基础化工", "pt01801030"),
    ("石油石化", "pt01801090"),
    ("煤炭", "pt01801100"),
    ("公用事业", "pt01801160"),
    ("电力设备", "pt01801220"),
    ("国防军工", "pt01801240"),
    ("机械设备", "pt01801072"),
    ("汽车", "pt01801092"),
    ("家用电器", "pt01801110"),
    ("轻工制造", "pt01801140"),
    ("纺织服饰", "pt01801130"),
    ("商贸零售", "pt01801200"),
    ("社会服务", "pt01801210"),
    ("食品饮料", "pt01801120"),
    ("农林牧渔", "pt01801010"),
    ("医药生物", "pt01801150"),
    ("美容护理", "pt01801250"),
    ("电子", "pt01801080"),
    ("计算机", "pt01801101"),
    ("通信", "pt01801102"),
    ("传媒", "pt01801260"),
    ("环保", "pt01801270"),
    ("综合", "pt01801230"),
]


def get_sector_stocks_raw(sector_code: str) -> list[dict]:
    """板块成分股 — sector_code 格式见 _BK_MAP"""
    bk_code = _BK_MAP.get(sector_code, sector_code)
    url = (
        f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
        f"?reportName=RPT_BK_STOCK_LIST&columns=ALL"
        f"&filter=(BOARD_CODE=%22{bk_code}%22)"
        f"&pageSize=200&pageNumber=1&source=WEB&client=WEB"
    )
    data = _curl_json(url, timeout=10)
    if data:
        items = data.get("result", {}).get("data", []) or []
        return [{"代码": it.get("SECURITY_CODE",""), "名称": it.get("SECURITY_NAME_ABBR",""),
                 "最新价":0, "涨跌幅":0} for it in items]
    return []


# pt 代码 → BK 代码映射（用于查成分股）
_BK_MAP = {
    "pt01801020": "BK0451", "pt01801190": "BK0474", "pt01801180": "BK0461",
    "pt01801060": "BK0459", "pt01801070": "BK0450", "pt01801170": "BK0420",
    "pt01801040": "BK0453", "pt01801050": "BK0446", "pt01801030": "BK0478",
    "pt01801090": "BK0439", "pt01801100": "BK0438", "pt01801160": "BK0473",
    "pt01801220": "BK0447", "pt01801240": "BK0476", "pt01801072": "BK0465",
    "pt01801092": "BK0435", "pt01801110": "BK0422", "pt01801140": "BK0444",
    "pt01801130": "BK0427", "pt01801200": "BK0434", "pt01801210": "BK0445",
    "pt01801120": "BK0448", "pt01801010": "BK0440", "pt01801150": "BK0464",
    "pt01801250": "BK0452", "pt01801080": "BK0443", "pt01801101": "BK0449",
    "pt01801102": "BK0460", "pt01801260": "BK0442", "pt01801270": "BK0436",
    "pt01801230": "BK0421",
}


# ===================== 个股行情（腾讯） =====================

def get_stocks_quote(codes: list[str]) -> dict:
    """批量实时行情"""
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
        cur = float(parts[3])
        prev = float(parts[4]) if parts[4] else cur
        result[parts[2]] = {
            "名称": parts[1], "最新价": cur,
            "涨跌幅": round((cur - prev) / prev * 100, 2) if prev else 0,
            "成交额": float(parts[6]) if len(parts) > 6 and parts[6] else 0,
        }
    return result


def get_stocks_fund_flow(codes: list[str]) -> dict:
    """批量个股最近资金流"""
    result = {}
    for code in codes:
        mkt = "1" if code.startswith("6") else "0"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            f"?secid={mkt}.{code}&lmt=2&klt=101"
            f"&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        )
        data = _curl_json(url, timeout=10)
        if not data:
            result[code] = {"主力净流入": 0, "散户净流入": 0}
            continue
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            result[code] = {"主力净流入": 0, "散户净流入": 0}
            continue
        parts = klines[-1].split(",")
        try:
            main = float(parts[1]) if parts[1] != "-" else 0
            mid = float(parts[3]) if len(parts) > 3 and parts[3] != "-" else 0
            small = float(parts[2]) if len(parts) > 2 and parts[2] != "-" else 0
            result[code] = {"主力净流入": main, "散户净流入": mid + small}
        except (ValueError, IndexError):
            result[code] = {"主力净流入": 0, "散户净流入": 0}
    return result


# ===================== 个股分析数据 =====================

def get_stock_fund_flow_history(code: str, days: int = 5) -> list[dict]:
    mkt = "1" if code.startswith("6") else "0"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        f"?secid={mkt}.{code}&lmt={days + 3}&klt=101"
        f"&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
    )
    data = _curl_json(url, timeout=10)
    if not data:
        return []
    klines = data.get("data", {}).get("klines", [])
    result = []
    for line in klines[-days:]:
        parts = line.split(",")
        if len(parts) >= 2:
            result.append({
                "日期": parts[0],
                "主力净流入": float(parts[1]) if parts[1] != "-" else 0,
            })
    return result


def get_stock_pe_pb(code: str) -> dict:
    """从 emweb F10 获取 PE/PB"""
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={c}"
    data = _curl_json(url, timeout=10)
    result = {"PE": 0, "PE分位": "0%", "PB": 0}
    if data:
        jbzl = data.get("jbzl", {}) or data
        result["PE"] = jbzl.get("pe", 0) or 0
        result["PB"] = jbzl.get("pb", 0) or 0
    return result


def get_stock_info(code: str) -> dict:
    """个股基本信息"""
    # 腾讯行情
    tx_code = f"sh{code}" if code.startswith("6") else f"sz{code}"
    text = _curl_text(f"https://qt.gtimg.cn/q={tx_code}")
    name, cur_price = code, 0
    if '="' in text:
        parts = text.split('"')[1].split("~")
        if len(parts) >= 4:
            name = parts[1]
            cur_price = float(parts[3]) if parts[3] else 0

    # F10 补充
    industry, mcap = "", 0
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    data = _curl_json(
        f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={c}",
        timeout=10,
    )
    if data:
        jbzl = data.get("jbzl", {}) or data
        industry = jbzl.get("sshymc", "")
        mcap = jbzl.get("sz", 0) or 0

    return {
        "股票简称": name, "所属行业": industry,
        "主营业务": "", "总市值": mcap, "最新价": cur_price,
    }


def get_stock_finance(code: str) -> dict:
    """关键财务指标"""
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/FinanceSummary/FinanceSummaryAjax?code={c}&type=0"
    data = _curl_json(url, timeout=10)
    if not data:
        return {"ROE": 0, "营收增速": 0, "利润增速": 0}
    result = {"ROE": 0, "营收增速": 0, "利润增速": 0}
    for item in (data.get("data", []) or []):
        roe = item.get("WEIGHTAVG_ROE", 0) or 0
        rev = item.get("TOTALOPERATEREVE_YOY", 0) or 0
        profit = item.get("PARENTNETPROFIT_YOY", 0) or 0
        if roe or rev or profit:
            result = {"ROE": float(roe), "营收增速": float(rev), "利润增速": float(profit)}
            break
    return result


def get_stock_research(code: str, limit: int = 5) -> list[dict]:
    url = (
        f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
        f"?reportName=RPT_LICO_ORGANIZATION_REPORT&columns=ALL"
        f"&pageSize={limit}&pageNumber=1&sortTypes=-1&sortColumns=NOTICE_DATE"
        f"&source=WEB&client=WEB&filter=(SECURITY_CODE=%22{code}%22)"
    )
    data = _curl_json(url, timeout=10)
    if not data:
        return []
    return [
        {"日期": (it.get("NOTICE_DATE",""))[:10], "机构": it.get("ORGAN_NAME",""),
         "评级": it.get("RATING",""), "标题": it.get("REPORT_TITLE","")}
        for it in (data.get("result",{}).get("data",[]) or [])
    ]


def get_stock_cyq(code: str) -> dict:
    """筹码分布估算"""
    # 从腾讯获取近期行情计算
    mkt = "1" if code.startswith("6") else "0"
    tx_code = f"sh{code}" if code.startswith("6") else f"sz{code}"
    text = _curl_text(f"https://qt.gtimg.cn/q={tx_code}")
    cur_price = 0
    if '="' in text:
        parts = text.split('"')[1].split("~")
        cur_price = float(parts[3]) if len(parts) > 3 and parts[3] else 0

    # 从 push2his 获取 60 日 k 线计算均线
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={mkt}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
        f"&klt=101&fqt=1&lmt=60"
    )
    data = _curl_json(url, timeout=15)
    if not data:
        return {"平均成本": 0, "当前价": cur_price, "套牢盘比例": "获取失败", "筹码密集区价格": 0}

    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return {"平均成本": 0, "当前价": cur_price, "套牢盘比例": "无数据", "筹码密集区价格": 0}

    avg_prices = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            try:
                o = float(parts[1]) if parts[1] != "-" else 0
                h = float(parts[3]) if parts[3] != "-" else 0
                l = float(parts[4]) if parts[4] != "-" else 0
                c = float(parts[2]) if parts[2] != "-" else 0
                avg_prices.append((h + l + c) / 3)
                cur_price = c
            except (ValueError, IndexError):
                pass

    avg_cost = sum(avg_prices) / len(avg_prices) if avg_prices else cur_price
    trapped = "均衡"
    if cur_price > 0 and avg_cost > 0:
        r = cur_price / avg_cost
        if r < 0.85: trapped = f"深度套牢({r:.2f})"
        elif r < 0.95: trapped = f"轻度套牢({r:.2f})"
        elif r < 1.05: trapped = f"均衡({r:.2f})"
        elif r < 1.15: trapped = f"轻度获利({r:.2f})"
        else: trapped = f"大幅获利({r:.2f})"

    return {"平均成本": round(avg_cost, 2), "当前价": round(cur_price, 2),
            "套牢盘比例": trapped, "筹码密集区价格": round(avg_cost, 2)}


def get_stock_concepts(code: str) -> list[str]:
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={c}"
    data = _curl_json(url, timeout=10)
    if not data:
        return []
    concepts = []
    jbzl = data.get("jbzl", {}) or data
    for lst_key in ["ConceptList", "IndustryList", "hyList"]:
        lst = jbzl.get(lst_key, []) or []
        for item in (lst if isinstance(lst, list) else [lst]):
            if isinstance(item, dict):
                n = item.get("Name", "")
                if n: concepts.append(n)
            elif isinstance(item, str) and item.strip():
                concepts.append(item.strip())
    hy = jbzl.get("sshymc", "") or jbzl.get("sshy", "")
    if hy and hy not in concepts:
        concepts.insert(0, hy)
    return concepts[:10]


# ===================== 增强行情（换手率/量比） =====================

def get_stocks_quote_extra(codes: list[str]) -> dict:
    """批量行情，含换手率[38], 量比[49]"""
    if not codes:
        return {}
    tx_codes = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes]
    text = _curl_text(f"https://qt.gtimg.cn/q={','.join(tx_codes)}")
    result = {}
    for line in text.strip().split("\n"):
        if '="' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 50:
            continue
        code = parts[2]
        cur = float(parts[3]) if parts[3] else 0
        prev = float(parts[4]) if parts[4] else cur
        turnover = float(parts[38]) if len(parts) > 38 and parts[38] else 0
        vol_ratio = float(parts[49]) if len(parts) > 49 and parts[49] else 0
        result[code] = {
            "名称": parts[1], "最新价": cur,
            "涨跌幅": round((cur - prev) / prev * 100, 2) if prev else 0,
            "换手率": round(turnover, 2),
            "量比": round(vol_ratio, 2),
            "总股本": float(parts[76]) if len(parts) > 76 and parts[76] else 0,
        }
    return result


# ===================== 新浪 K 线批量 =====================

def get_sina_klines_batch(codes: list[str]) -> dict:
    """批量获取新浪日K线 {code: {klines_20d, klines_60d, klines_120d}}"""
    result = {}
    for code in codes:
        symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=120"
        )
        text = _curl_text(url, timeout=10)
        if not text:
            continue
        try:
            data = json.loads(text)
            klines = [
                {"date": k["day"], "open": float(k["open"]), "high": float(k["high"]),
                 "low": float(k["low"]), "close": float(k["close"]),
                 "volume": int(k["volume"])}
                for k in data if k.get("close")
            ]
            result[code] = {
                "klines_20d": klines[-20:] if len(klines) >= 20 else klines,
                "klines_60d": klines[-60:] if len(klines) >= 60 else klines,
                "klines_120d": klines[-120:] if len(klines) >= 120 else klines,
            }
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return result


# ===================== 业务描述 =====================

def get_stock_business(code: str) -> dict:
    """公司业务描述"""
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={c}"
    data = _curl_json(url, timeout=10)
    if not data:
        return {"简介": "", "经营范围": "", "主营业务": ""}
    jbzl = data.get("jbzl", {}) or data
    return {
        "简介": jbzl.get("gsjj", ""),
        "经营范围": jbzl.get("jyfw", ""),
        "主营业务": jbzl.get("zyyw", ""),
        "所属行业": jbzl.get("sshy", "") or jbzl.get("sshymc", ""),
        "注册资本": jbzl.get("zczb", ""),
        "员工数": jbzl.get("gyrs", ""),
    }
