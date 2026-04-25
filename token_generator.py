"""
Smart Token Generator - Works both locally and with Cloud Run service
"""
import os
import requests
import logging

TOKEN_SERVICE_URL = os.getenv('TOKEN_SERVICE_URL', '')
TOKEN_SERVICE_SECRET = os.getenv('TOKEN_SERVICE_SECRET', '')
USE_LOCAL_GENERATION = os.getenv('USE_LOCAL_TOKEN_GENERATION', 'false').lower() == 'true'
print("USE_LOCAL_TOKEN_GENERATION =", os.getenv("USE_LOCAL_TOKEN_GENERATION"))


def generate_broker_token(broker_name, **credentials):
    """
    Smart token generator that works both locally and on cloud
    
    - If TOKEN_SERVICE_URL is set: Uses Cloud Run token service
    - If not set or USE_LOCAL_GENERATION=true: Uses local token generation
    
    Args:
        broker_name: Name of the broker (DHAN, ZERODHA, etc.)
        **credentials: Broker-specific credentials
        
    Returns:
        dict with 'access_token' and optionally 'available_balance'
        
    Raises:
        Exception if token generation fails
    """
    broker_upper = broker_name.upper()
    
    # Use local generation if explicitly requested or service URL not set
    if USE_LOCAL_GENERATION or not TOKEN_SERVICE_URL:
        logging.info(f"🏠 Using LOCAL token generation for {broker_upper}")
        return _generate_token_locally(broker_upper, **credentials)
    else:
        logging.info(f"☁️ Using CLOUD token service for {broker_upper}")
        return _call_token_service(broker_upper, **credentials)


def _call_token_service(broker_name, **credentials):
    """Call the Cloud Run token service"""
    if not TOKEN_SERVICE_URL or not TOKEN_SERVICE_SECRET:
        raise RuntimeError(
            "TOKEN_SERVICE_URL and TOKEN_SERVICE_SECRET must be set for cloud token generation"
        )
    
    payload = {
        'broker_name': broker_name,
        **credentials
    }
    
    headers = {
        'X-Internal-Secret': TOKEN_SERVICE_SECRET,
        'Content-Type': 'application/json'
    }
    
    try:
        logging.info(f"Calling token service for {broker_name}...")
        url = f"{TOKEN_SERVICE_URL.rstrip('/')}/generate-token"
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        
        try:
            data = response.json()
        except Exception:
            data = {"error": response.text}
        
        if response.status_code == 200 and data.get('ok'):
            logging.info(f"✅ Token service success for {broker_name}")
            return {
                'access_token': data['access_token'],
                'available_balance': data.get('available_balance')
            }
        else:
            error_msg = data.get('error', f'HTTP {response.status_code}')
            logging.error(f"❌ Token service failed: {error_msg}")
            raise Exception(f"Token service failed: {error_msg}")
            
    except requests.exceptions.Timeout:
        raise Exception("Token service request timed out")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Token service request failed: {str(e)}")


def _generate_token_locally(broker_name, **credentials):
    """Generate token locally using existing OAuth modules"""
    
    if broker_name == 'DHAN':
        try:
            from dhan_oauth import generate_dhan_token
            from dhan_executor import get_available_funds
            
            access_token = generate_dhan_token(
                api_key=credentials['api_key'],
                api_secret=credentials['api_secret'],
                client_id=credentials['client_id'],
                mobile_number=credentials['mobile'],
                pin=credentials['pin'],
                totp_secret=credentials.get('totp_secret', '')
            )
            
            # Try to fetch balance
            balance = None
            try:
                client_info = {
                    'client_id': credentials['client_id'],
                    'api_key': credentials['api_key'],
                    'api_secret': credentials['api_secret'],
                    'access_token': access_token
                }
                balance = get_available_funds(client_info)
            except Exception as bal_err:
                logging.warning(f"Balance fetch failed: {bal_err}")
            
            return {
                'access_token': access_token,
                'available_balance': balance
            }
            
        except Exception as e:
            logging.error(f"Local DHAN token generation failed: {e}")
            raise Exception(f"DHAN token generation failed: {str(e)}")
    
    elif broker_name == 'ZERODHA':
        try:
            # Try HTTP method first
            try:
                from zerodha_oauth import generate_zerodha_token
                access_token = generate_zerodha_token(
                    api_key=credentials['api_key'],
                    api_secret=credentials['api_secret'],
                    user_id=credentials['user_id'],
                    password=credentials['password'],
                    totp_secret=credentials.get('totp_secret', '')
                )
            except Exception as http_err:
                # Fallback to Selenium
                logging.warning(f"HTTP method failed, trying Selenium: {http_err}")
                from zerodha_oauth_sel import generate_zerodha_token
                access_token = generate_zerodha_token(
                    api_key=credentials['api_key'],
                    api_secret=credentials['api_secret'],
                    user_id=credentials['user_id'],
                    password=credentials['password'],
                    totp_secret=credentials.get('totp_secret', '')
                )
            
            # Try to fetch balance
            balance = None
            try:
                from kiteconnect import KiteConnect
                kite = KiteConnect(api_key=credentials['api_key'])
                kite.set_access_token(access_token)
                margins = kite.margins()
                balance = float(margins.get('equity', {}).get('available', {}).get('live_balance', 0))
            except Exception as bal_err:
                logging.warning(f"Balance fetch failed: {bal_err}")
            
            return {
                'access_token': access_token,
                'available_balance': balance
            }
            
        except Exception as e:
            logging.error(f"Local ZERODHA token generation failed: {e}")
            raise Exception(f"ZERODHA token generation failed: {str(e)}")
    
    else:
        raise Exception(f"Unsupported broker for local generation: {broker_name}")
