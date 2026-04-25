#!/usr/bin/env python3
"""
Validation script to verify all broker API fixes
"""
import os
import re

def check_function_exists(filepath, function_name):
    """Check if file contains a function definition"""
    if not os.path.exists(filepath):
        print(f"❌ {filepath} not found")
        return False
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    pattern = rf'def {function_name}\s*\('
    if re.search(pattern, content):
        print(f"✅ {os.path.basename(filepath):30} has {function_name}")
        return True
    else:
        print(f"❌ {os.path.basename(filepath):30} missing {function_name}")
        return False

def main():
    base_dir = "/project/workspace/SmartETF_Merged_Full_Project"
    
    print("=" * 70)
    print("BROKER API VALIDATION - place_order() Function Check")
    print("=" * 70)
    
    broker_apis = [
        'dhan_broker_api.py',
        'finvasia_broker_api.py',
        'zerodha_broker_api.py',
        'upstox_broker_api.py',
        'groww_broker_api.py'
    ]
    
    print("\n1. Checking broker_api files have place_order() function...")
    print("-" * 70)
    
    all_good = True
    for api_file in broker_apis:
        filepath = f"{base_dir}/{api_file}"
        if not check_function_exists(filepath, "place_order"):
            all_good = False
    
    print("\n2. Checking broker_api files have place_single_order_direct() function...")
    print("-" * 70)
    
    for api_file in broker_apis:
        filepath = f"{base_dir}/{api_file}"
        if os.path.exists(filepath):
            check_function_exists(filepath, "place_single_order_direct")
    
    print("\n3. Checking broker_api files have get_available_funds() function...")
    print("-" * 70)
    
    for api_file in broker_apis:
        filepath = f"{base_dir}/{api_file}"
        if os.path.exists(filepath):
            check_function_exists(filepath, "get_available_funds")
    
    print("\n4. Checking token generation methods...")
    print("-" * 70)
    
    # Check Dhan uses Playwright
    with open(f"{base_dir}/dhan_oauth.py", 'r') as f:
        dhan_content = f.read()
    if 'playwright' in dhan_content.lower():
        print("✅ dhan_oauth.py              uses Playwright (browser automation)")
    else:
        print("❌ dhan_oauth.py              NOT using browser automation")
    
    # Check Zerodha selenium exists
    if os.path.exists(f"{base_dir}/zerodha_oauth_sel.py"):
        with open(f"{base_dir}/zerodha_oauth_sel.py", 'r') as f:
            zerodha_sel_content = f.read()
        if 'selenium' in zerodha_sel_content.lower():
            print("✅ zerodha_oauth_sel.py       uses Selenium (browser automation)")
        else:
            print("❌ zerodha_oauth_sel.py       NOT using Selenium")
    
    # Check app.py imports
    with open(f"{base_dir}/app.py", 'r') as f:
        app_content = f.read()
    
    dhan_oauth_count = app_content.count('from dhan_oauth import generate_dhan_token')
    zerodha_sel_count = app_content.count('from zerodha_oauth_sel import generate_zerodha_token')
    
    print(f"\n5. Checking app.py token generation imports...")
    print("-" * 70)
    print(f"   DHAN imports (from dhan_oauth):         {dhan_oauth_count} (expected: 2)")
    print(f"   ZERODHA imports (from zerodha_oauth_sel): {zerodha_sel_count} (expected: 2)")
    
    if dhan_oauth_count == 2:
        print("✅ app.py uses dhan_oauth (Playwright) for test orders")
    else:
        print("❌ app.py DHAN imports incorrect")
    
    if zerodha_sel_count == 2:
        print("✅ app.py uses zerodha_oauth_sel (Selenium) for test orders")
    else:
        print("❌ app.py ZERODHA imports incorrect")
    
    print("\n" + "=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
