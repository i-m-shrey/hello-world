#!/usr/bin/env python3
"""
Test the NEW Dhan OAuth API method with actual DB credentials
"""
import os
import sys
from dotenv import load_dotenv

# Load env
load_dotenv()

# Test the NEW direct HTTP API method
print("=" * 60)
print("Testing NEW Dhan OAuth Direct HTTP API Method")
print("=" * 60)

def test_new_dhan_method(client_id, pin, totp_secret):
    """Test new HTTP API method"""
    import requests
    import pyotp

    print(f"\n[TEST] Generating token for client_id: {client_id}")

    try:
        totp_code = pyotp.TOTP(totp_secret).now()
        print(f"[INFO] TOTP generated: {totp_code}")

        url = (
            f"https://auth.dhan.co/app/generateAccessToken"
            f"?dhanClientId={client_id}&pin={pin}&totp={totp_code}"
        )

        print(f"[INFO] Calling API: {url[:60]}...")
        response = requests.post(url, timeout=20)

        print(f"[INFO] Response status: {response.status_code}")
        print(f"[INFO] Response: {response.text[:200]}")

        if response.status_code == 200:
            data = response.json()
            if "accessToken" in data:
                token = data["accessToken"]
                print(f"✅ SUCCESS! Token generated: {token[:30]}...")
                return True
            else:
                print(f"❌ FAILED: No accessToken in response")
                return False
        else:
            print(f"❌ FAILED: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


# Try to get DHAN credentials from DB
print("\n[INFO] Connecting to database to fetch DHAN credentials...")
try:
    import sqlalchemy as sa

    db_url = os.getenv('DB_URL')
    if not db_url:
        print("❌ No DB_URL in .env")
        sys.exit(1)

    engine = sa.create_engine(db_url)

    with engine.connect() as conn:
        result = conn.execute(sa.text("""
            SELECT b.user_id_broker, b.password, b.totp_secret, b.api_key, b.api_secret,
                   u.full_name, u.customer_id
            FROM broker b
            JOIN "user" u ON u.id = b.user_id
            WHERE b.broker_name = 'DHAN'
            AND b.subscription_status = 'Active'
            LIMIT 1
        """))

        row = result.fetchone()
        if not row:
            print("❌ No active DHAN broker found in database")
            sys.exit(1)

        client_id = row[0]
        pin = row[1]
        totp_secret = row[2]
        api_key = row[3]
        api_secret = row[4]
        full_name = row[5]
        customer_id = row[6]

        print(f"✅ Found DHAN client: {full_name} ({customer_id})")
        print(f"   Client ID: {client_id}")
        print(f"   Has TOTP: {'Yes' if totp_secret else 'No'}")

        # Test the NEW method
        success = test_new_dhan_method(client_id, pin, totp_secret)

        if success:
            print("\n" + "=" * 60)
            print("✅ NEW Dhan API Method WORKS - Can replace old Playwright method")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ NEW Dhan API Method FAILED - Keep old Playwright method")
            print("=" * 60)

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Install required packages: pip install sqlalchemy pyotp requests")
except Exception as e:
    print(f"❌ Database error: {e}")
    import traceback
    traceback.print_exc()
