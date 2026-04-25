"""
Angel One (SmartAPI) Broker API Wrapper
Requires: pip install smartapi-python pyotp logzero

Credentials stored in broker record:
  - api_key:         SmartAPI API key
  - user_id_broker:  Angel One client ID (e.g. A12345)
  - password:        Login password / PIN
  - totp_secret:     TOTP secret (base32)
  - access_token:    JWT auth token (stored in DB, but SmartConnect obj is
                     cached in-process for reuse)

KEY FINDING: SmartConnect sets internal session state during generateSession()
that cannot be replicated by just setting __access_token on a new instance.
Always use generateSession() — never reuse tokens across SmartConnect objects.

TOKEN RESOLUTION (permanent universal solution):
  Angel One reassigns instrument tokens over time and searchScrip is rate-limited
  / fuzzy. The correct source is OpenAPIScripMaster.json (Angel One's official
  instrument master). It is downloaded once per day and covers every NSE symbol
  automatically — no manual token maintenance needed.

  Resolution order for any symbol:
    1. Per-session in-memory cache (fast path)
    2. Instrument master — exact match  (sym or sym-EQ)
    3. Instrument master — prefix match (e.g. CPSE → CPSEETF-EQ, unambiguous only)
    4. searchScrip API               (rate-limited fallback; retries once on limit)
"""
import json
import logging
import time
import urllib.request
import pyotp

# ---------------------------------------------------------------------------
# Session cache  (keyed by broker_id or user_id_broker)
# ---------------------------------------------------------------------------
_SESSION_CACHE = {}

# ---------------------------------------------------------------------------
# Instrument master  — downloaded from Angel One once per day.
#
# Structure after loading:
#   _INSTRUMENT_MASTER: dict  upper_key → {'token': str, 'tradingsymbol': str}
#   Keys are stored both as "ITBEES-EQ" and "ITBEES" so any lookup style works.
#
# Using the master avoids:
#   • stale hard-coded tokens  (Angel One reassigns tokens; ALL old values wrong)
#   • searchScrip rate limits  (AB4006 cascade, unnecessary session regeneration)
#   • symbol/token mismatches  (AB1019) caused by using wrong tradingsymbol
# ---------------------------------------------------------------------------
_INSTRUMENT_MASTER = None
_INSTRUMENT_MASTER_LOADED_AT = 0.0
_INSTRUMENT_MASTER_TTL = 86400        # refresh once per day (seconds)
_INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Per-session token cache: project_symbol → {'token': str, 'tradingsymbol': str}
# tradingsymbol = the actual Angel One symbol to use in placeOrder params
_ETF_TOKEN_CACHE = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _save_token_to_db(client, token):
    """Persist refreshed JWT token to the Broker DB record (best-effort)."""
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
                logging.info(f"Angel One: token saved to DB for broker_id={broker_id}")
    except Exception as e:
        logging.warning(f"Angel One: could not save token to DB: {e}")


def _get_session_key(client):
    return client.get('broker_id') or client.get('user_id_broker', 'unknown')


def _get_smartconnect(client, force_new=False):
    """
    Return an authenticated SmartConnect instance.

    Always calls generateSession() — either from cache (if valid in this
    process run) or fresh. Setting __access_token manually on a new instance
    fails for most Angel API endpoints (rmsLimit, placeOrder etc.) because
    generateSession() sets additional internal session state beyond just the
    JWT token.
    """
    try:
        from SmartApi import SmartConnect
    except ImportError:
        raise ImportError("smartapi-python not installed. Run: pip install smartapi-python logzero")

    key = _get_session_key(client)

    if not force_new and key in _SESSION_CACHE:
        logging.debug(f"Angel One: reusing cached session for {key}")
        return _SESSION_CACHE[key]

    api_key    = client.get('api_key', '').strip()
    client_id  = client.get('user_id_broker', '').strip()
    password   = client.get('password', '').strip()
    totp_secret = client.get('totp_secret', '').strip()

    if not all([api_key, client_id, password, totp_secret]):
        raise Exception("Missing Angel One credentials: need api_key, user_id_broker, password, totp_secret")

    logging.info(f"Angel One: generating session for {client_id}...")
    obj = SmartConnect(api_key=api_key)
    totp_code = pyotp.TOTP(totp_secret).now()
    data = obj.generateSession(client_id, password, totp_code)

    if not data or data.get('status') is False:
        msg = data.get('message', 'Unknown') if data else 'No response'
        _SESSION_CACHE.pop(key, None)
        raise Exception(f"Angel One login failed: {msg}")

    new_token = data['data']['jwtToken']
    client['access_token'] = new_token
    _SESSION_CACHE[key] = obj
    _save_token_to_db(client, new_token)
    logging.info(f"Angel One: session ready for {client_id}")
    return obj


