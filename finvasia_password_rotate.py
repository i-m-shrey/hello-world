import os
import sys
import time
import re
import random
import sqlalchemy as sa
import pyotp
import zlib
from app_utils.shoonya_password_util import change_password_for_client
from email_notifications import send_email

DB_URL = "postgresql+pg8000://postgres.qogfivsjxarodbyokfkn:P%40ssword123211600%26prince@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"

# Deterministic policy: FirstName@SFX where SFX chosen by hash(user_id)
_SFXS = ["321","647","743","654","913","525","687","945","125"]

def _sfx_for(uid: str) -> str:
    try:
        idx = zlib.crc32((uid or '').encode('utf-8')) % len(_SFXS)
        return _SFXS[idx]
    except Exception:
        return _SFXS[0]

def _policy(full_name: str, uid: str) -> str | None:
    first = (full_name or '').split()[0]
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    return f"{base}@{_sfx_for(uid)}"

_SQL_SELECT = sa.text(
    """
    SELECT b.id AS broker_id,
           b.broker_name,
           b.user_id_broker,
           b.password AS broker_password,
           b.totp_secret,
           b.vendor_code,
           b.api_secret,
           b.imei,
           u.id AS user_id,
           u.full_name,
           u.email,
           u.mobile,
           u.customer_id
    FROM broker b
    JOIN "user" u ON u.id = b.user_id
    WHERE b.broker_name = :broker
      AND COALESCE(b.subscription_status,'') = 'Active'
      AND EXISTS (
        SELECT 1 FROM subscription s
        WHERE s.customer_id = u.customer_id
          AND s.payment_status IN ('Paid','Active','Successful')
          AND s.expiry_date > NOW()
      )
    ORDER BY u.id
    """
)

_SQL_UPDATE = sa.text('UPDATE broker SET password = :p, last_updated = NOW() WHERE id = :bid')

def main():
    # Config
    broker = 'FINVASIA'
    admin_email = os.environ.get('ADMIN_EMAIL', 'smartetfalgo@gmail.com')
    db_url = DB_URL
    engine = sa.create_engine(db_url, future=True)
    # Fetch all active FINVASIA rows
    with engine.begin() as conn:
        rows = conn.execute(_SQL_SELECT, {"broker": broker}).mappings().all()

    results = []
    ok = 0
    total = len(rows)

    for r in rows:
        new_pw = _policy(r['full_name'], r['user_id_broker'])
        old_pw = r['broker_password']
        changed = False
        verified = False
        error = ''

        if not new_pw:
            error = 'policy_failed'
        else:
            def _totp():
                return pyotp.TOTP(r['totp_secret']).now() if r['totp_secret'] else ''
            try:
                success = change_password_for_client(
                    userid=r['user_id_broker'],
                    old_password=old_pw,
                    new_password=new_pw,
                    vendor_code=r['vendor_code'] or '',
                    api_secret=r['api_secret'] or '',
                    imei=r['imei'] or 'api-device',
                    totp_fn=_totp,
                    verify=True,
                )
                if success:
                    # Update DB only after verification succeeds
                    with engine.begin() as conn:
                        conn.execute(_SQL_UPDATE, {"p": new_pw, "bid": r['broker_id']})
                    changed = True
                    verified = True
                    ok += 1
                else:
                    error = 'change_or_verify_failed'
            except Exception as e:
                error = str(e)

        results.append({
            'full_name': r['full_name'],
            'email': r['email'],
            'broker_username': r['user_id_broker'],
            'old_password': old_pw,
            'new_password': new_pw,
            'changed': changed,
            'verified': verified,
            'error': error,
        })
        time.sleep(0.5)  # small courtesy delay to avoid hammering API

    failed = total - ok

    # Write CSV locally (in case email fails)
    ts = time.strftime('%Y%m%d_%H%M%S')
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_orders')
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f'finvasia_passwords_{ts}.csv')
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('full_name,email,broker_username,old_password,new_password,changed,verified,error\n')
        for it in results:
            def esc(x):
                s = '' if x is None else str(x)
                if ',' in s or '"' in s:
                    s = '"' + s.replace('"','""') + '"'
                return s
            f.write(','.join([
                esc(it['full_name']), esc(it['email']), esc(it['broker_username']),
                esc(it['old_password']), esc(it['new_password']),
                esc(it['changed']), esc(it['verified']), esc(it['error'])
            ]) + '\n')

    # Build admin summary (HTML table) and email
    subject = f"Finvasia Password Rotation Summary"
    rows_html = "".join([
        f"<tr><td>{it['full_name'] or ''}</td><td>{it['broker_username'] or ''}</td><td>{it['new_password'] or ''}</td><td>{'OK' if (it['changed'] and it['verified']) else 'FAIL'}</td><td>{(it['error'] or '')}</td></tr>"
        for it in results
    ])
    html = f"""
    <html><body>
    <h3>Finvasia Password Rotation Summary</h3>
    <p>Processed: {total} | OK: {ok} | Failed: {failed}</p>
    <p>CSV saved to: {csv_path}</p>
    <table border="1" cellpadding="6" cellspacing="0">
      <thead><tr><th>Full Name</th><th>User ID</th><th>New Password</th><th>Status</th><th>Comments</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    </body></html>
    """

    try:
        send_email(admin_email, subject, html, is_html=True)
    except Exception:
        pass

    print(f"DONE: processed={total}, ok={ok}, failed={failed}. CSV: {csv_path}")
    sys.exit(0 if failed == 0 else 1)

if __name__ == '__main__':
    main()
