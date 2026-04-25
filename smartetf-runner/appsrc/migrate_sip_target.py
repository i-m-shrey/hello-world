"""
Database Migration Script for SIP Target Feature
Add monthly_sip_target and sip_target_updated_at columns to subscription table
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from app import app, db
from sqlalchemy import text

def migrate_database():
    """Add SIP target columns to subscription table"""
    
    with app.app_context():
        try:
            # Check if columns already exist
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'subscription' 
                AND column_name IN ('monthly_sip_target', 'sip_target_updated_at')
            """))
            
            existing_columns = [row[0] for row in result.fetchall()]
            
            if 'monthly_sip_target' not in existing_columns:
                print("Adding monthly_sip_target column...")
                db.session.execute(text("""
                    ALTER TABLE subscription 
                    ADD COLUMN monthly_sip_target DOUBLE PRECISION
                """))
                print("✅ monthly_sip_target column added successfully")
            else:
                print("✅ monthly_sip_target column already exists")
            
            if 'sip_target_updated_at' not in existing_columns:
                print("Adding sip_target_updated_at column...")
                db.session.execute(text("""
                    ALTER TABLE subscription 
                    ADD COLUMN sip_target_updated_at TIMESTAMP
                """))
                print("✅ sip_target_updated_at column added successfully")
            else:
                print("✅ sip_target_updated_at column already exists")
                
            db.session.commit()
            print("🎉 Migration completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {str(e)}")
            raise e

if __name__ == "__main__":
    print("🚀 Starting SIP Target Migration...")
    migrate_database()