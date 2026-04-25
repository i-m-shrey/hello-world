from fetch_etf_data import fetch_etf_data
from filter_etfs import calculate_quantities
from order_manager import OrderManager
import pandas as pd
import time

MAX_RETRIES = 3  # Maximum number of retry attempts
RETRY_DELAY = 5  # Delay between retries (in seconds)

if __name__ == "__main__":
    print("Starting ETF trading program...")

    # Step 1: Fetch ETF Data with Retry
    retry_count = 0
    etf_csv_file = None
    # etf_csv_file = 'ETF_Data_2025-05-22.csv'

    while retry_count < MAX_RETRIES:
        print(f"Attempt {retry_count + 1} to fetch ETF data...")
        etf_csv_file = fetch_etf_data()

        if etf_csv_file:
            print("ETF data successfully fetched.")
            break  # Exit the loop if fetch is successful

        retry_count += 1
        if retry_count < MAX_RETRIES:
            print(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

    if not etf_csv_file:
        print(f"Failed to fetch ETF data after {MAX_RETRIES} attempts. Exiting.")
        exit()

    # Step 2: Load ETF Data
    print("Loading ETF data...")
    etf_data = pd.read_csv(etf_csv_file)

    # Step 3: Filter and Calculate Quantities
    print("Filtering ETFs and calculating quantities...")
    filtered_etfs = calculate_quantities(etf_data)
    print(filtered_etfs)
    filtered_etfs.to_csv('todays_etf.csv')

    if filtered_etfs.empty:
        print("No ETFs meet the criteria for placing orders. Exiting.")
        exit()

    # Step 4: Initialize Order Manager
    print("Initializing Order Manager...")
    accounts_file = "accounts.csv"
    order_manager = OrderManager(accounts_file)

    # Step 5: Log in to Accounts
    print("Logging into all accounts...")
    order_manager.login_all()

    # Step 6: Place Orders
    print("Placing orders for filtered ETFs...")
    order_manager.place_orders(filtered_etfs)

    print("Program completed successfully.")
