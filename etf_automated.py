from notify_admin import notify_admin
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import pandas as pd
import datetime
from datetime import datetime as dt, timedelta
from fetch_etf_data import fetch_etf_data, fetch_etf_csv_direct, fetch_etf_csv_from_json
from filter_etfs import calculate_quantities
from broker_dispatcher import get_executor_for_broker
from client_fetcher import get_active_clients_with_sip
from app import app, Broker, Subscription, Plan, User, ClientPreferences, ClientStrategy, db
from models import ExecutionRun, OrderEvent, MonthlyInvestment, SchedulerSettings
from etf_categorizer import get_etf_category
from order_executor_generic import GenericOrderExecutor
from collections import defaultdict
import zipfile
import json
import logging
import traceback
from app_utils.shoonya_password_util import change_password_for_client  # used by finvasia_password_utils (kept for compatibility)
from proxy_utils import client_proxy_context, get_client_proxy
import threading
import concurrent.futures

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = f"{log_dir}/order_execution_{dt.now().strftime('%Y%m%d')}.log"
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

logging.info(f"Logs will be saved to: {log_file}")

def _get_preferences_map():
    prefs = {}
    try:
        rows = (
            db.session.query(ClientPreferences, User.customer_id)
            .join(User, ClientPreferences.user_id == User.id)
            .all()
        )
        for pref, customer_id in rows:
            prefs[customer_id] = {
                'excluded_etfs': pref.excluded_etfs or [],
                'excluded_sectors': pref.excluded_sectors or []
            }
    except Exception as e:
        logging.warning(f"Failed to load client preferences: {e}")
    return prefs


def _apply_exclusions(df, excluded_etfs, excluded_sectors):
    if df is None or df.empty:
        return df
    result = df.copy()
    if excluded_etfs:
        result = result[~result['SYMBOL'].isin(excluded_etfs)]
    if excluded_sectors:
        if 'CATEGORY' not in result.columns:
            try:
                if 'UNDERLYING_ASSET' not in result.columns:
                    result['UNDERLYING_ASSET'] = ''
                result['CATEGORY'] = result.apply(
                    lambda row: get_etf_category(row['SYMBOL'], row.get('UNDERLYING_ASSET', '')),
                    axis=1
                )
            except Exception:
                return result
        result = result[~result['CATEGORY'].isin(excluded_sectors)]
    return result


def _get_strategy_map():
    strategies = {}
    try:
        rows = ClientStrategy.query.all()
        for s in rows:
            strategies[s.broker_id] = s
    except Exception as e:
        logging.warning(f"Failed to load client strategies: {e}")
    return strategies


def _normalize_etf_snapshot(df):
    if df is None or df.empty:
        return {}
    snap = df.copy()
    snap.columns = snap.columns.str.strip().str.upper()
    if 'SYMBOL' not in snap.columns:
        return {}
    if 'LTP' not in snap.columns and 'CLOSE' in snap.columns:
        snap['LTP'] = snap['CLOSE']
    snap['SYMBOL'] = snap['SYMBOL'].astype(str).str.strip().str.upper()
    if 'LTP' in snap.columns:
        snap['LTP'] = pd.to_numeric(snap['LTP'], errors='coerce').fillna(0)
    if '%CHNG' in snap.columns:
        snap['%CHNG'] = pd.to_numeric(snap['%CHNG'], errors='coerce').fillna(0)
    return {row['SYMBOL']: {'ltp': row.get('LTP', 0), 'chng': row.get('%CHNG', 0)} for _, row in snap.iterrows()}


def _strategy_state_path(broker_id):
    base = os.path.join('data', 'custom_strategy')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"state_{broker_id}.json")


def _strategy_positions_path(broker_id):
    base = os.path.join('data', 'custom_strategy')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"positions_{broker_id}.csv")


def _load_strategy_state(broker_id):
    path = _strategy_state_path(broker_id)
    if not os.path.isfile(path):
        return {'liquid_qty': 0}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'liquid_qty': 0}


def _save_strategy_state(broker_id, state):
    path = _strategy_state_path(broker_id)
    with open(path, 'w') as f:
        json.dump(state, f)


def _load_positions(broker_id):
    path = _strategy_positions_path(broker_id)
    if not os.path.isfile(path):
        return pd.DataFrame(columns=['symbol', 'qty', 'entry_price'])
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=['symbol', 'qty', 'entry_price'])


def _save_positions(broker_id, df):
    path = _strategy_positions_path(broker_id)
    df.to_csv(path, index=False)


def _get_available_funds(client, broker_api_module):
    try:
        if hasattr(broker_api_module, 'get_available_funds'):
            return float(broker_api_module.get_available_funds(client) or 0)
    except Exception:
        pass
    try:
        broker = db.session.get(Broker, client.get('broker_id'))
        if broker and broker.available_balance is not None:
            return float(broker.available_balance)
    except Exception:
        pass
    return 0.0


def _parse_holdings(holdings, liquid_symbol):
    positions = []
    liquid_qty = 0.0
    for h in holdings or []:
        sym = (h.get('tradingsymbol') or h.get('symbol') or h.get('trading_symbol') or '').split('-')[0].strip().upper()
        qty = h.get('quantity') or h.get('qty') or h.get('holding_quantity') or h.get('net_quantity') or 0
        avg = h.get('average_price') or h.get('avg_price') or h.get('buy_price') or 0
        try:
            qty = float(qty)
            avg = float(avg)
        except Exception:
            qty = 0
            avg = 0
        if not sym or qty <= 0:
            continue
        if sym == liquid_symbol:
            liquid_qty += qty
        else:
            positions.append({'symbol': sym, 'qty': qty, 'entry_price': avg})
    return pd.DataFrame(positions), liquid_qty


def _net_profit_pct(buy_price, sell_price, qty):
    turnover = (buy_price + sell_price) * qty
    stt = sell_price * qty * 0.001
    exchange = turnover * 0.0000325
    sebi = turnover * 0.000001
    stamp = buy_price * qty * 0.00015
    gst = 0.18 * (exchange + sebi)
    charges = stt + exchange + sebi + stamp + gst
    net = (sell_price - buy_price) * qty - charges
    cost = buy_price * qty
    if cost <= 0:
        return 0
    return net / cost


def _pick_worst_fall(universe, snapshot):
    worst = None
    worst_chng = None
    for symbol in universe:
        data = snapshot.get(symbol)
        if not data:
            continue
        chng = data.get('chng', 0)
        if worst is None or chng < worst_chng:
            worst = symbol
            worst_chng = chng
    return worst


def _place_order_with_side(broker_api_module, client, symbol, qty, side):
    if qty <= 0:
        return None
    if hasattr(broker_api_module, 'place_single_order_direct'):
        return broker_api_module.place_single_order_direct(client, symbol, qty, side=side)
    raise Exception("place_single_order_direct not available")


