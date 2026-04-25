"""
Finvasia (Shoonya) API-based Login — Pure HTTP, NO Selenium/Browser required.

New flow as of April 1, 2026 (SEBI OAuth mandate):

  1. POST credentials to /NorenWClientAPI/QuickAuth with app_key=vendor_code
     → Returns susertoken (Noren session key) + OAuth code
  2. POST code + checksum to /NorenWClientAPI/GenAcsTok via registered static IP
     → Returns access_token (OAuth Bearer token for compliant order placement)
  3. Use susertoken with NorenRestApiPy set_session() for all API calls

Key constants discovered from Shoonya SPA source:
  K = Uint8Array([83,50,97,114,110,46,27,93]) → suffix = 'S3cur3!d'
  appkey = sha256(uid + '|' + 'S3cur3!d')
  apkversion = 'W2_20250926'
  source = 'API', vc = 'NOREN_API'

GenAcsTok MUST come from the client's registered static IP (SEBI requirement).
Uses pycurl (libcurl) for this call because Python requests/urllib3 has TLS
compatibility issues with the Finvasia CloudFront proxy setup.
"""

import hashlib
import json
import re
import time
import uuid
import pyotp

BASE_URL = "https://trade.shoonya.com/NorenWClientAPI"

# Shoonya SPA appkey constants (extracted from OAuthlogin/assets/index-d67dbe40.js)
_K = [83, 50, 97, 114, 110, 46, 27, 93]
_SUFFIX = ''.join(chr(_K[p] + p) for p in range(len(_K)))   # → 'S3cur3!d'
_APK_VERSION = "W2_20250926"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _pycurl_post(url: str, data: str, proxy_url: str | None = None, retries: int = 4) -> dict:
    """
    POST using pycurl (libcurl).  Required because Python requests/urllib3 fails
    HTTPS CONNECT tunnelling to trade.shoonya.com through the registered-IP proxy,
    while libcurl handles it correctly.
    """
    try:
        import pycurl
        from io import BytesIO
    except ImportError:
        raise ImportError("pycurl is required: pip install pycurl")

    for attempt in range(retries):
        buf = BytesIO()
        c = pycurl.Curl()
        try:
            c.setopt(pycurl.URL, url)
            c.setopt(pycurl.POST, 1)
            c.setopt(pycurl.POSTFIELDS, data)
            c.setopt(pycurl.HTTPHEADER, ["Content-Type: application/x-www-form-urlencoded"])
            c.setopt(pycurl.WRITEDATA, buf)
            c.setopt(pycurl.TIMEOUT, 25)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
            if proxy_url:
                m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
                if m:
                    c.setopt(pycurl.PROXY, m.group(3))
                    c.setopt(pycurl.PROXYPORT, int(m.group(4)))
                    c.setopt(pycurl.PROXYUSERPWD, f"{m.group(1)}:{m.group(2)}")
            c.perform()
            http_code = c.getinfo(pycurl.HTTP_CODE)
            text = buf.getvalue().decode()
            if http_code == 200 and text.strip():
                return json.loads(text)
            print(f"  [API] Attempt {attempt+1}/{retries}: HTTP {http_code} — {text[:80]}")
        except Exception as e:
            print(f"  [API] Attempt {attempt+1}/{retries} error: {e}")
        finally:
            try:
                c.close()
            except Exception:
                pass
        time.sleep(4)
    return {}


