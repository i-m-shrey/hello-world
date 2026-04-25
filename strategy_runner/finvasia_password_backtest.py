import os
import re
import time
import zlib
from datetime import datetime

import sqlalchemy as sa
import pyotp

from app_utils.shoonya_password_util import change_password_for_client
from finvasia_broker_api import get_available_funds


DEFAULT_DB_URL = os.getenv("DATABASE_URL", "")
BACKTEST_CUSTOMER_ID = ""
BACKTEST_APPLY = False
BACKTEST_VERIFY = True
BACKTEST_VERIFY_BALANCE = True
SFXS = ["321", "647", "743", "654", "913", "525", "687", "945", "125"]


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
           u.full_name,
           u.email,
           u.customer_id
    FROM broker b
    JOIN "user" u ON u.id = b.user_id
    WHERE b.broker_name = :broker
      AND COALESCE(b.subscription_status,'') = 'Active'
    ORDER BY u.id
    """
)

SQL_SELECT_ONE = sa.text(
    """
    SELECT b.id AS broker_id,
           b.broker_name,
           b.user_id_broker,
           b.password AS broker_password,
           b.totp_secret,
           b.vendor_code,
           b.api_secret,
           b.imei,
           u.full_name,
           u.email,
           u.customer_id
    FROM broker b
    JOIN "user" u ON u.id = b.user_id
    WHERE b.broker_name = :broker
      AND COALESCE(b.subscription_status,'') = 'Active'
      AND u.customer_id = :customer_id
    LIMIT 1
    """
)

SQL_UPDATE = sa.text("UPDATE broker SET password = :p, last_updated = NOW() WHERE id = :bid")


def password_policy(full_name: str, uid: str) -> str | None:
    first = (full_name or "").split()[0]
    cleaned = re.sub(r"[^A-Za-z0-9]", "", first)
    if not cleaned:
        return None
    base = cleaned[:1].upper() + cleaned[1:].lower()
    idx = zlib.crc32((uid or "").encode("utf-8")) % len(SFXS)
    return f"{base}@{SFXS[idx]}"


def run_backtest(
    db_url: str,
    apply_changes: bool,
    verify: bool,
    verify_balance: bool,
    customer_id: str | None
) -> int:
    engine = sa.create_engine(db_url, future=True)
    with engine.begin() as conn:
        if customer_id:
            rows = conn.execute(
                SQL_SELECT_ONE,
                {"broker": "FINVASIA", "customer_id": customer_id.strip()}
            ).mappings().all()
        else:
            rows = conn.execute(SQL_SELECT, {"broker": "FINVASIA"}).mappings().all()

    results = []
    for row in rows:
        new_pw = password_policy(row["full_name"], row["user_id_broker"])
        if not new_pw:
            results.append((row["customer_id"], False, "policy_failed", "", "", ""))
            continue

        def totp():
            return pyotp.TOTP(row["totp_secret"]).now() if row["totp_secret"] else ""

        if not apply_changes:
            print(f"[DRY-RUN] {row['customer_id']} -> new password would be: {new_pw}")
            print(f"[DRY-RUN] No DB update performed for {row['customer_id']}")
            results.append((row["customer_id"], True, "dry_run", new_pw, "", ""))
            continue

        try:
            ok = change_password_for_client(
                userid=row["user_id_broker"],
                old_password=row["broker_password"],
                new_password=new_pw,
                vendor_code=row["vendor_code"] or "",
                api_secret=row["api_secret"] or "",
                imei=row["imei"] or "api-device",
                totp_fn=totp,
                verify=verify,
            )
            if ok:
                with engine.begin() as conn:
                    conn.execute(SQL_UPDATE, {"p": new_pw, "bid": row["broker_id"]})
                print(f"[APPLIED] {row['customer_id']} -> new password set: {new_pw}")
                balance_status = ""
                balance_value = ""
                if verify_balance:
                    try:
                        balance = get_available_funds({
                            "user_id_broker": row["user_id_broker"],
                            "password": new_pw,
                            "totp_secret": row["totp_secret"],
                            "vendor_code": row["vendor_code"],
                            "api_secret": row["api_secret"],
                            "imei": row["imei"],
                        })
                        balance_status = "balance_ok"
                        balance_value = f"{balance:.2f}"
                        print(f"[VERIFY] Balance fetched for {row['customer_id']}: ₹{balance:.2f}")
                    except Exception as verify_error:
                        balance_status = f"balance_failed:{verify_error}"
                        print(f"[VERIFY] Balance fetch failed for {row['customer_id']}: {verify_error}")
                results.append((row["customer_id"], True, "changed", new_pw, balance_status, balance_value))
            else:
                results.append((row["customer_id"], False, "change_or_verify_failed", new_pw, "", ""))
        except Exception as exc:
            results.append((row["customer_id"], False, str(exc), new_pw, "", ""))

        time.sleep(0.5)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(os.path.dirname(__file__), "daily_orders", f"finvasia_backtest_{ts}.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("customer_id,success,status,new_password,balance_status,balance_value\n")
        for cid, ok, status, new_pw, balance_status, balance_value in results:
            f.write(f"{cid},{ok},{status},{new_pw},{balance_status},{balance_value}\n")

    ok_count = sum(1 for _, ok, _, _, _, _ in results if ok)
    print(f"Backtest complete: {ok_count}/{len(results)} successful. CSV: {out_path}")
    return 0


def main() -> int:
    if not DEFAULT_DB_URL:
        raise SystemExit("DATABASE_URL is required (pass --db-url or set env).")
    return run_backtest(
        DEFAULT_DB_URL,
        BACKTEST_APPLY,
        BACKTEST_VERIFY,
        BACKTEST_VERIFY_BALANCE,
        BACKTEST_CUSTOMER_ID or None
    )


if __name__ == "__main__":
    raise SystemExit(main())