def _run_custom_strategy(client, broker_api_module, strategy, etf_snapshot):
    broker_id = client.get('broker_id')
    universe = [str(s).strip().upper() for s in (strategy.universe or []) if str(s).strip()]
    if not universe:
        return {'status': 'skipped', 'reason': 'universe_empty'}
    liquid_symbol = (strategy.liquid_symbol or 'LIQUIDBEES').strip().upper()
    parts = max(1, int(strategy.parts or 40))
    profit_target = float(strategy.profit_target or 0.03)

    state = _load_strategy_state(broker_id)
    positions = _load_positions(broker_id)

    try:
        if hasattr(broker_api_module, 'get_holdings'):
            holdings = broker_api_module.get_holdings(client)
            positions, liquid_qty_h = _parse_holdings(holdings, liquid_symbol)
            state['liquid_qty'] = liquid_qty_h
    except Exception:
        pass

    liquid_data = etf_snapshot.get(liquid_symbol, {})
    liquid_ltp = float(liquid_data.get('ltp', 0))

    available_funds = _get_available_funds(client, broker_api_module)

    if not strategy.initialized_liquid and liquid_ltp > 0:
        buy_qty = int(available_funds / liquid_ltp)
        if buy_qty > 0:
            _place_order_with_side(broker_api_module, client, liquid_symbol, buy_qty, 'BUY')
            state['liquid_qty'] = float(state.get('liquid_qty', 0)) + buy_qty
            strategy.initialized_liquid = True
            strategy.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            _save_strategy_state(broker_id, state)
        return {'status': 'initialized'}

    if liquid_ltp <= 0:
        return {'status': 'skipped', 'reason': 'liquid_price_missing'}

    liquid_qty = float(state.get('liquid_qty', 0))
    liquid_value = liquid_qty * liquid_ltp

    position_value = 0
    for _, row in positions.iterrows():
        symbol = str(row['symbol']).upper()
        qty = float(row['qty'])
        ltp = float(etf_snapshot.get(symbol, {}).get('ltp', 0))
        position_value += qty * ltp

    total_capital = available_funds + liquid_value + position_value
    allocation = total_capital / parts if parts else 0
    if allocation <= 0:
        return {'status': 'skipped', 'reason': 'allocation_zero'}

    worst_symbol = _pick_worst_fall(universe, etf_snapshot)
    if not worst_symbol:
        return {'status': 'skipped', 'reason': 'no_symbol_found'}

    worst_ltp = float(etf_snapshot.get(worst_symbol, {}).get('ltp', 0))
    if worst_ltp <= 0:
        return {'status': 'skipped', 'reason': 'price_missing'}

    if available_funds < allocation and liquid_qty > 0:
        needed = allocation - available_funds
        sell_qty = int(needed / liquid_ltp) + 1
        sell_qty = min(sell_qty, int(liquid_qty))
        if sell_qty > 0:
            _place_order_with_side(broker_api_module, client, liquid_symbol, sell_qty, 'SELL')
            liquid_qty -= sell_qty
            available_funds += sell_qty * liquid_ltp
            state['liquid_qty'] = liquid_qty
            _save_strategy_state(broker_id, state)

    buy_qty = int(allocation / worst_ltp)
    if buy_qty <= 0:
        return {'status': 'skipped', 'reason': 'qty_zero'}

    _place_order_with_side(broker_api_module, client, worst_symbol, buy_qty, 'BUY')

    if positions.empty:
        positions = pd.DataFrame([{'symbol': worst_symbol, 'qty': buy_qty, 'entry_price': worst_ltp}])
    else:
        existing = positions[positions['symbol'].str.upper() == worst_symbol]
        if existing.empty:
            positions = pd.concat([positions, pd.DataFrame([{'symbol': worst_symbol, 'qty': buy_qty, 'entry_price': worst_ltp}])], ignore_index=True)
        else:
            idx = existing.index[0]
            prev_qty = float(positions.at[idx, 'qty'])
            prev_price = float(positions.at[idx, 'entry_price'])
            new_qty = prev_qty + buy_qty
            new_price = ((prev_qty * prev_price) + (buy_qty * worst_ltp)) / new_qty
            positions.at[idx, 'qty'] = new_qty
            positions.at[idx, 'entry_price'] = new_price

    exits = []
    remaining = []
    for _, row in positions.iterrows():
        symbol = str(row['symbol']).upper()
        qty = float(row['qty'])
        entry = float(row['entry_price'])
        ltp = float(etf_snapshot.get(symbol, {}).get('ltp', 0))
        if qty <= 0 or ltp <= 0:
            continue
        if _net_profit_pct(entry, ltp, qty) >= profit_target:
            _place_order_with_side(broker_api_module, client, symbol, int(qty), 'SELL')
            proceeds = qty * ltp
            buy_liquid_qty = int(proceeds / liquid_ltp)
            if buy_liquid_qty > 0:
                _place_order_with_side(broker_api_module, client, liquid_symbol, buy_liquid_qty, 'BUY')
                liquid_qty += buy_liquid_qty
            exits.append(symbol)
        else:
            remaining.append({'symbol': symbol, 'qty': qty, 'entry_price': entry})

    state['liquid_qty'] = liquid_qty
    _save_strategy_state(broker_id, state)
    _save_positions(broker_id, pd.DataFrame(remaining))

    return {'status': 'ok', 'bought': worst_symbol, 'exited': exits}


MAX_RETRIES = 3
RETRY_DELAY = 5

# User-configurable run mode: set to 'browser' to see Chrome, or 'headless' to run without UI
RUN_MODE = os.getenv('RUN_MODE', 'headless').lower()
# Multiplier is based on SIP monthly vs baseline (no remaining-based logic)
USE_MULTIPLIER = True
BASE_MONTHLY = float(os.getenv('BASE_MONTHLY', '8000'))  # 1x at ₹8,000 baseline
MULTIPLIER_MIN = float(os.getenv('MULTIPLIER_MIN', '0.5'))
MULTIPLIER_MAX = float(os.getenv('MULTIPLIER_MAX', '10.0'))
FINVASIA_PASSWORD_RESET_ON_ORDER = True
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com').strip() or 'smartetfalgo@gmail.com'
ETF_FETCH_STRATEGY_ORDER = "direct,json,selenium"

def fetch_etf_csv_with_strategy_order():
    order = [s.strip().lower() for s in ETF_FETCH_STRATEGY_ORDER.split(',') if s.strip()]
    strategies = {
        'direct': fetch_etf_csv_direct,
        'json': fetch_etf_csv_from_json,
        'selenium': fetch_etf_data,
    }
    for name in order:
        fn = strategies.get(name)
        if not fn:
            continue
        try:
            result = fn()
        except Exception as e:
            logging.warning(f"ETF fetch strategy {name} failed: {e}")
            continue
        if result:
            logging.info(f"ETF fetch strategy succeeded: {name}")
            return result
    return None


def _is_password_error(error_message: str) -> bool:
    msg = (error_message or '').lower()
    # Exclude broker/session errors that are NOT password problems.
    # Only trigger rotation for genuine Finvasia password-expiry errors.
    non_password = (
        'algo_chk',           # SEBI API config issue
        'session expired',    # session timeout — not a password issue
        'invalid session',    # session timeout
        'session key',        # session timeout
        'ltp unavailable',    # LTP fetch failure
        'mkt order',          # order type rejection
        'token refresh',      # token refresh failure
    )
    if any(x in msg for x in non_password):
        return False
    # Only match actual password-expiry keywords
    keywords = ("password", "pwd expired", "credentials expired")
    return any(k in msg for k in keywords)


def _rotate_finvasia_password(client: dict, error_message: str) -> dict:
    """Delegate to shared finvasia_password_utils — single source of truth."""
    from finvasia_password_utils import rotate_finvasia_password
    return rotate_finvasia_password(
        client,
        error_message=error_message,
        notify_client=True,
        debug=DEBUG,
    )


FILTER_BROKERS = []
# FILTER_BROKERS = ['DHAN']
FILTER_CUSTOMERS = []

# ── DEBUG mode ─────────────────────────────────────────────────────────────
# Set True for interactive per-client confirmation before any orders are placed.
# DEBUG=True forces sequential execution (max_workers=1) so prompts are readable.
DEBUG = False

# ── BLOCKED_BROKER_IDS ─────────────────────────────────────────────────
# Add any user_id_broker here to permanently skip that client from ALL
# order placement and health check sessions.
# Example: frozenset({'FN148473', 'FA55537'})
BLOCKED_BROKER_IDS: frozenset = frozenset()
# FILTER_CUSTOMERS = ['smartetf_user_10001', 'smartetf_user_10007']

# Broker user IDs that are permanently blocked from order placement.
# These accounts have an unresolvable API-config issue (e.g. ALGO_CHK: wrong
# vendor_code / app_key) that re-login cannot fix. Listing them here prevents
# any login attempt and avoids filling logs with guaranteed failures.
# Add / remove broker-level user_id_broker strings (not customer_ids) here.

MAX_PRICE_TOLERANCE_PERCENT = 40.0

# Brokers whose order placement uses pycurl with proxy set per curl handle —
# fully thread-safe, no env-var proxy needed during order execution.
_PYCURL_PROXY_BROKERS = frozenset({'FINVASIA'})
# Serialises HTTP_PROXY / HTTPS_PROXY env-var swaps for requests-based brokers
# so concurrent threads don't overwrite each other's proxy setting.
_ENV_PROXY_LOCK = threading.Lock()


