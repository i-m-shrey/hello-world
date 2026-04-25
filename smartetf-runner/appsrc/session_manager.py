"""
Multi-Broker Session Manager - Maintains persistent sessions for all clients
Supports any broker: Finvasia, Upstox, Dhan, HDFC, ICICI, mStock, etc.
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from client_fetcher import get_active_clients_with_sip
from account import Account
from dhan_api import DhanAPI, DhanAuth
from dhan_oauth import generate_dhan_token
from zerodha_oauth import generate_zerodha_token
from kiteconnect import KiteConnect
from proxy_utils import client_proxy_context, get_client_proxy
import logging
import time
from datetime import datetime

# ── BLOCKED_BROKER_IDS ─────────────────────────────────────────────────
# Shared with etf_automated.py and morning_health_check.py.
# Add any user_id_broker here to skip from session init entirely.
BLOCKED_BROKER_IDS: frozenset = frozenset()
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MultibrokerSessionManager:
    """
    Maintains persistent sessions for all clients across all brokers
    - Login once, use multiple times
    - Session validation and auto-renewal
    - Multi-broker support (Finvasia, Upstox, Dhan, etc.)
    - Error tracking and notifications
    """
    
    def __init__(self):
        self.client_sessions = {}  # {client_id: session_info}
        self.failed_sessions = {}  # {client_id: error_info}
        self.password_rotations = []  # Track password rotations
        self.session_stats = {
            'total_clients': 0,
            'successful_sessions': 0,
            'failed_sessions': 0,
            'last_update': None
        }

    def _create_account_object(self, client):
        """Create appropriate Account object based on broker type"""
        broker_name = client.get('broker_name', '').upper()

        if broker_name == 'FINVASIA':
            return Account(
                user_id=client['user_id_broker'],
                password=client['password'],
                totp_secret=client['totp_secret'],
                vendor_code=client['vendor_code'],
                api_secret=client['api_secret'],
                imei=client['imei'],
                is_master=client.get('is_master', False),
                multiplier=client.get('copy_multiplier', 1),
                copy=client.get('copy', True)
            )

        elif broker_name == 'DHAN':
            client_id = client.get('dhan_client_id', '').strip()
            api_key = client.get('api_key', '').strip()
            api_secret = client.get('api_secret', '').strip()
            pin = client.get('password', '').strip()
            totp_secret = client.get('totp_secret', '').strip()
            mobile = client.get('mobile', '').strip()
            existing_token = client.get('access_token', '').strip()

            if not all([client_id, api_key, api_secret]):
                raise Exception("Missing DHAN credentials: need client_id, api_key, api_secret")

            if not mobile:
                if not existing_token:
                    raise Exception("Missing mobile number for DHAN token generation. Please update broker details with mobile.")
                logging.warning(f"DHAN {client.get('customer_id')}: Using existing token (mobile missing for renewal)")
                auth = DhanAuth(client_id=client_id, access_token=existing_token)
                return DhanAPI(auth)

            if not all([pin]):
                if not existing_token:
                    raise Exception("Missing PIN for DHAN token generation")
                logging.warning(f"DHAN {client.get('customer_id')}: Using existing token (PIN missing)")
                auth = DhanAuth(client_id=client_id, access_token=existing_token)
                return DhanAPI(auth)

            try:
                new_token = generate_dhan_token(api_key, api_secret, client_id, mobile, pin, totp_secret)
                client['access_token'] = new_token

                from app import app, db
                from models import Broker
                with app.app_context():
                    broker = db.session.get(Broker, client.get('broker_id'))
                    if broker:
                        broker.access_token = new_token
                        broker.last_updated = datetime.utcnow()
                        db.session.commit()
                        logging.info(f"DHAN token generated for {client.get('customer_id')}")
            except Exception as e:
                logging.error(f"DHAN token generation failed for {client.get('customer_id')}: {e}")
                if existing_token:
                    logging.warning(f"DHAN {client.get('customer_id')}: Falling back to existing token")
                    auth = DhanAuth(client_id=client_id, access_token=existing_token)
                    return DhanAPI(auth)
                raise Exception(f"Token generation failed: {e}")

            auth = DhanAuth(client_id=client_id, access_token=new_token)
            return DhanAPI(auth)

        elif broker_name == 'ZERODHA':
            api_key = client.get('api_key', '').strip()
            api_secret = client.get('api_secret', '').strip()
            user_id = client.get('user_id_broker', '').strip()
            password = client.get('password', '').strip()
            totp_secret = client.get('totp_secret', '').strip()
            existing_token = client.get('access_token', '').strip()

            if not all([api_key, api_secret, user_id, password, totp_secret]):
                raise Exception("Missing ZERODHA credentials")

            try:
                new_token = generate_zerodha_token(api_key, api_secret, user_id, password, totp_secret)
                client['access_token'] = new_token

                from app import app, db
                from models import Broker
                with app.app_context():
                    broker = db.session.get(Broker, client.get('broker_id'))
                    if broker:
                        broker.access_token = new_token
                        broker.last_updated = datetime.utcnow()
                        db.session.commit()
                        logging.info(f"ZERODHA token generated for {client.get('customer_id')}")
            except Exception as e:
                logging.error(f"ZERODHA token generation failed: {e}")
                if existing_token:
                    logging.warning(f"ZERODHA: Falling back to existing token")
                    client['access_token'] = existing_token
                else:
                    raise Exception(f"Token generation failed: {e}")

            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(client['access_token'])
            return kite

        elif broker_name in ['UPSTOX', 'ANGEL', 'ANGELONE', 'ANGLE', 'GROWW']:
            return None

        elif broker_name in ['HDFC', 'ICICI', 'MSTOCK']:
            return None

        else:
            logging.warning(f"Unknown broker: {broker_name}")
            return None

    def initialize_all_sessions(self, allowed_customer_ids=None):
        """Initialize sessions for all active clients.

        allowed_customer_ids: optional set of customer_id strings.
          If provided, only those clients are initialised (used by DEBUG mode).
        """
        print("🔐 Initializing Multi-Broker Sessions...")

        # Get all active clients from database
        clients = get_active_clients_with_sip()

        # DEBUG mode: restrict to pre-selected clients
        if allowed_customer_ids is not None:
            clients = [c for c in clients if c.get('customer_id') in allowed_customer_ids]

        self.session_stats['total_clients'] = len(clients)

        if not clients:
            print("⚠️ No active clients found")
            return False

        print(f"👥 Found {len(clients)} active clients")

        # Group clients by broker
        clients_by_broker = {}
        for client in clients:
            broker = client.get('broker_name', 'UNKNOWN')
            if broker not in clients_by_broker:
                clients_by_broker[broker] = []
            clients_by_broker[broker].append(client)

        # Initialize sessions for each broker
        for broker_name, broker_clients in clients_by_broker.items():
            print(f"\n🏦 Processing {broker_name}: {len(broker_clients)} clients")
            self._initialize_broker_sessions(broker_name, broker_clients)

        # Update stats
        self.session_stats['successful_sessions'] = len(self.client_sessions)
        self.session_stats['failed_sessions'] = len(self.failed_sessions)
        self.session_stats['last_update'] = datetime.now()

        # Print summary
        print(f"\n📊 Session Initialization Summary:")
        print(f"  ✅ Successful: {self.session_stats['successful_sessions']}")
        print(f"  ❌ Failed: {self.session_stats['failed_sessions']}")
        print(f"  📈 Success Rate: {(self.session_stats['successful_sessions']/self.session_stats['total_clients']*100):.1f}%")

        return self.session_stats['successful_sessions'] > 0


    def _initialize_broker_sessions(self, broker_name, clients):
        """Initialize sessions for a specific broker's clients"""
        for client in clients:
            client_id = client.get('customer_id', 'unknown')
            user_id_broker = client.get('user_id_broker', '')

            # Skip permanently blocked broker IDs — wrong vendor_code in Finvasia
            # API portal. Attempting login wastes time and contributes to lockouts.
            if user_id_broker in BLOCKED_BROKER_IDS:
                print(f"  ⛔ Skipping {client_id} ({user_id_broker}) — in BLOCKED_BROKER_IDS")
                self.failed_sessions[client_id] = {
                    'client_info': client,
                    'broker_name': broker_name,
                    'error': f'Skipped: {user_id_broker} in BLOCKED_BROKER_IDS (ALGO_CHK)',
                    'timestamp': datetime.now(),
                }
                continue

            try:
                print(f"🔑 Logging in: {client_id} ({broker_name})")

                # Groww manages its own token refresh via _refresh_groww_tokens.
                # Mark as self-managed success rather than a failure.
                if broker_name.upper() == 'GROWW':
                    self.client_sessions[client_id] = {
                        'client_info': client,
                        'account_object': None,
                        'session': 'self-managed',
                        'broker_name': broker_name,
                        'login_time': 0,
                        'login_timestamp': datetime.now(),
                        'status': 'active',
                    }
                    print(f"  ✅ GROWW: {client_id} — token managed by refresh step")
                    continue

                with client_proxy_context(get_client_proxy(client)):
                    # Create account object
                    account = self._create_account_object(client)

                    if not account:
                        raise Exception(f"Broker {broker_name} not yet supported")

                    # Attempt login with a per-client timeout so blocked/stuck
                    # accounts don't hang the health check indefinitely.
                    LOGIN_TIMEOUT = 90  # seconds — covers 3 QuickAuth attempts + TOTP waits
                    login_start = time.time()

                    if broker_name == 'DHAN':
                        session = account
                        login_time = time.time() - login_start
                    elif broker_name == 'ZERODHA':
                        session = account
                        login_time = time.time() - login_start
                    elif hasattr(account, 'login'):
                        login_exc = [None]
                        def _do_login():
                            try:
                                account.login()
                            except Exception as _e:
                                login_exc[0] = _e
                        _t = threading.Thread(target=_do_login, daemon=True)
                        _t.start()
                        _t.join(timeout=LOGIN_TIMEOUT)
                        if _t.is_alive():
                            raise Exception(f"Login timed out after {LOGIN_TIMEOUT}s (broker unresponsive or account blocked)")
                        if login_exc[0]:
                            raise login_exc[0]
                        login_time = time.time() - login_start
                        session = account.session
                    else:
                        raise Exception("Invalid account object")

                # Validate session
                is_valid = False
                if broker_name == 'DHAN':
                    is_valid = isinstance(account, DhanAPI)
                elif broker_name == 'ZERODHA':
                    is_valid = isinstance(account, KiteConnect)
                elif session and hasattr(session, 'place_order'):
                    is_valid = True

                if is_valid:
                    self.client_sessions[client_id] = {
                        'client_info': client,
                        'account_object': account,
                        'session': session if broker_name not in ['DHAN', 'ZERODHA'] else account,
                        'broker_name': broker_name,
                        'login_time': login_time,
                        'login_timestamp': datetime.now(),
                        'status': 'active'
                    }

                    print(f"  ✅ Success: {client_id} ({login_time:.2f}s)")

                else:
                    raise Exception("Session validation failed")
                    
            except Exception as e:
                # Session failed
                self.failed_sessions[client_id] = {
                    'client_info': client,
                    'broker_name': broker_name,
                    'error': str(e),
                    'timestamp': datetime.now()
                }
                
                print(f"  ❌ Failed: {client_id} - {e}")
    
    def get_active_session(self, client_id):
        """Get active session for a client"""
        return self.client_sessions.get(client_id)
    
    def validate_session(self, client_id):
        """Validate if a client's session is still active"""
        session_info = self.client_sessions.get(client_id)
        
        if not session_info:
            return False
        
        # Here you would add broker-specific session validation
        # For now, assume session is valid if it exists
        return session_info['status'] == 'active'
    
    def refresh_session(self, client_id):
        """Refresh a specific client's session"""
        if client_id not in self.client_sessions:
            return False
        
        client_info = self.client_sessions[client_id]['client_info']
        broker_name = self.client_sessions[client_id]['broker_name']
        
        # Remove old session
        del self.client_sessions[client_id]
        
        # Re-initialize
        self._initialize_broker_sessions(broker_name, [client_info])
        
        return client_id in self.client_sessions
    
    def get_session_summary(self):
        """Get summary of all sessions"""
        summary = {
            'active_sessions': len(self.client_sessions),
            'failed_sessions': len(self.failed_sessions),
            'total_clients': self.session_stats['total_clients'],
            'last_update': self.session_stats['last_update'],
            'broker_breakdown': {}
        }
        
        # Broker breakdown
        for session_info in self.client_sessions.values():
            broker = session_info['broker_name']
            if broker not in summary['broker_breakdown']:
                summary['broker_breakdown'][broker] = {'active': 0, 'failed': 0}
            summary['broker_breakdown'][broker]['active'] += 1
        
        for failed_info in self.failed_sessions.values():
            broker = failed_info['broker_name']
            if broker not in summary['broker_breakdown']:
                summary['broker_breakdown'][broker] = {'active': 0, 'failed': 0}
            summary['broker_breakdown'][broker]['failed'] += 1
        
        return summary
    
    def get_failed_clients(self):
        """Get list of failed client sessions with error details"""
        failed_list = []
        for client_id, failed_info in self.failed_sessions.items():
            failed_list.append({
                'client_id': client_id,
                'broker': failed_info['broker_name'],
                'error': failed_info['error'],
                'timestamp': failed_info['timestamp'],
                'email': failed_info['client_info'].get('email', 'Not available')
            })
        return failed_list
    
    def cleanup_sessions(self):
        """Clean up all sessions"""
        print("🧹 Cleaning up sessions...")
        
        for client_id, session_info in self.client_sessions.items():
            try:
                # Close session if possible
                account = session_info['account_object']
                if hasattr(account, 'session') and hasattr(account.session, 'close'):
                    account.session.close()
            except Exception as e:
                logging.warning(f"Error closing session for {client_id}: {e}")
        
        self.client_sessions.clear()
        self.failed_sessions.clear()
        
        print("✅ Session cleanup complete")


# Test function
def test_session_manager():
    """Test the session manager"""
    print("🧪 Testing Multi-Broker Session Manager")
    print("=" * 50)
    
    manager = MultibrokerSessionManager()
    
    # Initialize sessions
    success = manager.initialize_all_sessions()
    
    if success:
        # Get summary
        summary = manager.get_session_summary()
        print(f"\n📊 Session Summary:")
        for broker, stats in summary['broker_breakdown'].items():
            print(f"  🏦 {broker}: {stats['active']} active, {stats['failed']} failed")
        
        # Get failed clients
        failed_clients = manager.get_failed_clients()
        if failed_clients:
            print(f"\n❌ Failed Clients:")
            for failed in failed_clients[:3]:  # Show first 3
                print(f"  • {failed['client_id']} ({failed['broker']}): {failed['error']}")
    
    # Cleanup
    manager.cleanup_sessions()
    
    return success


if __name__ == "__main__":
    test_session_manager()