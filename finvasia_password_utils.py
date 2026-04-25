"""
finvasia_password_utils.py
==========================
Single source of truth for Finvasia password management.
Imported by: morning_health_check.py, etf_automated.py, change_passwords.py

Flow (rotate_finvasia_password):
  1. Load history → forbidden set → generate new password (avoids last 3)
  2. DEBUG prompt — show history / old / new, ask y/n
  3. Pre-save backup CSV (before ANY API call — random suffix cannot be regenerated)
  4. POST /Changepwd
  5. If OK  → update DB immediately + append to password_history.csv
     If Not_Ok → fallback: try login with new pw (maybe already active)
  6. Re-login fresh session + verify balance
  7. If balance verified   → notify client (branded email)
     If balance unverified → email admin alert with old/new pw + error detail
                           → client still notified (password WAS changed)
"""

import os
import sys
import csv
import re
import random
import logging
import time
from datetime import datetime, timezone, timedelta

# ── Path setup ───────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_APPSRC = os.path.join(_HERE, '..')
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(_APPSRC))

from app import app
from models import db, User, Broker
from proxy_utils import client_proxy_context, get_client_proxy
from app_utils.shoonya_password_util import change_password_for_client
from finvasia_broker_api import get_available_funds
import finvasia_broker_api as _fba
from email_notifications import send_admin_alert_email, send_finvasia_password_reset_email

# =============================================================================
# CONSTANTS  (all callers read these)
# =============================================================================

OUTPUT_FOLDER  = os.path.join(_HERE, 'passwords')
HISTORY_FILE   = os.path.join(OUTPUT_FOLDER, 'password_history.csv')
HISTORY_FIELDS = [
    'timestamp', 'customer_id', 'user_id_broker', 'full_name',
    'pwd_current', 'pwd_previous', 'pwd_2_ago', 'changed', 'error',
]


# =============================================================================
# HISTORY HELPERS
# =============================================================================

def load_password_history(broker_id: str) -> list:
    """Return [current, previous, 2_ago] for broker_id (empty strings if none)."""
    if not os.path.exists(HISTORY_FILE):
        return ['', '', '']
    try:
        with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as f:
            rows = [r for r in csv.DictReader(f) if r.get('user_id_broker') == broker_id]
        if not rows:
            return ['', '', '']
        rows.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
        latest = rows[0]
        return [
            latest.get('pwd_current', ''),
            latest.get('pwd_previous', ''),
            latest.get('pwd_2_ago', ''),
        ]
    except Exception as e:
        logging.warning(f'[pw_utils] History load failed for {broker_id}: {e}')
        return ['', '', '']


def append_password_history(record: dict):
    """Append one rotation record to the rolling history CSV."""
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction='ignore')
        if not exists:
            w.writeheader()
        w.writerow(record)


# =============================================================================
# PASSWORD GENERATION
# =============================================================================

def generate_password(full_name: str, forbidden: set = None) -> str | None:
    """
    Generate FirstName@XXX (XXX = random 100-999), avoiding all passwords in
    forbidden (the last 3 used).  Tries up to 100 combinations; on exhaustion
    uses a 4-digit suffix as final fallback.
    """
    forbidden = forbidden or set()
    first   = (full_name or '').split()[0]
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    for _ in range(100):
        candidate = f"{base}@{random.randint(100, 999)}"
        if candidate not in forbidden:
            return candidate
    return f"{base}@{random.randint(1000, 9999)}"


# =============================================================================
# CORE ROTATION  (single function used by all callers)
# =============================================================================

