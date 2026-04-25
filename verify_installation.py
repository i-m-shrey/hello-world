#!/usr/bin/env python3
"""
SmartETF Enhanced Scheduler - Installation Verification Script
Run this after installing the updated files to verify everything is working.
"""

import sys
import os
import traceback

def test_imports():
    """Test that all required modules can be imported"""
    print("🔍 Testing Imports...")
    
    try:
        # Test Flask and SQLAlchemy
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        print("  ✅ Flask and SQLAlchemy")
        
        # Test enhanced scheduler
        sys.path.append(os.path.dirname(__file__))
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        print("  ✅ Enhanced Execution Scheduler")
        
        # Test email notifications
        from email_notifications import send_admin_alert_email, send_client_notification_email
        print("  ✅ Enhanced Email Notifications")
        
        # Test models
        from models import SchedulerSettings, User, Broker
        print("  ✅ Database Models (including SchedulerSettings)")
        
        # Test schedule package
        import schedule
        print("  ✅ Schedule package")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Import Error: {str(e)}")
        print(f"     {traceback.format_exc()}")
        return False

def test_database():
    """Test database connection and scheduler settings"""
    print("\n🗄️ Testing Database...")
    
    try:
        from app import app, db
        from models import SchedulerSettings
        
        with app.app_context():
            # Test database connection
            db.engine.execute('SELECT 1')
            print("  ✅ Database connection")
            
            # Test SchedulerSettings table
            settings = SchedulerSettings.query.first()
            if settings:
                print(f"  ✅ SchedulerSettings found (Health: {settings.session_test_time}, Execution: {settings.execution_time})")
            else:
                print("  ⚠️ No SchedulerSettings found - will create defaults")
                settings = SchedulerSettings()
                db.session.add(settings)
                db.session.commit()
                print("  ✅ Default SchedulerSettings created")
            
            return True
            
    except Exception as e:
        print(f"  ❌ Database Error: {str(e)}")
        return False

def test_file_structure():
    """Test that all required files are in place"""
    print("\n📁 Testing File Structure...")
    
    required_files = [
        'app.py',
        'models.py', 
        'email_notifications.py',
        'requirements.txt',
        'templates/admin/dashboard.html',
        'templates/admin/scheduler_management.html',
        'templates/admin/broker_passwords.html',
        'strategy_runner/execution_scheduler.py'
    ]
    
    all_files_exist = True
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ MISSING: {file_path}")
            all_files_exist = False
    
    return all_files_exist

def test_scheduler_functionality():
    """Test scheduler initialization"""
    print("\n⚙️ Testing Scheduler Functionality...")
    
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        
        scheduler = EnhancedExecutionScheduler()
        print("  ✅ Scheduler initialization")
        
        # Test scheduler methods exist
        if hasattr(scheduler, 'morning_health_check'):
            print("  ✅ Health check method available")
        else:
            print("  ❌ Health check method missing")
            return False
            
        if hasattr(scheduler, 'execute_strategy'):
            print("  ✅ Strategy execution method available")
        else:
            print("  ❌ Strategy execution method missing")
            return False
            
        if hasattr(scheduler, 'check_and_update_driver'):
            print("  ✅ Driver update method available")
        else:
            print("  ❌ Driver update method missing")
            return False
            
        return True
        
    except Exception as e:
        print(f"  ❌ Scheduler Error: {str(e)}")
        return False

def test_routes():
    """Test that Flask routes are accessible"""
    print("\n🌐 Testing Flask Routes...")
    
    try:
        from app import app
        
        with app.test_client() as client:
            # Test scheduler management route exists
            response = client.get('/admin/scheduler')
            if response.status_code in [200, 302]:  # 302 = redirect to login
                print("  ✅ /admin/scheduler route exists")
            else:
                print(f"  ❌ /admin/scheduler route error: {response.status_code}")
                return False
            
            # Test broker passwords route exists  
            response = client.get('/admin/broker-passwords')
            if response.status_code in [200, 302]:
                print("  ✅ /admin/broker-passwords route exists")
            else:
                print(f"  ❌ /admin/broker-passwords route error: {response.status_code}")
                return False
                
            # Test scheduler status API route
            response = client.get('/admin/scheduler/status')
            if response.status_code in [200, 302]:
                print("  ✅ /admin/scheduler/status route exists")
            else:
                print(f"  ❌ /admin/scheduler/status route error: {response.status_code}")
                return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ Route Error: {str(e)}")
        return False

def main():
    """Run all verification tests"""
    print("🧪 SmartETF Enhanced Scheduler - Installation Verification")
    print("=" * 60)
    
    tests = [
        ("File Structure", test_file_structure),
        ("Imports", test_imports), 
        ("Database", test_database),
        ("Scheduler", test_scheduler_functionality),
        ("Flask Routes", test_routes)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"\n❌ {test_name} test failed with exception: {str(e)}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 60)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✅ PASS" if passed_test else "❌ FAIL"
        print(f"{test_name:<20} {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 SUCCESS! All tests passed.")
        print("🚀 Your SmartETF Enhanced Scheduler is ready to use!")
        print("\nNext steps:")
        print("1. Start Flask: python app.py")
        print("2. Open browser: http://127.0.0.1:8080")
        print("3. Login as admin and test the scheduler features")
        return True
    else:
        print(f"\n⚠️ {total - passed} test(s) failed.")
        print("Please check the errors above and ensure all files are properly installed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)