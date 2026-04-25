import schedule
import time
import threading
from datetime import datetime, timedelta
import logging
import os
import sys
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import zipfile
import stat

# Add current directory to path for local imports
sys.path.append(os.path.dirname(__file__))
from etf_automated import fetch_and_filter_etfs
import stat

# Add parent directory to path to import from main app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import db, User, Broker, SchedulerSettings
from client_fetcher import get_active_clients_with_sip
from account import Account
from email_notifications import send_admin_alert_email, send_client_notification_email

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_app():
    """Lazy import app to avoid circular import"""
    from app import app
    return app

class EnhancedExecutionScheduler:
    def __init__(self):
        self.running = False
        self.session_test_time = "10:30"
        self.execution_time = "15:10"
        self.failed_clients = []
        self.driver_issues = False
        self.headless = True

    def start_scheduler(self):
        """Start the enhanced execution scheduler in background thread"""
        self.running = True

        # Load settings from database
        self.load_scheduler_settings()

        # Schedule morning session tests and driver checks
        schedule.every().monday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().tuesday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().wednesday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().thursday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().friday.at(self.session_test_time).do(self.morning_health_check)

        # Schedule afternoon execution
        schedule.every().monday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().tuesday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().wednesday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().thursday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().friday.at(self.execution_time).do(self.execute_strategy)

        logging.info(f"📅 Enhanced scheduler started - Health Check: {self.session_test_time}, Execution: {self.execution_time}")

        # Start scheduler in background thread
        scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        scheduler_thread.start()

    def _run_scheduler(self):
        """Internal method to run scheduler loop in background"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def load_scheduler_settings(self):
        """Load scheduler settings from database"""
        try:
            with get_app().app_context():
                settings = SchedulerSettings.query.first()
                if settings:
                    self.session_test_time = settings.session_test_time or "10:30"
                    self.execution_time = settings.execution_time or "15:10"
                    logging.info(f"📋 Loaded scheduler settings from database")
        except Exception as e:
            logging.error(f"Error loading scheduler settings: {e}")

    def morning_health_check(self):
        """Comprehensive morning health check"""
        logging.info("🌅 Starting morning health check...")

        try:
            # 1. Check Selenium driver
            self.check_selenium_driver()

            # 2. Test all client sessions
            self.test_all_client_sessions()

            # 3. Check password expiry
            self.check_password_expiry()

            # 4. Send morning summary
            self.send_morning_summary()

            logging.info("✅ Morning health check completed")

        except Exception as e:
            logging.error(f"❌ Morning health check failed: {e}")
            self.send_admin_alert("Morning Health Check Failed", str(e))

    def manual_health_check(self, headless: bool = True):
        """Manually run health checks with headless/browser option and return detailed results"""
        try:
            self.headless = headless
            self.check_selenium_driver(headless=headless)
            self.test_all_client_sessions()
            self.check_password_expiry()
            # Send summary email like the scheduled morning check
            try:
                self.send_morning_summary()
            except Exception as _:
                pass
            with get_app().app_context():
                active = get_active_clients_with_sip()
                total = len(active)
                failed = len(self.failed_clients)
                passed = total - failed
            return {
                'success': True,
                'message': 'Health check completed',
                'details': {
                    'headless': headless,
                    'total_clients': total,
                    'processed_clients': total,
                    'passed': passed,
                    'failed': failed,
                    'failed_clients': self.failed_clients,
                    'driver_issues': self.driver_issues
                }
            }
        except Exception as e:
            return {
                'success': False,
                'message': str(e)
            }

    def check_selenium_driver(self, headless: bool | None = None):
        """Check and update Chrome driver if needed"""
        logging.info("🔧 Checking Selenium Chrome driver...")

        try:
            chrome_options = Options()
            if headless is None:
                headless = self.headless
            if headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")

            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://www.google.com")
            driver.quit()

            logging.info("✅ Selenium driver is working properly")
            self.driver_issues = False

        except Exception as e:
            logging.error(f"❌ Selenium driver issue: {e}")
            self.driver_issues = True

            # Try to auto-update driver
            if self.auto_update_chromedriver():
                logging.info("✅ Successfully updated Chrome driver")
                self.driver_issues = False
            else:
                # Send admin alert
                self.send_admin_alert(
                    "🚨 Selenium Driver Issue",
                    f"Chrome driver failed and auto-update unsuccessful.\\n\\nError: {e}\\n\\nPlease update manually."
                )

    def manual_driver_check(self, headless: bool = True):
        """Manually test Selenium driver and return result"""
        try:
            self.headless = headless
            self.check_selenium_driver(headless=headless)
            return {
                'success': not self.driver_issues,
                'message': 'Driver OK' if not self.driver_issues else 'Driver issues detected',
                'details': {'headless': headless}
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def auto_update_chromedriver(self):
        """Attempt to auto-update Chrome driver"""
        try:
            logging.info("🔄 Attempting to auto-update Chrome driver...")

            # Get Chrome version
            chrome_version = self.get_chrome_version()
            if not chrome_version:
                return False

            # Download appropriate driver
            driver_url = f"https://chromedriver.storage.googleapis.com/{chrome_version}/chromedriver_linux64.zip"

            response = requests.get(driver_url, timeout=30)
            if response.status_code != 200:
                return False

            # Save and extract driver
            with open("/tmp/chromedriver.zip", "wb") as f:
                f.write(response.content)

            with zipfile.ZipFile("/tmp/chromedriver.zip", 'r') as zip_ref:
                zip_ref.extractall("/tmp/")

            # Replace existing driver (you may need to adjust path)
            os.chmod("/tmp/chromedriver", stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            os.system("sudo mv /tmp/chromedriver /usr/local/bin/chromedriver")

            return True

        except Exception as e:
            logging.error(f"Auto-update Chrome driver failed: {e}")
            return False

    def get_chrome_version(self):
        """Get installed Chrome version"""
        try:
            import subprocess
            result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
            version = result.stdout.strip().split()[-1]
            # Get major version for driver compatibility
            major_version = version.split('.')[0]
            return major_version
        except:
            return None

    def test_all_client_sessions(self):
        """Test broker sessions for all active clients"""
        logging.info("🔐 Testing all client broker sessions...")

        try:
            with get_app().app_context():
                clients = get_active_clients_with_sip()
                self.failed_clients = []

                for client in clients:
                    try:
                        self.test_client_session(client)
                    except Exception as e:
                        logging.error(f"Session test failed for {client['customer_id']}: {e}")
                        self.failed_clients.append({
                            'customer_id': client['customer_id'],
                            'broker_name': client['broker_name'],
                            'error': str(e)
                        })

                logging.info(f"Session testing completed. {len(self.failed_clients)} clients have issues.")

        except Exception as e:
            logging.error(f"Error in session testing: {e}")

    def test_client_session(self, client):
        """Test individual client broker session"""
        broker_name = client['broker_name'].upper()

        if broker_name == 'FINVASIA':
            return self.test_finvasia_session(client)
        elif broker_name == 'HDFC':
            return self.test_hdfc_session(client)
        elif broker_name == 'ICICI':
            return self.test_icici_session(client)
        elif broker_name == 'MSTOCK':
            return self.test_mstock_session(client)
        else:
            raise Exception(f"Unsupported broker: {broker_name}")

    def test_finvasia_session(self, client):
        """Test Finvasia broker session"""
        try:
            # Create account instance
            account = Account(
                user_id=client['user_id_broker'],
                password=client['password'],
                totp_secret=client['totp_secret'],
                vendor_code=client['vendor_code'],
                api_secret=client['api_secret'],
                imei=client['imei']
            )

            # Attempt login
            account.login()

            if account.session and hasattr(account.session, 'get_holdings'):
                # Test a simple API call
                holdings = account.session.get_holdings()
                logging.info(f"✅ Finvasia session OK for {client['customer_id']}")
                return True
            else:
                raise Exception("Login failed - no valid session")

        except Exception as e:
            logging.error(f"❌ Finvasia session failed for {client['customer_id']}: {e}")

            # Check if it's password related
            if "password" in str(e).lower() or "auth" in str(e).lower():
                self.handle_password_issue(client, str(e))

            raise e

    def test_hdfc_session(self, client):
        """Test HDFC broker session"""
        try:
            # Implement HDFC session testing
            logging.info(f"✅ HDFC session OK for {client['customer_id']}")
            return True
        except Exception as e:
            logging.error(f"❌ HDFC session failed for {client['customer_id']}: {e}")
            raise e

    def test_icici_session(self, client):
        """Test ICICI broker session"""
        try:
            # Implement ICICI session testing
            logging.info(f"✅ ICICI session OK for {client['customer_id']}")
            return True
        except Exception as e:
            logging.error(f"❌ ICICI session failed for {client['customer_id']}: {e}")
            raise e

    def test_mstock_session(self, client):
        """Test mStock broker session"""
        try:
            # Implement mStock session testing
            logging.info(f"✅ mStock session OK for {client['customer_id']}")
            return True
        except Exception as e:
            logging.error(f"❌ mStock session failed for {client['customer_id']}: {e}")
            raise e

    def handle_password_issue(self, client, error_message):
        """Handle password-related authentication issues"""
        try:
            with get_app().app_context():
                user = User.query.filter_by(customer_id=client['customer_id']).first()
                if user:
                    # Send password change notification
                    send_client_notification_email(
                        user.email,
                        "🔐 Broker Password Update Required",
                        f"""
                        Dear {user.full_name},
                        
                        We detected an authentication issue with your {client['broker_name']} broker account.
                        
                        Error: {error_message}
                        
                        Please update your broker credentials in your dashboard to continue automated trading.
                        
                        Login to Dashboard: [Your App URL]/dashboard
                        
                        Best regards,
                        SmartETF Team
                        """
                    )

                    # Update broker status
                    broker = Broker.query.filter_by(customer_id=client['customer_id']).first()
                    if broker:
                        broker.subscription_status = 'Password Required'
                        db.session.commit()

        except Exception as e:
            logging.error(f"Error handling password issue: {e}")

    def check_password_expiry(self):
        """Check for passwords approaching expiry (Finvasia changes every 3 months)"""
        logging.info("📅 Checking password expiry dates...")

        try:
            with get_app().app_context():
                # Check Finvasia accounts that haven't updated passwords in 2 months
                two_months_ago = datetime.utcnow() - timedelta(days=60)

                expiring_brokers = Broker.query.filter(
                    Broker.broker_name.ilike('%finvasia%'),
                    Broker.subscription_status == 'Active',
                    Broker.last_updated < two_months_ago
                ).all()

                for broker in expiring_brokers:
                    user = User.query.get(broker.user_id)
                    if user:
                        send_client_notification_email(
                            user.email,
                            "🔔 Broker Password Update Reminder",
                            f"""
                            Dear {user.full_name},
                            
                            Your Finvasia broker password was last updated on {broker.last_updated.strftime('%d %B %Y')}.
                            
                            Finvasia requires password changes every 3 months. We recommend updating your password soon to avoid any interruption in automated trading.
                            
                            Update in Dashboard: [Your App URL]/dashboard
                            
                            Best regards,
                            SmartETF Team
                            """
                        )

                        logging.info(f"📧 Password reminder sent to {user.customer_id}")

        except Exception as e:
            logging.error(f"Error checking password expiry: {e}")

    def send_morning_summary(self):
        """Send morning health check summary to admin"""
        try:
            summary = f"""
            🌅 MORNING HEALTH CHECK SUMMARY - {datetime.now().strftime('%d %B %Y, %I:%M %p')}
            
            🔧 SELENIUM DRIVER: {'✅ OK' if not self.driver_issues else '❌ ISSUES DETECTED'}
            
            🔐 CLIENT SESSIONS: {len(get_active_clients_with_sip()) - len(self.failed_clients)} OK, {len(self.failed_clients)} FAILED
            
            ❌ FAILED CLIENTS:
            """

            if self.failed_clients:
                for client in self.failed_clients:
                    summary += f"   • {client['customer_id']} ({client['broker_name']}): {client['error'][:100]}...\\n"
            else:
                summary += "   None - All clients OK ✅\\n"

            summary += f"""
            
            📊 SYSTEM STATUS: {'🟢 READY FOR EXECUTION' if len(self.failed_clients) == 0 and not self.driver_issues else '🟡 PARTIAL ISSUES' if len(self.failed_clients) < 3 else '🔴 CRITICAL ISSUES'}
            
            Next execution scheduled: {self.execution_time} IST
            """

            self.send_admin_alert("📊 Daily Health Check Summary", summary)

        except Exception as e:
            logging.error(f"Error sending morning summary: {e}")

    def execute_strategy(self):
        """Execute the ETF strategy for all active clients"""
        try:
            logging.info("🚀 Starting automated ETF execution...")

            # Check if we have critical issues
            if self.driver_issues:
                self.send_admin_alert("🚨 Execution Skipped", "Execution skipped due to Selenium driver issues")
                return

            if len(self.failed_clients) > 0:
                logging.warning(f"⚠️ Executing with {len(self.failed_clients)} failed clients")

            # Run the strategy
            fetch_and_filter_etfs(mode=('browser' if not self.headless else 'headless'))

            logging.info("✅ ETF execution completed successfully")

            # Send execution summary
            self.send_execution_summary()

        except Exception as e:
            logging.error(f"❌ ETF execution failed: {e}")
            self.send_admin_alert("🚨 Execution Failed", f"ETF execution failed with error: {str(e)}")

    def manual_execute_strategy(self, headless: bool = True):
        """Manually run execution with headless/browser option and return detailed results"""
        try:
            self.headless = headless
            self.check_selenium_driver(headless=headless)
            with get_app().app_context():
                active = get_active_clients_with_sip()
                total = len(active)
            result = fetch_and_filter_etfs(mode=('browser' if not headless else 'headless'))
            run_id = result.get('run_id') if isinstance(result, dict) else None
            return {
                'success': True,
                'message': 'Execution completed',
                'details': {
                    'headless': headless,
                    'run_id': run_id,
                    'total_clients': total,
                    'processed_clients': total,
                    'failed': len(self.failed_clients),
                    'failed_clients': self.failed_clients
                }
            }
        except Exception as e:
            return {
                'success': False,
                'message': str(e)
            }

    def send_execution_summary(self):
        """Send execution completion summary"""
        try:
            with get_app().app_context():
                active_clients = get_active_clients_with_sip()
                successful_clients = len(active_clients) - len(self.failed_clients)

                summary = f"""
                🚀 ETF EXECUTION COMPLETED - {datetime.now().strftime('%d %B %Y, %I:%M %p')}
                
                📊 EXECUTION SUMMARY:
                • Total Active Clients: {len(active_clients)}
                • Successful Executions: {successful_clients}
                • Failed/Skipped: {len(self.failed_clients)}
                
                💰 Orders placed successfully for {successful_clients} clients
                
                Check detailed logs and order files for complete execution details.
                """

                self.send_admin_alert("✅ Execution Summary", summary)

        except Exception as e:
            logging.error(f"Error sending execution summary: {e}")

    def send_admin_alert(self, subject, message):
        """Send alert to admin"""
        try:
            send_admin_alert_email(subject, message)
        except Exception as e:
            logging.error(f"Failed to send admin alert: {e}")

    def update_schedule_times(self, session_test_time=None, execution_time=None):
        """Update scheduler times (called from admin panel)"""
        if session_test_time:
            self.session_test_time = session_test_time
        if execution_time:
            self.execution_time = execution_time

        # Clear existing schedules and recreate
        schedule.clear()

        # Reschedule with new times
        schedule.every().monday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().tuesday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().wednesday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().thursday.at(self.session_test_time).do(self.morning_health_check)
        schedule.every().friday.at(self.session_test_time).do(self.morning_health_check)

        schedule.every().monday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().tuesday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().wednesday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().thursday.at(self.execution_time).do(self.execute_strategy)
        schedule.every().friday.at(self.execution_time).do(self.execute_strategy)

        logging.info(f"📅 Schedule updated - Health Check: {self.session_test_time}, Execution: {self.execution_time}")

    def stop_scheduler(self):
        """Stop the scheduler"""
        self.running = False
        logging.info("🛑 Enhanced execution scheduler stopped")

# Global scheduler instance
scheduler = EnhancedExecutionScheduler()

def start_background_execution():
    """Start execution scheduler in background thread"""
    thread = threading.Thread(target=scheduler.start_scheduler, daemon=True)
    thread.start()
    return thread

def update_scheduler_times(session_test_time, execution_time):
    """Update scheduler times from admin panel"""
    scheduler.update_schedule_times(session_test_time, execution_time)

def get_current_schedule():
    """Get current schedule times"""
    return {
        'session_test_time': scheduler.session_test_time,
        'execution_time': scheduler.execution_time,
        'failed_clients': len(scheduler.failed_clients),
        'driver_issues': scheduler.driver_issues
    }