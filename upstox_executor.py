"""
Upstox Order Executor - Places orders using Upstox API v2
"""
import logging
import upstox_client
from upstox_client.rest import ApiException


def get_tradingsymbol_upstox(symbol):
    """
    Convert symbol to Upstox tradingsymbol format
    
    Examples:
    - SBIN -> NSE_EQ|INE062A01020
    - NIFTYBEES -> NSE_EQ|INF204KA1LZ5
    
    For now, using simple format. Instrument key can be fetched via API if needed.
    """
    return f"NSE_EQ|{symbol}"


def place_order(account_info, filtered_etfs_df, is_amo=False):
    """
    Main order placement function for Upstox (called by broker_dispatcher)
    
    Args:
        account_info: Client data dict with access_token
        filtered_etfs_df: DataFrame with SYMBOL, QTY columns
        is_amo: True for After Market Order
    """
    order_type_label = "AMO" if is_amo else "regular"
    print(f"🚀 Placing {order_type_label} orders for {account_info.get('username', 'UPSTOX user')} via UPSTOX...")
    
    try:
        access_token = account_info.get('access_token', '').strip()
        
        if not access_token:
            print(f"❌ Missing UPSTOX access_token for {account_info.get('username')}")
            return
        
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        
        api_client = upstox_client.ApiClient(configuration)
        order_api = upstox_client.OrderApi(api_client)
        
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
            
            instrument_token = get_tradingsymbol_upstox(symbol)
            
            try:
                order_data = upstox_client.PlaceOrderRequest(
                    quantity=user_qty,
                    product='D',
                    validity='DAY' if not is_amo else 'DAY',
                    price=0.0,
                    tag='SmartETF',
                    instrument_token=instrument_token,
                    order_type='MARKET',
                    transaction_type='BUY',
                    disclosed_quantity=0,
                    trigger_price=0.0,
                    is_amo=is_amo
                )
                
                response = order_api.place_order(order_data, api_version='2.0')
                
                order_id = response.data.order_id if hasattr(response, 'data') else None
                print(f"→ Order placed: {symbol} × {user_qty} | Order ID: {order_id}")
            
            except ApiException as e:
                print(f"❌ Order failed for {symbol}: {e}")
            except Exception as err:
                print(f"❌ Order failed for {symbol}: {err}")
    
    except Exception as e:
        print(f"❌ Failed to process UPSTOX account {account_info.get('username')}: {e}")


def get_available_funds(client):
    """
    Fetch available balance for Upstox client
    
    Returns available cash balance
    """
    try:
        access_token = client.get('access_token', '').strip()
        
        if not access_token:
            raise Exception("No access_token available")
        
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        
        api_client = upstox_client.ApiClient(configuration)
        user_api = upstox_client.UserApi(api_client)
        
        response = user_api.get_user_fund_margin(api_version='2.0')
        
        if hasattr(response, 'data') and hasattr(response.data, 'equity'):
            available = response.data.equity.available_margin
            logging.info(f"Upstox balance for {client.get('customer_id')}: ₹{available}")
            return float(available)
        
        logging.warning(f"No fund data available for {client.get('customer_id')}")
        return 0.0
    
    except ApiException as e:
        logging.error(f"Failed to fetch Upstox balance for {client.get('customer_id')}: {e}")
        raise
    except Exception as e:
        logging.error(f"Failed to fetch Upstox balance for {client.get('customer_id')}: {e}")
        raise


def place_order_upstox(client, symbol, quantity, order_type='BUY', product='D', is_amo=False):
    """
    Place order on Upstox using API v2
    
    Args:
        client: Client data dict with access_token
        symbol: Trading symbol (e.g., 'SBIN', 'NIFTYBEES')
        quantity: Number of shares
        order_type: 'BUY' or 'SELL'
        product: 'D' (delivery), 'I' (intraday), 'CO' (cover order), 'OCO' (one cancels other)
        is_amo: True for After Market Order
    
    Returns:
        Order ID if successful
    """
    try:
        access_token = client.get('access_token', '').strip()
        
        if not access_token:
            raise Exception("No access_token available")
        
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        
        api_client = upstox_client.ApiClient(configuration)
        order_api = upstox_client.OrderApi(api_client)
        
        instrument_token = get_tradingsymbol_upstox(symbol)
        
        order_data = upstox_client.PlaceOrderRequest(
            quantity=int(quantity),
            product=product,
            validity='DAY',
            price=0.0,
            tag='SmartETF',
            instrument_token=instrument_token,
            order_type='MARKET',
            transaction_type=order_type,
            disclosed_quantity=0,
            trigger_price=0.0,
            is_amo=is_amo
        )
        
        logging.info(f"Placing Upstox order: {symbol} × {quantity}")
        
        response = order_api.place_order(order_data, api_version='2.0')
        
        order_id = response.data.order_id if hasattr(response, 'data') else None
        
        logging.info(f"Upstox order placed successfully: Order ID {order_id}")
        return order_id
    
    except ApiException as e:
        logging.error(f"Upstox order placement failed: {e}")
        raise
    except Exception as e:
        logging.error(f"Upstox order placement failed: {e}")
        raise


def execute_orders_for_upstox(session_manager, etf_orders, client):
    """
    Execute ETF orders for Upstox client
    
    Args:
        session_manager: MultibrokerSessionManager instance
        etf_orders: List of ETF orders with symbol, quantity
        client: Client data dict
    
    Returns:
        List of executed order results
    """
    results = []
    customer_id = client.get('customer_id')
    
    logging.info(f"Executing {len(etf_orders)} orders for Upstox client {customer_id}")
    
    for order in etf_orders:
        try:
            symbol = order.get('symbol')
            quantity = order.get('quantity')
            
            if not symbol or not quantity:
                logging.warning(f"Invalid order data: {order}")
                continue
            
            order_id = place_order_upstox(
                client=client,
                symbol=symbol,
                quantity=quantity,
                order_type='BUY',
                product='D'
            )
            
            results.append({
                'customer_id': customer_id,
                'symbol': symbol,
                'quantity': quantity,
                'order_id': order_id,
                'status': 'SUCCESS',
                'broker': 'UPSTOX'
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
                'broker': 'UPSTOX'
            })
    
    return results
