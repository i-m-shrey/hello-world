"""
etf_trading_algo.py

ETF Trading Algo — Modular execution module for the optional add-on.
Runs only for clients who have an active TradingAlgoSubscription.
Does NOT interfere with existing investment/SIP logic.

Fall Logic:
- 'average' mode: checks if current price has fallen >= ETF's avg daily fall from avg_buy_price
- 'fixed' mode: checks if current price has fallen >= admin-defined fall_percent from avg_buy_price

Profit Booking:
- If current price >= avg_buy_price * (1 + profit_percent/100), sell all units for that ETF
- Reset the cycle (mark as Day 0 again, clear position stats)
"""

import logging
import datetime
from datetime import date as date_type

logger = logging.getLogger(__name__)


def get_app():
    from app import app
    return app


def get_algo_settings():
    """Return TradingAlgoSettings singleton. Returns None if not found."""
    from models import TradingAlgoSettings
    return TradingAlgoSettings.query.first()


def get_algo_active_clients():
    """
    Return list of client dicts for clients with an active TradingAlgoSubscription.
    Reuses broker/subscription data from the same DB queries as get_active_clients_with_sip.
    """
    from models import db, TradingAlgoSubscription, User, Broker, Subscription
    from dhan_security_helper import decrypt_dhan_client_id, decrypt_dhan_api_key
    now = datetime.datetime.utcnow()
    try:
        rows = (
            db.session.query(TradingAlgoSubscription, User, Broker, Subscription)
            .join(User, TradingAlgoSubscription.user_id == User.id)
            .join(Subscription, TradingAlgoSubscription.subscription_id == Subscription.id)
            .join(Broker, Broker.user_id == User.id)
            .filter(
                TradingAlgoSubscription.is_active == True,
                TradingAlgoSubscription.expiry_date > now,
                TradingAlgoSubscription.start_date <= now,
                Broker.subscription_status == 'Active',
                Broker.is_master == True,
            )
            .all()
        )
        # If no master broker found, fall back to any active broker
        if not rows:
            rows = (
                db.session.query(TradingAlgoSubscription, User, Broker, Subscription)
                .join(User, TradingAlgoSubscription.user_id == User.id)
                .join(Subscription, TradingAlgoSubscription.subscription_id == Subscription.id)
                .join(Broker, Broker.user_id == User.id)
                .filter(
                    TradingAlgoSubscription.is_active == True,
                    TradingAlgoSubscription.expiry_date > now,
                    TradingAlgoSubscription.start_date <= now,
                    Broker.subscription_status == 'Active',
                )
                .order_by(Broker.created_at.asc())
                .all()
            )

        # Deduplicate by customer_id — pick one broker per customer
        seen = set()
        clients = []
        for algo_sub, user, broker, sub in rows:
            if user.customer_id in seen:
                continue
            seen.add(user.customer_id)
            client_data = {
                'customer_id': user.customer_id,
                'user_id': user.id,
                'broker_id': broker.id,
                'broker_name': broker.broker_name,
                'user_id_broker': broker.user_id_broker,
                'password': broker.password,
                'totp_secret': broker.totp_secret,
                'vendor_code': broker.vendor_code,
                'api_secret': broker.api_secret,
                'imei': broker.imei,
                'api_key': broker.api_key,
                'secret_key': broker.secret_key,
                'token_id': broker.token_id,
                'session_token': broker.session_token,
                'access_token': broker.access_token,
                'username_broker': broker.username,
                'proxy_ip': broker.proxy_ip or '',
                'algo_subscription_id': algo_sub.id,
            }
            # Decrypt Dhan credentials if applicable
            if broker.broker_name and broker.broker_name.upper() == 'DHAN':
                if broker.dhan_client_id_enc:
                    client_data['dhan_client_id'] = decrypt_dhan_client_id(
                        broker.dhan_client_id_enc, broker.dhan_client_id_iv, broker.dhan_client_id_tag) or ''
                if broker.api_key_enc:
                    client_data['api_key'] = decrypt_dhan_api_key(
                        broker.api_key_enc, broker.api_key_iv, broker.api_key_tag) or broker.api_key or ''
            clients.append(client_data)
        return clients
    except Exception as e:
        logger.error(f'[TradingAlgo] get_algo_active_clients error: {e}')
        return []


