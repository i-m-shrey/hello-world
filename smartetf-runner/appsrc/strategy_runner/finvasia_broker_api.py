"""
FINVASIA Broker API Wrapper

After SEBI April 1 2026 mandate, Shoonya's PlaceOrder endpoint requires
  app_key = vendor_code
in the jData payload (ALGO_CHK). NorenRestApiPy does NOT include this field,
so all orders were rejected with "ALGO_CHK: Invalid app_key or user_id".

Fix: bypass NorenRestApiPy for PlaceOrder; use pycurl directly with app_key.
After April 2026, Limits also requires Authorization: Bearer {access_token}.
get_available_funds() now uses pycurl directly (same as PlaceOrder) so the
Bearer header is always included.

Session caching: login() is called ONCE per client per script run.
"""
import io
import json
import logging
import re

import threading

import pycurl

from account import Account

logging.getLogger('NorenRestApiPy.NorenApi').setLevel(logging.DEBUG)

# Cache: user_id_broker → {'session': NorenApi, 'susertoken': str,
#                           'vendor_code': str, 'proxy_ip': str}
_session_cache: dict = {}

# Permanent broker-side failures: user_id_broker → error message
# These are errors that re-logging in will NOT fix (e.g. SEBI ALGO_CHK).
# Once set, all subsequent orders for that user_id are skipped immediately.
_PERMANENT_FAILURES: dict = {}
# Thread lock: serialises _session_cache / _PERMANENT_FAILURES writes and
# guards the login path so concurrent logins for the same user_id don't race.
_lock = threading.Lock()


def _is_permanent_broker_error(error_str: str) -> bool:
    """Return True for errors that are permanent broker-side rejections.
    Re-logging in will NOT resolve these — avoid wasting time on it."""
    lower = (error_str or '').lower()
    permanent_patterns = [
        'algo_chk',          # SEBI ALGO_CHK: Invalid app_key or user_id
        'invalid app_key',
        'user blocked',      # Finvasia account locked — re-login will not help
        'blocked due to',
        'multiple wrong',
    ]
    return any(p in lower for p in permanent_patterns)


def _get_or_create_session(client):
    """Return cached session info for this client, or login and cache a new one.
    Thread-safe: concurrent calls for different user_ids login in parallel;
    calls for the same user_id are deduplicated via double-checked locking.
    """
    user_id = client['user_id_broker']

    # Fast path — session already cached (GIL protects the dict read)
    with _lock:
        if user_id in _session_cache:
            logging.info(f"[FINVASIA] Reusing cached session for {user_id}")
            return _session_cache[user_id]

    # Slow path — login required.
    # proxy_url is passed explicitly so Account.login() does NOT read env vars,
    # making concurrent logins for different clients fully thread-safe.
    logging.info(f"[FINVASIA] Logging in for {user_id} (first order of this run)...")
    print(f"  🔑 FINVASIA login for {user_id}...")

    account = Account(
        user_id=user_id,
        password=client['password'],
        totp_secret=client['totp_secret'],
        vendor_code=client['vendor_code'],
        api_secret=client['api_secret'],
        imei=client.get('imei'),
        proxy_url=client.get('proxy_ip', ''),  # explicit proxy — no env-var dependency
        is_master=False,
        multiplier=1,
        copy=True,
    )
    try:
        account.login()
    except TypeError:
        # Older account.py version without proxy_url param — falls back to env vars
        account2 = Account(
            user_id=user_id,
            password=client['password'],
            totp_secret=client['totp_secret'],
            vendor_code=client['vendor_code'],
            api_secret=client['api_secret'],
            imei=client.get('imei'),
            is_master=False,
            multiplier=1,
            copy=True,
        )
        account2.login()
        account = account2

    if not account.session or not hasattr(account.session, 'place_order'):
        raise Exception(f"FINVASIA login failed for {user_id}")

    info = {
        'session':      account.session,
        'susertoken':   account.susertoken,
        'access_token': account.access_token,   # OAuth token from GenAcsTok (required for PlaceOrder)
        'vendor_code':  client['vendor_code'],
        'proxy_ip':     client.get('proxy_ip', ''),
    }
    with _lock:
        _session_cache[user_id] = info
    print(f"  ✅ FINVASIA login successful for {user_id} — session cached")
    return info


