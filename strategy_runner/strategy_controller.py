"""
SmartETF Strategy Controller - Unified interface for all strategy operations
Exposes both individual functions and complete execution flow
Perfect for admin panel integration and independent testing
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from session_manager import MultibrokerSessionManager
from morning_health_check import MorningHealthChecker
from order_executor import MultibrokerOrderExecutor
from fetch_etf_data import fetch_etf_data_with_fallback
from filter_etfs import filter_etfs_for_today
from client_fetcher import get_active_clients_with_sip
from email_notifications import send_email
import logging
import json
from datetime import datetime
import traceback
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SmartETFController:
    """
    Unified controller for all SmartETF operations
    - Individual function calls for admin panel
    - Complete strategy execution
    - Error handling and reporting
    - Status tracking and notifications
    """
    
    def __init__(self, admin_email="admin@smartetf.com"):
        self.admin_email = admin_email
        self.session_manager = None
        self.health_checker = None
        self.order_executor = None
        self.execution_log = []
        
    def log_operation(self, operation, status, details):
        """Log operation with timestamp"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'status': status,
            'details': details
        }
        self.execution_log.append(log_entry)
        logging.info(f"{operation}: {status} - {details}")
        return log_entry

    # ===== INDIVIDUAL FUNCTIONS FOR ADMIN PANEL =====
    
    def test_database_connection(self):
        """Test database connection and client loading"""
        try:
            self.log_operation("DATABASE_TEST", "STARTED", "Testing database connection")
            
            clients = get_active_clients_with_sip()
            
            if not clients or len(clients) == 0:
                return {
                    'success': False,
                    'message': 'No active clients found in database',
                    'data': {'client_count': 0}
                }
            
            # Analyze client distribution
            broker_counts = {}
            for client in clients:
                broker = client.get('broker_name', 'Unknown')
                broker_counts[broker] = broker_counts.get(broker, 0) + 1
            
            result = {
                'success': True,
                'message': f'Successfully loaded {len(clients)} active clients',
                'data': {
                    'client_count': len(clients),
                    'broker_distribution': broker_counts,
                    'sample_clients': [
                        {
                            'user_id': client.get('user_id', 'N/A'),
                            'broker': client.get('broker_name', 'Unknown'),
                            'status': 'Active'
                        }
                        for client in clients[:3]
                    ]
                }
            }
            
            self.log_operation("DATABASE_TEST", "SUCCESS", f"Loaded {len(clients)} clients")
            return result
            
        except Exception as e:
            error_msg = f"Database connection failed: {str(e)}"
            self.log_operation("DATABASE_TEST", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def run_session_health_check(self):
        """Test session maintenance for all clients"""
        try:
            self.log_operation("SESSION_HEALTH", "STARTED", "Testing client sessions")
            
            if not self.session_manager:
                self.session_manager = MultibrokerSessionManager()
            
            # Load and test all client sessions
            self.session_manager.load_all_clients()
            
            # Get session statistics
            stats = self.session_manager.session_stats
            failed_sessions = self.session_manager.failed_sessions
            
            result = {
                'success': True,
                'message': f'Session check complete: {stats["successful_sessions"]}/{stats["total_clients"]} successful',
                'data': {
                    'total_clients': stats['total_clients'],
                    'successful_sessions': stats['successful_sessions'],
                    'failed_sessions': stats['failed_sessions'],
                    'success_rate': f"{(stats['successful_sessions']/stats['total_clients']*100):.1f}%" if stats['total_clients'] > 0 else "0%",
                    'failed_details': [
                        {
                            'client_id': client_id,
                            'error': error_info.get('error', 'Unknown error'),
                            'broker': error_info.get('broker', 'Unknown')
                        }
                        for client_id, error_info in failed_sessions.items()
                    ][:5]  # Show first 5 failures
                }
            }
            
            self.log_operation("SESSION_HEALTH", "SUCCESS", f"Sessions tested: {stats['successful_sessions']}/{stats['total_clients']}")
            return result
            
        except Exception as e:
            error_msg = f"Session health check failed: {str(e)}"
            self.log_operation("SESSION_HEALTH", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def test_etf_data_fetching(self):
        """Test ETF data fetching capability"""
        try:
            self.log_operation("ETF_FETCH_TEST", "STARTED", "Testing ETF data fetching")
            
            # Test ETF data fetching with timeout handling
            etf_data = fetch_etf_data_with_fallback()
            
            if etf_data is None or len(etf_data) == 0:
                return {
                    'success': False,
                    'message': 'ETF data fetching returned empty result',
                    'data': {'etf_count': 0}
                }
            
            # Get sample ETF data
            sample_etfs = []
            if hasattr(etf_data, 'head'):  # DataFrame
                sample_etfs = etf_data.head(5).to_dict('records')
            elif isinstance(etf_data, list):
                sample_etfs = etf_data[:5]
            
            result = {
                'success': True,
                'message': f'Successfully fetched {len(etf_data)} ETFs',
                'data': {
                    'etf_count': len(etf_data),
                    'sample_etfs': sample_etfs,
                    'fetch_time': datetime.now().isoformat()
                }
            }
            
            self.log_operation("ETF_FETCH_TEST", "SUCCESS", f"Fetched {len(etf_data)} ETFs")
            return result
            
        except Exception as e:
            error_msg = f"ETF data fetching failed: {str(e)}"
            self.log_operation("ETF_FETCH_TEST", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def test_chrome_driver(self):
        """Test Chrome driver functionality"""
        try:
            self.log_operation("CHROME_DRIVER_TEST", "STARTED", "Testing Chrome driver")
            
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            
            # Test Chrome driver setup
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            
            # Try to create driver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Test basic functionality
            driver.get("https://www.google.com")
            title = driver.title
            driver.quit()
            
            result = {
                'success': True,
                'message': 'Chrome driver is working properly',
                'data': {
                    'driver_status': 'Working',
                    'test_url': 'https://www.google.com',
                    'test_result': f'Page title: {title}',
                    'test_time': datetime.now().isoformat()
                }
            }
            
            self.log_operation("CHROME_DRIVER_TEST", "SUCCESS", "Chrome driver working")
            return result
            
        except Exception as e:
            error_msg = f"Chrome driver test failed: {str(e)}"
            self.log_operation("CHROME_DRIVER_TEST", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def run_complete_morning_health_check(self):
        """Run complete morning health check with email report"""
        try:
            self.log_operation("MORNING_HEALTH", "STARTED", "Running complete morning health check")
            
            if not self.health_checker:
                self.health_checker = MorningHealthChecker(self.admin_email)
            
            # Run complete health check
            health_report = self.health_checker.run_complete_health_check()
            
            # Save health report
            report_filename = f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            report_path = os.path.join(os.path.dirname(__file__), 'daily_reports', report_filename)
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            
            with open(report_path, 'w') as f:
                json.dump(health_report, f, indent=2, default=str)
            
            result = {
                'success': True,
                'message': f'Morning health check complete - Status: {health_report["overall_status"]}',
                'data': {
                    'overall_status': health_report['overall_status'],
                    'critical_issues_count': len(health_report['critical_issues']),
                    'warnings_count': len(health_report['warnings']),
                    'report_file': report_path,
                    'email_sent': health_report.get('email_sent', False),
                    'critical_issues': health_report['critical_issues'][:3],  # First 3 issues
                    'recommendations': health_report['recommendations'][:3]  # First 3 recommendations
                }
            }
            
            self.log_operation("MORNING_HEALTH", "SUCCESS", f"Health check complete - {health_report['overall_status']}")
            return result
            
        except Exception as e:
            error_msg = f"Morning health check failed: {str(e)}"
            self.log_operation("MORNING_HEALTH", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def execute_strategy_now(self):
        """Execute complete ETF strategy (fetch data, filter, place orders)"""
        try:
            self.log_operation("STRATEGY_EXECUTION", "STARTED", "Starting complete ETF strategy execution")
            
            execution_results = {
                'etf_data_fetch': None,
                'etf_filtering': None,
                'session_management': None,
                'order_execution': None
            }
            
            # Step 1: Fetch ETF Data
            self.log_operation("STRATEGY_EXECUTION", "PROGRESS", "Step 1: Fetching ETF data")
            etf_data = fetch_etf_data_with_fallback()
            if etf_data is None or len(etf_data) == 0:
                raise Exception("Failed to fetch ETF data")
            execution_results['etf_data_fetch'] = {
                'success': True,
                'etf_count': len(etf_data)
            }
            
            # Step 2: Filter ETFs
            self.log_operation("STRATEGY_EXECUTION", "PROGRESS", "Step 2: Filtering ETFs for today")
            filtered_etfs = filter_etfs_for_today(etf_data)
            if filtered_etfs is None or len(filtered_etfs) == 0:
                raise Exception("No ETFs to trade today")
            execution_results['etf_filtering'] = {
                'success': True,
                'filtered_count': len(filtered_etfs)
            }
            
            # Step 3: Session Management
            self.log_operation("STRATEGY_EXECUTION", "PROGRESS", "Step 3: Managing client sessions")
            if not self.session_manager:
                self.session_manager = MultibrokerSessionManager()
            self.session_manager.load_all_clients()
            
            if self.session_manager.session_stats['successful_sessions'] == 0:
                raise Exception("No successful client sessions available")
            execution_results['session_management'] = {
                'success': True,
                'successful_sessions': self.session_manager.session_stats['successful_sessions'],
                'total_clients': self.session_manager.session_stats['total_clients']
            }
            
            # Step 4: Execute Orders
            self.log_operation("STRATEGY_EXECUTION", "PROGRESS", "Step 4: Executing orders")
            if not self.order_executor:
                self.order_executor = MultibrokerOrderExecutor()
            
            order_results = self.order_executor.execute_orders_for_etfs(
                etf_data=filtered_etfs,
                session_manager=self.session_manager
            )
            execution_results['order_execution'] = order_results
            
            # Generate summary
            total_orders = order_results.get('total_orders', 0)
            successful_orders = order_results.get('successful_orders', 0)
            
            result = {
                'success': True,
                'message': f'Strategy execution complete: {successful_orders}/{total_orders} orders successful',
                'data': {
                    'execution_time': datetime.now().isoformat(),
                    'total_orders': total_orders,
                    'successful_orders': successful_orders,
                    'success_rate': f"{(successful_orders/total_orders*100):.1f}%" if total_orders > 0 else "0%",
                    'details': execution_results
                }
            }
            
            self.log_operation("STRATEGY_EXECUTION", "SUCCESS", f"Strategy complete: {successful_orders}/{total_orders} orders")
            return result
            
        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            self.log_operation("STRATEGY_EXECUTION", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e), 'traceback': traceback.format_exc()}
            }

    def send_test_alert(self, message="Test alert from SmartETF Admin Panel"):
        """Send test email alert to admin"""
        try:
            self.log_operation("TEST_ALERT", "STARTED", "Sending test alert email")
            
            email_subject = "🧪 SmartETF Test Alert"
            email_body = f"""
            <h2>SmartETF Test Alert</h2>
            <p><strong>Message:</strong> {message}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Source:</strong> Admin Panel Manual Trigger</p>
            <hr>
            <p>This is a test alert to verify the email notification system is working properly.</p>
            """
            
            # Send email
            email_sent = send_email(
                to_email=self.admin_email,
                subject=email_subject,
                html_body=email_body
            )
            
            if email_sent:
                result = {
                    'success': True,
                    'message': f'Test alert sent successfully to {self.admin_email}',
                    'data': {
                        'recipient': self.admin_email,
                        'subject': email_subject,
                        'sent_time': datetime.now().isoformat()
                    }
                }
                self.log_operation("TEST_ALERT", "SUCCESS", f"Email sent to {self.admin_email}")
            else:
                result = {
                    'success': False,
                    'message': 'Failed to send test alert email',
                    'data': {'recipient': self.admin_email}
                }
                self.log_operation("TEST_ALERT", "FAILED", "Email sending failed")
            
            return result
            
        except Exception as e:
            error_msg = f"Test alert failed: {str(e)}"
            self.log_operation("TEST_ALERT", "FAILED", error_msg)
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }

    def get_execution_log(self, limit=50):
        """Get recent execution log"""
        return {
            'success': True,
            'message': f'Retrieved {len(self.execution_log)} log entries',
            'data': {
                'log_entries': self.execution_log[-limit:],
                'total_entries': len(self.execution_log)
            }
        }

    def get_system_status(self):
        """Get current system status summary"""
        try:
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'session_manager_initialized': self.session_manager is not None,
                'health_checker_initialized': self.health_checker is not None,
                'order_executor_initialized': self.order_executor is not None,
                'recent_operations': len([log for log in self.execution_log if 
                                        datetime.fromisoformat(log['timestamp']) > 
                                        datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)])
            }
            
            if self.session_manager:
                status_data['session_stats'] = self.session_manager.session_stats
            
            return {
                'success': True,
                'message': 'System status retrieved',
                'data': status_data
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to get system status: {str(e)}',
                'data': {'error': str(e)}
            }


