"""
Angel One (SmartAPI) Token Generation
Requires: pip install smartapi-python pyotp
"""
import pyotp
import logging


def generate_angel_token(api_key, client_id, password, totp_secret):
    """
    Generate Angel One SmartAPI auth token using client credentials + TOTP.

    Args:
        api_key:      SmartAPI API key (from Angel One developer portal)
        client_id:    Angel One client ID (e.g. A12345)
        password:     Angel One login password / PIN
        totp_secret:  TOTP secret key (base32) for 2FA

    Returns:
        dict: {'auth_token': ..., 'refresh_token': ..., 'feed_token': ...}
    """
    print(f"Generating Angel One token for client {client_id}...")

    try:
        from SmartApi import SmartConnect
    except ImportError:
        raise ImportError(
            "smartapi-python not installed. Run: pip install smartapi-python"
        )

    totp_code = pyotp.TOTP(totp_secret).now()
    print(f"[DEBUG] TOTP for {client_id}: {totp_code}")

    obj = SmartConnect(api_key=api_key)

    print("[1/2] Generating SmartAPI session...")
    data = obj.generateSession(client_id, password, totp_code)

    if not data or data.get('status') is False:
        msg = data.get('message', 'Unknown error') if data else 'No response'
        raise Exception(f"Angel One login failed for {client_id}: {msg}")

    auth_token = data['data']['jwtToken']
    refresh_token = data['data']['refreshToken']
    feed_token = obj.getfeedToken()

    print(f"[2/2] Token generated successfully: {auth_token[:30]}...")
    return {
        'auth_token': auth_token,
        'refresh_token': refresh_token,
        'feed_token': feed_token,
        'smartconnect': obj,
    }


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    try:
        result = generate_angel_token(
            api_key=os.getenv('ANGEL_API_KEY'),
            client_id=os.getenv('ANGEL_CLIENT_ID'),
            password=os.getenv('ANGEL_PASSWORD'),
            totp_secret=os.getenv('ANGEL_TOTP_SECRET'),
        )
        print(f"\nSUCCESS! auth_token: {result['auth_token'][:40]}...")
    except Exception as e:
        print(f"\nFAILED: {e}")
