#!/usr/bin/env python3
"""
Passive component price updater — double-click update_prices.bat to run.
"""

import re, json as json_mod, sys, os, base64, time
from datetime import datetime

def ensure(pkg, import_as=None):
    try:
        __import__(import_as or pkg)
    except ImportError:
        print(f"  Installing {pkg} ...")
        os.system(f'"{sys.executable}" -m pip install {pkg} -q')

ensure("requests")
ensure("cloudscraper")
ensure("beautifulsoup4", "bs4")

import requests
import cloudscraper
from bs4 import BeautifulSoup

# ── config ───────────────────────────────────────────────────────
REPO_OWNER   = "evan0621"
REPO_NAME    = "passive-components-tracker"
GITHUB_TOKEN = ""

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "github_config.json")
LOCAL_JSON  = os.path.join(SCRIPT_DIR, "passive_components_prices.json")
LOCAL_TMPL  = os.path.join(SCRIPT_DIR, "passive_components_template.html")

SPECS = [
    # ── MLCC AI（HBM 去耦）
    {"key": "47uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=47uf+4v+x6s+mlcc",                    "mouser_kw": "47uF 4V X6S MLCC"},
    {"key": "22uF_4V_X6S",               "url": "https://so.szlcsc.com/global.html?k=22uf+4v+x6s+mlcc",                    "mouser_kw": "22uF 4V X6S MLCC"},
    {"key": "10uF_16V_X7R",              "url": "https://so.szlcsc.com/global.html?k=10uf+16v+x7r+0402+mlcc",              "mouser_kw": "10uF 16V X7R 0402 MLCC"},
    # ── 鋁電解（貼片）AI
    {"key": "AlCap_PDB_100U_63V_M10x10", "url": "https://so.szlcsc.com/global.html?k=100uf+63v+hybrid+aluminum+smd+10x10", "mouser_kw": "100uF 63V hybrid aluminum SMD 10x10.2"},
    {"key": "Hybrid_560uF_16V_M8x10",    "url": "https://so.szlcsc.com/global.html?k=560uf+16v+hybrid+aluminum+smd+8x10",  "mouser_kw": "560uF 16V hybrid aluminum SMD 8x10"},
    {"key": "Polymer_100uF_63V_M10x10",  "url": "https://so.szlcsc.com/global.html?k=polymer+100uf+63v+smd+aluminum+10x10","mouser_kw": "100uF 63V polymer aluminum SMD 10x10.2"},
    # ── 鋁電解（牛角）AI
    {"key": "SnapIn_450V_1000uF",        "url": "https://so.szlcsc.com/global.html?k=450v+1000uf+snap-in+aluminum+electrolytic", "mouser_kw": "1000uF 450V snap-in aluminum electrolytic"},
    {"key": "SnapIn_450V_820uF",         "url": "https://so.szlcsc.com/global.html?k=450v+820uf+snap-in+aluminum+electrolytic",  "mouser_kw": "820uF 450V snap-in aluminum electrolytic"},
    # ── 鋁電解（直插）消費性
    {"key": "DIP_16V_1000uF",            "url": "https://so.szlcsc.com/global.html?k=1000uf+16v+aluminum+electrolytic+radial+dip","mouser_kw": "1000uF 16V radial aluminum electrolytic through-hole"},
    {"key": "DIP_25V_470uF",             "url": "https://so.szlcsc.com/global.html?k=470uf+25v+aluminum+electrolytic+radial+dip", "mouser_kw": "470uF 25V radial aluminum electrolytic through-hole"},
    # ── 鋁電解（貼片）消費性
    {"key": "Polymer_16V_270uF_SMD",     "url": "https://so.szlcsc.com/global.html?k=270uf+16v+polymer+aluminum+smd",       "mouser_kw": "270uF 16V polymer aluminum SMD electrolytic"},
    # ── MLCC 車用（AEC-Q200）
    {"key": "0402_100nF_50V_X7R_AEC",   "url": "https://so.szlcsc.com/global.html?k=0402+100nf+50v+x7r+aec-q200+mlcc",    "mouser_kw": "100nF 50V X7R 0402 AEC-Q200 MLCC"},
    {"key": "1206_10uF_50V_X7R_AEC",    "url": "https://so.szlcsc.com/global.html?k=1206+10uf+50v+x7r+aec-q200+mlcc",     "mouser_kw": "10uF 50V X7R 1206 AEC-Q200 MLCC"},
    # ── MLCC 消費性
    {"key": "0402_100nF_16V_X7R",       "url": "https://so.szlcsc.com/global.html?k=0402+100nf+16v+x7r+mlcc",              "mouser_kw": "100nF 16V X7R 0402 MLCC"},
    {"key": "0402_10uF_10V_X5R_CONS",   "url": "https://so.szlcsc.com/global.html?k=0402+10uf+10v+x5r+mlcc",               "mouser_kw": "10uF 10V X5R 0402 MLCC"},
    {"key": "0201_1uF_6V3_X5R",         "url": "https://so.szlcsc.com/global.html?k=0201+1uf+6.3v+x5r+mlcc",               "mouser_kw": "1uF 6.3V X5R 0201 MLCC"},
    # ── 鋁電解 車用（AEC-Q200）
    {"key": "AlCap_SMD_Hybrid_100uF_50V_AEC", "url": "https://so.szlcsc.com/global.html?k=100uf+50v+hybrid+polymer+smd+aluminum+aec-q200", "mouser_kw": "100uF 50V hybrid polymer aluminum SMD AEC-Q200"},
    {"key": "AlCap_SnapIn_470uF_450V_AEC",    "url": "https://so.szlcsc.com/global.html?k=470uf+450v+snap-in+aluminum+aec-q200",            "mouser_kw": "470uF 450V snap-in aluminum electrolytic AEC-Q200"},
    # ── NP0/C0G MLCC（AI LLC 諧振電路）
    {"key": "1206_10nF_630V_C0G",   "url": "https://so.szlcsc.com/global.html?k=10nf+630v+c0g+np0+1206+mlcc",  "mouser_kw": "10nF 630VDC C0G NP0 1206 SMD MLCC"},
    {"key": "1210_33nF_630V_C0G",   "url": "https://so.szlcsc.com/global.html?k=33nf+630v+c0g+np0+1210+mlcc",  "mouser_kw": "33nF 630VDC C0G NP0 1210 SMD MLCC"},
    # ── Mega CAP / 堆疊型 MLCC（AI HVDC 穩壓）
    {"key": "2220_1uF_250V_X7R",    "url": "https://so.szlcsc.com/global.html?k=1uf+250v+x7r+2220+mlcc",      "mouser_kw": "1uF 250VDC X7R 2220 SMD MLCC high voltage"},
    # ── 電感
    {"key": "2016_1uH_Inductor", "url": "https://so.szlcsc.com/global.html?k=2016+1uH+power+inductor+smd", "mouser_kw": "1uH 2016 SMD power inductor"},
    {"key": "Inductor_AEC_4u7uH",    "url": "https://so.szlcsc.com/global.html?k=4.7uH+aec-q200+2520+smd+power+inductor", "mouser_kw": "4.7uH AEC-Q200 2520 SMD power inductor automotive"},
    # ── 電阻
    {"key": "0402_10kOhm_1pct",        "url": "https://so.szlcsc.com/global.html?k=0402+10kohm+thick-film+resistor+1",  "mouser_kw": "10kohm 0402 1% thick film SMD resistor"},
    {"key": "0402_10kOhm_AEC",         "url": "https://so.szlcsc.com/global.html?k=0402+10kohm+thick-film+aec-q200+1", "mouser_kw": "10kohm 0402 1% AEC-Q200 thick film resistor automotive"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.szlcsc.com/",
}

# ── Exchange rate: CNY → USD ─────────────────────────────────────
def get_exchange_rate():
    """Fetch live CNY→USD rate from frankfurter.app (free, no key needed)."""
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=CNY&to=USD", timeout=10)
        rate = r.json()['rates']['USD']
        print(f"  Exchange rate: 1 CNY = {rate:.5f} USD")
        return rate
    except Exception as e:
        print(f"  Exchange rate fetch failed ({e}), using fallback 0.1380")
        return 0.1380  # fallback approximation

# ── Mouser API ────────────────────────────────────────────────────
def _parse_mouser_part(p):
    """Parse a single Mouser part dict into our product format."""
    price_breaks = p.get('PriceBreaks') or []
    prices = {}
    for pb in price_breaks:
        try:
            qty = int(pb.get('Quantity', 0))
            ps = str(pb.get('Price', '')).replace('$','').replace(',','').strip()
            price = float(ps)
            if qty > 0 and price > 0:
                prices[qty] = round(price, 4)
        except (ValueError, TypeError):
            pass
    if not prices:
        return None

    avail = p.get('Availability', '')
    stock_m = re.search(r'([\d,]+)\s+In Stock', avail)
    stock = int(stock_m.group(1).replace(',','')) if stock_m else 0

    min_qty = min(prices.keys())
    min_price_usd = prices[min_qty]
    mfr = p.get('Manufacturer', '')
    brand = mfr if isinstance(mfr, str) else (mfr or {}).get('ManufacturerName', '')

    return {
        'model':         p.get('ManufacturerPartNumber', ''),
        'brand':         brand,
        'package':       p.get('PackageName', '') or '',
        'description':   p.get('Description', '') or '',
        'stock':         stock,
        'min_price':     min_price_usd,
        'min_price_usd': min_price_usd,
        'min_qty':       min_qty,
        'prices':        prices,
        'prices_usd':    dict(prices),
        'currency':      'USD',
        'source':        'Mouser',
        'lcsc_id':       None,
        'mouser_url':    p.get('ProductDetailUrl', ''),
        'mouser_pn':     p.get('MouserPartNumber', ''),   # Mouser internal PN for catalog lookup
    }

MOUSER_MAX_PAGES = 5   # 5 pages × 50 = 250 results per spec (~130 API calls/run)
                        # Discover and daily both use same depth; catalog tracks known PNs.

def fetch_mouser(keyword, api_key, max_pages=None):
    """Search Mouser by keyword; fetch up to max_pages pages (default: MOUSER_MAX_PAGES)."""
    if max_pages is None:
        max_pages = MOUSER_MAX_PAGES
    base_url = f"https://api.mouser.com/api/v1.0/search/keyword?apiKey={api_key}&countryCode=US&searchWithSignum=false"
    PER_PAGE = 50
    products = []
    start = 0
    total = None
    page = 0

    while page < max_pages:
        body = {"SearchByKeywordRequest": {
            "keyword": keyword, "Records": PER_PAGE,
            "StartingRecord": start,
            "SearchOptions": "", "SearchWithSignum": "False"
        }}
        try:
            r = requests.post(base_url, json=body, timeout=20)
            data = r.json()
            result = (data or {}).get('SearchResults') or {}
            if total is None:
                total = int(result.get('NumberOfResult') or 0)
            parts = result.get('Parts') or []
        except Exception as e:
            print(f"[Mouser error @{start}: {e}]", end=' ')
            break

        for p in parts:
            prod = _parse_mouser_part(p)
            if prod:
                products.append(prod)

        page += 1
        start += PER_PAGE
        if not parts or start >= total:
            break
        time.sleep(0.5)   # polite delay between pages

    return products


def fetch_mouser_by_pn(mouser_pn, api_key):
    """Fetch a single Mouser part by MouserPartNumber (for catalog top-up)."""
    url = f"https://api.mouser.com/api/v1.0/search/partnumber?apiKey={api_key}&countryCode=US"
    body = {"SearchByPartNumberRequest": {
        "mouserPartNumber": mouser_pn,
        "partSearchOptions": ""
    }}
    try:
        r = requests.post(url, json=body, timeout=20)
        data = r.json()
        result = (data or {}).get('SearchResults') or {}   # guard against SearchResults: null
        parts = result.get('Parts') or []
        if parts:
            return _parse_mouser_part(parts[0])
    except Exception as e:
        print(f"[PN error {mouser_pn}: {e}]", end=' ')
    return None


# ── Mouser catalog (persistent part-number registry) ─────────────────────────
# ── SQLite DB ────────────────────────────────────────────────────────────────
import sqlite3

DB_FILE = os.path.join(SCRIPT_DIR, 'passive_components.db')

def init_db():
    """Open (or create) the SQLite DB and return a connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            spec_key        TEXT NOT NULL,
            date            TEXT NOT NULL,
            avg_price_usd   REAL,
            total_stock     INTEGER,
            in_stock_count  INTEGER,
            product_count   INTEGER,
            lcsc_count      INTEGER,
            mouser_count    INTEGER,
            exchange_rate   REAL,
            fetched_at      TEXT,
            PRIMARY KEY (spec_key, date)
        );
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            spec_key        TEXT NOT NULL,
            date            TEXT NOT NULL,
            source          TEXT NOT NULL,
            model           TEXT,
            brand           TEXT,
            package         TEXT,
            description     TEXT,
            stock           INTEGER DEFAULT 0,
            min_price_usd   REAL,
            min_qty         INTEGER,
            mouser_pn       TEXT,
            lcsc_id         TEXT,
            mouser_url      TEXT,
            prices_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_prod_spec_date ON products(spec_key, date);
        CREATE INDEX IF NOT EXISTS idx_prod_mouser_pn  ON products(mouser_pn);
        CREATE TABLE IF NOT EXISTS mouser_catalog (
            spec_key    TEXT NOT NULL,
            mouser_pn   TEXT NOT NULL,
            PRIMARY KEY (spec_key, mouser_pn)
        );
    """)
    conn.commit()
    return conn

