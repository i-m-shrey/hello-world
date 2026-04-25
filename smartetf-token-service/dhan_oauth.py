"""
DHAN Token Generation - Fixed Playwright flow
"""
import time
import requests
import pyotp
import re
from playwright.sync_api import Playwright, sync_playwright, TimeoutError as PlaywrightTimeoutError


def generate_dhan_token(api_key, api_secret, client_id, mobile_number, pin, totp_secret):
    """
    Generate DHAN access token using Playwright automation
    """
    
    def get_consent_url():
        """Step 1: Generate consent URL"""
        url = f"https://auth.dhan.co/app/generate-consent?client_id={client_id}"
        headers = {
            "app_id": api_key,
            "app_secret": api_secret
        }
        
        response = requests.post(url, headers=headers, timeout=20)
        if response.status_code != 200:
            raise Exception(f"Consent generation failed: {response.text}")
        
        data = response.json()
        consent_app_id = data.get('consentAppId')
        if not consent_app_id:
            raise Exception(f"No consentAppId in response: {data}")
        
        return f'https://auth.dhan.co/login/consentApp-login?consentAppId={consent_app_id}'
    
    def browser_automation(playwright: Playwright):
        """Step 2: Automate browser login and extract tokenId"""
        browser = None
        context = None
        token_id = None
        
        try:
            browser = playwright.firefox.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # Navigate to consent URL
            consent_url = get_consent_url()
            print(f"[1/4] Navigating to consent URL...")
            page.goto(consent_url, timeout=30000)
            
            # Enter mobile number
            print(f"[2/4] Entering mobile number...")
            page.get_by_role("textbox", name="Enter mobile number").fill(mobile_number)
            time.sleep(1)
            page.get_by_role("button", name="Proceed").click()
            
            # Wait for TOTP input
            page.wait_for_selector("input", timeout=15000)
            
            # Enter TOTP
            print(f"[3/4] Entering TOTP...")
            time.sleep(2)
            totp_code = pyotp.TOTP(totp_secret).now()
            page.locator("input").first.fill(str(totp_code))
            time.sleep(2)
            
            # Wait for PIN input
            page.wait_for_selector("input", timeout=15000)
            
            # Enter PIN
            print(f"[4/4] Entering PIN...")
            page.locator("input").first.fill(pin)
            time.sleep(1)

            # Submit the PIN by pressing Enter or clicking proceed button
            try:
                # Try to find and click Proceed button
                page.get_by_role("button", name="Proceed").click()
            except:
                # If button not found, press Enter on the input field
                page.locator("input").first.press("Enter")
            
            # Wait for navigation to complete after PIN submission
            print(f"[INFO] Waiting for redirect...")
            try:
                page.wait_for_url(lambda url: "tokenId=" in url, timeout=15000)
            except:
                pass
            time.sleep(1)
            
            # Extract tokenId from final URL
            final_url = page.url
            print(f"[INFO] Final URL: {final_url}")
            
            match = re.search(r"tokenId=([a-f0-9\-]+)", final_url)
            if match:
                token_id = match.group(1)
                print(f"[SUCCESS] Token ID extracted: {token_id}")
            else:
                raise Exception(f"Token ID not found in URL: {final_url}")
        
        except Exception as e:
            raise Exception(f"Browser automation failed: {e}")
        
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
        
        return token_id
    
    def get_access_token(token_id):
        """Step 3: Exchange tokenId for access token"""
        url = f"https://auth.dhan.co/app/consumeApp-consent?tokenId={token_id}"
        headers = {
            "app_id": api_key,
            "app_secret": api_secret
        }
        
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")
        
        data = response.json()
        access_token = data.get('accessToken')
        if not access_token:
            raise Exception(f"No accessToken in response: {data}")
        
        return access_token
    
    # Execute the flow
    print(f"Generating DHAN token for {client_id}...")
    
    with sync_playwright() as playwright:
        token_id = browser_automation(playwright)
        access_token = get_access_token(token_id)
        print(f"Token generated successfully: {access_token[:30]}...")
        return access_token


if __name__ == "__main__":
    # Test script
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    try:
        token = generate_dhan_token(
            api_key=os.getenv('api_key'),
            api_secret=os.getenv('api_secret'),
            client_id=os.getenv('client_id'),
            mobile_number=os.getenv('mobileno'),
            pin=os.getenv('pin'),
            totp_secret=os.getenv('dhanTOTPtoken')
        )
        print(f"\nSUCCESS! Access Token: {token}")
    except Exception as e:
        print(f"\nFAILED: {e}")
