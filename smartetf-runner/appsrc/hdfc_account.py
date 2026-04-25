
import requests

class HDFCAccount:
    def __init__(self, username, password, api_key):
        self.username = username
        self.password = password
        self.api_key = api_key
        self.access_token = None
        self.base_url = "https://api.hdfcsec.com/v1"  # Update with actual endpoint

    def login(self):
        print(f"🔐 Logging in HDFC user: {self.username}")
        # Placeholder login flow
        otp = input("🔢 Enter OTP for HDFC user {}: ".format(self.username)).strip()

        response = requests.post(f"{self.base_url}/auth/login", json={
            "username": self.username,
            "password": self.password,
            "otp": otp,
            "api_key": self.api_key
        })

        if response.status_code != 200:
            print("❌ Login failed:", response.text)
            return

        data = response.json()
        self.access_token = data.get("access_token")

        if self.access_token:
            print(f"✅ HDFC login successful for {self.username}")
        else:
            print("❌ Login failed: No access token returned.")

    def place_order(self, symbol, quantity, order_type="BUY"):
        if not self.access_token:
            print("⚠️ Cannot place order: Not logged in.")
            return

        print(f"📦 Placing HDFC order: {symbol} × {quantity}")
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        payload = {
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "exchange": "NSE",
            "price_type": "MKT"
        }

        response = requests.post(f"{self.base_url}/orders", json=payload, headers=headers)
        if response.status_code == 200:
            print(f"✅ Order placed for {symbol}")
        else:
            print(f"❌ Order failed for {symbol}: {response.text}")
