from icici_account import ICICIAccount
from validate_client_sessions import send_email
from app import app


# def execute_for_icici(filtered_etfs_df, clients=None):
#     with app.app_context():
#         if not clients:
#             print("❌ No clients provided for ICICI execution.")
#             return
#
#         print(f"🚀 Executing ICICI copy for {len(clients)} client(s)...")
#
#         for client in clients:
#             if client['broker_name'].upper() != 'ICICI':
#                 continue
#
#             required_keys = ["user_id_broker", "password", "app_key", "secret_key"]
#             missing = [key for key in required_keys if key not in client]
#             if missing:
#                 print(f"⚠️ Skipping {client.get('username')} due to missing fields: {missing}")
#                 continue
#
#             multiplier = int(client.get('copy_multiplier', 1))
#             print(f"🔑 Logging in ICICI client: {client['username']}")
#             account = ICICIAccount(
#                 username=client['user_id_broker'],
#                 password=client['password'],
#                 app_key=client['app_key'],
#                 secret_key=client['secret_key']
#             )
#             account.login()
#
#             if not account.session_token:
#                 print(f"❌ Skipping {client['username']} — login failed.")
#                 continue
#
#             for _, row in filtered_etfs_df.iterrows():
#                 symbol = row['SYMBOL'] + "-EQ"
#                 qty = int(row['QTY']) if row['QTY'] >= 1 else 1
#                 copied_qty = qty * multiplier
#
#                 account.place_order(symbol=symbol, quantity=copied_qty)


def place_order(account_info, filtered_etfs_df, is_amo=False):
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info['username']} via ICICI...")
    if is_amo:
        print(f"⚠️ AMO orders not yet implemented for ICICI")

    try:
        account = ICICIAccount(username=account_info['user_id_broker'], password=account_info['password'], app_key=account_info['app_key'], secret_key=account_info['secret_key'])
        account.login()

        if not account.session_token:
            print(f"❌ Login/session failed for {account_info['username']}")
            return

        for _, row in filtered_etfs_df.iterrows():
            symbol = row['SYMBOL'] + "-EQ"
            try:
                user_qty = int(row['USER_QTY'])
            except Exception:
                user_qty = int(row['QTY']) if row['QTY'] >= 1 else 1
            if user_qty < 1:
                continue

            print(f"→ Order: {account_info['username']} - {symbol} × {user_qty}")
            account.place_order(symbol=symbol, quantity=int(user_qty))

    except Exception as e:
        print(f"❌ Failed to process account {account_info.get('username')}: {e}")


def test_sessions(clients):
    print(f"🔍 ICICI: Testing sessions for {len(clients)} client(s)...")
    for client in clients:
        required_keys = ['user_id_broker', 'password', 'app_key', 'secret_key', 'email']
        missing = [key for key in required_keys if key not in client]
        if missing:
            print(f"⚠️ Skipping {client.get('username')} due to missing fields: {missing}")
            continue

        try:
            account = ICICIAccount(username=client['user_id_broker'], password=client['password'], app_key=client['app_key'], secret_key=client['secret_key'])
            account.login()

            if not account.session_token:
                raise Exception("Session failed: login unsuccessful")

            print(f"✅ Session OK for {client['username']}")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Session failed for {client['username']}: {error_msg}")

            email = client.get("email")
            if email:
                subject = "SmartETF Login Failed"
                body = f"Dear {client['username']},\n\nWe were unable to log in to your ICICI account.\n\nReason: {error_msg}\n\nPlease verify your credentials or reset your password.\n\n- SmartETF Support"
                send_email(to_address=email, subject=subject, body=body)
            else:
                print(f"⚠️ No email found for client {client['username']}, skipping email alert.")
