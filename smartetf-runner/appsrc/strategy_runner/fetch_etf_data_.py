import logging
import os
import requests
import time
import tempfile, shutil, random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from datetime import datetime

# ---- Config (env-overridable) ----
NSE_UA = os.getenv(
    "NSE_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

def fetch_cookies_with_selenium(headless: bool = True):
    """Headless Chromium with a UNIQUE temp user profile; returns cookie dict."""
    logging.info("Fetching cookies with Selenium...")

    # Force headless on Cloud Run
    if os.getenv("RUN_MODE", "headless").lower() == "headless":
        headless = True

    opts = Options()
    # Unique profile per run (prevents 'user data directory in use')
    tmp_profile = tempfile.mkdtemp(prefix="chrome-profile-", dir="/tmp")
    opts.add_argument(f"--user-data-dir={tmp_profile}")

    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1366,768")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(f"--user-agent={NSE_UA}")
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)

    # Respect container envs
    # if os.getenv("CHROME_BIN"):
    #     opts.binary_location = os.getenv("CHROME_BIN")
    # service = Service(executable_path=os.getenv("CHROMEDRIVER_PATH")) if os.getenv("CHROMEDRIVER_PATH") else Service()

    # driver = None
    try:
        driver = webdriver.Chrome(options=opts)

        # Warm-up like a real user so NSE sets anti-bot cookies
        driver.get("https://www.nseindia.com/")
        time.sleep(2 + random.random())
        driver.get("https://www.nseindia.com/market-data/exchange-traded-funds-etf")
        time.sleep(3 + random.random())

        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        logging.info(f"Cookies fetched: {len(cookies)}")

        if not cookies:
            driver.refresh()
            time.sleep(3)
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            logging.info(f"Cookies after refresh: {len(cookies)}")

        return cookies if cookies else None

    except Exception as e:
        logging.error(f"Error fetching cookies: {e}")
        return None
    finally:
        try:
            if driver:
                driver.quit()
        finally:
            shutil.rmtree(tmp_profile, ignore_errors=True)

def _is_csv_response(response, content_bytes: bytes) -> bool:
    ctype = (response.headers.get('content-type') or '').lower()
    if 'text/csv' in ctype or 'application/octet-stream' in ctype:
        return True
    head = content_bytes[:512].decode('latin-1', errors='ignore').lower()
    if '<html' in head or '<!doctype' in head:
        return False
    return ',' in head  # CSV-ish heuristic

def download_csv_with_cookies(cookies):
    logging.info("Downloading ETF data CSV (old path)…")
    csv_url = "https://www.nseindia.com/api/etf?csv=true&selectValFormat=crores"
    headers = {
        "User-Agent": NSE_UA,
        "Accept": "text/csv,application/csv,application/octet-stream,text/plain,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/exchange-traded-funds-etf",
        "Origin": "https://www.nseindia.com",
        "Connection": "keep-alive",
        # extra client hints that often help
        "sec-ch-ua": '"Chromium";v="120", "Not=A?Brand";v="24", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "Windows",
        "upgrade-insecure-requests": "1",
    }

    try:
        s = requests.Session()
        s.headers.update(headers)
        s.cookies.update(cookies)

        # Warm-up with same session + cookies (mimic user path)
        s.get("https://www.nseindia.com/", timeout=20)
        time.sleep(1.0)
        s.get("https://www.nseindia.com/market-data/exchange-traded-funds-etf", timeout=20)
        time.sleep(1.2)

        r = s.get(csv_url, timeout=30, allow_redirects=True)
        r.raise_for_status()

        content = r.content or b""
        if not _is_csv_response(r, content):
            logging.error(f"Unexpected content-type: {r.headers.get('content-type')} — not saving")
            return None

        file_name = f"ETF_Data_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(file_name, "wb") as f:
            f.write(content)
        sz = os.path.getsize(file_name)
        logging.info(f"ETF data saved as {file_name} (size={sz} bytes)")
        return file_name
    except Exception as e:
        logging.error(f"Error downloading ETF data: {e}")
        return None

def fetch_etf_data(headless: bool | None = None):
    # Respect Cloud Run default
    if headless is None:
        headless = os.getenv("RUN_MODE", "headless").lower() == "headless"

    print("Fetching ETF data...")

    # 1) Get cookies (headless)
    cookies = fetch_cookies_with_selenium(headless=headless)
    if not cookies:
        print("Failed to fetch cookies. Exiting.")
        return None

    # 2) Try download
    file_name = download_csv_with_cookies(cookies)

    # 3) Optional retry (re-fetch cookies and try once more)
    if not file_name:
        logging.warning("Download failed; re-fetching cookies and retrying once…")
        cookies2 = fetch_cookies_with_selenium(headless=True)
        if cookies2:
            file_name = download_csv_with_cookies(cookies2)

    if not file_name:
        print("Failed to download ETF CSV. Exiting.")
        return None

    print(f"ETF data successfully downloaded: {file_name}")
    return file_name


def fetch_etf_data_with_fallback():
    """
    Backwards-compatible wrapper expected by other modules.
    Returns the CSV file path string (or None on failure).
    """
    try:
        return fetch_etf_data()
    except Exception as _:
        return None