def db_load_history(conn):
    """Reconstruct full history dict from SQLite (for rebuild_html / skip logic)."""
    history = {}
    for row in conn.execute(
        "SELECT spec_key,date,avg_price_usd,total_stock,in_stock_count,"
        "product_count,lcsc_count,mouser_count,exchange_rate,fetched_at FROM daily_stats"
    ):
        sk, dt, avg, ts, isc, pc, lc, mc, er, fa = row
        history.setdefault(sk, {})[dt] = {
            'avg_price_usd': avg, 'total_stock': ts, 'in_stock_count': isc,
            'product_count': pc, 'lcsc_count': lc or 0, 'mouser_count': mc or 0,
            'exchange_rate': er, 'fetched_at': fa, 'products': []
        }
    for row in conn.execute(
        "SELECT spec_key,date,source,model,brand,package,description,"
        "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json FROM products"
    ):
        sk, dt, src, model, brand, pkg, desc, stk, mpu, mq, mpn, lid, murl, pj = row
        if sk in history and dt in history[sk]:
            prices = json_mod.loads(pj) if pj else {}
            history[sk][dt]['products'].append({
                'model': model or '', 'brand': brand or '',
                'package': pkg or '', 'description': desc or '',
                'stock': stk or 0, 'min_price_usd': mpu,
                'min_price': mpu, 'min_qty': mq,
                'mouser_pn': mpn, 'lcsc_id': lid, 'mouser_url': murl,
                'source': src, 'prices': prices, 'prices_usd': prices,
                'currency': 'USD' if src == 'Mouser' else 'CNY',
            })
    return history

