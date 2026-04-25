"""
Migration: Increase token columns size from VARCHAR(255) to TEXT
Run: python migrate_access_token.py
"""
from app import app, db
from sqlalchemy import text

with app.app_context():
    columns = ['access_token', 'secret_key', 'token_id', 'session_token']
    
    for column in columns:
        try:
            print(f"🔧 Migrating broker.{column} from VARCHAR(255) to TEXT...")
            
            db.session.execute(text(f"""
                ALTER TABLE broker 
                ALTER COLUMN {column} TYPE TEXT
            """))
            
            db.session.commit()
            print(f"✅ {column} migrated successfully")
            
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ {column} migration skipped: {e}")
    
    print("\n✅ All token columns migration completed!")
