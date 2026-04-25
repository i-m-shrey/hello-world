"""
change_passwords.py
===================
Standalone Finvasia password changer for SmartETF clients.

Uses the single shared rotation logic from finvasia_password_utils:
  • Last-3 password history (avoids Finvasia's reuse policy)
  • Random suffix (FirstName@XXX)
  • Pre-save backup CSV before any API call
  • DB update immediately on change
  • Re-login + balance verify
  • Admin alert if balance verify fails
  • Client email on success

Run:
    python change_passwords.py
"""

import os
import sys
import csv
import datetime
import logging

# ── Path setup ───────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
_APPSRC = os.path.join(_HERE, '..')
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(_APPSRC))

from app import app
from client_fetcher import get_active_clients_with_sip
from finvasia_password_utils import (
    rotate_finvasia_password,
    load_password_history,
    generate_password,
    OUTPUT_FOLDER,
    HISTORY_FILE,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =============================================================================
# CONTROL VARIABLES  (edit before running)
# =============================================================================

DEBUG = True
# True  → prompt per-client: show history / old / new → ask y/n
# False → auto-process all non-blocked clients

BLOCKED_BROKER_IDS: frozenset = frozenset()
# Add user_id_broker to permanently skip. Example: frozenset({'FN148473'})

# =============================================================================


def _save_run_csv(records: list, ts: str) -> str:
    """Per-run backup CSV (overwrites on each update)."""
    fields = [
        'customer_id', 'user_id_broker', 'full_name',
        'pwd_history_current', 'pwd_history_prev', 'pwd_history_2ago',
        'new_password_generated', 'changed', 'verified', 'balance',
        'error', 'verify_warning', 'timestamp',
    ]
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    path = os.path.join(OUTPUT_FOLDER, f'password_changes_{ts}.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(records)
    return path


def main():
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    print('=' * 60)
    print('   SmartETF — Finvasia Password Changer')
    print(f'   Started : {ts}')
    print(f'   Mode    : {"DEBUG (per-client prompt)" if DEBUG else "AUTO (all clients)"}')
    print('=' * 60)

    with app.app_context():
        all_clients = get_active_clients_with_sip()

    finvasia_clients = [
        c for c in all_clients
        if (c.get('broker_name') or '').upper() == 'FINVASIA'
        and c.get('user_id_broker') not in BLOCKED_BROKER_IDS
    ]

    if not finvasia_clients:
        print('\nNo FINVASIA clients found. Exiting.')
        return

    # ── Per-client selection (DEBUG mode) ────────────────────────────────────
    if DEBUG:
        print(f'\n[DEBUG] Select clients for password change:')
        selected = []
        for c in finvasia_clients:
            bid  = c.get('user_id_broker', '?')
            cid  = c.get('customer_id', '?')
            name = c.get('full_name') or c.get('username') or '?'
            ans  = input(f'  Change password for {name} ({cid} / {bid})? [y/n]: ').strip().lower()
            if ans == 'y':
                selected.append(c)
                print(f'  ✅ {bid} selected')
            else:
                print(f'  ⏭️  {bid} skipped')
        finvasia_clients = selected

    if not finvasia_clients:
        print('\nNo clients selected. Exiting.')
        return

    # ── Pre-run summary (show what will happen) ──────────────────────────────
    print(f'\n  Building password plan for {len(finvasia_clients)} client(s)...')
    records = []
    for c in finvasia_clients:
        bid  = c.get('user_id_broker')
        hist = load_password_history(bid)
        old_pw = c.get('password') or ''
        # If DB pw differs from history current, treat DB as current
        pwd_cur, pwd_prev, pwd_2ago = hist
        if old_pw and old_pw != pwd_cur:
            pwd_2ago = pwd_prev
            pwd_prev = pwd_cur
            pwd_cur  = old_pw
        forbidden = {p for p in [pwd_cur, pwd_prev, pwd_2ago] if p}
        full_name = c.get('full_name') or c.get('username') or ''
        new_pw = generate_password(full_name, forbidden)
        records.append({
            'customer_id':            c.get('customer_id'),
            'user_id_broker':         bid,
            'full_name':              full_name,
            'pwd_history_current':    pwd_cur,
            'pwd_history_prev':       pwd_prev,
            'pwd_history_2ago':       pwd_2ago,
            'new_password_generated': new_pw or 'POLICY_FAILED',
            'changed': False, 'verified': False, 'balance': '',
            'error': '', 'verify_warning': '', 'timestamp': '',
        })

    csv_path = _save_run_csv(records, ts)
    print(f'\n  ⚠️  Backup CSV saved BEFORE changes:')
    print(f'     {csv_path}')
    print(f'  ⚠️  Keep this file — it contains old passwords.')
    print(f'  📁 Rolling history : {HISTORY_FILE}\n')

    # ── Process each client ───────────────────────────────────────────────────
    for client, rec in zip(finvasia_clients, records):
        bid   = rec['user_id_broker']
        new_pw = rec['new_password_generated']

        print(f'\n{"─" * 58}')
        print(f'  Client  : {rec["full_name"]} ({rec["customer_id"]})')
        print(f'  Broker  : {bid}')
        print(f'  History : {rec["pwd_history_2ago"] or "-"} → {rec["pwd_history_prev"] or "-"} → {rec["pwd_history_current"] or "-"}')
        print(f'  Old pwd : {rec["pwd_history_current"] or client.get("password")}')
        print(f'  New pwd : {new_pw}')
        print(f'{"─" * 58}')

        if new_pw == 'POLICY_FAILED':
            print(f'  ❌ Policy failed — skipping.')
            rec['error'] = 'policy_failed'
            rec['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _save_run_csv(records, ts)
            continue

        # ── Delegate to shared rotation logic ────────────────────────────────
        # debug=DEBUG triggers the internal y/n confirmation prompt inside
        # rotate_finvasia_password, so the user sees old/new and can confirm.
        result = rotate_finvasia_password(
            client,
            error_message='manual_change',
            notify_client=True,
            debug=DEBUG,
        )

        # Update record with result
        rec.update({
            'changed':        result.get('changed', False),
            'verified':       result.get('verified', False),
            'balance':        result.get('balance') or '',
            'error':          result.get('error') or '',
            'verify_warning': result.get('verify_warning') or '',
            'timestamp':      datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        if result.get('new_password'):
            rec['new_password_generated'] = result['new_password']

        _save_run_csv(records, ts)

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f'\n{"=" * 58}')
    print('  FINAL SUMMARY')
    print(f'{"=" * 58}')
    for r in records:
        if r['error'] == 'skipped_by_user' or r['error'] == 'skipped_in_debug_mode':
            icon = '⏭️ '
        elif r['changed']:
            icon = '✅'
        else:
            icon = '❌'
        bal = f"₹{r['balance']}" if r['balance'] else 'N/A'
        print(f'  {icon} {r["user_id_broker"]:12} | changed={r["changed"]} | '
              f'verified={r["verified"]} | balance={bal}')
        if r['error']:
            print(f'       err : {r["error"]}')
        if r['verify_warning']:
            print(f'       warn: {r["verify_warning"]}')

    print(f'\n  📁 CSV saved at: {_save_run_csv(records, ts)}')
    print(f'  📁 Folder      : {OUTPUT_FOLDER}')


if __name__ == '__main__':
    main()
