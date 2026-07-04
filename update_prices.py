#!/usr/bin/env python3
"""
Passive component price updater — double-click update_prices.bat to run.
"""

import re, json as json_mod, sys, os, base64, time
from datetime import datetime, timezone, timedelta

# 統一用台灣時間（UTC+8）計算日期，GH Actions 和 local PC 才會一致
# 重要：不信任本機時鐘/時區設定 — 先問網路（GitHub API 的 Date header），
# 拿不到才退回本機時間。曾發生本機時區設錯導致晚上抓的資料被標成「明天」。
_TAIWAN = timezone(timedelta(hours=8))
_TW_CLOCK_OFFSET = None   # network_TW - local_naive，第一次呼叫時量測

def _measure_clock_offset():
    """回傳 timedelta = 真實台灣時間 - 本機 naive 時間；量不到回傳 None。"""
    from email.utils import parsedate_to_datetime
    for url in ("https://api.github.com", "https://www.google.com"):
        try:
            import requests as _rq
            r = _rq.get(url, timeout=10, stream=True)
            hdr = r.headers.get('Date')
            if not hdr:
                continue
            net_tw = parsedate_to_datetime(hdr).astimezone(_TAIWAN)
            return net_tw.replace(tzinfo=None) - datetime.now()
        except Exception:
            continue
    return None

def _now_tw():
    """可信的台灣時間（tz-aware）。優先網路時間，退回本機換算。"""
    global _TW_CLOCK_OFFSET
    if _TW_CLOCK_OFFSET is None:
        off = _measure_clock_offset()
        if off is not None:
            _TW_CLOCK_OFFSET = off
            if abs(off) > timedelta(minutes=30):
                print(f"  ⚠️  本機時鐘/時區與台灣時間偏差 {off}（請檢查 Windows 時區設定，應為 UTC+8 台北）")
        else:
            _TW_CLOCK_OFFSET = datetime.now(_TAIWAN).replace(tzinfo=None) - datetime.now()
            print("  ⚠️  無法取得網路時間，退回本機時區換算（若時區設錯日期會不準）")
    return (datetime.now() + _TW_CLOCK_OFFSET).replace(tzinfo=_TAIWAN)