def _invalidate_session(client):
    """Remove cached session so next call triggers a fresh generateSession."""
    key = _get_session_key(client)
    _SESSION_CACHE.pop(key, None)
    _ETF_TOKEN_CACHE.clear()
    client['access_token'] = ''


def _load_instrument_master(force_refresh=False):
    """
    Download and cache Angel One's instrument master file (NSE symbols only).
    Refreshes automatically once per day (TTL = 86400 s).

    Returns dict: upper_symbol_key → {'token': str, 'tradingsymbol': str}
    Keys stored as both 'ITBEES-EQ' and 'ITBEES' for flexible lookup.

    On download failure returns previously cached data (if any) or empty dict
    so the caller can fall back to searchScrip without crashing.
    """
    global _INSTRUMENT_MASTER, _INSTRUMENT_MASTER_LOADED_AT

    now = time.time()
    if (not force_refresh
            and _INSTRUMENT_MASTER is not None
            and (now - _INSTRUMENT_MASTER_LOADED_AT) < _INSTRUMENT_MASTER_TTL):
        return _INSTRUMENT_MASTER

    try:
        logging.info("Angel One: downloading instrument master file...")
        req = urllib.request.Request(
            _INSTRUMENT_MASTER_URL,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode('utf-8'))

        master = {}
        for item in data:
            if item.get('exch_seg') != 'NSE':
                continue
            raw_sym = item.get('symbol', '').strip().upper()
            tok = str(item.get('token', '')).strip()
            if not raw_sym or not tok:
                continue
            entry = {'token': tok, 'tradingsymbol': raw_sym}
            master[raw_sym] = entry                    # e.g. 'ITBEES-EQ'
            if raw_sym.endswith('-EQ'):
                master[raw_sym[:-3]] = entry           # e.g. 'ITBEES'

        _INSTRUMENT_MASTER = master
        _INSTRUMENT_MASTER_LOADED_AT = now
        logging.info(f"Angel One: instrument master loaded — {len(master)} NSE entries")
        return master

    except Exception as e:
        if _INSTRUMENT_MASTER is not None:
            logging.warning(f"Angel One: master refresh failed ({e}) — using cached version")
            return _INSTRUMENT_MASTER
        logging.warning(f"Angel One: could not load instrument master ({e}) — falling back to searchScrip")
        _INSTRUMENT_MASTER = {}
        return {}


def _is_rate_limited(result):
    """Return True if the response indicates an Angel API rate-limit error."""
    if not isinstance(result, dict):
        return False
    msg = (result.get('message') or result.get('errorcode') or '').lower()
    return 'access denied' in msg or 'exceeding access rate' in msg or 'rate limit' in msg


