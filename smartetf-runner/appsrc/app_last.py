from dateutil.relativedelta import relativedelta
from flask import Flask, request, render_template, redirect, session, g, flash, send_from_directory, request, jsonify, \
    url_for
import os
from models import db, Plan, User, SupportedBroker, PaymentMethod, SubscriptionStatus, Broker, Subscription, \
    PaymentMethod, SubscriptionStatus, SchedulerSettings, ExecutionRun, OrderEvent, HealthCheckRun, MonthlyInvestment
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus
import datetime
from datetime import timedelta
from functools import wraps
import pandas as pd
import uuid
from sqlalchemy.sql import text
import jinja2
import traceback
import razorpay
import logging
# from startup import init_database
from email_notifications import send_new_registration_notification

# Load environment variables
load_dotenv()

# Configure database for PostgreSQL
# password = quote_plus(os.getenv('DB_PASSWORD', 'P@ssword123'))
# supabasepassword = quote_plus(os.getenv('DB_PASSWORD', 'P@ssword123211600&prince'))
# db_url = f"postgresql://postgres:{password}@localhost/etf_portal"
# db_url = f"postgresql://postgres.qogfivsjxarodbyokfkn:{supabasepassword}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
# db_url = "postgresql+pg8000://postgres.qogfivsjxarodbyokfkn:P%40ssword123211600%26prince@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
db_url = "postgresql+pg8000://postgres.qogfivsjxarodbyokfkn:P%40ssword123211600%26prince@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"

# db_url = f"mysql+mysqldb://root:{password}@localhost/etf_portal"
# db_url = f"mysql+mysqldb://root:{password}@localhost/etf_portal"
print(f"Using database URL: {db_url}")

# Initialize Flask app
app = Flask(__name__)

# Configure app
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret_key')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,  # Maximum number of connections to keep open
    'pool_recycle': 300,  # Recycle connections every 5 minutes
    'pool_pre_ping': True,  # Verify connections before use
    'max_overflow': 0  # Don't allow overflow connections
}

# # After defining all your helper functions but before calling init_database
# app.create_admin_user = create_admin_user
# app.create_default_plans = create_default_plans
# app.create_default_supported_brokers = create_default_supported_brokers
# app.create_default_payment_methods = create_default_payment_methods
# app.create_default_subscription_statuses = create_default_subscription_statuses

# Initialize SQLAlchemy
db.init_app(app)
# with app.app_context():
#     db.create_all()
#     create_admin_user()
#     create_default_plans()
#     create_default_supported_brokers()
#     create_default_payment_methods()
#     create_default_subscription_statuses()
#     os.makedirs('data', exist_ok=True)

from api_routes import api_bp

app.register_blueprint(api_bp)

# Add after other configuration settings
# Razorpay Configuration
# razorpay_key_id = os.getenv('RAZORPAY_KEY_ID', 'rzp_test_35DF4o91Gg9iMi')
# razorpay_key_secret = os.getenv('RAZORPAY_KEY_SECRET', 'HZg01vKFg1t1hhrlfVUkQXYv')
razorpay_key_id = os.getenv('RAZORPAY_KEY_ID')
razorpay_key_secret = os.getenv('RAZORPAY_KEY_SECRET')


# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------
def export_brokers_to_csv(brokers, csv_path='data/accounts.csv'):
    """Export broker connections from the database to accounts.csv"""
    # Ensure the directory exists
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    # Create CSV data
    rows = []
    for broker in brokers:
        # Get subscription expiry if it exists
        subscription_expiry = ''
        if broker.subscription_expiry:
            subscription_expiry = broker.subscription_expiry.strftime('%d-%m-%Y')

        rows.append({
            'USER_ID': broker.user_id_broker,
            'PASSWORD': broker.password or '',
            'TOTP_SECRET': broker.totp_secret or '',
            'BROKER': broker.broker_name,
            'API_KEY': broker.api_key or '',
            'API_SECRET': broker.api_secret or '',
            'VENDOR_CODE': broker.vendor_code or '',
            'IMEI': broker.imei or '',
            'ACCESS_TOKEN': broker.access_token or '',
            'IS_MASTER': str(broker.is_master).upper(),
            'COPY_MULTIPLIER': broker.copy_multiplier,
            'COPY': str(broker.copy).upper(),
            'SUBSCRIPTION_EXPIRY': subscription_expiry,
            'SUBSCRIPTION_STATUS': broker.subscription_status or 'Inactive'
        })

    # Create the DataFrame and save as CSV
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)

    return csv_path


def get_current_subscription(user_id):
    """Get the current active subscription for a user."""
    now = datetime.datetime.now()
    user = User.query.get(user_id)
    if not user:
        return None

    return Subscription.query.filter(
        Subscription.customer_id == user.customer_id,
        Subscription.payment_status.in_(['Successful', 'Active', 'Paid']),
        db.or_(Subscription.is_queued == False, Subscription.is_queued.is_(None)),
        Subscription.start_date <= now,
        Subscription.expiry_date > now
    ).order_by(Subscription.expiry_date.desc()).first()


def get_queued_subscriptions(user_id):
    """Get all queued subscriptions for a user in start date order."""
    now = datetime.datetime.now()
    user = User.query.get(user_id)
    return Subscription.query.filter(
        Subscription.customer_id == user.customer_id,
        Subscription.payment_status.in_(['Successful', 'Paid', 'Active']),
        Subscription.is_queued == True,
        Subscription.start_date > now
    ).order_by(Subscription.start_date.asc()).all()


def get_upcoming_subscriptions(user_id):
    """Get all upcoming subscriptions (future start date) for a user."""
    now = datetime.datetime.utcnow()
    user = User.query.get(user_id)
    if not user:
        return []

    return Subscription.query.filter(
        Subscription.customer_id == user.customer_id,
        Subscription.payment_status.in_(['Successful', 'Paid', 'Active']),
        Subscription.start_date > now,
        Subscription.expiry_date > now
    ).order_by(Subscription.start_date.asc()).all()


def get_subscription_status(subscription):
    """Determine the status of a subscription."""
    if not subscription:
        return "Inactive"

    now = datetime.datetime.now()
    if subscription.expiry_date > now:
        return subscription.payment_status
    else:
        return "Expired"


def activate_queued_subscriptions():
    """
    Check for queued subscriptions that should now be active and update them.
    This function should be called regularly (e.g., by a scheduler or cron job).
    """
    now = datetime.datetime.now()

    # Find subscriptions that were queued but should now be active
    subscriptions_to_activate = Subscription.query.filter(
        Subscription.payment_status.in_(['Successful', 'Paid', 'Active']),
        Subscription.is_queued == True,
        # ... other conditions
    ).filter(
        Subscription.start_date <= now,
        Subscription.expiry_date > now
    ).all()

    for subscription in subscriptions_to_activate:
        # Mark as no longer queued
        subscription.is_queued = False

        # Update broker accounts for this user
        user = User.query.filter_by(customer_id=subscription.customer_id).first()
        broker_accounts = Broker.query.filter_by(user_id=user.id).all()
        for broker in broker_accounts:
            broker.subscription_status = 'Active'
            broker.subscription_expiry = subscription.expiry_date
            broker.plan_id = subscription.plan_id

            # Update Algo Investment settings based on plan
            if subscription.plan.has_copy_trading:
                broker.copy = True
                # If no master account exists, make the first one the master
                if not Broker.query.filter_by(user_id=subscription.customer_id,
                                              is_master=True).first() and broker_accounts:
                    broker_accounts[0].is_master = True

    if subscriptions_to_activate:
        try:
            db.session.commit()
            print(f"Activated {len(subscriptions_to_activate)} queued subscriptions")

            # Export updated broker data
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)
        except Exception as e:
            db.session.rollback()
            print(f"Error activating queued subscriptions: {str(e)}")


def auto_enable_copy_trading(user_id, broker_id):
    """
    Auto-enable Algo Investment for new broker if client has valid subscription + SIP target
    """
    try:
        # Get user details
        user = User.query.get(user_id)
        if not user:
            logging.error(f"User {user_id} not found")
            return False

        # Check if user has active subscription with SIP target
        current_subscription = get_current_subscription(user_id)

        if not current_subscription:
            logging.info(f"No active subscription for user {user_id}")
            return False

        if not current_subscription.monthly_sip_target or current_subscription.monthly_sip_target <= 0:
            logging.info(f"No SIP target set for user {user_id}")
            return False

        # Enable Algo Investment on the broker
        broker = Broker.query.get(broker_id)
        if broker:
            broker.copy = True
            broker.copy_multiplier = 1.0  # Will be calculated dynamically
            broker.subscription_status = 'Active'
            broker.subscription_expiry = current_subscription.expiry_date

            db.session.commit()

            # Send notification email
            send_copy_trading_enabled_email(user_id, broker.broker_name, current_subscription.monthly_sip_target)

            logging.info(f"✅ Algo Investment auto-enabled for user {user_id}, broker {broker_id}")

            # Log to application activity
            log_copy_trading_activation(user.customer_id, broker.broker_name, current_subscription.monthly_sip_target)

            return True
        else:
            logging.error(f"Broker {broker_id} not found")
            return False

    except Exception as e:
        logging.error(f"Error enabling Algo Investment for user {user_id}: {e}")
        db.session.rollback()
        return False


def send_copy_trading_enabled_email(user_id, broker_name, sip_amount):
    """Send email notification when Algo Investment is enabled"""
    try:
        user = User.query.get(user_id)
        if not user:
            return

        subject = "🎉 SmartETF Algo Investment Activated"

        body = f"""
        Dear {user.username},

        Great news! Your Algo Investment has been successfully activated.

        📊 Broker Account: {broker_name}
        💰 Monthly SIP Target: ₹{sip_amount:,.2f}
        📅 Trading Starts: Tomorrow at 3:10 PM IST
        🎯 Strategy: Automated ETF investment based on market conditions

        What happens next:
        ✅ Our system will analyze market conditions daily
        ✅ ETF orders will be placed automatically in your {broker_name} account
        ✅ Order quantities will be customized to your ₹{sip_amount:,.2f} monthly target
        ✅ You'll receive email confirmations for all trades

        Monitor your portfolio: Dashboard

        Questions? Reply to this email or contact our support team.

        Happy Investing!
        SmartETF Team
        """

        # TODO: Integrate with your email service
        # For now, just log the email content
        logging.info(f"📧 Algo Investment activation email prepared for {user.email}")
        logging.info(f"Subject: {subject}")
        logging.info(f"Body preview: {body[:200]}...")

        # Uncomment when email service is integrated:
        # send_email(user.email, subject, body)

    except Exception as e:
        logging.error(f"Error preparing activation email: {e}")


def log_copy_trading_activation(customer_id, broker_name, sip_amount):
    """Log Algo Investment activation for monitoring"""
    try:
        log_entry = {
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'customer_id': customer_id,
            'broker_name': broker_name,
            'sip_amount': sip_amount,
            'action': 'copy_trading_activated',
            'source': 'auto_enable_on_broker_addition'
        }

        # Log to file or database
        logging.info(f"📊 Algo Investment Activation: {log_entry}")

        # TODO: You can also save this to a dedicated table for analytics

    except Exception as e:
        logging.error(f"Error logging Algo Investment activation: {e}")


def send_sip_update_email(user, new_sip_amount, broker_count):
    """Send email when SIP amount is updated"""
    try:
        subject = f"SIP Target Updated - ₹{new_sip_amount:,.2f}"

        body = f"""
        Dear {user.username},

        Your monthly SIP target has been updated successfully.

        📊 New Monthly Target: ₹{new_sip_amount:,.2f}
        🔗 Connected Brokers: {broker_count}
        📅 Effective From: Next trading session (3:10 PM IST)

        Your Algo Investment will adjust automatically to meet this new target.

        Monitor your progress: Dashboard

        Best regards,
        SmartETF Team
        """

        logging.info(f"📧 SIP update email prepared for {user.email}")
        # TODO: Integrate with actual email service

    except Exception as e:
        logging.error(f"Error preparing SIP update email: {e}")


# ------------------------------------------------------------------------------
# Context Processors & Filters
# ------------------------------------------------------------------------------
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = db.session.get(User, user_id)


@app.before_request
def check_disclaimer_acceptance():
    """Check if user has accepted the disclaimer before accessing protected routes"""
    # List of routes that require disclaimer acceptance
    protected_routes = ['dashboard', 'add_broker', 'view_broker', 'edit_broker', 'delete_broker',
                        'view_plans', 'checkout', 'plan_checkout', 'profile']

    # Only check for logged in users and protected routes
    if 'user_id' in session and request.endpoint in protected_routes:
        user_id = session['user_id']
        user = User.query.get(user_id)

        # Skip disclaimer check for admin users
        if user and user.is_admin:
            return None

        # If regular user exists and hasn't accepted disclaimer
        if user and not user.disclaimer_accepted:
            # If not already on the disclaimer page, redirect there
            if request.endpoint != 'show_disclaimer' and request.endpoint != 'accept_disclaimer':
                flash("Please accept the disclaimer to continue.", "warning")
                return redirect(url_for('show_disclaimer'))


# @app.route("/")
# def index():
#     return "<h1>SmartETF backend is live 🎯</h1>"


@app.context_processor
def inject_user():
    return {'current_user': g.user}


@app.context_processor
def inject_subscription_helpers():
    return {
        'get_queued_subscriptions': get_queued_subscriptions
    }


@app.template_filter('datetime')
def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    if value:
        return value.strftime(format)
    return ""


@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now}


@app.context_processor
def inject_now():
    return {'now': datetime.datetime.utcnow}  # Changed to utcnow to match subscription logic


