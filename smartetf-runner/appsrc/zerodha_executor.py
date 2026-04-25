"""
Zerodha Order Executor - Places orders using Kite Connect API
"""
import logging
from kiteconnect import KiteConnect


def get_live_price_yahoo(symbol):
    """
    Fetch live price from Yahoo Finance
    
    Args:
        symbol: Trading symbol (e.g., 'PHARMABEES')
    
    Returns:
        float: Current price or None if fetch fails
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        price = ticker.info.get('currentPrice') or ticker.info.get('regularMarketPrice')
        if price:
            print(f"[Yahoo Finance] {symbol} price: ₹{price}")
            return float(price)
    except Exception as e:
        print(f"[Yahoo Finance] Failed to fetch price for {symbol}: {e}")
    return None


def get_tradingsymbol_zerodha(symbol):
    """
    Convert symbol to Zerodha tradingsymbol format
    
    Examples:
    - SBIN -> SBIN
    - NIFTYBEES -> NIFTYBEES
    - SBIETF -> SBIETF
    
    Zerodha uses plain symbol names for NSE stocks/ETFs
    """
    return symbol.strip().upper()


def place_order(account_info, filtered_etfs_df, is_amo=False):
    """
    Main order placement function for Zerodha (called by broker_dispatcher)
    
    Args:
        account_info: Client data dict with api_key, access_token
        filtered_etfs_df: DataFrame with SYMBOL, QTY columns
        is_amo: True for GTT order (Good Till Triggered)
    """
    order_type_label = "GTT" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info.get('username', 'ZERODHA user')} via ZERODHA...")
    
    try:
        api_key = account_info.get('api_key', '').strip()
        access_token = account_info.get('access_token', '').strip()
        
        if not api_key:
            print(f"❌ Missing ZERODHA api_key for {account_info.get('username')}")
            return
        
        if not access_token:
            print(f"❌ Missing ZERODHA access_token for {account_info.get('username')}")
            return
        
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        
        multiplier = int(account_info.get('copy_multiplier', 1))
        
        for _, row in filtered_etfs_df.iterrows():
            symbol = str(row.get('SYMBOL', '')).strip()
            if not symbol:
                continue
            
            try:
                user_qty = int(row['USER_QTY'])
            except Exception:
                user_qty = int(row['QTY']) * multiplier if row.get('QTY', 0) >= 1 else 0
            
            if user_qty < 1:
                continue
            
            tradingsymbol = get_tradingsymbol_zerodha(symbol)
            
            try:
                if is_amo:
                    live_price = get_live_price_yahoo(symbol)
                    if live_price:
                        trigger_price = round(live_price * 1.10, 2)  # Changed: 10% above current
                        limit_price = round(live_price * 1.15, 2)  # Changed: 15% above current
                        print(
                            f"[GTT] Using Yahoo price ₹{live_price}, trigger: ₹{trigger_price}, limit: ₹{limit_price}")
                    else:
                        live_price = 20
                        trigger_price = 25
                        limit_price = 30
                        print(f"[GTT] Failed to fetch live price, using fallback")

                    gtt_order = kite.place_gtt(
                        trigger_type=kite.GTT_TYPE_SINGLE,
                        tradingsymbol=tradingsymbol,
                        exchange=kite.EXCHANGE_NSE,
                        trigger_values=[trigger_price],
                        last_price=live_price,  # Changed: use actual live_price, not trigger
                        orders=[{
                            "transaction_type": kite.TRANSACTION_TYPE_BUY,
                            "quantity": user_qty,
                            "order_type": kite.ORDER_TYPE_LIMIT,
                            "product": kite.PRODUCT_CNC,
                            "price": limit_price
                        }]
                    )
                    order_id = gtt_order.get('trigger_id')
                    print(f"→ GTT order placed: {symbol} × {user_qty} | GTT ID: {order_id}")
                else:
                    # Use LIMIT order with LTP from the ETF data to avoid API rejection
                    # SEBI requires LIMIT orders for API algo trading
                    ltp_price = float(row.get('LTP', 0))
                    if ltp_price > 0:
                        # Add 3% buffer for BUY orders to ensure fill
                        limit_price = round(ltp_price * 1.03, 2)
                        order_id = kite.place_order(
                            kite.VARIETY_REGULAR,
                            kite.EXCHANGE_NSE,
                            tradingsymbol,
                            kite.TRANSACTION_TYPE_BUY,
                            user_qty,
                            kite.PRODUCT_CNC,
                            kite.ORDER_TYPE_LIMIT,
                            price=limit_price,
                            validity=kite.VALIDITY_DAY
                        )
                        print(f"  [ZERODHA] Using LIMIT @ {limit_price} for {symbol}")
                    else:
                        # Fallback to default price
                        order_id = kite.place_order(
                            kite.VARIETY_REGULAR,
                            kite.EXCHANGE_NSE,
                            tradingsymbol,
                            kite.TRANSACTION_TYPE_BUY,
                            user_qty,
                            kite.PRODUCT_CNC,
                            kite.ORDER_TYPE_LIMIT,
                            price=20.0,
                            validity=kite.VALIDITY_DAY
                        )
                
                print(f"→ Order placed: {symbol} × {user_qty} | Order ID: {order_id}")
            except Exception as err:
                print(f"❌ Order failed for {symbol}: {err}")
    
    except Exception as e:
        print(f"❌ Failed to process ZERODHA account {account_info.get('username')}: {e}")


def get_available_funds(client):
    """
    Fetch available balance for Zerodha client
    
    Returns available cash balance
    """
    try:
        kite = KiteConnect(api_key=client.get('api_key'))
        kite.set_access_token(client.get('access_token'))
        
        margins = kite.margins()
        
        equity_margin = margins.get('equity', {})
        available = equity_margin.get('available', {}).get('cash', 0)
        
        logging.info(f"Zerodha balance for {client.get('customer_id')}: ₹{available}")
        return float(available)
    
    except Exception as e:
        logging.error(f"Failed to fetch Zerodha balance for {client.get('customer_id')}: {e}")
        raise


def place_order_zerodha(client, symbol, quantity, order_type='BUY', product='CNC', is_amo=False):
    """
    Place order on Zerodha using Kite Connect API
    
    Args:
        client: Client data dict with api_key, access_token
        symbol: Trading symbol (e.g., 'SBIN', 'NIFTYBEES')
        quantity: Number of shares
        order_type: 'BUY' or 'SELL'
        product: 'CNC' (delivery), 'MIS' (intraday), 'NRML' (normal)
        is_amo: True for After Market Order
    
    Returns:
        Order ID if successful
    """
    try:
        kite = KiteConnect(api_key=client.get('api_key'))
        kite.set_access_token(client.get('access_token'))
        
        tradingsymbol = get_tradingsymbol_zerodha(symbol)
        
        # SEBI requires LIMIT orders for API algo trading - no MARKET orders allowed
        order_params = {
            'tradingsymbol': tradingsymbol,
            'exchange': 'NSE',
            'transaction_type': order_type,
            'quantity': int(quantity),
            'order_type': 'LIMIT',  # Always use LIMIT - MARKET not allowed via API
            'product': product,
            'validity': 'AMO' if is_amo else 'DAY'
        }
        
        # Get price for LIMIT order
        if is_amo:
            # For AMO, try to get live price
            live_price = get_live_price_yahoo(symbol)
            if live_price:
                order_params['price'] = round(live_price * 1.03, 2)  # 3% above for BUY
            else:
                order_params['price'] = 20.0  # Default fallback
        else:
            # For regular orders, price is required for LIMIT orders
            # The caller should pass the price or we'll use a default
            order_params['price'] = order_params.get('price', 20.0)
        
        logging.info(f"Placing Zerodha order: {order_params}")
        
        order_id = kite.place_order(
            kite.VARIETY_REGULAR,
            order_params['exchange'],
            order_params['tradingsymbol'],
            order_params['transaction_type'],
            order_params['quantity'],
            order_params['product'],
            order_params['order_type'],
            price=order_params.get('price'),
            validity=order_params['validity']
        )
        
        logging.info(f"Zerodha order placed successfully: Order ID {order_id}")
        return order_id
    
    except Exception as e:
        logging.error(f"Zerodha order placement failed: {e}")
        raise


def execute_orders_for_zerodha(session_manager, etf_orders, client):
    """
    Execute ETF orders for Zerodha client
    
    Args:
        session_manager: MultibrokerSessionManager instance
        etf_orders: List of ETF orders with symbol, quantity
        client: Client data dict
    
    Returns:
        List of executed order results
    """
    results = []
    customer_id = client.get('customer_id')
    
    logging.info(f"Executing {len(etf_orders)} orders for Zerodha client {customer_id}")
    
    for order in etf_orders:
        try:
            symbol = order.get('symbol')
            quantity = order.get('quantity')
            
            if not symbol or not quantity:
                logging.warning(f"Invalid order data: {order}")
                continue
            
            order_id = place_order_zerodha(
                client=client,
                symbol=symbol,
                quantity=quantity,
                order_type='BUY',
                product='CNC'
            )
            
            results.append({
                'customer_id': customer_id,
                'symbol': symbol,
                'quantity': quantity,
                'order_id': order_id,
                'status': 'SUCCESS',
                'broker': 'ZERODHA'
            })
        
        except Exception as e:
            logging.error(f"Order failed for {customer_id} - {symbol}: {e}")
            results.append({
                'customer_id': customer_id,
                'symbol': symbol,
                'quantity': quantity,
                'order_id': None,
                'status': 'FAILED',
                'error': str(e),
                'broker': 'ZERODHA'
            })
    
    return results