def _resolve_token(obj, symbol):
    """
    Resolve symboltoken + tradingsymbol for any NSE symbol.

    Returns:
        (token: str, tradingsymbol: str)
        tradingsymbol is the exact Angel One trading symbol to use in placeOrder
        (e.g. 'ITBEES-EQ', 'CPSEETF-EQ' even if the caller passed 'CPSE').

    Resolution order:
      1. Per-session cache              — instant
      2. Instrument master exact match  — no API call, no rate limits
      3. Instrument master prefix match — handles abbreviated project symbols
         (e.g. CPSE → CPSEETF-EQ); only used when match is unambiguous
      4. searchScrip API                — last resort; retries once on rate-limit

    Raises on auth errors so the caller can trigger a session refresh.
    Returns ('0', sym+'-EQ') if the symbol genuinely cannot be resolved.
    """
    sym = symbol.strip().upper()

    # 1. Per-session cache
    if sym in _ETF_TOKEN_CACHE:
        entry = _ETF_TOKEN_CACHE[sym]
        return entry['token'], entry['tradingsymbol']

    # 2 & 3. Instrument master
    master = _load_instrument_master()
    if master:
        # 2. Exact match (covers 'ITBEES', 'ITBEES-EQ', 'MIDCAPETF', etc.)
        entry = master.get(sym)
        if entry:
            _ETF_TOKEN_CACHE[sym] = entry
            logging.info(
                f"Angel resolved token for {sym}: {entry['token']} "
                f"→ {entry['tradingsymbol']} (master exact)"
            )
            return entry['token'], entry['tradingsymbol']

        # 3. Prefix match: find -EQ symbols whose base name starts with sym
        #    e.g. CPSE → CPSEETF-EQ  (one unambiguous match)
        #    Only trust this when exactly one candidate exists.
        prefix_candidates = {
            k: v for k, v in master.items()
            if k.endswith('-EQ') and k[:-3].startswith(sym) and len(k[:-3]) > len(sym)
        }
        if len(prefix_candidates) == 1:
            k, entry = next(iter(prefix_candidates.items()))
            _ETF_TOKEN_CACHE[sym] = entry
            logging.info(
                f"Angel resolved token for {sym}: {entry['token']} "
                f"→ {entry['tradingsymbol']} (master prefix via '{k}')"
            )
            return entry['token'], entry['tradingsymbol']
        elif len(prefix_candidates) > 1:
            logging.warning(
                f"Angel: {sym} is ambiguous in master "
                f"({len(prefix_candidates)} prefix matches: "
                f"{list(prefix_candidates.keys())[:5]}) — using searchScrip"
            )
        else:
            logging.warning(f"Angel: {sym} not found in instrument master — trying searchScrip")

    # 4. searchScrip fallback
    def _search():
        return obj.searchScrip(exchange="NSE", searchscrip=sym)

    try:
        result = _search()

        if result and not result.get('data') and _is_rate_limited(result):
            logging.warning(f"Angel searchScrip rate-limited for {sym} — sleeping 1s and retrying")
            time.sleep(1)
            result = _search()

        if result and result.get('data'):
            first_entry = None
            for item in result['data']:
                ts  = item.get('tradingsymbol', '').strip().upper()
                tok = str(item.get('symboltoken', '0')).strip()
                if not tok or tok == '0':
                    continue
                entry = {'token': tok, 'tradingsymbol': ts}
                if first_entry is None:
                    first_entry = entry
                if ts == sym or ts == sym + '-EQ':
                    _ETF_TOKEN_CACHE[sym] = entry
                    logging.info(f"Angel resolved token for {sym}: {tok} → {ts} (searchScrip exact)")
                    return tok, ts
            if first_entry:
                _ETF_TOKEN_CACHE[sym] = first_entry
                logging.info(
                    f"Angel resolved token for {sym}: {first_entry['token']} "
                    f"→ {first_entry['tradingsymbol']} (searchScrip first result)"
                )
                return first_entry['token'], first_entry['tradingsymbol']

    except KeyError as e:
        key_str = str(e).strip("'")
        if key_str in ('status', 'data', 'message'):
            raise Exception(f"Angel One token auth error during searchScrip for {sym}")
        logging.warning(f"Angel token lookup KeyError for {sym}: {e}")
    except Exception as e:
        logging.warning(f"Angel token lookup failed for {sym}: {e}")

    logging.warning(f"Angel: no symboltoken found for {sym}")
    return '0', sym + '-EQ'


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_single_order_direct(client, symbol, qty, is_amo=False, side='BUY'):
    """
    Place a BUY or SELL order for any NSE symbol. Auto-refreshes session on
    failure and retries once.

    Args:
        client:  broker credentials dict
        symbol:  NSE trading symbol as used in the strategy (e.g. 'NIFTYBEES')
        qty:     quantity (int)
        is_amo:  True for After Market Order
        side:    'BUY' or 'SELL' (default 'BUY')

    Returns:
        str: Angel One order_id
    """
    sym              = symbol.strip().upper()
    variety          = "AMO" if is_amo else "NORMAL"
    transaction_type = side.strip().upper() if side else 'BUY'

    def _attempt(fresh=False):
        obj = _get_smartconnect(client, force_new=fresh)
        tok, trading_sym = _resolve_token(obj, sym)

        if tok == '0':
            raise Exception(
                f"Angel One: symboltoken not resolved for {sym} — "
                "symbol not found on NSE. Verify the symbol name."
            )

        params = {
            "variety":         variety,
            "tradingsymbol":   trading_sym,   # exact Angel One symbol (e.g. CPSEETF-EQ)
            "symboltoken":     tok,
            "transactiontype": transaction_type,
            "exchange":        "NSE",
            "ordertype":       "MARKET",
            "producttype":     "DELIVERY",
            "duration":        "DAY",
            "quantity":        int(qty),
            "price":           "0",
            "squareoff":       "0",
            "stoploss":        "0",
        }
        logging.info(
            f"Angel One order: {transaction_type} {trading_sym} × {qty} "
            f"(token={tok}, AMO={is_amo})"
        )
        return obj.placeOrder(params)

    # First attempt (cached session)
    response = None
    try:
        response = _attempt(fresh=False)
    except Exception as first_err:
        err_str = str(first_err)
        # Symbol-not-found is not an auth error — session regen won't help
        if 'symboltoken not resolved' in err_str or 'AB4006' in err_str:
            raise Exception(f"Angel One order failed for {sym}: {first_err}")
        logging.warning(
            f"Angel One: first attempt exception for {sym}: {first_err} — refreshing session"
        )
        _invalidate_session(client)
        try:
            response = _attempt(fresh=True)
        except Exception as retry_err:
            raise Exception(f"Angel One order failed for {sym} after session refresh: {retry_err}")

    # placeOrder returns None when API rejects (e.g. AG8001 expired token)
    if response is None:
        logging.warning(
            f"Angel One: placeOrder returned None for {sym} — refreshing session and retrying"
        )
        _invalidate_session(client)
        try:
            response = _attempt(fresh=True)
        except Exception as retry_err:
            raise Exception(f"Angel One order failed for {sym} after session refresh: {retry_err}")

    # SmartConnect.placeOrder() returns the order ID as a plain string on success
    if isinstance(response, str) and response:
        logging.info(f"Angel One order placed: {sym} × {qty} | Order ID: {response}")
        return response

    # Some library versions return a dict: {'status': True, 'data': {'orderid': '...'}}
    if isinstance(response, dict) and response.get('status') is not False:
        data = response.get('data') or {}
        order_id = (data.get('orderid') if isinstance(data, dict) else None) or str(response)
        logging.info(f"Angel One order placed: {sym} × {qty} | Order ID: {order_id}")
        return order_id

    msg = response.get('message', 'Unknown error') if isinstance(response, dict) else 'No response'
    raise Exception(f"Angel One order failed for {sym}: {msg}")


