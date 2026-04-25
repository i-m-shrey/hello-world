"""
Generic Order Executor - Centralized retry logic for all brokers
Handles symbol mapping, fallback, and failure tracking
"""
import time
import logging
from symbol_config import get_mapped_symbol, calculate_alternative_qty, find_alternative_by_underlying_asset
from order_tracker import log_order_result

# SEBI / broker API rate limit: max 10 orders/sec per exchange segment.
# We stay well under by waiting 0.15s between orders (~6-7 orders/sec).
ORDER_RATE_LIMIT_SLEEP = 0.15


def _is_stop_client_error(error_str: str) -> bool:
    """Errors that should stop the whole client run, not just one symbol."""
    lower = (error_str or '').lower()
    patterns = [
        'token refresh failed',
        'session expired',
        'invalid session',
        'session key',
        'algo_chk',
        'invalid app_key',
        'app_key or user_id',
        'client token/session issue',
    ]
    return any(p in lower for p in patterns)


class GenericOrderExecutor:
    """
    Generic order executor that works with any broker
    Each broker provides simple place_order_api() method
    
    Retry limit: Max 3 alternatives after original fails
    """
    
    MAX_ALTERNATIVES = 3
    
    def __init__(self, broker_name, broker_api, customer_id, client_info=None):
        self.broker_name = broker_name.upper()
        self.broker_api = broker_api
        self.customer_id = customer_id
        self.client_info = client_info
        self.failed_symbols = []
    
    def _refresh_broker_session(self):
        """
        Refresh broker session/token for all supported brokers
        
        Returns:
            bool: True if refresh successful, False otherwise
        """
        if not self.client_info:
            logging.warning("No client info available for token refresh")
            return False
        
        try:
            if self.broker_name == 'DHAN':
                from dhan_oauth import generate_dhan_token
                from app import app, db
                from models import Broker
                
                api_key = self.client_info.get('api_key', '').strip()
                api_secret = self.client_info.get('api_secret', '').strip()
                client_id = self.client_info.get('dhan_client_id', '').strip()
                mobile = self.client_info.get('mobile', '').strip()
                pin = self.client_info.get('password', '').strip()
                totp_secret = self.client_info.get('totp_secret', '').strip()
                
                new_token = generate_dhan_token(api_key, api_secret, client_id, mobile, pin, totp_secret)
                self.client_info['access_token'] = new_token
                
                with app.app_context():
                    broker = db.session.get(Broker, self.client_info.get('broker_id'))
                    if broker:
                        broker.access_token = new_token
                        db.session.commit()
                
                logging.info(f"DHAN token refreshed for {self.customer_id}")
                return True
            
            elif self.broker_name == 'ZERODHA':
                from zerodha_oauth import generate_zerodha_token
                from kiteconnect import KiteConnect
                from app import app, db
                from models import Broker
                
                api_key = self.client_info.get('api_key', '').strip()
                api_secret = self.client_info.get('api_secret', '').strip()
                user_id = self.client_info.get('user_id_broker', '').strip()
                password = self.client_info.get('password', '').strip()
                totp_secret = self.client_info.get('totp_secret', '').strip()
                
                new_token = generate_zerodha_token(api_key, api_secret, user_id, password, totp_secret)
                self.client_info['access_token'] = new_token
                
                with app.app_context():
                    broker = db.session.get(Broker, self.client_info.get('broker_id'))
                    if broker:
                        broker.access_token = new_token
                        db.session.commit()
                
                kite = KiteConnect(api_key=api_key)
                kite.set_access_token(new_token)
                self.broker_api.kite = kite
                
                logging.info(f"ZERODHA token refreshed for {self.customer_id}")
                return True
            
            elif self.broker_name == 'FINVASIA':
                # Finvasia sessions are owned by finvasia_broker_api._session_cache.
                # Creating a new Account here would start a new Finvasia session that
                # invalidates the one in cache, causing "Session Expired" for all other
                # threads using the same user. Instead, just clear the cache entry —
                # the next place_single_order_direct call will re-login cleanly with
                # the correct proxy and update the cache.
                try:
                    import finvasia_broker_api as _fba
                    _fba._clear_session(self.client_info)
                    logging.info(f"FINVASIA session cleared for {self.customer_id} — will re-login on next order")
                    return True
                except Exception as e:
                    logging.error(f"FINVASIA session clear failed for {self.customer_id}: {e}")
                    return False
            
            else:
                logging.warning(f"Token refresh not implemented for {self.broker_name}")
                return False
        
        except Exception as e:
            logging.error(f"Failed to refresh {self.broker_name} session: {e}")
            return False
    
    def place_single_symbol_order(self, symbol, qty, price, full_etf_df=None):
        """
        Place order for single symbol with full retry logic
        
        Returns:
            dict: {
                'symbol': 'GOLDSHARE',
                'status': 'SUCCESS/REPLACED/FAILED',
                'actual_symbol': 'GOLDBEES',
                'original_qty': 2,
                'actual_qty': 3,
                'order_id': '123456',
                'reason': '...',
                'error': None
            }
        """
        
        print(f"\n  📊 Processing: {symbol} × {qty}")
        
        tried_symbols = []
        original_symbol = symbol
        original_qty = qty
        original_price = price
        
        result = self._try_place_order(symbol, qty)
        
        if result['success']:
            print(f"    ✅ Original symbol placed: {symbol} × {qty} | Order ID: {result['order_id']}")
            log_data = {
                'symbol': original_symbol,
                'status': 'SUCCESS',
                'actual_symbol': symbol,
                'original_qty': original_qty,
                'actual_qty': qty,
                'original_price': original_price,
                'actual_price': price,
                'order_id': result['order_id'],
                'reason': None,
                'error': None
            }
            log_order_result(self.customer_id, self.broker_name, log_data)
            return log_data
        
        print(f"    ❌ Original failed: {result['error']}")
        tried_symbols.append(symbol)
        
        if result.get('skip_alternatives'):
            print(f"    ⏭️ Skipping alternatives due to token/session failure")
            log_data = {
                'symbol': original_symbol,
                'status': 'FAILED',
                'actual_symbol': None,
                'original_qty': original_qty,
                'actual_qty': 0,
                'original_price': original_price,
                'actual_price': 0,
                'order_id': None,
                'reason': 'Token/session refresh failed - all orders skipped',
                'error': result['error'],
                'stop_client': True
            }
            log_order_result(self.customer_id, self.broker_name, log_data)
            return log_data
        
        alternatives_to_try = []
        
        mapped_symbol = get_mapped_symbol(symbol, self.broker_name)
        if mapped_symbol and mapped_symbol not in tried_symbols:
            alternatives_to_try.append({
                'symbol': mapped_symbol,
                'price': self._get_symbol_price(mapped_symbol, full_etf_df, original_price),
                'source': 'mapped'
            })
        
        if full_etf_df is not None:
            volume_alternatives = find_alternative_by_underlying_asset(original_symbol, full_etf_df, tried_symbols)
            for alt in volume_alternatives:
                if alt['symbol'] not in tried_symbols and alt['symbol'] not in [a['symbol'] for a in alternatives_to_try]:
                    alternatives_to_try.append({
                        'symbol': alt['symbol'],
                        'price': alt['price'],
                        'source': f"underlying: {alt['underlying']}, volume: {alt['volume']:.0f}"
                    })
        
        alternatives_to_try = alternatives_to_try[:self.MAX_ALTERNATIVES]
        
        if alternatives_to_try:
            print(f"    🔍 Will try {len(alternatives_to_try)} alternative(s) (max {self.MAX_ALTERNATIVES})")
            
            for idx, alt in enumerate(alternatives_to_try, 1):
                alt_symbol = alt['symbol']
                alt_price = alt['price']
                tried_symbols.append(alt_symbol)
                
                print(f"    🔄 Trying alternative {idx}/{len(alternatives_to_try)}: {alt_symbol} ({alt['source']})")
                
                alt_qty = calculate_alternative_qty(original_qty, original_price, alt_price)
                alt_result = self._try_place_order(alt_symbol, alt_qty)
                
                if alt_result['success']:
                    print(f"    ✅ Alternative {idx} placed: {alt_symbol} × {alt_qty} | Order ID: {alt_result['order_id']}")
                    log_data = {
                        'symbol': original_symbol,
                        'status': 'REPLACED',
                        'actual_symbol': alt_symbol,
                        'original_qty': original_qty,
                        'actual_qty': alt_qty,
                        'original_price': original_price,
                        'actual_price': alt_price,
                        'order_id': alt_result['order_id'],
                        'reason': f"Alternative {alt_symbol} used ({alt['source']})",
                        'error': result['error']
                    }
                    log_order_result(self.customer_id, self.broker_name, log_data)
                    return log_data
                else:
                    print(f"    ❌ Alternative {idx} failed: {alt_result['error']}")
        
        print(f"    ❌ All alternatives exhausted for {original_symbol}")
        self.failed_symbols.append({
            'symbol': original_symbol,
            'tried': tried_symbols,
            'last_error': result['error']
        })
        
        log_data = {
            'symbol': original_symbol,
            'status': 'FAILED',
            'actual_symbol': None,
            'original_qty': original_qty,
            'actual_qty': 0,
            'original_price': original_price,
            'actual_price': 0,
            'order_id': None,
            'reason': f"All alternatives failed (tried: {', '.join(tried_symbols)})",
            'error': result['error']
        }
        log_order_result(self.customer_id, self.broker_name, log_data)
        return log_data
    
    def place_all_orders(self, etf_orders_df, full_etf_df=None):
        """
        Place orders for all symbols in dataframe
        
        Args:
            etf_orders_df: DataFrame with SYMBOL, USER_QTY, LTP columns
            full_etf_df: Full ETF data for fallback
        
        Returns:
            list: All order results
        """
        results = []
        token_failed = False
        
        for _, row in etf_orders_df.iterrows():
            symbol = str(row.get('SYMBOL', '')).strip()
            if not symbol:
                continue
            
            try:
                qty = int(row.get('USER_QTY', 0))
            except:
                qty = int(row.get('QTY', 0))
            
            if qty < 1:
                continue
            
            price = float(row.get('LTP', 0))
            
            if token_failed:
                print(f"\n  ⏭️ Skipping {symbol} due to previous token failure")
                results.append({
                    'symbol': symbol,
                    'status': 'FAILED',
                    'actual_symbol': None,
                    'original_qty': qty,
                    'actual_qty': 0,
                    'original_price': price,
                    'actual_price': 0,
                    'order_id': None,
                    'reason': 'Skipped due to token/session failure',
                    'error': 'Client token/session issue',
                    'stop_client': True
                })
                continue
            
            result = self.place_single_symbol_order(symbol, qty, price, full_etf_df)
            results.append(result)

            # Rate limit: stay under 10 orders/sec (SEBI/broker API limit)
            time.sleep(ORDER_RATE_LIMIT_SLEEP)

            if result.get('stop_client') or _is_stop_client_error(result.get('error', '')) or _is_stop_client_error(result.get('reason', '')):
                token_failed = True
                print(f"    🚨 Client-level broker failure detected - will skip remaining {len(etf_orders_df) - len(results)} orders for this client")
        
        return results
    
    def _try_place_order(self, symbol, qty):
        """
        Try to place order using broker API with token retry logic
        
        Returns:
            dict: {'success': bool, 'order_id': str, 'error': str}
        """
        try:
            order_id = self.broker_api.place_order(symbol, qty)
            return {'success': True, 'order_id': order_id, 'error': None}
        except Exception as e:
            error_str = str(e).lower()
            
            token_errors = ['token', 'session', 'unauthorized', 'invalid session', 'access denied', 
                          'authentication', 'logged out', 'expired', 'invalid token']
            
            is_token_error = any(keyword in error_str for keyword in token_errors)
            
            if is_token_error:
                logging.warning(f"Token/session error detected for {self.broker_name}: {e}. Retrying with fresh token...")
                print(f"    🔄 Token error detected, regenerating token and retrying...")

                try:
                    refreshed = self._refresh_broker_session()
                    if refreshed:
                        logging.info(f"Token refreshed for {self.broker_name}, retrying order...")
                        order_id = self.broker_api.place_order(symbol, qty)
                        print(f"    ✅ Retry successful after token refresh")
                        return {'success': True, 'order_id': order_id, 'error': None}
                except Exception as retry_error:
                    retry_error_str = str(retry_error).lower()
                    is_still_token_error = any(keyword in retry_error_str for keyword in token_errors)

                    if is_still_token_error or _is_stop_client_error(retry_error_str):
                        logging.error(f"Token refresh failed - still token/session error: {retry_error}")
                        print(f"    ❌ Token/session refresh failed - skipping all remaining orders for this client")
                        return {'success': False, 'order_id': None, 'error': f"Token refresh failed: {retry_error}", 'skip_alternatives': True, 'stop_client': True}
                    else:
                        logging.error(f"Retry failed after token refresh (non-token error): {retry_error}")
                        return {'success': False, 'order_id': None, 'error': f"Retry failed: {retry_error}"}

            if _is_stop_client_error(error_str):
                return {'success': False, 'order_id': None, 'error': str(e), 'skip_alternatives': True, 'stop_client': True}

            return {'success': False, 'order_id': None, 'error': str(e)}
    
    def _get_symbol_price(self, symbol, full_etf_df, fallback_price):
        """Get symbol price from ETF data or fallback"""
        if full_etf_df is not None:
            try:
                row = full_etf_df[full_etf_df['SYMBOL'] == symbol]
                if not row.empty:
                    return float(row.iloc[0]['LTP'])
            except:
                pass
        return fallback_price
    
    def get_failed_symbols_summary(self):
        """Get summary of failed symbols for email"""
        return self.failed_symbols


