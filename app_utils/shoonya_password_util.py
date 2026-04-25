import hashlib
import json
import os
import time
from typing import Callable
import requests

DEFAULT_BASE_URL = os.environ.get("SHOONYA_BASE_URL", "https://api.shoonya.com/NorenWClientTP")

def _sha256(x: str) -> str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()

def _post(base_url: str, route: str, jdata: dict, jkey: str | None = None, timeout: int = 30) -> dict:
    url = f"{base_url.rstrip('/')}{route}"
    payload = "jData=" + json.dumps(jdata)
    if jkey:
        payload += f"&jKey={jkey}"
    r = requests.post(url, data=payload, timeout=timeout, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return r.json()
    except Exception:
        return {"stat": "Not_Ok", "emsg": r.text or str(r.status_code)}

def login_with_totp(base_url: str, userid: str, password: str, vendor_code: str, api_secret: str, imei: str, totp_fn: Callable[[], str]) -> dict:
    app_key = _sha256(f"{userid}|{api_secret}")
    jdata = {
        "source": "API",
        "apkversion": "py:1.0.0",
        "uid": userid,
        "pwd": _sha256(password),
        "factor2": totp_fn(),
        "vc": vendor_code,
        "appkey": app_key,
        "imei": imei,
    }
    return _post(base_url, "/QuickAuth", jdata)

def change_password_for_client(
    userid: str,
    old_password: str,
    new_password: str,
    *,
    vendor_code: str,
    api_secret: str,
    totp_fn: Callable[[], str],
    base_url: str = DEFAULT_BASE_URL,
    imei: str = "api-device",
    verify: bool = True,
) -> bool:
    """
    Change Finvasia/Shoonya password.

    Strategy (handles expired passwords):
    1. Try /Changepwd directly with hashed old+new passwords (works even when
       password is expired — no active session required).
    2. If that fails AND old password is NOT expired (i.e. we can still login),
       login first to get a session then retry /Changepwd with the session key.
    3. Optionally verify the new credentials work via login.
    """
    old_hash = _sha256(old_password)

    # ── Attempt 1: direct /Changepwd (no session needed, works for expired passwords) ──
    resp = _post(base_url, "/Changepwd", {
        "uid": userid,
        "oldpwd": old_hash,
        "pwd": new_password,
    })

    if resp.get("stat") == "Ok":
        if not verify:
            return True
        time.sleep(0.5)
        v = login_with_totp(base_url, userid, new_password, vendor_code, api_secret, imei, totp_fn)
        return v.get("stat") == "Ok"

    # ── Attempt 2: login with old password then retry /Changepwd ──
    # (Only possible when password is NOT expired)
    auth = login_with_totp(base_url, userid, old_password, vendor_code, api_secret, imei, totp_fn)
    if auth.get("stat") != "Ok":
        # Cannot login with old password either (expired or wrong) — nothing more we can do
        return False

    jkey = auth.get("susertoken", "")
    resp2 = _post(base_url, "/Changepwd", {
        "uid": userid,
        "oldpwd": old_hash,
        "pwd": new_password,
    }, jkey=jkey)

    if resp2.get("stat") != "Ok":
        return False

    if not verify:
        return True

    time.sleep(0.5)
    v2 = login_with_totp(base_url, userid, new_password, vendor_code, api_secret, imei, totp_fn)
    return v2.get("stat") == "Ok"

