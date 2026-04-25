import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from dateutil.relativedelta import relativedelta


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'user'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text, nullable=False)
    state = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    pin = db.Column(db.String(6), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    mobile = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    disclaimer_accepted = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime)
    customer_id = db.Column(db.String(50), unique=True, nullable=False)

    referrer_id = db.Column(db.Integer, db.ForeignKey('referrer.id'))
    referrer_commission_percent = db.Column(db.Float)

    portal_pw_enc = db.Column(db.Text)
    portal_pw_iv = db.Column(db.Text)
    portal_pw_tag = db.Column(db.Text)

    low_balance_alerts_enabled = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ClientPreferences(db.Model):
    __tablename__ = 'client_preferences'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    excluded_etfs = db.Column(JSON, default=list)
    excluded_sectors = db.Column(JSON, default=list)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    user = relationship('User', backref=db.backref('preferences', uselist=False))


class ClientStrategy(db.Model):
    __tablename__ = 'client_strategy'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    broker_id = db.Column(db.Integer, db.ForeignKey('broker.id'), nullable=False)
    mode = db.Column(db.String(20), default='default')
    enabled = db.Column(db.Boolean, default=False)
    parts = db.Column(db.Integer, default=40)
    profit_target = db.Column(db.Float, default=0.03)
    universe = db.Column(JSON, default=list)
    liquid_symbol = db.Column(db.String(50), default='LIQUIDBEES')
    initialized_liquid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    user = relationship('User', backref=db.backref('strategies', lazy=True))
    broker = relationship('Broker', backref=db.backref('strategies', lazy=True))


class Plan(db.Model):
    __tablename__ = 'plan'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    features = db.Column(db.Text)
    status = db.Column(db.String(20), default='Active')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    max_sip_amount = db.Column(db.Integer)
    monthly_price = db.Column(db.Float)
    quarterly_price = db.Column(db.Float)
    half_yearly_price = db.Column(db.Float)
    annually_price = db.Column(db.Float)

    has_copy_trading = db.Column(db.Boolean, default=False)
    max_brokers = db.Column(db.Integer, default=1)


class SupportedBroker(db.Model):
    __tablename__ = 'supported_broker'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    requires_password = db.Column(db.Boolean, default=True)
    requires_totp = db.Column(db.Boolean, default=False)
    requires_api_key = db.Column(db.Boolean, default=False)
    requires_api_secret = db.Column(db.Boolean, default=False)
    requires_vendor_code = db.Column(db.Boolean, default=False)
    requires_imei = db.Column(db.Boolean, default=False)
    requires_access_token = db.Column(db.Boolean, default=False)
    requires_client_id = db.Column(db.Boolean, default=False)
    requires_mobile = db.Column(db.Boolean, default=False)

    open_account_url = db.Column(db.Text)
    api_activation_url = db.Column(db.Text)
    
    video_api_key_url = db.Column(db.Text)
    video_vendor_code_url = db.Column(db.Text)
    video_imei_url = db.Column(db.Text)
    video_totp_url = db.Column(db.Text)
    video_api_secret_url = db.Column(db.Text)
    video_access_token_url = db.Column(db.Text)
    video_client_id_url = db.Column(db.Text)
    video_mobile_url = db.Column(db.Text)
    video_password_url = db.Column(db.Text)
    
    help_text_api_key = db.Column(db.Text)
    help_text_api_secret = db.Column(db.Text)
    help_text_client_id = db.Column(db.Text)
    help_text_password = db.Column(db.Text)
    help_text_totp = db.Column(db.Text)
    help_text_vendor_code = db.Column(db.Text)
    help_text_imei = db.Column(db.Text)
    help_text_mobile = db.Column(db.Text)
    
    help_image_api_key = db.Column(db.Text)
    help_image_api_secret = db.Column(db.Text)
    help_image_client_id = db.Column(db.Text)
    help_image_password = db.Column(db.Text)
    help_image_totp = db.Column(db.Text)
    help_image_vendor_code = db.Column(db.Text)
    help_image_imei = db.Column(db.Text)
    help_image_mobile = db.Column(db.Text)


