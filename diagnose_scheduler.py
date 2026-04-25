#!/usr/bin/env python3
"""
Scheduler Route Diagnostics Script

Run this script to identify exactly what's wrong with the scheduler routes.
Place this file in your SmartETF project directory and run: python diagnose_scheduler.py
"""

import sys
import os

def test_imports():
    """Test if all required modules can be imported"""
    print("=" * 50)
    print("🔍 TESTING IMPORTS")
    print("=" * 50)
    
    # Test schedule package
    try:
        import schedule
        print("✅ schedule package: OK")
    except ImportError:
        print("❌ schedule package: MISSING - Run: pip install schedule")
        return False
    
    # Test SchedulerSettings model
    try:
        from models import SchedulerSettings
        print("✅ SchedulerSettings model: OK")
    except Exception as e:
        print(f"❌ SchedulerSettings model: FAILED - {e}")
        return False
    
    # Test enhanced email functions
    try:
        from email_notifications import send_admin_alert_email
        print("✅ Enhanced email functions: OK")
    except Exception as e:
        print(f"❌ Enhanced email functions: FAILED - {e}")
        return False
    
    # Test execution scheduler
    try:
        from strategy_runner.execution_scheduler import EnhancedExecutionScheduler
        print("✅ EnhancedExecutionScheduler: OK")
    except ImportError as e:
        if "etf_automated" in str(e):
            print("❌ EnhancedExecutionScheduler: IMPORT ERROR - Wrong function name in execution_scheduler.py")
            print("🔧 FIX: Use the updated execution_scheduler.py from v3 package")
        else:
            print(f"❌ EnhancedExecutionScheduler: IMPORT ERROR - {e}")
        return False
    except Exception as e:
        print(f"❌ EnhancedExecutionScheduler: FAILED - {e}")
        return False
    
    return True

def test_app_routes():
    """Test if scheduler routes exist in app.py"""
    print("\n" + "=" * 50)
    print("🌐 TESTING APP.PY ROUTES")
    print("=" * 50)
    
    try:
        from app import app
        
        # Get all route rules
        route_rules = [str(rule) for rule in app.url_map.iter_rules()]
        
        required_routes = [
            '/admin/scheduler',
            '/admin/broker-passwords', 
            '/admin/scheduler/status',
            '/admin/scheduler/update',
            '/admin/scheduler/trigger-health-check',
            '/admin/scheduler/trigger-execution'
        ]
        
        missing_routes = []
        for route in required_routes:
            if any(route in rule for rule in route_rules):
                print(f"✅ {route}: Found")
            else:
                print(f"❌ {route}: MISSING")
                missing_routes.append(route)
        
        return len(missing_routes) == 0
        
    except Exception as e:
        print(f"❌ Error testing routes: {e}")
        return False

def test_route_functions():
    """Test if route functions can be called"""
    print("\n" + "=" * 50)
    print("🔧 TESTING ROUTE FUNCTIONS")
    print("=" * 50)
    
    try:
        from app import app
        
        with app.test_client() as client:
            
            # Test scheduler management
            try:
                response = client.get('/admin/scheduler')
                status = response.status_code
                if status in [200, 302, 401, 403]:  # Valid responses
                    print(f"✅ Scheduler Management: {status} (Valid)")
                else:
                    print(f"❌ Scheduler Management: {status} (Error)")
            except Exception as e:
                print(f"❌ Scheduler Management: Exception - {e}")
            
            # Test broker passwords
            try:
                response = client.get('/admin/broker-passwords')
                status = response.status_code
                if status in [200, 302, 401, 403]:
                    print(f"✅ Broker Passwords: {status} (Valid)")
                else:
                    print(f"❌ Broker Passwords: {status} (Error)")
            except Exception as e:
                print(f"❌ Broker Passwords: Exception - {e}")
            
            # Test scheduler status API
            try:
                response = client.get('/admin/scheduler/status')
                status = response.status_code
                if status in [200, 302, 401, 403]:
                    print(f"✅ Scheduler Status: {status} (Valid)")
                else:
                    print(f"❌ Scheduler Status: {status} (Error)")
            except Exception as e:
                print(f"❌ Scheduler Status: Exception - {e}")
                
    except Exception as e:
        print(f"❌ Error testing route functions: {e}")
        return False
    
    return True

def test_templates():
    """Test if required templates exist"""
    print("\n" + "=" * 50)
    print("📄 TESTING TEMPLATES")
    print("=" * 50)
    
    templates = [
        'templates/admin/scheduler_management.html',
        'templates/admin/broker_passwords.html',
        'templates/admin/dashboard.html'
    ]
    
    all_exist = True
    for template in templates:
        if os.path.exists(template):
            print(f"✅ {template}: Found")
        else:
            print(f"❌ {template}: MISSING")
            all_exist = False
    
    return all_exist

def test_database():
    """Test database and SchedulerSettings"""
    print("\n" + "=" * 50)
    print("🗄️ TESTING DATABASE")
    print("=" * 50)
    
    try:
        from app import app, db
        from models import SchedulerSettings
        
        with app.app_context():
            # Try to query SchedulerSettings
            try:
                settings = SchedulerSettings.query.first()
                print("✅ SchedulerSettings table: Exists")
                
                if not settings:
                    print("⚠️ No default settings found - will create on first access")
                else:
                    print(f"✅ Default settings: Found (Test time: {settings.session_test_time})")
                    
            except Exception as e:
                print(f"❌ SchedulerSettings table: Error - {e}")
                print("🔧 Running db.create_all()...")
                try:
                    db.create_all()
                    print("✅ Database tables created")
                except Exception as create_error:
                    print(f"❌ Failed to create tables: {create_error}")
                    return False
                    
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False
    
    return True

def main():
    """Run all diagnostic tests"""
    print("🚀 SmartETF Scheduler Route Diagnostics")
    print("=" * 50)
    print("This script will identify what's wrong with your scheduler routes.")
    print("=" * 50)
    
    all_tests_passed = True
    
    # Run all tests
    tests = [
        ("Imports", test_imports),
        ("App Routes", test_app_routes),
        ("Route Functions", test_route_functions),
        ("Templates", test_templates),
        ("Database", test_database)
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
            if not results[test_name]:
                all_tests_passed = False
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results[test_name] = False
            all_tests_passed = False
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 DIAGNOSTIC SUMMARY")
    print("=" * 50)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print("\n" + "=" * 50)
    if all_tests_passed:
        print("🎉 ALL TESTS PASSED!")
        print("If you're still getting errors, the issue might be:")
        print("1. Not logged in as admin user") 
        print("2. Browser cache (try Ctrl+F5)")
        print("3. Session issues (try logout/login)")
    else:
        print("🚨 ISSUES FOUND!")
        print("Follow the error messages above to fix the failing components.")
        print("Most common fixes:")
        print("- Replace app.py with updated version")
        print("- Copy missing template files")
        print("- Run: pip install schedule")
        print("- Run database migration")
    
    print("=" * 50)
    return 0 if all_tests_passed else 1

if __name__ == "__main__":
    sys.exit(main())