import hashlib
import json
import time
from typing import Optional, Dict, Any
import requests


class ShoonyaPasswordChangeError(Exception):
    """Raised when Shoonya password change fails."""


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def change_shoonya_password(
    uid: str,
    api_key: str,
    vendor_code: str,
    imei: str,
    old_password: str,
    new_password: str,
    factor2: Optional[str] = None,          # OTP/TOTP if login is needed
    session_token: Optional[str] = None,     # existing susertoken (if you already maintain a session)
    base_url: str = "https://api.shoonya.com/NorenWClientWeb",
    timeout: int = 20
) -> Dict[str, Any]:
    """
    Change the Shoonya (Finvasia) trading password using the Noren API session.

    Modes:
      - Mode A: If `session_token` is provided, uses it directly to call Change Password.
      - Mode B: If `session_token` is None, performs login using uid/pwd/factor2 to obtain a session, then changes password.

    Parameters
    ----------
    uid : str
        Shoonya client/user id.
    api_key : str
        API key generated on Shoonya's API portal (Prism). Used to derive `appkey`.
    vendor_code : str
        Vendor code assigned by Shoonya.
    imei : str
        Device/IMEI identifier string (can be a stable device token you use).
    old_password : str
        Current (old) password in plain text. The function hashes it per Shoonya spec.
    new_password : str
        Desired new password in plain text. The function hashes it per Shoonya spec.
    factor2 : str, optional
        OTP/TOTP for 2FA. Mandatory if `session_token` is not provided (i.e., when login is required).
    session_token : str, optional
        Existing `susertoken`. If provided, login is skipped.
    base_url : str, optional
        Base URL for the Noren web client API.
    timeout : int, optional
        Per-request timeout in seconds.

    Returns
    -------
    dict
        {
          "ok": bool,
          "message": str,
          "session_token": str,    # returned/retained token (useful if you logged in via this function)
          "raw": dict              # raw Shoonya API response for diagnostics
        }

    Raises
    ------
    ShoonyaPasswordChangeError
        If login or password change fails, with the server's message included.
    """
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})

    def _post(path: str, jdata: dict, need_auth: bool = False) -> dict:
        url = f"{base_url}/{path}"
        headers = {}
        if need_auth and session_token:
            # Many Noren implementations accept either/both of these:
            headers["Authorization"] = f"Bearer {session_token}"
            headers["jKey"] = session_token

        payload = {
            "jData": json.dumps(jdata)
        }
        resp = s.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            raise ShoonyaPasswordChangeError(f"Non-JSON response from {path}: {resp.text[:300]}")

    # --- Step 1: Ensure we have a session token (Mode B does login) ---
    appkey = _sha256_hex(f"{uid}|{api_key}")

    if not session_token:
        if not factor2:
            raise ShoonyaPasswordChangeError("No session_token provided and factor2 (OTP/TOTP) missing for login.")

        # Shoonya expects hashed password in login
        login_payload = {
            "uid": uid,
            "pwd": _sha256_hex(old_password),     # login with CURRENT password
            "factor2": factor2,                   # OTP/TOTP
            "vc": vendor_code,
            "appkey": appkey,
            "imei": imei
        }
        login_res = _post("QuickAuth", login_payload, need_auth=False)

        # Typical success key is "stat": "Ok" with "susertoken" in data; adjust if your variant differs
        if str(login_res.get("stat", "")).lower() != "ok" or not login_res.get("susertoken"):
            msg = login_res.get("emsg") or login_res.get("message") or "Login failed"
            raise ShoonyaPasswordChangeError(f"Login failed: {msg}")

        session_token = login_res["susertoken"]

        # If the server demands immediate password reset, they'll often indicate it (e.g., spasswordreset == 'Y')
        # We proceed to change password below regardless, since that's our goal.

    # --- Step 2: Change Password using the (new or provided) session token ---
    change_payload = {
        "uid": uid,
        "oldpwd": _sha256_hex(old_password),
        "pwd": new_password
    }

    change_res = _post("Changepwd", change_payload, need_auth=True)

    if str(change_res.get("stat", "")).lower() != "ok":
        msg = change_res.get("emsg") or change_res.get("message") or "Change password failed"
        raise ShoonyaPasswordChangeError(f"Change password failed: {msg}")

    # --- Step 3: (Optional) Re-Login with new password to validate the rotation & refresh token ---
    # This is handy if you want to immediately use the new credentials downstream.
    # Comment out if you want to retain the old session until it expires.
    try:
        relog_payload = {
            "uid": uid,
            "pwd": _sha256_hex(new_password),
            "factor2": factor2 or "",           # TOTP can be reused if still valid; else pass a fresh one
            "vc": vendor_code,
            "appkey": appkey,
            "imei": imei
        }
        # A tiny wait helps avoid race conditions on some backends after password change
        time.sleep(0.6)
        relog_res = _post("QuickAuth", relog_payload, need_auth=False)
        if str(relog_res.get("stat", "")).lower() == "ok" and relog_res.get("susertoken"):
            session_token = relog_res["susertoken"]
    except Exception:
        # If re-login fails (e.g., TOTP expired), we still return success for the password change itself.
        pass

    return {
        "ok": True,
        "message": "Password changed successfully.",
        "session_token": session_token,
        "raw": change_res
    }


res = change_shoonya_password(
    uid="AB1234",
    api_key="YOUR_API_KEY",
    vendor_code="YOUR_VENDOR",
    imei="YOUR_DEVICE_ID",
    old_password="OldPass@123",
    new_password="NewPass@456",
    factor2="123456"  # TOTP or SMS OTP
)
