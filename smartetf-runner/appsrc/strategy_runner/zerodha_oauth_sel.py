"""
Zerodha Kite Connect Token Generation - Selenium automation
"""
import time
import requests
import pyotp
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import hashlib


def generate_zerodha_token(api_key, api_secret, user_id, password, totp_secret):
    """
    Generate Zerodha access token using Selenium automation
    
    Flow:
    1. Navigate to Kite login URL with API key
    2. Enter user_id and password
    3. Enter TOTP
    4. Extract request_token from redirect URL
    5. Generate checksum and exchange for access_token
    """
    
    def generate_checksum(api_key, request_token, api_secret):
        """Generate SHA256 checksum for token exchange"""
        data = f"{api_key}{request_token}{api_secret}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def browser_automation():
        """Step 1-3: Automate browser login and extract request_token"""
        driver = None
        request_token = None
        
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            
            driver = webdriver.Chrome(options=chrome_options)
            
            # Navigate to Kite login URL
            login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
            print(f"[1/4] Navigating to Zerodha Kite login...")
            driver.get(login_url)
            
            # Wait for page load
            time.sleep(2)
            
            # Enter user_id
            print(f"[2/4] Entering User ID...")
            user_id_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "userid"))
            )
            user_id_field.send_keys(user_id)
            
            # Enter password
            password_field = driver.find_element(By.ID, "password")
            password_field.send_keys(password)
            
            # Click login button
            login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_button.click()
            
            # Wait for TOTP page
            time.sleep(2)
            
            # Enter TOTP
            print(f"[3/4] Entering TOTP...")
            totp_code = pyotp.TOTP(totp_secret).now()
            
            try:
                totp_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "userid"))
                )
            except:
                try:
                    totp_field = driver.find_element(By.NAME, "totp")
                except:
                    totp_field = driver.find_element(By.XPATH, "//input[@type='text' or @type='tel']")
            
            totp_field.send_keys(totp_code)
            
            time.sleep(2)
            
            # Try to click continue button if present (page might auto-submit)
            print(f"[4/5] Checking for continue button...")
            try:
                continue_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
                )
                print(f"[INFO] Continue button found, clicking...")
                continue_button.click()
            except:
                print(f"[INFO] No continue button found, TOTP might have auto-submitted")
            
            # Wait for redirect or authorize page
            print(f"[5/6] Waiting for redirect...")
            time.sleep(4)
            
            # Check if Authorize button appears (first-time authorization)
            print(f"[6/6] Checking for Authorize button...")
            try:
                authorize_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Authorise') or contains(text(), 'Authorize')]"))
                )
                print(f"[INFO] Authorize button found, clicking...")
                authorize_button.click()
                time.sleep(3)
            except:
                print(f"[INFO] No authorize button found, proceeding...")
            
            # Get current URL (should contain request_token)
            current_url = driver.current_url
            print(f"[INFO] Redirect URL: {current_url}")
            
            # Extract request_token from URL
            match = re.search(r"request_token=([^&]+)", current_url)
            if match:
                request_token = match.group(1)
                print(f"[SUCCESS] Request token extracted: {request_token[:20]}...")
            else:
                raise Exception(f"Request token not found in URL: {current_url}")
        
        except Exception as e:
            raise Exception(f"Browser automation failed: {e}")
        
        finally:
            if driver:
                driver.quit()
        
        return request_token
    
    def exchange_token(request_token):
        """Step 4: Exchange request_token for access_token"""
        url = "https://api.kite.trade/session/token"
        
        checksum = generate_checksum(api_key, request_token, api_secret)
        
        payload = {
            'api_key': api_key,
            'request_token': request_token,
            'checksum': checksum
        }
        
        response = requests.post(url, data=payload, timeout=20)
        
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")
        
        data = response.json()
        
        if data.get('status') != 'success':
            raise Exception(f"Token exchange unsuccessful: {data}")
        
        access_token = data.get('data', {}).get('access_token')
        
        if not access_token:
            raise Exception(f"No access_token in response: {data}")
        
        return access_token
    
    # Execute the flow
    print(f"Generating Zerodha access token for {user_id}...")
    
    request_token = browser_automation()
    access_token = exchange_token(request_token)
    
    print(f"Token generated successfully: {access_token[:30]}...")
    return access_token


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    try:
        token = generate_zerodha_token(
            api_key=os.getenv('ZERODHA_API_KEY'),
            api_secret=os.getenv('ZERODHA_API_SECRET'),
            user_id=os.getenv('ZERODHA_USER_ID'),
            password=os.getenv('ZERODHA_PASSWORD'),
            totp_secret=os.getenv('ZERODHA_TOTP_SECRET')
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")