def create_monthly_tracking_folder():
    """Create folder for monthly tracking CSV files"""
    current_month = dt.now().strftime('%Y-%m')
    folder_path = f"monthly_tracking/{current_month}"
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def read_monthly_invested(customer_id, current_month=None):
    """Read month-to-date invested amount; prefer DB, fallback to CSV"""
    if not current_month:
        current_month = dt.now().strftime('%Y-%m')

    if os.getenv('ENABLE_MONTHLY_DB', '0').lower() in ('1', 'true', 'yes'):
        try:
            with app.app_context():
                total = db.session.query(db.func.coalesce(db.func.sum(MonthlyInvestment.invested_amount), 0.0)) \
                    .filter(MonthlyInvestment.customer_id == customer_id, MonthlyInvestment.month == current_month) \
                    .scalar()
                if total is not None:
                    return float(total)
        except Exception as e:
            logging.warning(f"MonthlyInvestment DB read failed for {customer_id}: {e}")

    folder_path = f"monthly_tracking/{current_month}"
    tracking_file = f"{folder_path}/{customer_id}_monthly.csv"

    if not os.path.exists(tracking_file):
        return 0.0

    try:
        df = pd.read_csv(tracking_file)
        return df['invested_amount'].sum()
    except Exception as e:
        logging.warning(f"Error reading monthly tracking for {customer_id}: {e}")
        return 0.0


def update_monthly_invested(customer_id, investment_amount, etf_details=None):
    """Update monthly invested amount for a customer (DB + CSV audit)"""
    current_month = dt.now().strftime('%Y-%m')
    folder_path = create_monthly_tracking_folder()
    tracking_file = f"{folder_path}/{customer_id}_monthly.csv"

    if os.getenv('ENABLE_MONTHLY_DB', '0').lower() in ('1', 'true', 'yes'):
        try:
            with app.app_context():
                db.session.add(MonthlyInvestment(
                    customer_id=customer_id,
                    day=dt.now().date(),
                    month=current_month,
                    invested_amount=float(investment_amount or 0),
                    etf_details_json=etf_details or []
                ))
                db.session.commit()
        except Exception as e:
            logging.warning(f"MonthlyInvestment DB insert failed for {customer_id}: {e}")

    new_record = {
        'date': dt.now().strftime('%Y-%m-%d'),
        'time': dt.now().strftime('%H:%M:%S'),
        'invested_amount': investment_amount,
        'etf_count': len(etf_details) if etf_details else 0,
        'etf_details': json.dumps(etf_details) if etf_details else ''
    }

    try:
        if os.path.exists(tracking_file):
            df = pd.read_csv(tracking_file)
            df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
        else:
            df = pd.DataFrame([new_record])
        df.to_csv(tracking_file, index=False)
        logging.info(f"Updated monthly tracking for {customer_id}: +₹{investment_amount}")
    except Exception as e:
        logging.error(f"Error updating monthly tracking for {customer_id}: {e}")


def calculate_market_condition():
    """Analyze market condition for consecutive falling days"""
    # This is a simplified version - you can enhance with actual market data
    # For now, we'll use ETF data to determine market condition
    try:
        # Check last 5 days of market data (simplified)
        # You can enhance this with actual market indices
        return {
            'consecutive_falling_days': 0,  # Will be enhanced
            'market_severity': 'normal',  # normal, moderate_fall, severe_fall
            'adjustment_factor': 1.0  # Multiplier for aggressive investment
        }
    except Exception as e:
        logging.warning(f"Error calculating market condition: {e}")
        return {'consecutive_falling_days': 0, 'market_severity': 'normal', 'adjustment_factor': 1.0}


def calculate_user_multipliers(filtered_etfs_df):
    """Calculate personalized multipliers for each user based on SIP targets and market conditions"""

    with app.app_context():
        user_multipliers = {}
        market_condition = calculate_market_condition()
        current_month = dt.now().strftime('%Y-%m')

        logging.info(f"Calculating multipliers for {current_month}")
        logging.info(f"Market condition: {market_condition}")

        # Get current (unique) active subscriptions with SIP targets per customer
        now = datetime.datetime.utcnow()
        active_subscriptions = (
            Subscription.query
            .filter(
                Subscription.payment_status.in_(['Active', 'Successful', 'Paid']),
                Subscription.start_date <= now,
                db.func.date(Subscription.expiry_date) >= now.date(),
                Subscription.is_queued.is_(False),
                Subscription.monthly_sip_target.isnot(None),
                Subscription.monthly_sip_target > 0
            ).all()
        )

        # Deduplicate: keep latest-expiring subscription per customer
        subs_by_customer = {}
        for sub in active_subscriptions:
            prev = subs_by_customer.get(sub.customer_id)
            if prev is None or (sub.expiry_date and prev and sub.expiry_date > prev.expiry_date):
                subs_by_customer[sub.customer_id] = sub
        unique_subscriptions = list(subs_by_customer.values())

        logging.info(f"Found {len(unique_subscriptions)} unique customers with SIP targets")

        for subscription in unique_subscriptions:
            try:
                customer_id = subscription.customer_id
                sip_monthly = float(subscription.monthly_sip_target or 0)
                if sip_monthly <= 0:
                    continue
                m = sip_monthly / BASE_MONTHLY if BASE_MONTHLY > 0 else 1.0
                m = max(MULTIPLIER_MIN, m)
                user_multipliers[customer_id] = {
                    'multiplier': round(m, 2),
                    'monthly_target': sip_monthly,
                    'month_invested': None,
                    'remaining_target': None,
                    'market_condition': 'sip_ratio'
                }
                logging.info(f"User {customer_id}: SIP=₹{sip_monthly}, Multiplier={m}")
            except Exception as e:
                logging.error(f"Error calculating multiplier for subscription {subscription.id}: {e}")
                continue

        return user_multipliers


def generate_daily_csvs(filtered_etfs_df, user_multipliers):
    """Generate daily CSV files for ETF orders and user tracking"""

    try:
        timestamp = dt.now().strftime('%Y%m%d_%H%M%S')

        # 1. Generate ETF Orders CSV
        etf_orders = []
        for _, row in filtered_etfs_df.iterrows():
            etf_orders.append({
                'symbol': row['SYMBOL'],
                'ltp': row['LTP'],
                'base_qty': row['QTY'],
                'base_amount': row['FINAL_AMOUNT']
            })

        etf_df = pd.DataFrame(etf_orders)
        etf_csv_path = f"daily_orders/etf_orders_{timestamp}.csv"
        os.makedirs('daily_orders', exist_ok=True)
        etf_df.to_csv(etf_csv_path, index=False)

        # 2. Generate User Tracking CSV
        user_tracking = []
        for customer_id, data in user_multipliers.items():
            # Get user details
            with app.app_context():
                user = User.query.filter_by(customer_id=customer_id).first()
                username = user.username if user else customer_id

            user_tracking.append({
                'customer_id': customer_id,
                'username': username,
                'monthly_target': data['monthly_target'],
                'month_invested': data['month_invested'],
                'remaining_target': data['remaining_target'],
                'multiplier': data['multiplier'],
                'market_condition': data['market_condition'],
                'estimated_investment': sum(
                    row['FINAL_AMOUNT'] * data['multiplier'] for _, row in filtered_etfs_df.iterrows())
            })

        user_df = pd.DataFrame(user_tracking)
        user_csv_path = f"daily_orders/user_tracking_{timestamp}.csv"
        user_df.to_csv(user_csv_path, index=False)

        # 3. Create ZIP file
        zip_path = f"daily_orders/smartetf_orders_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(etf_csv_path, os.path.basename(etf_csv_path))
            zipf.write(user_csv_path, os.path.basename(user_csv_path))

        logging.info(f"Generated daily CSVs and ZIP: {zip_path}")

        return {
            'etf_csv': etf_csv_path,
            'user_csv': user_csv_path,
            'zip_file': zip_path,
            'total_users': len(user_multipliers)
        }

    except Exception as e:
        logging.error(f"Error generating daily CSVs: {e}")
        return None


def _refresh_dhan_token_if_needed(client):
    """Refresh DHAN access token before order execution"""
    try:
        from dhan_oauth import generate_dhan_token

        client_id = client.get('dhan_client_id', '').strip()
        api_key = client.get('api_key', '').strip()
        api_secret = client.get('api_secret', '').strip()
        mobile = client.get('mobile', '').strip()
        pin = client.get('password', '').strip()
        totp_secret = client.get('totp_secret', '').strip()

        if not all([client_id, api_key, api_secret, mobile, pin]):
            logging.warning(
                f"DHAN {client.get('customer_id')}: Missing credentials for token renewal, using existing token")
            return

        logging.info(f"DHAN {client.get('customer_id')}: Refreshing access token...")
        new_token = generate_dhan_token(api_key, api_secret, client_id, mobile, pin, totp_secret)

        client['access_token'] = new_token

        broker_id = client.get('broker_id')
        if broker_id:
            broker = db.session.get(Broker, broker_id)
            if broker:
                broker.access_token = new_token
                broker.last_updated = datetime.datetime.utcnow()
                db.session.commit()
                logging.info(f"DHAN {client.get('customer_id')}: Token refreshed and saved to DB")
    except Exception as e:
        logging.error(f"DHAN token refresh failed for {client.get('customer_id')}: {e}")


