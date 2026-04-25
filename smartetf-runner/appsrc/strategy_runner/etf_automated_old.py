from strategy_runner.notify_admin import notify_admin
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import pandas as pd
import datetime
from datetime import datetime as dt, timedelta
from fetch_etf_data import fetch_etf_data
from filter_etfs import calculate_quantities
from broker_dispatcher import get_executor_for_broker
from client_fetcher import get_active_clients_with_sip
from app import app, Broker, Subscription, Plan, User, db
from models import ExecutionRun, OrderEvent, MonthlyInvestment
import zipfile
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MAX_RETRIES = 3
RETRY_DELAY = 5

# User-configurable run mode: set to 'browser' to see Chrome, or 'headless' to run without UI
RUN_MODE = os.getenv('RUN_MODE', 'headless').lower()
# Multiplier is based on SIP monthly vs baseline (no remaining-based logic)
USE_MULTIPLIER = True
BASE_MONTHLY = float(os.getenv('BASE_MONTHLY', '10000'))  # 1x at ₹10,000 by default
MULTIPLIER_MIN = float(os.getenv('MULTIPLIER_MIN', '0.5'))
MULTIPLIER_MAX = float(os.getenv('MULTIPLIER_MAX', '5.0'))

def create_monthly_tracking_folder():
    """Create folder for monthly tracking CSV files"""
    current_month = dt.now().strftime('%Y-%m')
    folder_path = f"monthly_tracking/{current_month}"
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def read_monthly_invested(customer_id, current_month=None):
    """Read month-to-date invested amount; prefer DB, fallback to CSV"""
    if not current_month:
        current_month = dt.now().strftime('%Y-%m')

    if os.getenv('ENABLE_MONTHLY_DB', '0').lower() in ('1', 'true', 'yes'):
        try:
            with app.app_context():
                total = db.session.query(db.func.coalesce(db.func.sum(MonthlyInvestment.invested_amount), 0.0)) \
                    .filter(MonthlyInvestment.customer_id == customer_id, MonthlyInvestment.month == current_month) \
                    .scalar()
                if total is not None:
                    return float(total)
        except Exception as e:
            logging.warning(f"MonthlyInvestment DB read failed for {customer_id}: {e}")

    folder_path = f"monthly_tracking/{current_month}"
    tracking_file = f"{folder_path}/{customer_id}_monthly.csv"

    if not os.path.exists(tracking_file):
        return 0.0

    try:
        df = pd.read_csv(tracking_file)
        return df['invested_amount'].sum()
    except Exception as e:
        logging.warning(f"Error reading monthly tracking for {customer_id}: {e}")
        return 0.0

def update_monthly_invested(customer_id, investment_amount, etf_details=None):
    """Update monthly invested amount for a customer (DB + CSV audit)"""
    current_month = dt.now().strftime('%Y-%m')
    folder_path = create_monthly_tracking_folder()
    tracking_file = f"{folder_path}/{customer_id}_monthly.csv"

    if os.getenv('ENABLE_MONTHLY_DB', '0').lower() in ('1', 'true', 'yes'):
        try:
            with app.app_context():
                db.session.add(MonthlyInvestment(
                    customer_id=customer_id,
                    day=dt.now().date(),
                    month=current_month,
                    invested_amount=float(investment_amount or 0),
                    etf_details_json=etf_details or []
                ))
                db.session.commit()
        except Exception as e:
            logging.warning(f"MonthlyInvestment DB insert failed for {customer_id}: {e}")
    
    new_record = {
        'date': dt.now().strftime('%Y-%m-%d'),
        'time': dt.now().strftime('%H:%M:%S'),
        'invested_amount': investment_amount,
        'etf_count': len(etf_details) if etf_details else 0,
        'etf_details': json.dumps(etf_details) if etf_details else ''
    }
    
    try:
        if os.path.exists(tracking_file):
            df = pd.read_csv(tracking_file)
            df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
        else:
            df = pd.DataFrame([new_record])
        df.to_csv(tracking_file, index=False)
        logging.info(f"Updated monthly tracking for {customer_id}: +₹{investment_amount}")
    except Exception as e:
        logging.error(f"Error updating monthly tracking for {customer_id}: {e}")

