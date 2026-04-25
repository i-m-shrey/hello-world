from flask import Flask
from models import db, Plan
from app import Broker, SupportedBroker, PaymentMethod





def create_default_plans():
    """Create default subscription plans if none exist."""
    try:
        # Check if plans exist using raw SQL to avoid schema issues
        result = db.session.execute(db.text("SELECT COUNT(*) FROM plan")).scalar()

        if result == 0:
            plans = [
                Plan(
                    name="Basic Plan",
                    description="Basic ETF trading features for a single broker",
                    duration=30,
                    price=499.00,
                    features="Single broker access\nBasic ETF Investment\nEmail support",
                    status='Active',
                    is_active=True,
                    has_copy_trading=False,
                    max_sip_amount=20000,
                    max_brokers=1
                ),
                Plan(
                    name="Standard Plan",
                    description="Enhanced ETF trading with Investment functionality",
                    duration=90,
                    price=1349.00,
                    features="Single broker access\nInvestment functionality\nPriority support",
                    status='Active',
                    is_active=True,
                    has_copy_trading=True,
                    max_sip_amount=20000,
                    max_brokers=1
                ),
                Plan(
                    name="Premium Plan",
                    description="Full featured ETF trading platform for professionals",
                    duration=365,
                    price=4999.00,
                    features="No Need to Buy Subscription Again ang Again.(Yearly Package)",
                    status='Active',
                    is_active=True,
                    has_copy_trading=True,
                    max_sip_amount=20000,
                    max_brokers=1
                )
            ]

            for plan in plans:
                db.session.add(plan)

            db.session.commit()
            print(f"Created {len(plans)} default subscription plans")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default plans: {e}")


def create_default_supported_brokers():
    """Create default supported brokers if none exist."""
    try:
        if SupportedBroker.query.count() == 0:
            brokers = [
                SupportedBroker(
                    name="FINVASIA",
                    description="FINVASIA API Integration",
                    is_active=True,
                    requires_totp=True,
                    requires_vendor_code=True,
                    requires_api_secret=True,
                    requires_imei=True
                ),
                SupportedBroker(
                    name="ZERODHA",
                    description="ZERODHA API Integration",
                    is_active=True,
                    requires_api_key=True,
                    requires_api_secret=True,
                    requires_access_token=True
                ),
                SupportedBroker(
                    name="UPSTOX",
                    description="UPSTOX API Integration",
                    is_active=True,
                    requires_api_key=True,
                    requires_api_secret=True,
                    requires_mobile=True,
                    requires_password=True,
                    requires_totp=True
                ),
                SupportedBroker(
                    name="GROWW",
                    description="GROWW API Integration",
                    is_active=True,
                    requires_api_key=True,
                    requires_totp=True,
                    requires_password=False
                ),
                SupportedBroker(
                    name="ANGEL",
                    description="Angel One (SmartAPI) Integration",
                    is_active=True,
                    requires_api_key=True,
                    requires_client_id=True,
                    requires_password=True,
                    requires_totp=True
                ),
                SupportedBroker(
                    name="MSTOCK",
                    description="MSTOCK API Integration",
                    is_active=True,
                    requires_api_key=True,
                    requires_api_secret=True
                ),
                SupportedBroker(
                    name="DHAN",
                    description="DHAN API Integration",
                    is_active=True,
                    requires_access_token=True
                )
            ]

            for broker in brokers:
                db.session.add(broker)

            db.session.commit()
            print(f"Created {len(brokers)} default supported brokers")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default supported brokers: {e}")


def create_default_payment_methods():
    """Create default payment methods if none exist."""
    try:
        if PaymentMethod.query.count() == 0:
            methods = [
                PaymentMethod(
                    name="Credit Card",
                    description="Payment using credit card",
                    is_active=True
                ),
                PaymentMethod(
                    name="Debit Card",
                    description="Payment using debit card",
                    is_active=True
                ),
                PaymentMethod(
                    name="UPI",
                    description="Unified Payment Interface",
                    is_active=True
                ),
                PaymentMethod(
                    name="Net Banking",
                    description="Payment through net banking",
                    is_active=True
                ),
                PaymentMethod(
                    name="PayTM",
                    description="Payment through PayTM wallet",
                    is_active=True
                )
            ]

            for method in methods:
                db.session.add(method)

            db.session.commit()
            print(f"Created {len(methods)} default payment methods")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default payment methods: {e}")
