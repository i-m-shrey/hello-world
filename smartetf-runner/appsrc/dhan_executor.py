import datetime
from typing import Dict, Any, Optional, List

import pandas as pd

from dhan_api import DhanAPI, DhanAuth, DhanApiError, get_security_id


def place_order(account_info, filtered_etfs_df, is_amo=False):
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info.get('username', 'DHAN user')} via DHAN...")

    try:
        client_id = (account_info.get('dhan_client_id') or '').strip()
        access_token = (account_info.get('access_token') or '').strip()
        
        if not client_id:
            print(f"❌ Missing DHAN client_id for {account_info.get('username')}")
            return
        
        if not access_token:
            print(f"❌ Missing DHAN access_token for {account_info.get('username')}")
            return

        auth = DhanAuth(client_id=client_id, access_token=access_token)
        api = DhanAPI(auth)

        multiplier = int(account_info.get('copy_multiplier', 1))

        for _, row in filtered_etfs_df.iterrows():
            symbol = str(row.get('SYMBOL', '')).strip()
            if not symbol:
                continue

            try:
                base_qty = int(row.get('QTY', 0))
            except Exception:
                base_qty = 0

            if base_qty <= 0:
                continue

            user_qty = base_qty * multiplier
            if user_qty <= 0:
                continue

            exchange_segment = str(row.get('exchange_segment') or row.get('EXCHANGE') or 'NSE_EQ').strip().upper()

            try:
                security_id = get_security_id(symbol=symbol, exchange_segment=exchange_segment)
                payload = {
                    "dhanClientId": client_id,
                    "transactionType": "BUY",
                    "exchangeSegment": exchange_segment,
                    "productType": "CNC",
                    "orderType": "MARKET",
                    "validity": "DAY",
                    "securityId": str(security_id),
                    "quantity": user_qty,
                    "disclosedQuantity": 0,
                    "price": 0,
                    "triggerPrice": 0,
                    "afterMarketOrder": is_amo,
                }
                order_resp = api.place_order(payload)
                print(f"→ Order placed: {symbol} × {user_qty} | Response: {order_resp}")
            except DhanApiError as err:
                print(f"❌ Order failed for {symbol}: {err}")
            except Exception as exc:
                print(f"❌ Order failed for {symbol}: {exc}")

    except Exception as e:
        print(f"❌ Failed to process DHAN account {account_info.get('username')}: {e}")


def get_available_funds(account_info):
    """Get available funds for DHAN account (matches executor interface)."""
    try:
        client_id = (account_info.get('dhan_client_id') or account_info.get('client_id') or '').strip()
        access_token = (account_info.get('access_token') or '').strip()
        
        if not client_id or not access_token:
            raise DhanApiError('Missing DHAN credentials: client_id and access_token required')

        auth = DhanAuth(client_id=client_id, access_token=access_token)
        api = DhanAPI(auth)
        resp = api.get_fund_limit()
        
        print(f"[DHAN] Raw API response: {resp}")
        
        if not isinstance(resp, dict):
            raise DhanApiError(f"Invalid response type: {type(resp)}")
        
        # Check in nested 'data' first
        if 'data' in resp and isinstance(resp['data'], dict):
            data = resp['data']
        else:
            # Use top-level response
            data = resp
        
        print(f"[DHAN] Checking data: {data}")
        
        # Check for balance fields (typo version first)
        if 'availabelBalance' in data:
            val = float(data['availabelBalance'])
            print(f"[DHAN] ✅ Returning availabelBalance: {val}")
            return val
        
        if 'availableBalance' in data:
            val = float(data['availableBalance'])
            print(f"[DHAN] ✅ Returning availableBalance: {val}")
            return val
        
        if 'withdrawableBalance' in data and data['withdrawableBalance'] > 0:
            val = float(data['withdrawableBalance'])
            print(f"[DHAN] ✅ Returning withdrawableBalance: {val}")
            return val
        
        # Fallback to sodLimit calculation
        if 'sodLimit' in data:
            utilized = float(data.get('utilizedAmount', 0) or 0)
            sod_limit = float(data.get('sodLimit', 0) or 0)
            val = sod_limit - utilized
            print(f"[DHAN] ✅ Returning sodLimit-utilized: {val}")
            return val
        
        raise DhanApiError(f"Could not parse available balance from fundlimit response: {resp}")
    
    except DhanApiError:
        raise
    except Exception as e:
        print(f"❌ Failed to get DHAN funds: {e}")
        raise DhanApiError(f"Failed to get DHAN funds: {e}")


def place_market_buy_nse(account_info, symbol, quantity):
    """Place a single market buy order for NSE (matches executor interface for test orders)."""
    try:
        client_id = (account_info.get('dhan_client_id') or '').strip()
        access_token = (account_info.get('access_token') or '').strip()
        
        if not client_id or not access_token:
            raise DhanApiError('Missing DHAN credentials')

        auth = DhanAuth(client_id=client_id, access_token=access_token)
        api = DhanAPI(auth)

        security_id = get_security_id(symbol=symbol, exchange_segment='NSE_EQ')
        payload = {
            "dhanClientId": client_id,
            "transactionType": "BUY",
            "exchangeSegment": "NSE_EQ",
            "productType": "CNC",
            "orderType": "MARKET",
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": int(quantity),
            "disclosedQuantity": 0,
            "price": 0,
            "triggerPrice": 0,
            "afterMarketOrder": False,
        }
        
        order_resp = api.place_order(payload)
        print(f"→ Test order placed: {symbol} × {quantity} | Response: {order_resp}")
        return order_resp

    except Exception as e:
        print(f"❌ Test order failed: {e}")
        raise


def _save_renewed_token(account_info, new_token):
    """Save renewed token back to database."""
    try:
        from app import app, db
        from models import Broker
        broker_id = account_info.get('broker_id')
        if broker_id:
            with app.app_context():
                broker = db.session.get(Broker, broker_id)
                if broker:
                    broker.access_token = new_token
                    broker.last_updated = datetime.datetime.utcnow()
                    db.session.commit()
    except Exception as e:
        print(f"⚠️ Failed to save renewed token: {e}")


def test_sessions(clients):
    """Test DHAN sessions for a list of client dicts."""
    print(f"🔍 DHAN: Testing sessions for {len(clients)} client(s)...")
    
    from validate_client_sessions import send_email
    
    for client in clients:
        client_id = client.get('dhan_client_id', '').strip()
        access_token = client.get('access_token', '').strip()
        
        if not client_id:
            print(f"⚠️ Skipping {client.get('username')} - missing client_id")
            continue
        
        if not access_token:
            print(f"⚠️ Skipping {client.get('username')} - missing access_token")
            continue

        try:
            auth = DhanAuth(client_id=client_id, access_token=access_token)
            api = DhanAPI(auth)
            
            new_token = api.renew_token()
            print(f"✅ Token renewed for {client['username']}")
            _save_renewed_token(client, new_token)

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Session failed for {client['username']}: {error_msg}")

            email = client.get("email")
            if email:
                subject = "SmartETF DHAN Login Failed"
                body = f"""Dear {client['username']},

We were unable to authenticate your DHAN account.

Reason: {error_msg}

Please verify your API credentials.

– SmartETF Support"""
                try:
                    send_email(to_address=email, subject=subject, body=body)
                except Exception:
                    pass
            else:
                print(f"⚠️ No email found for client {client['username']}, skipping email alert.")