def calculate_market_condition():
    """Analyze market condition for consecutive falling days"""
    # This is a simplified version - you can enhance with actual market data
    # For now, we'll use ETF data to determine market condition
    try:
        # Check last 5 days of market data (simplified)
        # You can enhance this with actual market indices
        return {
            'consecutive_falling_days': 0,  # Will be enhanced
            'market_severity': 'normal',    # normal, moderate_fall, severe_fall
            'adjustment_factor': 1.0        # Multiplier for aggressive investment
        }
    except Exception as e:
        logging.warning(f"Error calculating market condition: {e}")
        return {'consecutive_falling_days': 0, 'market_severity': 'normal', 'adjustment_factor': 1.0}

def calculate_user_multipliers(filtered_etfs_df):
    """Calculate personalized multipliers for each user based on SIP targets and market conditions"""
    
    with app.app_context():
        user_multipliers = {}
        market_condition = calculate_market_condition()
        current_month = dt.now().strftime('%Y-%m')
        
        logging.info(f"Calculating multipliers for {current_month}")
        logging.info(f"Market condition: {market_condition}")
        
        # Get current (unique) active subscriptions with SIP targets per customer
        now = datetime.datetime.utcnow()
        active_subscriptions = (
            Subscription.query
            .filter(
                Subscription.payment_status.in_(['Active', 'Successful', 'Paid']),
                Subscription.start_date <= now,
                Subscription.expiry_date > now,
                Subscription.is_queued.is_(False),
                Subscription.monthly_sip_target.isnot(None),
                Subscription.monthly_sip_target > 0
            ).all()
        )

        # Deduplicate: keep latest-expiring subscription per customer
        subs_by_customer = {}
        for sub in active_subscriptions:
            prev = subs_by_customer.get(sub.customer_id)
            if prev is None or (sub.expiry_date and prev and sub.expiry_date > prev.expiry_date):
                subs_by_customer[sub.customer_id] = sub
        unique_subscriptions = list(subs_by_customer.values())
        
        logging.info(f"Found {len(unique_subscriptions)} unique customers with SIP targets")
        
        for subscription in unique_subscriptions:
            try:
                customer_id = subscription.customer_id
                sip_monthly = float(subscription.monthly_sip_target or 0)
                if sip_monthly <= 0:
                    continue
                m = sip_monthly / BASE_MONTHLY if BASE_MONTHLY > 0 else 1.0
                m = max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, m))
                user_multipliers[customer_id] = {
                    'multiplier': round(m, 2),
                    'monthly_target': sip_monthly,
                    'month_invested': None,
                    'remaining_target': None,
                    'market_condition': 'sip_ratio'
                }
                logging.info(f"User {customer_id}: SIP=₹{sip_monthly}, Multiplier={m}")
            except Exception as e:
                logging.error(f"Error calculating multiplier for subscription {subscription.id}: {e}")
                continue
        
        return user_multipliers

def generate_daily_csvs(filtered_etfs_df, user_multipliers):
    """Generate daily CSV files for ETF orders and user tracking"""
    
    try:
        timestamp = dt.now().strftime('%Y%m%d_%H%M%S')
        
        # 1. Generate ETF Orders CSV
        etf_orders = []
        for _, row in filtered_etfs_df.iterrows():
            etf_orders.append({
                'symbol': row['SYMBOL'],
                'ltp': row['LTP'],
                'base_qty': row['QTY'],
                'base_amount': row['FINAL_AMOUNT']
            })
        
        etf_df = pd.DataFrame(etf_orders)
        etf_csv_path = f"daily_orders/etf_orders_{timestamp}.csv"
        os.makedirs('daily_orders', exist_ok=True)
        etf_df.to_csv(etf_csv_path, index=False)
        
        # 2. Generate User Tracking CSV
        user_tracking = []
        for customer_id, data in user_multipliers.items():
            # Get user details
            with app.app_context():
                user = User.query.filter_by(customer_id=customer_id).first()
                username = user.username if user else customer_id
            
            user_tracking.append({
                'customer_id': customer_id,
                'username': username,
                'monthly_target': data['monthly_target'],
                'month_invested': data['month_invested'],
                'remaining_target': data['remaining_target'],
                'multiplier': data['multiplier'],
                'market_condition': data['market_condition'],
                'estimated_investment': sum(row['FINAL_AMOUNT'] * data['multiplier'] for _, row in filtered_etfs_df.iterrows())
            })
        
        user_df = pd.DataFrame(user_tracking)
        user_csv_path = f"daily_orders/user_tracking_{timestamp}.csv"
        user_df.to_csv(user_csv_path, index=False)
        
        # 3. Create ZIP file
        zip_path = f"daily_orders/smartetf_orders_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(etf_csv_path, os.path.basename(etf_csv_path))
            zipf.write(user_csv_path, os.path.basename(user_csv_path))
        
        logging.info(f"Generated daily CSVs and ZIP: {zip_path}")
        
        return {
            'etf_csv': etf_csv_path,
            'user_csv': user_csv_path,
            'zip_file': zip_path,
            'total_users': len(user_multipliers)
        }
        
    except Exception as e:
        logging.error(f"Error generating daily CSVs: {e}")
        return None

