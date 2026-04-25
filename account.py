import os
import sys
import pyotp
from NorenRestApiPy.NorenApi import NorenApi

# Ensure appsrc/ is on the path so strategy_runner package can be imported
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from strategy_runner.finvasia_oauth import generate_finvasia_token


class Account:
    def __init__(self, user_id, password, totp_secret, vendor_code, api_secret,
                 imei=None, proxy_url=None, is_master=False, multiplier=1, copy=True):
        self.user_id = user_id
        self.password = password
        self.totp_secret = totp_secret
        self.vendor_code = vendor_code
        self.api_secret = api_secret
        self.imei = imei        # kept for backward-compat; not used in new OAuth flow
        self.proxy_url = proxy_url
        self.is_master = is_master
        self.multiplier = multiplier
        self.copy = copy
        self.session = None

    def generate_totp(self):
        otp = pyotp.TOTP(self.totp_secret).now()
        print(f"[DEBUG] TOTP for {self.user_id}: {otp}")
        return otp

    def login(self):
        # Resolve proxy: explicit > env vars set by client_proxy_context
        # pycurl does NOT inherit HTTP_PROXY env vars — must be passed explicitly.
        proxy = (
            self.proxy_url
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
        )

        result = generate_finvasia_token(
            vendor_code=self.vendor_code,
            api_secret=self.api_secret,
            userid=self.user_id,
            password=self.password,
            totp_secret=self.totp_secret,
            proxy_url=proxy,
        )

        self.session = NorenApi(
            host="https://trade.shoonya.com/NorenWClientAPI/",
            websocket="wss://trade.shoonya.com/NorenWSTP/",
        )
        self.session.set_session(
            userid=self.user_id,
            password=self.password,
            usertoken=result["susertoken"],
        )
        self.susertoken = result["susertoken"]
        self.access_token = result["access_token"]
        print(f"Login successful for {self.user_id}")
