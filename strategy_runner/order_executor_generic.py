"""
Generic Order Executor - Centralized retry logic for all brokers
Handles symbol mapping, fallback, and failure tracking
"""
import logging
import time
from symbol_config import get_mapped_symbol, calculate_alternative_qty, find_alternative_by_underlying_asset
from order_tracker import log_order_result


class GenericOrderExecutor:
    """
    Generic order executor that works with any broker
    Each broker provides simple place_order_api() method
    
    Retry limit: Max 3 alternatives after original fails
    """
    
    MAX_ALTERNATIVES = 3
    # SEBI retail rate limit: <= 10 orders/sec (0.1s). Use 0.15s for safety.
    ORDER_RATE_LIMIT_SECONDS = 0.15
    
    def __init__(self, broker_name, broker_api, customer_id):
        self.broker_name = broker_name.upper()
        self.broker_api = broker_api
        self.customer_id = customer_id
        self.failed_symbols = []
    
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
            
            result = self.place_single_symbol_order(symbol, qty, price, full_etf_df)
            results.append(result)
            time.sleep(self.ORDER_RATE_LIMIT_SECONDS)
        
        return results
    
    def _try_place_order(self, symbol, qty):
        """
        Try to place order using broker API
        
        Returns:
            dict: {'success': bool, 'order_id': str, 'error': str}
        """
        try:
            order_id = self.broker_api.place_order(symbol, qty)
            return {'success': True, 'order_id': order_id, 'error': None}
        except Exception as e:
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
    
    generic_executor = GenericOrderExecutor(broker_name, broker_api, customer_id)
    
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