def _clear_session(client):
    """Remove cached session so next call triggers a fresh login."""
    user_id = client.get('user_id_broker', '')
    with _lock:
        _session_cache.pop(user_id, None)
    logging.info(f"[FINVASIA] Session cache cleared for {user_id}")

def _get_ltp_pycurl(susertoken, userid, tradingsymbol, proxy_url, access_token=None):
    """
    Fetch LTP for a symbol via SearchScrip+GetQuotes.
    Returns float LTP, or None on failure.
    """
    try:
        # Step 1: SearchScrip to get token
        stext = tradingsymbol.replace('-EQ', '')
        search_payload = "jData=" + json.dumps({"uid": userid, "stext": stext, "exch": "NSE"}) + f"&jKey={susertoken}"
        headers = ["Content-Type: application/x-www-form-urlencoded"]
        if access_token and access_token != susertoken:
            headers.append(f"Authorization: Bearer {access_token}")

        buf = io.BytesIO()
        c = pycurl.Curl()
        try:
            c.setopt(pycurl.URL, "https://trade.shoonya.com/NorenWClientAPI/SearchScrip")
            c.setopt(pycurl.POST, 1)
            c.setopt(pycurl.POSTFIELDS, search_payload)
            c.setopt(pycurl.HTTPHEADER, headers)
            c.setopt(pycurl.WRITEDATA, buf)
            c.setopt(pycurl.TIMEOUT, 15)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
            if proxy_url:
                m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
                if m:
                    c.setopt(pycurl.PROXY, m.group(3))
                    c.setopt(pycurl.PROXYPORT, int(m.group(4)))
                    c.setopt(pycurl.PROXYUSERPWD, f"{m.group(1)}:{m.group(2)}")
            c.perform()
        finally:
            try: c.close()
            except Exception: pass

        search_resp = json.loads(buf.getvalue().decode(errors='replace'))
        token = None
        if search_resp.get('stat') == 'Ok':
            for v in (search_resp.get('values') or []):
                if v.get('tsym', '').upper() == tradingsymbol.upper():
                    token = v.get('token')
                    break
            if not token and search_resp.get('values'):
                token = search_resp['values'][0].get('token')
        if not token:
            return None

        # Step 2: GetQuotes with token
        q_payload = "jData=" + json.dumps({"uid": userid, "exch": "NSE", "token": token}) + f"&jKey={susertoken}"
        buf2 = io.BytesIO()
        c2 = pycurl.Curl()
        try:
            c2.setopt(pycurl.URL, "https://trade.shoonya.com/NorenWClientAPI/GetQuotes")
            c2.setopt(pycurl.POST, 1)
            c2.setopt(pycurl.POSTFIELDS, q_payload)
            c2.setopt(pycurl.HTTPHEADER, headers)
            c2.setopt(pycurl.WRITEDATA, buf2)
            c2.setopt(pycurl.TIMEOUT, 15)
            c2.setopt(pycurl.SSL_VERIFYPEER, 0)
            if proxy_url:
                m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
                if m:
                    c2.setopt(pycurl.PROXY, m.group(3))
                    c2.setopt(pycurl.PROXYPORT, int(m.group(4)))
                    c2.setopt(pycurl.PROXYUSERPWD, f"{m.group(1)}:{m.group(2)}")
            c2.perform()
        finally:
            try: c2.close()
            except Exception: pass

        q_resp = json.loads(buf2.getvalue().decode(errors='replace'))
        lp = q_resp.get('lp') or q_resp.get('c')  # LTP or close price
        if lp:
            return float(lp)
    except Exception as ex:
        logging.warning(f"[FINVASIA] LTP fetch failed for {tradingsymbol}: {ex}")
    return None


