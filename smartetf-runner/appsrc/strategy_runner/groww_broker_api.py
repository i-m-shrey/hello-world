"""
Groww Broker API Wrapper - TOTP-Type with Daily Auto Token Generation

Credentials stored in broker record:
  - api_key:      Groww API Key (TOTP-type JWT from Groww)
  - totp_secret:  TOTP Secret (base32 string, shown when generating TOTP token)
  - access_token: JWT token (auto-generated daily, cached in memory/DB)

TOKEN GENERATION (TOTP-Type):
  1. Client generates TOTP key ONCE at groww.in/trade-api/api-keys
  2. System generates daily token using: api_key + TOTP code
  3. No daily manual approval needed!

API RESPONSE FORMAT:
  place_order() → dict  (keys include 'groww_order_id')
  get_holdings_for_user() → dict
  get_available_margin_details() → dict (keys include 'available_amount')
"""
import logging
import pyotp
import uuid
import requests
from datetime import datetime, timedelta
from growwapi import GrowwAPI
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPIAuthorisationException,
    GrowwAPIException,
)

# ---------------------------------------------------------------------------
# Session cache  (keyed by broker_id or api_key)
# ---------------------------------------------------------------------------
_SESSION_CACHE = {}
_TOKEN_EXPIRY = {}


def generate_groww_token_daily(api_key: str, totp_secret: str) -> str:
    """
    Generate Groww access token using TOTP.
    Called every morning during health check to get fresh token.

    Uses MINIMAL headers to avoid IP whitelist checks.

    Args:
        api_key: The API Key JWT from Groww (generated once by client)
        totp_secret: The TOTP secret base32 string (generated once by client)

    Returns:
        Access token for the day
    """
    if not api_key or not totp_secret:
        raise ValueError("Groww: Both api_key and totp_secret are required for TOTP-type")

    # Generate current TOTP code
    totp = pyotp.TOTP(totp_secret)
    current_totp = totp.now()

    logging.info(f"[GROWW] Generating token with TOTP: {current_totp}")

    # Use MINIMAL headers - avoid x-client-* headers that trigger IP checks
    url = "https://api.groww.in/v1/token/api/access"
    headers = {
        "x-request-id": str(uuid.uuid4()),
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }
    data = {"key_type": "totp", "totp": current_totp}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)

        if response.status_code == 200:
            result = response.json()
            access_token = result.get("token")
            if access_token:
                logging.info(f"[GROWW] Token generated successfully (length: {len(access_token)})")
                return access_token
            raise ValueError(f"Empty token in response: {result}")

        elif response.status_code == 400:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Bad Request")
            raise Exception(f"Groww 400: {error_msg}. Check credentials or TOTP timing.")

        elif response.status_code == 401:
            raise Exception(
                "Groww 401: Unauthorized. TOTP may have expired (30s window). "
                "Retry with fresh TOTP code."
            )

        else:
            raise Exception(f"Groww API error {response.status_code}: {response.text[:200]}")

    except requests.exceptions.RequestException as e:
        raise Exception(f"Groww API request failed: {e}")


def refresh_groww_token_for_client(client: dict) -> bool:
    """
    Refresh Groww token for a client. Called by morning health check.

    Args:
        client: Client dict with api_key, totp_secret

    Returns:
        True if token refreshed successfully
    """
    cache_key = _get_session_key(client)

    # Clear cache to force regeneration
    _SESSION_CACHE.pop(cache_key, None)
    _TOKEN_EXPIRY.pop(cache_key, None)

    try:
        api_key = client.get('api_key', '').strip()
        totp_secret = client.get('totp_secret', '').strip()

        if not api_key or not totp_secret:
            logging.warning(f"[GROWW] No TOTP credentials for {client.get('customer_id')}, skipping refresh")
            return False

        # Generate new token
        new_token = generate_groww_token_daily(api_key, totp_secret)
        client['access_token'] = new_token
        client['token_generated_at'] = datetime.now().isoformat()

        # Save to DB
        _save_token_to_db(client, new_token)

        logging.info(f"[GROWW] Token refreshed for {client.get('customer_id')}")
        return True

    except Exception as e:
        logging.error(f"[GROWW] Token refresh failed for {client.get('customer_id')}: {e}")
        return False