def _today_tw():
    return _now_tw().strftime("%Y-%m-%d")

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
    # LCSC 用中文關鍵字才能區分固液混合 vs 固態（英文 hybrid/polymer 會被忽略，兩者結果相同）
    {"key": "AlCap_PDB_100U_63V_M10x10", "url": "https://so.szlcsc.com/global.html?k=100uf+63v+%E5%9B%BA%E6%B6%B2%E6%B7%B7%E5%90%88", "mouser_kw": "100uF 63V hybrid aluminum SMD 10x10.2",
     "pin_lcsc": ["245958", "245590"]},  # 固液混合；pin 立隆 VZH101M1JTR-1010 / VE-101M1JTR-1010
    {"key": "Hybrid_560uF_16V_M8x10",    "url": "https://so.szlcsc.com/global.html?k=560uf+16v+%E5%9B%BA%E6%B6%B2%E6%B7%B7%E5%90%88",  "mouser_kw": "560uF 16V hybrid aluminum SMD 8x10"},      # 固液混合
    {"key": "Polymer_100uF_63V_M10x10",  "url": "https://so.szlcsc.com/global.html?k=100uf+63v+%E5%9B%BA%E6%80%81%E9%93%9D%E7%94%B5%E8%A7%A3","mouser_kw": "100uF 63V polymer aluminum SMD 10x10.2"},  # 固态铝电解
    # ── 鋁電解（牛角）AI
    # LCSC 牛角料要用中文「牛角」搜，英文 snap-in 搜不到金山電/立隆等品牌
    # pin_lcsc: 指定料號（永久追蹤，不受搜尋排序影響，每天直抓商品頁）
    {"key": "SnapIn_450V_1000uF",        "url": "https://so.szlcsc.com/global.html?k=1000uf+450v+%E7%89%9B%E8%A7%92", "mouser_kw": "1000uF 450V snap-in aluminum electrolytic", "min_v": 450,
     "pin_lcsc": ["6567239"]},           # 金山電 GM2W102MND3565 (1000uF 450V)
    {"key": "SnapIn_450V_820uF",         "url": "https://so.szlcsc.com/global.html?k=820uf+450v+%E7%89%9B%E8%A7%92",  "mouser_kw": "820uF 450V snap-in aluminum electrolytic",  "min_v": 450,
     "pin_lcsc": ["146216"]},            # 立隆 LSG821M2W--A3560 (820uF 450V)
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
    {"key": "AlCap_SnapIn_470uF_450V_AEC",    "url": "https://so.szlcsc.com/global.html?k=470uf+450v+%E7%89%9B%E8%A7%92",                   "mouser_kw": "470uF 450V snap-in aluminum electrolytic AEC-Q200", "min_v": 450},   # 牛角；LCSC 混入大量低壓料 → min_v 過濾
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

    # 交期（領先指標）："77 Days" → 77
    lt_m = re.search(r'(\d+)', str(p.get('LeadTime') or ''))
    lead_time_days = int(lt_m.group(1)) if lt_m else None

    min_qty = min(prices.keys())
    # 地板價：取階梯中「最低單價」（觀察地板價有沒有上調），非最小起訂量那一階
    min_price_usd, floor_qty = _floor_price(prices)
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
        'floor_qty':     floor_qty,
        'lead_time_days': lead_time_days,
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
            median_price_usd REAL,
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
        CREATE TABLE IF NOT EXISTS panel (
            spec_key    TEXT NOT NULL,
            pid         TEXT NOT NULL,   -- 'L:<lcsc_id>' 或 'M:<mouser_pn>'
            model       TEXT,
            status      TEXT NOT NULL DEFAULT 'active',  -- active/candidate/retired
            added       TEXT,
            last_seen   TEXT,
            miss_streak INTEGER DEFAULT 0,
            seen_streak INTEGER DEFAULT 0,
            PRIMARY KEY (spec_key, pid)
        );
    """)
    conn.commit()
    # Migrations: add columns to existing DBs (each fails silently if exists)
    for ddl in (
        "ALTER TABLE daily_stats ADD COLUMN median_price_usd REAL",
        "ALTER TABLE daily_stats ADD COLUMN lcsc_avg_cny REAL",
        "ALTER TABLE daily_stats ADD COLUMN lcsc_median_cny REAL",
        "ALTER TABLE daily_stats ADD COLUMN mouser_avg_usd REAL",
        "ALTER TABLE daily_stats ADD COLUMN mouser_median_usd REAL",
        "ALTER TABLE daily_stats ADD COLUMN lcsc_stock INTEGER",
        "ALTER TABLE daily_stats ADD COLUMN mouser_stock INTEGER",
        "ALTER TABLE daily_stats ADD COLUMN mouser_leadtime_days REAL",
        "ALTER TABLE products ADD COLUMN min_price_cny REAL",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception:
            pass
    return conn

def db_load_history(conn):
    """Reconstruct full history dict from SQLite (for rebuild_html / skip logic)."""
    history = {}
    for row in conn.execute(
        "SELECT spec_key,date,avg_price_usd,total_stock,in_stock_count,"
        "product_count,lcsc_count,mouser_count,exchange_rate,fetched_at,median_price_usd,"
        "lcsc_avg_cny,lcsc_median_cny,mouser_avg_usd,mouser_median_usd,"
        "lcsc_stock,mouser_stock,mouser_leadtime_days FROM daily_stats"
    ):
        (sk, dt, avg, ts, isc, pc, lc, mc, er, fa, med,
         lac, lmc, mau, mmu, lst, mst, mlt) = row
        history.setdefault(sk, {})[dt] = {
            'avg_price_usd': avg, 'total_stock': ts, 'in_stock_count': isc,
            'product_count': pc, 'lcsc_count': lc or 0, 'mouser_count': mc or 0,
            'exchange_rate': er, 'fetched_at': fa, 'median_price_usd': med,
            'lcsc_avg_cny': lac, 'lcsc_median_cny': lmc,
            'mouser_avg_usd': mau, 'mouser_median_usd': mmu,
            'lcsc_stock': lst, 'mouser_stock': mst, 'mouser_leadtime_days': mlt,
            'products': []
        }
    for row in conn.execute(
        "SELECT spec_key,date,source,model,brand,package,description,"
        "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json,min_price_cny FROM products"
    ):
        sk, dt, src, model, brand, pkg, desc, stk, mpu, mq, mpn, lid, murl, pj, mpc = row
        if sk in history and dt in history[sk]:
            prices = json_mod.loads(pj) if pj else {}
            history[sk][dt]['products'].append({
                'model': model or '', 'brand': brand or '',
                'package': pkg or '', 'description': desc or '',
                'stock': stk or 0, 'min_price_usd': mpu,
                'min_price': mpu, 'min_qty': mq, 'min_price_cny': mpc,
                'mouser_pn': mpn, 'lcsc_id': lid, 'mouser_url': murl,
                'source': src, 'prices': prices, 'prices_usd': prices,
                'currency': 'USD' if src == 'Mouser' else 'CNY',
            })
    return history

def _compute_median(products):
    prices = sorted(
        p.get('min_price_usd') or 0 for p in products
        if (p.get('stock') or 0) > 0 and (p.get('min_price_usd') or 0) > 0
    )
    if not prices: return None
    n, mid = len(prices), len(prices) // 2
    return (prices[mid-1] + prices[mid]) / 2 if n % 2 == 0 else prices[mid]

def db_save_day(conn, spec_key, date, day_data):
    """Upsert one day's data for a spec (replaces old entry if exists)."""
    # 優先使用呼叫端算好的（固定樣本池）median，沒有才用原始樣本重算
    median = day_data.get('median_price_usd')
    if median is None:
        median = _compute_median(day_data.get('products', []))
    conn.execute(
        "INSERT OR REPLACE INTO daily_stats "
        "(spec_key,date,avg_price_usd,total_stock,in_stock_count,product_count,"
        " lcsc_count,mouser_count,exchange_rate,fetched_at,median_price_usd,"
        " lcsc_avg_cny,lcsc_median_cny,mouser_avg_usd,mouser_median_usd,"
        " lcsc_stock,mouser_stock,mouser_leadtime_days) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        spec_key, date,
        day_data.get('avg_price_usd'), day_data.get('total_stock'),
        day_data.get('in_stock_count'), day_data.get('product_count'),
        day_data.get('lcsc_count'),    day_data.get('mouser_count'),
        day_data.get('exchange_rate'), day_data.get('fetched_at'),
        median,
        day_data.get('lcsc_avg_cny'),  day_data.get('lcsc_median_cny'),
        day_data.get('mouser_avg_usd'), day_data.get('mouser_median_usd'),
        day_data.get('lcsc_stock'),    day_data.get('mouser_stock'),
        day_data.get('mouser_leadtime_days'),
    ))
    conn.execute("DELETE FROM products WHERE spec_key=? AND date=?", (spec_key, date))
    for p in day_data.get('products', []):
        prices_usd = p.get('prices_usd') or p.get('prices') or {}
        conn.execute(
            "INSERT INTO products (spec_key,date,source,model,brand,package,description,"
            "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json,min_price_cny) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec_key, date, p.get('source','LCSC'), p.get('model',''),
             p.get('brand',''), p.get('package',''), p.get('description',''),
             p.get('stock',0), p.get('min_price_usd'), p.get('min_qty'),
             p.get('mouser_pn'), str(p.get('lcsc_id','')) if p.get('lcsc_id') else None,
             p.get('mouser_url'),
             json_mod.dumps({str(k): v for k, v in prices_usd.items()}),
             p.get('min_price_cny'))
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