class Broker(db.Model):
    __tablename__ = 'broker'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('brokers', lazy=True))
    customer_id = db.Column(db.String(50), nullable=False)

    broker_name = db.Column(db.String(50), nullable=False)
    user_id_broker = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    totp_secret = db.Column(db.String(255))
    api_key = db.Column(db.Text)
    api_secret = db.Column(db.String(255))
    vendor_code = db.Column(db.String(100))
    imei = db.Column(db.String(100))
    mobile = db.Column(db.String(30))
    username = db.Column(db.String(100))
    otp = db.Column(db.String(10))
    secret_key = db.Column(db.Text)
    token_id = db.Column(db.Text)
    session_token = db.Column(db.Text)
    timestamp = db.Column(db.DateTime)
    broker_login_type = db.Column(db.String(50))

    is_master = db.Column(db.Boolean, default=False)
    copy = db.Column(db.Boolean, default=True)
    copy_multiplier = db.Column(db.Float, default=1.0)

    available_balance = db.Column(db.Float)
    balance_checked_at = db.Column(db.DateTime)

    access_token = db.Column(db.Text)
    
    dhan_client_id_enc = db.Column(db.Text)
    dhan_client_id_iv = db.Column(db.Text)
    dhan_client_id_tag = db.Column(db.Text)
    
    api_key_enc = db.Column(db.Text)
    api_key_iv = db.Column(db.Text)
    api_key_tag = db.Column(db.Text)
    
    subscription_status = db.Column(db.String(20), default='Inactive')
    subscription_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_updated = db.Column(db.DateTime)

    test_order_completed = db.Column(db.Boolean, default=False)
    test_order_confirmed = db.Column(db.Boolean, default=False)
    test_order_attempts = db.Column(db.Integer, default=0)
    test_order_last_attempt = db.Column(db.DateTime)

    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'))
    plan = db.relationship('Plan', backref=db.backref('brokers', lazy=True))

    proxy_ip = db.Column(db.String(255), nullable=True)
    proxy_label = db.Column(db.String(100), nullable=True)


class ProxyPool(db.Model):
    """Webshare static proxy pool — one entry per purchased proxy slot."""
    __tablename__ = 'proxy_pool'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    proxy_ip = db.Column(db.String(50), nullable=False)
    proxy_port = db.Column(db.String(10), nullable=False)
    proxy_username = db.Column(db.String(100), nullable=False)
    proxy_password = db.Column(db.String(100), nullable=False)
    proxy_url = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(100))
    country = db.Column(db.String(50))
    city = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    assigned_broker_id = db.Column(db.Integer, db.ForeignKey('broker.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    assigned_broker = db.relationship('Broker', foreign_keys=[assigned_broker_id],
                                      backref=db.backref('proxy_slot', uselist=False))


class Subscription(db.Model):
    __tablename__ = 'subscription'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(50), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'))
    plan_name = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expiry_date = db.Column(db.DateTime, nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default='Paid')
    payment_method = db.Column(db.String(50))
    payment_id = db.Column(db.String(100))
    amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_queued = db.Column(db.Boolean, default=False)
    billing_cycle = db.Column(Enum('monthly', 'quarterly', 'half_yearly', 'annually', name='billing_cycle_enum'), nullable=False)
    monthly_sip_target = db.Column(db.Float, nullable=True)
    sip_target_updated_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User',
                           primaryjoin="Subscription.customer_id == User.customer_id",
                           foreign_keys="[Subscription.customer_id]",
                           backref=db.backref('subscriptions', lazy=True))
    plan = db.relationship('Plan', backref=db.backref('subscriptions', lazy=True))