def db_save_day(conn, spec_key, date, day_data):
    """Upsert one day's data for a spec (replaces old entry if exists)."""
    conn.execute("INSERT OR REPLACE INTO daily_stats VALUES (?,?,?,?,?,?,?,?,?,?)", (
        spec_key, date,
        day_data.get('avg_price_usd'), day_data.get('total_stock'),
        day_data.get('in_stock_count'), day_data.get('product_count'),
        day_data.get('lcsc_count'),    day_data.get('mouser_count'),
        day_data.get('exchange_rate'), day_data.get('fetched_at'),
    ))
    conn.execute("DELETE FROM products WHERE spec_key=? AND date=?", (spec_key, date))
    for p in day_data.get('products', []):
        prices_usd = p.get('prices_usd') or p.get('prices') or {}
        conn.execute(
            "INSERT INTO products (spec_key,date,source,model,brand,package,description,"
            "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec_key, date, p.get('source','LCSC'), p.get('model',''),
             p.get('brand',''), p.get('package',''), p.get('description',''),
             p.get('stock',0), p.get('min_price_usd'), p.get('min_qty'),
             p.get('mouser_pn'), str(p.get('lcsc_id','')) if p.get('lcsc_id') else None,
             p.get('mouser_url'),
             json_mod.dumps({str(k): v for k, v in prices_usd.items()}))
        )
    conn.commit()