def get_or_create_position(db_session, customer_id, broker_id, etf_symbol):
    """Get or create a TradingAlgoPosition for a given client/ETF."""
    from models import TradingAlgoPosition
    pos = db_session.query(TradingAlgoPosition).filter_by(
        customer_id=customer_id,
        broker_id=broker_id,
        etf_symbol=etf_symbol.upper()
    ).first()
    if not pos:
        pos = TradingAlgoPosition(
            customer_id=customer_id,
            broker_id=broker_id,
            etf_symbol=etf_symbol.upper(),
            is_day0_complete=False,
            cycle_active=False,
        )
        db_session.add(pos)
        db_session.flush()
    return pos


def get_fall_threshold(etf_symbol, settings, etf_configs_map, avg_fall_data):
    """
    Return the fall threshold % for a given ETF.
    - avg_fall_data: dict {symbol: avg_fall_pct} from dynamic_fall_calculator (positive numbers)
    """
    if settings.apply_globally:
        if settings.fall_mode == 'fixed':
            return float(settings.global_fall_percent or 3.0)
        else:  # 'average'
            return float(avg_fall_data.get(etf_symbol.upper(), settings.global_fall_percent or 3.0))
    else:
        cfg = etf_configs_map.get(etf_symbol.upper())
        if cfg:
            if cfg.fall_mode == 'fixed':
                return float(cfg.fall_percent or 3.0)
            else:
                return float(avg_fall_data.get(etf_symbol.upper(), cfg.fall_percent or 3.0))
        # fallback to global
        return float(avg_fall_data.get(etf_symbol.upper(), settings.global_fall_percent or 3.0))


def get_profit_threshold(etf_symbol, settings, etf_configs_map):
    """Return the profit target % for a given ETF."""
    if settings.apply_globally:
        return float(settings.global_profit_percent or 3.0)
    cfg = etf_configs_map.get(etf_symbol.upper())
    if cfg:
        return float(cfg.profit_percent or 3.0)
    return float(settings.global_profit_percent or 3.0)


def reset_position(pos):
    """Reset position after a sell cycle so ETF is treated as Day 0 again."""
    pos.is_day0_complete = False
    pos.cycle_active = False
    pos.avg_buy_price = 0.0
    pos.total_qty = 0
    pos.total_invested = 0.0
    pos.buy_count = 0
    pos.last_sell_date = date_type.today()
    pos.updated_at = datetime.datetime.utcnow()


def record_buy(pos, qty, price):
    """Update position after a buy."""
    new_total_invested = pos.total_invested + (qty * price)
    new_total_qty = pos.total_qty + qty
    pos.avg_buy_price = new_total_invested / new_total_qty if new_total_qty > 0 else price
    pos.total_qty = new_total_qty
    pos.total_invested = new_total_invested
    pos.buy_count += 1
    pos.last_buy_date = date_type.today()
    pos.is_day0_complete = True
    pos.cycle_active = True
    pos.updated_at = datetime.datetime.utcnow()


