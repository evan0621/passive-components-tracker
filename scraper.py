#!/usr/bin/env python3
"""
LCSC passive component price scraper.
Uses cloudscraper to bypass Cloudflare protection on GitHub Actions.
"""
import json, re, time
from datetime import datetime, timezone, timedelta

try:
    import cloudscraper
    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    print("Using cloudscraper")
except ImportError:
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    print("Using requests (cloudscraper not available)")

TW = timezone(timedelta(hours=8))
NOW = datetime.now(TW)
TODAY = NOW.strftime("%Y-%m-%d")

SPECS = [
    {"key": "47uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=47uf+4v+x6s"},
    {"key": "22uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=22uf+4v+x6s"},
    {"key": "10uF_16V_X7R",              "url": "https://so.szlcsc.com/global.html?k=10uf+16v+x7r"},
    {"key": "0402_100nF_16V_X7R",        "url": "https://so.szlcsc.com/global.html?k=0402+0.1uf+16v+x7r"},
    {"key": "0201_100nF_6V3_X5R",        "url": "https://so.szlcsc.com/global.html?k=0201+0.1uf+6.3v+x5r"},
    {"key": "AlCap_PDB_100U_63V_M10x10", "url": "https://so.szlcsc.com/global.html?k=100uf+63v+hybrid+aluminum+10x10"},
]

MODEL_RE = re.compile(r'\b([A-Z][A-Z0-9\-]{5,})\b')
PRICE_RE = re.compile(r'(\d[\d,]+)\+\s*\n+[￥¥CNY]([0-9.]+)', re.MULTILINE)
STOCK_RE = re.compile(r'现货\s*(\d+)')

def parse_products(text):
    products = []
    blocks = re.split(r'\n(?=[A-Z][A-Z0-9\-]{5,})', text)
    for block in blocks:
        lines = block.strip().split('\n')
        if not lines:
            continue
        first = lines[0].strip()
        m = MODEL_RE.match(first)
        if not m:
            continue
        model = m.group(1)
        stock_m = STOCK_RE.search(block)
        if not stock_m:
            continue
        stock = int(stock_m.group(1))
        if stock <= 0:
            continue
        prices = {}
        for pm in PRICE_RE.finditer(block):
            qty = int(pm.group(1).replace(',', ''))
            price = float(pm.group(2))
            prices[qty] = price
        if not prices:
            continue
        sp = sorted(prices.items())
        brand_m = re.search(r'\n([A-Z][a-zA-Z ]{2,20})\n', block)
        brand = brand_m.group(1).strip() if brand_m else ""
        pkg_m = re.search(r'\b(0201|0402|0603|0805|1206|1210|SMD[^,\n]*)\b', block)
        pkg = pkg_m.group(1) if pkg_m else ""
        products.append({
            "model": model, "brand": brand, "package": pkg,
            "stock": stock, "min_price": sp[0][1], "min_qty": sp[0][0],
            "prices": {str(k): v for k, v in prices.items()}
        })
    return products

def fetch_spec(spec):
    print(f"  Fetching {spec['key']} ...")
    try:
        resp = session.get(spec["url"], timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        print(f"    ERROR: {e}")
        return []
    products = parse_products(text)
    print(f"    -> {len(products)} in-stock products")
    return products

# Load existing data
JSON_PATH = "passive_components_prices.json"
try:
    with open(JSON_PATH) as f:
        data = json.load(f)
except:
    data = {}

for spec in SPECS:
    key = spec["key"]
    products = fetch_spec(spec)
    time.sleep(2)  # polite delay

    if products:
        prices_list = [p["min_price"] for p in products]
        avg = sum(prices_list) / len(prices_list)
    else:
        avg = None

    history = data.get(key, {}).get("history", [])
    entry = {"date": TODAY, "avg_price": round(avg, 4) if avg else None, "product_count": len(products)}
    if not history or history[-1]["date"] != TODAY:
        history.append(entry)
    else:
        history[-1] = entry

    data[key] = {
        "key": key,
        "url": spec["url"],
        "fetched_at": NOW.isoformat(),
        "avg_price": round(avg, 4) if avg else None,
        "product_count": len(products),
        "products": products[:15],
        "history": history
    }

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Saved " + JSON_PATH)

# Generate index.html
with open("passive_components_template.html", encoding="utf-8") as f:
    tmpl = f.read()

html = tmpl.replace("__HISTORY_JSON__", json.dumps(data, ensure_ascii=False))
with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Generated index.html")