def _place_order_pycurl(susertoken, userid, vendor_code, tradingsymbol,
                        qty, buy_or_sell, is_amo, proxy_url, access_token=None, ltp=None):
    """
    Place a single order via pycurl with app_key included (SEBI ALGO_CHK).
    Per April 2026 OAuth doc: access_token must be sent as Bearer in Authorization header.
    Returns norenordno (order ID string) or raises Exception.

    ltp: pre-fetched LTP from the ETF CSV (avoids a second broker API round-trip).
         If None or 0, falls back to _get_ltp_pycurl (live broker fetch).
    """
    # Use CSV LTP if provided — avoids a broker API call and works when market
    # is closed (GetQuotes returns 0/empty but ETF CSV has the last traded price).
    if ltp is None or ltp <= 0:
        ltp = _get_ltp_pycurl(susertoken, userid, tradingsymbol, proxy_url, access_token)

    if ltp and ltp > 0:
        # For BUY: price 3% above LTP to ensure fill; for SELL: 3% below
        if buy_or_sell == 'B':
            limit_price = round(ltp * 1.03, 2)
        else:
            limit_price = round(ltp * 0.97, 2)
        prctyp = "LMT"
        prc    = str(limit_price)
        logging.info(f"[FINVASIA] LTP {ltp} → LMT {prctyp} @ {prc} for {tradingsymbol}")
    else:
        # LTP unavailable from both CSV and live broker API.
        # NOTE: do NOT include "ALGO_CHK" in this message — that text triggers
        # _is_permanent_broker_error() which would mark the entire client as
        # permanently failed. LTP unavailability is transient (market closed,
        # symbol not found) — subsequent symbols for the same client must still run.
        raise Exception(f"LTP unavailable for {tradingsymbol} — cannot determine limit price (market closed or symbol not found)")

    order_dict = {
        "ordersource": "API",
        "uid":         userid,
        "actid":       userid,
        "trantype":    buy_or_sell,
        "prd":         "C",
        "exch":        "NSE",
        "tsym":        tradingsymbol,
        "qty":         str(qty),
        "dscqty":      "0",
        "prctyp":      prctyp,
        "prc":         prc,
        "ret":         "DAY",
        "remarks":     f"Order for {tradingsymbol}",
        "app_key":     vendor_code,   # SEBI ALGO_CHK: must match registered vendor
    }
    # Per official doc: send "amo":"Yes" ONLY for AMO orders; omit entirely otherwise
    if is_amo:
        order_dict["amo"] = "Yes"
    # Per official doc: trgprc only for SL-LMT; omit for MKT

    # April 2026 OAuth: PlaceOrder requires access_token (from GenAcsTok), NOT susertoken.
    _jkey = access_token or susertoken
    payload = "jData=" + json.dumps(order_dict) + f"&jKey={_jkey}"

    # Per official OAuth doc: always send Authorization Bearer header for write ops.
    headers = [
        "Content-Type: application/x-www-form-urlencoded",
        f"Authorization: Bearer {_jkey}",
    ]

    buf = io.BytesIO()
    c = pycurl.Curl()
    try:
        c.setopt(pycurl.URL, "https://trade.shoonya.com/NorenWClientAPI/PlaceOrder")
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.POSTFIELDS, payload)
        c.setopt(pycurl.HTTPHEADER, headers)
        c.setopt(pycurl.WRITEDATA, buf)
        c.setopt(pycurl.TIMEOUT, 30)
        c.setopt(pycurl.SSL_VERIFYPEER, 0)
        if proxy_url:
            m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
            if m:
                c.setopt(pycurl.PROXY,        m.group(3))
                c.setopt(pycurl.PROXYPORT,    int(m.group(4)))
                c.setopt(pycurl.PROXYUSERPWD, f"{m.group(1)}:{m.group(2)}")
        c.perform()
        http_code = c.getinfo(pycurl.HTTP_CODE)
    finally:
        try: c.close()
        except Exception: pass

    body = buf.getvalue().decode('utf-8', errors='replace')
    logging.debug(f"[FINVASIA] PlaceOrder HTTP {http_code}: {body[:300]}")

    try:
        resp = json.loads(body)
    except Exception:
        raise Exception(f"PlaceOrder non-JSON (HTTP {http_code}): {body[:200]}")

    if resp.get('stat') == 'Ok':
        order_id = resp.get('norenordno', resp.get('orderId', 'unknown'))
        logging.info(f"[FINVASIA] Order placed: {tradingsymbol} → {order_id}")
        return order_id
    else:
        raise Exception(f"PlaceOrder failed: {resp.get('emsg', resp)}")


