"""
Migration: ALTER broker.api_key from VARCHAR(255) to TEXT

Run once on your production DB:
    python migrate_api_key_to_text.py

Safe for all brokers - TEXT is functionally identical to VARCHAR for short values.
Only removes the 255-char limit, needed for Groww's long JWT api_key.
"""
from app import app, db

def run():
    with app.app_context():
        try:
            db.engine.execute("ALTER TABLE broker ALTER COLUMN api_key TYPE TEXT")
            print("✅ broker.api_key successfully changed to TEXT")
        except Exception as e:
            # SQLAlchemy 2.x uses connection directly
            with db.engine.connect() as conn:
                conn.execute(db.text("ALTER TABLE broker ALTER COLUMN api_key TYPE TEXT"))
                conn.commit()
            print("✅ broker.api_key successfully changed to TEXT")

if __name__ == "__main__":
    run()
