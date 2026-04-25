"""
Migration: Add proxy support to SmartETF

Run this ONCE against your Supabase PostgreSQL database.
It is safe to run multiple times (idempotent).

What this does:
  1. Adds proxy_ip and proxy_label columns to the broker table
  2. Creates the proxy_pool table
  3. Seeds the 20 Webshare proxies you purchased

Usage:
    python migrate_add_proxy_ip.py
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app import app, db
from sqlalchemy import text

# ── Your 20 Webshare proxies ─────────────────────────────────────────────────
# Format: (IP, PORT, USERNAME, PASSWORD, COUNTRY, CITY)
WEBSHARE_PROXIES = [
    ("140.233.170.13",  "7725", "vqsekvvw", "z2l9ui08sn2z", "Italy",         "Milan"),
    ("9.142.194.93",    "6761", "vqsekvvw", "z2l9ui08sn2z", "United States", "Sacramento"),
    ("9.142.219.210",   "6374", "vqsekvvw", "z2l9ui08sn2z", "United States", "Sacramento"),
    ("5.59.250.6",      "6704", "vqsekvvw", "z2l9ui08sn2z", "Italy",         "Pomezia"),
    ("9.142.199.71",    "5238", "vqsekvvw", "z2l9ui08sn2z", "United States", "Sacramento"),
    ("82.21.62.77",     "7841", "vqsekvvw", "z2l9ui08sn2z", "Italy",         "Milan"),
    ("9.142.22.234",    "6891", "vqsekvvw", "z2l9ui08sn2z", "United States", "Sacramento"),
    ("104.253.109.147", "5425", "vqsekvvw", "z2l9ui08sn2z", "Germany",       "Frankfurt"),
    ("138.226.77.243",  "7432", "vqsekvvw", "z2l9ui08sn2z", "United States", "Sacramento"),
    ("46.203.15.152",   "7153", "vqsekvvw", "z2l9ui08sn2z", "France",        "Paris"),
    ("216.98.255.63",   "6685", "vqsekvvw", "z2l9ui08sn2z", "United States", ""),
    ("82.23.103.185",   "7912", "vqsekvvw", "z2l9ui08sn2z", "United Kingdom",""),
    ("96.62.180.231",   "7941", "vqsekvvw", "z2l9ui08sn2z", "United States", ""),
    ("46.203.20.251",   "6752", "vqsekvvw", "z2l9ui08sn2z", "France",        ""),
    ("82.23.61.196",    "7948", "vqsekvvw", "z2l9ui08sn2z", "United Kingdom",""),
    ("192.145.71.53",   "6690", "vqsekvvw", "z2l9ui08sn2z", "United States", ""),
    ("216.98.255.69",   "6691", "vqsekvvw", "z2l9ui08sn2z", "United States", ""),
    ("103.130.178.43",  "5707", "vqsekvvw", "z2l9ui08sn2z", "India",         ""),
    ("46.203.144.45",   "7812", "vqsekvvw", "z2l9ui08sn2z", "France",        ""),
    ("9.142.34.170",    "6841", "vqsekvvw", "z2l9ui08sn2z", "United States", ""),
]


def run_migration():
    with app.app_context():
        with db.engine.connect() as conn:

            # ── 1. broker.proxy_ip column ──────────────────────────────────
            res = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='broker' AND column_name='proxy_ip'
            """))
            if not res.fetchone():
                conn.execute(text("ALTER TABLE broker ADD COLUMN proxy_ip VARCHAR(255)"))
                print("✅ Added broker.proxy_ip")
            else:
                print("ℹ️  broker.proxy_ip already exists")

            # ── 2. broker.proxy_label column ──────────────────────────────
            res = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='broker' AND column_name='proxy_label'
            """))
            if not res.fetchone():
                conn.execute(text("ALTER TABLE broker ADD COLUMN proxy_label VARCHAR(100)"))
                print("✅ Added broker.proxy_label")
            else:
                print("ℹ️  broker.proxy_label already exists")

            # ── 3. proxy_pool table ────────────────────────────────────────
            res = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name='proxy_pool'
            """))
            if not res.fetchone():
                conn.execute(text("""
                    CREATE TABLE proxy_pool (
                        id               SERIAL PRIMARY KEY,
                        proxy_ip         VARCHAR(50)  NOT NULL,
                        proxy_port       VARCHAR(10)  NOT NULL,
                        proxy_username   VARCHAR(100) NOT NULL,
                        proxy_password   VARCHAR(100) NOT NULL,
                        proxy_url        VARCHAR(255) NOT NULL,
                        label            VARCHAR(100),
                        country          VARCHAR(50),
                        city             VARCHAR(50),
                        is_active        BOOLEAN DEFAULT TRUE,
                        assigned_broker_id INTEGER REFERENCES broker(id) ON DELETE SET NULL,
                        created_at       TIMESTAMP DEFAULT NOW()
                    )
                """))
                print("✅ Created proxy_pool table")
            else:
                print("ℹ️  proxy_pool table already exists")

            conn.commit()

            # ── 4. Seed proxies (skip if already seeded) ───────────────────
            res = conn.execute(text("SELECT COUNT(*) FROM proxy_pool"))
            count = res.scalar()
            if count == 0:
                for i, (ip, port, user, pwd, country, city) in enumerate(WEBSHARE_PROXIES, 1):
                    url = f"http://{user}:{pwd}@{ip}:{port}"
                    label = f"Proxy #{i} — {country}{' / ' + city if city else ''}"
                    conn.execute(text("""
                        INSERT INTO proxy_pool
                            (proxy_ip, proxy_port, proxy_username, proxy_password,
                             proxy_url, label, country, city)
                        VALUES
                            (:ip, :port, :user, :pwd, :url, :label, :country, :city)
                    """), {"ip": ip, "port": port, "user": user, "pwd": pwd,
                           "url": url, "label": label, "country": country, "city": city})
                conn.commit()
                print(f"✅ Seeded {len(WEBSHARE_PROXIES)} proxies into proxy_pool")
            else:
                print(f"ℹ️  proxy_pool already has {count} rows — skipping seed")

        print("\n✅ Migration complete!")
        print("\nNext steps:")
        print("  1. Go to Admin → Broker Passwords (/admin/broker-passwords)")
        print("  2. Scroll to 'Static IP Assignment' section")
        print("  3. Assign one proxy to each client")
        print("  4. Copy the IP shown → whitelist it on each client's broker portal")
        return True


if __name__ == '__main__':
    ok = run_migration()
    sys.exit(0 if ok else 1)
