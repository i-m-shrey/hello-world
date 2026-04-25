"""
DHAN Token Generation - Pure HTTP API (no Playwright/Selenium)

Uses the official DhanHQ direct token generation endpoint:
  POST https://auth.dhan.co/app/generateAccessToken
    ?dhanClientId={client_id}&pin={pin}&totp={totp_code}

Requires TOTP to be enabled on the DHAN account.
Docs: https://dhanhq.co/docs/v2/authentication/
"""
import requests
import pyotp


def generate_dhan_token(api_key, api_secret, client_id, mobile_number, pin, totp_secret):
    """
    Generate DHAN access token using the direct REST API (no browser automation).

    Args:
        api_key:        Dhan App ID (used by partner consent flow — not needed here but kept for API compat)
        api_secret:     Dhan App Secret (same as above)
        client_id:      Dhan Client ID (numeric, e.g. '1102446172')
        mobile_number:  Not required for this flow (kept for API compatibility)
        pin:            Dhan 6-digit PIN
        totp_secret:    TOTP secret (base32) for 2FA

    Returns:
        str: access token valid for 24 hours
    """
    print(f"Generating DHAN token for {client_id}...")

    totp_code = pyotp.TOTP(totp_secret).now()
    print(f"[DEBUG] TOTP for {client_id}: {totp_code}")

    url = (
        f"https://auth.dhan.co/app/generateAccessToken"
        f"?dhanClientId={client_id}&pin={pin}&totp={totp_code}"
    )

    print("[1/1] Requesting access token from DhanHQ API...")
    response = requests.post(url, timeout=20)

    if response.status_code != 200:
        raise Exception(
            f"DHAN token generation failed: HTTP {response.status_code} — {response.text}"
        )

    data = response.json()

    if data.get("status") == "error" or "accessToken" not in data:
        msg = data.get("message", str(data))
        raise Exception(f"DHAN token generation failed for {client_id}: {msg}")

    access_token = data["accessToken"]
    expiry = data.get("expiryTime", "24h")
    print(f"[SUCCESS] Token generated (expires: {expiry}): {access_token[:30]}...")
    return access_token


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    try:
        token = generate_dhan_token(
            api_key=os.getenv('api_key', ''),
            api_secret=os.getenv('api_secret', ''),
            client_id=os.getenv('client_id'),
            mobile_number=os.getenv('mobileno', ''),
            pin=os.getenv('pin'),
            totp_secret=os.getenv('dhanTOTPtoken'),
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")
