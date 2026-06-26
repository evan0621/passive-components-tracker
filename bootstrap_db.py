"""
bootstrap_db.py — If local DB is empty, import historical data from GitHub JSON.
Run before update_prices.py on first GitHub Actions execution.
"""
import json, sqlite3, os, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'passive_components.db')
JSON_URL = 'https://raw.githubusercontent.com/evan0621/passive-components-tracker/main/passive_components_prices.json'

def needs_bootstrap():
    if not os.path.exists(DB): return True
    conn = sqlite3.connect(DB)
    try:
        count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='daily_stats'").fetchone()[0]
        if count == 0: return True
        rows = conn.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0]
        return rows == 0
    except: return True
    finally: conn.close()

def bootstrap():
    import requests
    print(f"DB empty — bootstrapping from GitHub JSON...")
    r = requests.get(JSON_URL, timeout=60)
    r.raise_for_status()
    history = r.json()

    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            spec_key TEXT NOT NULL, date TEXT NOT NULL,
            avg_price_usd REAL, total_stock INTEGER, in_stock_count INTEGER,
            product_count INTEGER, lcsc_count INTEGER, mouser_count INTEGER,
            exchange_rate REAL, fetched_at TEXT,
            PRIMARY KEY (spec_key, date)
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spec_key TEXT NOT NULL, date TEXT NOT NULL, source TEXT NOT NULL,
            model TEXT, brand TEXT, package TEXT, description TEXT,
            stock INTEGER, min_price_usd REAL, min_qty INTEGER,
            mouser_pn TEXT, lcsc_id TEXT, mouser_url TEXT, prices_json TEXT
        );
        CREATE TABLE IF NOT EXISTS mouser_catalog (
            spec_key TEXT NOT NULL, mouser_pn TEXT NOT NULL,
            PRIMARY KEY (spec_key, mouser_pn)
        );
        CREATE INDEX IF NOT EXISTS idx_prod_spec_date ON products(spec_key, date);
        CREATE INDEX IF NOT EXISTS idx_prod_mouser_pn  ON products(mouser_pn);
    """)

    stats_count = 0
    prod_count = 0
    for spec_key, dates in history.items():
        for date, entry in dates.items():
            conn.execute(
                "INSERT OR REPLACE INTO daily_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                (spec_key, date,
                 entry.get('avg_price_usd'), entry.get('total_stock'),
                 entry.get('in_stock_count'), entry.get('product_count'),
                 entry.get('lcsc_count', 0), entry.get('mouser_count', 0),
                 entry.get('exchange_rate'), entry.get('fetched_at'))
            )
            stats_count += 1
            for p in entry.get('products', []):
                prices = p.get('prices') or p.get('prices_usd') or {}
                conn.execute(
                    "INSERT INTO products (spec_key,date,source,model,brand,package,description,"
                    "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (spec_key, date, p.get('source','LCSC'), p.get('model',''),
                     p.get('brand',''), p.get('package',''), p.get('description',''),
                     p.get('stock',0), p.get('min_price_usd'), p.get('min_qty'),
                     p.get('mouser_pn'), p.get('lcsc_id'), p.get('mouser_url'),
                     json.dumps(prices))
                )
                prod_count += 1
    conn.commit()
    conn.close()
    print(f"Bootstrap done: {stats_count} daily_stats, {prod_count} products")

if __name__ == '__main__':
    if needs_bootstrap():
        bootstrap()
    else:
        count = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0]
        print(f"DB already has {count} rows — skipping bootstrap")