# ── Method 0: __NEXT_DATA__ JSON（LCSC 2026-07 改版後的主要來源）──
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')

def parse_next_data(html):
    """LCSC 新版（Next.js）搜尋頁：完整資料都在 __NEXT_DATA__ JSON 裡。"""
    m = _NEXT_DATA_RE.search(html or '')
    if not m:
        return []
    try:
        data = json_mod.loads(m.group(1))
        recs = data['props']['pageProps']['soData']['searchResult']['productRecordList'] or []
    except Exception:
        return []
    out = []
    for rec in recs:
        pv = rec.get('productVO') or {}
        model = pv.get('productModel') or ''
        pid = str(pv.get('productId') or '')
        prices = {}
        for t in pv.get('productPriceList') or []:
            try:
                q = int(t.get('startPurchasedNumber') or t.get('spNumber') or 0)
                v = float(t.get('productPrice') or t.get('thePrice') or 0)
                if q > 0 and v > 0:
                    prices[q] = v
            except Exception:
                pass
        if not model or not pid or not prices:
            continue
        stock = max(int(rec.get('totalStockNumber') or 0),
                    int(pv.get('stockNumber') or 0),
                    int(pv.get('validStockNumber') or 0))
        out.append({
            'model': model,
            'lcsc_id': pid,
            'brand': _TAG_RE.sub('', rec.get('lightBrandName') or ''),
            'package': pv.get('encapsulationModel') or '',
            'description': _TAG_RE.sub('', rec.get('remarkPrefixTitle')
                                       or rec.get('lightProductIntro') or ''),
            'prices': prices,
            'stock': stock,
            'min_qty': min(prices),
            'min_price': prices[min(prices)],
        })
    return out

def parse_item_page(html):
    """LCSC 商品頁（item.szlcsc.com/<id>.html）→ 單一產品。
    SSR 只有現貨單價 + 整盤價，沒有完整階梯，但足夠算地板價。"""
    m = _NEXT_DATA_RE.search(html or '')
    if not m:
        return None
    try:
        pp = json_mod.loads(m.group(1))['props']['pageProps']
    except Exception:
        return None
    pr = (pp.get('webData') or {}).get('productRecord') or {}
    prices = {}
    try:
        price = float(pp.get('price') or 0)
        if price > 0:
            prices[int(pr.get('minBuyNumber') or 1)] = price
    except Exception:
        pass
    try:
        en, ep = pr.get('productMinEncapsulationNumber'), pr.get('encaptionPrice')
        if en and ep and float(en) > 0 and float(ep) > 0:
            prices[int(en)] = round(float(ep) / float(en), 6)
    except Exception:
        pass
    if not prices:
        return None
    stock = max(int(pr.get('stockNumber') or 0), int(pr.get('validStockNumber') or 0))
    return {
        'model': pr.get('productModel') or '',
        'lcsc_id': str(pr.get('productId') or ''),
        'brand': pr.get('productGradePlateName') or '',
        'package': pr.get('encapsulationModel') or '',
        'description': pr.get('remark') or '',
        'prices': prices,
        'stock': stock,
        'min_qty': min(prices),
        'min_price': prices[min(prices)],
    }

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
    r'|\bElite\b|金山'          # 金山電 8042 (Taiwan Chinsan)，品牌名 Elite / 金山电子
    # 中國國產鋁電解/電容大廠（LCSC 地板價主力）
    r'|Ymin|永铭|AISHI|艾华|KNSCHA|科尼盛|JIERR|捷而瑞'
    r'|CapXon|丰宾|Man.?Yue|万裕|SamYoung|三莹'
    r'|BERYL|绿宝石|TOPAZ|托普|KFSON|康富松|HONOR|荣誉'
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
    result = parse_next_data(html)      # 主要：Next.js JSON
    if result:
        return result
    result = parse_html_cards(html)     # 舊版 HTML 卡片
    if result:
        print("[fallback:html-cards]", end=' ')
        return result
    result = parse_jsonld(html)         # 最後手段（樣本極小，僅 3 筆/頁）
    if result:
        print(f"[fallback:json-ld {len(result)} items]", end=' ')
    return result

# ── 額定電壓 sanity check（防止低壓料混入高壓規格）────────────────
# EIA 電壓代碼（鋁電解料號常見，如 471M1E=25V、821M2W=450V）
_EIA_V_CODE = {
    '0E': 2.5, '0G': 4, '0J': 6.3, '1A': 10, '1C': 16, '1D': 20, '1E': 25,
    '1V': 35, '1H': 50, '1J': 63, '1K': 80, '2A': 100, '2B': 125, '2C': 160,
    '2D': 200, '2E': 250, '2F': 315, '2V': 350, '2G': 400, '2W': 450,
    '2H': 500, '2J': 630,
}
_EIA_V_RE = re.compile(r'\d{3}[MK]([0-2][A-Z])')          # 容量碼+公差+電壓碼
_EXPL_V_RE = re.compile(r'(\d{1,4}(?:\.\d)?)V(?=[^A-Za-z]|$)')  # 明碼電壓，V 後不能接字母