def db_load_catalog(conn):
    """Return {spec_key: set(mouser_pn)} from DB."""
    catalog = {}
    for sk, pn in conn.execute("SELECT spec_key, mouser_pn FROM mouser_catalog"):
        catalog.setdefault(sk, set()).add(pn)
    return catalog

def db_upsert_catalog(conn, spec_key, pns):
    """Add new Mouser PNs for a spec into catalog (existing ones untouched)."""
    conn.executemany(
        "INSERT OR IGNORE INTO mouser_catalog (spec_key, mouser_pn) VALUES (?,?)",
        [(spec_key, pn) for pn in pns if pn]
    )
    conn.commit()

# ── Method 1: parse product cards from HTML (primary) ────────────
def parse_html_cards(html):
    soup = BeautifulSoup(html, 'html.parser')
    products = []
    seen = set()

    for card in soup.find_all(attrs={'data-custom-data': True}):
        try:
            cd = json_mod.loads(card.get('data-custom-data', '{}'))
        except Exception:
            continue
        if cd.get('productType') != 'main':
            continue
        pid = str(cd.get('productId', ''))
        if not pid or pid in seen:
            continue
        seen.add(pid)

        section = card.find('section')
        if not section:
            continue

        product = {'model': '', 'lcsc_id': pid, 'brand': '', 'package': '', 'prices': {}, 'stock': 0}

        # model name
        model_a = section.find('a', {'data-spm': 'n'})
        if model_a:
            sp = model_a.find('span')
            product['model'] = sp.get('title') or sp.get_text(strip=True) if sp else model_a.get_text(strip=True)

        # brand / package / stock from <dl> elements
        for dl in section.find_all('dl'):
            dt = dl.find('dt')
            dd = dl.find('dd')
            if not dt or not dd:
                continue
            label = dt.get_text(strip=True)
            val_sp = dd.find('span')
            val = (val_sp.get('title') or val_sp.get_text(strip=True)) if val_sp else dd.get_text(strip=True)
            if label == '品牌':
                product['brand'] = val
            elif label == '封装':
                product['package'] = val
            elif label == '现货':
                digits = re.sub(r'\D', '', val)
                if digits:
                    product['stock'] = int(digits)

        # price ladder from <ul class="w-[170px]">
        for ul in section.find_all('ul'):
            if 'w-[170px]' not in ul.get('class', []):
                continue
            for li in ul.find_all('li'):
                lbl = li.find('label')
                pspan = li.find('span', class_=lambda c: c and 'flex-1' in c)
                if not lbl or not pspan:
                    continue
                qty_d = re.sub(r'\D', '', lbl.get_text())
                price_t = pspan.get_text(strip=True).replace('￥','').replace('¥','').strip()
                try:
                    product['prices'][int(qty_d)] = float(price_t)
                except Exception:
                    pass
            if product['prices']:
                break

        if product['model'] and product['prices']:
            min_qty = min(product['prices'].keys())
            product['min_qty'] = min_qty
            product['min_price'] = product['prices'][min_qty]
            products.append(product)

    return products

