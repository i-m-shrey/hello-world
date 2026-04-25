"""
Zerodha Broker API Wrapper - Simple order placement only
No retry logic (handled by generic executor)
"""
import logging
from kiteconnect import KiteConnect


def place_single_order_direct(client, symbol, qty, is_amo=False, ltp=None):
    """Direct order placement — uses LMT for all order types per SEBI mandate."""
    api_key = client.get('api_key', '').strip()
    access_token = client.get('access_token', '').strip()
    
    if not api_key or not access_token:
        raise Exception("Missing Zerodha credentials")
    
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    
    tradingsymbol = symbol.strip().upper()
    
    if is_amo:
        # Get live price from Yahoo Finance
        live_price = _get_live_price_yahoo(symbol)
        
        if live_price and live_price > 0:
            trigger_price = round(live_price * 1.10, 2)
            limit_price = round(live_price * 1.15, 2)
            print(f"[GTT] Yahoo price ₹{live_price}, trigger: ₹{trigger_price}, limit: ₹{limit_price}")
        else:
            # Higher fallback to avoid "trigger already met"
            live_price = 200
            trigger_price = 250
            limit_price = 300
            print(f"[GTT] ⚠️ Yahoo fetch failed, using high fallback: trigger ₹{trigger_price}")
        
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
        # Regular LMT order — SEBI mandate: MKT orders banned for API algo trading.
        # Use CSV LTP if provided, otherwise fetch live price.
        if not ltp or ltp <= 0:
            ltp = _get_live_price_yahoo(symbol) or 0
        if not ltp or ltp <= 0:
            raise Exception(f"LTP unavailable for {tradingsymbol} — cannot determine limit price")
        limit_price = round(ltp * 1.03, 2)
        print(f"[ZERODHA] LTP {ltp} → LMT @ {limit_price} for {tradingsymbol}")
        order_id = kite.place_order(
            kite.VARIETY_REGULAR,
            kite.EXCHANGE_NSE,
            tradingsymbol,
            kite.TRANSACTION_TYPE_BUY,
            qty,
            kite.PRODUCT_CNC,
            kite.ORDER_TYPE_LIMIT,
            price=limit_price,
            validity=kite.VALIDITY_DAY
        )
        return order_id


def _get_live_price_yahoo(symbol):
    """Fetch from Yahoo Finance"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        price = ticker.info.get('currentPrice') or ticker.info.get('regularMarketPrice')
        if price:
            return float(price)
    except Exception as e:
        print(f"[Yahoo] Failed for {symbol}: {e}")
    return None
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


def place_order(client, filtered_etfs_df, is_amo=False):
    """
    Place orders for multiple ETFs (DataFrame-based interface for compatibility)
    Used by app.py test order flow
    """
    order_type_label = "GTT" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {client.get('username', 'ZERODHA user')} via ZERODHA...")
    
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
            order_label = "GTT" if is_amo else "Order"
            print(f"→ {order_label} placed: {symbol} × {user_qty} | Order ID: {order_id}")
        except Exception as err:
            print(f"❌ Order failed for {symbol}: {err}")


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