def _rated_voltage(p):
    """從型號/描述推測額定電壓（V）；推測不出回傳 None（保守保留）。"""
    text = f"{p.get('model', '')} {p.get('description', '')}"
    vs = [float(m.group(1)) for m in _EXPL_V_RE.finditer(text)]
    vs += [_EIA_V_CODE[m.group(1)] for m in _EIA_V_RE.finditer(text.upper())
           if m.group(1) in _EIA_V_CODE]
    return max(vs) if vs else None

def filter_min_voltage(products, min_v):
    """剔除額定電壓明確低於 min_v 的料；電壓不明的保留。"""
    kept, removed = [], []
    for p in products:
        v = _rated_voltage(p)
        if v is not None and v < min_v * 0.99:
            removed.append(f"{p.get('model','')}({v:g}V)")
        else:
            kept.append(p)
    if removed:
        tags = ', '.join(removed[:3]) + ('…' if len(removed) > 3 else '')
        print(f"[V<{min_v} 剔除 {len(removed)}: {tags}]", end=' ')
    return kept

# ── LCSC 樣本量守門 ──────────────────────────────────────────────
def _lcsc_guard(key, lcsc_products, history, today):
    """LCSC 筆數若比近 7 天中位數低太多（<60%），視為當日抓取降級，
    沿用最近一天的 LCSC 產品，避免爛樣本污染統計。
    回傳 (products, degraded, carried_from)。"""
    spec_hist = history.get(key, {})
    dates = sorted(d for d in spec_hist if d < today)[-7:]
    counts = sorted((spec_hist[d].get('lcsc_count') or 0) for d in dates)
    if not counts:
        return lcsc_products, False, None
    med = counts[len(counts) // 2]
    if med < 5 or len(lcsc_products) >= med * 0.6:
        return lcsc_products, False, None
    # 降級 — 從最近的日期往回找可沿用的 LCSC 樣本
    for d in reversed(dates):
        prev = [p for p in spec_hist[d].get('products', []) if p.get('source') == 'LCSC']
        if len(prev) >= med * 0.6:
            carried = []
            for p in prev:
                q = dict(p)
                q['carried'] = True
                q['carried_from'] = d
                _fp, _fq = _floor_price(q.get('prices_usd') or q.get('prices'))
                if _fp is not None:   # 統一地板價口徑
                    q['min_price_usd'] = round(_fp, 6)
                    q['floor_qty'] = _fq
                carried.append(q)
            print(f"[⚠️ LCSC degraded: {len(lcsc_products)} < 60% of median {med} — carrying {len(carried)} from {d}]", end=' ')
            return carried, True, d
    print(f"[⚠️ LCSC degraded: {len(lcsc_products)} vs median {med}, no carry source]", end=' ')
    return lcsc_products, True, None

# ── 固定樣本池統計（樣本組成穩定，跨日才可比較）───────────────────
def _pid(p):
    """產品的跨日穩定識別碼。"""
    if p.get('source') == 'Mouser' or p.get('mouser_pn'):
        return 'M:' + str(p.get('mouser_pn') or p.get('model'))
    return 'L:' + str(p.get('lcsc_id') or p.get('model'))

def compute_stats(products, spec_hist, today, lookback=7, min_frac=0.6):
    """回傳 dict(avg, median, raw_avg, raw_median, panel_size)。
    樣本池 = 近 lookback 天內出現在 >=60% 天數的料號；
    池內今日有價的料 >=5 筆才用池統計，否則退回全樣本。"""
    def _avg(xs): return round(sum(xs) / len(xs), 6) if xs else None
    def _med(xs):
        if not xs: return None
        n, m = len(xs), len(xs) // 2
        return round((xs[m-1] + xs[m]) / 2, 6) if n % 2 == 0 else round(xs[m], 6)

    instock = [p for p in products
               if (p.get('stock') or 0) > 0 and (p.get('min_price_usd') or 0) > 0]
    raw = sorted(p['min_price_usd'] for p in instock)
    out = {'avg': _avg(raw), 'median': _med(raw),
           'raw_avg': _avg(raw), 'raw_median': _med(raw), 'panel_size': None}

    # 只取有 products 明細的歷史日期（slim 同步回來的日期沒有明細）
    dates = sorted(d for d in (spec_hist or {})
                   if d < today and spec_hist[d].get('products'))[-lookback:]
    if len(dates) < 3:
        return out
    from collections import Counter
    seen = Counter()
    for d in dates:
        seen.update({_pid(p) for p in spec_hist[d]['products']})
    need = max(2, int(round(len(dates) * min_frac)))
    panel = {i for i, c in seen.items() if c >= need}
    panel_prices = sorted(p['min_price_usd'] for p in instock if _pid(p) in panel)
    if len(panel_prices) >= 5:
        out['avg'] = _avg(panel_prices)
        out['median'] = _med(panel_prices)
        out['panel_size'] = len(panel_prices)
    return out

# ── 固定追蹤名單（basket）：每天統計「同一批」料號 ────────────────
# 核心保證：統計樣本 = DB 裡的正式名單，跟當天搜尋結果好壞無關。
#   - 名單成員當天沒抓到 → 沿用最近一次價格（最多 PANEL_CARRY_MAX 天）
#   - 新料號連續出現 PANEL_ADD_STREAK 天才轉正進名單（避免搜尋雜訊）
#   - 成員連續缺席 PANEL_DROP_DAYS 天才除名（避免名單震盪）
PANEL_ADD_STREAK = 1    # 新料出現 N 天即轉正（=1 立即納入；若日後雜訊多可調回 5）
PANEL_DROP_DAYS  = 14   # 缺席 N 天 → 除名
PANEL_CARRY_MAX  = 7    # 缺席期間沿用舊價最多 N 天

def _find_last_record(spec_hist, pid, today, max_back=PANEL_CARRY_MAX):
    """往回找該料號最近一筆真實抓取紀錄。回傳 (product, date) 或 (None, None)。"""
    for d in sorted((d for d in spec_hist if d < today), reverse=True)[:max_back]:
        for p in spec_hist[d].get('products', []):
            if not p.get('carried') and _pid(p) == pid:
                return p, d
    return None, None

def _seed_panel(conn, key, spec_hist, today, today_pids, min_v=None):
    """初次建名單：近 7 天出現在 >=60% 天數的料號；歷史不足則用今天全部。"""
    dates = sorted(d for d in spec_hist
                   if d < today and spec_hist[d].get('products'))[-7:]
    if len(dates) >= 3:
        from collections import Counter
        seen = Counter()
        for d in dates:
            seen.update({_pid(p) for p in spec_hist[d]['products']
                         if not min_v or (_rated_voltage(p) or min_v) >= min_v * 0.99})
        need = max(2, int(round(len(dates) * 0.6)))
        pids = {i for i, c in seen.items() if c >= need}
    else:
        pids = set(today_pids)
    conn.executemany(
        "INSERT OR IGNORE INTO panel (spec_key,pid,model,status,added,last_seen,miss_streak,seen_streak) "
        "VALUES (?,?,?,?,?,?,0,0)",
        [(key, pid, '', 'active', today, today) for pid in pids])   # OR IGNORE: 不覆蓋 pinned
    conn.commit()
    print(f"[panel seeded: {len(pids)}]", end=' ')
    return pids

def panel_sample(conn, key, all_products, spec_hist, today, min_v=None):
    """維護名單並回傳 (統計樣本, 沿用的產品們, 摘要字串)。"""
    cur = {}
    for p in all_products:
        cur.setdefault(_pid(p), p)

    rows = conn.execute(
        "SELECT pid,status,last_seen,miss_streak,seen_streak,added "
        "FROM panel WHERE spec_key=?", (key,)).fetchall()
    members = {r[0]: {'status': r[1], 'last_seen': r[2],
                      'miss': r[3] or 0, 'seen': r[4] or 0, 'added': r[5]}
               for r in rows}

    actives = [pid for pid, m in members.items() if m['status'] in ('active', 'pinned')]
    # 播種判斷只看一般成員：pin 先註冊不代表名單已播種（否則樣本只剩 pin，統計會失真）
    if not any(m['status'] == 'active' for m in members.values()):
        seeded = _seed_panel(conn, key, spec_hist, today, cur.keys(), min_v)
        for pid in seeded:
            if pid not in members:   # 不覆蓋既有 pinned
                members[pid] = {'status': 'active', 'last_seen': today,
                                'miss': 0, 'seen': 0, 'added': today}
                actives.append(pid)

    # 名單裡已存在的低壓料 → 立即除名（規格加了 min_v 後的一次性清理）
    if min_v:
        purged = 0
        for pid in list(actives):
            src = cur.get(pid) or _find_last_record(spec_hist, pid, today)[0]
            v = _rated_voltage(src) if src else None
            if v is not None and v < min_v * 0.99:
                conn.execute("UPDATE panel SET status='retired' WHERE spec_key=? AND pid=?",
                             (key, pid))
                actives.remove(pid)
                purged += 1
        if purged:
            print(f"[panel V<{min_v} 除名 {purged}]", end=' ')

    prev_date = max((d for d in spec_hist if d < today), default=None)

    sample, carried_items = [], []
    fresh = carry = dropped = 0
    for pid in actives:
        m = members[pid]
        if pid in cur:
            sample.append(cur[pid]); fresh += 1
            conn.execute("UPDATE panel SET last_seen=?, miss_streak=0 WHERE spec_key=? AND pid=?",
                         (today, key, pid))
        else:
            miss = m['miss'] + 1
            if miss >= PANEL_DROP_DAYS and m['status'] != 'pinned':   # pinned 永不除名
                conn.execute("UPDATE panel SET status='retired', miss_streak=?, seen_streak=0 "
                             "WHERE spec_key=? AND pid=?", (miss, key, pid))
                dropped += 1
                continue
            conn.execute("UPDATE panel SET miss_streak=? WHERE spec_key=? AND pid=?",
                         (miss, key, pid))
            if miss <= PANEL_CARRY_MAX:
                lastp, lastd = _find_last_record(spec_hist, pid, today)
                if lastp:
                    q = dict(lastp)
                    q['carried'] = True
                    q['carried_from'] = lastd
                    _fp, _fq = _floor_price(q.get('prices_usd') or q.get('prices'))
                    if _fp is not None:   # 沿用的舊資料也統一成地板價口徑
                        q['min_price_usd'] = round(_fp, 6)
                        q['floor_qty'] = _fq
                    sample.append(q); carried_items.append(q); carry += 1

    # 名單外的料號 = 候選：連續出現 PANEL_ADD_STREAK 天才轉正
    added = 0
    for pid, p in cur.items():
        m = members.get(pid)
        if m and m['status'] in ('active', 'pinned'):
            continue
        streak = (m['seen'] + 1) if (m and m['last_seen'] == prev_date) else 1
        if streak >= PANEL_ADD_STREAK:
            conn.execute(
                "INSERT OR REPLACE INTO panel (spec_key,pid,model,status,added,last_seen,miss_streak,seen_streak) "
                "VALUES (?,?,?,?,?,?,0,?)",
                (key, pid, p.get('model', ''), 'active',
                 (m or {}).get('added') or today, today, streak))
            added += 1
        else:
            conn.execute(
                "INSERT OR REPLACE INTO panel (spec_key,pid,model,status,added,last_seen,miss_streak,seen_streak) "
                "VALUES (?,?,?,?,?,?,0,?)",
                (key, pid, p.get('model', ''), 'candidate',
                 (m or {}).get('added') or today, today, streak))
    conn.commit()

    note = f"panel:{fresh + carry}/{len(actives)} (fresh:{fresh} carry:{carry}"
    if added:   note += f" +{added}轉正"
    if dropped: note += f" -{dropped}除名"
    note += ")"
    return sample, carried_items, note

def _floor_price(prices):
    """從價格階梯取最低單價（地板價）與對應數量。鍵可能是 int 或 str。"""
    try:
        items = [(int(k), float(v)) for k, v in (prices or {}).items() if v and float(v) > 0]
    except Exception:
        return None, None
    if not items:
        return None, None
    mn = min(v for _, v in items)
    qty = max(q for q, v in items if v == mn)
    return mn, qty

def _basket_stats(products):
    """對固定名單樣本算 avg/median（僅 in-stock 且有價）。"""
    xs = sorted(p['min_price_usd'] for p in products
                if (p.get('stock') or 0) > 0 and (p.get('min_price_usd') or 0) > 0)
    if not xs:
        return {'avg': None, 'med': None, 'n': 0}
    n, m = len(xs), len(xs) // 2
    med = (xs[m-1] + xs[m]) / 2 if n % 2 == 0 else xs[m]
    return {'avg': round(sum(xs) / n, 6), 'med': round(med, 6), 'n': n}

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
    today = _today_tw()
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
        if spec.get('paused'):   # 規格加 "paused": True 即暫停追蹤（保留歷史）
            print(f"  [{idx}/{total_specs}] ⏸ {key}  (paused)")
            continue
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
            page_url = base_url if page == 1 else f"{base_url}&page={page}"   # 新版分頁參數
            html = fetch_lcsc_page(page_url)
            if not html or len(html) < 5000:
                if page == 1:
                    print("LCSC FAILED", end=' ')
                break
            # 第 1 頁若主解析（__NEXT_DATA__/HTML 卡片）為空（LCSC 改版/反爬），
            # 換 session 重試，避免直接退回只有 3 筆的 JSON-LD 爛樣本
            raw = parse_next_data(html) or parse_html_cards(html)
            if not raw and page == 1:
                for retry in range(2):
                    print(f"[parse-empty, retry {retry+1}]", end=' ', flush=True)
                    time.sleep(8 + retry * 7)
                    sc = cloudscraper.create_scraper()
                    html2 = fetch_lcsc_page(page_url)
                    if html2 and len(html2) > 5000:
                        raw = parse_next_data(html2) or parse_html_cards(html2)
                        if raw:
                            html = html2
                            break
            if not raw:
                raw = parse_jsonld(html)
                if raw:
                    print(f"[fallback:json-ld {len(raw)} items]", end=' ')
            new_items = [p for p in raw if p.get('lcsc_id') and p['lcsc_id'] not in seen_lcsc]
            if not new_items:
                break   # no new items → last page reached
            for p in new_items:
                seen_lcsc.add(p['lcsc_id'])
                # 地板價：取階梯最低單價；CNY 原幣另存（LCSC 指數用，排除匯率干擾）
                _fp, _fq = _floor_price(p.get('prices'))
                _fp_cny = _fp if _fp is not None else p['min_price']
                p['min_price_cny'] = round(_fp_cny, 6)
                p['min_price_usd'] = round(_fp_cny * rate, 6)
                p['floor_qty'] = _fq
                p['currency'] = 'CNY'
                p['source'] = 'LCSC'
                p.setdefault('mouser_url', None)
                p['prices_usd'] = {q: round(v * rate, 6) for q, v in p.get('prices', {}).items()}
            lcsc_products.extend(new_items)
            if page > 1:
                time.sleep(2 + random.uniform(0, 2))   # polite delay between LCSC pages

        lcsc_products = clean_products(lcsc_products)   # apply brand whitelist to LCSC too
        lcsc_products, lcsc_degraded, lcsc_carried_from = _lcsc_guard(key, lcsc_products, history, today)
        min_v = spec.get('min_v')
        if min_v:   # 額定電壓過濾（守門沿用的舊資料也要過）
            lcsc_products = filter_min_voltage(lcsc_products, min_v)

        # ── 指定料號（pin）註冊進名單：永久追蹤、不受搜尋排序影響 ──
        for lid in spec.get('pin_lcsc', []):
            conn.execute(
                "INSERT OR REPLACE INTO panel (spec_key,pid,model,status,added,last_seen,miss_streak,seen_streak) "
                "SELECT ?,?,COALESCE((SELECT model FROM panel WHERE spec_key=? AND pid=?),''),'pinned',"
                "COALESCE((SELECT added FROM panel WHERE spec_key=? AND pid=?),?),?,0,0",
                (key, 'L:' + str(lid), key, 'L:' + str(lid), key, 'L:' + str(lid), today, today))
        conn.commit()

        # ── LCSC 名單成員直抓：名單內的料就算搜尋排序掉出頁面，也直接抓商品頁 ──
        try:
            panel_lids = [r[0][2:] for r in conn.execute(
                "SELECT pid FROM panel WHERE spec_key=? AND status IN ('active','pinned') AND pid LIKE 'L:%'",
                (key,))]
        except Exception:
            panel_lids = []
        have_lids = {str(p.get('lcsc_id')) for p in lcsc_products}
        missing_lids = [l for l in panel_lids if l and l not in have_lids][:10]  # 上限 10 筆/規格
        topup_n = 0
        for lid in missing_lids:
            ih = fetch_lcsc_page(f"https://item.szlcsc.com/{lid}.html")
            prod = parse_item_page(ih) if ih else None
            if prod and prod.get('prices'):
                lastp, _ = _find_last_record(history.get(key, {}), 'L:' + lid, today)
                if lastp:   # 品牌/描述從歷史紀錄補（商品頁 SSR 沒品牌欄位）
                    prod['brand'] = prod.get('brand') or lastp.get('brand', '')
                    prod['description'] = prod.get('description') or lastp.get('description', '')
                if min_v:
                    v = _rated_voltage(prod)
                    if v is not None and v < min_v * 0.99:
                        continue
                _fp, _fq = _floor_price(prod['prices'])
                prod['min_price_cny'] = round(_fp, 6)
                prod['min_price_usd'] = round(_fp * rate, 6)
                prod['floor_qty'] = _fq
                prod['prices_usd'] = {q: round(vv * rate, 6) for q, vv in prod['prices'].items()}
                prod['currency'] = 'CNY'
                prod['source'] = 'LCSC'
                prod['topup'] = True
                prod.setdefault('mouser_url', None)
                lcsc_products.append(prod)
                topup_n += 1
            time.sleep(1 + random.uniform(0, 1))
        if topup_n:
            print(f"[+{topup_n} LCSC panel top-up]", end=' ')

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
            if min_v:
                mouser_products = filter_min_voltage(mouser_products, min_v)
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

        # ── 固定追蹤名單：統計樣本 = 名單成員（當日缺席者沿用最近價）──
        sample, carried_items, panel_note = panel_sample(
            conn, key, all_products, history.get(key, {}), today, min_v=min_v)
        stats = _basket_stats(sample)
        raw_stats = _basket_stats(all_products)
        if stats['avg'] is None:            # 名單全缺（理論上不會）→ 退回全樣本
            stats = raw_stats

        # ── 分源指數：LCSC 用人民幣原幣（排除匯率干擾）、Mouser 用美元 ──
        lcsc_sample   = [p for p in sample if p.get('source') != 'Mouser']
        mouser_sample = [p for p in sample if p.get('source') == 'Mouser']

        def _avg_med(xs):
            xs = sorted(xs)
            if not xs:
                return None, None
            n, m2 = len(xs), len(xs) // 2
            med = (xs[m2-1] + xs[m2]) / 2 if n % 2 == 0 else xs[m2]
            return round(sum(xs) / n, 6), round(med, 6)

        lc_cny = []
        for p in lcsc_sample:
            if (p.get('stock') or 0) <= 0:
                continue
            c = p.get('min_price_cny')
            if not c and rate and (p.get('min_price_usd') or 0) > 0:
                c = p['min_price_usd'] / rate   # 舊資料沒存 CNY 時的備援換算
            if c and c > 0:
                lc_cny.append(c)
        lcsc_avg_cny, lcsc_median_cny = _avg_med(lc_cny)
        mo_stats = _basket_stats(mouser_sample)

        # 交期（Mouser LeadTime 中位數，天）— 只算當日新鮮資料
        _lts = sorted(p['lead_time_days'] for p in mouser_sample
                      if p.get('lead_time_days') and not p.get('carried'))
        mouser_lt = None
        if _lts:
            _n = len(_lts)
            mouser_lt = _lts[_n//2] if _n % 2 else (_lts[_n//2-1] + _lts[_n//2]) / 2

        lcsc_stock   = sum(p.get('stock') or 0 for p in lcsc_sample)
        mouser_stock = sum(p.get('stock') or 0 for p in mouser_sample)

        day_products = all_products + carried_items
        instock = [p for p in day_products if p.get('stock', 0) > 0]
        total_stock = sum(p.get('stock', 0) for p in day_products)

        day_data = {
            'products':       day_products,
            'avg_price_usd':  stats['avg'],
            'median_price_usd': stats['med'],
            'raw_avg_price_usd': raw_stats['avg'],
            'panel_size':     stats['n'],
            'panel_carried':  len(carried_items),
            'lcsc_avg_cny':   lcsc_avg_cny,
            'lcsc_median_cny': lcsc_median_cny,
            'mouser_avg_usd': mo_stats['avg'],
            'mouser_median_usd': mo_stats['med'],
            'lcsc_stock':     lcsc_stock,
            'mouser_stock':   mouser_stock,
            'mouser_leadtime_days': mouser_lt,
            'exchange_rate':  rate,
            'product_count':  len(day_products),
            'in_stock_count': len(instock),
            'total_stock':    total_stock,
            'lcsc_count':     len(lcsc_products),
            'mouser_count':   len(mouser_products),
            'lcsc_carried_from': lcsc_carried_from,
            'fetched_at':     _now_tw().isoformat()
        }
        db_save_day(conn, key, today, day_data)      # persist immediately (crash-safe)
        history.setdefault(key, {})[today] = day_data
        _lc_note = f"¥{lcsc_avg_cny}" if lcsc_avg_cny else "—"
        _mo_note = f"${mo_stats['avg']}" if mo_stats['avg'] else "—"
        print(f"LCSC:{len(lcsc_products)} Mouser:{len(mouser_products)}  {panel_note}  LCSC均{_lc_note} Mouser均{_mo_note}")
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
                prods = v.get('products', [])
                if entry.get('median_price_usd') is None and prods:
                    # 只有在沒有算好的（固定樣本池）median 時才用原始樣本補算
                    entry['median_price_usd'] = _median(prods)
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

    today = _today_tw()
    interactive = sys.stdin.isatty()
    force     = '--force'     in sys.argv   # 命令列強制重抓
    discover  = '--discover'  in sys.argv   # 全量掃描以更新 catalog
    scheduled = '--scheduled' in sys.argv   # 明確標記為排程執行（Task Scheduler）
    if discover:
        force = True   # discover 同時強制重抓

    # ── 排程模式：先 pull GitHub JSON 同步本地 DB ──────────────────
    # GH Actions = primary (06:00 Taiwan); local PC = backup (21:00 Taiwan)
    # 每次排程都先 bootstrap（sync from GitHub），確保本地 DB 跟 GitHub 一致
    # （含清除 GitHub 上已刪除的壞資料日期）
    if not force and not discover and (scheduled or not interactive):
        print("  [sync] 從 GitHub 同步本地 DB...")
        try:
            import bootstrap_db as _bdb
            _bdb.bootstrap(today=today)
        except Exception as _e:
            print(f"  Bootstrap 失敗 ({_e}) — 繼續使用本地 DB")

        # 同步完後再確認今天有沒有資料（GH Actions 是否已跑）
        print("  [backup check] 確認 GH Actions 今早是否已執行...")
        import sqlite3 as _sq3b
        with _sq3b.connect(DB_FILE) as _cb:
            _today_rows = _cb.execute(
                "SELECT COUNT(*) FROM daily_stats WHERE date=? AND product_count > 0", (today,)
            ).fetchone()[0]
            _mouser_ok = _cb.execute(
                "SELECT COUNT(*) FROM daily_stats WHERE date=? AND mouser_count > 0", (today,)
            ).fetchone()[0]
        if _today_rows >= len(SPECS) * 0.8 and _mouser_ok >= len(SPECS) * 0.5:
            print(f"  GitHub 已有今日資料（{_today_rows}/{len(SPECS)} specs，{_mouser_ok} 有 Mouser 結果）")
            print(f"  GH Actions 今早已執行 — local PC 跳過，不重複抓取。")
            print(f"\n✅ Done!  https://evan0621.github.io/passive-components-tracker/\n")
            return
        else:
            print(f"  GitHub 無今日資料（{_today_rows}/{len(SPECS)} specs）— local PC 接管抓取")

    # Check if today's data already exists (from DB, not JSON)
    _conn = init_db(); _conn.close()   # ensure DB is initialised
    import sqlite3 as _sq3
    with _sq3.connect(DB_FILE) as _c:
        _rows = _c.execute("SELECT COUNT(*) FROM daily_stats WHERE date=?", (today,)).fetchone()
    has_today = (_rows[0] > 0)
    if not force and has_today:
        if interactive:
            force = False  # 手動執行：跳過已抓的，只補新規格
        else:
            force = True   # 排程執行：全部重抓最新資料
            print("\nAuto mode: re-fetching today's data...")

    print("[1/3] Scraping LCSC + Mouser...")
    history = scrape_all(force=force, mouser_key=MOUSER_KEY, discover=discover)

    print("\n[2/3] Rebuilding index.html...")
    html = rebuild_html(history)
    print(f"  {len(html):,} bytes")

    print("\n[3/3] Pushing to GitHub...")

    # 推送前驗證：Mouser 結果異常（rate limit）→ 跳過推送
    total_specs = len(SPECS)
    specs_with_today = sum(1 for k in history if today in history[k] and history[k][today].get('product_count', 0) > 0)
    mouser_zero = sum(1 for k in history if today in history[k] and history[k][today].get('mouser_count', 0) == 0)
    if specs_with_today < total_specs * 0.5:
        print(f"  ⚠️  只有 {specs_with_today}/{total_specs} 個規格有今日資料，疑似抓取異常，跳過推送。")
        print(f"\n⚠️  未推送，請確認網路或 LCSC/Mouser 狀況後重試。\n")
    elif mouser_zero > total_specs * 0.5:
        print(f"  ⚠️  {mouser_zero}/{total_specs} 個規格 Mouser 返回 0 筆（可能達到 API 配額上限），跳過推送。")
        print(f"  本地 DB 已保留今日 LCSC 資料，明天重跑即可。\n")
    else:
        msg = f"price update {today}"
        gh_push("passive_components_prices.json", json_mod.dumps(slim_history(history), ensure_ascii=False, indent=2), msg)
        gh_push("index.html", html, msg)
        with open(LOCAL_TMPL, encoding='utf-8') as _f:
            gh_push("passive_components_template.html", _f.read(), msg)
        # 固定追蹤名單也推上去，讓 GH Actions / local PC 用同一份名單
        import sqlite3 as _sq3p
        with _sq3p.connect(DB_FILE) as _cp:
            try:
                _panel_rows = _cp.execute(
                    "SELECT spec_key,pid,model,status,added,last_seen,miss_streak,seen_streak "
                    "FROM panel").fetchall()
                gh_push("panel.json", json_mod.dumps(_panel_rows, ensure_ascii=False), msg)
            except Exception as _pe:
                print(f"  panel.json 推送失敗（{_pe}）— 不影響價格資料")
        print(f"\n✅ Done!  https://evan0621.github.io/passive-components-tracker/\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    if sys.stdin.isatty():
        input("Press Enter to close...")
