"""
Final Fixed Client Fetcher - Handles Database Session Correctly
Works for both Flask app and standalone execution
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import models and helpers
from models import db, Broker, User, Subscription, Plan
from dhan_security_helper import decrypt_dhan_client_id, decrypt_dhan_api_key
import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def get_app():
    """Lazy import app to avoid circular import"""
    from app import app
    return app

def get_active_clients_with_sip():
    """
    Return ONE execution target per customer (no duplicates), with a single broker chosen by priority:
    1) is_master=True broker if present, else
    2) any broker with copy=True, else
    3) earliest created broker.
    Also enforces a single current subscription per customer (latest expiry).
    """
    with get_app().app_context():
        try:
            now = datetime.datetime.utcnow()

            # Latest active subscription per customer
            current_subs_subq = (
                db.session.query(
                    Subscription.customer_id.label('customer_id'),
                    db.func.max(Subscription.expiry_date).label('max_expiry')
                )
                .filter(
                    Subscription.payment_status.in_(['Active', 'Successful', 'Paid']),
                    Subscription.start_date <= now,
                    Subscription.expiry_date > now,
                    db.or_(Subscription.is_queued == False, Subscription.is_queued.is_(None))
                )
                .group_by(Subscription.customer_id)
                .subquery()
            )

            rows = (
                db.session.query(Broker, User, Subscription, Plan)
                .join(User, Broker.customer_id == User.customer_id)
                .join(current_subs_subq, current_subs_subq.c.customer_id == User.customer_id)
                .join(
                    Subscription,
                    (Subscription.customer_id == current_subs_subq.c.customer_id)
                    & (Subscription.expiry_date == current_subs_subq.c.max_expiry)
                )
                .join(Plan, Subscription.plan_id == Plan.id)
                .filter(
                    Broker.subscription_status == 'Active',
                    Subscription.monthly_sip_target.isnot(None),
                    Subscription.monthly_sip_target > 0,
                    Plan.is_active.is_(True)
                )
                .order_by(Broker.created_at.asc())
                .all()
            )

            # Group brokers by customer_id then pick one
            by_customer: dict[str, list[tuple]] = {}
            for broker, user, sub, plan in rows:
                by_customer.setdefault(user.customer_id, []).append((broker, user, sub, plan))

            active_clients = []

            def missing_required_fields(b: Broker) -> list[str]:
                name = (b.broker_name or '').upper()
                if name == 'FINVASIA':
                    req = ['user_id_broker', 'password', 'totp_secret', 'vendor_code', 'api_secret', 'imei']
                elif name == 'HDFC':
                    req = ['user_id_broker', 'password', 'username']
                elif name == 'ICICI':
                    req = ['user_id_broker', 'password']
                elif name == 'MSTOCK':
                    req = ['user_id_broker', 'password', 'username']
                elif name == 'DHAN':
                    missing = []
                    if not (b.dhan_client_id_enc and b.dhan_client_id_iv and b.dhan_client_id_tag):
                        missing.append('dhan_client_id')
                    if not ((b.api_key_enc and b.api_key_iv and b.api_key_tag) or b.api_key):
                        missing.append('api_key')
                    if not b.api_secret:
                        missing.append('api_secret')
                    return missing
                elif name == 'ZERODHA':
                    req = ['user_id_broker', 'password', 'totp_secret', 'api_key', 'api_secret']
                else:
                    req = ['user_id_broker', 'password']
                return [f for f in req if not getattr(b, f, None)]

            for cust_id, items in by_customer.items():
                # choose preferred broker
                items_valid = [(b, u, s, p) for (b, u, s, p) in items if not missing_required_fields(b)]
                if not items_valid:
                    # keep first to log missing details
                    b, u, s, p = items[0]
                    logging.warning(f"Skipping {cust_id}: missing fields for all brokers")
                    continue

                # priority selection
                preferred = None
                # 1) is_master
                for tup in items_valid:
                    if tup[0].is_master:
                        preferred = tup
                        break
                # 2) copy=True
                if preferred is None:
                    for tup in items_valid:
                        if bool(tup[0].copy):
                            preferred = tup
                            break
                # 3) fallback: earliest created (already ordered)
                if preferred is None:
                    preferred = items_valid[0]

                broker, user, subscription, plan = preferred

                days_until_expiry = (subscription.expiry_date.date() - now.date()).days
                if days_until_expiry < 0:
                    logging.warning(f"Skipping {cust_id}: current subscription expired")
                    continue

                client_data = {
                    'customer_id': user.customer_id,
                    'username': user.username,
                    'email': user.email,
                    'mobile': broker.mobile or user.mobile or '',
                    'user_id': user.id,
                    'broker_id': broker.id,
                    'broker_name': broker.broker_name,
                    'user_id_broker': broker.user_id_broker,
                    'password': broker.password,
                    'totp_secret': broker.totp_secret,
                    'vendor_code': broker.vendor_code,
                    'api_secret': broker.api_secret,
                    'imei': broker.imei,
                    'api_key': broker.api_key,
                    'secret_key': broker.secret_key,
                    'token_id': broker.token_id,
                    'session_token': broker.session_token,
                    'access_token': broker.access_token,
                    'username_broker': broker.username,
                    'is_master': broker.is_master,
                    'copy': broker.copy,
                    'copy_multiplier': broker.copy_multiplier,
                    'subscription_id': subscription.id,
                    'subscription_status': broker.subscription_status,
                    'subscription_expiry': subscription.expiry_date,
                    'days_until_expiry': days_until_expiry,
                    'payment_status': subscription.payment_status,
                    'billing_cycle': subscription.billing_cycle,
                    'monthly_sip_target': float(subscription.monthly_sip_target),
                    'sip_target_updated_at': subscription.sip_target_updated_at,
                    'plan_id': plan.id,
                    'plan_name': plan.name,
                    'max_sip_amount': plan.max_sip_amount,
                    'has_copy_trading': plan.has_copy_trading,
                    'max_brokers': plan.max_brokers,
                    'created_at': broker.created_at,
                    'last_updated': broker.last_updated,
                    'proxy_ip': getattr(broker, 'proxy_ip', None) or '',
                }

                if broker.broker_name and broker.broker_name.upper() == "DHAN":
                    if broker.dhan_client_id_enc:
                        client_data["dhan_client_id"] = decrypt_dhan_client_id(
                            broker.dhan_client_id_enc,
                            broker.dhan_client_id_iv,
                            broker.dhan_client_id_tag
                        ) or ''
                    
                    if broker.api_key_enc:
                        client_data["api_key"] = decrypt_dhan_api_key(
                            broker.api_key_enc,
                            broker.api_key_iv,
                            broker.api_key_tag
                        ) or broker.api_key or ''
                    else:
                        client_data["api_key"] = broker.api_key or ''
                    
                    client_data["api_secret"] = broker.api_secret or ''
                    client_data["access_token"] = broker.access_token or ''

                active_clients.append(client_data)

            logging.info(f"✅ Deduped active customers: {len(active_clients)} (was {len(rows)} broker rows)")
            return active_clients
        except Exception as e:
            logging.error(f"❌ Error retrieving active clients: {e}")
            import traceback
            logging.error(f"Full traceback: {traceback.format_exc()}")
            return []


def get_active_clients():
    """
    Legacy function for backward compatibility.
    Returns basic client data without SIP information.
    """
    return get_active_clients_with_sip()


def validate_client_credentials(client_data):
    """
    Validate that a client has all required credentials for their broker type.
    """
    broker_name = client_data.get('broker_name', '').upper()

    validation_rules = {
        'FINVASIA': ['user_id_broker', 'password', 'totp_secret', 'vendor_code', 'api_secret', 'imei'],
        'HDFC': ['user_id_broker', 'password', 'username_broker'],
        'ICICI': ['user_id_broker', 'password'],
        'MSTOCK': ['user_id_broker', 'password', 'username_broker']
    }

    required_fields = validation_rules.get(broker_name, [])
    missing_fields = []

    for field in required_fields:
        if not client_data.get(field):
            missing_fields.append(field)

    return {
        'is_valid': len(missing_fields) == 0,
        'missing_fields': missing_fields,
        'broker_name': broker_name
    }


def get_subscription_summary():
    """
    Get summary of all subscriptions for monitoring.
    """
    with get_app().app_context():
        try:
            current_time = datetime.datetime.utcnow()

            # Active subscriptions
            active_subs = Subscription.query.filter(
                Subscription.expiry_date > current_time
            ).count()

            # Subscriptions with SIP targets
            sip_subs = Subscription.query.filter(
                Subscription.expiry_date > current_time,
                Subscription.monthly_sip_target.isnot(None),
                Subscription.monthly_sip_target > 0
            ).count()

            # Expiring soon (within 7 days)
            expiring_soon = Subscription.query.filter(
                Subscription.expiry_date > current_time,
                Subscription.expiry_date <= current_time + datetime.timedelta(days=7)
            ).count()

            return {
                'active_subscriptions': active_subs,
                'sip_enabled_subscriptions': sip_subs,
                'expiring_soon': expiring_soon,
                'last_updated': current_time
            }

        except Exception as e:
            logging.error(f"Error getting subscription summary: {e}")
            return None


def test_database_connection():
    """
    Test if database connection and models are working correctly.
    """
    with get_app().app_context():
        try:
            # Test basic query
            user_count = User.query.count()
            broker_count = Broker.query.count()
            subscription_count = Subscription.query.count()

            logging.info(f"📊 Database Connection Test:")
            logging.info(f"   Users: {user_count}")
            logging.info(f"   Brokers: {broker_count}")
            logging.info(f"   Subscriptions: {subscription_count}")

            # Test SIP subscriptions specifically
            sip_count = Subscription.query.filter(
                Subscription.monthly_sip_target.isnot(None),
                Subscription.monthly_sip_target > 0
            ).count()

            logging.info(f"   SIP Enabled: {sip_count}")

            return True

        except Exception as e:
            logging.error(f"❌ Database connection test failed: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return False


def test_client_fetcher():
    """
    Test function to verify the client fetcher works correctly.
    """
    print("🧪 Testing Client Fetcher...")

    # First test database connection
    if not test_database_connection():
        print("❌ Database connection failed!")
        return False

    try:
        clients = get_active_clients_with_sip()
        print(f"✅ Found {len(clients)} active clients with SIP targets")

        if clients:
            print("\n📊 Client Details:")
            for i, client in enumerate(clients[:5]):  # Show first 5 clients
                validation = validate_client_credentials(client)
                status = "✅" if validation['is_valid'] else "❌"
                print(
                    f"  {i + 1}. {status} {client['customer_id']}: {client['broker_name']} - SIP ₹{client['monthly_sip_target']:,}")
                if not validation['is_valid']:
                    print(f"      Missing: {validation['missing_fields']}")

        summary = get_subscription_summary()
        if summary:
            print(f"\n📈 Subscription Summary:")
            print(f"  • Active: {summary['active_subscriptions']}")
            print(f"  • With SIP: {summary['sip_enabled_subscriptions']}")
            print(f"  • Expiring Soon: {summary['expiring_soon']}")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        print(f"Full error: {traceback.format_exc()}")
        return False


if __name__ == "__main__":
    # Test the function
    success = test_client_fetcher()
    if success:
        print("\n🎉 Client fetcher test passed!")
    else:
        print("\n💥 Client fetcher test failed!")