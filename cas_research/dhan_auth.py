"""Dhan token mint + cache. NEVER run mint during market hours (09:00-15:45 IST)
while the live TradeX runner owns the token — minting invalidates its token.
"""
import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

DHAN_CLIENT_ID = "1102446172"
DHAN_PIN = "211600"
DHAN_TOTP_SECRET = "N6QJKHMQBWBNN3QWTLJ32OGPGXK3KJMC"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dhan_token.txt")
IST = timezone(timedelta(hours=5, minutes=30))


def _token_valid(token: str) -> bool:
    if not token or len(token) <= 20:
        return False
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(int(exp), tz=timezone.utc) > datetime.now(timezone.utc) + timedelta(minutes=10)
    except Exception:
        pass
    return False


def _market_hours_guard():
    now = datetime.now(IST)
    if now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (15, 46):
        raise RuntimeError(
            f"Refusing to mint Dhan token during market hours ({now:%H:%M} IST) — "
            "live runner owns the token. Retry after 15:46 IST."
        )


def mint_token() -> str:
    import pyotp

    _market_hours_guard()
    last_err = None
    for attempt in range(3):
        totp = pyotp.TOTP(DHAN_TOTP_SECRET).now()
        url = (
            "https://auth.dhan.co/app/generateAccessToken"
            f"?dhanClientId={DHAN_CLIENT_ID}&pin={DHAN_PIN}&totp={totp}"
        )
        resp = requests.post(url, timeout=20)
        if resp.status_code != 200:
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            time.sleep(5)
            continue
        data = resp.json()
        if data.get("status") == "error":
            msg = data.get("message", str(data))
            last_err = msg
            if "totp" in msg.lower() and attempt < 2:
                time.sleep(31)
                continue
            raise RuntimeError(f"Dhan token mint failed: {msg}")
        if "accessToken" in data:
            token = data["accessToken"]
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
            print(f"[auth] minted token (expires {data.get('expiryTime', '?')}): {token[:25]}...")
            return token
    raise RuntimeError(f"Dhan token mint failed after 3 attempts: {last_err}")


def get_token(force_mint: bool = False) -> str:
    if not force_mint and os.path.exists(TOKEN_FILE):
        tok = open(TOKEN_FILE).read().strip()
        if _token_valid(tok):
            return tok
    return mint_token()


def headers(token: str | None = None) -> dict:
    return {
        "access-token": token or get_token(),
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


if __name__ == "__main__":
    import sys
    t = get_token(force_mint="--force" in sys.argv)
    print(f"token ok: {t[:25]}... valid={_token_valid(t)}")
