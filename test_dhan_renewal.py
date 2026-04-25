"""
Test DHAN token renewal
Run: python test_dhan_renewal.py
"""
from app import app
from models import db, Broker, User
from dhan_security_helper import decrypt_dhan_client_id
from dhan_api import DhanAPI, DhanAuth

with app.app_context():
    # Find first DHAN broker
    broker = Broker.query.filter_by(broker_name='DHAN').first()
    
    if not broker:
        print("❌ No DHAN broker found")
        exit(1)
    
    client_id = decrypt_dhan_client_id(
        broker.dhan_client_id_enc,
        broker.dhan_client_id_iv,
        broker.dhan_client_id_tag
    )
    access_token = broker.access_token
    
    if not client_id or not access_token:
        print("❌ Missing client_id or access_token")
        exit(1)
    
    print(f"Testing renewal for: {broker.user_id_broker}")
    print(f"Client ID: {client_id}")
    print(f"Current token: {access_token[:20]}...")
    
    try:
        auth = DhanAuth(client_id=client_id, access_token=access_token)
        api = DhanAPI(auth)
        
        new_token = api.renew_token()
        print(f"✅ SUCCESS! Token renewed")
        print(f"New token: {new_token[:20]}...")
        
        # Save to DB
        broker.access_token = new_token
        db.session.commit()
        print("✅ Saved to database")
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
