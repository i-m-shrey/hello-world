"""
Zerodha Broker API Wrapper - Simple order placement only
No retry logic (handled by generic executor)
"""
import logging
from kiteconnect import KiteConnect


def place_single_order_direct(client, symbol, qty, is_amo=False):
    """
    Direct order placement - no retry logic
    Raises exception if fails
    
    Returns:
        str: order_id
    """
    api_key = client.get('api_key', '').strip()
    access_token = client.get('access_token', '').strip()
    
    if not api_key or not access_token:
        raise Exception("Missing Zerodha credentials")
    
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    tradingsymbol = symbol.strip().upper()
    
    if is_amo:
        live_price = _get_live_price(kite, symbol) or 20
        trigger_price = round(live_price * 1.10, 2)
        limit_price = round(live_price * 1.15, 2)
        
        response = kite.place_gtt(
            trigger_type=kite.GTT_TYPE_SINGLE,
            tradingsymbol=tradingsymbol,
            exchange=kite.EXCHANGE_NSE,
            trigger_values=[trigger_price],
            last_price=live_price,
            orders=[{
                "transaction_type": kite.TRANSACTION_TYPE_BUY,
                "quantity": qty,
                "order_type": kite.ORDER_TYPE_LIMIT,
                "product": kite.PRODUCT_CNC,
                "price": limit_price
            }]
        )
        return response.get('trigger_id')
    else:
        order_id = kite.place_order(
            kite.VARIETY_REGULAR,
            kite.EXCHANGE_NSE,
            tradingsymbol,
            kite.TRANSACTION_TYPE_BUY,
            qty,
            kite.PRODUCT_CNC,
            kite.ORDER_TYPE_MARKET,
            validity=kite.VALIDITY_DAY
        )
        return order_id


def _get_live_price(kite, symbol):
    """Fetch live price from Kite"""
    try:
        quote = kite.quote(f"NSE:{symbol}")
        return float(quote[f"NSE:{symbol}"]["last_price"])
    except:
        return None


def get_available_funds(client):
    """Fetch available balance"""
    try:
        kite = KiteConnect(api_key=client.get('api_key'))
        kite.set_access_token(client.get('access_token'))
        
        margins = kite.margins()
        equity_margin = margins.get('equity', {})
        available = equity_margin.get('available', {}).get('cash', 0)
        
        logging.info(f"Zerodha balance for {client.get('customer_id')}: ₹{available}")
        return float(available)
    except Exception as e:
        logging.error(f"Failed to fetch Zerodha balance: {e}")
        raise
