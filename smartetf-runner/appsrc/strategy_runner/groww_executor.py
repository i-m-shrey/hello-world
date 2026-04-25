"""
Groww Order Executor - Places orders using Groww API
"""
import logging
from growwapi import GrowwAPI


def get_tradingsymbol_groww(symbol):
    """
    Convert symbol to Groww tradingsymbol format
    
    Examples:
    - SBIN -> SBIN
    - NIFTYBEES -> NIFTYBEES
    
    Groww uses standard NSE symbols for equity trading
    """
    return symbol.strip().upper()


def place_order(account_info, filtered_etfs_df, is_amo=False):
    """
    Main order placement function for Groww (called by broker_dispatcher)
    
    Args:
        account_info: Client data dict with access_token
        filtered_etfs_df: DataFrame with SYMBOL, QTY columns
        is_amo: True for After Market Order
    """
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info.get('username', 'GROWW user')} via GROWW...")
    
    try:
        access_token = account_info.get('access_token', '').strip()
        
        if not access_token:
            print(f"❌ Missing GROWW access_token for {account_info.get('username')}")
            return
        
        groww = GrowwAPI(access_token)
        
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
            
            trading_symbol = get_tradingsymbol_groww(symbol)
            
            try:
                place_order_response = groww.place_order(
                    trading_symbol=trading_symbol,
                    quantity=user_qty,
                    validity=groww.VALIDITY_DAY,
                    exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_CASH,
                    product=groww.PRODUCT_CNC,
                    order_type=groww.ORDER_TYPE_MARKET,
                    transaction_type=groww.TRANSACTION_TYPE_BUY,
                    order_reference_id=f"SmartETF-{symbol}"
                )
                
                order_id = place_order_response.order_id if hasattr(place_order_response, 'order_id') else None
                print(f"→ Order placed: {symbol} × {user_qty} | Order ID: {order_id}")
            
            except Exception as err:
                print(f"❌ Order failed for {symbol}: {err}")
    
    except Exception as e:
        print(f"❌ Failed to process GROWW account {account_info.get('username')}: {e}")


def get_available_funds(client):
    """
    Fetch available balance for Groww client
    
    Returns available cash balance
    """
    try:
        access_token = client.get('access_token', '').strip()
        
        if not access_token:
            raise Exception("No access_token available")
        
        groww = GrowwAPI(access_token)
        
        user_fund_margin_response = groww.get_user_fund_margin()
        
        if hasattr(user_fund_margin_response, 'equity_amount'):
            available = user_fund_margin_response.equity_amount
            logging.info(f"Groww balance for {client.get('customer_id')}: ₹{available}")
            return float(available)
        
        logging.warning(f"No fund data available for {client.get('customer_id')}")
        return 0.0
    
    except Exception as e:
        logging.error(f"Failed to fetch Groww balance for {client.get('customer_id')}: {e}")
        raise


def place_order_groww(client, symbol, quantity, order_type='BUY', product='CNC', is_amo=False):
    """
    Place order on Groww using API
    
    Args:
        client: Client data dict with access_token
        symbol: Trading symbol (e.g., 'SBIN', 'NIFTYBEES')
        quantity: Number of shares
        order_type: 'BUY' or 'SELL'
        product: 'CNC' (delivery), 'MIS' (intraday), 'NRML' (normal)
        is_amo: True for After Market Order
    
    Returns:
        Order ID if successful
    """
    try:
        access_token = client.get('access_token', '').strip()
        
        if not access_token:
            raise Exception("No access_token available")
        
        groww = GrowwAPI(access_token)
        
        trading_symbol = get_tradingsymbol_groww(symbol)
        
        transaction_type = groww.TRANSACTION_TYPE_BUY if order_type == 'BUY' else groww.TRANSACTION_TYPE_SELL
        
        product_type = groww.PRODUCT_CNC
        if product == 'MIS':
            product_type = groww.PRODUCT_MIS
        elif product == 'NRML':
            product_type = groww.PRODUCT_NRML
        
        logging.info(f"Placing Groww order: {symbol} × {quantity}")
        
        place_order_response = groww.place_order(
            trading_symbol=trading_symbol,
            quantity=int(quantity),
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            product=product_type,
            order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=transaction_type,
            order_reference_id=f"SmartETF-{symbol}"
        )
        
        order_id = place_order_response.order_id if hasattr(place_order_response, 'order_id') else None
        
        logging.info(f"Groww order placed successfully: Order ID {order_id}")
        return order_id
    
    except Exception as e:
        logging.error(f"Groww order placement failed: {e}")
        raise


def execute_orders_for_groww(session_manager, etf_orders, client):
    """
    Execute ETF orders for Groww client
    
    Args:
        session_manager: MultibrokerSessionManager instance
        etf_orders: List of ETF orders with symbol, quantity
        client: Client data dict
    
    Returns:
        List of executed order results
    """
    results = []
    customer_id = client.get('customer_id')
    
    logging.info(f"Executing {len(etf_orders)} orders for Groww client {customer_id}")
    
    for order in etf_orders:
        try:
            symbol = order.get('symbol')
            quantity = order.get('quantity')
            
            if not symbol or not quantity:
                logging.warning(f"Invalid order data: {order}")
                continue
            
            order_id = place_order_groww(
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
                'broker': 'GROWW'
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
                'broker': 'GROWW'
            })
    
    return results