# ── Method 2: JSON-LD fallback (gets basic info, min price only) ─
def parse_jsonld(html):
    products = []
    for m in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json_mod.loads(m)
        except Exception:
            continue
        if data.get('@type') != 'ItemList':
            continue
        for item in data.get('itemListElement', []):
            prod = item.get('item', {})
            offer = prod.get('offers', {})
            price = offer.get('price')
            url = offer.get('url', '')
            lcsc_id = re.search(r'/(\d+)\.html', url)
            if not price or not lcsc_id:
                continue
            instock = 'InStock' in offer.get('availability', '')
            products.append({
                'model': prod.get('name', ''),
                'lcsc_id': lcsc_id.group(1),
                'brand': prod.get('brand', {}).get('name', ''),
                'package': '',
                'prices': {1: float(price)},
                'min_price': float(price),
                'stock': 9999 if instock else 0,
            })
    return products

# ── Mouser product cleaner ───────────────────────────────────────

# 1. Kit / assortment + Engineering Model (-EM 後綴 = 工程樣品，價格虛高非量產料)
_KIT_RE = re.compile(
    r'KIT|ASSORTMENT|SAMPLE\s*BOOK|ASSORT|-EM$', re.I)

# 2. Military part-number prefixes (料號開頭)
#    M55342          = MIL-PRF-55342 thin-film resistor
#    M39003/M39006   = MIL-PRF-39003/39006 tantalum/wet electrolytic
#    M39007          = MIL-PRF-39007 wirewound resistor
#    M39010          = MIL-PRF-39010 fixed inductor
#    M39023          = MIL-PRF-39023 precision resistor (RNR/RNC series)
#    M32535          = MIL-PRF-32535 MLCC
#    M55681          = MIL-PRF-55681 film capacitor
#    CDR             = Vishay military ceramic capacitor (CDR31/CDR35…)
#    CWR/TWA/CSR     = 濕鉭軍規  MLS/MLP/THA = Knowles 扁平航太鋁電容
#    RNR/RNC/RNRB    = MIL-PRF-39023 precision resistors
_MIL_RE = re.compile(
    r'^M55342|^M39003|^M39006|^M39007|^M39010|^M39023|^M32535|^M55681'
    r'|^CDR\d'
    r'|^CWR\d|^TWA\d|^CSR\d'
    r'|^MLS\d|^MLP\d|^THA\d'
    r'|^RNR\d|^RNC\d|^RNRB|^RNRC'
    r'|JANTX|JANS\s|MIL-PRF'
    # 大尺寸金屬複合/一體成型功率電感（伺服器/車用大電流，非消費性）
    r'|^IHLP|^IHDM|^IHSR'         # Vishay 大電流系列
    r'|^SER\d{4}[A-Z]'            # Bourns SER 大尺寸
    r'|^PA4342|^PA4374|^PA4308',  # Coilcraft 大尺寸
    re.I)

# 3. Description 關鍵字：SnPb / 航太 / 醫療 / 特殊封裝
#    任何一個命中 → 直接排除
_BAD_DESC_RE = re.compile(
    # 含鉛端子
    r'\bSn\s*[/–-]\s*Pb\b|SnPb|Tin.?Lead|Non.?RoHS|Non\s+RoHS'
    # 氣密封裝 (Knowles 扁平、衛星級)
    r'|Hermetical(?:ly)?\s+Seal|Flatpack|Flat\s+Pack|Thinpack|Thin\s+Pack'
    # 軍/航太/太空等級宣告
    r'|Hi.?Rel\b|High.?Reliability|Space.?Grade|Space.?Level'
    r'|Aerospace.?Grade|\bMilitary.?Grade\b|\bMIL\s+Grade\b'
    # QPL / DSCC = 美軍合格產品清單，絕對軍規
    r'|\bQPL\b|DSCC\s+Draw'
    # 醫療植入式
    r'|Implantable|Medical.?Grade|Medical.?Implant'
    # 薄膜 (Thin Film) 電阻/電容：精密/軍醫特規，價格虛高（M-0402K 系列等）
    r'|Thin\s+Film'
    # 軸向引線 (Axial)：古董封裝，只用於音響/航太維修，非現代消費性直插電容
    r'|\bAxial\b'
    # 焊針/焊片 (Solder Tag/Pin/Lug)：工業大電流電容，非一般 DIP 消費性
    r'|Solder\s+Tag|Solder\s+Pin|Solder\s+Lug'
    # 音響發燒級：KEMET/Nichicon 音響特規，單價遠高於一般消費性
    r'|\bAudio\s+Grade\b|\bAudio\s+Series\b',
    re.I)

