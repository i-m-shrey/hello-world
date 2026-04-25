
import requests

class ICICIAccount:
    def __init__(self, username, password, app_key, secret_key):
        self.username = username
        self.password = password
        self.app_key = app_key
        self.secret_key = secret_key
        self.session_token = None
        self.base_url = "https://api.icicidirect.com/breezeapi"  # Confirm endpoint

    def login(self):
        print(f"🔐 Logging in ICICI user: {self.username}")
        # Placeholder login logic, may need encryption/signature
        response = requests.post(f"{self.base_url}/login", json={
            "username": self.username,
            "password": self.password,
            "app_key": self.app_key,
            "secret_key": self.secret_key
        })

        if response.status_code != 200:
            print("❌ Login failed:", response.text)
            return

        data = response.json()
        self.session_token = data.get("session_token")

        if self.session_token:
            print(f"✅ ICICI login successful for {self.username}")
        else:
            print("❌ Login failed: No session token returned.")

    def place_order(self, symbol, quantity, order_type="BUY"):
        if not self.session_token:
            print("⚠️ Cannot place order: Not logged in.")
            return

        print(f"📦 Placing ICICI order: {symbol} × {quantity}")
        headers = {
            "Authorization": f"Bearer {self.session_token}"
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
