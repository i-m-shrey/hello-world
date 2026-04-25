"""
Morning Health Check System - Daily validation of all systems
1. Session maintenance for every client (find errors, email admin)
2. ETF CSV fetching test (ChromeDriver, network, API issues)
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from session_manager import MultibrokerSessionManager
from email_notifications import send_email, send_admin_alert_email
import logging
from datetime import datetime
import json
import time
import traceback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MorningHealthChecker:
    """
    Daily morning health check system
    - Tests all client sessions across all brokers
    - Validates ETF data fetching capability
    - ChromeDriver health check
    - Sends detailed email reports to admin
    """
    
    def __init__(self, admin_email=None):
        if not admin_email:
            admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartetf.com')
        self.admin_email = admin_email
        self.health_report = {
            'timestamp': datetime.now(),
            'session_check': {},
            'etf_fetch_check': {},
            'chrome_driver_check': {},
            'overall_status': 'UNKNOWN',
            'critical_issues': [],
            'warnings': [],
            'recommendations': []
        }
    
    def run_complete_health_check(self):
        """Run all health checks and generate report"""
        print("🌅 SmartETF Morning Health Check")
        print("=" * 50)
        print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Step 1: Session Health Check
        print("\n1️⃣ CLIENT SESSION HEALTH CHECK")
        print("-" * 30)
        self._check_client_sessions()
        
        # Step 2: ChromeDriver Check (ETF fetch skipped in health)
        print("\n2️⃣ CHROMEDRIVER HEALTH CHECK")
        print("-" * 30)
        self._check_chrome_driver()
        
        # Step 4: Generate Overall Status
        print("\n4️⃣ GENERATING HEALTH REPORT")
        print("-" * 30)
        self._generate_overall_status()
        
        # Step 5: Send Email Report
        self._send_health_report_email()
        
        # Step 6: Save Report
        self._save_health_report()
        
        print("\n✅ Morning health check completed")
        return self.health_report['overall_status'] in ['HEALTHY', 'WARNING']
    
    def _check_client_sessions(self):
        """Check all client sessions across all brokers"""
        print("🔐 Testing client sessions...")
        
        session_manager = MultibrokerSessionManager()
        
        try:
            # Initialize all sessions
            session_success = session_manager.initialize_all_sessions()
            
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
            
            if summary['active_sessions'] == 0:
                self.health_report['critical_issues'].append("No active client sessions")
            elif self.health_report['session_check']['success_rate'] < 80:
                self.health_report['critical_issues'].append(f"Low session success rate: {self.health_report['session_check']['success_rate']:.1f}%")
            
            # Cleanup sessions
            session_manager.cleanup_sessions()
            
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
    
    def _check_etf_data_fetching(self):
        """Check ETF data fetching capability"""
        print("📊 Testing ETF data fetching...")
        
        try:
            start_time = time.time()
            
            # Attempt to fetch ETF data
            etf_file = fetch_etf_data_with_fallback()
            
            fetch_time = time.time() - start_time
            
            if etf_file:
                # Check file size and content
                file_size = os.path.getsize(etf_file) if os.path.exists(etf_file) else 0
                
                self.health_report['etf_fetch_check'] = {
                    'status': 'PASS',
                    'file_name': etf_file,
                    'file_size_bytes': file_size,
                    'fetch_time_seconds': fetch_time,
                    'timestamp': datetime.now()
                }
                
                print(f"  ✅ ETF data fetched successfully")
                print(f"  📄 File: {etf_file}")
                print(f"  📏 Size: {file_size:,} bytes")
                print(f"  ⏱️ Time: {fetch_time:.2f} seconds")
                
                # Check file size
                if file_size < 1000:  # Less than 1KB
                    self.health_report['warnings'].append(f"ETF file unusually small: {file_size} bytes")
                
            else:
                self.health_report['etf_fetch_check'] = {
                    'status': 'FAIL',
                    'error': 'Failed to fetch ETF data',
                    'fetch_time_seconds': fetch_time,
                    'timestamp': datetime.now()
                }
                
                print(f"  ❌ ETF data fetch failed")
                self.health_report['critical_issues'].append("ETF data fetching failed")
                
        except Exception as e:
            print(f"  ❌ ETF fetch error: {e}")
            self.health_report['etf_fetch_check'] = {
                'status': 'ERROR',
                'error': str(e),
                'timestamp': datetime.now()
            }
            self.health_report['critical_issues'].append(f"ETF fetch error: {e}")
    
    def _check_chrome_driver(self):
        """Check ChromeDriver health"""
        print("🌐 Testing ChromeDriver...")
        
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")

            start_time = time.time()

            # Test ChromeDriver
            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://www.google.com")
            title = driver.title
            driver.quit()

            test_time = time.time() - start_time

            self.health_report['chrome_driver_check'] = {
                'status': 'PASS',
                'test_url': 'https://www.google.com',
                'page_title': title,
                'test_time_seconds': test_time,
                'timestamp': datetime.now()
            }

            print(f"  ✅ ChromeDriver working")
            print(f"  🌐 Test page: {title}")
            print(f"  ⏱️ Time: {test_time:.2f} seconds")

            # Check for slow response
            if test_time > 10:
                self.health_report['warnings'].append(f"ChromeDriver slow response: {test_time:.2f} seconds")

        except Exception as e:
            print(f"  ❌ ChromeDriver error: {e}")
            self.health_report['chrome_driver_check'] = {
                'status': 'ERROR',
                'error': str(e),
                'timestamp': datetime.now()
            }
            try:
                send_admin_alert_email("ChromeDriver error", str(e))
            except Exception:
                pass
            # Check for common ChromeDriver issues
            error_str = str(e).lower()
            if 'chromedriver' in error_str:
                self.health_report['critical_issues'].append("ChromeDriver not found or outdated")
                self.health_report['recommendations'].append("Update ChromeDriver: pip install --upgrade webdriver-manager")
            elif 'chrome' in error_str:
                self.health_report['critical_issues'].append("Chrome browser issues")
            else:
                self.health_report['critical_issues'].append(f"ChromeDriver error: {e}")
    
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
CHROMEDRIVER CHECK:
• Status: {report['chrome_driver_check'].get('status', 'N/A')}
"""
        
        if report['chrome_driver_check'].get('page_title'):
            body += f"• Test Result: {report['chrome_driver_check']['page_title']}\n"
            body += f"• Test Time: {report['chrome_driver_check'].get('test_time_seconds', 0):.2f}s\n"
        
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