# Global controller instance for admin panel
controller = SmartETFController()

# ===== ADMIN PANEL INTEGRATION FUNCTIONS =====

def admin_test_database():
    """Admin panel function: Test database connection"""
    return controller.test_database_connection()

def admin_run_health_check():
    """Admin panel function: Run health check"""
    return controller.run_session_health_check()

def admin_test_etf_fetch():
    """Admin panel function: Test ETF data fetching"""
    return controller.test_etf_data_fetching()

def admin_test_chrome_driver():
    """Admin panel function: Test Chrome driver"""
    return controller.test_chrome_driver()

def admin_run_morning_health():
    """Admin panel function: Run complete morning health check"""
    return controller.run_complete_morning_health_check()

def admin_execute_strategy():
    """Admin panel function: Execute complete ETF strategy"""
    return controller.execute_strategy_now()

def admin_send_test_alert():
    """Admin panel function: Send test alert"""
    return controller.send_test_alert()

def admin_get_system_status():
    """Admin panel function: Get system status"""
    return controller.get_system_status()

def admin_get_execution_log():
    """Admin panel function: Get execution log"""
    return controller.get_execution_log()


# ===== STANDALONE EXECUTION =====

if __name__ == "__main__":
    print("🎛️ SmartETF Strategy Controller")
    print("=" * 50)
    print("Available operations:")
    print("1. Test Database Connection")
    print("2. Run Session Health Check")
    print("3. Test ETF Data Fetching")
    print("4. Test Chrome Driver")
    print("5. Run Complete Morning Health Check")
    print("6. Execute Strategy Now")
    print("7. Send Test Alert")
    print("8. Get System Status")
    print("9. Run All Tests")
    print("0. Exit")
    
    while True:
        try:
            choice = input("\nEnter choice (0-9): ").strip()
            
            if choice == "0":
                print("Goodbye!")
                break
            elif choice == "1":
                result = controller.test_database_connection()
                print(json.dumps(result, indent=2))
            elif choice == "2":
                result = controller.run_session_health_check()
                print(json.dumps(result, indent=2))
            elif choice == "3":
                result = controller.test_etf_data_fetching()
                print(json.dumps(result, indent=2))
            elif choice == "4":
                result = controller.test_chrome_driver()
                print(json.dumps(result, indent=2))
            elif choice == "5":
                result = controller.run_complete_morning_health_check()
                print(json.dumps(result, indent=2))
            elif choice == "6":
                result = controller.execute_strategy_now()
                print(json.dumps(result, indent=2))
            elif choice == "7":
                result = controller.send_test_alert()
                print(json.dumps(result, indent=2))
            elif choice == "8":
                result = controller.get_system_status()
                print(json.dumps(result, indent=2))
            elif choice == "9":
                print("\n🧪 Running all tests...")
                tests = [
                    ("Database Connection", controller.test_database_connection),
                    ("Session Health Check", controller.run_session_health_check),
                    ("ETF Data Fetching", controller.test_etf_data_fetching),
                    ("Chrome Driver", controller.test_chrome_driver),
                ]
                
                for test_name, test_func in tests:
                    print(f"\n--- {test_name} ---")
                    result = test_func()
                    status = "✅ PASS" if result['success'] else "❌ FAIL"
                    print(f"{status}: {result['message']}")
            else:
                print("Invalid choice!")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")