# 4. 特定品牌在特定料號前綴下才出問題，但 Knowles 鋁電容全系列都是航太料
#    → 直接用品牌排除（Knowles 不做一般商用鋁電容）
_BAD_BRAND_RE = re.compile(r'^Knowles$', re.I)

# ── Brand whitelist ───────────────────────────────────────────────────────────
# Only keep products from recognized Tier-1~3 commercial manufacturers.
# Anything not matching is treated as unknown/niche and dropped.
_ALLOWED_BRAND_RE = re.compile(
    r'Murata|TDK|Samsung.*Electro|SEMCO|Taiyo.?Yuden|Kyocera|AVX'
    r'|Yageo|KEMET|Vishay|Walsin'
    r'|Fenghua|Holy.?Stone|IHHEC|禾伸堂'
    r'|PSA|信昌'
    r'|Nichicon|Nippon.?Chemi|Panasonic|Rubycon|Lelon'
    r'|APAQ|Chinsan|Jianghai'
    r'|Sumida|Coilcraft|TAI.?TECH|台慶|台庆'
    r'|Rohm|KOA',
    re.I
)

def clean_products(products):
    """
    Remove definitively wrong Mouser products:
    1. Kits / assortments
    2. Military part-number prefixes (M55342, M32535, CWR, MLS/MLP/THA …)
    3. Description flags: SnPb, Non-RoHS, Hermetic Seal, Flatpack, Hi-Rel,
       Aerospace/Space Grade, Military Grade, Medical/Implant,
       Thin Film, Axial, Solder Tag/Pin/Lug, Audio Grade
    4. Knowles brand (专做航太密封鋁電容，无商用版本)
    5. Brand not in whitelist (Tier-1~3 commercial manufacturers only)
    NOTE: No price-based filtering — genuine AI shortage spikes must not be removed.
    """
    clean = []
    removed = []
    for p in products:
        model = p.get('model') or ''
        desc  = p.get('description') or ''
        brand = p.get('brand') or ''

        if _KIT_RE.search(model):
            removed.append(f'KIT:{model}'); continue
        if _MIL_RE.search(model):
            removed.append(f'MIL:{model}'); continue
        if _BAD_DESC_RE.search(desc):
            removed.append(f'DESC:{model}'); continue
        if _BAD_BRAND_RE.match(brand):
            removed.append(f'BRAND:{model}'); continue
        if not _ALLOWED_BRAND_RE.search(brand):
            removed.append(f'NOBRAND:{model}'); continue
        clean.append(p)

    if removed:
        tags = ', '.join(removed[:5]) + ('…' if len(removed) > 5 else '')
        print(f'[cleaned {len(removed)}: {tags}]', end=' ')
    return clean

# ── combined parse with fallback ─────────────────────────────────
def parse_products(html):
    result = parse_html_cards(html)
    if result:
        return result
    # fallback to JSON-LD
    result = parse_jsonld(html)
    if result:
        print(f"[fallback:json-ld {len(result)} items]", end=' ')
    return result

# ── clean bad history entries ────────────────────────────────────
def clean_bad(history):
    cleaned = 0
    for key in history:
        for date in list(history[key].keys()):
            if history[key][date].get('product_count', len(history[key][date].get('products',['x']))) == 0:
                del history[key][date]
                cleaned += 1
    if cleaned:
        print(f"  Cleaned {cleaned} bad entries (0 products) from history")
    return history

