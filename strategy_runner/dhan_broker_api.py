"""
DHAN Broker API Wrapper - Simple order placement only
"""
from dhan_api import DhanAPI, DhanAuth, DhanApiError
from dhan_security_helper import get_security_id


def place_single_order_direct(client, symbol, qty, is_amo=False):
    """Direct order placement - raises exception if fails"""
    client_id = client.get('dhan_client_id', '').strip()
    access_token = client.get('access_token', '').strip()
    
    if not client_id or not access_token:
        raise Exception("Missing DHAN credentials")
    
    auth = DhanAuth(client_id=client_id, access_token=access_token)
    api = DhanAPI(auth)
    
    exchange_segment = 'NSE_EQ'
    security_id = get_security_id(symbol=symbol, exchange_segment=exchange_segment)
    
    payload = {
        "dhanClientId": client_id,
        "transactionType": "BUY",
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
    
    order_resp = api.place_order(payload)
    
    if 'orderId' in order_resp:
        return order_resp['orderId']
    elif 'data' in order_resp and 'orderId' in order_resp['data']:
        return order_resp['data']['orderId']
    else:
        raise Exception(f"Order response missing orderId: {order_resp}")


def get_available_funds(client):
    """Fetch available balance"""
    client_id = client.get('dhan_client_id', '').strip()
    access_token = client.get('access_token', '').strip()
    
    if not client_id or not access_token:
        raise Exception("Missing DHAN credentials")
    
    auth = DhanAuth(client_id=client_id, access_token=access_token)
    api = DhanAPI(auth)
    
    resp = api.get_fund_limit()
    
    if isinstance(resp, dict):
        if 'data' in resp and isinstance(resp['data'], dict):
            return float(resp['data'].get('availabelBalance', 0))
        return float(resp.get('availabelBalance', 0))
    
    return 0.0