def run_trading_algo_for_client(client, settings, etf_configs_map, etf_snapshot, avg_fall_data, db_session):
    """
    Run the ETF Trading Algo for a single client.

    For each selected ETF in settings.selected_etfs:
      1. If not Day 0 complete -> BUY (initial purchase)
      2. If Day 0 complete and position active:
         a. Check profit -> if target reached, SELL and reset
         b. Check fall -> if fallen enough, BUY more

    etf_snapshot: dict {symbol: {'ltp': float, 'chng': float}}
    avg_fall_data: dict {symbol: float}  (positive avg daily fall %)
    """
    from broker_dispatcher import get_executor_for_broker
    customer_id = client['customer_id']
    broker_id = client['broker_id']

    selected_etfs = [s.strip().upper() for s in (settings.selected_etfs or []) if s.strip()]
    if not selected_etfs:
        logger.info(f'[TradingAlgo] {customer_id}: no ETFs selected in admin settings')
        return

    # Resolve broker executor; bail early if order placement is not supported
    broker_api_module = get_executor_for_broker(client['broker_name'])
    if not hasattr(broker_api_module, 'place_single_order_direct'):
        logger.warning(f'[TradingAlgo] {customer_id}: broker {client["broker_name"]} lacks place_single_order_direct, skipping')
        return

    for etf_symbol in selected_etfs:
        try:
            snap = etf_snapshot.get(etf_symbol)
            if not snap:
                logger.warning(f'[TradingAlgo] {customer_id}: {etf_symbol} not in snapshot, skipping')
                continue

            current_price = float(snap.get('ltp', 0))
            if current_price <= 0:
                logger.warning(f'[TradingAlgo] {customer_id}: {etf_symbol} LTP=0, skipping')
                continue

            pos = get_or_create_position(db_session, customer_id, broker_id, etf_symbol)

            fall_threshold_pct = get_fall_threshold(etf_symbol, settings, etf_configs_map, avg_fall_data)
            profit_threshold_pct = get_profit_threshold(etf_symbol, settings, etf_configs_map)

            # --- DAY 0: Initial buy ---
            if not pos.is_day0_complete:
                logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} Day 0 buy at \u20b9{current_price}')
                qty = max(1, int(1000 / current_price))  # Buy ~\u20b91000 worth; adjust as needed
                try:
                    # Place order FIRST; only record position state if order succeeds
                    broker_api_module.place_single_order_direct(client, etf_symbol, qty, side='BUY')
                    record_buy(pos, qty, current_price)
                    logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} Day 0 BUY {qty}@{current_price} OK')
                except Exception as e:
                    logger.error(f'[TradingAlgo] {customer_id}: {etf_symbol} Day 0 BUY failed: {e}')
                continue  # Done for today for this ETF

            # --- Position is open: check profit FIRST, then fall ---
            if pos.cycle_active and pos.avg_buy_price > 0:

                # Check profit target
                profit_pct = ((current_price - pos.avg_buy_price) / pos.avg_buy_price) * 100
                if profit_pct >= profit_threshold_pct:
                    logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} profit {profit_pct:.2f}% >= target {profit_threshold_pct}% \u2192 SELL')
                    try:
                        # Place sell order FIRST; only reset position state if order succeeds
                        broker_api_module.place_single_order_direct(client, etf_symbol, pos.total_qty, side='SELL')
                        reset_position(pos)  # Reset cycle so it restarts as Day 0
                        logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} SELL OK \u2192 cycle reset')
                    except Exception as e:
                        logger.error(f'[TradingAlgo] {customer_id}: {etf_symbol} SELL failed: {e}')
                    continue

                # Check fall trigger for additional buy
                fall_from_avg = ((pos.avg_buy_price - current_price) / pos.avg_buy_price) * 100
                if fall_from_avg >= fall_threshold_pct:
                    logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} fallen {fall_from_avg:.2f}% >= threshold {fall_threshold_pct}% \u2192 BUY more')
                    qty = max(1, int(1000 / current_price))
                    try:
                        # Place order FIRST; only record position state if order succeeds
                        broker_api_module.place_single_order_direct(client, etf_symbol, qty, side='BUY')
                        record_buy(pos, qty, current_price)
                        logger.info(f'[TradingAlgo] {customer_id}: {etf_symbol} additional BUY {qty}@{current_price} OK')
                    except Exception as e:
                        logger.error(f'[TradingAlgo] {customer_id}: {etf_symbol} BUY failed: {e}')
                else:
                    logger.debug(f'[TradingAlgo] {customer_id}: {etf_symbol} no action (fall {fall_from_avg:.2f}% < {fall_threshold_pct}%)')

        except Exception as etf_err:
            logger.error(f'[TradingAlgo] {customer_id}: {etf_symbol} unhandled error: {etf_err}')

    db_session.commit()


