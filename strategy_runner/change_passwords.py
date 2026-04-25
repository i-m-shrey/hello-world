"""
change_passwords.py
===================
Standalone Finvasia password changer for SmartETF clients.

• Tracks last 3 passwords to avoid Finvasia's "cannot reuse last 3 passwords" policy.
• Rolling history CSV (passwords/password_history.csv) — appends every change.
• Timestamped backup CSV per run (passwords/password_changes_YYYYMMDD_HHMMSS.csv).
• Identical policy + change logic as morning_health_check._rotate_finvasia_password().

Run:
    python change_passwords.py
"""

import os
import sys
import csv
import time
import random
import re
import logging
import datetime

# ── Path setup ───────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_APPSRC = os.path.join(_HERE, '..')
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(_APPSRC))

from app import app
from models import db, User, Broker
from client_fetcher import get_active_clients_with_sip
from proxy_utils import client_proxy_context, get_client_proxy
from app_utils.shoonya_password_util import change_password_for_client
from finvasia_broker_api import get_available_funds
import finvasia_broker_api as _fba

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =============================================================================
# CONTROL VARIABLES  (edit these before running)
# =============================================================================

DEBUG = True
# True  → prompt per-client (shows history, generates new pwd, asks y/n)
# False → auto-process all non-blocked clients

BLOCKED_BROKER_IDS: frozenset = frozenset()
# Add user_id_broker to permanently skip. Example: frozenset({'FN148473'})

OUTPUT_FOLDER = os.path.join(_HERE, "passwords")

# =============================================================================
# END OF CONTROL VARIABLES
# =============================================================================

# ── Rolling history file ─────────────────────────────────────────────────────
_HISTORY_FILE = os.path.join(OUTPUT_FOLDER, "password_history.csv")
_HISTORY_FIELDS = ['timestamp', 'customer_id', 'user_id_broker', 'full_name',
                   'pwd_current', 'pwd_previous', 'pwd_2_ago', 'changed', 'error']


def _load_last_passwords(broker_id: str) -> list:
    """Load last known passwords for broker_id from history. Returns [current, prev, 2_ago]."""
    if not os.path.exists(_HISTORY_FILE):
        return ['', '', '']
    try:
        with open(_HISTORY_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r.get('user_id_broker') == broker_id]
        if not rows:
            return ['', '', '']
        # Get most recent by timestamp
        rows.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
        latest = rows[0]
        return [
            latest.get('pwd_current', ''),
            latest.get('pwd_previous', ''),
            latest.get('pwd_2_ago', '')
        ]
    except Exception as e:
        logging.warning(f"History load failed for {broker_id}: {e}")
        return ['', '', '']


def _append_history(record: dict):
    """Append one change to rolling history CSV."""
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    exists = os.path.exists(_HISTORY_FILE)
    with open(_HISTORY_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=_HISTORY_FIELDS, extrasaction='ignore')
        if not exists:
            w.writeheader()
        w.writerow(record)


def _password_policy(full_name: str, uid: str, forbidden: set) -> str | None:
    """
    Generate random policy password FirstName@XXX, avoiding last 3 passwords.
    forbidden = set of last 3 passwords to avoid collision with Finvasia policy.
    """
    first = (full_name or '').split()[0]
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    # Try up to 100 times to avoid collision
    for _ in range(100):
        suffix = str(random.randint(100, 999))
        candidate = f"{base}@{suffix}"
        if candidate not in forbidden:
            return candidate
    # Fallback: add extra digit if all 900 combos exhausted
    return f"{base}@{random.randint(1000, 9999)}"


def _save_run_csv(records: list, ts: str) -> str:
    """Per-run backup CSV (replaced each run) with full details."""
    fields = ['customer_id', 'user_id_broker', 'full_name', 'pwd_current',
              'pwd_previous', 'pwd_2_ago', 'new_password_generated',
              'changed', 'verified', 'balance', 'error', 'verify_warning', 'timestamp']
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    path = os.path.join(OUTPUT_FOLDER, f"password_changes_{ts}.csv")
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(records)
    return path


