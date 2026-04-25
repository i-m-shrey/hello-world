"""
DHAN Broker API Wrapper - Simple order placement only
"""
import logging
from dhan_api import DhanAPI, DhanAuth, DhanApiError, get_security_id

# Module-level session cache: dhan_client_id → DhanAPI instance
# Reuses the same requests.Session() for all orders in a run.
_api_cache: dict = {}


def _get_or_create_dhan_api(client):
    """Return cached DhanAPI for this client, or create and cache a new one."""
    client_id = client.get('dhan_client_id', '').strip()
    access_token = client.get('access_token', '').strip()
    proxy_url = client.get('proxy_ip', '').strip() or None

    if client_id in _api_cache:
        # Update token in case it was refreshed since last order
        _api_cache[client_id].auth.access_token = access_token
        logging.debug(f"[DHAN] Reusing cached session for {client_id}")
        return _api_cache[client_id]

    auth = DhanAuth(client_id=client_id, access_token=access_token)
    api = DhanAPI(auth, proxy_url=proxy_url)
    _api_cache[client_id] = api
    logging.info(f"[DHAN] Created and cached new session for {client_id}")
    return api


def _clear_dhan_session(client):
    """Remove cached session so next call creates a fresh one."""
    client_id = client.get('dhan_client_id', '')
    _api_cache.pop(client_id, None)


def _get_live_price_yahoo(symbol):
    """Fetch live price from Yahoo Finance"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        price = ticker.info.get('currentPrice') or ticker.info.get('regularMarketPrice')
        if price:
            return float(price)
    except Exception as e:
        print(f"[Yahoo] Failed for {symbol}: {e}")
    return None


def place_single_order_direct(client, symbol, qty, is_amo=False, side='BUY'):
    """Direct order placement — reuses cached DhanAPI session."""
    client_id = client.get('dhan_client_id', '').strip()
    access_token = client.get('access_token', '').strip()

    if not client_id or not access_token:
        raise Exception("Missing DHAN credentials")

    api = _get_or_create_dhan_api(client)

    exchange_segment = 'NSE_EQ'
    security_id = get_security_id(symbol=symbol, exchange_segment=exchange_segment)
    
    payload = {
        "dhanClientId": client_id,
        "transactionType": "BUY" if str(side).upper() == 'BUY' else "SELL",
        "exchangeSegment": exchange_segment,
        "productType": "CNC",
        "orderType": "MARKET",
        "validity": "DAY",
        "securityId": str(security_id),
        "quantity": qty,
        "disclosedQuantity": 0,
        "price": 0,
        "triggerPrice": 0,
        "afterMarketOrder": is_amo,
    }
    
    # Add amoTime when AMO is enabled
    if is_amo:
        payload["amoTime"] = "OPEN"  # Execute at market open
    
    order_resp = api.place_order(payload)
    
    if 'orderId' in order_resp:
        return order_resp['orderId']
    elif 'data' in order_resp and 'orderId' in order_resp['data']:
        return order_resp['data']['orderId']
    else:
        raise Exception(f"Order response missing orderId: {order_resp}")
        
        
 
def place_order(client, filtered_etfs_df, is_amo=False):
    """
    Place orders for multiple ETFs (DataFrame-based interface for compatibility)
    Used by app.py test order flow
    """
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'DHAN user')} via DHAN...")
    
    multiplier = int(client.get('copy_multiplier', 1))
    
    for _, row in filtered_etfs_df.iterrows():
        symbol = str(row.get('SYMBOL', '')).strip()
        if not symbol:
            continue
        
        try:
            user_qty = int(row.get('USER_QTY', row.get('QTY', 0)))
            if user_qty < 1:
                user_qty = int(row.get('QTY', 0)) * multiplier
            if user_qty < 1:
                continue
        except Exception:
            continue
        
        try:
            order_id = place_single_order_direct(client, symbol, user_qty, is_amo)
            order_label = "AMO" if is_amo else "Order"
            print(f"→ {order_label} placed: {symbol} × {user_qty} | Order ID: {order_id}")
        except Exception as err:
            print(f"❌ Order failed for {symbol}: {err}")
            raise


def get_available_funds(client):
    """Fetch available balance — reuses cached DhanAPI session."""
    client_id = client.get('dhan_client_id', '').strip()
    access_token = client.get('access_token', '').strip()

    if not client_id or not access_token:
        raise Exception("Missing DHAN credentials")

    api = _get_or_create_dhan_api(client)
    
    resp = api.get_fund_limit()
    
    if isinstance(resp, dict):
        if 'data' in resp and isinstance(resp['data'], dict):
            return float(resp['data'].get('availabelBalance', 0))
        return float(resp.get('availabelBalance', 0))
    
    return 0.0
