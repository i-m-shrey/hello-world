"""
Upstox Broker API Wrapper

Credentials stored in broker record:
  - api_key:     Upstox API Key (client_id from developer console)
  - api_secret:  Upstox API Secret (client_secret)
  - mobile:      Upstox registered mobile number (username)
  - password:    Upstox login password
  - totp_secret: TOTP secret for 2FA (base32 from authenticator setup)
  - access_token: JWT token (cached in DB, refreshed via TOTP flow)

TOKEN GENERATION:
  Uses upstox-totp library which handles the full OAuth2 + TOTP login flow
  automatically. No manual browser/redirect needed.
  upx.app_token.get_access_token() → AccessTokenResponse
  token = response.data.access_token
"""
import logging
import upstox_client
from upstox_client.rest import ApiException

# ---------------------------------------------------------------------------
# Session cache  (keyed by broker_id)
# ---------------------------------------------------------------------------
_SESSION_CACHE = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _save_token_to_db(client, token):
    """Persist refreshed token to the Broker DB record (best-effort)."""
    broker_id = client.get('broker_id')
    if not broker_id:
        return
    try:
        from app import app, db
        from models import Broker
        from datetime import datetime as _dt
        with app.app_context():
            broker = db.session.get(Broker, broker_id)
            if broker:
                broker.access_token = token
                broker.last_updated = _dt.utcnow()
                db.session.commit()
                logging.info(f"Upstox: token saved to DB for broker_id={broker_id}")
    except Exception as e:
        logging.warning(f"Upstox: could not save token to DB: {e}")


def _get_session_key(client):
    return client.get('broker_id') or client.get('mobile', 'upstox_unknown')


def _generate_fresh_token(client):
    """
    Generate a new Upstox access token via TOTP OAuth2 flow.
    Returns the token string and saves it to DB + client dict.
    """
    api_key = client.get('api_key', '').strip()
    api_secret = client.get('api_secret', '').strip()
    mobile = client.get('mobile', '').strip()
    password = client.get('password', '').strip()
    totp_secret = client.get('totp_secret', '').strip()

    if not all([api_key, api_secret, mobile, password, totp_secret]):
        raise Exception(
            "Upstox: missing credentials for token generation "
            "(need api_key, api_secret, mobile, password, totp_secret)"
        )

    logging.info(f"Upstox: generating new access token for {client.get('customer_id', 'unknown')}...")

    try:
        from upstox_totp import UpstoxTOTP
    except ImportError:
        raise ImportError("upstox-totp not installed. Run: pip install upstox-totp")

    upx = UpstoxTOTP(
        username=mobile,
        password=password,
        totp_secret=totp_secret,
        client_id=api_key,
        client_secret=api_secret,
        redirect_uri='https://127.0.0.1',
    )

    response = upx.app_token.get_access_token()

    if response and response.data and response.data.access_token:
        token = response.data.access_token
        client['access_token'] = token
        _save_token_to_db(client, token)
        logging.info(f"Upstox: token generated successfully for {client.get('customer_id', 'unknown')}")
        return token
    else:
        raise Exception(f"Upstox: get_access_token returned unexpected response: {response}")


def _get_api_client(client, force_new=False):
    """
    Return an authenticated upstox_client.ApiClient instance.

    Uses cached token from client dict if available. On force_new=True or
    missing token, generates a fresh token via TOTP flow.
    """
    key = _get_session_key(client)

    if not force_new and key in _SESSION_CACHE:
        logging.debug(f"Upstox: reusing cached session for {key}")
        return _SESSION_CACHE[key]

    token = client.get('access_token', '').strip()

    if not token or force_new:
        token = _generate_fresh_token(client)

    configuration = upstox_client.Configuration()
    configuration.access_token = token
    api_client = upstox_client.ApiClient(configuration)
    _SESSION_CACHE[key] = api_client
    return api_client


def _invalidate_session(client):
    """Remove cached session and clear token so next call regenerates."""
    key = _get_session_key(client)
    _SESSION_CACHE.pop(key, None)
    client['access_token'] = ''


