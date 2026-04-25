"""
Minimal Mock Admin Controller - Guaranteed to Work
Returns mock data for all admin functions without any external dependencies
"""

import json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MockAdminController:
    """
    Mock controller that returns realistic test data
    No external dependencies - guaranteed to work
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

def admin_test_database():
    """Test database connection - MOCK VERSION"""
    try:
        # Mock successful database test
        mock_data = {
            'client_count': 8,
            'active_subscriptions': 6,
            'connection_time': '0.045 seconds',
            'test_time': datetime.now().isoformat()
        }
        
        return {
            'success': True,
            'message': 'Database connection successful! Found 8 active clients with valid subscriptions.',
            'data': mock_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Database test failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_run_health_check():
    """Session health check - MOCK VERSION"""
    try:
        # Mock session health check results
        mock_results = {
            'finvasia_clients': 5,
            'upstox_clients': 2, 
            'dhan_clients': 1,
            'successful_sessions': 7,
            'failed_sessions': 1,
            'session_details': {
                'client_001': 'Active',
                'client_002': 'Active',
                'client_003': 'Session Expired',
                'client_004': 'Active',
                'client_005': 'Active',
                'client_006': 'Active',
                'client_007': 'Active',
                'client_008': 'Active'
            }
        }
        
        return {
            'success': True,
            'message': f'Session health check completed. {mock_results["successful_sessions"]} successful, {mock_results["failed_sessions"]} failed.',
            'data': mock_results
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Session health check failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_test_etf_fetch():
    """ETF data fetching test - MOCK VERSION"""
    try:
        # Mock ETF fetch results
        mock_etf_data = {
            'etf_count': 25,
            'data_source': 'NSE India',
            'fetch_time': '2.3 seconds',
            'sample_etfs': [
                {'symbol': 'NIFTYBEES', 'price': 185.50, 'change': -2.1},
                {'symbol': 'JUNIORBEES', 'price': 425.80, 'change': -1.8},
                {'symbol': 'BANKBEES', 'price': 445.25, 'change': -3.2}
            ],
            'filters_applied': {
                'min_volume': 10000,
                'price_drop_threshold': 2.0,
                'market_cap_filter': True
            }
        }
        
        return {
            'success': True,
            'message': f'ETF data fetched successfully! Found {mock_etf_data["etf_count"]} ETFs meeting criteria.',
            'data': mock_etf_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'ETF data fetch failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_test_chrome_driver():
    """Chrome driver test - MOCK VERSION"""
    try:
        # Mock chrome driver test
        mock_driver_data = {
            'driver_version': 'ChromeDriver 127.0.6533.88',
            'chrome_version': 'Chrome 127.0.6533.88',
            'test_url': 'https://www.nseindia.com',
            'response_time': '1.2 seconds',
            'status': 'Driver working correctly'
        }
        
        return {
            'success': True,
            'message': 'Chrome driver test successful! Driver is up-to-date and functional.',
            'data': mock_driver_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Chrome driver test failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_run_morning_health():
    """Complete morning health check - MOCK VERSION"""
    try:
        # Run all individual tests
        db_result = admin_test_database()
        session_result = admin_run_health_check()
        etf_result = admin_test_etf_fetch()
        driver_result = admin_test_chrome_driver()
        
        # Count successes
        results = [db_result, session_result, etf_result, driver_result]
        successful_tests = sum(1 for r in results if r['success'])
        total_tests = len(results)
        
        mock_health_data = {
            'database_test': db_result['success'],
            'session_test': session_result['success'],
            'etf_fetch_test': etf_result['success'],
            'driver_test': driver_result['success'],
            'overall_health': successful_tests / total_tests * 100,
            'email_notification': 'Sent to admin@smartetf.com',
            'test_summary': f'{successful_tests}/{total_tests} tests passed'
        }
        
        return {
            'success': successful_tests > total_tests // 2,
            'message': f'Complete health check finished. {successful_tests}/{total_tests} tests passed. System health: {mock_health_data["overall_health"]:.0f}%',
            'data': mock_health_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Complete health check failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_execute_strategy():
    """Execute strategy - MOCK VERSION"""
    try:
        # Mock strategy execution
        mock_execution = {
            'clients_processed': 8,
            'orders_generated': 24,
            'successful_orders': 22,
            'failed_orders': 2,
            'total_investment': 156750.00,
            'execution_time': '45.2 seconds',
            'order_details': [
                {'client': 'Client_001', 'etf': 'NIFTYBEES', 'quantity': 50, 'status': 'Success'},
                {'client': 'Client_002', 'etf': 'BANKBEES', 'quantity': 25, 'status': 'Success'},
                {'client': 'Client_003', 'etf': 'JUNIORBEES', 'quantity': 30, 'status': 'Failed - Insufficient Balance'}
            ]
        }
        
        return {
            'success': True,
            'message': f'Strategy execution completed! {mock_execution["successful_orders"]}/{mock_execution["orders_generated"]} orders successful. Total investment: ₹{mock_execution["total_investment"]:,.2f}',
            'data': mock_execution
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Strategy execution failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_send_test_alert():
    """Send test alert - MOCK VERSION"""
    try:
        mock_email_data = {
            'recipient': 'admin@smartetf.com',
            'subject': 'SmartETF Test Alert - System Functional',
            'sent_time': datetime.now().isoformat(),
            'email_provider': 'SMTP Gmail',
            'delivery_status': 'Delivered'
        }
        
        return {
            'success': True,
            'message': f'Test alert email sent successfully to {mock_email_data["recipient"]}. Check your inbox for confirmation.',
            'data': mock_email_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Test alert failed: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_get_system_status():
    """Get system status - MOCK VERSION"""
    try:
        mock_status = {
            'system_healthy': True,
            'database_connected': True,
            'active_clients': 8,
            'failed_clients': 1,
            'driver_issues': False,
            'last_health_check': datetime.now().isoformat(),
            'uptime': '2 days, 14 hours',
            'memory_usage': '245 MB',
            'cpu_usage': '12%'
        }
        
        return {
            'success': True,
            'message': 'System status retrieved successfully',
            'data': mock_status
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to get system status: {str(e)}',
            'data': {'error': str(e)}
        }

def admin_get_execution_log():
    """Get execution log - MOCK VERSION"""
    try:
        mock_log = [
            {
                'timestamp': '2025-08-23T15:10:00',
                'operation': 'Strategy Execution',
                'status': 'success',
                'details': '22/24 orders successful'
            },
            {
                'timestamp': '2025-08-23T10:30:00',
                'operation': 'Health Check',
                'status': 'success', 
                'details': '7/8 clients active'
            },
            {
                'timestamp': '2025-08-22T15:10:00',
                'operation': 'Strategy Execution',
                'status': 'success',
                'details': '20/21 orders successful'
            }
        ]
        
        return {
            'success': True,
            'message': f'Retrieved {len(mock_log)} log entries',
            'data': mock_log
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to get execution log: {str(e)}',
            'data': {'error': str(e)}
        }

if __name__ == "__main__":
    # Test all functions
    print("🧪 Testing Mock Admin Controller")
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
            print(f"{status} {name}: {result['message'][:80]}...")
        except Exception as e:
            print(f"❌ ERROR {name}: {str(e)}")
    
    print("\n🎉 Mock Admin Controller test complete!")