# ------------------------------------------------------------------------------
# Authentication & Middleware
# ------------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login to access this page", "error")
            return redirect(url_for('login'))

        user = db.session.get(User, session['user_id'])
        if not user or not user.is_admin:
            flash("Admin privileges required", "error")
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)

    return decorated_function


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login to access this page", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# ------------------------------------------------------------------------------
# Routes: Authentication
# ------------------------------------------------------------------------------
# @app.route('/')
# def home():
#     return render_template('index.html')


@app.route('/')
def show_frontend():
    return render_template('marketing/index.html')


@app.route('/home')
def home():
    return redirect(url_for('show_frontend'))


@app.route('/marketing_static/<path:filename>')
def marketing_static(filename):
    return send_from_directory(os.path.join(app.root_path, 'marketing/static'), filename)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_identifier = request.form.get('username')  # This field accepts both username and email
        password = request.form.get('password')

        # Query user by either username OR email
        user = User.query.filter(
            db.or_(
                User.username == login_identifier,
                User.email == login_identifier
            )
        ).first()

        if user and user.check_password(password):
            # Check if account is active
            if not user.is_active:
                flash('Your account is inactive. Please contact support.', 'error')
                return render_template('login.html')

            # Store user info in session
            session['user_id'] = user.id
            session.permanent = True

            # Update last login time
            user.last_login = datetime.datetime.utcnow()
            db.session.commit()

            # Skip disclaimer check for admin users
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))

            # Check if disclaimer has been accepted
            if not user.disclaimer_accepted:
                return redirect(url_for('show_disclaimer'))

            # If disclaimer is accepted, redirect to dashboard
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username/email or password', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    # 🔐 Redirect if already logged in
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        print("User:", user)
        # print(user)
        if user:
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        address = request.form.get('address')
        state = request.form.get('state')
        city = request.form.get('city')
        pin = request.form.get('pin')
        mobile = request.form.get('mobile')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Validation checks
        if not username or not email or not mobile or not password or not full_name or not address or not state or not city or not pin:
            flash("All fields are required", "error")
            return render_template('register.html')

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template('register.html')

        if len(mobile) != 10 or not mobile.isdigit():
            flash("Please enter a valid 10-digit mobile number", "error")
            return render_template('register.html')

        # Check for existing username, email, and mobile
        existing_user = User.query.filter(
            db.or_(
                User.username == username,
                User.email == email,
                User.mobile == mobile
            )
        ).first()

        if existing_user:
            if existing_user.username == username:
                flash("Username already exists", "error")
            elif existing_user.email == email:
                flash("Email already registered", "error")
            elif existing_user.mobile == mobile:
                flash("Mobile number already registered", "error")
            return render_template('register.html')

        # Create new user with UUID as customer_id
        customer_id = generate_next_customer_id()

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            address=address,
            state=state,
            mobile=mobile,
            city=city,
            pin=pin,
            customer_id=customer_id,
            is_admin=False,
            is_active=True,
            created_at=datetime.datetime.utcnow()  # ✅ Add this line
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()

            # Send email notification to admin about new registration
            user_data = {
                'full_name': full_name,
                'username': username,
                'email': email,
                'mobile': mobile,
                'address': address,
                'city': city,
                'state': state,
                'pin': pin,
                'customer_id': customer_id
            }

            try:
                send_new_registration_notification(user_data)
            except Exception as email_error:
                print(f"⚠️ Registration successful but email notification failed: {email_error}")

            flash("Registration successful! You can now log in.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error during registration: {str(e)}", "error")

    return render_template('register.html')


@app.route('/terms-of-service')
def terms_of_service():
    """Terms of Service page"""
    return render_template('legal/terms-of-service.html')