def execute_orders_for_client(client, etf_orders_df, full_etf_df=None):
    """
    Execute orders for a single client using generic executor
    
    Args:
        client: Client dict with broker info
        etf_orders_df: DataFrame with orders
        full_etf_df: Full ETF data
    
    Returns:
        list: Order results
    """
    broker_name = client.get('broker_name', '').upper()
    customer_id = client.get('customer_id')
    
    print(f"\n🚀 Executing orders for {customer_id} via {broker_name}...")
    
    from broker_dispatcher import get_executor_for_broker
    executor_module = get_executor_for_broker(broker_name)
    
    broker_api = create_broker_api_wrapper(client, executor_module)
    
    generic_executor = GenericOrderExecutor(broker_name, broker_api, customer_id, client_info=client)
    
    results = generic_executor.place_all_orders(etf_orders_df, full_etf_df)
    
    return results


def create_broker_api_wrapper(client, executor_module):
    """
    Create broker API wrapper that provides simple place_order() method
    """
    class BrokerAPIWrapper:
        def __init__(self, client_info, executor):
            self.client = client_info
            self.executor = executor
        
        def place_order(self, symbol, qty):
            """Place order and return order_id or raise exception"""
            return self.executor.place_single_order_direct(self.client, symbol, qty)
    
    return BrokerAPIWrapper(client, executor_module)