# Alias for backward compatibility
_refresh_groww_token_if_needed = refresh_groww_token_for_client


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
                logging.info(f"Groww: token saved to DB for broker_id={broker_id}")
    except Exception as e:
        logging.warning(f"Groww: could not save token to DB: {e}")


def _get_session_key(client):
    return client.get('broker_id') or client.get('api_key', 'groww_unknown')


def _generate_fresh_token(client):
    """
    Generate a new Groww access token using TOTP (api_key + totp_secret).
    Returns the token string and saves it to DB + client dict.
    """
    api_key = client.get('api_key', '').strip()
    totp_secret = client.get('totp_secret', '').strip()

    if not api_key:
        raise Exception("Groww: missing api_key for token generation")
    if not totp_secret:
        raise Exception("Groww: missing totp_secret for token generation. "
                       "Generate TOTP-type key at groww.in/trade-api/api-keys")

    logging.info(f"Groww: generating new access token for {client.get('customer_id', 'unknown')}...")

    # Use TOTP method for automatic daily generation
    token = generate_groww_token_daily(api_key, totp_secret)

    if not token or not isinstance(token, str):
        raise Exception(f"Groww: token generation returned unexpected value: {token!r}")

    client['access_token'] = token
    _save_token_to_db(client, token)
    logging.info(f"Groww: token generated successfully for {client.get('customer_id', 'unknown')}")
    return token


def _get_groww(client, force_new=False):
    """
    Return an authenticated GrowwAPI instance.

    Uses cached token from client dict if available. On force_new=True or
    missing token, generates a fresh token via api_key+totp_secret (TOTP method).
    """
    key = _get_session_key(client)

    # Check if we have a valid cached token (less than 12 hours old)
    if not force_new and key in _SESSION_CACHE:
        expiry = _TOKEN_EXPIRY.get(key)
        if expiry and datetime.now() < expiry:
            logging.debug(f"Groww: reusing cached session for {key}")
            return _SESSION_CACHE[key]
        # Token expired, clear cache
        _SESSION_CACHE.pop(key, None)
        _TOKEN_EXPIRY.pop(key, None)

    token = client.get('access_token', '').strip()

    if not token or force_new:
        token = _generate_fresh_token(client)

    groww = GrowwAPI(token)
    _SESSION_CACHE[key] = groww
    _TOKEN_EXPIRY[key] = datetime.now() + timedelta(hours=12)
    return groww


def _invalidate_session(client):
    """Remove cached session and clear token so next call regenerates."""
    key = _get_session_key(client)
    _SESSION_CACHE.pop(key, None)
    _TOKEN_EXPIRY.pop(key, None)
    client['access_token'] = ''