def rotate_finvasia_password(
    client: dict,
    error_message: str = '',
    notify_client: bool = True,
    debug: bool = False,
) -> dict:
    """
    Unified Finvasia password rotation.

    Args:
        client        – Client dict with keys: user_id_broker, password,
                        totp_secret, vendor_code, api_secret, imei,
                        broker_id, customer_id, [email], [full_name]
        error_message – The error that triggered this rotation (logged only)
        notify_client – Send branded email to client on successful change
        debug         – Print old/new/history and prompt y/n before changing

    Returns dict with keys:
        success, changed, verified, balance, old_password, new_password,
        error, verify_warning, updated_client, customer_id, broker_id,
        user_id_broker
    """
    import pyotp

    broker_id      = client.get('broker_id')
    customer_id    = client.get('customer_id')
    user_id_broker = client.get('user_id_broker')
    old_password   = client.get('password')

    result = {
        'customer_id':    customer_id,
        'broker_id':      broker_id,
        'user_id_broker': user_id_broker,
        'old_password':   old_password,
        'new_password':   None,
        'success':        False,
        'changed':        False,
        'verified':       False,
        'balance':        None,
        'error':          None,
        'verify_warning': None,
        'updated_client': None,
    }

    # ── Resolve full_name ────────────────────────────────────────────────────
    full_name = client.get('full_name') or ''
    if not full_name:
        try:
            with app.app_context():
                u = User.query.filter_by(customer_id=customer_id).first()
                if u:
                    full_name = u.full_name or ''
        except Exception:
            pass
    if not full_name:
        full_name = client.get('username') or ''

    # ── Step 1: History → forbidden set → new password ───────────────────────
    hist = load_password_history(user_id_broker)
    pwd_current, pwd_previous, pwd_2_ago = hist[0], hist[1], hist[2]

    # If DB password differs from latest history entry, treat DB as current
    if old_password and old_password != pwd_current:
        pwd_2_ago    = pwd_previous
        pwd_previous = pwd_current
        pwd_current  = old_password

    forbidden    = {p for p in [pwd_current, pwd_previous, pwd_2_ago] if p}
    new_password = generate_password(full_name, forbidden)
    history_chain = {
        'pwd_current':  pwd_current,
        'pwd_previous': pwd_previous,
        'pwd_2_ago':    pwd_2_ago,
    }
    result['new_password'] = new_password

    if not new_password:
        result['error'] = 'password_policy_failed'
        logging.error(f'[pw_utils] {user_id_broker}: cannot generate policy password')
        return result

    # ── Step 2: DEBUG prompt ─────────────────────────────────────────────────
    if debug:
        print(f'\n[DEBUG] Password rotation → {customer_id} / {user_id_broker}')
        print(f'  History  (2ago → prev → current): '
              f'{pwd_2_ago or "-"} → {pwd_previous or "-"} → {pwd_current or "-"}')
        print(f'  Old password : {old_password}')
        print(f'  New password : {new_password}')
        ans = input('  Proceed with password change? [y/n]: ').strip().lower()
        if ans != 'y':
            print(f'  ⏭️  Skipped by user (DEBUG)')
            result['error'] = 'skipped_in_debug_mode'
            return result

    # ── Step 3: Pre-save backup CSV (before ANY API call) ────────────────────
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        _ts   = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        _path = os.path.join(OUTPUT_FOLDER, f'pwd_backup_{customer_id}_{_ts}.csv')
        with open(_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['customer_id', 'user_id_broker', 'old_password', 'new_password', 'timestamp'])
            w.writerow([customer_id, user_id_broker, old_password, new_password, _ts])
        print(f'  💾 Backup CSV saved: {_path}')
    except Exception as bak_err:
        print(f'  ⚠️  Backup CSV write failed: {bak_err} — proceeding anyway')

    # ── TOTP helper ──────────────────────────────────────────────────────────
    totp_secret = client.get('totp_secret')
    def _totp():
        tok = pyotp.TOTP(totp_secret).now() if totp_secret else ''
        print(f'  [TOTP] {user_id_broker}: {tok}')
        return tok

    proxy = get_client_proxy(client)

    # ── Step 4: POST /Changepwd ──────────────────────────────────────────────
    print(f'  🔑 Calling /Changepwd for {user_id_broker}...')
    change_ok = False   # True = changed | False = Not_Ok | None = exception
    try:
        with client_proxy_context(proxy):
            change_ok = change_password_for_client(
                userid       = user_id_broker,
                old_password = old_password,
                new_password = new_password,
                vendor_code  = client.get('vendor_code') or '',
                api_secret   = client.get('api_secret')  or '',
                imei         = client.get('imei') or 'api-device',
                totp_fn      = _totp,
                verify       = False,   # we verify ourselves below
            )
    except Exception as chg_exc:
        print(f'  ⚠️  /Changepwd raised: {chg_exc}')
        result['error'] = str(chg_exc)
        change_ok = None  # unknown — check via fallback login

    # ── Step 5: Handle Not_Ok / exception → fallback login ───────────────────
    if change_ok is False:
        print(f'  ❌ /Changepwd returned Not_Ok — trying fallback login with new pw...')
        _fb_ok, _fb_bal, _fb_err = _verify_balance(client, new_password, proxy, attempts=1)
        if _fb_ok:
            print(f'  ✅ Fallback: new password already active (balance ₹{_fb_bal})')
            change_ok = True
            result.update(changed=True, verified=True, balance=_fb_bal)
        else:
            result['error'] = 'change_or_verify_failed'
            print(f'  ❌ Fallback also failed for {user_id_broker}: {_fb_err}')
            return result

    if change_ok is None:
        print(f'  🔄 Exception path: testing new password via login...')
        _fb_ok, _fb_bal, _fb_err = _verify_balance(client, new_password, proxy, attempts=1)
        if _fb_ok:
            print(f'  ✅ New password already active. Balance ₹{_fb_bal}')
            change_ok = True
            result.update(changed=True, verified=True, balance=_fb_bal)
        else:
            result['error'] = f'changepwd exception + fallback failed: {_fb_err}'
            print(f'  ❌ Both paths failed for {user_id_broker}')
            return result

    # ── Step 6: /Changepwd OK (or fallback confirmed) ────────────────────────
    if not result['changed']:
        result['changed'] = True
        print(f'  ✅ /Changepwd OK — password changed at broker.')

    # DB save immediately — must not lose new password even if verify fails
    _save_to_db(broker_id, customer_id, user_id_broker, new_password)
    client['password'] = new_password
    result['updated_client'] = dict(client)

    # History append immediately after DB save
    append_password_history({
        'timestamp':      datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'customer_id':    customer_id,
        'user_id_broker': user_id_broker,
        'full_name':      full_name,
        'pwd_current':    new_password,
        'pwd_previous':   history_chain['pwd_current'],
        'pwd_2_ago':      history_chain['pwd_previous'],
        'changed':        True,
        'error':          '',
    })

    # ── Step 7: Re-login + balance verify ────────────────────────────────────
    if not result['verified']:   # skip if fallback already verified
        # Wait for a FULL fresh TOTP window (30s cycle) before re-login.
        # GenAcsTok rejects repeat calls using the same TOTP code within
        # one 30-second window — this caused INVALID_IP on rapid retries.
        # 32s guarantees the TOTP rotates to a new code before we try.
        import pyotp as _pyotp
        _secret = client.get('totp_secret')
        _cur_totp = _pyotp.TOTP(_secret).now() if _secret else ''
        _remaining = 30 - (time.time() % 30)
        _wait = max(_remaining + 2, 2)   # always at least 2s into new window
        print(f'  ⏳ Waiting {_wait:.0f}s for fresh TOTP window before re-login '
              f'(current TOTP: {_cur_totp}, {_remaining:.0f}s left in window)...')
        time.sleep(_wait)
        verified, balance, verify_error = _verify_balance(client, new_password, proxy)
        result['verified']       = verified
        result['balance']        = balance
        result['verify_warning'] = verify_error if not verified else None

        if verified:
            print(f'  ✅ Balance verified: ₹{balance}')
        else:
            print(f'  ⚠️  Balance verify failed: {verify_error}')
            # Email admin — password changed but verify failed
            _admin_alert_verify_failed(
                user_id_broker = user_id_broker,
                customer_id    = customer_id,
                full_name      = full_name,
                old_password   = old_password,
                new_password   = new_password,
                verify_error   = verify_error or 'unknown',
            )

    result['success'] = True   # password WAS changed and saved

    # ── Step 8: Notify client ────────────────────────────────────────────────
    if notify_client:
        _email, _sent = _notify_client(client, full_name, customer_id, new_password)
        result['client_email']      = _email
        result['client_email_sent'] = _sent
    else:
        result['client_email']      = None
        result['client_email_sent'] = None

    return result


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _verify_balance(client: dict, new_password: str, proxy: str, attempts: int = 3):
    """
    Clear session cache, re-login with new_password via proxy, fetch Limits balance.

    Uses client_proxy_context to match the same login path as etf_automated
    (env vars + explicit proxy_ip together ensure pycurl routes correctly).

    Between retry attempts waits a full TOTP window (31s) so each attempt
    uses a fresh TOTP code — GenAcsTok rejects same-window TOTP reuse.

    Returns (verified: bool, balance: float|None, error: str|None).
    """
    uid        = client.get('user_id_broker')
    last_error = None

    for attempt in range(attempts):
        try:
            _fba._clear_session({'user_id_broker': uid})
        except Exception:
            pass
        try:
            vc = {
                'user_id_broker': uid,
                'password':       new_password,
                'totp_secret':    client.get('totp_secret'),
                'vendor_code':    client.get('vendor_code'),
                'api_secret':     client.get('api_secret'),
                'imei':           client.get('imei'),
                'proxy_ip':       proxy,
            }
            # Wrap in client_proxy_context so env vars are set too.
            # etf_automated always logs in within this context — matching
            # that exact path is what makes GenAcsTok succeed.
            with client_proxy_context(proxy):
                balance = get_available_funds(vc)
            return True, balance, None
        except Exception as e:
            last_error = str(e)
            logging.warning(
                f'[pw_utils] Balance verify attempt {attempt+1}/{attempts} '
                f'for {uid}: {last_error}'
            )
            if attempt < attempts - 1:
                # Wait a full TOTP window so the next attempt gets a fresh
                # TOTP code — prevents GenAcsTok INVALID_IP on same-window reuse.
                print(f'  ⏳ Waiting 31s for fresh TOTP window before retry {attempt+2}/{attempts}...')
                time.sleep(31)

    return False, None, last_error