def _refresh_zerodha_token_if_needed(client):
    """Refresh ZERODHA access token before order execution"""
    try:
        from zerodha_oauth import generate_zerodha_token

        api_key = client.get('api_key', '').strip()
        api_secret = client.get('api_secret', '').strip()
        user_id = client.get('user_id_broker', '').strip()
        password = client.get('password', '').strip()
        totp_secret = client.get('totp_secret', '').strip()

        if not all([api_key, api_secret, user_id, password, totp_secret]):
            logging.warning(f"ZERODHA {client.get('customer_id')}: Missing credentials for token renewal")
            return

        logging.info(f"ZERODHA {client.get('customer_id')}: Refreshing access token...")
        new_token = generate_zerodha_token(api_key, api_secret, user_id, password, totp_secret)

        client['access_token'] = new_token

        broker_id = client.get('broker_id')
        if broker_id:
            broker = db.session.get(Broker, broker_id)
            if broker:
                broker.access_token = new_token
                broker.last_updated = datetime.datetime.utcnow()
                db.session.commit()
                logging.info(f"ZERODHA {client.get('customer_id')}: Token refreshed and saved to DB")
    except Exception as e:
        logging.error(f"ZERODHA token refresh failed for {client.get('customer_id')}: {e}")


def _refresh_angel_token_if_needed(client):
    """Refresh Angel One access token by re-running generateSession via TOTP"""
    try:
        from angel_oauth import generate_angel_token

        api_key = client.get('api_key', '').strip()
        client_id = client.get('user_id_broker', '').strip()
        password = client.get('password', '').strip()
        totp_secret = client.get('totp_secret', '').strip()

        if not all([api_key, client_id, password, totp_secret]):
            logging.warning(f"ANGEL {client.get('customer_id')}: Missing credentials for token renewal")
            return

        logging.info(f"ANGEL {client.get('customer_id')}: Refreshing access token...")
        result = generate_angel_token(api_key, client_id, password, totp_secret)
        new_token = result['auth_token']

        client['access_token'] = new_token

        broker_id = client.get('broker_id')
        if broker_id:
            broker = db.session.get(Broker, broker_id)
            if broker:
                broker.access_token = new_token
                broker.last_updated = datetime.datetime.utcnow()
                db.session.commit()
                logging.info(f"ANGEL {client.get('customer_id')}: Token refreshed and saved to DB")
    except Exception as e:
        logging.error(f"ANGEL token refresh failed for {client.get('customer_id')}: {e}")


def _refresh_groww_token_if_needed(client):
    """Refresh Groww access token using TOTP (api_key + totp_secret)."""
    try:
        from groww_broker_api import refresh_groww_token_for_client
        logging.info(f"GROWW {client.get('customer_id')}: Refreshing access token via TOTP...")
        success = refresh_groww_token_for_client(client)
        if success:
            logging.info(f"GROWW {client.get('customer_id')}: Token refreshed and saved to DB")
        else:
            logging.warning(f"GROWW {client.get('customer_id')}: Token refresh returned False")
    except Exception as e:
        logging.error(f"GROWW token refresh failed for {client.get('customer_id')}: {e}")


def _refresh_upstox_token_if_needed(client):
    """Refresh Upstox access token via TOTP OAuth2 flow."""
    try:
        from upstox_oauth import generate_upstox_token

        api_key = client.get('api_key', '').strip()
        api_secret = client.get('api_secret', '').strip()
        mobile = client.get('mobile', '').strip()
        password = client.get('password', '').strip()
        totp_secret = client.get('totp_secret', '').strip()

        if not all([api_key, api_secret, mobile, password, totp_secret]):
            logging.warning(f"UPSTOX {client.get('customer_id')}: Missing credentials for token renewal")
            return

        logging.info(f"UPSTOX {client.get('customer_id')}: Refreshing access token...")
        new_token = generate_upstox_token(api_key, api_secret, mobile, password, totp_secret)

        client['access_token'] = new_token

        # Invalidate in-process session cache so next order uses fresh token
        try:
            import upstox_broker_api
            upstox_broker_api._invalidate_session(client)
        except Exception:
            pass

        broker_id = client.get('broker_id')
        if broker_id:
            broker = db.session.get(Broker, broker_id)
            if broker:
                broker.access_token = new_token
                broker.last_updated = datetime.datetime.utcnow()
                db.session.commit()
                logging.info(f"UPSTOX {client.get('customer_id')}: Token refreshed and saved to DB")
    except Exception as e:
        logging.error(f"UPSTOX token refresh failed for {client.get('customer_id')}: {e}")


def _is_token_error(error_message):
    """
    Detect if error is related to token expiration

    Checks for:
    - HTTP 401
    - DHAN error code DH-901
    - Generic token/authentication keywords
    """
    if not error_message:
        return False

    error_lower = str(error_message).lower()

    token_keywords = [
        'invalid_authentication',
        'token is invalid',
        'token expired',
        'authentication failed',
        'session expired',
        'http 401',
        'dh-901',
        'invalid session',
        'session does not exist',
        'unauthorized',
        'invalid access token',
        'ag8001',
        'invalid token',
        'token auth error',
        'token refresh',
    ]

    return any(keyword in error_lower for keyword in token_keywords)


def _apply_smart_fallback(personalized_etfs, full_etf_df, multiplier, customer_id):
    """
    Smart fallback for 0-qty ETFs:
    1. Try to find cheaper alternative in same category with high volume
    2. If no alternative, buy 1 qty if price is within MAX_PRICE_TOLERANCE_PERCENT
    """
    zero_qty = personalized_etfs[personalized_etfs['USER_QTY'] == 0].copy()

    if zero_qty.empty:
        return personalized_etfs

    logging.info(f"[{customer_id}] Found {len(zero_qty)} ETFs with 0 qty, searching for alternatives...")

    for idx, row in zero_qty.iterrows():
        symbol = row['SYMBOL']
        allocated = row['ALLOCATED_AMOUNT'] * multiplier
        current_price = row['LTP']
        category = row.get('CATEGORY')

        if not category:
            tolerance = allocated * (1 + MAX_PRICE_TOLERANCE_PERCENT / 100.0)
            if current_price <= tolerance:
                logging.info(f"  ✅ {symbol}: No category, but within {MAX_PRICE_TOLERANCE_PERCENT}% tolerance → 1 qty")
                personalized_etfs.loc[idx, 'USER_QTY'] = 1
            continue

        same_category = full_etf_df[
            (full_etf_df['CATEGORY'] == category) &
            (full_etf_df['SYMBOL'] != symbol) &
            (full_etf_df['LTP'] > 0)
            ].copy()

        if same_category.empty:
            tolerance = allocated * (1 + MAX_PRICE_TOLERANCE_PERCENT / 100.0)
            if current_price <= tolerance:
                logging.info(
                    f"  ✅ {symbol}: No alternatives, but within {MAX_PRICE_TOLERANCE_PERCENT}% tolerance → 1 qty")
                personalized_etfs.loc[idx, 'USER_QTY'] = 1
            continue

        same_category = same_category.sort_values(['VOLUME', 'LTP'], ascending=[False, True])

        affordable = same_category[same_category['LTP'] <= allocated]

        if not affordable.empty:
            alt = affordable.iloc[0]
            alt_qty = int(allocated / alt['LTP'])
            if alt_qty > 0:
                logging.info(
                    f"  🔄 {symbol} (₹{current_price:.2f}) → {alt['SYMBOL']} (₹{alt['LTP']:.2f}) | Qty: {alt_qty}")
                personalized_etfs.loc[idx, 'SYMBOL'] = alt['SYMBOL']
                personalized_etfs.loc[idx, 'LTP'] = alt['LTP']
                personalized_etfs.loc[idx, 'USER_QTY'] = alt_qty
        else:
            tolerance = allocated * (1 + MAX_PRICE_TOLERANCE_PERCENT / 100.0)
            if current_price <= tolerance:
                logging.info(
                    f"  ✅ {symbol}: Within {MAX_PRICE_TOLERANCE_PERCENT}% tolerance (₹{current_price:.2f} vs ₹{allocated:.2f}) → 1 qty")
                personalized_etfs.loc[idx, 'USER_QTY'] = 1
            else:
                logging.info(f"  ⏭️  {symbol}: Skipped (₹{current_price:.2f} exceeds ₹{tolerance:.2f})")

    return personalized_etfs