def _do_change(client: dict, old_password: str, new_password: str) -> dict:
    """
    Core password change logic (identical to morning_health_check).
    verify=False prevents TOTP reuse. DB save is caller's responsibility.
    """
    import pyotp

    result = {
        'changed': False, 'verified': False, 'balance': None,
        'error': None, 'verify_warning': None, 'success': False,
    }

    proxy = get_client_proxy(client)

    # Shortcut: old == new (policy already set)
    if old_password == new_password:
        try:
            _fba._clear_session(client)
            vc = dict(client)
            vc['password'] = new_password
            vc['proxy_ip'] = proxy
            result['balance'] = get_available_funds(vc)
            result.update({'changed': True, 'verified': True, 'success': True})
            print(f"  ✅ Balance confirmed: ₹{result['balance']}")
        except Exception as e:
            result.update({'error': str(e), 'changed': True, 'success': True,
                          'verify_warning': str(e)})
            print(f"  ⚠️ Verify failed (already correct): {e}")
        return result

    # Step 1: /Changepwd (verify=False)
    totp_secret = client.get('totp_secret')
    def _totp():
        tok = pyotp.TOTP(totp_secret).now() if totp_secret else ''
        print(f"    [TOTP] {client.get('user_id_broker')}: {tok}")
        return tok

    change_success = False
    try:
        with client_proxy_context(proxy):
            change_success = change_password_for_client(
                userid=client['user_id_broker'],
                old_password=old_password,
                new_password=new_password,
                vendor_code=client.get('vendor_code') or '',
                api_secret=client.get('api_secret') or '',
                imei=client.get('imei') or 'api-device',
                totp_fn=_totp,
                verify=False,
            )
    except Exception as change_exc:
        print(f"  ⚠️ /Changepwd raised: {change_exc}")
        # Fallback: check if policy already active
        try:
            _fba._clear_session(client)
            vc = dict(client)
            vc['password'] = new_password
            vc['proxy_ip'] = proxy
            result['balance'] = get_available_funds(vc)
            result.update({'changed': True, 'verified': True, 'success': True})
            print(f"  ✅ Policy already active. Balance: ₹{result['balance']}")
        except Exception as fb_exc:
            result['error'] = f"change raised: {change_exc} | fallback: {fb_exc}"
            print(f"  ❌ Both change and fallback failed.")
        return result

    if not change_success:
        print(f"  ❌ /Changepwd Not_Ok — checking if policy already active...")
        try:
            _fba._clear_session(client)
            vc = dict(client)
            vc['password'] = new_password
            vc['proxy_ip'] = proxy
            result['balance'] = get_available_funds(vc)
            result.update({'changed': True, 'verified': True, 'success': True})
            print(f"  ✅ Policy already active. Balance: ₹{result['balance']}")
        except Exception as e:
            result['error'] = 'change_or_verify_failed'
            print(f"  ❌ Change failed: {e}")
        return result

    # Step 2: /Changepwd OK
    result['changed'] = True
    print(f"  ✅ /Changepwd OK — password changed.")

    # Step 3: Verify with 5s TOTP window
    print(f"  ⏳ Sleep 5s for fresh TOTP...")
    time.sleep(5)
    try:
        _fba._clear_session(client)
        vc = dict(client)
        vc['password'] = new_password
        vc['proxy_ip'] = proxy
        result['balance'] = get_available_funds(vc)
        result.update({'verified': True, 'success': True})
        print(f"  ✅ Balance verified: ₹{result['balance']}")
    except Exception as verify_exc:
        result.update({'success': True, 'verify_warning': str(verify_exc)})
        print(f"  ⚠️ Verify failed (password changed): {verify_exc}")

    return result


