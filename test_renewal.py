"""
Test DHAN token renewal - Run now to verify fix
Usage: python test_renewal.py
"""
from app import app
from models import Broker
from dhan_security_helper import decrypt_dhan_client_id
from dhan_api import DhanAPI, DhanAuth

with app.app_context():
    broker = Broker.query.filter_by(broker_name='DHAN').first()
    
    if not broker:
        print("❌ No DHAN broker found")
        exit(1)
    
    client_id = decrypt_dhan_client_id(
        broker.dhan_client_id_enc,
        broker.dhan_client_id_iv,
        broker.dhan_client_id_tag
    )
    
    if not client_id or not broker.access_token:
        print("❌ Missing client_id or access_token")
        exit(1)
    
    print(f"Testing renewal for broker ID: {broker.id}")
    print(f"Client ID: {client_id}")
    print(f"Current token: {broker.access_token[:30]}...")
    
    try:
        auth = DhanAuth(client_id=client_id, access_token=broker.access_token)
        api = DhanAPI(auth)
        
        new_token = api.renew_token()
        print(f"\n✅ SUCCESS! Token renewed")
        print(f"New token: {new_token[:30]}...")
        
        broker.access_token = new_token
        from models import db
        db.session.commit()
        print("✅ Saved to database")
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
