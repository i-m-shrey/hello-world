"""
Simplified Admin Controller for Testing Admin Panel Buttons
This version has minimal dependencies and focuses on admin panel functionality
"""

import sys
import os
import logging
import json
from datetime import datetime
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleAdminController:
    """
    Simplified controller for admin panel testing
    Provides mock/basic implementations of all admin functions
    """
    
    def __init__(self, admin_email="admin@smartetf.com"):
        self.admin_email = admin_email
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
        
    def test_database_connection(self):
        """Test database connection (simplified)"""
        try:
            # Try to import database components
            sys.path.append(os.path.dirname(os.path.dirname(__file__)))
            from client_fetcher import get_active_clients_with_sip
            
            # Test database connection
            clients = get_active_clients_with_sip()
            client_count = len(clients) if clients else 0
            
            self.log_operation("Database Test", "success", f"Found {client_count} active clients")
            
            return {
                'success': True,
                'message': f'Database connection successful. Found {client_count} active clients.',
                'data': {
                    'client_count': client_count,
                    'test_time': datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            error_msg = f"Database connection failed: {str(e)}"
            self.log_operation("Database Test", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def run_session_health_check(self):
        """Run session health check (simplified)"""
        try:
            # Mock session check
            mock_results = {
                'finvasia_clients': 5,
                'upstox_clients': 2,
                'dhan_clients': 1,
                'successful_sessions': 7,
                'failed_sessions': 1
            }
            
            self.log_operation("Session Health Check", "success", f"Checked {mock_results['successful_sessions'] + mock_results['failed_sessions']} clients")
            
            return {
                'success': True,
                'message': f'Session health check completed. {mock_results["successful_sessions"]} successful, {mock_results["failed_sessions"]} failed.',
                'data': mock_results
            }
            
        except Exception as e:
            error_msg = f"Session health check failed: {str(e)}"
            self.log_operation("Session Health Check", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def test_etf_data_fetching(self):
        """Test ETF data fetching (simplified)"""
        try:
            # Try to import and test ETF fetching
            from .fetch_etf_data import fetch_etf_data_with_fallback
            
            # Test ETF data fetch with timeout
            etf_data = fetch_etf_data_with_fallback()
            
            if etf_data is not None and len(etf_data) > 0:
                self.log_operation("ETF Data Fetch", "success", f"Fetched {len(etf_data)} ETFs")
                
                return {
                    'success': True,
                    'message': f'ETF data fetched successfully. Found {len(etf_data)} ETFs.',
                    'data': {
                        'etf_count': len(etf_data),
                        'columns': list(etf_data.columns) if hasattr(etf_data, 'columns') else [],
                        'test_time': datetime.now().isoformat()
                    }
                }
            else:
                self.log_operation("ETF Data Fetch", "failed", "No ETF data received")
                
                return {
                    'success': False,
                    'message': 'ETF data fetch failed - no data received',
                    'data': {'error': 'Empty dataset'}
                }
                
        except Exception as e:
            error_msg = f"ETF data fetch failed: {str(e)}"
            self.log_operation("ETF Data Fetch", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def test_chrome_driver(self):
        """Test Chrome driver (simplified)"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            
            # Test ChromeDriver installation and version
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Test basic functionality
            driver.get("https://www.google.com")
            title = driver.title
            driver.quit()
            
            self.log_operation("Chrome Driver Test", "success", f"Driver working, tested on: {title}")
            
            return {
                'success': True,
                'message': f'Chrome driver test successful. Page title: {title}',
                'data': {
                    'page_title': title,
                    'test_time': datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            error_msg = f"Chrome driver test failed: {str(e)}"
            self.log_operation("Chrome Driver Test", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def run_complete_morning_health_check(self):
        """Run complete morning health check"""
        try:
            results = {
                'database': self.test_database_connection(),
                'sessions': self.run_session_health_check(),
                'etf_fetch': self.test_etf_data_fetching(),
                'chrome_driver': self.test_chrome_driver()
            }
            
            # Count successes
            successful_tests = sum(1 for r in results.values() if r['success'])
            total_tests = len(results)
            
            # Send email notification
            email_result = self.send_test_alert()
            
            self.log_operation("Complete Health Check", "success", f"{successful_tests}/{total_tests} tests passed")
            
            return {
                'success': successful_tests > total_tests // 2,  # More than half successful
                'message': f'Complete health check finished. {successful_tests}/{total_tests} tests passed.',
                'data': {
                    'test_results': results,
                    'email_sent': email_result['success'],
                    'summary': f"{successful_tests}/{total_tests} tests passed"
                }
            }
            
        except Exception as e:
            error_msg = f"Complete health check failed: {str(e)}"
            self.log_operation("Complete Health Check", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def execute_strategy_now(self):
        """Execute complete ETF strategy (mock for testing)"""
        try:
            # Mock strategy execution
            mock_execution_results = {
                'clients_processed': 8,
                'orders_placed': 24,
                'successful_orders': 22,
                'failed_orders': 2,
                'total_investment': 150000
            }
            
            self.log_operation("Strategy Execution", "success", f"Processed {mock_execution_results['clients_processed']} clients")
            
            return {
                'success': True,
                'message': f'Strategy execution completed. {mock_execution_results["successful_orders"]}/{mock_execution_results["orders_placed"]} orders successful.',
                'data': mock_execution_results
            }
            
        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            self.log_operation("Strategy Execution", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def send_test_alert(self):
        """Send test alert email"""
        try:
            # Try to send actual email
            sys.path.append(os.path.dirname(os.path.dirname(__file__)))
            from email_notifications import send_email
            
            subject = "SmartETF Admin Panel Test Alert"
            body = f"""
            This is a test alert from SmartETF Admin Panel.
            
            Test Details:
            - Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            - System: Admin Panel Test
            - Status: Alert system working correctly
            
            This confirms that email notifications are functioning properly.
            """
            
            result = send_email(self.admin_email, subject, body)
            
            self.log_operation("Test Alert", "success", f"Email sent to {self.admin_email}")
            
            return {
                'success': True,
                'message': f'Test alert email sent successfully to {self.admin_email}',
                'data': {
                    'recipient': self.admin_email,
                    'subject': subject,
                    'sent_time': datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            error_msg = f"Test alert failed: {str(e)}"
            self.log_operation("Test Alert", "failed", error_msg)
            
            return {
                'success': False,
                'message': error_msg,
                'data': {'error': str(e)}
            }
    
    def get_system_status(self):
        """Get current system status"""
        try:
            # Mock system status
            status = {
                'system_healthy': True,
                'database_connected': True,
                'active_clients': 8,
                'failed_clients': 1,
                'driver_issues': False,
                'last_health_check': datetime.now().isoformat(),
                'uptime': '2 days, 14 hours'
            }
            
            return {
                'success': True,
                'message': 'System status retrieved successfully',
                'data': status
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to get system status: {str(e)}',
                'data': {'error': str(e)}
            }
    
    def get_execution_log(self):
        """Get execution log"""
        try:
            return {
                'success': True,
                'message': f'Retrieved {len(self.execution_log)} log entries',
                'data': self.execution_log[-20:]  # Last 20 entries
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to get execution log: {str(e)}',
                'data': {'error': str(e)}
            }

# Create global controller instance
controller = SimpleAdminController()

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

if __name__ == "__main__":
    # Test all functions if run directly
    print("🧪 Testing Simple Admin Controller")
    print("=" * 40)
    
    functions = [
        ("Database Test", admin_test_database),
        ("Health Check", admin_run_health_check),
        ("ETF Fetch Test", admin_test_etf_fetch),
        ("Chrome Driver Test", admin_test_chrome_driver),
        ("Complete Health Check", admin_run_morning_health),
        ("Strategy Execution", admin_execute_strategy),
        ("Send Test Alert", admin_send_test_alert),
        ("System Status", admin_get_system_status),
        ("Execution Log", admin_get_execution_log)
    ]
    
    for name, func in functions:
        try:
            result = func()
            status = "✅ PASS" if result['success'] else "❌ FAIL"
            print(f"{status} {name}: {result['message']}")
        except Exception as e:
            print(f"❌ ERROR {name}: {str(e)}")
    
    print("\n🎉 Simple Admin Controller test complete!")