def _apply_single_etf_cap(personalized_etfs, sip_monthly, cap_percent, customer_id):
    """
    Cap each ETF order so no single ETF consumes more than cap_percent% of the
    user's monthly SIP target.  Rows whose qty would drop to 0 are zeroed out
    (the smart-fallback already ran, so no further substitution happens here).
    """
    if not cap_percent or cap_percent <= 0 or sip_monthly <= 0:
        return personalized_etfs

    max_per_etf = (cap_percent / 100.0) * sip_monthly
    capped = 0

    for idx, row in personalized_etfs.iterrows():
        if row['USER_QTY'] <= 0 or row['LTP'] <= 0:
            continue
        user_amount = row['USER_QTY'] * row['LTP']
        if user_amount > max_per_etf:
            new_qty = int(max_per_etf / row['LTP'])
            logging.info(
                f"[{customer_id}] ETF cap: {row['SYMBOL']} qty {int(row['USER_QTY'])} → {new_qty} "
                f"(\u20b9{user_amount:.0f} → \u20b9{new_qty * row['LTP']:.0f}, cap=\u20b9{max_per_etf:.0f})"
            )
            personalized_etfs.loc[idx, 'USER_QTY'] = new_qty
            capped += 1

    if capped:
        logging.info(
            f"[{customer_id}] Single-ETF cap ({cap_percent}% of \u20b9{sip_monthly:,.0f}) applied to {capped} ETF(s)"
        )
    return personalized_etfs