def place_single_order_direct(client, symbol, qty, is_amo=False, side='BUY', ltp=None):
    """Direct order placement — reuses cached session, raises on failure.

    ltp: optional pre-fetched LTP from ETF CSV. Passed straight to
         _place_order_pycurl to avoid a redundant broker API call.
    """
    user_id = client['user_id_broker']

    # If this client hit a permanent broker error earlier this run, skip immediately
    # without any network call — avoids pointless re-login loops.
    with _lock:
        if user_id in _PERMANENT_FAILURES:
            raise Exception(_PERMANENT_FAILURES[user_id])

    info = _get_or_create_session(client)

    tradingsymbol = symbol.strip().upper() + "-EQ"
    buy_or_sell   = "B" if str(side).upper() == 'BUY' else "S"

    try:
        return _place_order_pycurl(
            susertoken=info['susertoken'],
            userid=user_id,
            vendor_code=info['vendor_code'],
            tradingsymbol=tradingsymbol,
            qty=int(qty),
            buy_or_sell=buy_or_sell,
            is_amo=is_amo,
            proxy_url=info['proxy_ip'],
            access_token=info['access_token'],
            ltp=ltp,
        )
    except Exception as e:
        error_str = str(e)
        # Permanent broker-side error — re-login will not help. Mark client failed
        # for this run so all remaining orders are skipped without any network call.
        if _is_permanent_broker_error(error_str):
            logging.warning(
                f"[FINVASIA] Permanent broker error for {user_id} ({error_str}) "
                f"— skipping re-login, all remaining orders for this client will be skipped."
            )
            with _lock:
                _PERMANENT_FAILURES[user_id] = error_str
            raise
        # Transient session error — clear cache, re-login once and retry
        logging.warning(f"[FINVASIA] Order failed ({e}), re-login and retry...")
        _clear_session(client)
        info = _get_or_create_session(client)
        return _place_order_pycurl(
            susertoken=info['susertoken'],
            userid=user_id,
            vendor_code=info['vendor_code'],
            tradingsymbol=tradingsymbol,
            qty=int(qty),
            buy_or_sell=buy_or_sell,
            is_amo=is_amo,
            proxy_url=info['proxy_ip'],
            access_token=info['access_token'],
            ltp=ltp,
        )


def place_order(client, filtered_etfs_df, is_amo=False):
    """Place orders for multiple ETFs (DataFrame-based interface)."""
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'FINVASIA user')} via FINVASIA...")

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
    """Fetch available balance via pycurl with Authorization: Bearer header.

    After April 2026, Finvasia's Limits endpoint also requires the Bearer token.
    Using NorenRestApiPy.get_limits() fails with 'Session Expired' because it
    sends only jKey=susertoken without the Authorization header.
    """
    info         = _get_or_create_session(client)
    userid       = client['user_id_broker']
    proxy_url    = info['proxy_ip']
    access_token = info['access_token']
    susertoken   = info['susertoken']
    _jkey        = access_token or susertoken

    payload = "jData=" + json.dumps({"uid": userid, "actid": userid}) + f"&jKey={_jkey}"
    headers = [
        "Content-Type: application/x-www-form-urlencoded",
        f"Authorization: Bearer {_jkey}",
    ]

    buf = io.BytesIO()
    c   = pycurl.Curl()
    try:
        c.setopt(pycurl.URL, "https://trade.shoonya.com/NorenWClientAPI/Limits")
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.POSTFIELDS, payload)
        c.setopt(pycurl.HTTPHEADER, headers)
        c.setopt(pycurl.WRITEDATA, buf)
        c.setopt(pycurl.TIMEOUT, 20)
        c.setopt(pycurl.SSL_VERIFYPEER, 0)
        if proxy_url:
            import re as _re
            _m = _re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', proxy_url)
            if _m:
                c.setopt(pycurl.PROXY, _m.group(3))
                c.setopt(pycurl.PROXYPORT, int(_m.group(4)))
                c.setopt(pycurl.PROXYUSERPWD, f"{_m.group(1)}:{_m.group(2)}")
        c.perform()
    finally:
        try: c.close()
        except Exception: pass

    resp = json.loads(buf.getvalue().decode(errors='replace'))
    if resp.get('stat') != 'Ok':
        raise Exception(f"Limits failed for {userid}: {resp.get('emsg', resp)}")

    cash   = float(resp.get('cash',   0))
    payin  = float(resp.get('payin',  0))
    payout = float(resp.get('payout', 0))
    return cash + payin - payout
