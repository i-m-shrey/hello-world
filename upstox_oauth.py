"""
Upstox Token Generation - Using upstox-totp library

The upstox-totp library handles the full OAuth2 + TOTP login flow automatically.
No manual browser/redirect needed.
"""
from upstox_totp import UpstoxTOTP


def generate_upstox_token(api_key, api_secret, mobile, password, totp_secret):
    """
    Generate Upstox access token using upstox-totp library.

    Args:
        api_key:     Upstox API Key (client_id from developer console)
        api_secret:  Upstox API Secret (client_secret)
        mobile:      Upstox registered mobile number (username)
        password:    Upstox login password
        totp_secret: TOTP secret for 2FA (base32 format)

    Returns:
        str: access_token string

    Flow:
    1. Initialize UpstoxTOTP with credentials directly (no env vars needed)
    2. Library handles OAuth flow + TOTP automatically
    3. Returns access token from AccessTokenResponse.data.access_token
    """
    print(f"Generating Upstox access token for mobile {str(mobile)[:6]}...")

    try:
        upx = UpstoxTOTP(
            username=mobile,
            password=password,
            totp_secret=totp_secret,
            client_id=api_key,
            client_secret=api_secret,
            redirect_uri='https://127.0.0.1',
        )

        print(f"[1/2] Initiating OAuth flow with TOTP...")
        response = upx.app_token.get_access_token()

        if response and response.data and response.data.access_token:
            access_token = response.data.access_token
            print(f"[2/2] Token generated successfully: {access_token[:30]}...")
            return access_token
        else:
            raise Exception(f"Token generation failed — unexpected response: {response}")

    except Exception as e:
        raise Exception(f"Upstox token generation failed: {e}")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    try:
        token = generate_upstox_token(
            api_key=os.getenv('UPSTOX_API_KEY'),
            api_secret=os.getenv('UPSTOX_API_SECRET'),
            mobile=os.getenv('UPSTOX_MOBILE'),
            password=os.getenv('UPSTOX_PASSWORD'),
            totp_secret=os.getenv('UPSTOX_TOTP_SECRET'),
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")
