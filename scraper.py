#!/usr/bin/env python3
"""被動元件價格爬蟲 - GitHub Actions 版本"""
import re, json, os, time
from datetime import datetime, timezone, timedelta
import requests

SPECS = [
    {"key": "47uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=47uf+4v+x6s"},
    {"key": "22uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=22uf+4v+x6s"},
    {"key": "10uF_16V_X7R",              "url": "https://so.szlcsc.com/global.html?k=10uf+16v+x7r"},
    {"key": "0402_100nF_16V_X7R",        "url": "https://so.szlcsc.com/global.html?k=0402+0.1uf+16v+x7r"},
    {"key": "0201_100nF_6V3_X5R",        "url": "https://so.szlcsc.com/global.html?k=0201+0.1uf+6.3v+x5r"},
    {"key": "AlCap_PDB_100U_63V_M10x10", "url": "https://so.szlcsc.com/global.html?k=100uf+63v+hybrid+aluminum+10x10"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.szlcsc.com/",
}

PRICES_FILE   = "passive_components_prices.json"
TEMPLATE_FILE = "passive_components_template.html"
OUTPUT_FILE   = "index.html"


def fetch_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_products(html):
    products = []
    model_re = re.compile(r'\[([A-Z][A-Z0-9\-]{5,})\]\(https://item\.szlcsc\.com/(\d+)', re.M)
    matches = list(model_re.finditer(html))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(html)
        block = html[start:end]
        product = {"model": m.group(1), "lcsc_id": m.group(2),
                   "brand": "", "package": "", "prices": {}, "stock": 0}
        bm = re.search(r'品牌\[([^\]]+)\]', block)
        if bm: product["brand"] = bm.group(1)
        pm = re.search(r'封装(\S+)', block)
        if pm: product["package"] = pm.group(1)
        for qty, price in re.findall(r'[-*]?\s*(\d+)\+\s*\n+[￥¥]([0-9.]+)', block):
            product["prices"][int(qty)] = float(price)
        sm = re.search(r'现货(\d{2,})', block)
        if sm: product["stock"] = int(sm.group(1))
        if product["prices"]:
            sp = sorted(product["prices"].items())
            product["min_price"] = sp[0][1]
            product["min_qty"]   = sp[0][0]
            products.append(product)
    return products


def main():
    tw = timezone(timedelta(hours=8))
    now = datetime.now(tw)
    today = now.strftime("%Y-%m-%d")
    print(f"[{now.strftime('%H:%M')} CST] 抓取被動元件價格 {today}")

    history = json.load(open(PRICES_FILE, encoding="utf-8")) if os.path.exists(PRICES_FILE) else {}

    for spec in SPECS:
        key, url = spec["key"], spec["url"]
        print(f"  {key} ...", end=" ", flush=True)
        try:
            products = parse_products(fetch_page(url))
            in_stock = [p for p in products if p.get("stock",0)>0 and p.get("min_price",0)>0]
            avg = sum(p["min_price"] for p in in_stock)/len(in_stock) if in_stock else None
            history.setdefault(key, {})[today] = {
                "fetched_at": now.isoformat(), "avg_price": avg, "products": products}
            print(f"OK {len(products)} 種, 現貨 {len(in_stock)}, avg=¥{avg:.4f}" if avg else f"OK {len(products)} 種, 無現貨")
        except Exception as e:
            print(f"FAIL {e}")
        time.sleep(1.5)

    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    if os.path.exists(TEMPLATE_FILE):
        tmpl = open(TEMPLATE_FILE, encoding="utf-8").read()
        html = tmpl.replace("__HISTORY_JSON__", json.dumps(history, ensure_ascii=False))
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"產生 {OUTPUT_FILE} ({len(html):,} bytes)")

    print("✅ 完成")
    # Summary
    for spec in SPECS:
        k = spec["key"]
        d = history.get(k, {}).get(today, {})
        avg = d.get("avg_price")
        cnt = len([p for p in d.get("products",[]) if p.get("stock",0)>0])
        print(f"  {k}: ¥{avg:.4f} ({cnt} 現貨)" if avg else f"  {k}: 無資料")


if __name__ == "__main__":
    main()
