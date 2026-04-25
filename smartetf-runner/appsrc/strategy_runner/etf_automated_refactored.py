
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import pandas as pd
from fetch_etf_data import fetch_etf_data
from filter_etfs import calculate_quantities
from broker_dispatcher import get_executor_for_broker
from client_fetcher import get_active_clients
from app import app, Broker


MAX_RETRIES = 3
RETRY_DELAY = 5

def fetch_and_filter_etfs():
    print("📊 Starting ETF data fetch...")
    retry_count = 0
    etf_csv_file = None

    while retry_count < MAX_RETRIES:
        print(f"⏳ Attempt {retry_count + 1} to fetch ETF data...")
        etf_csv_file = fetch_etf_data()

        if etf_csv_file:
            print("✅ ETF data fetched successfully.")
            break

        retry_count += 1
        if retry_count < MAX_RETRIES:
            print(f"🔁 Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

    if not etf_csv_file:
        print("❌ Failed to fetch ETF data. Exiting.")
        return None

    print("📥 Loading ETF data...")
    etf_data = pd.read_csv(etf_csv_file)

    print("🔍 Filtering ETFs and calculating quantities...")
    filtered = calculate_quantities(etf_data)

    if filtered.empty:
        print("⚠️ No ETFs matched the filter criteria.")
        return None

    print("💾 Saving filtered ETFs to todays_etf.csv")
    filtered.to_csv("todays_etf.csv", index=False)

    return filtered

def run_strategy():
    filtered_etfs = fetch_and_filter_etfs()
    if filtered_etfs is None:
        print("⚠️ No ETFs to execute.")
        return

    with app.app_context():
        master_broker = Broker.query.filter_by(is_master=True).first()
        if not master_broker:
            print("❌ No master broker found in the database.")
            return

        print(f"🔍 Master broker identified: {master_broker.broker_name.upper()}")
        master_executor = get_executor_for_broker(master_broker.broker_name.upper())

        master_info = {
            "username": master_broker.user_id_broker,
            "user_id_broker": master_broker.user_id_broker,
            "password": master_broker.password,
            "totp_secret": getattr(master_broker, "totp_secret", ""),
            "vendor_code": getattr(master_broker, "vendor_code", ""),
            "api_secret": getattr(master_broker, "api_secret", ""),
            "imei": getattr(master_broker, "imei", ""),
            "api_key": getattr(master_broker, "api_key", ""),
            "app_key": getattr(master_broker, "app_key", ""),
            "secret_key": getattr(master_broker, "secret_key", ""),
            "copy_multiplier": 1,
            "copy": False,
            "is_master": True
        }

        print("▶️ Executing master broker order placement...")
        master_executor.place_order(master_info, filtered_etfs)

        print("🔁 Starting client execution by broker...")
        clients = get_active_clients()
        for client in clients:
            if client.get("is_master", False):
                continue

            broker_name = client["broker_name"].upper()
            try:
                executor = get_executor_for_broker(broker_name)
                executor.place_order(client, filtered_etfs)
            except Exception as e:
                print(f"❌ Failed for client {client.get('username')} ({broker_name}): {e}")

if __name__ == "__main__":
    print("🚀 Starting SmartETF Strategy Runner...")
    run_strategy()
    print("✅ Execution complete.")