def load_avg_fall_data():
    """Load historical average fall % per ETF from dynamic_fall_calculator or hardcoded CSV."""
    try:
        from dynamic_fall_calculator import (
            get_available_historical_days, MIN_DATA_DAYS,
            HISTORICAL_FOLDER, ENABLE_DYNAMIC_FALL
        )
        import os, pandas as pd
        if not ENABLE_DYNAMIC_FALL:
            return _load_hardcoded_avg_fall()
        if get_available_historical_days() < MIN_DATA_DAYS:
            return _load_hardcoded_avg_fall()
        # Calculate rolling avg fall from historical folder
        avg_falls = {}
        for fname in os.listdir(HISTORICAL_FOLDER):
            if not fname.endswith('.csv'):
                continue
            try:
                df = pd.read_csv(os.path.join(HISTORICAL_FOLDER, fname))
                if '%CHNG' in df.columns and 'SYMBOL' in df.columns:
                    for _, row in df.iterrows():
                        sym = str(row['SYMBOL']).strip().upper()
                        chng = float(row['%CHNG'])
                        if chng < 0:
                            avg_falls.setdefault(sym, []).append(abs(chng))
            except Exception:
                pass
        return {sym: sum(vals)/len(vals) for sym, vals in avg_falls.items() if vals}
    except Exception as e:
        logger.warning(f'[TradingAlgo] load_avg_fall_data error: {e}')
        return _load_hardcoded_avg_fall()


def _load_hardcoded_avg_fall():
    """Load average fall from the hardcoded indices CSV (same source as filter_etfs.py)."""
    try:
        import os, pandas as pd
        csv_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'strategy_runner', 'average_percentage_fall_indices.csv'
        )
        if not os.path.isfile(csv_path):
            return {}
        df = pd.read_csv(csv_path)
        result = {}
        for _, row in df.iterrows():
            try:
                sym = str(row.get('SYMBOL', row.get('Symbol', ''))).strip().upper()
                fall = abs(float(row.get('AVG_FALL', row.get('Avg_Fall', row.get('average_fall', 0)))))
                if sym:
                    result[sym] = fall
            except Exception:
                pass
        return result
    except Exception as e:
        logger.warning(f'[TradingAlgo] _load_hardcoded_avg_fall error: {e}')
        return {}


def run_all_trading_algo(etf_snapshot):
    """
    Main entry point — called from etf_automated.py after the regular SIP execution.
    etf_snapshot: dict {symbol: {'ltp': float, 'chng': float}}
    """
    from models import db, TradingAlgoETFConfig
    settings = get_algo_settings()
    if not settings:
        logger.info('[TradingAlgo] No TradingAlgoSettings found, skipping')
        return
    # Note: we run even if is_enabled=False (existing subscribers keep running)
    # Only checkout visibility is controlled by is_enabled

    clients = get_algo_active_clients()
    if not clients:
        logger.info('[TradingAlgo] No active algo subscribers found')
        return

    logger.info(f'[TradingAlgo] Running for {len(clients)} clients')
    avg_fall_data = load_avg_fall_data()
    etf_configs = TradingAlgoETFConfig.query.filter_by(settings_id=settings.id).all()
    etf_configs_map = {c.etf_symbol.upper(): c for c in etf_configs}

    for client in clients:
        try:
            run_trading_algo_for_client(
                client=client,
                settings=settings,
                etf_configs_map=etf_configs_map,
                etf_snapshot=etf_snapshot,
                avg_fall_data=avg_fall_data,
                db_session=db.session,
            )
        except Exception as e:
            logger.error(f'[TradingAlgo] Client {client["customer_id"]} failed: {e}')

    logger.info('[TradingAlgo] Completed')