# ── scrape all specs ─────────────────────────────────────────────
def scrape_all(force=False, mouser_key='', discover=False):
    import random
    today = datetime.now().strftime("%Y-%m-%d")
    sc = cloudscraper.create_scraper()
    conn = init_db()
    history = db_load_history(conn)
    catalog = db_load_catalog(conn)
    mouser_pages = MOUSER_MAX_PAGES   # 5 pages for both discover and daily
    if discover:
        print(f"  [DISCOVER MODE] Full Mouser scan — will update catalog")

    print("  Fetching exchange rate...")
    rate = get_exchange_rate()  # CNY → USD

    total_specs = len(SPECS)
    for idx, spec in enumerate(SPECS, 1):
        key = spec['key']
        if not force and key in history and today in history[key]:
            print(f"  [{idx}/{total_specs}] ✓ {key}  (skip)")
            continue

        print(f"  [{idx}/{total_specs}] {key} ...", end=' ', flush=True)

        # ── LCSC (multi-page) ─────────────────────────────────────
        lcsc_products = []
        seen_lcsc = set()

        def fetch_lcsc_page(url):
            """Fetch one LCSC page with retry + rate-limit detection."""
            nonlocal sc
            html = None
            for attempt in range(3):
                for fn in [
                    lambda u: sc.get(u, headers=HEADERS, timeout=30).text,
                    lambda u: requests.get(u, headers=HEADERS, timeout=30).text,
                ]:
                    try:
                        h = fn(url)
                        if h and len(h) > 5000:
                            html = h
                            break
                    except Exception:
                        pass
                if html and '嘉立创集团用户登录中心' in html:
                    wait = 10 + attempt * 8
                    print(f"[rate-limited, wait {wait}s]", end=' ', flush=True)
                    time.sleep(wait)
                    sc = cloudscraper.create_scraper()
                    html = None
                    continue
                break
            return html

        base_url = spec['url']
        for page in range(1, 11):  # up to 10 pages (~300 products)
            page_url = base_url if page == 1 else f"{base_url}&currentPage={page}"
            html = fetch_lcsc_page(page_url)
            if not html or len(html) < 5000:
                if page == 1:
                    print("LCSC FAILED", end=' ')
                break
            raw = parse_products(html)
            new_items = [p for p in raw if p.get('lcsc_id') and p['lcsc_id'] not in seen_lcsc]
            if not new_items:
                break   # no new items → last page reached
            for p in new_items:
                seen_lcsc.add(p['lcsc_id'])
                p['min_price_usd'] = round(p['min_price'] * rate, 6)
                p['currency'] = 'CNY'
                p['source'] = 'LCSC'
                p.setdefault('mouser_url', None)
                p['prices_usd'] = {q: round(v * rate, 6) for q, v in p.get('prices', {}).items()}
            lcsc_products.extend(new_items)
            if page > 1:
                time.sleep(2 + random.uniform(0, 2))   # polite delay between LCSC pages

        lcsc_products = clean_products(lcsc_products)   # apply brand whitelist to LCSC too

        # ── Mouser ────────────────────────────────────────────────
        mouser_products = []
        if mouser_key and spec.get('mouser_kw'):
            # Step 1: keyword search (limited pages normally, full scan in --discover)
            kw_products = fetch_mouser(spec['mouser_kw'], mouser_key, max_pages=mouser_pages)
            kw_products = clean_products(kw_products)
            kw_pns = {p['mouser_pn'] for p in kw_products if p.get('mouser_pn')}

            # Step 2: top-up from catalog — fetch parts not seen in keyword results
            catalog_pns = set(catalog.get(key, set()))
            missing_pns = catalog_pns - kw_pns
            TOPUP_LIMIT = 50   # safety cap: never fetch more than 50 missing PNs per spec
            if len(missing_pns) > TOPUP_LIMIT:
                missing_pns = set(list(missing_pns)[:TOPUP_LIMIT])
            extra_products = []
            if missing_pns and not discover:
                for pn in missing_pns:
                    prod = fetch_mouser_by_pn(pn, mouser_key)
                    if prod:
                        cleaned = clean_products([prod])
                        if cleaned:
                            extra_products.extend(cleaned)
                    time.sleep(0.3)
                if extra_products:
                    print(f"[+{len(extra_products)} catalog top-up]", end=' ')

            # Step 3: merge + update catalog in DB
            mouser_products = kw_products + extra_products
            new_pns = {p['mouser_pn'] for p in mouser_products if p.get('mouser_pn')}
            db_upsert_catalog(conn, key, new_pns)
            catalog.setdefault(key, set()).update(new_pns)

            for p in mouser_products:
                p['prices_usd'] = dict(p['prices'])  # already USD

        all_products = lcsc_products + mouser_products
        if not all_products:
            if html:
                debug_path = os.path.join(SCRIPT_DIR, f"debug_{key}.html")
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(html[:80000])
            print(f"0 products")
            continue

        instock = [p for p in all_products if p.get('stock', 0) > 0]
        usd_prices = [p['min_price_usd'] for p in instock if p.get('min_price_usd', 0) > 0]
        avg_usd = round(sum(usd_prices) / len(usd_prices), 6) if usd_prices else None
        total_stock = sum(p.get('stock', 0) for p in all_products)

        day_data = {
            'products':       all_products,
            'avg_price_usd':  avg_usd,
            'exchange_rate':  rate,
            'product_count':  len(all_products),
            'in_stock_count': len(instock),
            'total_stock':    total_stock,
            'lcsc_count':     len(lcsc_products),
            'mouser_count':   len(mouser_products),
            'fetched_at':     datetime.now().isoformat()
        }
        db_save_day(conn, key, today, day_data)      # persist immediately (crash-safe)
        history.setdefault(key, {})[today] = day_data
        print(f"LCSC:{len(lcsc_products)} Mouser:{len(mouser_products)}  avg ${avg_usd}")
        time.sleep(3 + random.uniform(0, 3))

    total_catalog = sum(len(v) for v in catalog.values())
    print(f"  DB catalog: {total_catalog} Mouser PNs across {len(catalog)} specs")
    conn.close()
    return history

