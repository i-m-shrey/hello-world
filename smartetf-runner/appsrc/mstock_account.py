
import requests

class MStockAccount:
    def __init__(self, username, password, api_key):
        self.username = username
        self.password = password
        self.api_key = api_key
        self.access_token = None
        self.base_url = "https://api.mstock.com/v1"  # Update this if needed

    def login(self):
        print(f"🔐 Starting login for MStock user: {self.username}")
        # Step 1: Initiate login (request OTP)
        response = requests.post(f"{self.base_url}/auth/request-otp", json={
            "username": self.username,
            "api_key": self.api_key
        })

        if response.status_code != 200:
            print("❌ Failed to request OTP:", response.text)
            return

        print("📩 OTP sent. Please check SMS or email.")
        otp = input("🔢 Enter OTP for MStock user {}: ".format(self.username)).strip()

        # Step 2: Submit OTP and login
        login_response = requests.post(f"{self.base_url}/auth/verify-otp", json={
            "username": self.username,
            "password": self.password,
            "otp": otp,
            "api_key": self.api_key
        })

        if login_response.status_code != 200:
            print("❌ Login failed:", login_response.text)
            return

        data = login_response.json()
        self.access_token = data.get("access_token")

        if not self.access_token:
            print("❌ Login failed: No access token returned.")
            return

        print("✅ MStock login successful for", self.username)

    def place_order(self, symbol, quantity, order_type="BUY"):
        if not self.access_token:
            print("⚠️ Cannot place order: Not logged in.")
            return

        print(f"📦 Placing MStock order: {symbol} × {quantity}")
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        order_payload = {
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "exchange": "NSE",
            "price_type": "MKT"
        }

        response = requests.post(f"{self.base_url}/orders", json=order_payload, headers=headers)
        if response.status_code == 200:
            print(f"✅ Order placed for {symbol}")
        else:
            print(f"❌ Failed to place order for {symbol}: {response.text}")
