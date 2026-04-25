"""
Zerodha Kite Connect Token Generation - HTTP-based (no Selenium)
"""
import time
import requests
import pyotp
import re
import hashlib


def generate_zerodha_token(api_key, api_secret, user_id, password, totp_secret):
    """
    Generate Zerodha access token using pure HTTP requests

    Flow:
    1. POST credentials to login API
    2. POST TOTP to 2FA API
    3. Extract request_token from redirect
    4. Generate checksum and exchange for access_token
    """

    def generate_checksum(api_key, request_token, api_secret):
        """Generate SHA256 checksum for token exchange"""
        data = f"{api_key}{request_token}{api_secret}"
        return hashlib.sha256(data.encode()).hexdigest()

    def http_authentication():
        """Step 1-3: HTTP-based login and extract request_token"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://kite.zerodha.com',
            'Referer': 'https://kite.zerodha.com/'
        })

        try:
            login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
            print(f"[1/5] Initializing session with Zerodha...")

            init_response = session.get(login_url, timeout=15)
            if init_response.status_code != 200:
                raise Exception(f"Failed to initialize session: HTTP {init_response.status_code}")

            print(f"[2/5] Submitting credentials...")
            login_payload = {
                'user_id': user_id,
                'password': password
            }

            login_response = session.post(
                'https://kite.zerodha.com/api/login',
                data=login_payload,
                timeout=15,
                allow_redirects=False
            )

            if login_response.status_code not in [200, 302]:
                raise Exception(f"Login failed: HTTP {login_response.status_code} - {login_response.text}")

            try:
                login_data = login_response.json()
            except:
                raise Exception(f"Login response not JSON: {login_response.text[:200]}")

            if login_data.get('status') != 'success':
                error_msg = login_data.get('message', 'Unknown error')
                raise Exception(f"Login failed: {error_msg}")

            request_id = login_data.get('data', {}).get('request_id')
            if not request_id:
                raise Exception(f"No request_id in login response: {login_data}")

            print(f"[3/5] Generating and submitting TOTP...")
            totp_code = pyotp.TOTP(totp_secret).now()

            twofa_payload = {
                'user_id': user_id,
                'request_id': request_id,
                'twofa_value': totp_code,
                'twofa_type': 'totp',
                'skip_session': ''
            }

            twofa_response = session.post(
                'https://kite.zerodha.com/api/twofa',
                data=twofa_payload,
                timeout=15,
                allow_redirects=False
            )

            if twofa_response.status_code not in [200, 302]:
                raise Exception(f"2FA failed: HTTP {twofa_response.status_code} - {twofa_response.text}")

            try:
                twofa_data = twofa_response.json()
            except:
                raise Exception(f"2FA response not JSON: {twofa_response.text[:200]}")

            if twofa_data.get('status') != 'success':
                error_msg = twofa_data.get('message', 'Unknown error')
                raise Exception(f"2FA failed: {error_msg}")

            print(f"[4/5] Following redirect to capture request_token...")

            redirect_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
            redirect_response = session.get(redirect_url, timeout=15, allow_redirects=True)

            final_url = redirect_response.url
            print(f"[INFO] Final redirect URL: {final_url}")

            match = re.search(r"request_token=([^&]+)", final_url)
            if match:
                request_token = match.group(1)
                print(f"[SUCCESS] Request token extracted: {request_token[:20]}...")
                return request_token

            for redirect in redirect_response.history:
                match = re.search(r"request_token=([^&]+)", redirect.url)
                if match:
                    request_token = match.group(1)
                    print(f"[SUCCESS] Request token extracted from redirect: {request_token[:20]}...")
                    return request_token

            raise Exception(f"Request token not found in redirect URL: {final_url}")

        except requests.exceptions.Timeout:
            raise Exception("HTTP request timed out - check network connection")
        except requests.exceptions.ConnectionError:
            raise Exception("Connection error - check network connectivity")
        except Exception as e:
            raise Exception(f"HTTP authentication failed: {e}")

    def exchange_token(request_token):
        """Step 5: Exchange request_token for access_token"""
        url = "https://api.kite.trade/session/token"

        checksum = generate_checksum(api_key, request_token, api_secret)

        payload = {
            'api_key': api_key,
            'request_token': request_token,
            'checksum': checksum
        }

        response = requests.post(url, data=payload, timeout=20)

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")

        data = response.json()

        if data.get('status') != 'success':
            raise Exception(f"Token exchange unsuccessful: {data}")

        access_token = data.get('data', {}).get('access_token')

        if not access_token:
            raise Exception(f"No access_token in response: {data}")

        return access_token

    print(f"Generating Zerodha access token for {user_id}...")

    request_token = http_authentication()
    access_token = exchange_token(request_token)

    print(f"[5/5] Token generated successfully: {access_token[:30]}...")
    return access_token


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    try:
        token = generate_zerodha_token(
            api_key=os.getenv('ZERODHA_API_KEY'),
            api_secret=os.getenv('ZERODHA_API_SECRET'),
            user_id=os.getenv('ZERODHA_USER_ID'),
            password=os.getenv('ZERODHA_PASSWORD'),
            totp_secret=os.getenv('ZERODHA_TOTP_SECRET')
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")