# ── rebuild index.html ───────────────────────────────────────────
def slim_history(history):
    """Strip products from all but the latest date per spec (keeps HTML/JSON small).
    For older dates, precompute median_price_usd so the trend chart still works."""
    def _median(prods):
        prices = sorted(
            p.get('min_price_usd') or 0
            for p in prods
            if (p.get('stock') or 0) > 0 and (p.get('min_price_usd') or 0) > 0
        )
        if not prices: return None
        n, mid = len(prices), len(prices) // 2
        return (prices[mid-1] + prices[mid]) / 2 if n % 2 == 0 else prices[mid]

    slim = {}
    for sk, dates in history.items():
        slim[sk] = {}
        latest = max(dates.keys()) if dates else None
        for dt, v in dates.items():
            entry = {k: val for k, val in v.items() if k != 'products'}
            if dt == latest:
                entry['products'] = v.get('products', [])
            else:
                entry['median_price_usd'] = _median(v.get('products', []))
                entry['products'] = []
            slim[sk][dt] = entry
    return slim

def rebuild_html(history):
    if not os.path.exists(LOCAL_TMPL):
        print(f"ERROR: {LOCAL_TMPL} not found"); sys.exit(1)
    tmpl = open(LOCAL_TMPL, encoding='utf-8').read()
    return tmpl.replace('__HISTORY_JSON__', json_mod.dumps(slim_history(history), ensure_ascii=False))

# ── GitHub API push ──────────────────────────────────────────────
API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"

def gh_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def gh_push(path, content_str, msg):
    r = requests.get(f"{API}/{path}", headers=gh_headers())
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {"message": msg, "content": base64.b64encode(content_str.encode('utf-8')).decode()}
    if sha: body['sha'] = sha
    print(f"  Pushing {path} ({len(content_str):,} bytes)...")
    r = requests.put(f"{API}/{path}", headers=gh_headers(), json=body)
    if r.status_code in (200, 201):
        print(f"  ✅ {path}")
    else:
        print(f"  ❌ {path}  HTTP {r.status_code}")
        try:
            print(f"     {r.json().get('message','')}")
        except Exception:
            print(f"     {r.text[:200]}")

# ── main ─────────────────────────────────────────────────────────
def main():
    print("=" * 52)
    print("  Passive Component Price Updater")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 52)

    cfg = json_mod.load(open(CONFIG_FILE, encoding='utf-8')) if os.path.exists(CONFIG_FILE) else {}
    global GITHUB_TOKEN
    GITHUB_TOKEN = cfg.get('token', '')
    if not GITHUB_TOKEN:
        print("ERROR: github_config.json missing or no token"); sys.exit(1)
    MOUSER_KEY = cfg.get('mouser_key', '')
    if MOUSER_KEY:
        print(f"  Mouser API key loaded")
    else:
        print("  No Mouser key — LCSC only")

    today = datetime.now().strftime("%Y-%m-%d")
    # Check if today's data already exists (from DB, not JSON)
    _conn = init_db(); _conn.close()   # ensure DB is initialised
    import sqlite3 as _sq3
    with _sq3.connect(DB_FILE) as _c:
        _rows = _c.execute("SELECT COUNT(*) FROM daily_stats WHERE date=?", (today,)).fetchone()
    has_today = (_rows[0] > 0)
    interactive = sys.stdin.isatty()
    force    = '--force'    in sys.argv   # 命令列強制重抓
    discover = '--discover' in sys.argv   # 全量掃描以更新 catalog
    if discover:
        force = True   # discover 同時強制重抓
    if not force and has_today:
        if interactive:
            force = False  # 手動執行：跳過已抓的，只補新規格
        else:
            force = True   # 排程執行：每天 21:00 全部重抓最新資料
            print("\nAuto mode: re-fetching today's data...")

    print("[1/3] Scraping LCSC + Mouser...")
    history = scrape_all(force=force, mouser_key=MOUSER_KEY, discover=discover)

    print("\n[2/3] Rebuilding index.html...")
    html = rebuild_html(history)
    print(f"  {len(html):,} bytes")

    print("\n[3/3] Pushing to GitHub...")

    # 推送前驗證：今天有資料的規格數 < 50% → 疑似大規模抓取失敗，跳過推送
    specs_with_today = sum(1 for k in history if today in history[k] and history[k][today].get('product_count', 0) > 0)
    total_specs = len(SPECS)
    if specs_with_today < total_specs * 0.5:
        print(f"  ⚠️  只有 {specs_with_today}/{total_specs} 個規格有今日資料，疑似抓取異常，跳過推送。")
        print(f"  本地資料已保留於 {DB_FILE}")
        print(f"\n⚠️  未推送，請確認網路或 LCSC/Mouser 狀況後重試。\n")
    else:
        msg = f"price update {today}"
        gh_push("passive_components_prices.json", json_mod.dumps(slim_history(history), ensure_ascii=False, indent=2), msg)
        gh_push("index.html", html, msg)
        with open(LOCAL_TMPL, encoding='utf-8') as _f:
            gh_push("passive_components_template.html", _f.read(), msg)
        print(f"\n✅ Done!  https://evan0621.github.io/passive-components-tracker/\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    if sys.stdin.isatty():
        input("Press Enter to close...")
