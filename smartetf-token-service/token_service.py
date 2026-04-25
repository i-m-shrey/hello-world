from flask import Flask, request, jsonify
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

INTERNAL_SECRET = os.getenv('INTERNAL_SECRET')
if not INTERNAL_SECRET:
    raise RuntimeError("INTERNAL_SECRET environment variable must be set. Cannot start without it.")

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/generate-token', methods=['POST'])
def generate_token():
    auth_header = request.headers.get('X-Internal-Secret', '')
    if auth_header != INTERNAL_SECRET:
        logging.warning(f"Unauthorized access attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    broker = data.get('broker_name', '').upper()
    
    try:
        if broker == 'DHAN':
            from dhan_oauth import generate_dhan_token
            
            token = generate_dhan_token(
                api_key=data['api_key'],
                api_secret=data['api_secret'],
                client_id=data['client_id'],
                mobile_number=data['mobile'],
                pin=data['pin'],
                totp_secret=data.get('totp_secret', '')
            )
            
            balance = None
            try:
                from dhan_api import DhanAPI, DhanAuth
                auth = DhanAuth(client_id=data['client_id'], access_token=token)
                dhan_api = DhanAPI(auth)
                fund_data = dhan_api.get_fund_limit()
                
                if 'availabelBalance' in fund_data:
                    balance = float(fund_data['availabelBalance'])
                elif 'data' in fund_data and 'availabelBalance' in fund_data['data']:
                    balance = float(fund_data['data']['availabelBalance'])
                elif 'availableBalance' in fund_data:
                    balance = float(fund_data['availableBalance'])
                    
                logging.info(f"✅ DHAN balance fetched: ₹{balance}")
            except Exception as balance_err:
                logging.warning(f"⚠️ DHAN balance fetch failed: {balance_err}")
            
            logging.info(f"✅ DHAN token generated successfully")
            return jsonify({
                'ok': True,
                'access_token': token,
                'available_balance': balance,
                'broker_name': 'DHAN'
            })
            
        elif broker == 'ZERODHA':
            token = None
            method_used = None
            
            try:
                from zerodha_oauth import generate_zerodha_token as generate_zerodha_http
                logging.info(f"🔄 Attempting ZERODHA token generation via HTTP...")
                token = generate_zerodha_http(
                    api_key=data['api_key'],
                    api_secret=data['api_secret'],
                    user_id=data['user_id'],
                    password=data['password'],
                    totp_secret=data.get('totp_secret', '')
                )
                method_used = 'HTTP'
                logging.info(f"✅ ZERODHA token generated successfully via HTTP")
            except Exception as http_error:
                logging.warning(f"⚠️ HTTP method failed: {str(http_error)}")
                logging.info(f"🔄 Falling back to Selenium method...")
                
                try:
                    from zerodha_oauth_sel import generate_zerodha_token as generate_zerodha_sel
                    token = generate_zerodha_sel(
                        api_key=data['api_key'],
                        api_secret=data['api_secret'],
                        user_id=data['user_id'],
                        password=data['password'],
                        totp_secret=data.get('totp_secret', '')
                    )
                    method_used = 'Selenium'
                    logging.info(f"✅ ZERODHA token generated successfully via Selenium")
                except Exception as sel_error:
                    logging.error(f"❌ Both methods failed. HTTP: {http_error}, Selenium: {sel_error}")
                    raise Exception(f"HTTP failed: {http_error}. Selenium failed: {sel_error}")
            
            if not token:
                raise Exception("Failed to generate Zerodha token")
            
            balance = None
            try:
                from kiteconnect import KiteConnect
                kite = KiteConnect(api_key=data['api_key'])
                kite.set_access_token(token)
                margins = kite.margins()
                balance = float(margins.get('equity', {}).get('available', {}).get('live_balance', 0))
                logging.info(f"✅ ZERODHA balance fetched: ₹{balance}")
            except Exception as balance_err:
                logging.warning(f"⚠️ ZERODHA balance fetch failed: {balance_err}")
            
            return jsonify({
                'ok': True,
                'access_token': token,
                'available_balance': balance,
                'broker_name': 'ZERODHA',
                'method': method_used
            })
            
        else:
            return jsonify({'error': f'Unsupported broker: {broker}'}), 400
            
    except Exception as e:
        logging.error(f"Token generation failed for {broker}: {str(e)}")
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
