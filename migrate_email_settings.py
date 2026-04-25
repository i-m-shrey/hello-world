#!/usr/bin/env python3
"""
Migration script to add EmailSettings table to the database.
Run this after updating models.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from models import db, EmailSettings

def create_email_settings_table():
    """Create the email_settings table"""
    app = Flask(__name__)
    
    # Database configuration
    db_url = os.getenv('DB_URL') or "postgresql+pg8000://postgres.qogfivsjxarodbyokfkn:P%40ssword123211600%26prince@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        try:
            # Create the table
            db.create_all()
            print("✅ EmailSettings table created successfully!")
            
            # Check if default settings exist
            settings = EmailSettings.query.first()
            if not settings:
                # Create default settings
                settings = EmailSettings()
                db.session.add(settings)
                db.session.commit()
                print("✅ Default email settings created!")
            else:
                print("ℹ️ Email settings already exist")
            
            print("\n📧 Email Settings Configuration:")
            print(f"  Provider: {settings.provider}")
            print(f"  Zoho Email: {settings.zoho_email}")
            print(f"  Gmail Email: {settings.gmail_email}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            db.session.rollback()
            sys.exit(1)

if __name__ == '__main__':
    create_email_settings_table()
