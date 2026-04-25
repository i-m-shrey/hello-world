from account import Account
from app import app
from validate_client_sessions import send_email


# def execute_for_finvasia(filtered_etfs_df, clients=None):
#     with app.app_context():
#         if clients is None:
#             print("❌ Clients not provided to Finvasia executor. Master logic should not be handled here.")
#             return
#
#         print(f"📥 Running Finvasia copy for {len(clients)} client(s)...")
#
#         for client in clients:
#             if client['broker_name'].upper() != 'FINVASIA':
#                 continue
#             if not client.get('copy', True):
#                 continue
#             if client.get("is_master", False):
#                 continue
#
#             required_keys = [
#                 "user_id_broker", "password", "totp_secret",
#                 "vendor_code", "api_secret", "imei"
#             ]
#             missing = [key for key in required_keys if key not in client]
#             if missing:
#                 print(f"⚠️ Skipping {client.get('username')} due to missing fields: {missing}")
#                 continue
#
#             multiplier = int(client.get('copy_multiplier', 1))
#             copier = Account(
#                 user_id=client['user_id_broker'],
#                 password=client['password'],
#                 totp_secret=client['totp_secret'],
#                 vendor_code=client['vendor_code'],
#                 api_secret=client['api_secret'],
#                 imei=client['imei'],
#                 is_master=False,
#                 multiplier=multiplier,
#                 copy=True
#             )
#
#             copier.login()
#
#             if not copier.session or not hasattr(copier.session, 'place_order'):
#                 print(f"❌ Copier session not ready for {client['username']}")
#                 continue
#
#             for _, row in filtered_etfs_df.iterrows():
#                 symbol = row['SYMBOL'] + "-EQ"
#                 qty = int(row['QTY']) if row['QTY'] >= 1 else 1
#                 copied_qty = qty * multiplier
#
#                 print(f"→ Copier order for {client['username']}: {symbol} × {copied_qty}")
#                 copier.session.place_order(
#                     buy_or_sell="B",
#                     product_type="C",
#                     exchange="NSE",
#                     tradingsymbol=symbol,
#                     quantity=copied_qty,
#                     discloseqty=0,
#                     price_type="MKT",
#                     price=0.0,
#                     retention="DAY",
#                     amo=None,
#                     remarks=f"Copier order for {symbol}"
#                 )
#
#         print("✅ All Finvasia client orders completed.")


def place_order(account_info, filtered_etfs_df, is_amo=False):
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info['username']} via FINVASIA...")

    try:
        account = Account(user_id=account_info['user_id_broker'], password=account_info['password'], totp_secret=account_info['totp_secret'], vendor_code=account_info['vendor_code'], api_secret=account_info['api_secret'], imei=account_info['imei'], is_master=account_info.get('is_master', False), multiplier=account_info.get('copy_multiplier', 1), copy=account_info.get('copy', True))
        account.login()

        if not account.session and hasattr(account.session, 'place_order'):
            print(f"❌ Login/session failed for {account_info['username']}")
            return

        for _, row in filtered_etfs_df.iterrows():
            symbol = row['SYMBOL'] + "-EQ"
            # Prefer USER_QTY if provided by strategy (already includes multiplier); fallback to QTY
            try:
                user_qty = int(row['USER_QTY'])
            except Exception:
                user_qty = int(row['QTY']) if row['QTY'] >= 1 else 1
            if user_qty < 1:
                continue

            print(f"→ Order: {account_info['username']} - {symbol} × {user_qty}")
            account.session.place_order(
                buy_or_sell="B",
                product_type="C",
                exchange="NSE",
                tradingsymbol=symbol,
                quantity=int(user_qty),
                discloseqty=0,
                price_type="MKT",
                price=0.0,
                retention="DAY",
                amo="YES" if is_amo else None,
                remarks=f"Order for {symbol}"
            )

    except Exception as e:
        print(f"❌ Failed to process account {account_info.get('username')}: {e}")


def test_sessions(clients):
    print(f"🔍 Finvasia: Testing sessions for {len(clients)} client(s)...")
    for client in clients:
        required_keys = [
            "user_id_broker", "password", "totp_secret",
            "vendor_code", "api_secret", "imei", "email"
        ]
        missing = [key for key in required_keys if key not in client]
        if missing:
            print(f"⚠️ Skipping {client.get('username')} due to missing fields: {missing}")
            continue

        try:
            account = Account(
                user_id=client['user_id_broker'],
                password=client['password'],
                totp_secret=client['totp_secret'],
                vendor_code=client['vendor_code'],
                api_secret=client['api_secret'],
                imei=client['imei'],
                is_master=False,
                multiplier=1,
                copy=True
            )

            account.login()

            if not account.session or not hasattr(account.session, 'place_order'):
                raise Exception("Session failed: login unsuccessful")

            print(f"✅ Session OK for {client['username']}")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Session failed for {client['username']}: {error_msg}")

            email = client.get("email")
            if email:
                subject = "SmartETF Login Failed"
                body = f"""Dear {client['username']},

We were unable to log in to your Finvasia account.

Reason: {error_msg}

Please verify your credentials or reset your password.

– SmartETF Support"""
                send_email(to_address=email, subject=subject, body=body)
            else:
                print(f"⚠️ No email found for client {client['username']}, skipping email alert.")