def generate_finvasia_token(
    vendor_code: str,
    api_secret: str,
    userid: str,
    password: str,
    totp_secret: str,
    proxy_url: str | None = None,
) -> dict:
    """
    Authenticate with Finvasia via pure API calls (no browser/Selenium).

    Parameters
    ----------
    vendor_code : str   e.g. 'FN148473_U'  (Client Id from API Key Generation page)
    api_secret  : str   64-char Secret Code from API Key Generation page
    userid      : str   e.g. 'FN148473'
    password    : str   account password
    totp_secret : str   TOTP secret (base32)
    proxy_url   : str   registered static-IP proxy, e.g.
                        'http://user:pass@9.142.219.210:6374'
                        Required for GenAcsTok (SEBI IP check).

    Returns
    -------
    dict with keys:
        susertoken  — Noren session key (use for set_session())
        access_token — OAuth Bearer token (from GenAcsTok)
        uid          — userid
    """
    # ── Step 1: QuickAuth ──────────────────────────────────────────────────────
    # TOTP is single-use per 30s window. Each retry must use a fresh TOTP code
    # obtained in a new window. Wait for a clean window before each attempt.
    import pycurl as _pc
    from io import BytesIO as _BytesIO
    appkey = _sha256(userid + "|" + _SUFFIX)
    r1 = {}

    print(f"  [API] QuickAuth for {userid}...")
    for _attempt in range(1, 4):
        _remaining = 30 - (time.time() % 30)
        if _remaining < 5:
            print(f"  [API] Waiting {_remaining:.0f}s for fresh TOTP window...")
            time.sleep(_remaining + 1)
        _totp = pyotp.TOTP(totp_secret).now()
        print(f"  [API] TOTP for {userid}: {_totp}")
        _buf = _BytesIO()
        _c = _pc.Curl()
        try:
            _c.setopt(_pc.URL, f"{BASE_URL}/QuickAuth")
            _c.setopt(_pc.POST, 1)
            _c.setopt(_pc.POSTFIELDS, "jData=" + json.dumps({
                "apkversion": _APK_VERSION, "uid": userid,
                "pwd": _sha256(password), "factor2": _totp,
                "appkey": appkey, "imei": str(uuid.uuid4()),
                "addldivinf": "Mozilla/5.0 (X11; Linux x86_64)",
                "source": "API", "vc": "NOREN_API", "app_key": vendor_code,
            }))
            _c.setopt(_pc.HTTPHEADER, ["Content-Type: application/x-www-form-urlencoded"])
            _c.setopt(_pc.WRITEDATA, _buf)
            _c.setopt(_pc.TIMEOUT, 25)
            _c.setopt(_pc.SSL_VERIFYPEER, 0)
            if proxy_url:
                _m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
                if _m:
                    _c.setopt(_pc.PROXY, _m.group(3))
                    _c.setopt(_pc.PROXYPORT, int(_m.group(4)))
                    _c.setopt(_pc.PROXYUSERPWD, f"{_m.group(1)}:{_m.group(2)}")
            _c.perform()
            _http = _c.getinfo(_pc.HTTP_CODE)
        finally:
            try: _c.close()
            except Exception: pass
        _body = _buf.getvalue().decode(errors='replace')
        if _http == 200 and _body.strip():
            try: r1 = json.loads(_body)
            except Exception: pass
        if r1.get("stat") == "Ok":
            break
        _emsg = r1.get('emsg', '')
        print(f"  [API] QuickAuth attempt {_attempt}/3 HTTP {_http}: {_body[:80]}")
        # Terminal errors — retrying wastes 31s per attempt; fail immediately.
        _terminal = ('user blocked', 'blocked due to', 'multiple wrong',
                     'invalid vendor', 'algo_chk', 'invalid app_key')
        if any(t in _emsg.lower() for t in _terminal):
            break
        if _attempt < 3:
            time.sleep(31)  # wait for next TOTP window

    if r1.get("stat") != "Ok":
        raise Exception(f"QuickAuth failed for {userid}: {r1.get('emsg', r1)}")

    susertoken = r1["susertoken"]
    code       = r1["code"]       # OAuth authorization code
    print(f"  [API] QuickAuth OK for {userid}")

    # ── Step 2: GenAcsTok ─────────────────────────────────────────────────────
    # MUST originate from the client's registered static IP (SEBI mandate).
    # Checksum = SHA-256(vendor_code + api_secret + code)
    checksum = _sha256(vendor_code + api_secret + code)

    print(f"  [API] GenAcsTok for {userid} (via registered IP proxy)...")
    r2 = _pycurl_post(
        f"{BASE_URL}/GenAcsTok",
        "jData=" + json.dumps({"code": code, "checksum": checksum}),
        proxy_url=proxy_url,
    )

    if not r2 or ("access_token" not in r2 and "USERID" not in r2):
        emsg = r2.get("emsg", r2) if r2 else "empty response"
        # Fall back to susertoken from QuickAuth if GenAcsTok fails
        print(f"  [API] GenAcsTok failed ({emsg}), falling back to susertoken")
        access_token = susertoken
    else:
        access_token = r2.get("access_token") or susertoken
        print(f"  [API] Login complete for {userid}")

    return {
        "susertoken":  susertoken,
        "access_token": access_token,
        "uid":         userid,
    }


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    # Quick test — reads credentials from DB
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    try:
        from app import app
        from models import db, Broker
        with app.app_context():
            b = Broker.query.filter_by(user_id_broker="FN148473").first()
            result = generate_finvasia_token(
                vendor_code=b.vendor_code,
                api_secret=b.api_secret,
                userid=b.user_id_broker,
                password=b.password,
                totp_secret=b.totp_secret,
                proxy_url=b.proxy_ip,
            )
            print("SUCCESS:", {k: v[:20]+"..." for k, v in result.items() if v})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("FAILED:", e)