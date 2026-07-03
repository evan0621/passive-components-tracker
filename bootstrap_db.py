"""
bootstrap_db.py — Sync historical data from GitHub JSON into local DB.
Safe to run every time: uses INSERT OR IGNORE for rows, UPDATE for null medians only.
"""
import json, sqlite3, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'passive_components.db')
JSON_URL = 'https://raw.githubusercontent.com/evan0621/passive-components-tracker/main/passive_components_prices.json'
PANEL_URL = 'https://raw.githubusercontent.com/evan0621/passive-components-tracker/main/panel.json'

def bootstrap(today=None):
    """today: 可信的台灣日期字串（由呼叫端傳入）；不傳才退回本機時鐘換算。"""
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
        except Exception:
            pass  # column already exists

    inserted = 0
    repaired = 0
    prod_count = 0

    for spec_key, dates in history.items():
        for date, entry in dates.items():
            # INSERT OR REPLACE: GitHub JSON is the source of truth.
            # This overwrites stale/bad DB rows (e.g., Mouser=0 bad data)
            # with whatever is currently in GitHub JSON.
            cur = conn.execute(
                "INSERT OR REPLACE INTO daily_stats "
                "(spec_key,date,avg_price_usd,total_stock,in_stock_count,product_count,"
                " lcsc_count,mouser_count,exchange_rate,fetched_at,median_price_usd,"
                " lcsc_avg_cny,lcsc_median_cny,mouser_avg_usd,mouser_median_usd,"
                " lcsc_stock,mouser_stock,mouser_leadtime_days) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (spec_key, date,
                 entry.get('avg_price_usd'), entry.get('total_stock'),
                 entry.get('in_stock_count'), entry.get('product_count'),
                 entry.get('lcsc_count', 0), entry.get('mouser_count', 0),
                 entry.get('exchange_rate'), entry.get('fetched_at'),
                 entry.get('median_price_usd'),
                 entry.get('lcsc_avg_cny'), entry.get('lcsc_median_cny'),
                 entry.get('mouser_avg_usd'), entry.get('mouser_median_usd'),
                 entry.get('lcsc_stock'), entry.get('mouser_stock'),
                 entry.get('mouser_leadtime_days'))
            )
            inserted += cur.rowcount

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
                            "stock,min_price_usd,min_qty,mouser_pn,lcsc_id,mouser_url,prices_json,min_price_cny) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (spec_key, date, p.get('source','LCSC'), p.get('model',''),
                             p.get('brand',''), p.get('package',''), p.get('description',''),
                             p.get('stock',0), p.get('min_price_usd'), p.get('min_qty'),
                             p.get('mouser_pn'), p.get('lcsc_id'), p.get('mouser_url'),
                             json.dumps(prices), p.get('min_price_cny'))
                        )
                        prod_count += 1

    # Sync DB to GitHub JSON: delete any date that was cleaned from JSON
    # (e.g., bad Mouser data removed manually), but keep today's fresh data
    if not today:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        today = _dt.now(_tz(_td(hours=8))).strftime("%Y-%m-%d")  # 台灣時間（本機換算，備援）
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

    # 同步固定追蹤名單（panel）— GH Actions 和 local PC 必須用同一份名單
    try:
        pr = requests.get(PANEL_URL, timeout=30)
        if pr.status_code == 200:
            rows = pr.json()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS panel (
                    spec_key    TEXT NOT NULL,
                    pid         TEXT NOT NULL,
                    model       TEXT,
                    status      TEXT NOT NULL DEFAULT 'active',
                    added       TEXT,
                    last_seen   TEXT,
                    miss_streak INTEGER DEFAULT 0,
                    seen_streak INTEGER DEFAULT 0,
                    PRIMARY KEY (spec_key, pid)
                )""")
            conn.executemany(
                "INSERT OR REPLACE INTO panel VALUES (?,?,?,?,?,?,?,?)",
                [tuple(r) for r in rows])
            print(f"  Panel synced: {len(rows)} entries")
    except Exception as _pe:
        print(f"  Panel sync skipped ({_pe})")

    conn.commit()
    conn.close()
    print(f"Done: {inserted} rows inserted, {repaired} medians repaired, {prod_count} products added, {deleted} stale rows removed")

if __name__ == '__main__':
    bootstrap()
