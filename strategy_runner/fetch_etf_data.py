import logging
import os
import requests
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from datetime import datetime
import csv


def fetch_cookies_with_selenium(headless: bool = True):
    logging.info("Fetching cookies with Selenium...")
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1366,768")
    else:
        chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--lang=en-US,en")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    try:
        # Visit base first to allow anti-bot to set cookies
        driver.get("https://www.nseindia.com/")
        time.sleep(2)
        driver.get("https://www.nseindia.com/market-data/exchange-traded-funds-etf")
        time.sleep(6)
        cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
        logging.info(f"Cookies fetched: {len(cookies)}")
        if not cookies:
            # Retry once with refresh
            driver.refresh()
            time.sleep(5)
            cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
            logging.info(f"Cookies after refresh: {len(cookies)}")
        return cookies if cookies else None
    except Exception as e:
        logging.error(f"Error fetching cookies: {e}")
        return None
    finally:
        driver.quit()


def _is_csv_response(response, content_bytes: bytes) -> bool:
    ctype = (response.headers.get('content-type') or '').lower()
    if 'text/csv' in ctype or 'application/octet-stream' in ctype:
        return True
    head = content_bytes[:512].decode('latin-1', errors='ignore').lower()
    if '<html' in head or '<!doctype' in head:
        return False
    # Heuristic: looks like CSV if first line has commas
    if ',' in head:
        return True
    return False


def download_csv_with_cookies(cookies):
    logging.info("Downloading ETF data CSV...")
    csv_url = "https://www.nseindia.com/api/etf?csv=true&selectValFormat=crores"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Accept': 'text/csv,application/csv,application/octet-stream,text/plain,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nseindia.com/market-data/exchange-traded-funds-etf',
        'Connection': 'keep-alive'
    }

    try:
        session = requests.Session()
        session.headers.update(headers)
        session.cookies.update(cookies)
        response = session.get(csv_url, timeout=30, allow_redirects=True)
        response.raise_for_status()
        content = response.content or b''
        if not _is_csv_response(response, content):
            logging.error(f"Unexpected content-type: {response.headers.get('content-type')} — not saving")
            return None
        file_name = f"ETF_Data_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(file_name, 'wb') as file:
            file.write(content)
        logging.info(f"ETF data saved as {file_name}")
        return file_name
    except Exception as e:
        logging.error(f"Error downloading ETF data: {e}")
        return None

def _warm_requests_session(session: requests.Session) -> None:
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept": "text/csv,application/csv,application/octet-stream,text/plain,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/exchange-traded-funds-etf",
        "Origin": "https://www.nseindia.com",
        "Connection": "keep-alive",
    })
    session.get("https://www.nseindia.com/", timeout=20)
    time.sleep(0.8)
    session.get("https://www.nseindia.com/market-data/exchange-traded-funds-etf", timeout=20)
    time.sleep(0.8)

def fetch_etf_csv_direct() -> str | None:
    """Strategy 1: direct CSV endpoint without Selenium."""
    logging.info("Fetching ETF CSV via direct NSE endpoint (no Selenium)...")
    try:
        session = requests.Session()
        _warm_requests_session(session)
        url = "https://www.nseindia.com/api/etf?csv=true&selectValFormat=crores"
        response = session.get(url, timeout=30, allow_redirects=True)
        response.raise_for_status()
        content = response.content or b""
        if not _is_csv_response(response, content):
            logging.error("Direct CSV response was not valid CSV.")
            return None
        file_name = f"ETF_Data_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(file_name, "wb") as f:
            f.write(content)
        logging.info(f"ETF data saved as {file_name} (direct CSV)")
        return file_name
    except Exception as e:
        logging.error(f"Direct CSV fetch failed: {e}")
        return None

def fetch_etf_csv_from_json() -> str | None:
    """Strategy 2: fetch JSON endpoint and convert to CSV."""
    logging.info("Fetching ETF data via JSON endpoint (no Selenium)...")
    try:
        session = requests.Session()
        _warm_requests_session(session)
        url = "https://www.nseindia.com/api/etf"
        response = session.get(url, timeout=30, allow_redirects=True)
        response.raise_for_status()
        data = response.json()
        records = data.get("data") if isinstance(data, dict) else None
        if not records:
            logging.error("JSON endpoint returned no data.")
            return None
        file_name = f"ETF_Data_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(file_name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        logging.info(f"ETF data saved as {file_name} (JSON->CSV)")
        return file_name
    except Exception as e:
        logging.error(f"JSON endpoint fetch failed: {e}")
        return None


def fetch_etf_data(headless: bool | None = None):
    if headless is None:
        headless = os.getenv('HEADLESS', '1').lower() in ('1', 'true', 'yes', 'on')
    print("Fetching ETF data...")

    # 1) Try preferred mode for cookies
    cookies = fetch_cookies_with_selenium(headless=headless)
    if not cookies and headless:
        logging.warning("Headless cookies empty; trying visible browser mode once...")
        cookies = fetch_cookies_with_selenium(headless=False)

    if not cookies:
        print("Failed to fetch cookies. Exiting.")
        return None

    # 2) Try download; if not CSV and was headless, retry with visible cookies
    file_name = download_csv_with_cookies(cookies)
    if not file_name and headless:
        logging.warning("Headless download was not CSV; refetching cookies in visible browser and retrying...")
        cookies2 = fetch_cookies_with_selenium(headless=False)
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
        file_name = fetch_etf_csv_direct()
        if file_name:
            return file_name
        file_name = fetch_etf_csv_from_json()
        if file_name:
            return file_name
        return fetch_etf_data()
    except Exception as _:
        return None