def _save_to_db(broker_id, customer_id, user_id_broker, new_password):
    """Persist new password in DB (by broker_id, fallback to user_id_broker)."""
    try:
        with app.app_context():
            broker = db.session.get(Broker, broker_id) if broker_id else None
            if not broker:
                broker = Broker.query.filter_by(user_id_broker=user_id_broker).first()
            if broker:
                broker.password      = new_password
                broker.last_updated  = datetime.utcnow()
                db.session.commit()
                print(f'  💾 DB updated — new password saved for {user_id_broker}')
            else:
                print(f'  ⚠️  DB row not found for {user_id_broker} — password NOT saved!')
    except Exception as db_err:
        print(f'  ⚠️  DB save failed for {customer_id}: {db_err}')


def _notify_client(client: dict, full_name: str, customer_id: str, new_password: str) -> tuple:
    """
    Send branded password-reset email to the client.
    Returns (client_email: str|None, sent_ok: bool).
    """
    client_email = client.get('email')
    if not client_email:
        try:
            with app.app_context():
                u = User.query.filter_by(customer_id=customer_id).first()
                if u:
                    client_email = u.email
        except Exception:
            pass
    if client_email:
        try:
            send_finvasia_password_reset_email(client_email, full_name, customer_id, new_password)
            print(f'  ✅ Client email sent → {client_email}')
            return client_email, True
        except Exception as e:
            print(f'  ❌ Client email failed ({client_email}): {e}')
            return client_email, False
    else:
        print(f'  ⚠️  No email found for {customer_id} — client not notified')
        return None, False