def _is_auth_error(exc):
    """Return True if the exception indicates an auth/token expiry error."""
    if isinstance(exc, ApiException):
        if exc.status in (401, 403):
            return True
    err = str(exc).lower()
    return any(k in err for k in (
        '401', '403', 'unauthorized', 'token', 'session', 'authentication',
        'invalid token', 'expired', 'access denied', 'udapi-b100'
    ))


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_single_order_direct(client, symbol, qty, is_amo=False, side='BUY'):
    """
    Place a BUY or SELL order for any NSE equity/ETF symbol via Upstox.
    Auto-refreshes token on 401/auth failure and retries once.

    Args:
        client:  broker credentials dict
        symbol:  NSE trading symbol (e.g. 'NIFTYBEES')
        qty:     quantity (int)
        is_amo:  True for After Market Order
        side:    'BUY' or 'SELL' (default 'BUY')

    Returns:
        str: Upstox order_id
    """
    sym = symbol.strip().upper()
    transaction_type = side.strip().upper() if side else 'BUY'
    instrument_token = f"NSE_EQ|{sym}"

    def _attempt(fresh=False):
        api_client = _get_api_client(client, force_new=fresh)
        order_api = upstox_client.OrderApi(api_client)
        order_data = upstox_client.PlaceOrderRequest(
            quantity=int(qty),
            product='D',
            validity='DAY',
            price=0.0,
            tag='SmartETF',
            instrument_token=instrument_token,
            order_type='MARKET',
            transaction_type=transaction_type,
            disclosed_quantity=0,
            trigger_price=0.0,
            is_amo=is_amo,
        )
        logging.info(
            f"Upstox order: {transaction_type} {sym} × {qty} "
            f"(token={instrument_token}, AMO={is_amo})"
        )
        return order_api.place_order(order_data, api_version='2.0')

    # First attempt (cached session)
    response = None
    try:
        response = _attempt(fresh=False)
    except Exception as first_err:
        if not _is_auth_error(first_err):
            raise Exception(f"Upstox order failed for {sym}: {first_err}")
        logging.warning(
            f"Upstox: auth error placing order for {sym}: {first_err} — refreshing token"
        )
        _invalidate_session(client)
        try:
            response = _attempt(fresh=True)
        except Exception as retry_err:
            raise Exception(f"Upstox order failed for {sym} after token refresh: {retry_err}")

    if response and hasattr(response, 'data') and response.data:
        order_id = getattr(response.data, 'order_id', None)
        if order_id:
            logging.info(f"Upstox order placed: {sym} × {qty} | Order ID: {order_id}")
            return str(order_id)

    raise Exception(f"Upstox: order response missing order_id: {response}")


def place_order(client, filtered_etfs_df, is_amo=False):
    """DataFrame-based order placement (called by admin test order endpoint)."""
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'UPSTOX user')} via UPSTOX...")

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
            order_label = "AMO" if is_amo else "Order"
            print(f"→ {order_label} placed: {symbol} × {user_qty} | Order ID: {order_id}")
        except Exception as err:
            print(f"❌ Order failed for {symbol}: {err}")


# ---------------------------------------------------------------------------
# Holdings & funds
# ---------------------------------------------------------------------------

def get_holdings(client):
    """
    Fetch current holdings for Upstox client.

    Returns:
        list: holdings list or []
    """
    def _try(fresh=False):
        api_client = _get_api_client(client, force_new=fresh)
        portfolio_api = upstox_client.PortfolioApi(api_client)
        response = portfolio_api.get_holdings(api_version='2.0')
        return response

    try:
        resp = _try(fresh=False)
    except Exception as e:
        if _is_auth_error(e):
            logging.warning(f"Upstox holdings: auth error for {client.get('customer_id')}, refreshing token")
            _invalidate_session(client)
            try:
                resp = _try(fresh=True)
            except Exception as e2:
                logging.error(f"Upstox holdings fetch failed for {client.get('customer_id')}: {e2}")
                return []
        else:
            logging.error(f"Upstox holdings fetch failed for {client.get('customer_id')}: {e}")
            return []

    if resp and hasattr(resp, 'data') and resp.data:
        return resp.data if isinstance(resp.data, list) else []
    return []


def get_available_funds(client):
    """
    Fetch available cash balance for Upstox client.
    Auto-refreshes token on auth failure and retries once.

    Returns:
        float: available cash in INR
    """
    def _try(fresh=False):
        api_client = _get_api_client(client, force_new=fresh)
        user_api = upstox_client.UserApi(api_client)
        return user_api.get_user_fund_margin(api_version='2.0')

    try:
        resp = _try(fresh=False)
    except Exception as e:
        if _is_auth_error(e):
            logging.warning(
                f"Upstox balance: auth error for {client.get('customer_id')}, refreshing token"
            )
            _invalidate_session(client)
            try:
                resp = _try(fresh=True)
            except Exception as e2:
                logging.error(f"Upstox balance fetch failed for {client.get('customer_id')}: {e2}")
                raise
        else:
            logging.error(f"Upstox balance fetch failed for {client.get('customer_id')}: {e}")
            raise

    if resp and hasattr(resp, 'data') and resp.data:
        data = resp.data
        if hasattr(data, 'equity') and data.equity:
            available = getattr(data.equity, 'available_margin', 0.0) or 0.0
            logging.info(f"Upstox balance for {client.get('customer_id')}: ₹{available}")
            return float(available)

    logging.warning(f"Upstox: no fund data available for {client.get('customer_id')}")
    return 0.0