class PaymentMethod(db.Model):
    __tablename__ = 'payment_method'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    payment_method = db.Column(db.Text)
    payment_id = db.Column(db.Text)
    amount_paid = db.Column(db.String(255))
    payment_status = db.Column(db.Text)
    customer_id = db.Column(db.Text)
    payment_data = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class SubscriptionStatus(db.Model):
    __tablename__ = 'subscription_status'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class SchedulerSettings(db.Model):
    __tablename__ = 'scheduler_settings'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    session_test_time = db.Column(db.String(5), default='10:30')
    execution_time = db.Column(db.String(5), default='15:10')
    driver_check_enabled = db.Column(db.Boolean, default=True)
    password_check_enabled = db.Column(db.Boolean, default=True)
    email_notifications_enabled = db.Column(db.Boolean, default=True)
    max_failed_clients_threshold = db.Column(db.Integer, default=3)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    updated_by = db.Column(db.String(50))

    low_balance_threshold_percent = db.Column(db.Integer, default=20)
    max_single_etf_percent = db.Column(db.Integer, default=20)


class ExecutionRun(db.Model):
    __tablename__ = 'execution_run'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime)
    mode = db.Column(db.String(20), default='headless', nullable=False)
    status = db.Column(db.String(20), default='running', nullable=False)
    message = db.Column(db.Text)
    total_clients = db.Column(db.Integer, default=0)
    processed = db.Column(db.Integer, default=0)
    passed = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    total_orders = db.Column(db.Integer, default=0)
    ok_orders = db.Column(db.Integer, default=0)
    fail_orders = db.Column(db.Integer, default=0)
    trace_id = db.Column(db.String(64))
    created_by_admin_id = db.Column(db.Integer)


class OrderEvent(db.Model):
    __tablename__ = 'order_event'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('execution_run.id', ondelete='CASCADE'))
    customer_id = db.Column(db.String(50))
    broker_name = db.Column(db.String(50))
    symbol = db.Column(db.String(50))
    side = db.Column(db.String(10), default='BUY')
    qty = db.Column(db.Integer)
    status = db.Column(db.String(20))
    error = db.Column(db.Text)
    order_ref = db.Column(db.String(100))
    placed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    run = db.relationship('ExecutionRun', backref=db.backref('events', lazy=True))


class HealthCheckRun(db.Model):
    __tablename__ = 'health_check_run'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime)
    mode = db.Column(db.String(20), default='headless', nullable=False)
    driver_issues = db.Column(db.Boolean, default=False)
    total_clients = db.Column(db.Integer, default=0)
    passed = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    failed_clients_json = db.Column(JSON)


class MonthlyInvestment(db.Model):
    __tablename__ = 'monthly_investment'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(50), nullable=False)
    day = db.Column(db.Date, default=datetime.date.today)
    month = db.Column(db.String(7), nullable=False)
    invested_amount = db.Column(db.Float, default=0.0, nullable=False)
    etf_details_json = db.Column(JSON)


