"""
构建全市场股票→行业映射缓存（并行版）
Sina 获取全部A股代码 → 并行 emweb F10 查行业 → 存本地 JSON
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from data_fetcher import _curl_json

CACHE_FILE = Path(__file__).parent / "data" / "stock_industry_map.json"
WORKERS = 8


def _query_industry(code: str) -> tuple | None:
    """查询单只股票的行业，返回 (code, name, industry) 或 None"""
    c = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={c}"
    data = _curl_json(url, timeout=10)
    if data:
        jbzl = data.get("jbzl", {}) or data
        industry = jbzl.get("sshymc", "") or jbzl.get("sshy", "")
        if industry:
            return (code, jbzl.get("gsmc", code), industry.strip())
    return None


def build_cache():
    print("1/2 从 Sina 获取全 A 股代码...")
    all_codes = []
    page = 1
    while page <= 80:
        url = (
            f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"Market_Center.getHQNodeData?page={page}&num=80&sort=symbol&asc=1"
            f"&node=hs_a&symbol=&_s_r_a=init"
        )
        data = _curl_json(url, timeout=15)
        if not data:
            break
        for item in data:
            code = item.get("code", "")
            if code and len(code) == 6:
                all_codes.append(code)
        page += 1
        if page % 20 == 0:
            print(f"  已获取 {len(all_codes)} 只...")

    print(f"  共 {len(all_codes)} 只 A 股，开始并行查询行业...")

    # 2. 并行查行业
    industry_map = {}
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_query_industry, c): c for c in all_codes}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                code, name, industry = result
                industry_map[code] = {"name": name, "industry": industry}
            done += 1
            if done % 200 == 0:
                elapsed = time.time() - t0
                eta = (elapsed / done) * (len(all_codes) - done)
                print(f"  {done}/{len(all_codes)} ({done*100//len(all_codes)}%), "
                      f"已用时 {elapsed:.0f}s, 预计剩余 {eta:.0f}s")

    print(f"3/3 保存缓存: {len(industry_map)} 只有行业分类")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(industry_map, ensure_ascii=False), encoding="utf-8")
    print(f"完成！总耗时 {time.time()-t0:.0f}s")


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    return json.loads(CACHE_FILE.read_text(encoding="utf-8"))


def get_stocks_by_industry(industry_name: str) -> list[dict]:
    cache = load_cache()
    return [
        {"代码": code, "名称": info["name"], "行业": info["industry"]}
        for code, info in cache.items()
        if info["industry"] == industry_name
    ]


if __name__ == "__main__":
    build_cache()