def execute_etf_orders(filtered_etfs_df, user_multipliers, run_id=None):
    """Execute ETF orders for all users with their personalized multipliers; log OrderEvent rows"""
    
    with app.app_context():
        active_clients = get_active_clients_with_sip()
        
        execution_summary = {
            'total_clients': len(active_clients),
            'successful_orders': 0,
            'failed_orders': 0,
            'total_investment': 0
        }
        
        for client in active_clients:
            try:
                customer_id = client.get('customer_id')
                
                if customer_id not in user_multipliers:
                    logging.warning(f"No multiplier found for client {customer_id}")
                    continue
                
                user_data = user_multipliers[customer_id]
                multiplier = user_data['multiplier']
                
                broker_name = client.get('broker_name', '').upper()
                executor = get_executor_for_broker(broker_name)
                
                if not executor:
                    logging.error(f"No executor found for broker {broker_name}")
                    execution_summary['failed_orders'] += 1
                    continue
                
                personalized_etfs = filtered_etfs_df.copy()
                if USE_MULTIPLIER:
                    # Floor integer quantities based on SIP multiplier (no redistribution)
                    personalized_etfs['USER_QTY'] = (personalized_etfs['QTY'] * multiplier).apply(lambda x: int(x))
                else:
                    personalized_etfs['USER_QTY'] = personalized_etfs['QTY'].astype(int)
                personalized_etfs['USER_AMOUNT'] = personalized_etfs['USER_QTY'] * personalized_etfs['LTP']
                total_investment = float(personalized_etfs['USER_AMOUNT'].sum())
                
                executor.place_order(client, personalized_etfs)
                
                etf_details = personalized_etfs[['SYMBOL', 'USER_QTY', 'USER_AMOUNT']].to_dict('records')
                update_monthly_invested(customer_id, total_investment, etf_details)
                
                execution_summary['successful_orders'] += 1
                execution_summary['total_investment'] += total_investment
                
                try:
                    if run_id is not None:
                        for row in personalized_etfs.itertuples(index=False):
                            db.session.add(OrderEvent(
                                run_id=run_id,
                                customer_id=customer_id,
                                broker_name=broker_name,
                                symbol=row.SYMBOL,
                                side='BUY',
                                qty=int(row.USER_QTY),
                                status='SUCCESS'
                            ))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logging.warning(f"OrderEvent logging failed for {customer_id}: {e}")
                
                logging.info(f"Orders executed for {customer_id}: ₹{total_investment} (multiplier: {multiplier})")
                
            except Exception as e:
                logging.error(f"Error executing orders for client {client.get('customer_id', 'unknown')}: {e}")
                execution_summary['failed_orders'] += 1
                if run_id is not None:
                    try:
                        db.session.add(OrderEvent(
                            run_id=run_id,
                            customer_id=client.get('customer_id'),
                            broker_name=client.get('broker_name','').upper(),
                            symbol='ALL',
                            side='BUY',
                            qty=0,
                            status='FAILED',
                            error=str(e)
                        ))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                continue
        
        return execution_summary

