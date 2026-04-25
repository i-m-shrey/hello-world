"""
Groww Token Generation - Using API Key and Secret

Note: GrowwAPI.get_access_token() returns the token string directly.
Approval-type keys require daily approval at https://groww.in/trade-api/api-keys
"""
from growwapi import GrowwAPI


def generate_groww_token(api_key, api_secret=None):
    """
    Generate Groww access token using API Key and optional Secret.

    Args:
        api_key:    Groww API Key from Groww Cloud API Keys Page
        api_secret: Groww API Secret (required for approval-type keys)

    Returns:
        str: access_token string

    Flow:
    1. Call GrowwAPI.get_access_token() with API key (+ secret if provided)
    2. Returns the access token string directly (not an object)
    """
    print(f"Generating Groww access token...")

    try:
        print(f"[1/2] Requesting access token from Groww...")

        if api_secret:
            access_token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
        else:
            access_token = GrowwAPI.get_access_token(api_key=api_key)

        if not access_token or not isinstance(access_token, str):
            raise Exception(f"Failed to retrieve access token: got {access_token!r}")

        print(f"[2/2] Token generated successfully: {access_token[:30]}...")
        return access_token

    except Exception as e:
        raise Exception(f"Groww token generation failed: {e}")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    try:
        token = generate_groww_token(
            api_key=os.getenv('GROWW_API_KEY'),
            api_secret=os.getenv('GROWW_API_SECRET'),
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")