def main():
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    print("=" * 60)
    print("   SmartETF — Finvasia Password Changer (Last-3 History)")
    print(f"   Started: {ts}")
    print(f"   Mode: {'DEBUG (prompts)' if DEBUG else 'AUTO'}")
    print("=" * 60)

    # Load all FINVASIA clients
    with app.app_context():
        all_clients = get_active_clients_with_sip()

    finvasia_clients = [
        c for c in all_clients
        if (c.get('broker_name') or '').upper() == 'FINVASIA'
        and c.get('user_id_broker') not in BLOCKED_BROKER_IDS
    ]

    if not finvasia_clients:
        print("\nNo FINVASIA clients. Exiting.")
        return

    # DEBUG: per-client selection
    if DEBUG:
        print(f"\n[DEBUG] Select clients:")
        selected = []
        for c in finvasia_clients:
            bid = c.get('user_id_broker', '?')
            cid = c.get('customer_id', '?')
            ans = input(f"  Include {cid}/{bid}? [y/n]: ").strip().lower()
            if ans == 'y':
                selected.append(c)
                print(f"  ✅ {bid}")
            else:
                print(f"  ⏭️ {bid}")
        finvasia_clients = selected

    if not finvasia_clients:
        print("\nNo clients selected. Exiting.")
        return

    # Build records with history, generate new password avoiding last 3
    print(f"\n  Building password plan for {len(finvasia_clients)} client(s)...")
    records = []
    for c in finvasia_clients:
        with app.app_context():
            broker_row = Broker.query.filter_by(user_id_broker=c['user_id_broker']).first()
            user_row = User.query.filter_by(customer_id=c['customer_id']).first()
            old_pw = broker_row.password if broker_row else (c.get('password') or '')
            full_name = (user_row.full_name if user_row else None) or c.get('username') or ''

        # Load last 3 from rolling history
        hist = _load_last_passwords(c['user_id_broker'])
        pwd_current, pwd_previous, pwd_2_ago = hist[0], hist[1], hist[2]

        # If DB password differs from history current, use DB as ground truth
        db_is_current = (old_pw == pwd_current)
        if not db_is_current and old_pw:
            # Shift: DB pwd becomes current, previous history shifts
            pwd_2_ago = pwd_previous
            pwd_previous = pwd_current
            pwd_current = old_pw

        # Generate new password, avoiding last 3
        forbidden = {p for p in [pwd_current, pwd_previous, pwd_2_ago] if p}
        new_pw = _password_policy(full_name, c['user_id_broker'], forbidden)

        records.append({
            'customer_id': c['customer_id'],
            'user_id_broker': c['user_id_broker'],
            'full_name': full_name,
            'pwd_current': pwd_current,
            'pwd_previous': pwd_previous,
            'pwd_2_ago': pwd_2_ago,
            'new_password_generated': new_pw or 'POLICY_FAILED',
            'changed': False, 'verified': False, 'balance': '',
            'error': '', 'verify_warning': '', 'timestamp': '',
        })

    # Save run backup CSV
    csv_path = _save_run_csv(records, ts)
    print(f"\n  ⚠️  Run backup saved: {csv_path}")
    print(f"  ⚠️  Rolling history: {_HISTORY_FILE}\n")

    # Process each
    for client, rec in zip(finvasia_clients, records):
        bid = rec['user_id_broker']
        old_pw = rec['pwd_current'] or rec['pwd_previous']  # current if available
        new_pw = rec['new_password_generated']

        print(f"\n{'─' * 58}")
        print(f"  Client: {rec['full_name']} ({rec['customer_id']})")
        print(f"  Broker: {bid}")
        print(f"  History (last 3): {rec['pwd_2_ago'] or '-'} → {rec['pwd_previous'] or '-'} → {rec['pwd_current'] or '-'}")
        print(f"  New generated:    {new_pw}")
        print(f"{'─' * 58}")

        if new_pw == 'POLICY_FAILED':
            print(f"  ❌ Policy failed. Skipping.")
            rec['error'] = 'policy_failed'
            rec['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _save_run_csv(records, ts)
            _append_history(rec)
            continue

        if DEBUG:
            conf = input(f"  Confirm change? [y/n]: ").strip().lower()
            if conf != 'y':
                print(f"  ⏭️ Skipped.")
                rec['error'] = 'skipped_by_user'
                rec['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _save_run_csv(records, ts)
                _append_history(rec)
                continue

        # Run change
        result = _do_change(client, old_pw, new_pw)

        # Save to DB
        if result.get('changed'):
            try:
                with app.app_context():
                    broker_row = Broker.query.filter_by(user_id_broker=bid).first()
                    if broker_row:
                        broker_row.password = new_pw
                        broker_row.last_updated = datetime.datetime.utcnow()
                        db.session.commit()
                        print(f"  💾 DB updated for {bid}.")
                    else:
                        print(f"  ⚠️ DB row not found for {bid}!")
            except Exception as db_err:
                print(f"  ⚠️ DB save failed: {db_err}")

        # Update record with result
        rec.update({
            'changed': result.get('changed', False),
            'verified': result.get('verified', False),
            'balance': result.get('balance') or '',
            'error': result.get('error') or '',
            'verify_warning': result.get('verify_warning') or '',
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })

        # Append to rolling history (new becomes current, chain shifts)
        if result.get('changed'):
            rec['pwd_2_ago'] = rec['pwd_previous']
            rec['pwd_previous'] = rec['pwd_current']
            rec['pwd_current'] = new_pw
        _append_history(rec)
        _save_run_csv(records, ts)

    # Summary
    print(f"\n{'=' * 58}")
    print("  FINAL SUMMARY")
    print(f"{'=' * 58}")
    for r in records:
        icon = '✅' if r['changed'] else ('⏭️ ' if r['error'] == 'skipped_by_user' else '❌')
        print(f"  {icon} {r['user_id_broker']:12} | changed={r['changed']} | {r['pwd_current'][:20]:20}")
        if r['error']:
            print(f"       err: {r['error']}")

    print(f"\n  📁 Run CSV:  {csv_path}")
    print(f"  📁 History:  {_HISTORY_FILE}")


if __name__ == '__main__':
    main()
