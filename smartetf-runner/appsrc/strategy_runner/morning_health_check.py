"""
Morning Health Check System - Daily validation of all systems

1. Session maintenance for every client (find errors, email admin)
2. ETF CSV fetching test (network, API issues)

Note: Selenium/ChromeDriver removed. Login uses pure-API flow via
finvasia_oauth.generate_finvasia_token (QuickAuth + pycurl GenAcsTok).
"""



import sys

import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))



from session_manager import MultibrokerSessionManager

try:
    from groww_broker_api import refresh_groww_token_for_client, get_available_funds as groww_get_funds
    _GROWW_AVAILABLE = True
except ImportError:
    _GROWW_AVAILABLE = False
    refresh_groww_token_for_client = None
    groww_get_funds = None
from email_notifications import send_email, send_admin_alert_email, send_client_notification_email, send_finvasia_password_reset_email
from app_utils.shoonya_password_util import change_password_for_client  # used by finvasia_password_utils (kept for compatibility)
from finvasia_broker_api import get_available_funds
from proxy_utils import client_proxy_context, get_client_proxy

import logging

from datetime import datetime

import json

import time

import traceback



# Access app + DB models for subscription promotion

from app import app

from models import db, Subscription, User, Broker, Plan, SchedulerSettings



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Broker user IDs permanently blocked from password-reset attempts and order
# placement. These accounts have an API config issue (ALGO_CHK / wrong
# vendor_code) that cannot be fixed by rotating the password.
# Keeping them here prevents the health check from sending false-alarm emails
# and wasting login attempts on accounts that can never trade.

# ── DEBUG mode ─────────────────────────────────────────────────────────────
# Set True to get a yes/no prompt before processing each client, and to see
# passwords printed to console before any rotation attempt.
DEBUG = True

# ── BLOCKED_BROKER_IDS ─────────────────────────────────────────────────
# Add any user_id_broker here to permanently skip that client from ALL
# order placement and health check sessions.
# Example: frozenset({'FN148473', 'FA55537'})
BLOCKED_BROKER_IDS: frozenset = frozenset()





