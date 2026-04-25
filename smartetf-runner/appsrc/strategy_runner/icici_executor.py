"""
ICICI Direct Breeze API Executor
Requires: pip install breeze-connect

Credential fields in broker record:
  - api_key:       Breeze APP KEY
  - api_secret:    Breeze Secret Key
  - access_token:  Session token obtained from ICICI OAuth login URL

How to get session_token:
  1. Direct user to: https://api.icicidirect.com/apiuser/login?api_key=<APP_KEY>
  2. After login, redirect URL contains ?SessionToken=<token>
  3. Store that token in the broker record as access_token.
  4. Session tokens are valid for one trading day.
"""
import logging


def _get_breeze(client):
    """Return an authenticated BreezeConnect instance."""
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        raise ImportError("breeze-connect not installed. Run: pip install breeze-connect")

    api_key = client.get('api_key', '').strip()
    api_secret = client.get('api_secret', '').strip()
    session_token = client.get('access_token', '').strip()

    if not all([api_key, api_secret, session_token]):
        raise Exception(
            "Missing ICICI Breeze credentials: need api_key, api_secret, and access_token (session token)"
        )

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    return breeze


def place_single_order_direct(client, symbol, qty, is_amo=False):
    """
    Place a single BUY market order on NSE via ICICI Breeze. Raises on failure.

    Returns:
        str: order_id
    """
    breeze = _get_breeze(client)
    sym = symbol.strip().upper()

    order_params = dict(
        stock_code=sym,
        exchange_code="NSE",
        product="margin",
        action="buy",
        order_type="market",
        stoploss="0",
        quantity=str(int(qty)),
        price="0",
        validity="day",
        validity_date="",
        disclosed_quantity="0",
        expiry_date="",
        right="others",
        strike_price="0",
        user_remark="SmartETF",
        order_type_fresh="market",
        order_rate_fresh="0",
        settlement_id="",
        order_segment_code="N",
        market_type="MKT",
        fresh_order_limit="0",
        is_amo=str(is_amo).upper(),
    )

    logging.info(f"ICICI Breeze order: {sym} × {qty} (AMO={is_amo})")
    response = breeze.place_order(**order_params)

    if response and response.get('Status') == 200:
        order_id = (
            response.get('Success', {}).get('order_id')
            or response.get('Success', {}).get('OrderId')
            or str(response.get('Success', ''))
        )
        logging.info(f"ICICI order placed: {sym} × {qty} | Order ID: {order_id}")
        return order_id

    msg = response.get('Error') or response.get('message', 'Unknown error') if response else 'No response'
    raise Exception(f"ICICI order failed for {sym}: {msg}")


def place_order(client, filtered_etfs_df, is_amo=False):
    """DataFrame-based order placement (called by BrokerAPIWrapper)."""
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'ICICI user')} via ICICI Direct...")

    for _, row in filtered_etfs_df.iterrows():
        symbol = str(row.get('SYMBOL', '')).strip()
        if not symbol:
            continue
        try:
            user_qty = int(row.get('USER_QTY', row.get('QTY', 0)))
            if user_qty < 1:
                continue
        except Exception:
            continue

        try:
            order_id = place_single_order_direct(client, symbol, user_qty, is_amo)
            print(f"→ Order placed: {symbol} × {user_qty} | Order ID: {order_id}")
        except Exception as err:
            print(f"❌ Order failed for {symbol}: {err}")


def get_available_funds(client):
    """
    Fetch available cash balance for ICICI Direct client.

    Returns:
        float: available cash in INR
    """
    breeze = _get_breeze(client)
    try:
        resp = breeze.get_fund_limit()
        if resp and resp.get('Status') == 200:
            data = resp.get('Success', {})
            for key in ('limit_used', 'payIn', 'cash_limit', 'net', 'available_limit'):
                if key in data:
                    available = float(data[key])
                    logging.info(f"ICICI balance for {client.get('customer_id')}: ₹{available}")
                    return available
            raise Exception(f"No known balance field in response: {data}")
        raise Exception(f"get_fund_limit failed: {resp}")
    except Exception as e:
        logging.error(f"ICICI balance fetch failed for {client.get('customer_id')}: {e}")
        raise


def test_sessions(clients):
    print(f"🔍 ICICI: Testing sessions for {len(clients)} client(s)...")
    for client in clients:
        try:
            balance = get_available_funds(client)
            print(f"✅ Session OK for {client.get('username')} — Balance: ₹{balance}")
        except Exception as e:
            print(f"❌ Session failed for {client.get('username')}: {e}")