class Referrer(db.Model):
    __tablename__ = 'referrer'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255))
    mobile = db.Column(db.String(30))
    default_commission_percent = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ReferralCommission(db.Model):
    __tablename__ = 'referral_commission'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    referrer_id = db.Column(db.Integer, db.ForeignKey('referrer.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=False)
    payment_id = db.Column(db.String(100))
    amount_paid = db.Column(db.Float, nullable=False)
    commission_percent = db.Column(db.Float, nullable=False)
    commission_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    paid_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('referral_commissions', lazy=True))
    referrer = db.relationship('Referrer', backref=db.backref('commissions', lazy=True))
    subscription = db.relationship('Subscription', backref=db.backref('referral_commissions', lazy=True))


class ReferralPayout(db.Model):
    __tablename__ = 'referral_payout'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('referrer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    referrer = db.relationship('Referrer', backref=db.backref('payouts', lazy=True))


class Campaign(db.Model):
    __tablename__ = 'campaign'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    total_seats = db.Column(db.Integer, nullable=False)
    seats_taken = db.Column(db.Integer, default=0)
    discount_type = db.Column(db.String(20), nullable=False)  # 'percentage' or 'fixed'
    discount_value = db.Column(db.Float, nullable=False)
    applicable_plan_ids = db.Column(db.Text)  # comma-separated plan IDs, blank = all
    applicable_billing_cycles = db.Column(db.Text)  # comma-separated cycles, blank = all
    display_offer_scope = db.Column(db.Text)  # display-only text e.g. "Annual plan only"
    display_validity_text = db.Column(db.String(200))  # display-only validity text e.g. "Valid for 1 month"
    terms_text = db.Column(db.Text)  # display-only terms for email
    alert_thresholds = db.Column(db.Text)  # comma-separated seat counts for email alerts e.g. "50,100,150"
    alerts_sent = db.Column(db.Text, default='')  # comma-separated thresholds already triggered
    is_active = db.Column(db.Boolean, default=True)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    registrations = db.relationship('CampaignRegistration', backref='campaign', lazy=True)


class CampaignRegistration(db.Model):
    __tablename__ = 'campaign_registration'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    discount_code = db.Column(db.String(50), unique=True, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    registered_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    used_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('campaign_registrations', lazy=True))


class DiscountCode(db.Model):
    __tablename__ = 'discount_code'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), nullable=False)  # 'percentage' or 'fixed'
    discount_value = db.Column(db.Float, nullable=False)
    applicable_plan_ids = db.Column(db.Text)  # comma-separated plan IDs, blank = all
    applicable_billing_cycles = db.Column(db.Text)  # comma-separated cycles, blank = all
    max_uses = db.Column(db.Integer, default=0)  # 0 = unlimited
    times_used = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    valid_from = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    campaign = db.relationship('Campaign', backref=db.backref('discount_codes', lazy=True))
    assigned_user = db.relationship('User', backref=db.backref('assigned_discount_codes', lazy=True))


class DiscountUsage(db.Model):
    __tablename__ = 'discount_usage'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    discount_code_id = db.Column(db.Integer, db.ForeignKey('discount_code.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=True)
    original_amount = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, nullable=False)
    final_amount = db.Column(db.Float, nullable=False)
    used_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    discount_code = db.relationship('DiscountCode', backref=db.backref('usages', lazy=True))
    user = db.relationship('User', backref=db.backref('discount_usages', lazy=True))
    subscription = db.relationship('Subscription', backref=db.backref('discount_usages', lazy=True))


class EmailSettings(db.Model):
    """Email configuration settings stored in database for admin panel"""
    __tablename__ = 'email_settings'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    
    # Provider selection: 'zoho' or 'gmail'
    provider = db.Column(db.String(20), default='zoho')
    
    # Zoho Settings
    zoho_smtp_server = db.Column(db.String(100), default='smtppro.zoho.in')
    zoho_smtp_port = db.Column(db.Integer, default=465)
    zoho_email = db.Column(db.String(120), default='support@smartetfalgo.com')
    zoho_password = db.Column(db.Text)
    
    # Gmail Settings
    gmail_smtp_server = db.Column(db.String(100), default='smtp.gmail.com')
    gmail_smtp_port = db.Column(db.Integer, default=587)
    gmail_email = db.Column(db.String(120), default='smartetfalgo@gmail.com')
    gmail_password = db.Column(db.Text)
    
    # Common settings
    admin_email = db.Column(db.String(120))
    sender_name = db.Column(db.String(100), default='SmartETF Algo')
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    updated_by = db.Column(db.String(50))

    def get_smtp_config(self):
        """Get SMTP configuration based on selected provider"""
        sender_name = self.sender_name or 'SmartETF Algo'
        if self.provider == 'zoho':
            return {
                'server': self.zoho_smtp_server,
                'port': self.zoho_smtp_port,
                'email': self.zoho_email,
                'password': self.zoho_password,
                'use_ssl': self.zoho_smtp_port == 465,
                'sender_name': sender_name,
            }
        else:  # gmail
            return {
                'server': self.gmail_smtp_server,
                'port': self.gmail_smtp_port,
                'email': self.gmail_email,
                'password': self.gmail_password,
                'use_ssl': self.gmail_smtp_port == 465,
                'sender_name': sender_name,
            }