class MorningHealthChecker:

    """

    Daily morning health check system

    - Promotes queued subscriptions that have reached start_date

    - Tests all client sessions across all brokers

    - Updates broker balances on successful session

    - ChromeDriver health check

    - Sends detailed email reports to admin

    """



    def __init__(self, admin_email=None):

        if not admin_email:

            admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')

        self.admin_email = admin_email

        self.health_report = {

            'timestamp': datetime.now(),

            'subscription_activation': {

                'activated_count': 0,

                'activated': []

            },

            'balance_update': {

                'updated_count': 0,

                'failed': []

            },

            'low_balance_alerts': {

                'threshold_percent': None,

                'alerts': []

            },

            'session_check': {},

            'etf_fetch_check': {},

            'chrome_driver_check': {'status': 'N/A', 'note': 'Selenium removed — pure API login'},

            'overall_status': 'UNKNOWN',

            'critical_issues': [],

            'warnings': [],

            'recommendations': []

        }

        self.session_manager = None



    def run_complete_health_check(self):

        print("🌅 SmartETF Morning Health Check")

        print("=" * 50)

        print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")



        print("\n0️⃣ PROMOTING QUEUED SUBSCRIPTIONS (IF DUE)")

        print("-" * 30)

        self._promote_queued_subscriptions()



        print("\n1️⃣ CLIENT SESSION HEALTH CHECK")

        print("-" * 30)

        self._check_client_sessions()



        # 1b: Refresh GROWW tokens (self-managed brokers)

        self._refresh_groww_tokens()



        print("\n2️⃣ FETCHING BROKER BALANCES")

        print("-" * 30)

        self._update_broker_balances()



        # Step 4: Generate Overall Status

        print("\n4️⃣ GENERATING HEALTH REPORT")

        print("-" * 30)

        self._generate_overall_status()



        # Step 5: Send Email Report

        self._send_health_report_email()



        # Step 6: Save Report

        self._save_health_report()

        if self.session_manager:
            try:
                self.session_manager.cleanup_sessions()
            except Exception as cleanup_error:
                logging.warning(f"Session cleanup warning: {cleanup_error}")
            finally:
                self.session_manager = None

        print("\n✅ Morning health check completed")

        return self.health_report['overall_status'] in ['HEALTHY', 'WARNING']
    
    def _promote_queued_subscriptions(self):
        """Activate queued subscriptions whose start_date has arrived and notify admin."""
        activated = []
        try:
            with app.app_context():
                # Use UTC-safe comparison by default; DB timestamps are typically UTC
                now = datetime.utcnow()
                due = Subscription.query.filter(
                    Subscription.payment_status.in_(['Successful', 'Paid', 'Active']),
                    Subscription.is_queued.is_(True),
                    Subscription.start_date <= now,
                    Subscription.expiry_date > now
                ).all()

                for sub in due:
                    sub.is_queued = False
                    user = User.query.filter_by(customer_id=sub.customer_id).first()
                    # Update all brokers for this user
                    if user:
                        brokers = Broker.query.filter_by(user_id=user.id).all()
                        for b in brokers:
                            b.subscription_status = 'Active'
                            b.subscription_expiry = sub.expiry_date
                            b.plan_id = sub.plan_id
                            # Enable Algo Investment if plan supports it
                            try:
                                if sub.plan and getattr(sub.plan, 'has_copy_trading', False):
                                    b.copy = True
                            except Exception:
                                pass
                    activated.append({
                        'customer_id': sub.customer_id,
                        'plan_name': sub.plan_name,
                        'start_date': str(sub.start_date),
                        'expiry_date': str(sub.expiry_date)
                    })
                if due:
                    db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            self.health_report['warnings'].append(f"Queued subscription promotion error: {e}")
            print(f"  ❌ Promotion error: {e}")
            activated = []
        
        # Save into report and optionally email
        self.health_report['subscription_activation']['activated'] = activated
        self.health_report['subscription_activation']['activated_count'] = len(activated)
        if activated:
            print(f"  ✅ Activated {len(activated)} queued subscription(s)")
            # Append a short section to recommendations for visibility
            self.health_report['recommendations'].append(
                f"Activated {len(activated)} queued subscription(s) during health check"
            )
            # Send a concise admin email summary
            try:
                lines = [
                    "The following queued subscriptions were activated during health check:\n"
                ]
                for a in activated:
                    lines.append(
                        f"• {a['customer_id']} — {a['plan_name']} (start {a['start_date']}, expires {a['expiry_date']})"
                    )
                send_email(
                    to_address=os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com'),
                    subject=f"Queued subscriptions activated: {len(activated)}",
                    body="\n".join(lines)
                )
                print("  📧 Admin notified about activated subscriptions")
            except Exception as e:
                print(f"  ⚠️ Failed to send activation email: {e}")
    
    def _check_client_sessions(self):
        """Check all client sessions across all brokers"""
        print("🔐 Testing client sessions...")
        
        session_manager = MultibrokerSessionManager()

        self.session_manager = session_manager

        # ── DEBUG: per-client opt-in prompt ──────────────────────────────────
        allowed_ids = None
        if DEBUG:
            from client_fetcher import get_active_clients_with_sip as _get_all
            _all_clients = _get_all()
            allowed_ids = set()
            print("\n[DEBUG MODE] Select which clients to include in health check:")
            for _c in _all_clients:
                _cid  = _c.get('customer_id', '?')
                _name = _c.get('username', _cid)
                _bid  = _c.get('user_id_broker', '?')
                _brk  = _c.get('broker_name', '?')
                _ans  = input(f"  Include {_name} ({_cid} / {_bid} / {_brk})? [y/n]: ").strip().lower()
                if _ans == 'y':
                    allowed_ids.add(_cid)
                    print(f"  ✅ {_cid} included")
                else:
                    print(f"  ⏭️  {_cid} skipped")

        try:
            # Initialize sessions (filtered by allowed_ids when DEBUG=True)
            session_success = session_manager.initialize_all_sessions(allowed_customer_ids=allowed_ids)
            
            # Get session summary
            summary = session_manager.get_session_summary()
            failed_clients = session_manager.get_failed_clients()
            
            # Store results
            self.health_report['session_check'] = {
                'status': 'PASS' if session_success else 'FAIL',
                'total_clients': summary['total_clients'],
                'active_sessions': summary['active_sessions'],
                'failed_sessions': summary['failed_sessions'],
                'success_rate': (summary['active_sessions'] / summary['total_clients'] * 100) if summary['total_clients'] > 0 else 0,
                'broker_breakdown': summary['broker_breakdown'],
                'failed_clients': failed_clients,
                'timestamp': datetime.now()
            }
            
            # Print results
            print(f"  📊 Total Clients: {summary['total_clients']}")
            print(f"  ✅ Active Sessions: {summary['active_sessions']}")
            print(f"  ❌ Failed Sessions: {summary['failed_sessions']}")
            print(f"  📈 Success Rate: {self.health_report['session_check']['success_rate']:.1f}%")
            
            # Check for issues
            if summary['failed_sessions'] > 0:
                self.health_report['warnings'].append(f"{summary['failed_sessions']} client sessions failed")
                
                print(f"  ⚠️ Failed Clients:")
                for failed in failed_clients[:5]:  # Show first 5
                    print(f"    • {failed['client_id']} ({failed['broker']}): {failed['error']}")
                self._attempt_finvasia_password_resets(session_manager)

            # Proactively verify trading ability for Finvasia clients whose sessions
            # initialized successfully. Finvasia allows login with an expired password
            # (grace window) but blocks actual order placement — this catches that gap
            # before etf_automated.py runs at market open.
            self._verify_finvasia_active_sessions(session_manager)

            # Refresh session counts in health_report to reflect any clients that
            # were recovered by password resets above. The initial counts were stored
            # before resets ran, so critical-issue thresholds must use final state.
            final_active = len(getattr(session_manager, 'client_sessions', {}))
            final_failed = len(getattr(session_manager, 'failed_sessions', {}))
            total = self.health_report['session_check'].get('total_clients', final_active + final_failed)
            final_rate = (final_active / total * 100) if total > 0 else 0
            self.health_report['session_check']['active_sessions'] = final_active
            self.health_report['session_check']['failed_sessions'] = final_failed
            self.health_report['session_check']['success_rate'] = final_rate
            if final_active == total:
                self.health_report['session_check']['status'] = 'PASS'
                # Remove the "sessions failed" warning if all clients recovered
                self.health_report['warnings'] = [
                    w for w in self.health_report['warnings']
                    if 'client sessions failed' not in w
                ]

            if final_active == 0:
                self.health_report['critical_issues'].append("No active client sessions")
            elif final_rate < 60:
                # Only CRITICAL if more than 40% of clients are failing.
                # Known temporary failures (blocked accounts, unsupported brokers)
                # handled gracefully via fallback — don't mark as CRITICAL.
                self.health_report['critical_issues'].append(f"Low session success rate: {final_rate:.1f}%")
            elif final_rate < 80:
                self.health_report['warnings'].append(f"Session success rate: {final_rate:.1f}% (some clients may be blocked/pending)")
            
        except Exception as e:
            print(f"  ❌ Session check failed: {e}")
            self.health_report['session_check'] = {
                'status': 'ERROR',
                'error': str(e),
                'timestamp': datetime.now()
            }
            self.health_report['critical_issues'].append(f"Session check error: {e}")
            try:
                send_admin_alert_email("Session check failed", str(e))
            except Exception:
                pass

    def _refresh_groww_tokens(self):
        """
        Refresh tokens for GROWW clients (self-managed brokers).
        Called after session check to ensure GROWW tokens are fresh.
        """
        if not _GROWW_AVAILABLE:
            print("\n⚠️ GROWW broker API not available — skipping GROWW token refresh")
            return
        print("\n🔐 Refreshing GROWW tokens...")
        print("-" * 30)
        
        try:
            # Get all active clients with GROWW broker
            from client_fetcher import get_active_clients_with_sip
            clients = get_active_clients_with_sip()
            
            groww_clients = [c for c in clients if c.get('broker_name', '').upper() == 'GROWW']
            
            if not groww_clients:
                print("  ℹ️ No GROWW clients found")
                return
            
            print(f"  👥 Found {len(groww_clients)} GROWW client(s)")
            
            refreshed = 0
            failed = []
            
            for client in groww_clients:
                client_id = client.get('customer_id', 'unknown')
                try:
                    print(f"  🔑 Refreshing token: {client_id}")
                    
                    # Generate fresh token using TOTP
                    success = refresh_groww_token_for_client(client)
                    
                    if success:
                        # Add to session manager's active sessions for balance check
                        self.session_manager.client_sessions[client_id] = {
                            'client_info': client,
                            'account_object': None,  # GROWW manages its own
                            'session': 'self-managed',
                            'broker_name': 'GROWW',
                            'login_time': 0,
                            'login_timestamp': datetime.now(),
                            'status': 'active',
                            'token_refreshed': True
                        }
                        refreshed += 1
                        print(f"    ✅ Token refreshed for {client_id}")
                    else:
                        failed.append(client_id)
                        print(f"    ❌ Token refresh failed for {client_id}")
                        
                except Exception as e:
                    failed.append(client_id)
                    print(f"    ❌ Error for {client_id}: {e}")
            
            print(f"\n  📊 GROWW Token Refresh Summary:")
            print(f"    ✅ Refreshed: {refreshed}/{len(groww_clients)}")
            if failed:
                print(f"    ❌ Failed: {len(failed)}")
                
        except Exception as e:
            print(f"  ❌ GROWW token refresh error: {e}")
            logging.error(f"GROWW token refresh error: {e}")

    def _update_broker_balances(self):

        updated = 0
        failures = []
        alerts = []

        if not self.session_manager or not getattr(self.session_manager, 'client_sessions', None):
            self.health_report['balance_update']['updated_count'] = 0
            self.health_report['balance_update']['failed'] = []
            self.health_report['low_balance_alerts']['alerts'] = []
            return

        def extract_amount(resp):

            if resp is None:
                return None

            if isinstance(resp, (int, float)):
                return float(resp)

            if isinstance(resp, str):
                try:
                    return float(resp)
                except Exception:
                    return None

            if isinstance(resp, dict):
                keys = ['availablecash', 'available_balance', 'available', 'cash', 'cashavailable', 'net', 'netcash',
                        'availblemargin', 'net_available']
                for k in keys:
                    if k in resp and isinstance(resp[k], (int, float, str)):
                        try:
                            return float(resp[k])
                        except Exception:
                            pass
                if 'data' in resp and isinstance(resp['data'], dict):
                    return extract_amount(resp['data'])

            return None

        try:
            with app.app_context():
                settings = SchedulerSettings.query.first()
                threshold_percent = (settings.low_balance_threshold_percent
                                     if settings and settings.low_balance_threshold_percent is not None else 20)
                self.health_report['low_balance_alerts']['threshold_percent'] = threshold_percent
                subscription_cache = {}
                user_cache = {}

                for client_id, info in self.session_manager.client_sessions.items():
                    api = info.get('session')
                    client = info.get('client_info', {})
                    broker_id = client.get('broker_id')

                    if not api or not broker_id:
                        failures.append({
                            'customer_id': client.get('customer_id'),
                            'broker_name': client.get('broker_name'),
                            'reason': 'no_session_or_broker_id'
                        })
                        continue

                    resp = None
                    amount = None
                    broker_name = client.get('broker_name', '').strip().upper()

                    _BROKER_FUND_MAP = {
                        'DHAN':         ('dhan_executor',      'get_available_funds'),
                        'FINVASIA':     ('finvasia_broker_api','get_available_funds'),
                        'ZERODHA':      ('zerodha_broker_api', 'get_available_funds'),
                        'ANGEL':        ('angel_broker_api',   'get_available_funds'),
                        'ANGELONE':     ('angel_broker_api',   'get_available_funds'),
                        'ANGLE':        ('angel_broker_api',   'get_available_funds'),
                        'UPSTOX':       ('upstox_broker_api',  'get_available_funds'),
                        'GROWW':        ('groww_broker_api',   'get_available_funds'),
                        'ICICI':        ('icici_executor',     'get_available_funds'),
                    }
                    balance_fetch_error = None
                    if broker_name in _BROKER_FUND_MAP:
                        mod_name, fn_name = _BROKER_FUND_MAP[broker_name]
                        try:
                            import importlib
                            mod = importlib.import_module(mod_name)
                            fn = getattr(mod, fn_name)
                            result = fn(client)
                            amount = extract_amount(result)
                        except Exception as e:
                            balance_fetch_error = str(e)
                            logging.warning(f"{broker_name} balance fetch failed for {client.get('customer_id')}: {e}")
                    elif broker_name in ('HDFC', 'MSTOCK'):
                        logging.info(f"{broker_name} balance fetch not yet implemented, skipping {client.get('customer_id')}")
                    else:
                        for meth in ('limits', 'get_limits', 'get_balance', 'account_details', 'get_fund_limit'):
                            fn = getattr(api, meth, None)
                            if not fn:
                                continue
                            try:
                                resp = fn()
                                if resp:
                                    break
                            except Exception:
                                resp = None
                                continue
                        amount = extract_amount(resp)

                    try:
                        broker = db.session.get(Broker, broker_id)
                        if not broker:
                            failures.append({
                                'customer_id': client.get('customer_id'),
                                'broker_name': client.get('broker_name'),
                                'reason': 'broker_not_found'
                            })
                            continue

                        if amount is not None:
                            broker.available_balance = float(amount)
                            broker.balance_checked_at = datetime.utcnow()
                            updated += 1

                            alert = self._maybe_send_low_balance_alert(
                                broker,
                                broker.available_balance,
                                threshold_percent,
                                subscription_cache,
                                user_cache
                            )
                            if alert:
                                alerts.append(alert)
                        else:
                            failures.append({
                                'customer_id': client.get('customer_id'),
                                'broker_name': broker.broker_name,
                                'reason': balance_fetch_error or 'no_amount_parsed'
                            })

                    except Exception as db_error:
                        failures.append({
                            'customer_id': client.get('customer_id'),
                            'broker_name': broker.broker_name if 'broker' in locals() and broker else client.get('broker_name'),
                            'reason': f'db_error:{db_error}'
                        })

                try:
                    db.session.commit()
                except Exception as commit_error:
                    db.session.rollback()
                    self.health_report['warnings'].append(f"Balance update commit failed: {commit_error}")

        except Exception as e:
            self.health_report['warnings'].append(f"Balance update error: {e}")

        self.health_report['balance_update']['updated_count'] = updated
        self.health_report['balance_update']['failed'] = failures
        self.health_report['low_balance_alerts']['alerts'] = alerts

        print(f"  ✅ Updated balances for {updated} broker(s)")
        if failures:
            print(f"  ⚠️ Balance update failures: {len(failures)}")
        if alerts:
            print(f"  📧 Sent {len(alerts)} low balance alert(s)")

    def _attempt_finvasia_password_resets(self, session_manager):
        """
        For every failed FINVASIA session, attempt a password rotation regardless
        of the error type. Finvasia passwords expire every 90 days and the expiry
        can surface as any kind of failure (timeout, auth error, no response, etc.).
        If rotation succeeds we re-initialise the session so the client is live
        for the rest of the day without waiting for the next morning run.
        """
        resets = []
        failed = []
        for client_id, failed_info in list(session_manager.failed_sessions.items()):
            broker_name = (failed_info.get('broker_name') or '').upper()
            if broker_name != 'FINVASIA':
                continue
            client = failed_info.get('client_info', {})
            # Skip accounts that are blocked due to API config (ALGO_CHK), not passwords.
            if client.get('user_id_broker') in BLOCKED_BROKER_IDS:
                logging.info(
                    f"  ⛔ Skipping password reset for {client.get('customer_id')} "
                    f"({client.get('user_id_broker')}) — in BLOCKED_BROKER_IDS"
                )
                continue
            error_msg = str(failed_info.get('error') or '')
            non_password_errors = (
                'session expired', 'invalid session', 'session key',
                'algo_chk', 'invalid app_key', 'ltp unavailable',
                'connection', 'timeout', 'network',
                'user blocked', 'blocked due to', 'multiple wrong',
            )
            if any(x in error_msg.lower() for x in non_password_errors):
                logging.warning(
                    f"  ⏭️ Skipping password reset for {client.get('customer_id')} "
                    f"— error is non-password: {error_msg[:80]}"
                )
                continue
            print(f"  🔐 Finvasia password reset attempt → {client.get('customer_id')} (trigger: {error_msg[:80]})")
            result = self._rotate_finvasia_password(client, error_msg)
            if result.get('success'):
                resets.append(result)
                # Re-initialise session with updated credentials so the client
                # can trade today without needing a manual restart.
                updated_client = result.get('updated_client', client)
                try:
                    session_manager._initialize_broker_sessions('FINVASIA', [updated_client])
                    # Remove from failed_sessions if we managed to add it to client_sessions
                    if client_id in session_manager.client_sessions:
                        if client_id in session_manager.failed_sessions:
                            del session_manager.failed_sessions[client_id]
                        # Adjust session stats
                        session_manager.session_stats['successful_sessions'] = len(session_manager.client_sessions)
                        session_manager.session_stats['failed_sessions'] = len(session_manager.failed_sessions)
                        print(f"  ✅ Session re-initialised for {client.get('customer_id')} after password reset")
                    else:
                        print(f"  ⚠️ Password reset OK but session re-init failed for {client.get('customer_id')}")
                except Exception as re_init_err:
                    print(f"  ⚠️ Session re-init error for {client.get('customer_id')}: {re_init_err}")
            else:
                failed.append(result)
            self._send_admin_password_rotation_email(result)

        if resets:
            self.health_report.setdefault('password_resets', [])
            self.health_report['password_resets'].extend(resets)
            print(f"  🔐 Finvasia password resets completed: {len(resets)}")
        if failed:
            self.health_report.setdefault('password_reset_failures', [])
            self.health_report['password_reset_failures'].extend(failed)
            print(f"  ⚠️ Finvasia password reset failures: {len(failed)}")

        if resets or failed:
            self._write_finvasia_password_csv(resets + failed)

    def _verify_finvasia_active_sessions(self, session_manager):
        """
        For every FINVASIA client whose session initialized successfully, call
        get_available_funds to confirm actual trading ability — not just login.

        Finvasia permits session establishment even when the 90-day password has
        recently expired (grace window), but subsequent order placement fails.
        This check catches that gap so the password is rotated *before*
        etf_automated.py runs at market open.

        Clients whose balance check passes are left untouched.
        Clients whose balance check fails are sent through _rotate_finvasia_password
        exactly like failed-session clients.
        """
        resets = []
        failed_rotations = []

        for client_id, info in list(getattr(session_manager, 'client_sessions', {}).items()):
            client = info.get('client_info', {})
            broker_name = (client.get('broker_name') or '').upper()
            if broker_name != 'FINVASIA':
                continue

            # Accounts in BLOCKED_BROKER_IDS have an API config issue (ALGO_CHK),
            # not a password issue. Skip both the balance check and password rotation.
            if client.get('user_id_broker') in BLOCKED_BROKER_IDS:
                logging.info(
                    f"  ⛔ Skipping trading check for {client.get('customer_id')} "
                    f"({client.get('user_id_broker')}) — in BLOCKED_BROKER_IDS"
                )
                continue

            customer_id = client.get('customer_id', client_id)
            uid         = client.get('user_id_broker', '')
            proxy_url   = get_client_proxy(client)
            print(f"  🔍 Finvasia trading check → {customer_id}")

            # ── Reuse Phase 1 session — no second QuickAuth+GenAcsTok needed ──
            # session_manager already logged in this client above.
            # Strategy: inject those tokens into finvasia_broker_api._session_cache
            # so get_available_funds() uses the existing session without re-login.
            #
            # Fallback chain (all errors are handled gracefully):
            #   1. Phase 1 account has tokens → inject + call Limits (0 extra logins)
            #   2. Injection or Limits call fails  → fall back to verify_balance (shared)
            #   3. account_object missing tokens   → fall back to verify_balance (shared)
            verified     = False
            balance      = None
            error        = None
            _used_phase1 = False

            _account = info.get('account_object')
            _stoken  = getattr(_account, 'susertoken',  None) if _account else None
            _atoken  = getattr(_account, 'access_token', None) if _account else None
            _proxy   = proxy_url or client.get('proxy_ip', '')

            if _stoken:
                # Phase 1 tokens available — inject and call Limits directly
                _fba_ref = None
                try:
                    import finvasia_broker_api as _fba_ref
                    with _fba_ref._lock:
                        _fba_ref._session_cache[uid] = {
                            'session':      getattr(_account, 'session', None),
                            'susertoken':   _stoken,
                            'access_token': _atoken or _stoken,
                            'vendor_code':  client.get('vendor_code', ''),
                            'proxy_ip':     _proxy,
                        }
                    _vc = dict(client)
                    _vc['proxy_ip'] = _proxy
                    balance      = get_available_funds(_vc)
                    verified     = True
                    _used_phase1 = True
                except Exception as _inject_err:
                    # Clean up any partial cache entry to avoid stale state
                    try:
                        if _fba_ref is not None:
                            with _fba_ref._lock:
                                _fba_ref._session_cache.pop(uid, None)
                    except Exception:
                        pass
                    error = str(_inject_err)
                    logging.warning(
                        f"  ⚠️ {customer_id}: Phase-1 reuse failed "
                        f"({error[:80]}), retrying with fresh login..."
                    )

            if not _used_phase1:
                # Fallback: fresh verify using shared utility (re-login with current password)
                from finvasia_password_utils import _verify_balance
                verified, balance, error = _verify_balance(
                    client, client.get('password'), proxy_url, attempts=2
                )

            if verified:
                print(f"  ✅ {customer_id}: trading OK (₹{balance})")
                continue

            # Session was alive but trading is blocked — likely expired password
            non_password_errors = (
                'session expired', 'invalid session', 'session key',
                'algo_chk', 'invalid app_key', 'ltp unavailable',
                'connection', 'timeout', 'network',
                'user blocked', 'blocked due to', 'multiple wrong',
            )
            if any(x in (error or '').lower() for x in non_password_errors):
                logging.warning(
                    f"  ⏭️ Skipping proactive password rotation for {customer_id} "
                    f"— error is non-password: {(error or '')[:80]}"
                )
                continue
            print(f"  ⚠️ {customer_id}: trading check FAILED ({error}) — triggering proactive password rotation")
            result = self._rotate_finvasia_password(client, error or 'trading_check_failed')

            if result.get('success'):
                resets.append(result)
                updated_client = result.get('updated_client', client)
                # Patch the in-memory session so the health check's balance step
                # and any same-process callers use the new password.
                session_manager.client_sessions[client_id]['client_info']['password'] = result['new_password']
                print(f"  ✅ {customer_id}: proactive password rotation succeeded")
            else:
                failed_rotations.append(result)
                self.health_report['warnings'].append(
                    f"Finvasia proactive password rotation failed for {customer_id}: {result.get('error')}"
                )
                print(f"  ❌ {customer_id}: proactive rotation failed — {result.get('error')}")

            self._send_admin_password_rotation_email(result)

        if resets:
            self.health_report.setdefault('password_resets', [])
            self.health_report['password_resets'].extend(resets)
            print(f"  🔐 Proactive Finvasia password resets: {len(resets)}")
        if failed_rotations:
            self.health_report.setdefault('password_reset_failures', [])
            self.health_report['password_reset_failures'].extend(failed_rotations)
            print(f"  ⚠️ Proactive Finvasia rotation failures: {len(failed_rotations)}")
        if resets or failed_rotations:
            self._write_finvasia_password_csv(resets + failed_rotations)

    def _is_password_error(self, error_message: str) -> bool:
        """Kept for reference; no longer used as a gate — all Finvasia failures now trigger rotation."""
        msg = (error_message or '').lower()
        keywords = ("password", "auth", "expired", "reset", "invalid")
        return any(k in msg for k in keywords)

    def _rotate_finvasia_password(self, client: dict, error_message: str) -> dict:
        """Delegate to shared finvasia_password_utils — single source of truth."""
        from finvasia_password_utils import rotate_finvasia_password
        return rotate_finvasia_password(
            client,
            error_message=error_message,
            notify_client=True,
            debug=DEBUG,
        )


    def _write_finvasia_password_csv(self, results):
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_orders')
        os.makedirs(out_dir, exist_ok=True)
        csv_path = os.path.join(out_dir, f'finvasia_password_resets_{ts}.csv')
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write('customer_id,old_password,new_password,changed,verified,balance,error\n')
            for r in results:
                f.write(
                    f"{r.get('customer_id')},{r.get('old_password','')},{r.get('new_password','')},"
                    f"{r.get('success')},{r.get('verified')},{r.get('balance','')},{r.get('error','')}\n"
                )

    def _send_admin_password_rotation_email(self, result):
        subject = f"Finvasia password reset — {result.get('customer_id')}"
        status = "SUCCESS" if result.get('success') else "FAILED"
        status_color = "#28a745" if result.get('success') else "#dc3545"

        client_email = result.get('client_email') or 'N/A'
        client_email_sent = result.get('client_email_sent')
        if client_email_sent is True:
            email_status_html = f"<span style='color:#28a745;font-weight:bold;'>&#10003; Sent to {client_email}</span>"
        elif client_email_sent is False and client_email != 'N/A':
            email_status_html = f"<span style='color:#dc3545;font-weight:bold;'>&#10007; Failed — attempted to {client_email}</span>"
        else:
            email_status_html = "<span style='color:#999;'>No email address on record</span>"

        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        timestamp = datetime.now(IST).strftime('%d %B %Y, %I:%M %p IST')

        html = f"""
        <html>
        <body style="font-family:Arial,sans-serif;margin:20px;background:#f5f5f5;">
            <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
                <div style="background:{status_color};color:white;padding:16px 20px;">
                    <h3 style="margin:0;">Finvasia Password Reset — {status}</h3>
                    <p style="margin:4px 0 0 0;font-size:13px;opacity:0.9;">{timestamp}</p>
                </div>
                <div style="padding:20px;">
                    <table style="width:100%;border-collapse:collapse;font-size:14px;">
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;width:170px;">Customer ID</td>
                            <td style="padding:8px 0;font-weight:bold;">{result.get('customer_id') or 'N/A'}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;">Old Password</td>
                            <td style="padding:8px 0;font-family:monospace;">{result.get('old_password') or 'N/A'}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;">New Password</td>
                            <td style="padding:8px 0;font-family:monospace;font-weight:bold;">{result.get('new_password') or 'N/A'}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;">Balance Verified</td>
                            <td style="padding:8px 0;">{result.get('verified')}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;">Balance</td>
                            <td style="padding:8px 0;">{'&#8377;' + str(result.get('balance')) if result.get('balance') else 'N/A'}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:8px 0;color:#666;">Client Email Sent</td>
                            <td style="padding:8px 0;">{email_status_html}</td>
                        </tr>
                        <tr>
                            <td style="padding:8px 0;color:#666;">Error</td>
                            <td style="padding:8px 0;color:#dc3545;">{result.get('error') or result.get('verify_warning') or result.get('verify_error') or '—'}</td>
                        </tr>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """
        send_email(
            to_address=os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com'),
            subject=subject,
            body=html,
            is_html=True
        )
    
    def _maybe_send_low_balance_alert(self, broker, amount, threshold_percent, subscription_cache, user_cache):
        customer_id = broker.customer_id
        if customer_id not in subscription_cache:
            subscription_cache[customer_id] = self._get_active_subscription(customer_id)
        subscription = subscription_cache.get(customer_id)
        if not subscription or not subscription.monthly_sip_target or subscription.monthly_sip_target <= 0:
            return None
        threshold_amount = (subscription.monthly_sip_target * threshold_percent) / 100.0
        if amount is None or amount >= threshold_amount:
            return None
        if broker.user_id not in user_cache:
            user_cache[broker.user_id] = db.session.get(User, broker.user_id)
        user = user_cache.get(broker.user_id)
        if not user or not getattr(user, 'low_balance_alerts_enabled', True) or not user.email:
            return None
        try:
            balance_value = float(amount)
            subject = f"Low Balance Alert - {broker.broker_name}"
            message = (
                f"Dear {user.full_name or user.username},\n\n"
                f"Your {broker.broker_name} trading account balance is ₹{balance_value:,.2f}, which is below "
                f"{threshold_percent}% (₹{threshold_amount:,.2f}) of your Monthly SIP target of "
                f"₹{subscription.monthly_sip_target:,.2f}.\n\n"
                "Please add funds to your broker account to prevent missed SmartETF orders.\n\n"
                "Regards,\nSmartETF Team"
            )
            send_client_notification_email(user.email, subject, message)
            return {
                'customer_id': user.customer_id,
                'broker': broker.broker_name,
                'balance': balance_value,
                'threshold': threshold_amount
            }
        except Exception as alert_error:
            self.health_report['warnings'].append(
                f"Low balance email failed for {broker.customer_id}: {alert_error}"
            )
            return None

    def _get_active_subscription(self, customer_id):
        if not customer_id:
            return None
        now = datetime.utcnow()
        return Subscription.query.filter(
            Subscription.customer_id == customer_id,
            Subscription.payment_status.in_(['Successful', 'Paid', 'Active']),
            Subscription.start_date <= now,
            Subscription.expiry_date > now,
            db.or_(Subscription.is_queued == False, Subscription.is_queued.is_(None))
        ).order_by(Subscription.expiry_date.desc()).first()

    # def _check_etf_data_fetching(self):
    #     """Check ETF data fetching capability"""
    #     print("📊 Testing ETF data fetching...")
    #
    #     try:
    #         start_time = time.time()
    #
    #         # Attempt to fetch ETF data
    #         etf_file = fetch_etf_data_with_fallback()
    #
    #         fetch_time = time.time() - start_time
    #
    #         if etf_file:
    #             # Check file size and content
    #             file_size = os.path.getsize(etf_file) if os.path.exists(etf_file) else 0
    #
    #             self.health_report['etf_fetch_check'] = {
    #                 'status': 'PASS',
    #                 'file_name': etf_file,
    #                 'file_size_bytes': file_size,
    #                 'fetch_time_seconds': fetch_time,
    #                 'timestamp': datetime.now()
    #             }
    #
    #             print(f"  ✅ ETF data fetched successfully")
    #             print(f"  📄 File: {etf_file}")
    #             print(f"  📏 Size: {file_size:,} bytes")
    #             print(f"  ⏱️ Time: {fetch_time:.2f} seconds")
    #
    #             # Check file size
    #             if file_size < 1000:  # Less than 1KB
    #                 self.health_report['warnings'].append(f"ETF file unusually small: {file_size} bytes")
    #
    #         else:
    #             self.health_report['etf_fetch_check'] = {
    #                 'status': 'FAIL',
    #                 'error': 'Failed to fetch ETF data',
    #                 'fetch_time_seconds': fetch_time,
    #                 'timestamp': datetime.now()
    #             }
    #
    #             print(f"  ❌ ETF data fetch failed")
    #             self.health_report['critical_issues'].append("ETF data fetching failed")
    #
    #     except Exception as e:
    #         print(f"  ❌ ETF fetch error: {e}")
    #         self.health_report['etf_fetch_check'] = {
    #             'status': 'ERROR',
    #             'error': str(e),
    #             'timestamp': datetime.now()
    #         }
    #         self.health_report['critical_issues'].append(f"ETF fetch error: {e}")
    
    def _check_chrome_driver(self):
        """ChromeDriver check removed — login now uses pure API (no Selenium)."""
        self.health_report['chrome_driver_check'] = {
            'status': 'N/A',
            'note': 'Selenium removed. Login uses QuickAuth + pycurl GenAcsTok.',
            'timestamp': datetime.now()
        }
    
    def _generate_overall_status(self):
        """Generate overall health status"""
        critical_count = len(self.health_report['critical_issues'])
        warning_count = len(self.health_report['warnings'])
        
        if critical_count > 0:
            self.health_report['overall_status'] = 'CRITICAL'
        elif warning_count > 2:
            self.health_report['overall_status'] = 'WARNING'
        else:
            self.health_report['overall_status'] = 'HEALTHY'
        
        print(f"📊 Overall Status: {self.health_report['overall_status']}")
        
        if critical_count > 0:
            print(f"🚨 Critical Issues: {critical_count}")
            for issue in self.health_report['critical_issues']:
                print(f"  • {issue}")
        
        if warning_count > 0:
            print(f"⚠️ Warnings: {warning_count}")
            for warning in self.health_report['warnings']:
                print(f"  • {warning}")
    
    def _send_health_report_email(self):
        """Send health report email to admin"""
        print("📧 Sending health report email...")
        
        try:
            # Generate email content
            status_emoji = {
                'HEALTHY': '✅',
                'WARNING': '⚠️',
                'CRITICAL': '🚨'
            }
            
            subject = f"SmartETF Morning Health Check - {self.health_report['overall_status']} {status_emoji.get(self.health_report['overall_status'], '❓')}"
            
            body = self._generate_email_body()
            
            # Send email
            send_email(
                to_address=self.admin_email,
                subject=subject,
                body=body
            )
            
            print(f"  ✅ Email sent to {self.admin_email}")
            
        except Exception as e:
            print(f"  ❌ Email send failed: {e}")
    
    def _generate_email_body(self):
        """Generate detailed email body"""
        report = self.health_report
        
        body = f"""SmartETF Morning Health Check Report
{'=' * 50}

Timestamp: {report['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}
Overall Status: {report['overall_status']}

SUBSCRIPTION ACTIVATION:

• Activated: {report['subscription_activation']['activated_count']}

"""

        if report['subscription_activation']['activated']:

            for a in report['subscription_activation']['activated']:

                body += f"  • {a['customer_id']} — {a['plan_name']} (start {a['start_date']}, expires {a['expiry_date']})\n"

        body += f"""

BALANCE UPDATES:

• Updated: {report['balance_update']['updated_count']}

"""

        if report['balance_update']['failed']:

            body += f"• Failed: {len(report['balance_update']['failed'])}\n"
            body += "Failed Entries:\n"
            for failure in report['balance_update']['failed'][:5]:
                body += (
                    f"• {failure.get('customer_id', 'unknown')} / "
                    f"{failure.get('broker_name', 'Broker')} — {failure.get('reason', 'reason not captured')}\n"
                )

        body += f"""

LOW BALANCE ALERTS:

• Threshold: {report['low_balance_alerts'].get('threshold_percent', 20)}% of SIP target

• Alerts Sent: {len(report['low_balance_alerts'].get('alerts', []))}

"""

        if report['low_balance_alerts'].get('alerts'):

            body += "Recent Alerts:\n"

            for alert in report['low_balance_alerts']['alerts'][:5]:

                body += (f"• {alert.get('customer_id', 'unknown')} / {alert.get('broker', 'Broker')} — "
                         f"₹{alert.get('balance', 0):,.2f} vs threshold ₹{alert.get('threshold', 0):,.2f}\n")

        body += f"""

SESSION HEALTH CHECK:

"""

        if 'session_check' in report and report['session_check']:

            session = report['session_check']

            body += f"""• Status: {session.get('status', 'N/A')}

• Total Clients: {session.get('total_clients', 0)}

• Active Sessions: {session.get('active_sessions', 0)}

• Failed Sessions: {session.get('failed_sessions', 0)}

• Success Rate: {session.get('success_rate', 0):.1f}%

"""

            if session.get('failed_clients'):

                body += "\nFailed Clients:\n"

                for failed in session['failed_clients'][:5]:

                    body += f"• {failed['client_id']} ({failed['broker']}): {failed['error']}\n"

        body += f"""

ETF DATA FETCH CHECK:

• Status: {report['etf_fetch_check'].get('status', 'N/A')}

"""

        if report['etf_fetch_check'].get('file_name'):

            body += f"• File: {report['etf_fetch_check']['file_name']}\n"

            body += f"• Size: {report['etf_fetch_check'].get('file_size_bytes', 0):,} bytes\n"

            body += f"• Fetch Time: {report['etf_fetch_check'].get('fetch_time_seconds', 0):.2f}s\n"

        body += f"""

SELENIUM/CHROMEDRIVER:

• Status: {report['chrome_driver_check'].get('status', 'N/A')} — {report['chrome_driver_check'].get('note', '')}

"""

        # --- Dynamic Fall Calculator status ---
        try:
            from dynamic_fall_calculator import (
                get_available_historical_days,
                MIN_DATA_DAYS, BLEND_PERIOD, ROLLING_DAYS, ENABLE_DYNAMIC_FALL,
            )
            days = get_available_historical_days()
            total = MIN_DATA_DAYS + BLEND_PERIOD  # 180

            if not ENABLE_DYNAMIC_FALL:
                fall_phase = 0
                fall_label = "Disabled"
                fall_msg   = "Dynamic fall is disabled — hardcoded CSV always used."
            elif days < MIN_DATA_DAYS:
                fall_phase = 1
                fall_label = "Phase 1 — Hardcoded CSV"
                fall_msg   = f"{days}/{MIN_DATA_DAYS} days collected. Need {MIN_DATA_DAYS - days} more trading days before blending starts."
            elif days < total:
                blend_ratio = round((days - MIN_DATA_DAYS) / BLEND_PERIOD * 100)
                fall_phase = 2
                fall_label = "Phase 2 — Blending"
                fall_msg   = f"{blend_ratio}% dynamic / {100 - blend_ratio}% hardcoded. {total - days} more days until fully dynamic."
            else:
                fall_phase = 3
                fall_label = "Phase 3 — Fully Dynamic"
                fall_msg   = f"Rolling {ROLLING_DAYS}-day window ({days} days collected). Hardcoded CSV no longer used."

            body += f"""

DYNAMIC AVERAGE FALL CALCULATOR:

• Current Phase: {fall_phase} — {fall_label}
• Days Collected: {days}
• Status: {fall_msg}

"""
        except Exception as _fe:
            body += f"\nDYNAMIC FALL CALCULATOR: status unavailable ({_fe})\n"

        # --- end fall status ---

        if report['critical_issues']:

            body += f"\nCRITICAL ISSUES:\n"

            for issue in report['critical_issues']:

                body += f"• {issue}\n"

        if report['warnings']:

            body += f"\nWARNINGS:\n"

            for warning in report['warnings']:

                body += f"• {warning}\n"

        if report['recommendations']:

            body += f"\nRECOMMENDATIONS:\n"

            for rec in report['recommendations']:

                body += f"• {rec}\n"

        body += f"""

Next Steps:

1. Address critical issues immediately

2. Monitor warnings throughout the day

3. Check evening execution results

4. Review session failures with clients



– SmartETF Health Monitor
"""
        
        return body
    
    def _save_health_report(self):
        """Save health report to file"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save JSON report
        report_file = f"health_report_{timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump(self.health_report, f, indent=2, default=str)
        
        print(f"📄 Health report saved: {report_file}")


def run_morning_health_check(admin_email=None):
    """Run the complete morning health check"""
    if not admin_email:
        admin_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com')
    checker = MorningHealthChecker(admin_email)
    return checker.run_complete_health_check()


if __name__ == "__main__":
    print("🌅 SmartETF Morning Health Check")
    print("This will test all systems and send email report")
    print()
    admin_email = os.getenv('ADMIN_EMAIL', 'smartetfalgo@gmail.com').strip() or 'smartetfalgo@gmail.com'
    try:
        success = run_morning_health_check(admin_email)
    except Exception:
        try:
            send_email(admin_email, "🚨 Health Check Crash", f"Health check crashed:\n\n{traceback.format_exc()}")
        except Exception:
            pass
        sys.exit(1)
    if success:
        print("\n🎉 Health check completed successfully!")
        sys.exit(0)
    else:
        print("\n🚨 Health check found critical issues!")
        sys.exit(1)