def place_order(client, filtered_etfs_df, is_amo=False):
    """DataFrame-based order placement (called by admin test order endpoint)."""
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'ANGEL user')} via ANGEL ONE...")

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


# ---------------------------------------------------------------------------
# Holdings & funds
# ---------------------------------------------------------------------------

def get_holdings(client):
    """
    Fetch current holdings for Angel One client.

    Returns:
        list: holdings list or []
    """
    try:
        obj = _get_smartconnect(client)
        resp = obj.holding()
        if resp and resp.get('data'):
            return resp['data']
        if resp is None or not resp.get('status'):
            logging.warning("Angel One holdings: invalid response, refreshing session")
            _invalidate_session(client)
            obj = _get_smartconnect(client, force_new=True)
            resp = obj.holding()
            if resp and resp.get('data'):
                return resp['data']
        return []
    except Exception as e:
        logging.error(f"Angel One holdings fetch failed for {client.get('customer_id')}: {e}")
        return []


def get_available_funds(client):
    """
    Fetch available cash balance for Angel One client.
    Auto-refreshes session on token error and retries once.

    Returns:
        float: available cash in INR
    """
    def _try_rms(obj):
        rms = obj.rmsLimit()
        if rms and isinstance(rms.get('data'), dict) and 'availablecash' in rms['data']:
            available = float(rms['data']['availablecash'])
            logging.info(f"Angel One balance for {client.get('customer_id')}: ₹{available}")
            return available
        return None

    try:
        obj = _get_smartconnect(client)
        result = _try_rms(obj)
        if result is not None:
            return result

        logging.warning(
            f"Angel One: rmsLimit failed for {client.get('customer_id')}, refreshing session"
        )
        _invalidate_session(client)
        obj = _get_smartconnect(client, force_new=True)
        result = _try_rms(obj)
        if result is not None:
            return result

        raise Exception("rmsLimit returned no valid data after session refresh")

    except Exception as e:
        logging.error(f"Angel One balance fetch failed for {client.get('customer_id')}: {e}")
        raise