def _is_auth_error(exc):
    """Return True if the exception indicates an auth/token error."""
    if isinstance(exc, (GrowwAPIAuthenticationException, GrowwAPIAuthorisationException)):
        return True
    err = str(exc).lower()
    return any(k in err for k in (
        '401', '403', 'unauthorized', 'authentication', 'token', 'invalid token',
        'session expired', 'access denied'
    ))


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_single_order_direct(client, symbol, qty, is_amo=False, side='BUY'):
    """
    Place a BUY or SELL order for any NSE equity/ETF symbol.
    Auto-refreshes token on auth failure and retries once.

    Args:
        client:  broker credentials dict
        symbol:  NSE trading symbol (e.g. 'NIFTYBEES')
        qty:     quantity (int)
        is_amo:  True for After Market Order (Groww uses VALIDITY_EOS for AMO)
        side:    'BUY' or 'SELL' (default 'BUY')

    Returns:
        str: groww_order_id
    """
    sym = symbol.strip().upper()
    transaction_type = side.strip().upper() if side else 'BUY'
    # Groww uses VALIDITY_EOS for after-market; DAY for intraday/delivery
    validity = 'EOS' if is_amo else 'DAY'

    def _attempt(fresh=False):
        groww = _get_groww(client, force_new=fresh)
        response = groww.place_order(
            trading_symbol=sym,
            quantity=int(qty),
            validity=validity,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            product=groww.PRODUCT_CNC,
            order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=transaction_type,
            price=0.0,
        )
        return response

    # First attempt (cached session)
    response = None
    try:
        response = _attempt(fresh=False)
    except Exception as first_err:
        if not _is_auth_error(first_err):
            raise Exception(f"Groww order failed for {sym}: {first_err}")
        logging.warning(
            f"Groww: auth error placing order for {sym}: {first_err} — refreshing token"
        )
        _invalidate_session(client)
        try:
            response = _attempt(fresh=True)
        except Exception as retry_err:
            raise Exception(f"Groww order failed for {sym} after token refresh: {retry_err}")

    if not isinstance(response, dict):
        raise Exception(f"Groww: unexpected order response type {type(response)}: {response}")

    # Extract order ID — primary key is 'groww_order_id', fallback to 'order_id'
    order_id = (
        response.get('groww_order_id')
        or response.get('order_id')
        or response.get('orderId')
    )
    if not order_id:
        raise Exception(f"Groww: order response missing order_id: {response}")

    logging.info(f"Groww order placed: {sym} × {qty} ({transaction_type}) | Order ID: {order_id}")
    return str(order_id)


def place_order(client, filtered_etfs_df, is_amo=False):
    """DataFrame-based order placement (called by admin test order endpoint)."""
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'GROWW user')} via GROWW...")

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
    Fetch current holdings for Groww client.

    Returns:
        list: holdings list or []
    """
    def _try(fresh=False):
        groww = _get_groww(client, force_new=fresh)
        resp = groww.get_holdings_for_user()
        return resp

    try:
        resp = _try(fresh=False)
    except Exception as e:
        if _is_auth_error(e):
            logging.warning(f"Groww holdings: auth error for {client.get('customer_id')}, refreshing token")
            _invalidate_session(client)
            try:
                resp = _try(fresh=True)
            except Exception as e2:
                logging.error(f"Groww holdings fetch failed for {client.get('customer_id')}: {e2}")
                return []
        else:
            logging.error(f"Groww holdings fetch failed for {client.get('customer_id')}: {e}")
            return []

    if not isinstance(resp, dict):
        return []

    # Holdings payload may be under a 'holdings' key or directly as a list
    holdings_data = resp.get('holdings') or resp.get('data') or []
    if isinstance(holdings_data, list):
        return holdings_data

    logging.debug(f"Groww holdings response keys: {list(resp.keys())}")
    return []


def get_available_funds(client):
    """
    Fetch available cash balance for Groww client.
    Auto-refreshes token on auth failure and retries once.

    Returns:
        float: available cash in INR
    """
    def _try(fresh=False):
        groww = _get_groww(client, force_new=fresh)
        resp = groww.get_available_margin_details()
        return resp

    try:
        resp = _try(fresh=False)
    except Exception as e:
        if _is_auth_error(e):
            logging.warning(
                f"Groww balance: auth error for {client.get('customer_id')}, refreshing token"
            )
            _invalidate_session(client)
            try:
                resp = _try(fresh=True)
            except Exception as e2:
                logging.error(f"Groww balance fetch failed for {client.get('customer_id')}: {e2}")
                raise
        else:
            logging.error(f"Groww balance fetch failed for {client.get('customer_id')}: {e}")
            raise

    if not isinstance(resp, dict):
        raise Exception(f"Groww: unexpected funds response: {resp}")

    # Try multiple likely keys for available balance
    available = (
        resp.get('available_amount')
        or resp.get('availableAmount')
        or resp.get('equity_available')
        or resp.get('net')
        or resp.get('available')
        or 0.0
    )
    try:
        available = float(available)
    except (TypeError, ValueError):
        available = 0.0

    logging.info(f"Groww balance for {client.get('customer_id')}: ₹{available}")
    return available