@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page"""
    return render_template('legal/privacy-policy.html')


@app.route('/refund-policy')
def refund_policy():
    """Refund Policy page"""
    return render_template('legal/refund-policy.html')


@app.route('/risk-disclosure')
def risk_disclosure():
    """Risk Disclosure page"""
    return render_template('legal/risk-disclosure.html')


# Optional: Add a general legal index page
@app.route('/legal')
def legal_index():
    """Legal documents index page"""
    return render_template('legal/index.html')


@app.route('/download/pdf/<filename>')
def download_pdf(filename):
    """Download PDF files from static/pdfs directory"""
    try:
        return send_from_directory(
            os.path.join(app.root_path, 'static/pdfs'),
            filename,
            as_attachment=True,
            download_name=filename
        )
    except FileNotFoundError:
        flash('PDF file not found.', 'error')
        return redirect(url_for('show_frontend'))


@app.route('/db/add_disclaimer_column', methods=['GET'])
@admin_required
def add_disclaimer_column():
    try:
        db.session.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS disclaimer_accepted BOOLEAN DEFAULT FALSE;')
        db.session.commit()
        return "Disclaimer column added successfully!"
    except Exception as e:
        db.session.rollback()
        return f"Error adding disclaimer column: {str(e)}"


@app.route('/disclaimer')
@login_required
def show_disclaimer():
    """Show the disclaimer page to the user"""
    return render_template('client/disclaimer.html')


@app.route('/disclaimer/accept', methods=['POST'])
@login_required
def accept_disclaimer():
    """Handle disclaimer acceptance"""
    if 'accept' in request.form:
        user_id = session['user_id']
        user = User.query.get_or_404(user_id)
        user.disclaimer_accepted = True
        db.session.commit()
        flash("Thank you for accepting the disclaimer.", "success")
        return redirect(url_for('dashboard'))
    else:
        flash("You must accept the disclaimer to continue.", "error")
        return redirect(url_for('show_disclaimer'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('is_admin', None)
    flash("You have been logged out successfully", "success")
    return redirect(url_for('login'))


# ------------------------------------------------------------------------------
# Routes: Client
# ------------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)

    # Get current subscription
    current_subscription = get_current_subscription(user_id)
    upcoming_subscriptions = get_upcoming_subscriptions(user_id)
    queued_subscriptions = get_queued_subscriptions(user_id)

    # Get broker connections for the current user
    broker_connections = Broker.query.filter_by(user_id=user_id).all()

    # Check if user can add more brokers
    # Check if user can add more brokers
    max_brokers_reached = True  # Default: no broker addition allowed
    max_brokers_allowed = 0

    if current_subscription:
        plan = Plan.query.get(current_subscription.plan_id)
        if plan:
            max_brokers_allowed = plan.max_brokers
            if len(broker_connections) >= max_brokers_allowed:
                max_brokers_reached = True
            else:
                max_brokers_reached = False
    else:
        max_brokers_reached = True  # Explicitly block broker addition

    # Get available plans
    available_plans = Plan.query.filter_by(is_active=True).all()

    # Check if any broker is marked as master
    any_master = any(broker.is_master for broker in broker_connections)

    # Get trading activity (mock data for now)
    trading_activity = []

    # Calculate month invested (mock for now - will be calculated from CSV files later)
    month_invested = 0
    if current_subscription and current_subscription.monthly_sip_target:
        # TODO: Calculate actual invested amount from CSV files
        # For now, just showing placeholder
        month_invested = 0

    return render_template(
        'client/dashboard.html',
        user=user,
        current_subscription=current_subscription,
        queued_subscriptions=queued_subscriptions,
        upcoming_subscriptions=upcoming_subscriptions,
        broker_connections=broker_connections,
        available_plans=available_plans,
        any_master=any_master,
        trading_activity=trading_activity,
        max_brokers_reached=max_brokers_reached,
        max_brokers_allowed=max_brokers_allowed,
        month_invested=month_invested
    )


@app.route('/update_sip_target', methods=['POST'])
@login_required
def update_sip_target():
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)

    # Get current subscription
    current_subscription = get_current_subscription(user_id)
    if not current_subscription:
        flash('No active subscription found.', 'error')
        return redirect(url_for('dashboard'))

    # Get the SIP target from form
    monthly_sip_target = request.form.get('monthly_sip_target')

    try:
        monthly_sip_target = float(monthly_sip_target)

        # Validate against plan limits
        plan = Plan.query.get(current_subscription.plan_id)
        if not plan:
            flash('Plan not found.', 'error')
            return redirect(url_for('dashboard'))

        if monthly_sip_target > plan.max_sip_amount:
            flash(f'SIP amount cannot exceed plan limit of ₹{plan.max_sip_amount:,}', 'error')
            return redirect(url_for('dashboard'))

        if monthly_sip_target < 1000:
            flash('Minimum SIP amount is ₹1,000', 'error')
            return redirect(url_for('dashboard'))

        # Update subscription with SIP target
        current_subscription.monthly_sip_target = monthly_sip_target
        current_subscription.sip_target_updated_at = datetime.datetime.utcnow()

        # 🆕 AUTO-ENABLE/DISABLE Algo Investment FOR ALL USER'S BROKERS
        user_brokers = Broker.query.filter_by(user_id=user_id, is_master=False).all()

        for broker in user_brokers:
            if monthly_sip_target > 0:
                # Enable Algo Investment
                broker.copy = True
                broker.subscription_status = 'Active'
                broker.subscription_expiry = current_subscription.expiry_date
            else:
                # Disable Algo Investment
                broker.copy = False
                broker.subscription_status = 'Inactive'

        db.session.commit()

        # Send enhanced confirmation message
        if monthly_sip_target > 0:
            message = f'✅ Monthly SIP target updated to ₹{monthly_sip_target:,} - Algo Investment enabled for {len(user_brokers)} broker(s)'

            # Send update email for existing users
            send_sip_update_email(user, monthly_sip_target, len(user_brokers))
        else:
            message = f'⚠️ SIP target set to ₹0 - Algo Investment disabled'

        flash(message, 'success')

    except (ValueError, TypeError):
        flash('Please enter a valid SIP amount.', 'error')

    return redirect(url_for('dashboard'))


@app.route('/broker/add', methods=['GET', 'POST'])
@login_required
def add_broker():
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)
    print(user.customer_id)

    # Check if user already has a broker
    existing_brokers = Broker.query.filter_by(user_id=user_id).count()
    print(1)
    current_plan = None
    max_brokers_reached = False

    # Get current subscription to determine broker limit
    current_subscription = get_current_subscription(user_id)

    # REQUIRE ACTIVE SUBSCRIPTION FOR BROKER ADDITION
    if not current_subscription:
        flash("You must have an active subscription plan to add broker accounts.", "error")
        return redirect(url_for('view_plans'))

    if current_subscription:
        current_plan = Plan.query.get(current_subscription.plan_id)
        print(2)
        # Check if user has reached their broker limit
        if current_plan and existing_brokers >= current_plan.max_brokers:
            max_brokers_reached = True
            flash(f"You have reached the maximum number of brokers ({current_plan.max_brokers}) allowed for your plan.",
                  "error")

    # Get list of supported brokers from database
    supported_brokers = SupportedBroker.query.filter_by(is_active=True).all()
    print(3)
    print(max_brokers_reached)
    print(request.method)
    if request.method == 'POST' and not max_brokers_reached:
        broker_name = request.form.get('broker_name')
        user_id_broker = request.form.get('user_id_broker')
        password = request.form.get('password')
        print(4)
        # Find the selected broker to validate required fields
        selected_broker = SupportedBroker.query.filter_by(name=broker_name).first()
        print(5)
        if not selected_broker:
            flash("Invalid broker selected", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)

        # Broker-specific fields
        totp_secret = request.form.get('totp_secret', '')
        api_key = request.form.get('api_key', '')
        api_secret = request.form.get('api_secret', '')
        vendor_code = request.form.get('vendor_code', '')
        imei = request.form.get('imei', '')
        access_token = request.form.get('access_token', '')

        # Validate input
        if not broker_name or not user_id_broker or not password:
            flash("All required fields must be filled", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)

        # Validate broker-specific required fields
        if selected_broker.requires_totp and not totp_secret:
            flash("TOTP Secret is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        if selected_broker.requires_api_key and not api_key:
            flash("API Key is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        if selected_broker.requires_api_secret and not api_secret:
            flash("API Secret is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        if selected_broker.requires_vendor_code and not vendor_code:
            flash("Vendor Code is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        if selected_broker.requires_imei and not imei:
            flash("IMEI is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        if selected_broker.requires_access_token and not access_token:
            flash("Access Token is required for this broker", "error")
            return render_template('client/add_broker.html',
                                   brokers=supported_brokers,
                                   max_brokers_reached=max_brokers_reached,
                                   current_plan=current_plan)
        print(5)
        # Create new broker
        # Create new broker
        broker = Broker(
            user_id=user_id,
            broker_name=broker_name,
            user_id_broker=user_id_broker,
            password=password,
            totp_secret=totp_secret,
            api_key=api_key,
            api_secret=api_secret,
            vendor_code=vendor_code,
            imei=imei,
            access_token=access_token,
            # Set Algo Investment to automatic (modified as requested)
            is_master=False,  # Default to not master
            copy=True,  # Default to copy trades
            copy_multiplier=1.0,  # Default multiplier

            # Set subscription details - allow adding brokers without subscription
            subscription_status='Inactive' if not current_subscription else 'Active',
            subscription_expiry=None if not current_subscription else current_subscription.expiry_date,
            plan_id=None if not current_subscription else current_subscription.plan_id
        )
        broker.customer_id = user.customer_id
        print(6)
        print(broker)

        # Apply plan settings
        if current_plan and current_plan.has_copy_trading:
            # Auto-configure Algo Investment if the plan supports it
            broker.copy = True

            # If this is the first broker and the plan supports Algo Investment, make it the master
            if existing_brokers == 0:
                broker.is_master = True

        try:
            db.session.add(broker)
            db.session.commit()

            # 🆕 AUTO-ENABLE Algo Investment
            copy_trading_enabled = auto_enable_copy_trading(user_id, broker.id)

            if copy_trading_enabled:
                flash(
                    f"Broker {broker_name} added successfully! 🎉 Algo Investment activated - orders will begin tomorrow at 3:10 PM.",
                    "success")
            else:
                flash(f"Broker {broker_name} added successfully. Set your monthly SIP target to activate Algo Investment.",
                      "info")

            # Export brokers to CSV
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)

            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding broker: {str(e)}", "error")
            logging.error(f"Database error in broker addition: {e}")

    return render_template('client/add_broker.html',
                           brokers=supported_brokers,
                           max_brokers_reached=max_brokers_reached,
                           current_plan=current_plan)


def generate_next_customer_id():
    """Generate the next customer_id by incrementing the highest existing one"""
    # Find the pattern smartetf_user_XXXXX
    pattern = "smartetf_user_"

    # Get the latest user with the highest customer_id
    latest_user = User.query.filter(
        User.customer_id.like(f"{pattern}%")
    ).order_by(db.desc(User.customer_id)).first()

    if latest_user:
        try:
            # Extract the number part
            current_num = int(latest_user.customer_id.replace(pattern, ""))
            # Increment by 1
            next_num = current_num + 1
        except ValueError:
            # Fall back to a default if the format isn't as expected
            next_num = 10001
    else:
        # Start from 10001 if no users exist
        next_num = 10001

    # Format the new customer_id
    return f"{pattern}{next_num}"


@app.route('/debug/add-test-broker')
@login_required
def add_test_broker():
    user_id = session['user_id']
    supported_broker = SupportedBroker.query.first()

    broker = Broker(
        user_id=user_id,
        broker_name=supported_broker.name,
        user_id_broker="test_id",
        password="test_password",
        is_master=False,
        copy=True,
        copy_multiplier=1.0,
        subscription_status='Inactive',
        subscription_expiry=None,
        plan_id=None
    )

    try:
        db.session.add(broker)
        db.session.commit()
        flash("Test broker added successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "error")

    return redirect(url_for('dashboard'))


@app.route('/broker/view/<int:broker_id>')
@login_required
def view_broker(broker_id):
    user_id = session['user_id']
    broker = Broker.query.filter_by(id=broker_id, user_id=user_id).first_or_404()

    return render_template('client/broker_details.html', broker=broker)


@app.route('/broker/delete/<int:broker_id>', methods=['GET', 'POST'])
@login_required
def delete_broker(broker_id):
    user_id = session['user_id']
    broker = Broker.query.filter_by(id=broker_id, user_id=user_id).first_or_404()

    # Count other copy accounts for warning
    other_copy_accounts = 0
    if broker.is_master:
        other_copy_accounts = Broker.query.filter_by(
            user_id=user_id,
            copy=True,
            is_master=False
        ).count()

    if request.method == 'POST':
        try:
            db.session.delete(broker)
            db.session.commit()

            flash("Broker deleted successfully", "success")

            # Export brokers to CSV
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)

            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting broker: {str(e)}", "error")

    return render_template('client/delete_broker.html',
                           broker=broker,
                           other_copy_accounts=other_copy_accounts)


@app.route('/plans')
@login_required
def view_plans():
    user_id = session['user_id']

    # Get timeframe from URL parameter (default to monthly)
    timeframe = request.args.get('timeframe', 'monthly')

    # Get all active plans
    plans = Plan.query.filter_by(is_active=True).all()

    # Add current price and billing text for each plan based on timeframe
    for plan in plans:
        if timeframe == 'monthly':
            plan.current_price = plan.monthly_price
            plan.billing_text = 'per month'
        elif timeframe == 'quarterly':
            plan.current_price = plan.quarterly_price
            plan.billing_text = 'per quarter'
        elif timeframe == 'half_yearly':
            plan.current_price = plan.half_yearly_price
            plan.billing_text = 'per 6 months'
        elif timeframe == 'annually':
            plan.current_price = plan.annually_price
            plan.billing_text = 'per year'
        else:
            plan.current_price = plan.monthly_price
            plan.billing_text = 'per month'

    # Get user's current subscription
    current_subscription = get_current_subscription(user_id)

    return render_template(
        'client/plans.html',
        plans=plans,
        current_subscription=current_subscription,
        current_timeframe=timeframe
    )


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)

    # Handle form submission
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            # Validate current password
            if not user.check_password(current_password):
                flash("Current password is incorrect", "error")
            elif new_password != confirm_password:
                flash("New passwords do not match", "error")
            elif len(new_password) < 6:
                flash("Password must be at least 6 characters long", "error")
            else:
                # Update password
                user.set_password(new_password)
                db.session.commit()
                flash("Password updated successfully", "success")
                return redirect(url_for('profile'))

    return render_template('client/profile.html', user=user)


@app.route('/plan/select/<int:plan_id>')
@login_required
def select_plan(plan_id):
    user_id = session['user_id']
    plan = Plan.query.get_or_404(plan_id)

    # Get timeframe and price from URL parameters
    timeframe = request.args.get('timeframe', 'monthly')

    # Calculate price and duration based on timeframe
    if timeframe == 'monthly':
        current_price = plan.monthly_price
        duration = 30
    elif timeframe == 'quarterly':
        current_price = plan.quarterly_price
        duration = 90
    elif timeframe == 'half_yearly':
        current_price = plan.half_yearly_price
        duration = 180
    elif timeframe == 'annually':
        current_price = plan.annually_price
        duration = 365
    else:
        current_price = plan.monthly_price
        duration = 30

    # Get user's current subscription
    current_subscription = get_current_subscription(user_id)

    return render_template('client/select_plan.html',
                           plan=plan,
                           timeframe=timeframe,
                           current_price=current_price,
                           duration=duration,
                           current_subscription=current_subscription)


@app.route('/db/add_queued_subscription_column', methods=['GET'])
@admin_required
def add_queued_subscription_column():
    try:
        db.session.execute('ALTER TABLE subscription ADD COLUMN IF NOT EXISTS is_queued BOOLEAN DEFAULT FALSE;')
        db.session.commit()
        return "is_queued column added to subscription table successfully!"
    except Exception as e:
        db.session.rollback()
        return f"Error adding is_queued column: {str(e)}"


# @app.route('/plan/checkout/<int:plan_id>', methods=['GET', 'POST'])
# @login_required
# def checkout(plan_id):
#     user_id = session['user_id']
#     user = User.query.get_or_404(user_id)
#     plan = Plan.query.get_or_404(plan_id)
#
#     # Define payment method types
#     payment_method_types = ['Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'PayTM']
#
#     # Create Razorpay order
#     razorpay_order = None
#     try:
#         # Convert price to paise (Razorpay requires amount in smallest currency unit)
#         amount_in_paise = int(plan.price * 100)
#         order_data = {
#             'amount': amount_in_paise,
#             'currency': 'INR',
#             'receipt': f'plan_purchase_{plan.id}_{user.id}',
#             'notes': {
#                 'plan_id': plan.id,
#                 'user_id': user.id,
#                 'plan_name': plan.name
#             }
#         }
#
#         razorpay_order = razorpay_client.order.create(data=order_data)
#     except Exception as e:
#         flash(f"Error initializing payment: {str(e)}", "error")
#         razorpay_order = None
#
#     if request.method == 'POST':
#         # This section will handle the POST request after payment
#         # This is handled in the payment_callback route now
#         pass
#
#     return render_template(
#         'client/checkout.html',
#         plan=plan,
#         user=user,
#         payment_method_types=payment_method_types,
#         razorpay_order=razorpay_order,
#         razorpay_key_id=razorpay_key_id
#     )


@app.route('/admin')
@admin_required
def admin_dashboard():
    user_count = User.query.filter_by(is_admin=False).count()
    broker_count = Broker.query.count()
    active_subscriptions = Subscription.query.filter(
        Subscription.expiry_date > datetime.datetime.now()
    ).count()

    # Get revenue statistics
    subscriptions = Subscription.query.all()
    total_revenue = sum(sub.amount or 0 for sub in subscriptions)

    # Recent users
    recent_users = User.query.filter_by(is_admin=False).order_by(
        User.created_at.desc()
    ).limit(5).all()

    # Recent subscriptions
    recent_subscriptions = Subscription.query.order_by(
        Subscription.created_at.desc()
    ).limit(5).all()

    # Get scheduler settings for display
    scheduler_settings = SchedulerSettings.query.first()
    if not scheduler_settings:
        scheduler_settings = SchedulerSettings()
        db.session.add(scheduler_settings)
        db.session.commit()

    return render_template(
        'admin/dashboard.html',
        user_count=user_count,
        broker_count=broker_count,
        active_subscriptions=active_subscriptions,
        total_revenue=total_revenue,
        recent_users=recent_users,
        recent_subscriptions=recent_subscriptions,
        scheduler_settings=scheduler_settings
    )


@app.route('/admin/users')
@admin_required
def admin_users():
    # Get all regular users (non-admin)
    users = User.query.filter_by(is_admin=False).all()

    # Get subscription and broker data for each user
    user_details = []
    for user in users:
        # Get current subscription
        current_subscription = get_current_subscription(user.id)

        # Get broker connections
        broker_connections = Broker.query.filter_by(user_id=user.id).all()

        # Get the broker names as a comma-separated string
        broker_names = ", ".join(
            [broker.broker_name for broker in broker_connections]) if broker_connections else "None"

        # Determine account status
        if user.is_active:
            if current_subscription and current_subscription.expiry_date > datetime.datetime.now():
                account_status = "Active"
            else:
                account_status = "No Subscription"
        else:
            account_status = "Inactive"

        # Add to user details
        user_details.append({
            'user': user,
            'subscription': current_subscription,
            'broker_names': broker_names,
            'account_status': account_status,
            'broker_count': len(broker_connections)
        })

    return render_template('admin/users.html', user_details=user_details)


@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_view_user(user_id):
    user = User.query.get_or_404(user_id)

    # Get broker connections for this user
    broker_connections = Broker.query.filter_by(user_id=user.id).all()

    # Get current subscription
    current_subscription = get_current_subscription(user.id)

    # Get upcoming subscriptions
    upcoming_subscriptions = get_upcoming_subscriptions(user.id)

    queued_subscription = Subscription.query.filter_by(
        customer_id=user.customer_id,
        is_queued=True
    ).order_by(Subscription.start_date.asc()).first()

    return render_template(
        "admin/view_user.html",
        user=user,
        current_subscription=current_subscription,
        queued_subscription=queued_subscription,
        upcoming_subscriptions=upcoming_subscriptions,
        broker_connections=broker_connections
    )


@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    # Count user's brokers
    broker_count = Broker.query.filter_by(user_id=user.id).count()

    # Check if user has active subscription
    # Check if user has active subscription
    has_active_subscription = False
    subscription = get_current_subscription(user.id)
    if subscription:
        has_active_subscription = True

    # Get upcoming subscriptions with days calculation
    upcoming_subscriptions = get_upcoming_subscriptions(user.id)
    # Calculate days until start for each subscription
    for sub in upcoming_subscriptions:
        days_until = (sub.start_date.date() - datetime.datetime.utcnow().date()).days
        sub.days_until_start = days_until

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        customer_id = request.form.get('customer_id')
        is_admin = 'is_admin' in request.form
        is_active = 'is_active' in request.form

        # Check for duplicates
        username_exists = User.query.filter(User.username == username, User.id != user.id).first()
        email_exists = User.query.filter(User.email == email, User.id != user.id).first()

        if username_exists:
            flash("Username already exists", "error")
        elif email_exists:
            flash("Email already exists", "error")
        else:
            # Update password if provided
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            if password:
                if password != confirm_password:
                    flash("Passwords do not match", "error")
                    return render_template(
                        'admin/edit_user.html',
                        user=user,
                        broker_count=broker_count,
                        has_active_subscription=has_active_subscription,
                        upcoming_subscriptions=upcoming_subscriptions
                    )
                user.set_password(password)

            # Update other fields
            user.username = username
            user.email = email
            user.customer_id = customer_id
            user.is_admin = is_admin
            user.is_active = is_active

            try:
                db.session.commit()
                flash("User updated successfully", "success")
                return redirect(url_for('admin_view_user', user_id=user.id))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating user: {str(e)}", "error")

    return render_template(
        'admin/edit_user.html',
        user=user,
        broker_count=broker_count,
        has_active_subscription=has_active_subscription,
        upcoming_subscriptions=upcoming_subscriptions
    )


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash("Cannot delete admin user", "error")
        return redirect(url_for('admin_users'))

    try:
        # Delete all related data
        Broker.query.filter_by(user_id=user.id).delete()
        Subscription.query.filter_by(customer_id=user.customer_id).delete()

        db.session.delete(user)
        db.session.commit()

        flash("User and all associated data deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user: {str(e)}", "error")

    return redirect(url_for('admin_users'))


@app.route('/admin/plans')
@admin_required
def admin_plans():
    plans = Plan.query.all()
    return render_template('admin/plans.html', plans=plans)


@app.route('/admin/plan/create', methods=['GET', 'POST'])
@admin_required
def admin_create_plan():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        # duration = int(request.form.get('duration'))
        # price = float(request.form.get('price'))
        features = request.form.get('features')
        status = request.form.get('status', 'Active')
        has_copy_trading = 'has_copy_trading' in request.form
        max_brokers = int(request.form.get('max_brokers', 1))
        monthly_price = float(request.form.get('monthly_price')) or 0
        quarterly_price = float(request.form.get('quarterly_price')) or 0
        half_yearly_price = float(request.form.get('half_yearly_price')) or 0
        annually_price = float(request.form.get('annually_price')) or 0

        # Create plan
        plan = Plan(
            name=name,
            description=description,
            # duration=duration,
            monthly_price=monthly_price,
            quarterly_price=quarterly_price,
            half_yearly_price=half_yearly_price,
            annually_price=annually_price,
            # price=price,
            features=features,
            status=status,
            is_active=(status == 'Active'),
            has_copy_trading=has_copy_trading,
            max_brokers=max_brokers
        )

        db.session.add(plan)
        db.session.commit()

        flash("Plan created successfully", "success")
        return redirect(url_for('admin_plans'))

    return render_template('admin/create_plan.html')


@app.route('/admin/plan/<int:plan_id>')
@admin_required
def admin_view_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)

    # Get stats
    total_subscriptions = Subscription.query.filter_by(plan_id=plan.id).count()
    active_subscriptions = Subscription.query.filter_by(plan_id=plan.id).filter(
        Subscription.expiry_date > datetime.datetime.now()
    ).count()
    total_revenue = db.session.query(db.func.sum(Subscription.amount)).filter_by(plan_id=plan.id).scalar() or 0
    unique_users = db.session.query(Subscription.customer_id).filter_by(plan_id=plan.id).distinct().count()
    broker_count = Broker.query.filter_by(plan_id=plan.id).count()

    # Recent subscriptions
    recent_subscriptions = Subscription.query.filter_by(plan_id=plan.id).order_by(
        Subscription.created_at.desc()
    ).limit(5).all()

    return render_template(
        'admin/view_plan.html',
        plan=plan,
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        total_revenue=total_revenue,
        unique_users=unique_users,
        broker_count=broker_count,
        recent_subscriptions=recent_subscriptions
    )


@app.route('/admin/plan/edit/<int:plan_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)

    if request.method == 'POST':
        plan.name = request.form.get('name')
        plan.description = request.form.get('description')
        # plan.duration = int(request.form.get('duration'))
        # plan.price = float(request.form.get('price'))
        plan.features = request.form.get('features')
        plan.status = request.form.get('status', 'Active')
        plan.is_active = (plan.status == 'Active')
        plan.has_copy_trading = 'has_copy_trading' in request.form
        plan.max_brokers = int(request.form.get('max_brokers', 1))
        plan.monthly_price = float(request.form.get('monthly_price') or 0)
        plan.quarterly_price = float(request.form.get('quarterly_price') or 0)
        plan.half_yearly_price = float(request.form.get('half_yearly_price') or 0)
        plan.annually_price = float(request.form.get('annually_price') or 0)
        plan.max_sip_amount = int(request.form.get('max_sip_amount', 0))

        try:
            db.session.commit()
            flash("Plan updated successfully", "success")
            return redirect(url_for('admin_view_plan', plan_id=plan.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating plan: {str(e)}", "error")

    return render_template('admin/edit_plan.html', plan=plan)


@app.route('/admin/plan/delete/<int:plan_id>', methods=['POST'])
@admin_required
def admin_delete_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)

    # Check if plan is in use
    subscriptions = Subscription.query.filter_by(plan_id=plan_id).count()
    brokers = Broker.query.filter_by(plan_id=plan_id).count()

    if subscriptions > 0 or brokers > 0:
        flash("Cannot delete plan that is in use", "error")
        return redirect(url_for('admin_plans'))

    try:
        db.session.delete(plan)
        db.session.commit()
        flash("Plan deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting plan: {str(e)}", "error")

    return redirect(url_for('admin_plans'))


@app.route('/admin/plan/toggle-status/<int:plan_id>')
@admin_required
def admin_toggle_plan_status(plan_id):
    plan = Plan.query.get_or_404(plan_id)

    plan.is_active = not plan.is_active
    plan.status = 'Active' if plan.is_active else 'Inactive'

    try:
        db.session.commit()
        status = "activated" if plan.is_active else "deactivated"
        flash(f"Plan {status} successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error toggling plan status: {str(e)}", "error")

    return redirect(url_for('admin_view_plan', plan_id=plan.id))


@app.route('/admin/brokers')
@admin_required
def admin_brokers():
    # Get query parameters for filtering
    broker_name = request.args.get('broker')
    status = request.args.get('status')
    user_id = request.args.get('user_id')

    # Base query
    query = Broker.query

    # Apply filters
    if broker_name:
        query = query.filter_by(broker_name=broker_name)

    if status:
        query = query.filter_by(subscription_status=status)

    if user_id:
        query = query.filter_by(user_id=int(user_id))

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 20
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    brokers = pagination.items

    # Get supported brokers for filtering
    supported_brokers = SupportedBroker.query.all()

    # Get subscription statuses for filtering
    subscription_statuses = SubscriptionStatus.query.all()

    return render_template(
        'admin/brokers.html',
        brokers=brokers,
        supported_brokers=supported_brokers,
        subscription_statuses=subscription_statuses,
        pagination=pagination
    )


@app.route('/admin/broker/<int:broker_id>')
@admin_required
def admin_view_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)

    # Get all plans for the dropdown
    plans = Plan.query.filter_by(is_active=True).all()

    # Get all supported brokers
    supported_brokers = SupportedBroker.query.all()

    return render_template(
        'admin/view_broker.html',
        broker=broker,
        plans=plans,
        supported_brokers=supported_brokers
    )


@app.route('/admin/broker/edit/<int:broker_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)

    # Get all plans
    plans = Plan.query.all()

    # Get all supported brokers
    supported_brokers = SupportedBroker.query.all()

    # Get subscription statuses
    subscription_statuses = SubscriptionStatus.query.all()

    if request.method == 'POST':
        broker.user_id_broker = request.form.get('user_id_broker')

        # Update password if provided
        password = request.form.get('password')
        if password:
            broker.password = password

        # Update broker-specific fields
        if request.form.get('totp_secret'):
            broker.totp_secret = request.form.get('totp_secret')

        if request.form.get('api_key'):
            broker.api_key = request.form.get('api_key')

        if request.form.get('api_secret'):
            broker.api_secret = request.form.get('api_secret')

        if request.form.get('vendor_code'):
            broker.vendor_code = request.form.get('vendor_code')

        if request.form.get('imei'):
            broker.imei = request.form.get('imei')

        if request.form.get('access_token'):
            broker.access_token = request.form.get('access_token')

        # Update Algo Investment settings
        broker.is_master = 'is_master' in request.form
        broker.copy = 'copy' in request.form
        broker.copy_multiplier = float(request.form.get('copy_multiplier', 1.0))

        # Update subscription settings
        plan_id = request.form.get('plan_id')
        if plan_id:
            broker.plan_id = int(plan_id)
        else:
            broker.plan_id = None

        broker.subscription_status = request.form.get('subscription_status', 'Inactive')

        expiry_date = request.form.get('subscription_expiry')
        if expiry_date:
            broker.subscription_expiry = datetime.datetime.strptime(expiry_date, '%Y-%m-%d')

        broker.last_updated = datetime.datetime.utcnow()

        try:
            db.session.commit()

            # Export brokers to CSV
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)

            flash("Broker updated successfully", "success")
            return redirect(url_for('admin_view_broker', broker_id=broker.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating broker: {str(e)}", "error")

    return render_template(
        'admin/edit_broker.html',
        broker=broker,
        plans=plans,
        supported_brokers=supported_brokers,
        subscription_statuses=subscription_statuses
    )


@app.route('/admin/broker/delete/<int:broker_id>', methods=['POST'])
@admin_required
def admin_delete_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)

    try:
        db.session.delete(broker)
        db.session.commit()

        # Export brokers to CSV
        all_brokers = Broker.query.all()
        export_brokers_to_csv(all_brokers)

        flash("Broker deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting broker: {str(e)}", "error")

    return redirect(url_for('admin_brokers'))


@app.route('/admin/broker/assign-plan/<int:broker_id>', methods=['POST'])
@admin_required
def admin_assign_plan_to_broker(broker_id):
    broker = Broker.query.get_or_404(broker_id)

    plan_id = request.form.get('plan_id')
    if not plan_id:
        flash("Please select a plan", "error")
        return redirect(url_for('admin_view_broker', broker_id=broker.id))

    plan = Plan.query.get_or_404(plan_id)

    # Update broker with plan details
    broker.plan_id = plan.id
    broker.subscription_status = 'Active'

    # Calculate expiry date
    auto_calculate = 'auto_calculate_expiry' in request.form
    if auto_calculate:
        plan_name = plan.name.lower()
        if 'quarter' in plan_name:
            broker.subscription_expiry = datetime.datetime.now() + relativedelta(months=3)
        elif 'half' in plan_name:
            broker.subscription_expiry = datetime.datetime.now() + relativedelta(months=6)
        elif 'annual' in plan_name or 'year' in plan_name:
            broker.subscription_expiry = datetime.datetime.now() + relativedelta(years=1)
        else:
            broker.subscription_expiry = datetime.datetime.now() + relativedelta(months=1)  # Default: monthly

    broker.last_updated = datetime.datetime.utcnow()

    try:
        db.session.commit()

        # Export brokers to CSV
        all_brokers = Broker.query.all()
        export_brokers_to_csv(all_brokers)

        flash(f"Plan '{plan.name}' assigned to broker successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error assigning plan: {str(e)}", "error")

    return redirect(url_for('admin_view_broker', broker_id=broker.id))


@app.route('/admin/subscriptions')
@admin_required
def admin_subscriptions():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '')

    # Base query for all subscriptions
    query = Subscription.query.order_by(Subscription.id.desc())

    # Apply search filter if provided
    if search:
        try:
            # First get matching users
            matching_users = User.query.filter(
                db.or_(
                    User.username.ilike(f'%{search}%'),
                    User.email.ilike(f'%{search}%'),
                    User.customer_id.ilike(f'%{search}%')
                )
            ).all()

            # Get their customer IDs
            matching_customer_ids = [user.customer_id for user in matching_users]

            # Search subscriptions by user data, plan name, or payment ID
            if matching_customer_ids:
                query = query.filter(
                    db.or_(
                        Subscription.customer_id.in_(matching_customer_ids),
                        Subscription.plan_name.ilike(f'%{search}%'),
                        Subscription.payment_id.ilike(f'%{search}%')
                    )
                )
            else:
                # If no users found, only search by plan and payment ID
                query = query.filter(
                    db.or_(
                        Subscription.plan_name.ilike(f'%{search}%'),
                        Subscription.payment_id.ilike(f'%{search}%')
                    )
                )
        except Exception as e:
            # If search fails, only search by plan and payment ID
            query = query.filter(
                db.or_(
                    Subscription.plan_name.ilike(f'%{search}%'),
                    Subscription.payment_id.ilike(f'%{search}%')
                )
            )

    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    subscriptions = pagination.items

    # Attach user attribute to each subscription
    for subscription in subscriptions:
        try:
            user = User.query.filter_by(customer_id=subscription.customer_id).first()
            subscription.user = user if user else type('obj', (object,), {'username': 'Unknown User'})()
        except:
            subscription.user = type('obj', (object,), {'username': 'Unknown User'})()

    # Simple data for template
    active_subs = []
    queued_subs = []
    statuses = []
    plans = []

    try:
        statuses = SubscriptionStatus.query.all()
    except:
        pass

    try:
        plans = Plan.query.filter_by(is_active=True).all()
    except:
        pass

    return render_template(
        'admin/subscriptions.html',
        subscriptions=subscriptions,
        active_subs=active_subs,
        queued_subs=queued_subs,
        pagination=pagination,
        search=search,
        statuses=statuses,
        plans=plans
    )


@app.route('/admin/subscription/<int:subscription_id>')
@admin_required
def admin_view_subscription(subscription_id):
    subscription = Subscription.query.get_or_404(subscription_id)
    user = User.query.filter_by(customer_id=subscription.customer_id).first()

    all_subscriptions = Subscription.query.filter_by(
        customer_id=user.customer_id
    ).order_by(Subscription.id.desc()).all()

    associated_brokers = Broker.query.filter_by(
        user_id=user.id,
        plan_id=subscription.plan_id
    ).all()

    available_plans = Plan.query.filter_by(is_active=True).all()

    return render_template(
        'admin/view_subscription.html',
        subscription=subscription,
        user=user,
        all_subscriptions=all_subscriptions,
        associated_brokers=associated_brokers,
        available_plans=available_plans
    )


@app.route('/admin/subscription/create', methods=['GET', 'POST'])
@admin_required
def admin_create_subscription():
    users = User.query.filter_by(is_admin=False, is_active=True).all()
    plans_raw = Plan.query.filter_by(is_active=True).all()

    # Serialize plans for JS
    plans_serialized = [
        {
            "id": p.id,
            "name": p.name,
            "monthly_price": p.monthly_price,
            "quarterly_price": p.quarterly_price,
            "half_yearly_price": p.half_yearly_price,
            "annually_price": p.annually_price
        }
        for p in plans_raw
    ]

    payment_method_types = ['Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'PayTM']
    subscription_statuses = SubscriptionStatus.query.all()
    preselected_user_id = request.args.get('user_id', type=int)
    preselected_user = User.query.get(preselected_user_id) if preselected_user_id else None

    if request.method == 'POST':
        user_id_str = request.form.get('user_id')
        plan_id_str = request.form.get('plan_id')
        billing_cycle = request.form.get('billing_cycle')
        valid_cycles = ['monthly', 'quarterly', 'half_yearly', 'annually']
        if billing_cycle not in valid_cycles:
            flash("Invalid or missing billing cycle", "error")
            return redirect(url_for('admin_create_subscription'))

        payment_method_type = request.form.get('payment_method')
        payment_status = request.form.get('payment_status')

        if not all([user_id_str, plan_id_str, billing_cycle, payment_method_type, payment_status]):
            flash("All fields are required", "error")
            return render_template('admin/create_subscription.html',
                                   users=users,
                                   plans=plans_raw,
                                   plans_serialized=plans_serialized,
                                   payment_method_types=payment_method_types,
                                   subscription_statuses=subscription_statuses,
                                   preselected_user_id=preselected_user_id,
                                   preselected_user=preselected_user)

        try:
            user_id = int(user_id_str)
            plan_id = int(plan_id_str)
        except ValueError:
            flash("Invalid input values", "error")
            return render_template('admin/create_subscription.html',
                                   users=users,
                                   plans=plans_raw,
                                   plans_serialized=plans_serialized,
                                   payment_method_types=payment_method_types,
                                   subscription_statuses=subscription_statuses,
                                   preselected_user_id=preselected_user_id,
                                   preselected_user=preselected_user)

        user = User.query.get_or_404(user_id)
        plan = Plan.query.get_or_404(plan_id)

        try:
            start_date = datetime.datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        except ValueError:
            flash("Invalid start date format", "error")
            return render_template('admin/create_subscription.html',
                                   users=users,
                                   plans=plans_raw,
                                   plans_serialized=plans_serialized,
                                   payment_method_types=payment_method_types,
                                   subscription_statuses=subscription_statuses,
                                   preselected_user_id=preselected_user_id,
                                   preselected_user=preselected_user)

        from dateutil.relativedelta import relativedelta
        current_sub = get_current_subscription(user.id)

        if current_sub:
            start_date = current_sub.expiry_date
            is_queued = True
        else:
            is_queued = False

        # Determine expiry and amount from billing cycle
        if billing_cycle == 'monthly':
            expiry_date = start_date + relativedelta(months=1)
            amount = plan.monthly_price
        elif billing_cycle == 'quarterly':
            expiry_date = start_date + relativedelta(months=3)
            amount = plan.quarterly_price
        elif billing_cycle == 'half_yearly':
            expiry_date = start_date + relativedelta(months=6)
            amount = plan.half_yearly_price
        elif billing_cycle == 'annually':
            expiry_date = start_date + relativedelta(years=1)
            amount = plan.annually_price
        else:
            flash("Invalid billing cycle selected.", "error")
            return redirect(url_for('admin_create_subscription'))

        payment_id = request.form.get('payment_id') or f"ADMIN-{uuid.uuid4().hex[:8]}"

        subscription = Subscription(
            customer_id=user.customer_id,
            plan_id=plan_id,
            plan_name=plan.name,
            start_date=start_date,
            expiry_date=expiry_date,
            billing_cycle=billing_cycle,
            amount=amount,
            payment_status=payment_status,
            payment_method=payment_method_type,
            payment_id=payment_id,
            is_queued=is_queued
        )

        try:
            db.session.add(subscription)

            if 'update_brokers' in request.form:
                broker_accounts = Broker.query.filter_by(user_id=user_id).all()
                for broker in broker_accounts:
                    broker.subscription_status = payment_status
                    broker.subscription_expiry = expiry_date
                    broker.plan_id = plan_id
                    if plan.has_copy_trading:
                        broker.copy = True
                        if not Broker.query.filter_by(user_id=user_id, is_master=True).first() and broker == \
                                broker_accounts[0]:
                            broker.is_master = True

            # Optional: record payment
            payment = PaymentMethod(
                name=f"Payment for {plan.name}",
                description=f"Payment for {user.username}'s {plan.name} subscription",
                payment_method=payment_method_type,
                payment_id=payment_id,
                amount_paid=amount,
                customer_id=user.customer_id,
                payment_status=payment_status,
                is_active=True,
                created_at=datetime.datetime.utcnow(),
                payment_data=datetime.datetime.utcnow()
            )
            db.session.add(payment)

            db.session.commit()
            export_brokers_to_csv(Broker.query.all())

            flash(f"Subscription created successfully for {user.username}", "success")
            return redirect(url_for('admin_subscriptions'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating subscription: {str(e)}", "error")

    return render_template("admin/create_subscription.html",
                           users=users,
                           plans=plans_raw,
                           plans_serialized=plans_serialized,
                           payment_method_types=payment_method_types,
                           subscription_statuses=subscription_statuses,
                           preselected_user_id=preselected_user_id,
                           preselected_user=preselected_user)


@app.route('/admin/subscription/edit/<int:subscription_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_subscription(subscription_id):
    subscription = Subscription.query.get_or_404(subscription_id)

    # Get the related user
    user = User.query.filter_by(customer_id=subscription.customer_id).first()

    plans = Plan.query.all()
    # Define payment method types instead of querying the table
    payment_method_types = ['Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'PayTM']
    subscription_statuses = SubscriptionStatus.query.all()

    if request.method == 'POST':
        plan_id = int(request.form.get('plan_id'))
        payment_method_type = request.form.get('payment_method')  # Now getting the method type directly
        payment_status = request.form.get('payment_status')

        # Get plan
        plan = Plan.query.get_or_404(plan_id)

        # Parse dates
        start_date = datetime.datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        expiry_date = datetime.datetime.strptime(request.form.get('expiry_date'), '%Y-%m-%d')

        # Get amount and payment ID
        amount = float(request.form.get('amount'))
        payment_id = request.form.get('payment_id')

        # Update subscription
        subscription.plan_id = plan_id
        subscription.plan_name = plan.name
        subscription.start_date = start_date
        subscription.expiry_date = expiry_date
        subscription.payment_status = payment_status
        subscription.payment_method = payment_method_type  # Direct use of method type
        subscription.payment_id = payment_id
        subscription.amount = amount

        try:
            # Update broker accounts if checkbox is checked
            if 'update_brokers' in request.form:
                user = User.query.filter_by(customer_id=subscription.customer_id).first()
                if not user:
                    flash("User not found for given customer_id", "error")
                    return redirect(url_for('admin_subscriptions'))

                broker_accounts = Broker.query.filter_by(user_id=user.id).all()

                for broker in broker_accounts:
                    broker.subscription_status = payment_status
                    broker.subscription_expiry = expiry_date
                    broker.plan_id = plan_id

            # Also update the payment method record
            if payment_id:
                # Find or create a payment record for this subscription
                existing_payment = PaymentMethod.query.filter_by(payment_id=payment_id).first()

                if existing_payment:
                    # Update existing payment record
                    existing_payment.amount_paid = amount
                    existing_payment.payment_status = payment_status
                    existing_payment.is_active = (payment_status == 'Successful')
                    # Since payment_data is a timestamp, set it to current time when updated
                    existing_payment.payment_data = datetime.datetime.utcnow()
                    existing_payment.payment_method = payment_method_type  # Direct use of method type
                    existing_payment.customer_id = user.customer_id
                else:
                    # Create new payment record
                    new_payment = PaymentMethod(
                        name=f"Payment for {subscription.plan_name}",
                        description=f"Payment for subscription #{subscription.id}",
                        is_active=(payment_status == 'Successful'),
                        created_at=datetime.datetime.utcnow(),
                        payment_data=datetime.datetime.utcnow(),
                        payment_method=payment_method_type,  # Direct use of method type
                        payment_id=payment_id,
                        amount_paid=amount,
                        customer_id=user.customer_id,
                        payment_status=payment_status
                    )
                    db.session.add(new_payment)

            db.session.commit()

            # Success notification
            flash("Subscription updated successfully", "success")
            return redirect(url_for('admin_view_subscription', subscription_id=subscription.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating subscription: {str(e)}", "error")
            print(f"Error updating subscription: {str(e)}")  # Add for debugging

    return render_template(
        'admin/edit_subscription.html',
        subscription=subscription,
        user=user,
        plans=plans,
        payment_method_types=payment_method_types,  # Pass method types instead of payment_methods
        subscription_statuses=subscription_statuses
    )


@app.route('/admin/subscription/delete/<int:subscription_id>', methods=['POST'])
@admin_required
def admin_delete_subscription(subscription_id):
    subscription = Subscription.query.get_or_404(subscription_id)

    try:
        db.session.delete(subscription)
        db.session.commit()
        flash("Subscription deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting subscription: {str(e)}", "error")

    return redirect(url_for('admin_subscriptions'))


@app.route('/admin/subscription/queue/<int:subscription_id>', methods=['POST'])
def queue_subscription(subscription_id):
    current_sub = Subscription.query.get_or_404(subscription_id)
    user_id = current_sub.user_id
    selected_plan_id = request.form.get('plan_id')

    # Check if a queued subscription already exists
    existing_queued = Subscription.query.filter_by(user_id=user_id, is_queued=True).first()
    if existing_queued:
        flash("A queued subscription already exists for this user.", "warning")
        return redirect(url_for('admin_subscriptions'))

    # Estimate new plan start and end dates based on current subscription
    queued_start = current_sub.end_date
    queued_end = queued_start + timedelta(days=30)  # Adjust as per plan's duration

    queued_sub = Subscription(
        user_id=user_id,
        plan_id=selected_plan_id,
        start_date=queued_start,
        end_date=queued_end,
        is_queued=True
    )
    db.session.add(queued_sub)
    db.session.commit()

    flash("Queued subscription created successfully.", "success")
    return redirect(url_for('admin_subscriptions'))


@app.route('/admin/subscription/renew/<int:subscription_id>', methods=['POST'])
@admin_required
def admin_renew_subscription(subscription_id):
    selected_plan_id = request.form.get('plan_id')
    plan = Plan.query.get_or_404(selected_plan_id)
    billing_cycle = request.form.get('billing_cycle')

    old_sub = Subscription.query.get_or_404(subscription_id)
    user = User.query.filter_by(customer_id=old_sub.customer_id).first()

    now = datetime.datetime.now()
    current = get_current_subscription(user.id)

    if current:
        start_date = current.expiry_date
        is_queued = True
    else:
        start_date = now
        is_queued = False

    from dateutil.relativedelta import relativedelta

    if billing_cycle == 'monthly':
        expiry_date = start_date + relativedelta(months=1)
        amount = plan.monthly_price
    elif billing_cycle == 'quarterly':
        expiry_date = start_date + relativedelta(months=3)
        amount = plan.quarterly_price
    elif billing_cycle == 'half_yearly':
        expiry_date = start_date + relativedelta(months=6)
        amount = plan.half_yearly_price
    elif billing_cycle == 'annually':
        expiry_date = start_date + relativedelta(years=1)
        amount = plan.annually_price
    else:
        flash("Invalid billing cycle selected.", "error")
        return redirect(url_for('admin_view_subscription', subscription_id=subscription_id))

    new_sub = Subscription(
        customer_id=user.customer_id,
        plan_id=plan.id,
        plan_name=plan.name,
        start_date=start_date,
        expiry_date=expiry_date,
        billing_cycle=billing_cycle,
        amount=amount,
        payment_status='Paid',
        payment_method='Admin Manual',
        payment_id=f"RENEW-{uuid.uuid4().hex[:8]}",
        is_queued=is_queued,
        created_at=now
    )

    try:
        db.session.add(new_sub)
        db.session.commit()
        flash("Subscription renewed successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error during renewal: {str(e)}", "error")

    return redirect(url_for('admin_view_subscription', subscription_id=new_sub.id))


@app.route('/admin/subscription/cancel/<int:subscription_id>', methods=['POST'])
@admin_required
def admin_cancel_subscription(subscription_id):
    subscription = Subscription.query.get_or_404(subscription_id)

    subscription.payment_status = 'Cancelled'

    try:
        # Fetch actual User based on customer_id
        user = User.query.filter_by(customer_id=subscription.customer_id).first()

        # Update broker accounts if user is valid
        broker_accounts = []
        if user:
            broker_accounts = Broker.query.filter_by(
                user_id=user.id,
                plan_id=subscription.plan_id
            ).all()
            for broker in broker_accounts:
                broker.subscription_status = 'Cancelled'

        db.session.commit()

        # Export updated broker data
        all_brokers = Broker.query.all()
        export_brokers_to_csv(all_brokers)

        flash("Subscription cancelled successfully", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error cancelling subscription: {str(e)}", "error")

    return redirect(url_for('admin_view_subscription', subscription_id=subscription.id))


@app.route('/admin/supported-brokers')
@admin_required
def admin_supported_brokers():
    supported_brokers = SupportedBroker.query.all()
    return render_template('admin/supported_brokers.html', supported_brokers=supported_brokers)


@app.route('/admin/supported-broker/create', methods=['GET', 'POST'])
@admin_required
def admin_create_supported_broker():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        is_active = 'is_active' in request.form

        # Required fields
        requires_totp = 'requires_totp' in request.form
        requires_api_key = 'requires_api_key' in request.form
        requires_api_secret = 'requires_api_secret' in request.form
        requires_vendor_code = 'requires_vendor_code' in request.form
        requires_imei = 'requires_imei' in request.form
        requires_access_token = 'requires_access_token' in request.form

        # Check if broker already exists
        if SupportedBroker.query.filter_by(name=name).first():
            flash(f"Broker with name '{name}' already exists", "error")
            return render_template('admin/create_supported_broker.html')

        # Create new supported broker
        broker = SupportedBroker(
            name=name,
            description=description,
            is_active=is_active,
            requires_totp=requires_totp,
            requires_api_key=requires_api_key,
            requires_api_secret=requires_api_secret,
            requires_vendor_code=requires_vendor_code,
            requires_imei=requires_imei,
            requires_access_token=requires_access_token
        )

        try:
            db.session.add(broker)
            db.session.commit()

            flash(f"Broker '{name}' added successfully", "success")
            return redirect(url_for('admin_supported_brokers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding broker: {str(e)}", "error")

    return render_template('admin/create_supported_broker.html')


@app.route('/admin/supported-broker/edit/<int:broker_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_supported_broker(broker_id):
    broker = SupportedBroker.query.get_or_404(broker_id)

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        is_active = 'is_active' in request.form

        # Required fields
        requires_totp = 'requires_totp' in request.form
        requires_api_key = 'requires_api_key' in request.form
        requires_api_secret = 'requires_api_secret' in request.form
        requires_vendor_code = 'requires_vendor_code' in request.form
        requires_imei = 'requires_imei' in request.form
        requires_access_token = 'requires_access_token' in request.form

        # Check if name already exists for a different broker
        existing_broker = SupportedBroker.query.filter(SupportedBroker.name == name,
                                                       SupportedBroker.id != broker_id).first()
        if existing_broker:
            flash(f"Broker with name '{name}' already exists", "error")
            return render_template('admin/edit_supported_broker.html', broker=broker)

        # Update broker
        broker.name = name
        broker.description = description
        broker.is_active = is_active
        broker.requires_totp = requires_totp
        broker.requires_api_key = requires_api_key
        broker.requires_api_secret = requires_api_secret
        broker.requires_vendor_code = requires_vendor_code
        broker.requires_imei = requires_imei
        broker.requires_access_token = requires_access_token

        try:
            db.session.commit()
            flash(f"Broker '{name}' updated successfully", "success")
            return redirect(url_for('admin_supported_brokers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating broker: {str(e)}", "error")

    return render_template('admin/edit_supported_broker.html', broker=broker)


@app.route('/admin/supported-broker/delete/<int:broker_id>', methods=['POST'])
@admin_required
def admin_delete_supported_broker(broker_id):
    broker = SupportedBroker.query.get_or_404(broker_id)

    # Check if the broker is in use
    if Broker.query.filter_by(broker_name=broker.name).first():
        flash(f"Cannot delete broker '{broker.name}' as it's in use", "error")
        return redirect(url_for('admin_supported_brokers'))

    try:
        db.session.delete(broker)
        db.session.commit()
        flash(f"Broker '{broker.name}' deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting broker: {str(e)}", "error")

    return redirect(url_for('admin_supported_brokers'))


@app.route('/admin/payment-methods')
@admin_required
def admin_payment_methods():
    payment_methods = PaymentMethod.query.all()
    return render_template('admin/payment_methods.html', payment_methods=payment_methods)


@app.route('/admin/payment-method/create', methods=['GET', 'POST'])
@admin_required
def admin_create_payment_method():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        is_active = 'is_active' in request.form

        # Check if payment method already exists
        if PaymentMethod.query.filter_by(name=name).first():
            flash(f"Payment method with name '{name}' already exists", "error")
            return render_template('admin/create_payment_method.html')

        # Create new payment method
        payment_method = PaymentMethod(
            name=name,
            description=description,
            is_active=is_active
        )

        try:
            db.session.add(payment_method)
            db.session.commit()
            flash(f"Payment method '{name}' added successfully", "success")
            return redirect(url_for('admin_payment_methods'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding payment method: {str(e)}", "error")

    return render_template('admin/create_payment_method.html')


@app.route('/admin/payment-method/edit/<int:method_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_payment_method(method_id):
    method = PaymentMethod.query.get_or_404(method_id)

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        is_active = 'is_active' in request.form

        # Check if name already exists for a different method
        existing_method = PaymentMethod.query.filter(PaymentMethod.name == name, PaymentMethod.id != method_id).first()
        if existing_method:
            flash(f"Payment method with name '{name}' already exists", "error")
            return render_template('admin/edit_payment_method.html', method=method)

        # Update method
        method.name = name
        method.description = description
        method.is_active = is_active

        try:
            db.session.commit()
            flash(f"Payment method '{name}' updated successfully", "success")
            return redirect(url_for('admin_payment_methods'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating payment method: {str(e)}", "error")

    return render_template('admin/edit_payment_method.html', method=method)


@app.route('/admin/payment-method/delete/<int:method_id>', methods=['POST'])
@admin_required
def admin_delete_payment_method(method_id):
    method = PaymentMethod.query.get_or_404(method_id)

    # Check if the method is in use
    if Subscription.query.filter_by(payment_method=method.name).first():
        flash(f"Cannot delete payment method '{method.name}' as it's in use", "error")
        return redirect(url_for('admin_payment_methods'))

    try:
        db.session.delete(method)
        db.session.commit()
        flash(f"Payment method '{method.name}' deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting payment method: {str(e)}", "error")

    return redirect(url_for('admin_payment_methods'))


@app.route('/admin/subscription-statuses')
@admin_required
def admin_subscription_statuses():
    statuses = SubscriptionStatus.query.all()
    return render_template('admin/subscription_statuses.html', statuses=statuses)


@app.route('/admin/subscription-status/create', methods=['GET', 'POST'])
@admin_required
def admin_create_subscription_status():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')

        # Check if status already exists
        if SubscriptionStatus.query.filter_by(name=name).first():
            flash(f"Subscription status with name '{name}' already exists", "error")
            return render_template('admin/create_subscription_status.html')

        # Create new status
        status = SubscriptionStatus(
            name=name,
            description=description
        )

        try:
            db.session.add(status)
            db.session.commit()
            flash(f"Subscription status '{name}' added successfully", "success")
            return redirect(url_for('admin_subscription_statuses'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding subscription status: {str(e)}", "error")

    return render_template('admin/create_subscription_status.html')


@app.route('/admin/subscription-status/edit/<int:status_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_subscription_status(status_id):
    status = SubscriptionStatus.query.get_or_404(status_id)

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')

        # Check if name already exists for a different status
        existing_status = SubscriptionStatus.query.filter(SubscriptionStatus.name == name,
                                                          SubscriptionStatus.id != status_id).first()
        if existing_status:
            flash(f"Subscription status with name '{name}' already exists", "error")
            return render_template('admin/edit_subscription_status.html', status=status)

        # Update status
        status.name = name
        status.description = description

        try:
            db.session.commit()
            flash(f"Subscription status '{name}' updated successfully", "success")
            return redirect(url_for('admin_subscription_statuses'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating subscription status: {str(e)}", "error")

    return render_template('admin/edit_subscription_status.html', status=status)


@app.route('/admin/subscription-status/delete/<int:status_id>', methods=['POST'])
@admin_required
def admin_delete_subscription_status(status_id):
    status = SubscriptionStatus.query.get_or_404(status_id)

    # Check if the status is in use
    if Subscription.query.filter_by(payment_status=status.name).first() or Broker.query.filter_by(
            subscription_status=status.name).first():
        flash(f"Cannot delete subscription status '{status.name}' as it's in use", "error")
        return redirect(url_for('admin_subscription_statuses'))

    try:
        db.session.delete(status)
        db.session.commit()
        flash(f"Subscription status '{status.name}' deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting subscription status: {str(e)}", "error")

    return redirect(url_for('admin_subscription_statuses'))


@app.route('/admin/activate_queued_subscriptions', methods=['GET'])
@admin_required
def admin_activate_queued_subscriptions():
    activate_queued_subscriptions()
    flash("Queued subscriptions checked and activated if necessary", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/exports')
@admin_required
def admin_exports():
    # Get list of exported files
    data_dir = 'data'
    export_files = []

    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.endswith('.csv'):
                file_path = os.path.join(data_dir, file)
                file_stats = os.stat(file_path)

                # Determine file type
                file_type = "Unknown"
                if 'broker' in file:
                    file_type = "Brokers"
                elif 'user' in file:
                    file_type = "Users"
                elif 'subscription' in file:
                    file_type = "Subscriptions"

                export_files.append({
                    'name': file,
                    'type': file_type,
                    'size': f"{file_stats.st_size / 1024:.1f} KB",
                    'created_at': datetime.datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })

    # Sort files by created time, newest first
    export_files.sort(key=lambda x: x['created_at'], reverse=True)

    return render_template('admin/exports.html', export_files=export_files)


@app.route('/admin/exports/brokers', methods=['POST'])
@admin_required
def admin_export_brokers():
    # Generate export filename with timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = f"data/brokers_export_{timestamp}.csv"

    # Get all brokers
    all_brokers = Broker.query.all()

    try:
        # Export to CSV
        csv_path = export_brokers_to_csv(all_brokers, export_path)
        flash(f"Brokers exported successfully to {csv_path}", "success")
    except Exception as e:
        flash(f"Error exporting brokers: {str(e)}", "error")

    return redirect(url_for('admin_exports'))


@app.route('/admin/exports/users', methods=['POST'])
@admin_required
def admin_export_users():
    # Generate export filename with timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = f"data/users_export_{timestamp}.csv"

    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)

    try:
        # Get all users
        users = User.query.all()

        # Create data for export
        data = []
        for user in users:
            last_login = user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else ''

            data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin,
                'is_active': user.is_active,
                'customer_id': user.customer_id,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'last_login': last_login
            })

        # Create DataFrame and export to CSV
        df = pd.DataFrame(data)
        df.to_csv(export_path, index=False)

        flash(f"Users exported successfully to {export_path}", "success")
    except Exception as e:
        flash(f"Error exporting users: {str(e)}", "error")

    return redirect(url_for('admin_exports'))


@app.route('/admin/exports/subscriptions', methods=['POST'])
@admin_required
def admin_export_subscriptions():
    # Generate export filename with timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = f"data/subscriptions_export_{timestamp}.csv"

    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)

    try:
        # Get all subscriptions
        subscriptions = Subscription.query.all()

        # Create data for export
        data = []
        for sub in subscriptions:
            data.append({
                'id': sub.id,
                'user_id': sub.user_id,
                'username': sub.user.username if sub.user else '',
                'plan_id': sub.plan_id,
                'plan_name': sub.plan_name,
                'start_date': sub.start_date.strftime('%Y-%m-%d'),
                'expiry_date': sub.expiry_date.strftime('%Y-%m-%d'),
                'payment_status': sub.payment_status,
                'payment_method': sub.payment_method,
                'payment_id': sub.payment_id,
                'amount': sub.amount,
                'created_at': sub.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        # Create DataFrame and export to CSV
        df = pd.DataFrame(data)
        df.to_csv(export_path, index=False)

        flash(f"Subscriptions exported successfully to {export_path}", "success")
    except Exception as e:
        flash(f"Error exporting subscriptions: {str(e)}", "error")

    return redirect(url_for('admin_exports'))


@app.route('/admin/user/reset_disclaimer/<int:user_id>', methods=['POST'])
@admin_required
def admin_reset_user_disclaimer(user_id):
    user = User.query.get_or_404(user_id)
    user.disclaimer_accepted = False
    db.session.commit()
    flash(f"Disclaimer acceptance reset for {user.username}", "success")
    return redirect(url_for('admin_view_user', user_id=user.id))


@app.route('/admin/exports/download/<file_name>')
@admin_required
def admin_download_export(file_name):
    # Validate filename to prevent directory traversal
    if '..' in file_name or '/' in file_name:
        flash("Invalid filename", "error")
        return redirect(url_for('admin_exports'))

    file_path = os.path.join('data', file_name)

    if not os.path.exists(file_path):
        flash("File not found", "error")
        return redirect(url_for('admin_exports'))

    # Send file
    return send_file(file_path, as_attachment=True)


@app.route('/admin/exports/delete/<file_name>', methods=['POST'])
@admin_required
def admin_delete_export(file_name):
    # Validate filename to prevent directory traversal
    if '..' in file_name or '/' in file_name:
        flash("Invalid filename", "error")
        return redirect(url_for('admin_exports'))

    file_path = os.path.join('data', file_name)

    if not os.path.exists(file_path):
        flash("File not found", "error")
        return redirect(url_for('admin_exports'))

    try:
        os.remove(file_path)
        flash(f"File {file_name} deleted successfully", "success")
    except Exception as e:
        flash(f"Error deleting file: {str(e)}", "error")

    return redirect(url_for('admin_exports'))


# ------------------------------------------------------------------------------
# Admin Scheduler Management Routes
# ------------------------------------------------------------------------------

@app.route('/admin/scheduler')
@admin_required
def admin_scheduler_management():
    """Admin page for scheduler management"""
    try:
        # Get or create scheduler settings
        settings = SchedulerSettings.query.first()
        if not settings:
            settings = SchedulerSettings()
            db.session.add(settings)
            db.session.commit()

        # Get scheduler status for template
        from datetime import datetime

        schedule_status = {
            'session_test_time': settings.session_test_time,
            'execution_time': settings.execution_time,
            'failed_clients': 0,  # Will be updated from actual checks
            'driver_issues': False,  # Will be updated from actual checks
            'is_running': True
        }

        return render_template('admin/scheduler_management.html',
                               current_settings=settings,
                               schedule_status=schedule_status,
                               current_time=datetime.now().strftime('%d %B %Y, %I:%M %p'))
    except Exception as e:
        flash(f'Error loading scheduler management: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/scheduler/update', methods=['POST'])
@admin_required
def admin_update_scheduler_settings():
    """Update scheduler settings"""
    try:
        settings = SchedulerSettings.query.first()
        if not settings:
            settings = SchedulerSettings()
            db.session.add(settings)

        # Update settings from form
        settings.session_test_time = request.form.get('session_test_time', '10:30')
        settings.execution_time = request.form.get('execution_time', '15:10')
        settings.driver_check_enabled = 'driver_check_enabled' in request.form
        settings.password_check_enabled = 'password_check_enabled' in request.form
        settings.email_notifications_enabled = 'email_notifications_enabled' in request.form
        settings.max_failed_clients_threshold = int(request.form.get('max_failed_clients_threshold', 3))

        db.session.commit()
        flash('Scheduler settings updated successfully!', 'success')

    except Exception as e:
        flash(f'Error updating scheduler settings: {str(e)}', 'error')
        db.session.rollback()

    return redirect(url_for('admin_scheduler_management'))


@app.route('/admin/broker-passwords')
@admin_required
def admin_broker_passwords():
    """Admin page for viewing broker passwords"""
    try:
        # Get all brokers with their user information (using the ORM relationships)
        brokers = Broker.query.join(User).all()

        return render_template('admin/broker_passwords.html', brokers=brokers)

    except Exception as e:
        flash(f'Error loading broker passwords: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))


# Manual Trigger Routes
@app.route('/admin/scheduler/trigger-health-check', methods=['POST'])
@admin_required
def admin_trigger_health_check():
    """Manual trigger for health check"""
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        data = request.get_json(silent=True) or {}
        headless = data.get('headless')
        if headless is None:
            arg = request.args.get('headless')
            if arg is not None:
                headless = arg.lower() in ('1','true','yes')
            else:
                headless = True
        scheduler = EnhancedExecutionScheduler()
        result = scheduler.manual_health_check(headless=headless)
        return jsonify({
            'success': result['success'],
            'message': result['message'],
            'details': result.get('details', {})
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error triggering health check: {str(e)}'
        }), 500


@app.route('/admin/scheduler/trigger-execution', methods=['POST'])
@admin_required
def admin_trigger_execution():
    """Manual trigger for strategy execution (directly runs strategy_runner/etf_automated.py)"""
    try:
        import subprocess, sys, os
        data = request.get_json(silent=True) or {}
        headless = data.get('headless')
        if headless is None:
            arg = request.args.get('headless')
            headless = arg.lower() in ('1','true','yes') if arg is not None else True
        mode = 'headless' if headless else 'browser'
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'strategy_runner', 'etf_automated.py')
        env = os.environ.copy()
        env['HEADLESS'] = '1' if headless else '0'
        env['RUN_MODE'] = mode
        cmd = [sys.executable, '-u', script_path]
        # Ensure DB run logs so we can summarize in email
        env['ENABLE_RUN_LOGS'] = env.get('ENABLE_RUN_LOGS', '1')
        start_ts = datetime.datetime.utcnow().isoformat()
        # Write child stdout/stderr to a rolling log so you can verify it ran
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"manual-exec-{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.log")
        log_file = open(log_path, 'ab')
        proc = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(__file__)), env=env, stdout=log_file, stderr=subprocess.STDOUT)

        def _notify_on_finish(p, mode, start_ts, log_path, log_file):
            try:
                rc = p.wait()
                end_ts = datetime.datetime.utcnow()
                start_dt = datetime.datetime.fromisoformat(start_ts)
                duration = (end_ts - start_dt).total_seconds()
                from email_notifications import send_execution_email, send_admin_alert_email
                from datetime import timezone
                # Gather metrics from DB (if available)
                metrics = {'total_clients': None, 'passed': None, 'failed': None, 'total_orders': None, 'ok_orders': None, 'fail_orders': None}
                success = (rc == 0)
                try:
                    with app.app_context():
                        run = ExecutionRun.query.order_by(ExecutionRun.id.desc()).first()
                        if run and run.ended_at:
                            metrics.update({
                                'total_clients': run.total_clients,
                                'passed': run.passed,
                                'failed': run.failed,
                                'total_orders': run.total_orders,
                                'ok_orders': run.ok_orders,
                                'fail_orders': run.fail_orders,
                            })
                            if isinstance(run.status, str) and run.status.lower() == 'failed':
                                success = False
                except Exception:
                    pass

                # Find latest generated files after start time
                base_dir = os.path.dirname(os.path.abspath(__file__))
                daily_dir = os.path.join(base_dir, 'daily_orders')
                files = {'zip_file': None, 'etf_csv': None, 'user_csv': None, 'todays_etf': None}
                try:
                    def latest_with_prefix(folder, prefix, ext):
                        try:
                            candidates = [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(ext)]
                            if not candidates:
                                return None
                            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                            return candidates[0]
                        except Exception:
                            return None
                    if os.path.isdir(daily_dir):
                        files['zip_file'] = latest_with_prefix(daily_dir, 'smartetf_orders_', '.zip')
                        files['etf_csv'] = latest_with_prefix(daily_dir, 'etf_orders_', '.csv')
                        files['user_csv'] = latest_with_prefix(daily_dir, 'user_tracking_', '.csv')
                    todays_etf_path = os.path.join(base_dir, 'todays_etf.csv')
                    if os.path.isfile(todays_etf_path):
                        files['todays_etf'] = todays_etf_path
                except Exception:
                    pass

                # Convert naive UTC to aware UTC
                start_dt_utc = start_dt.replace(tzinfo=timezone.utc)
                end_dt_utc = end_ts.replace(tzinfo=timezone.utc)

                try:
                    send_execution_email(
                        success=success,
                        metrics=metrics,
                        files=files,
                        mode=mode,
                        started_at_utc=start_dt_utc,
                        ended_at_utc=end_dt_utc,
                        pid=p.pid,
                        log_path=log_path
                    )
                except Exception:
                    # Fallback to simple admin alert
                    summary = []
                    summary.append(f"Mode: {mode}")
                    summary.append(f"PID: {p.pid}")
                    summary.append(f"Exit code: {rc}")
                    summary.append(f"Started at: {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    summary.append(f"Ended at: {end_ts.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    summary.append(f"Duration: {int(duration)}s")
                    if any(v is not None for v in metrics.values()):
                        summary.append("")
                        summary.append("Execution summary:")
                        summary.append(f"  Total clients: {metrics.get('total_clients')}")
                        summary.append(f"  Passed: {metrics.get('passed')}  Failed: {metrics.get('failed')}")
                        summary.append(f"  Total orders: {metrics.get('total_orders')}  OK: {metrics.get('ok_orders')}  Fail: {metrics.get('fail_orders')}")
                    summary.append("")
                    summary.append(f"Log file: {log_path}")
                    subject = "✅ Manual Execution Finished" if success else "🚨 Manual Execution Failed"
                    send_admin_alert_email(subject, "\n".join(summary))
            except Exception:
                pass
            finally:
                try:
                    log_file.flush()
                    log_file.close()
                except Exception:
                    pass

        import threading
        threading.Thread(target=_notify_on_finish, args=(proc, mode, start_ts, log_path, log_file), daemon=True).start()

        return jsonify({
            'success': True,
            'message': f'Started ETF execution (direct) in {mode} mode. PID={proc.pid}',
            'details': {'pid': proc.pid, 'mode': mode, 'headless': (mode == 'headless'), 'log': log_path}
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error triggering execution: {str(e)}'}), 500


@app.route('/admin/scheduler/status')
@admin_required
def admin_scheduler_status():
    """Get current scheduler status (AJAX endpoint)"""
    try:
        # Get real-time status
        active_clients = Broker.query.filter_by(is_active=True).count()
        total_clients = Broker.query.count()

        # Get scheduler settings
        settings = SchedulerSettings.query.first()
        if not settings:
            settings = SchedulerSettings()

        # Count potential password warnings (Finvasia accounts older than 2.5 months)
        from datetime import timedelta
        warning_date = datetime.datetime.now() - timedelta(days=75)  # 2.5 months
        finvasia_brokers = Broker.query.filter_by(broker_name='FINVASIA').all()
        password_warnings = sum(1 for broker in finvasia_brokers
                                if broker.created_at < warning_date)

        status = {
            'is_running': True,
            'active_clients': active_clients,
            'total_clients': total_clients,
            'last_health_check': 'Not yet run',
            'last_execution': 'Not yet run',
            'failed_sessions': 0,
            'driver_status': 'OK',
            'password_warnings': password_warnings,
            'morning_check_time': settings.session_test_time,
            'execution_time': settings.execution_time,
            'driver_check_enabled': settings.driver_check_enabled,
            'password_check_enabled': settings.password_check_enabled,
            'email_notifications_enabled': settings.email_notifications_enabled
        }

        return jsonify(status)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/scheduler/test-driver-update', methods=['POST'])
@admin_required
def admin_test_driver_update():
    """Test Chrome driver update"""
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        data = request.get_json(silent=True) or {}
        headless = data.get('headless')
        if headless is None:
            arg = request.args.get('headless')
            headless = arg.lower() in ('1','true','yes') if arg is not None else True
        scheduler = EnhancedExecutionScheduler()
        result = scheduler.manual_driver_check(headless=headless)
        try:
            from email_notifications import send_admin_alert_email
            send_admin_alert_email(
                subject="Chrome Driver Check",
                message=f"Mode: {'headless' if headless else 'browser'}\nResult: {'OK' if result.get('success') else 'Issues'}\nDetails: {result.get('message','')}"
            )
        except Exception:
            pass
        return jsonify({
            'success': result['success'],
            'message': result['message'],
            'details': result.get('details', {})
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error testing driver update: {str(e)}'
        }), 500


@app.route('/admin/scheduler/send-test-alert', methods=['POST'])
@admin_required
def admin_send_test_alert():
    """Send test alert email to admin"""
    try:
        from email_notifications import send_admin_alert_email
        from datetime import datetime
        msg = (
            "This is a test alert from the SmartETF Enhanced Execution Scheduler.\n"
            f"Triggered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Admin: {session.get('user_email', 'admin')}"
        )
        send_admin_alert_email(
            subject="🧪 Test Alert - SmartETF Scheduler",
            message=msg
        )
        return jsonify({'success': True, 'message': 'Test alert email sent successfully! Check your inbox.', 'details': {'email_sent': True, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error sending test alert: {str(e)}', 'details': {'error': str(e)}}), 500

@app.route('/admin/scheduler/test-database', methods=['POST'])
@admin_required
def admin_test_database():
    try:
        users = User.query.count()
        brokers = Broker.query.count()
        return jsonify({'success': True, 'message': 'Database OK', 'details': {'users': users, 'brokers': brokers}})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database test failed: {str(e)}'}), 500

@app.route('/admin/scheduler/test-sessions', methods=['POST'])
@admin_required
def admin_test_sessions():
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        scheduler = EnhancedExecutionScheduler()
        result = scheduler.manual_health_check(headless=True)
        return jsonify({'success': result['success'], 'message': 'Session test completed', 'details': result.get('details', {})})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Session test failed: {str(e)}'}), 500

@app.route('/admin/scheduler/test-etf-fetch', methods=['POST'])
@admin_required
def admin_test_etf_fetch():
    try:
        from strategy_runner.etf_automated import fetch_and_filter_etfs
        fetch_and_filter_etfs()
        return jsonify({'success': True, 'message': 'ETF fetch completed', 'details': {}})
    except Exception as e:
        return jsonify({'success': False, 'message': f'ETF fetch failed: {str(e)}'}), 500

@app.route('/admin/runs')
@admin_required
def admin_runs():
    runs = ExecutionRun.query.order_by(ExecutionRun.started_at.desc()).limit(50).all()
    return render_template('admin/runs.html', runs=runs)

@app.route('/admin/run/<int:run_id>/events')
@admin_required
def admin_run_events(run_id):
    run = ExecutionRun.query.get_or_404(run_id)
    events = OrderEvent.query.filter_by(run_id=run_id).order_by(OrderEvent.placed_at.desc()).limit(1000).all()
    return render_template('admin/run_events.html', run=run, events=events)


@app.route('/broker/edit/<int:broker_id>', methods=['GET', 'POST'])
@login_required
def edit_broker(broker_id):
    user_id = session['user_id']
    broker = Broker.query.filter_by(id=broker_id, user_id=user_id).first_or_404()

    # Get the supported broker details to know required fields
    supported_broker = SupportedBroker.query.filter_by(name=broker.broker_name).first()

    if request.method == 'POST':
        # Update broker details
        broker.user_id_broker = request.form.get('user_id_broker')

        # Only update password if provided
        new_password = request.form.get('password')
        if new_password:
            broker.password = new_password

        # Update broker-specific fields if provided
        if supported_broker.requires_totp:
            totp_secret = request.form.get('totp_secret')
            if totp_secret:
                broker.totp_secret = totp_secret

        if supported_broker.requires_api_key:
            api_key = request.form.get('api_key')
            if api_key:
                broker.api_key = api_key

        if supported_broker.requires_api_secret:
            api_secret = request.form.get('api_secret')
            if api_secret:
                broker.api_secret = api_secret

        if supported_broker.requires_vendor_code:
            vendor_code = request.form.get('vendor_code')
            if vendor_code:
                broker.vendor_code = vendor_code

        if supported_broker.requires_imei:
            imei = request.form.get('imei')
            if imei:
                broker.imei = imei

        if supported_broker.requires_access_token:
            access_token = request.form.get('access_token')
            if access_token:
                broker.access_token = access_token

        try:
            db.session.commit()

            # Update CSV export
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)

            flash("Broker details updated successfully", "success")
            return redirect(url_for('view_broker', broker_id=broker.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating broker: {str(e)}", "error")

    return render_template('client/edit_broker.html', broker=broker, supported_broker=supported_broker)


@app.route('/install_razorpay', methods=['GET'])
@admin_required
def install_razorpay():
    try:
        import subprocess
        subprocess.check_call(['pip', 'install', 'razorpay'])
        return "Razorpay package installed successfully!"
    except Exception as e:
        return f"Error installing Razorpay: {str(e)}"


@app.route('/plan/checkout/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def checkout(plan_id):
    user_id = session['user_id']
    user = User.query.get_or_404(user_id)
    plan = Plan.query.get_or_404(plan_id)
    billing_cycle = request.form.get('billing_cycle') or request.args.get('billing_cycle', 'monthly')

    # Get current subscription
    current_subscription = get_current_subscription(user_id)

    # Check if user is extending a subscription
    is_extension = current_subscription and current_subscription.plan_id == plan.id

    # Define payment method types
    payment_method_types = ['Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'PayTM']

    # Create Razorpay order
    razorpay_order = None
    try:
        # Convert price to paise
        price_map = {
            "monthly": plan.monthly_price or 0,
            "quarterly": plan.quarterly_price or 0,
            "half_yearly": plan.half_yearly_price or 0,
            "annually": plan.annually_price or 0
        }
        selected_price = price_map.get(billing_cycle, 0)
        if selected_price <= 0:
            flash(f"Invalid price for {billing_cycle} billing cycle", "error")
            return redirect(url_for('view_plans'))
        amount_in_paise = int(selected_price * 100)
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f'plan_purchase_{plan.id}_{user.id}',
            'notes': {
                'plan_id': plan.id,
                'user_id': user.id,
                'plan_name': plan.name,
                'billing_cycle': billing_cycle,
                'is_extension': '1' if is_extension else '0'
            }
        }

        razorpay_order = razorpay_client.order.create(data=order_data)
    except Exception as e:
        flash(f"Error initializing payment: {str(e)}", "error")
        razorpay_order = None

    # Additional checkout handling code...

    return render_template(
        'client/checkout.html',
        plan=plan,
        user=user,
        current_subscription=current_subscription,
        is_extension=is_extension,
        payment_method_types=payment_method_types,
        razorpay_order=razorpay_order,
        razorpay_key_id=razorpay_key_id,
        billing_cycle=billing_cycle
    )


@app.route('/payment/verify', methods=['POST'])
@login_required
def payment_verify():
    try:
        # Get the payment data
        payment_id = request.form.get('razorpay_payment_id')
        order_id = request.form.get('razorpay_order_id')
        signature = request.form.get('razorpay_signature')
        user_id = session['user_id']

        # Get the user to access their customer_id
        user = User.query.get_or_404(user_id)

        # Verify signature
        params_dict = {
            'razorpay_payment_id': payment_id,
            'razorpay_order_id': order_id,
            'razorpay_signature': signature
        }

        try:
            razorpay_client.utility.verify_payment_signature(params_dict)
            payment_verified = True
        except Exception as e:
            payment_verified = False
            flash(f"Payment verification failed: {str(e)}", "error")
            return redirect(url_for('view_plans'))

        if payment_verified:
            # Get payment details from Razorpay
            payment_details = razorpay_client.payment.fetch(payment_id)

            # Get order details to retrieve plan and user info
            order_details = razorpay_client.order.fetch(order_id)

            plan_id = int(order_details['notes']['plan_id'])
            plan = Plan.query.get_or_404(plan_id)
            amount = payment_details['amount'] / 100  # Convert from paise to rupees
            payment_method = payment_details.get('method', 'Razorpay')
            billing_cycle = order_details['notes'].get('billing_cycle')

            # Check if the user already has an active subscription for this plan
            current_subscription = Subscription.query.filter_by(
                customer_id=user.customer_id,
                plan_id=plan_id,
                payment_status='Successful'
            ).filter(
                Subscription.expiry_date > datetime.datetime.now()
            ).first()

            # Find the latest subscription end date for this plan (active or queued)
            latest_subscription = Subscription.query.filter_by(
                customer_id=user.customer_id,
                plan_id=plan_id,
                payment_status='Successful'
            ).order_by(Subscription.expiry_date.desc()).first()

            if latest_subscription:
                # Start the new subscription after the latest one ends
                start_date = latest_subscription.expiry_date
                is_queued = True if start_date > datetime.datetime.now() else False
            else:
                # No existing subscription, start immediately
                start_date = datetime.datetime.now()
                is_queued = False

            # Calculate expiry date based on the start date
            # billing_cycle = request.form.get('billing_cycle')  # or request.json.get if using JS

            if billing_cycle == 'monthly':
                expiry_date = start_date + relativedelta(months=1)
                amount = plan.monthly_price
            elif billing_cycle == 'quarterly':
                expiry_date = start_date + relativedelta(months=3)
                amount = plan.quarterly_price
            elif billing_cycle == 'half_yearly':
                expiry_date = start_date + relativedelta(months=6)
                amount = plan.half_yearly_price
            elif billing_cycle == 'annually':
                expiry_date = start_date + relativedelta(years=1)
                amount = plan.annually_price
            else:
                flash("Invalid billing cycle", "error")
                return redirect(url_for('view_plans'))

            # Create the new subscription
            subscription = Subscription(
                customer_id=user.customer_id,
                plan_id=plan_id,
                plan_name=plan.name,
                start_date=start_date,
                expiry_date=expiry_date,
                billing_cycle=billing_cycle,
                payment_status='Successful',
                payment_method=payment_method,
                payment_id=payment_id,
                amount=amount
            )

            db.session.add(subscription)

            # Create payment record
            payment = PaymentMethod(
                name=f"Payment for {plan.name}",
                description=f"Razorpay payment for {plan.name} subscription" +
                            (f" (queued to start on {start_date.strftime('%d %b, %Y')})" if is_queued else ""),
                is_active=True,
                created_at=datetime.datetime.utcnow(),
                payment_data=datetime.datetime.utcnow(),
                payment_method=payment_method,
                payment_id=payment_id,
                amount_paid=amount,
                customer_id=User.query.get(user_id).customer_id,
                payment_status='Successful'
            )
            db.session.add(payment)

            # Only update broker accounts if this is the current active subscription
            if not is_queued:
                # Update broker accounts
                broker_accounts = Broker.query.filter_by(user_id=user_id).all()
                for broker in broker_accounts:
                    broker.subscription_status = 'Active'
                    broker.subscription_expiry = expiry_date
                    broker.plan_id = plan_id

                    # Update Algo Investment settings based on plan
                    if plan.has_copy_trading:
                        broker.copy = True
                        # If no master account exists, make the first one the master
                        if not Broker.query.filter_by(user_id=user_id, is_master=True).first() and broker_accounts:
                            broker_accounts[0].is_master = True

            db.session.commit()

            # Export updated broker data
            all_brokers = Broker.query.all()
            export_brokers_to_csv(all_brokers)

            if is_queued:
                flash(
                    f"Your subscription to {plan.name} has been queued and will automatically start on {start_date.strftime('%d %b, %Y')}.",
                    "success")
            else:
                flash(f"Plan '{plan.name}' purchased successfully! Your subscription is now active.", "success")

            return redirect(url_for('dashboard'))

    except Exception as e:
        flash(f"Error processing payment: {str(e)}", "error")

    return redirect(url_for('view_plans'))


@app.route('/payment/success')
@login_required
def payment_success():
    return render_template('client/payment_success.html')


@app.route('/payment/cancel')
@login_required
def payment_cancel():
    return render_template('client/payment_cancel.html')


# ------------------------------------------------------------------------------
# Error handlers
# ------------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', error="Page not found"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error="Internal server error"), 500


@app.errorhandler(Exception)
def handle_error(e):
    if app.debug:
        raise e
    return render_template('error.html', error=str(e)), 500


# ------------------------------------------------------------------------------
# Database initialization and app startup
# ------------------------------------------------------------------------------
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
                    features="Single broker access\nBasic ETF Investment\nEmail support",
                    status='Active',
                    is_active=True,
                    has_copy_trading=False,
                    max_sip_amount=20000,
                    max_brokers=1,
                    monthly_price=499.00,
                    quarterly_price=1349.00,
                    half_yearly_price=2499.00,
                    annually_price=4999.00
                ),
                Plan(
                    name="Standard Plan",
                    description="Enhanced ETF trading with Investment functionality",
                    features="Single broker access\nInvestment functionality\nPriority support",
                    status='Active',
                    is_active=True,
                    has_copy_trading=True,
                    max_sip_amount=50000,
                    max_brokers=2,
                    monthly_price=999.00,
                    quarterly_price=2699.00,
                    half_yearly_price=4999.00,
                    annually_price=9999.00
                ),
                Plan(
                    name="Premium Plan",
                    description="Full featured ETF trading platform for professionals",
                    features="Multiple broker access\nAdvanced ETF strategies\nPriority support\nAlgo Investment",
                    status='Active',
                    is_active=True,
                    has_copy_trading=True,
                    max_sip_amount=100000,
                    max_brokers=5,
                    monthly_price=1999.00,
                    quarterly_price=5399.00,
                    half_yearly_price=9999.00,
                    annually_price=19999.00
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
                    requires_access_token=True
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


@app.route('/admin/initialize-payment-methods', methods=['GET'])
@admin_required
def initialize_payment_methods():
    create_default_payment_methods()
    flash("Payment methods initialized", "success")
    return redirect(url_for('admin_payment_methods'))


def create_default_subscription_statuses():
    """Create default subscription statuses if none exist."""
    try:
        if SubscriptionStatus.query.count() == 0:
            statuses = [
                SubscriptionStatus(
                    name="Active",
                    description="Subscription is active"
                ),
                SubscriptionStatus(
                    name="Pending",
                    description="Subscription is pending activation"
                ),
                SubscriptionStatus(
                    name="Expired",
                    description="Subscription has expired"
                ),
                SubscriptionStatus(
                    name="Cancelled",
                    description="Subscription was cancelled"
                )
            ]

            for status in statuses:
                db.session.add(status)

            db.session.commit()
            print(f"Created {len(statuses)} default subscription statuses")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default subscription statuses: {e}")


def create_admin_user():
    """Create a default admin user if none exists."""
    try:
        if not User.query.filter_by(is_admin=True).first():
            admin = User(
                full_name="Admin",
                address="N/A",
                state="N/A",
                city="N/A",
                pin="000000",
                username="admin",
                email="admin@admin.com",
                mobile="9999999999",
                password_hash=generate_password_hash("admin"),
                disclaimer_accepted=False,
                is_admin=True,
                is_active=True,
                customer_id="admin_default"
            )
            admin.set_password("adminpassword")

            db.session.add(admin)
            db.session.commit()

            print("Default admin user created")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating admin user: {e}")


@app.route('/debug/user/<int:user_id>/subscription')
@admin_required
def debug_user_subscription(user_id):
    """Debug route to check subscription data for a user."""
    now = datetime.datetime.utcnow()
    user = User.query.get(user_id)

    if not user:
        return f"<h1>User {user_id} not found</h1>"

    # Get all subscriptions for this user
    all_subs = Subscription.query.filter(
        Subscription.customer_id == user.customer_id
    ).all()

    # Get current subscription using the function
    current_sub = get_current_subscription(user_id)

    debug_info = f"""
    <h1>Debug Subscription Data for User {user_id}</h1>
    <h2>User Info:</h2>
    <ul>
        <li>Username: {user.username}</li>
        <li>Customer ID: {user.customer_id}</li>
        <li>Email: {user.email}</li>
    </ul>

    <h2>Current Time:</h2>
    <p>{now}</p>

    <h2>All Subscriptions ({len(all_subs)}):</h2>
    <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr>
            <th>ID</th>
            <th>Plan</th>
            <th>Payment Status</th>
            <th>Start Date</th>
            <th>Expiry Date</th>
            <th>Is Queued</th>
            <th>Should Be Active?</th>
        </tr>
    """

    for sub in all_subs:
        status_ok = sub.payment_status in ['Successful', 'Active', 'Paid']
        not_queued = sub.is_queued == False or sub.is_queued is None
        started = sub.start_date <= now
        not_expired = sub.expiry_date > now
        should_be_active = status_ok and not_queued and started and not_expired

        debug_info += f"""
        <tr>
            <td>{sub.id}</td>
            <td>{sub.plan_name}</td>
            <td>{sub.payment_status}</td>
            <td>{sub.start_date}</td>
            <td>{sub.expiry_date}</td>
            <td>{sub.is_queued}</td>
            <td style="background-color: {'lightgreen' if should_be_active else 'lightcoral'}">
                {should_be_active}<br>
                Status OK: {status_ok}<br>
                Not Queued: {not_queued}<br>
                Started: {started}<br>
                Not Expired: {not_expired}
            </td>
        </tr>
        """

    debug_info += f"""
    </table>

    <h2>Current Subscription Function Result:</h2>
    <p style="background-color: {'lightgreen' if current_sub else 'lightcoral'}; padding: 10px;">
        {f'Found: {current_sub.plan_name} (ID: {current_sub.id})' if current_sub else 'No active subscription found'}
    </p>

    <p><a href="{url_for('admin_view_user', user_id=user_id)}">&larr; Back to User Details</a></p>
    """

    return debug_info


# Main entry point
if __name__ == '__main__':
    # Import send_file here to avoid possible circular import
    from flask import send_file

    try:
        # Create database tables manually before running
        with app.app_context():
            db.create_all()
            create_admin_user()
            create_default_plans()
            create_default_supported_brokers()
            create_default_payment_methods()
            create_default_subscription_statuses()
            os.makedirs('data', exist_ok=True)

            # Initialize and create default scheduler settings
            settings = SchedulerSettings.query.first()
            if not settings:
                settings = SchedulerSettings()
                db.session.add(settings)
                db.session.commit()
                print("Created default scheduler settings")

        # Initialize and start the Enhanced Execution Scheduler
        try:
            from strategy_runner.execution_scheduler import EnhancedExecutionScheduler

            print("Initializing Enhanced Execution Scheduler...")
            scheduler = EnhancedExecutionScheduler()

            # Start the scheduler in background
            scheduler.start_scheduler()
            print("✅ Enhanced Execution Scheduler started successfully!")
            print("📅 Morning health checks scheduled")
            print("🚀 Afternoon strategy execution scheduled")

        except Exception as e:
            print(f"❌ Warning: Could not start scheduler: {e}")
            print("The application will still run, but automated scheduling will not work.")

        # Run the app
        print("Starting ETF Trading Portal...")
        # app.run(debug=True, host='0.0.0.0', port=8005)
        port = int(os.environ.get("PORT", 8080))
        app.run(debug=False, host="0.0.0.0", port=port)
    except Exception as e:
        print(f"Error during startup: {e}")