def _admin_alert_verify_failed(
    user_id_broker, customer_id, full_name, old_password, new_password, verify_error
):
    """Email admin when password was changed but balance verification failed."""
    IST = timezone(timedelta(hours=5, minutes=30))
    ts  = datetime.now(IST).strftime('%d %B %Y %I:%M %p IST')
    subject = f'⚠️ Finvasia Password Changed — Balance Verify Failed ({user_id_broker})'
    message = (
        f'Finvasia Password Changed but Balance Verification Failed\n'
        f'{"=" * 62}\n'
        f'Customer ID  : {customer_id}\n'
        f'Broker ID    : {user_id_broker}\n'
        f'Full Name    : {full_name}\n'
        f'Old Password : {old_password}\n'
        f'New Password : {new_password}\n'
        f'Timestamp    : {ts}\n'
        f'{"=" * 62}\n'
        f'Verify Error : {verify_error}\n\n'
        f'Notes:\n'
        f'  • Password WAS successfully changed at the broker.\n'
        f'  • DB and history CSV have been updated with the new password.\n'
        f'  • Balance check failed — likely a GenAcsTok / registered-IP issue.\n'
        f'  • Client has been notified of the new password.\n'
        f'  • Please verify the client can trade, or check GenAcsTok IP registration.\n'
    )
    try:
        send_admin_alert_email(subject, message)
        print(f'  📧 Admin alert sent: balance verify failed for {user_id_broker}')
    except Exception as e:
        print(f'  ❌ Admin alert send failed: {e}')