def fetch_and_filter_etfs(mode: str = 'headless'):
    """Main function to fetch ETF data, calculate multipliers, and execute strategy"""
    
    print("📊 Starting ETF SIP Strategy with Personalized Multipliers...")

    run_id = None
    if os.getenv('ENABLE_RUN_LOGS', '0').lower() in ('1', 'true', 'yes'):
        with app.app_context():
            try:
                run = ExecutionRun(mode='browser' if mode == 'browser' else 'headless', status='running')
                db.session.add(run)
                db.session.commit()
                run_id = run.id
            except Exception as e:
                print(f"⚠️ Failed to create ExecutionRun: {e}")
    
    # Step 1: Fetch ETF data
    print("⏳ Fetching ETF data...")
    retry_count = 0
    etf_csv_file = None

    while retry_count < MAX_RETRIES:
        print(f"⏳ Attempt {retry_count + 1} to fetch ETF data...")
        etf_csv_file = fetch_etf_data(headless=(mode != 'browser'))

        if etf_csv_file:
            print("✅ ETF data fetched successfully.")
            break

        retry_count += 1
        if retry_count < MAX_RETRIES:
            print(f"🔁 Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

    if not etf_csv_file:
        print("❌ Failed to fetch ETF data. Exiting.")
        return None

    # Step 2: Load and filter ETF data
    print("📥 Loading ETF data...")
    etf_data = pd.read_csv(etf_csv_file)
    if etf_data is None or etf_data.empty:
        print("⚠️ Downloaded ETF CSV is empty or invalid.")
        return None

    print("🔍 Filtering ETFs and calculating quantities...")
    filtered = calculate_quantities(etf_data)

    if filtered is None or filtered.empty:
        print("⚠️ No ETFs matched the filter criteria.")
        return None

    print("💾 Saving filtered ETFs to todays_etf.csv")
    filtered.to_csv("todays_etf.csv", index=False)
    
    # Step 3: Calculate personalized multipliers
    print("🧮 Calculating personalized user multipliers...")
    user_multipliers = calculate_user_multipliers(filtered)
    
    if not user_multipliers:
        print("⚠️ No users with SIP targets found.")
        return None
    
    print(f"✅ Calculated multipliers for {len(user_multipliers)} users")
    
    # Step 4: Generate daily CSV files
    print("📝 Generating daily CSV files...")
    csv_result = generate_daily_csvs(filtered, user_multipliers)
    
    if csv_result:
        print(f"✅ Generated CSV files: {csv_result['zip_file']}")
    
    # Step 5: Execute orders
    print("🚀 Executing ETF orders...")
    execution_result = execute_etf_orders(filtered, user_multipliers, run_id=run_id)

    print(f"📊 Execution Summary:")
    print(f"   Total Clients: {execution_result['total_clients']}")
    print(f"   Successful Orders: {execution_result['successful_orders']}")
    print(f"   Failed Orders: {execution_result['failed_orders']}")
    print(f"   Total Investment: ₹{execution_result['total_investment']:,.2f}")

    if os.getenv('ENABLE_RUN_LOGS', '0').lower() in ('1', 'true', 'yes') and run_id is not None:
        with app.app_context():
            try:
                run = ExecutionRun.query.get(run_id)
                if run:
                    run.ended_at = dt.now()
                    run.status = 'success'
                    run.total_clients = execution_result['total_clients']
                    run.processed = execution_result['total_clients']
                    run.passed = execution_result['successful_orders']
                    run.failed = execution_result['failed_orders']
                    run.total_orders = execution_result['successful_orders'] + execution_result['failed_orders']
                    run.ok_orders = execution_result['successful_orders']
                    run.fail_orders = execution_result['failed_orders']
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ Failed to finalize ExecutionRun: {e}")

    return {
        'run_id': run_id,
        'filtered_etfs': filtered,
        'user_multipliers': user_multipliers,
        'csv_files': csv_result,
        'execution_summary': execution_result
    }

if __name__ == "__main__":
    result = fetch_and_filter_etfs(mode=RUN_MODE)
    if result:
        print("🎉 ETF SIP Strategy completed successfully!")
    else:
        print("❌ ETF SIP Strategy failed!")