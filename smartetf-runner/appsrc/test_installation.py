#!/usr/bin/env python3
"""
SmartETF Enhanced Scheduler - Local Testing Script

Run this script after applying the update package to verify everything is working correctly.
"""

import sys
import os
import importlib.util

def test_imports():
    """Test if all required modules can be imported"""
    print("🔍 Testing imports...")
    
    try:
        import schedule
        print("  ✅ schedule module imported successfully")
    except ImportError:
        print("  ❌ schedule module not found. Run: pip install schedule")
        return False
    
    try:
        from models import SchedulerSettings
        print("  ✅ SchedulerSettings model imported successfully")
    except ImportError as e:
        print(f"  ❌ SchedulerSettings model import failed: {e}")
        return False
    
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        print("  ✅ EnhancedExecutionScheduler imported successfully")
    except ImportError as e:
        print(f"  ❌ EnhancedExecutionScheduler import failed: {e}")
        return False
    
    try:
        from email_notifications import send_admin_alert_email
        print("  ✅ Enhanced email functions imported successfully")
    except ImportError as e:
        print(f"  ❌ Enhanced email functions import failed: {e}")
        return False
    
    return True

def test_database():
    """Test database connectivity and SchedulerSettings model"""
    print("\n🗄️ Testing database...")
    
    try:
        from app import app, db
        from models import SchedulerSettings
        
        with app.app_context():
            # Test database connection
            db.create_all()
            print("  ✅ Database connection successful")
            
            # Test SchedulerSettings model
            settings = SchedulerSettings.query.first()
            if not settings:
                settings = SchedulerSettings()
                db.session.add(settings)
                db.session.commit()
                print("  ✅ Created default SchedulerSettings")
            else:
                print("  ✅ SchedulerSettings found in database")
            
            print(f"  📊 Current settings: Test time={settings.session_test_time}, Execution time={settings.execution_time}")
            
    except Exception as e:
        print(f"  ❌ Database test failed: {e}")
        return False
    
    return True

def test_routes():
    """Test if new admin routes are available"""
    print("\n🌐 Testing routes...")
    
    try:
        from app import app
        
        with app.test_client() as client:
            # Test routes exist (will return redirect to login, but that's expected)
            routes_to_test = [
                '/admin/scheduler',
                '/admin/broker-passwords',
                '/admin/scheduler/status'
            ]
            
            for route in routes_to_test:
                response = client.get(route)
                if response.status_code in [200, 302, 401, 403]:  # These are all valid responses
                    print(f"  ✅ Route {route} exists")
                else:
                    print(f"  ❌ Route {route} failed with status {response.status_code}")
                    return False
                    
    except Exception as e:
        print(f"  ❌ Route testing failed: {e}")
        return False
    
    return True

def test_templates():
    """Test if template files exist"""
    print("\n📄 Testing templates...")
    
    templates_to_check = [
        'templates/admin/scheduler_management.html',
        'templates/admin/broker_passwords.html'
    ]
    
    for template in templates_to_check:
        if os.path.exists(template):
            print(f"  ✅ Template {template} exists")
        else:
            print(f"  ❌ Template {template} not found")
            return False
    
    return True

def test_scheduler_functionality():
    """Test basic scheduler functionality"""
    print("\n⏰ Testing scheduler functionality...")
    
    try:
        from app import app
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        
        with app.app_context():
            scheduler = EnhancedExecutionScheduler()
            print("  ✅ EnhancedExecutionScheduler instance created")
            
            # Test that methods exist
            if hasattr(scheduler, 'morning_health_check'):
                print("  ✅ morning_health_check method exists")
            else:
                print("  ❌ morning_health_check method not found")
                return False
            
            if hasattr(scheduler, 'execute_strategy'):
                print("  ✅ execute_strategy method exists")
            else:
                print("  ❌ execute_strategy method not found")
                return False
                
    except Exception as e:
        print(f"  ❌ Scheduler functionality test failed: {e}")
        return False
    
    return True

def main():
    """Main testing function"""
    print("🚀 SmartETF Enhanced Scheduler - Local Testing")
    print("=" * 50)
    
    all_tests_passed = True
    
    # Run all tests
    test_results = [
        test_imports(),
        test_database(),
        test_routes(),
        test_templates(),
        test_scheduler_functionality()
    ]
    
    all_tests_passed = all(test_results)
    
    print("\n" + "=" * 50)
    if all_tests_passed:
        print("🎉 ALL TESTS PASSED! Your enhanced scheduler is ready to use.")
        print("\n📋 Next Steps:")
        print("1. Start your application: python app.py")
        print("2. Login as admin and go to /admin/scheduler")
        print("3. Configure your preferred settings")
        print("4. Test manual triggers")
    else:
        print("❌ SOME TESTS FAILED. Please check the errors above.")
        print("\n🔧 Common fixes:")
        print("- Run: pip install schedule")
        print("- Ensure all files were copied to correct locations")
        print("- Check that database migration completed")
    
    return 0 if all_tests_passed else 1

if __name__ == "__main__":
    sys.exit(main())