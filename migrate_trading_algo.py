"""Migration: Create ETF Trading Algo tables."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app
from models import db, TradingAlgoSettings, TradingAlgoETFConfig, TradingAlgoSubscription, TradingAlgoPosition

with app.app_context():
    db.create_all()
    if not TradingAlgoSettings.query.first():
        s = TradingAlgoSettings()
        db.session.add(s)
        db.session.commit()
        print('Created default TradingAlgoSettings (id=1).')
    else:
        print('TradingAlgoSettings already exists.')
    print('Migration complete.')
