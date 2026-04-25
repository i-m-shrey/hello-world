"""
Keep SmartETF Backend warm during business hours
Alternative to Cloud Scheduler for free tier
"""
import requests
import time
from datetime import datetime
import os

BACKEND_URL = os.getenv('BACKEND_URL', 'https://your-backend-url.run.app')
HEALTH_ENDPOINT = '/health'
PING_INTERVAL = 300  # 5 minutes

def is_business_hours():
    now = datetime.now()
    # Monday-Friday, 9 AM - 6 PM IST
    return now.weekday() < 5 and 9 <= now.hour <= 18

def ping_backend():
    try:
        url = f"{BACKEND_URL}{HEALTH_ENDPOINT}"
        start = time.time()
        response = requests.get(url, timeout=10)
        duration = time.time() - start
        
        print(f"[{datetime.now()}] Status: {response.status_code}, Time: {duration:.2f}s")
        return response.status_code == 200
    except Exception as e:
        print(f"[{datetime.now()}] Error: {e}")
        return False

if __name__ == '__main__':
    print(f"🔥 SmartETF Keep-Warm Service")
    print(f"Target: {BACKEND_URL}{HEALTH_ENDPOINT}")
    print(f"Interval: {PING_INTERVAL}s\n")
    
    while True:
        if is_business_hours():
            print(f"[{datetime.now()}] Pinging backend...")
            ping_backend()
        else:
            print(f"[{datetime.now()}] Outside business hours, skipping...")
        
        time.sleep(PING_INTERVAL)
