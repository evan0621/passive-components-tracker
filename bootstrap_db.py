"""
bootstrap_db.py — Sync historical data from GitHub JSON into local DB.
Safe to run every time: uses INSERT OR IGNORE for rows, UPDATE for null medians only.
"""
import json, sqlite3, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'passive_components.db')
JSON_URL = 'https://raw.githubusercontent.com/evan0621/passive-components-tracker/main/passive_components_prices.json'

def bootstrap():
    import requests
    print("Syncing from GitHub JSON (filling gaps only)...")
    r = requests.get(JSON_URL, timeout=60)
    r.raise_for_status()
    history = r.json()

    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            spec_key TEXT NOT NULL, date TEXT NOT NULL,
            avg_price_usd REAL, total_stock INTEGER, in_stock_count INTEGER,
            product_count INTEGER, lcsc_count INTEGER, mouser_count INTEGER,
            exchange_rate REAL, fetched_at TEXT, median_price_usd REAL,
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
    try:
        conn.execute("ALTER TABLE daily_stats ADD COLUMN median_price_usd REAL")
    except Exception:
        pass  # column already exists

    inserted = 0
    repaired = 0
    prod_count = 0

    for spec_key, dates in history.items():
        for date, entry in dates.items():
            # Insert row if not exists (preserve today's freshly-fetched data)
            cur = conn.execute(
                "INSERT OR IGNORE INTO daily_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (spec_key, date,
                 entry.get('avg_price_usd'), entry.get('total_stock'),
                 entry.get('in_stock_count'), entry.get('product_count'),
                 entry.get('lcsc_count', 0), entry.get('mouser_count', 0),
                 entry.get('exchange_rate'), entry.get('fetched_at'),
                 entry.get('median_price_usd'))
            )
            inserted += cur.rowcount

            # Repair null median_price_usd for existing rows
            median = entry.get('median_price_usd')
            if median is not None:
                cur = conn.execute(
                    "UPDATE daily_stats SET median_price_usd=? WHERE spec_key=? AND date=? AND median_price_usd IS NULL",
                    (median, spec_key, date)
                )
                repaired += cur.rowcount

            # Insert products only if none exist for this spec+date
            products = entry.get('products', [])
            if products:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM products WHERE spec_key=? AND date=?",
                    (spec_key, date)
                ).fetchone()[0]
                if existing == 0:
                    for p in products:
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

    # Sync DB to GitHub JSON: delete any date that was cleaned from JSON
    # (e.g., bad Mouser data removed manually), but keep today's fresh data
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    today = _dt.now(_tz(_td(hours=8))).strftime("%Y-%m-%d")  # 台灣時間
    valid_dates = set(d for dates in history.values() for d in dates.keys())
    all_db_dates = set(
        row[0] for row in conn.execute("SELECT DISTINCT date FROM daily_stats")
    )
    stale_dates = all_db_dates - valid_dates - {today}
    deleted = 0
    for d in stale_dates:
        r = conn.execute("DELETE FROM daily_stats WHERE date=?", (d,))
        conn.execute("DELETE FROM products WHERE date=?", (d,))
        deleted += r.rowcount
        print(f"  Removed stale date {d} from DB (not in GitHub JSON)")

    conn.commit()
    conn.close()
    print(f"Done: {inserted} rows inserted, {repaired} medians repaired, {prod_count} products added, {deleted} stale rows removed")

if __name__ == '__main__':
    bootstrap()