def _execute_client_orders(client, filtered_etfs_df, user_multipliers, preferences_map,
                           strategy_map, etf_snapshot, max_single_etf_percent, run_id):
    """
    Execute all ETF orders for a single client in a dedicated thread.

    Thread-safety:
      FINVASIA  — pycurl sets proxy per curl handle; fully parallel, no env vars.
      Others    — requests reads env vars; serialised via _ENV_PROXY_LOCK.

    Returns a result dict consumed by execute_etf_orders for aggregation.
    """
    result = {
        'customer_id': None,
        'broker_name': None,
        'status': 'SKIPPED',          # 'SUCCESS' | 'FAILED' | 'SKIPPED'
        'total_investment': 0.0,
        'email_rows': [],
        'order_results_entry': None,  # {'customer_id':…, 'broker':…, 'results':[…]}
    }

    with app.app_context():
        try:
            customer_id = client.get('customer_id')
            broker_name = client.get('broker_name', '').strip().upper()
            result['customer_id'] = customer_id
            result['broker_name'] = broker_name

            if FILTER_CUSTOMERS and customer_id not in FILTER_CUSTOMERS:
                logging.info(f"⏭️  Skipping {customer_id} (not in FILTER_CUSTOMERS)")
                return result

            if FILTER_BROKERS and broker_name not in FILTER_BROKERS:
                logging.info(f"⏭️  Skipping {customer_id} ({broker_name} not in FILTER_BROKERS)")
                return result

            # Hard skip for broker IDs with unresolvable API-config issues.
            # Checked BEFORE any login attempt so no network call is wasted.
            user_id_broker = client.get('user_id_broker', '')
            if user_id_broker in BLOCKED_BROKER_IDS:
                logging.warning(
                    f"⛔ Skipping {customer_id} ({user_id_broker}) — "
                    f"broker ID is in BLOCKED_BROKER_IDS (ALGO_CHK / API config issue). "
                    f"Remove from BLOCKED_BROKER_IDS once the vendor_code is corrected in Finvasia."
                )
                result['status'] = 'SKIPPED'
                return result

            if customer_id not in user_multipliers:
                logging.warning(f"No multiplier found for client {customer_id}")
                return result

            user_data = user_multipliers[customer_id]
            multiplier = user_data['multiplier']

            try:
                broker_api_module = get_executor_for_broker(broker_name)
            except Exception as e:
                logging.error(f"No executor found for broker {broker_name}: {e}")
                result['status'] = 'FAILED'
                return result

            strategy = strategy_map.get(client.get('broker_id'))
            if strategy and strategy.enabled and (strategy.mode or '').lower() == 'custom':
                try:
                    strat_result = _run_custom_strategy(client, broker_api_module, strategy, etf_snapshot)
                    logging.info(f"Custom strategy result for {customer_id}: {strat_result}")
                    result['status'] = 'SUCCESS'
                except Exception as e:
                    logging.error(f"Custom strategy failed for {customer_id}: {e}")
                    result['status'] = 'FAILED'
                return result

            personalized_etfs = filtered_etfs_df.copy()
            client_prefs = preferences_map.get(customer_id, {})
            excluded_etfs = client_prefs.get('excluded_etfs') or []
            excluded_sectors = client_prefs.get('excluded_sectors') or []
            filtered_for_client = filtered_etfs_df
            if excluded_etfs or excluded_sectors:
                personalized_etfs = _apply_exclusions(personalized_etfs, excluded_etfs, excluded_sectors)
                filtered_for_client = _apply_exclusions(filtered_for_client, excluded_etfs, excluded_sectors)
            if personalized_etfs is None or personalized_etfs.empty:
                logging.info(f"No ETFs left to trade for client {customer_id} after exclusions")
                return result

            if USE_MULTIPLIER:
                personalized_etfs['USER_QTY'] = (
                    (personalized_etfs['ALLOCATED_AMOUNT'] * multiplier) / personalized_etfs['LTP']
                ).apply(lambda x: int(x) if x > 0 else 0)
            else:
                personalized_etfs['USER_QTY'] = personalized_etfs['QTY'].astype(int)

            personalized_etfs = _apply_smart_fallback(
                personalized_etfs, filtered_for_client, multiplier, customer_id
            )

            sip_monthly = user_data.get('monthly_target', 0)
            personalized_etfs = _apply_single_etf_cap(
                personalized_etfs, sip_monthly, max_single_etf_percent, customer_id
            )

            personalized_etfs['USER_AMOUNT'] = personalized_etfs['USER_QTY'] * personalized_etfs['LTP']
            total_investment = float(personalized_etfs['USER_AMOUNT'].sum())

            _proxy_url = get_client_proxy(client)
            if _proxy_url:
                try:
                    from urllib.parse import urlparse
                    _display_ip = urlparse(_proxy_url).hostname or _proxy_url
                except Exception:
                    _display_ip = _proxy_url
                print(f"""\n{'='*60}
🌐 CLIENT  : {client.get('username', customer_id)} ({customer_id})
📡 BROKER  : {broker_name}
🔒 PROXY IP: {_display_ip}  ← whitelist this on broker portal
{'='*60}""")
                logging.info(f"[{customer_id}] Using proxy IP: {_display_ip} for order placement")
            else:
                print(f"""\n{'='*60}
⚠️  CLIENT  : {client.get('username', customer_id)} ({customer_id})
📡 BROKER  : {broker_name}
❌ NO PROXY ASSIGNED — orders will use server IP (not SEBI compliant)
{'='*60}""")
                logging.warning(f"[{customer_id}] No proxy assigned — placing orders without static IP")

            class BrokerAPIWrapper:
                def __init__(self, client_info, api_module, broker_name_str):
                    self.client = client_info
                    self.api_module = api_module
                    self.broker_name = broker_name_str.upper()
                    self.token_refreshed = False
                    self.proxy_url = get_client_proxy(client_info)

                def place_order(self, symbol, qty, ltp=None):
                    try:
                        from urllib.parse import urlparse
                        _ip = urlparse(self.proxy_url).hostname if self.proxy_url else 'NO PROXY'
                    except Exception:
                        _ip = self.proxy_url or 'NO PROXY'
                    print(f"  📤 Placing order: {symbol} x {qty} | IP: {_ip}")
                    logging.info(f"  Order: {symbol} x {qty} via IP {_ip}")
                    try:
                        return self.api_module.place_single_order_direct(
                            self.client, symbol, qty, ltp=ltp)
                    except Exception as e:
                        error_msg = str(e)
                        # FINVASIA: place_single_order_direct already retried once internally.
                        # Adding an outer retry loop causes 6+ logins per order.
                        if self.broker_name == 'FINVASIA':
                            raise
                        if not _is_token_error(error_msg):
                            raise
                        _cid = self.client.get('customer_id', 'unknown')
                        if self.token_refreshed:
                            logging.warning(f"Token already refreshed for {_cid}, not retrying again")
                            raise
                        logging.warning(f"⚠️ Token expired for {_cid} ({self.broker_name}), refreshing...")
                        try:
                            if self.broker_name == 'DHAN':
                                _refresh_dhan_token_if_needed(self.client)
                            elif self.broker_name == 'ZERODHA':
                                _refresh_zerodha_token_if_needed(self.client)
                            elif self.broker_name == 'ANGEL':
                                _refresh_angel_token_if_needed(self.client)
                            elif self.broker_name in ('ANGELONE', 'ANGLE'):
                                _refresh_angel_token_if_needed(self.client)
                            elif self.broker_name == 'GROWW':
                                _refresh_groww_token_if_needed(self.client)
                            elif self.broker_name == 'UPSTOX':
                                _refresh_upstox_token_if_needed(self.client)
                            else:
                                logging.warning(f"Token refresh not implemented for {self.broker_name}")
                                raise
                            self.token_refreshed = True
                            logging.info(f"ℹ️ Token refreshed, retrying order for {symbol}...")
                            return self.api_module.place_single_order_direct(
                                self.client, symbol, qty, ltp=ltp)
                        except Exception as refresh_error:
                            logging.error(f"❌ Token refresh failed: {refresh_error}")
                            raise Exception(f"Token refresh failed: {refresh_error}") from e

            broker_api = BrokerAPIWrapper(client, broker_api_module, broker_name)
            generic_executor = GenericOrderExecutor(broker_name, broker_api, customer_id, client_info=client)

            # Place orders:
            # FINVASIA → pycurl sets proxy per curl handle → fully thread-safe, no env var needed.
            # Others   → requests reads HTTP_PROXY env var → serialise via _ENV_PROXY_LOCK.
            if broker_name in _PYCURL_PROXY_BROKERS:
                order_results = generic_executor.place_all_orders(personalized_etfs, filtered_for_client)
            else:
                with _ENV_PROXY_LOCK:
                    with client_proxy_context(get_client_proxy(client)):
                        order_results = generic_executor.place_all_orders(personalized_etfs, filtered_for_client)

            # Finvasia: if any orders failed with a password error, rotate and retry
            if broker_name == 'FINVASIA' and FINVASIA_PASSWORD_RESET_ON_ORDER and order_results:
                password_errors = [
                    r for r in order_results
                    if r.get('status') == 'FAILED' and _is_password_error(r.get('error', ''))
                ]
                if password_errors:
                    logging.warning(f"[{customer_id}] Finvasia password error on order; attempting auto-rotation")
                    rotation = _rotate_finvasia_password(client, password_errors[0].get('error', ''))
                    if rotation.get('success'):
                        client['password'] = rotation['new_password']
                        retry_symbols = {r.get('symbol') for r in password_errors if r.get('symbol')}
                        retry_df = personalized_etfs[personalized_etfs['SYMBOL'].isin(retry_symbols)]
                        if not retry_df.empty:
                            retry_results = generic_executor.place_all_orders(retry_df, filtered_for_client)
                            if retry_results:
                                retry_map = {r['symbol']: r for r in retry_results}
                                merged = []
                                for r in order_results:
                                    merged.append(retry_map.get(r.get('symbol'), r))
                                order_results = merged
                    else:
                        logging.warning(f"[{customer_id}] Finvasia password rotation failed: {rotation.get('error')}")

            if order_results:
                result['order_results_entry'] = {
                    'customer_id': customer_id,
                    'broker': broker_name,
                    'results': order_results
                }

            order_result_map = {}
            if order_results:
                for r in order_results:
                    order_result_map[r['symbol']] = r

            etf_details = personalized_etfs[['SYMBOL', 'USER_QTY', 'USER_AMOUNT']].to_dict('records')
            update_monthly_invested(customer_id, total_investment, etf_details)

            result['status'] = 'SUCCESS'
            result['total_investment'] = total_investment

            user = User.query.filter_by(customer_id=customer_id).first()
            client_name = user.full_name if user else customer_id

            for _, etf_row in personalized_etfs.iterrows():
                symbol = etf_row['SYMBOL']
                actual_status = 'SUCCESS'
                if symbol in order_result_map:
                    actual_status = order_result_map[symbol].get('status', 'SUCCESS')
                result['email_rows'].append({
                    'etf': etf_row['SYMBOL'],
                    'client': client_name,
                    'qty': int(etf_row['USER_QTY']),
                    'amount': float(etf_row['USER_AMOUNT']),
                    'total_client': total_investment,
                    'status': actual_status
                })

            try:
                if run_id is not None:
                    for row in personalized_etfs.itertuples(index=False):
                        symbol = row.SYMBOL
                        actual_status = 'SUCCESS'
                        actual_symbol = symbol
                        order_id = None
                        error_msg = None
                        if symbol in order_result_map:
                            r = order_result_map[symbol]
                            actual_status = r.get('status', 'SUCCESS')
                            actual_symbol = r.get('actual_symbol') or symbol
                            order_id = r.get('order_id')
                            error_msg = r.get('error')
                        db.session.add(OrderEvent(
                            run_id=run_id,
                            customer_id=customer_id,
                            broker_name=broker_name,
                            symbol=actual_symbol,
                            side='BUY',
                            qty=int(row.USER_QTY),
                            status=actual_status,
                            error=error_msg
                        ))
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logging.warning(f"OrderEvent logging failed for {customer_id}: {e}")

            logging.info(f"Orders executed for {customer_id}: ₹{total_investment} (multiplier: {multiplier})")

        except Exception as e:
            logging.error(f"Error executing orders for client {client.get('customer_id', 'unknown')}: {e}")
            result['status'] = 'FAILED'
            if run_id is not None:
                try:
                    db.session.add(OrderEvent(
                        run_id=run_id,
                        customer_id=client.get('customer_id'),
                        broker_name=client.get('broker_name', '').upper(),
                        symbol='ALL',
                        side='BUY',
                        qty=0,
                        status='FAILED',
                        error=str(e)
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    return result


def execute_etf_orders(filtered_etfs_df, user_multipliers, run_id=None, etf_data=None):
    """Execute ETF orders for all users in parallel; log OrderEvent rows."""

    with app.app_context():
        active_clients = get_active_clients_with_sip()
        preferences_map = _get_preferences_map()
        strategy_map = _get_strategy_map()
        etf_snapshot = _normalize_etf_snapshot(etf_data if etf_data is not None else filtered_etfs_df)

        _sched = SchedulerSettings.query.first()
        max_single_etf_percent = (
            _sched.max_single_etf_percent
            if _sched and _sched.max_single_etf_percent is not None
            else 0
        )

    # ── DEBUG: per-client opt-in prompt ────────────────────────────────────
    if DEBUG:
        print("\n[DEBUG MODE] Select which clients to process:")
        selected = []
        for _c in active_clients:
            _cid  = _c.get('customer_id', '?')
            _name = _c.get('username', _cid)
            _bid  = _c.get('user_id_broker', '?')
            _brk  = _c.get('broker_name', '?')
            _ans  = input(f"  Include {_name} ({_cid} / {_bid} / {_brk})? [y/n]: ").strip().lower()
            if _ans == 'y':
                selected.append(_c)
                print(f"  ✅ {_cid} included")
            else:
                print(f"  ⏭️  {_cid} skipped")
        active_clients = selected

    execution_summary = {
        'total_clients': len(active_clients),
        'successful_orders': 0,
        'failed_orders': 0,
        'total_investment': 0,
        'email_rows': [],
        'all_order_results': []
    }

    # Run sequentially in DEBUG mode so output is readable; else parallel.
    # DEBUG mode: max_workers=1 forces sequential execution
    max_workers = 1 if DEBUG else min(len(active_clients), 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_client = {
            executor.submit(
                _execute_client_orders,
                client, filtered_etfs_df, user_multipliers, preferences_map,
                strategy_map, etf_snapshot, max_single_etf_percent, run_id
            ): client
            for client in active_clients
        }

        for future in concurrent.futures.as_completed(future_to_client):
            client = future_to_client[future]
            try:
                res = future.result()
                if res['status'] == 'SUCCESS':
                    execution_summary['successful_orders'] += 1
                    execution_summary['total_investment'] += res['total_investment']
                    execution_summary['email_rows'].extend(res['email_rows'])
                    if res.get('order_results_entry'):
                        execution_summary['all_order_results'].append(res['order_results_entry'])
                elif res['status'] == 'FAILED':
                    execution_summary['failed_orders'] += 1
                # SKIPPED: client filtered out — counters unchanged
            except Exception as exc:
                logging.error(f"Thread error for client {client.get('customer_id')}: {exc}")
                execution_summary['failed_orders'] += 1

    # Client Monthly Tracking (non-critical, fails gracefully)
    with app.app_context():
        try:
            from client_monthly_tracker import update_client_tracking, send_tracking_email
            csv_path = update_client_tracking(execution_summary, user_multipliers)
            if csv_path:
                send_tracking_email()
                logging.info("Client tracking email sent successfully")
        except Exception as e:
            logging.warning(f"Client tracking failed (non-critical): {e}")

    return execution_summary

def fetch_and_filter_etfs(mode: str = 'headless'):
    """Main function to fetch ETF data, calculate multipliers, and execute strategy"""

    print("📊 Starting ETF SIP Strategy with Personalized Multipliers...")

    run_id = None
    run_id_env = os.getenv("RUN_ID", "").strip()
    if run_id_env.isdigit():
        run_id = int(run_id_env)
        with app.app_context():
            try:
                run = ExecutionRun.query.get(run_id)
                if run:
                    run.status = 'running'
                    run.mode = 'browser' if mode == 'browser' else 'headless'
                    db.session.commit()
            except Exception as e:
                print(f"⚠️ Failed to bind ExecutionRun: {e}")
    elif os.getenv('ENABLE_RUN_LOGS', '0').lower() in ('1', 'true', 'yes'):
        with app.app_context():
            try:
                run = ExecutionRun(mode='browser' if mode == 'browser' else 'headless', status='running')
                db.session.add(run)
                db.session.commit()
                run_id = run.id
            except Exception as e:
                print(f"⚠️ Failed to create ExecutionRun: {e}")

    # Step 1: Fetch ETF data
    print("⏳ Fetching ETF data...")
    retry_count = 0
    etf_csv_file = None

    while retry_count < MAX_RETRIES:
        print(f"⏳ Attempt {retry_count + 1} to fetch ETF data...")
        # etf_csv_file = fetch_etf_csv_with_strategy_order()
        # etf_csv_file = fetch_etf_csv_with_strategy_order()
        etf_csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ETF_Data_2026-04-07.csv")

        if etf_csv_file:
            print("✅ ETF data fetched successfully.")
            break

        retry_count += 1
        if retry_count < MAX_RETRIES:
            print(f"🔁 Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

    if not etf_csv_file:
        print("❌ Failed to fetch ETF data. Exiting.")
        raise RuntimeError("Failed to fetch ETF data after all retries")

    # Step 2: Load and filter ETF data
    print("📥 Loading ETF data...")
    etf_data = pd.read_csv(etf_csv_file)
    if etf_data is None or etf_data.empty:
        print("⚠️ Downloaded ETF CSV is empty or invalid.")
        raise RuntimeError("ETF CSV is empty or invalid")

    print("🔍 Filtering ETFs and calculating quantities...")
    filtered = calculate_quantities(etf_data)

    if filtered is None or filtered.empty:
        today = dt.now().strftime("%Y-%m-%d")
        msg = "No ETF fell below their average today."
        print(msg)
        notify_admin(
            subject=f"SmartETF — No trades today ({today})",
            html_body=f"<h3>SmartETF — No trades today ({today})</h3><p>{msg}</p>",
            text_body=msg
        )
        import sys as _sys
        _sys.exit(0)

    print("💾 Saving filtered ETFs to todays_etf.csv")
    filtered.to_csv("todays_etf.csv", index=False)

    # Step 3: Calculate personalized multipliers
    print("🧮 Calculating personalized user multipliers...")
    user_multipliers = calculate_user_multipliers(filtered)

    if not user_multipliers:
        print("⚠️ No users with SIP targets found.")
        raise RuntimeError("No users with SIP targets found")

    print(f"✅ Calculated multipliers for {len(user_multipliers)} users")

    # Step 4: Generate daily CSV files
    print("📝 Generating daily CSV files...")
    csv_result = generate_daily_csvs(filtered, user_multipliers)

    if csv_result:
        print(f"✅ Generated CSV files: {csv_result['zip_file']}")

    # Step 5: Execute orders
    print("🚀 Executing ETF orders...")
    execution_result = execute_etf_orders(filtered, user_multipliers, run_id=run_id, etf_data=etf_data)

    print(f"📊 Execution Summary:")
    print(f"   Total Clients: {execution_result['total_clients']}")
    print(f"   Successful Orders: {execution_result['successful_orders']}")
    print(f"   Failed Orders: {execution_result['failed_orders']}")
    print(f"   Total Investment: ₹{execution_result['total_investment']:,.2f}")

    # ── ETF Trading Algo (add-on subscribers only) ──────────────────────────
    # This runs AFTER the regular SIP investment flow and only affects clients
    # who have purchased the ETF Trading Algo add-on. Failures here do NOT
    # affect the main execution result.
    try:
        from etf_trading_algo import run_all_trading_algo, get_app as _get_algo_app
        logger.info('Running ETF Trading Algo for add-on subscribers...')
        algo_etf_snapshot = _normalize_etf_snapshot(etf_data) if etf_data is not None else {}
        with app.app_context():
            run_all_trading_algo(algo_etf_snapshot)
        logger.info('ETF Trading Algo completed.')
    except Exception as algo_err:
        import traceback as _tb
        logger.error(f'ETF Trading Algo execution failed (non-critical): {algo_err}')
        logger.error(_tb.format_exc())
    # ────────────────────────────────────────────────────────────────────────

    if os.getenv('ENABLE_RUN_LOGS', '0').lower() in ('1', 'true', 'yes') and run_id is not None:
        with app.app_context():
            try:
                run = ExecutionRun.query.get(run_id)
                if run:
                    run.ended_at = dt.now()
                    run.status = 'success'
                    run.total_clients = execution_result['total_clients']
                    run.processed = execution_result['total_clients']
                    run.passed = execution_result['successful_orders']
                    run.failed = execution_result['failed_orders']
                    run.total_orders = execution_result['successful_orders'] + execution_result['failed_orders']
                    run.ok_orders = execution_result['successful_orders']
                    run.fail_orders = execution_result['failed_orders']
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ Failed to finalize ExecutionRun: {e}")

    return {
        'run_id': run_id,
        'filtered_etfs': filtered,
        'user_multipliers': user_multipliers,
        'csv_files': csv_result,
        'execution_summary': execution_result
    }


if __name__ == "__main__":
    start_time = dt.now()
    today = start_time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        print(f"🚀 SmartETF Strategy Execution Started: {today}")
        result = fetch_and_filter_etfs(mode=RUN_MODE)

        if result:
            exec_summary = result['execution_summary']
            end_time = dt.now()
            duration = (end_time - start_time).total_seconds()

            # Build detailed email table
            total_clients = exec_summary.get('total_clients', 0)
            succ = exec_summary.get('successful_orders', 0)
            fail = exec_summary.get('failed_orders', 0)
            email_rows = exec_summary.get('email_rows', [])
            all_order_results = exec_summary.get('all_order_results', [])

            # Analyze order results for failures/replacements
            replaced_count = 0
            failed_count = 0
            replaced_details = []
            failed_details = []

            for client_result in all_order_results:
                customer_id = client_result.get('customer_id')
                broker = client_result.get('broker')
                results = client_result.get('results', [])

                for result in results:
                    status = result.get('status')
                    if status == 'REPLACED':
                        replaced_count += 1
                        replaced_details.append({
                            'customer': customer_id,
                            'broker': broker,
                            'original': result.get('symbol'),
                            'alternative': result.get('actual_symbol'),
                            'reason': result.get('reason', 'N/A')
                        })
                    elif status == 'FAILED':
                        failed_count += 1
                        failed_details.append({
                            'customer': customer_id,
                            'broker': broker,
                            'symbol': result.get('symbol'),
                            'error': result.get('error', 'Unknown error')
                        })

            # Header summary
            header_html = f"""
            <div style='font-family:Inter,Arial,sans-serif; margin-bottom:12px'>
              <h2 style='margin:0;'>ETF SIP — Execution Report</h2>
              <p style='margin:6px 0 0 0;'><b>Execution Time:</b> {today} &nbsp; | &nbsp; <b>Duration:</b> {duration:.2f}s</p>
              <p style='margin:6px 0 0 0;'><b>Total Clients:</b> {total_clients} &nbsp; | &nbsp; 
                 <b>Success:</b> {succ} &nbsp; | &nbsp; <b>Failed:</b> {fail}</p>
            </div>
            """


            # Table rows with proper status colors
            def get_status_color(status):
                if status == 'SUCCESS':
                    return '#0a8a0a'  # green
                elif status == 'REPLACED':
                    return '#ff8c00'  # orange
                else:  # FAILED
                    return '#c00'  # red


            rows_html = "".join([
                f"""<tr>
                        <td style='padding:6px 8px;border:1px solid #ddd'>{r.get('etf')}</td>
                        <td style='padding:6px 8px;border:1px solid #ddd'>{r.get('client')}</td>
                        <td style='padding:6px 8px;border:1px solid #ddd; text-align:right'>{r.get('qty')}</td>
                        <td style='padding:6px 8px;border:1px solid #ddd; text-align:right'>{r.get('amount'):.2f}</td>
                        <td style='padding:6px 8px;border:1px solid #ddd; text-align:right'>{r.get('total_client'):.2f}</td>
                        <td style='padding:6px 8px;border:1px solid #ddd; font-weight:600; color:{get_status_color(r.get('status'))}'>{r.get('status')}</td>
                    </tr>""" for r in email_rows
            ])

            table_html = f"""
            <table cellspacing='0' cellpadding='0' style='border-collapse:collapse; font-family:Inter,Arial,sans-serif'>
              <thead>
                <tr style='background:#f6f8fa'>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>ETF Name</th>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Client</th>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:right'>Qty</th>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:right'>Amount (₹)</th>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:right'>Client Total (₹)</th>
                  <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Status</th>
                </tr>
              </thead>
              <tbody>{rows_html or "<tr><td colspan='6' style='padding:8px;border:1px solid #ddd;color:#666'>No rows</td></tr>"}</tbody>
            </table>
            """

            # Add replacements section if any
            replacements_html = ""
            if replaced_details:
                replacement_rows = ''.join([
                                               f"<tr><td style='padding:6px 8px;border:1px solid #ddd'>{r['customer']}</td><td style='padding:6px 8px;border:1px solid #ddd'>{r['broker']}</td><td style='padding:6px 8px;border:1px solid #ddd'>{r['original']}</td><td style='padding:6px 8px;border:1px solid #ddd'>{r['alternative']}</td><td style='padding:6px 8px;border:1px solid #ddd;font-size:12px'>{r['reason']}</td></tr>"
                                               for r in replaced_details[:10]])
                if len(replaced_details) > 10:
                    replacement_rows += f"<tr><td colspan='5' style='padding:6px 8px;border:1px solid #ddd;color:#666'>... and {len(replaced_details) - 10} more</td></tr>"

                replacements_html = f"""
            <div style='margin-top:20px; font-family:Inter,Arial,sans-serif'>
              <h3 style='margin:0 0 10px 0; color:#ff8c00'>🔄 Symbol Replacements ({replaced_count})</h3>
              <table cellspacing='0' cellpadding='0' style='border-collapse:collapse; width:100%'>
                <thead>
                  <tr style='background:#fff3e0'>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Client</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Broker</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Original Symbol</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Alternative Symbol</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {replacement_rows}
                </tbody>
              </table>
            </div>
                """

            # Add failures section if any
            failures_html = ""
            if failed_details:
                failure_rows = ''.join([
                                           f"<tr><td style='padding:6px 8px;border:1px solid #ddd'>{r['customer']}</td><td style='padding:6px 8px;border:1px solid #ddd'>{r['broker']}</td><td style='padding:6px 8px;border:1px solid #ddd'>{r['symbol']}</td><td style='padding:6px 8px;border:1px solid #ddd;font-size:12px;color:#c00'>{r['error'][:100]}</td></tr>"
                                           for r in failed_details[:10]])
                if len(failed_details) > 10:
                    failure_rows += f"<tr><td colspan='4' style='padding:6px 8px;border:1px solid #ddd;color:#666'>... and {len(failed_details) - 10} more</td></tr>"

                failures_html = f"""
            <div style='margin-top:20px; font-family:Inter,Arial,sans-serif'>
              <h3 style='margin:0 0 10px 0; color:#c00'>❌ Failed Orders ({failed_count})</h3>
              <table cellspacing='0' cellpadding='0' style='border-collapse:collapse; width:100%'>
                <thead>
                  <tr style='background:#ffebee'>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Client</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Broker</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Symbol</th>
                    <th style='padding:6px 8px;border:1px solid #ddd;text-align:left'>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {failure_rows}
                </tbody>
              </table>
              <p style='margin-top:10px; color:#c00'><strong>⚠️ ACTION REQUIRED:</strong> Check symbol mappings in symbol_config.py and broker credentials.</p>
            </div>
                """

            html_body = header_html + table_html + replacements_html + failures_html + "<p style='color: gray; font-size: 12px; margin-top:16px'>SmartETF Automated Trading System</p>"

            # Send SUCCESS email
            subject = f"✅ SmartETF Execution Success - {start_time.strftime('%Y-%m-%d')}"
            # Text body with failures/replacements
            replacements_text = ""
            if replaced_details:
                replacements_text = f"\n\n🔄 Symbol Replacements ({replaced_count}):\n"
                for r in replaced_details[:10]:
                    replacements_text += f"  • {r['customer']} ({r['broker']}): {r['original']} → {r['alternative']}\n"
                if len(replaced_details) > 10:
                    replacements_text += f"  ... and {len(replaced_details) - 10} more\n"

            failures_text = ""
            if failed_details:
                failures_text = f"\n\n❌ Failed Orders ({failed_count}):\n"
                for r in failed_details[:10]:
                    failures_text += f"  • {r['customer']} ({r['broker']}): {r['symbol']} - {r['error'][:80]}\n"
                if len(failed_details) > 10:
                    failures_text += f"  ... and {len(failed_details) - 10} more\n"
                failures_text += "\n⚠️ ACTION REQUIRED: Check symbol mappings in symbol_config.py and broker credentials.\n"

            text_body = f"""
✅ SmartETF Strategy Executed Successfully

Execution Time: {today}
Duration: {duration:.2f} seconds

Execution Summary:
- Total Clients: {total_clients}
- Successful Orders: {succ}
- Failed Orders: {fail}
- Total Investment: ₹{exec_summary['total_investment']:,.2f}

Order Details: {len(email_rows)} orders placed{replacements_text}{failures_text}

SmartETF Automated Trading System
            """

            notify_admin(subject=subject, html_body=html_body, text_body=text_body)
            print("🎉 ETF SIP Strategy completed successfully!")
            print("📧 Success email sent to admin")
            sys.exit(0)
        else:
            raise RuntimeError("Strategy returned None")

    except Exception as e:
        end_time = dt.now()
        duration = (end_time - start_time).total_seconds()
        error_trace = traceback.format_exc()

        # Send FAILURE email
        subject = f"❌ SmartETF Execution FAILED - {start_time.strftime('%Y-%m-%d')}"
        html_body = f"""
<h2 style="color: red;">❌ SmartETF Strategy Execution FAILED</h2>
<p><strong>Execution Time:</strong> {today}</p>
<p><strong>Duration:</strong> {duration:.2f} seconds</p>
<hr>
<h3>Error Details</h3>
<p><strong>Error:</strong> {str(e)}</p>
<pre style="background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto;">{error_trace}</pre>
<hr>
<p style="color: red;"><strong>⚠️ ACTION REQUIRED:</strong> Please check the logs and fix the issue.</p>
<p style="color: gray; font-size: 12px;">SmartETF Automated Trading System</p>
        """
        text_body = f"""
❌ SmartETF Strategy Execution FAILED

Execution Time: {today}
Duration: {duration:.2f} seconds

Error Details:
{str(e)}

Full Traceback:
{error_trace}

⚠️ ACTION REQUIRED: Please check the logs and fix the issue.

SmartETF Automated Trading System
        """

        try:
            notify_admin(subject=subject, html_body=html_body, text_body=text_body)
            print("📧 Failure email sent to admin")
        except Exception as email_err:
            print(f"⚠️ Failed to send failure email: {email_err}")

        print(f"❌ ETF SIP Strategy failed: {e}")
        sys.exit(1)
