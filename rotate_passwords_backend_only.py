import os
import re
import random
import time
import sqlalchemy as sa
import pyotp
from app_utils.shoonya_password_util import change_password_for_client

DB_URL = os.environ.get('DB_URL') or os.environ.get('DATABASE_URL')
if not DB_URL:
    raise SystemExit('Set DB_URL to your Postgres connection string')

engine = sa.create_engine(DB_URL, future=True)

SQL_SELECT = sa.text(
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

SQL_UPDATE = sa.text('UPDATE broker SET password = :p, last_updated = NOW() WHERE id = :bid')

def policy(full_name: str) -> str | None:
    nums = ["321","647","743"]
    first = (full_name or '').split()[0]
    cleaned = re.sub(r'[^A-Za-z0-9]', '', first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    return f"{base}@{random.choice(nums)}"

def main(broker='FINVASIA'):
    ok = 0
    total = 0
    with engine.begin() as conn:
        rows = conn.execute(SQL_SELECT, {"broker": broker}).mappings().all()
    total = len(rows)
    for r in rows:
        new_pw = policy(r['full_name'])
        if not new_pw:
            continue
        old_pw = r['broker_password']
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
                with engine.begin() as conn:
                    conn.execute(SQL_UPDATE, {"p": new_pw, "bid": r['broker_id']})
                ok += 1
        except Exception:
            pass
        time.sleep(1)
    print(f"DONE: processed={total}, ok={ok}, failed={total-ok}")

if __name__ == '__main__':
    main()
