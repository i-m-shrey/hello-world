import datetime
import logging
import pandas as pd
from account import Account

logging.basicConfig(
    filename='logs/etf' + str(datetime.datetime.now().today().strftime("%d_%m_%Y_time_%H_%M_%S")) + '.log',
    level=logging.DEBUG,
    format='%(asctime)s:%(levelname)s:%(threadName)s:%(message)s')

class OrderManager:
    def __init__(self, accounts_file):
        self.accounts = []
        self.master_account = None
        self.load_accounts(accounts_file)

    def load_accounts(self, accounts_file):
        """
        Load accounts from a CSV file.
        """
        print("Loading accounts...")
        df = pd.read_csv(accounts_file)
        for _, row in df.iterrows():
            account = Account(
                user_id=row['USER_ID'],
                password=row['PASSWORD'],
                totp_secret=row['TOTP_SECRET'],
                vendor_code=row['VENDOR_CODE'],
                api_secret=row['API_SECRET'],
                imei=row['IMEI'],
                is_master=row['IS_MASTER'],
                multiplier=row['COPY_MULTIPLIER'],
                copy=row['COPY']
            )
            if row['IS_MASTER']:
                self.master_account = account
            else:
                self.accounts.append(account)
        print("Accounts loaded successfully.")

    def login_all(self):
        """
        Log in all accounts (master and copiers).
        """
        # print("Logging into all accounts...")
        self.master_account.login()
        for account in self.accounts:
            account.login()
        print("Login completed.")

    def place_orders(self, filtered_etfs):
        """
        Place orders for filtered ETFs for both master and copiers.
        """
        print("Placing orders...")
        for _, row in filtered_etfs.iterrows():
            tradingsymbol = row['SYMBOL'] + "-EQ"
            quantity = row['QTY']

            # Place order for the master account
            print(f"Placing master order for {tradingsymbol} with quantity {quantity}.")
            if quantity == 0 or quantity < 1:
                quantity = 1
                print(f"Changing master order for {tradingsymbol} with quantity {quantity}.")
            self.master_account.session.place_order(
                buy_or_sell="B",
                product_type="C",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                quantity=quantity,
                discloseqty=0,
                price_type="MKT",
                price=0.0,
                retention="DAY",
                amo=None,
                remarks=f"Master order for {tradingsymbol}"
            )

            # Place orders for copier accounts
            for account in self.accounts:
                if not account.copy:
                    print(f"Skipping copier {account.user_id}.")
                    continue

                copied_quantity = quantity * int(account.multiplier)
                print(f"Placing copier order for {account.user_id} with quantity {copied_quantity}.")
                logging.debug(f"Placing copier order for {account.user_id} with quantity {copied_quantity}.")
                try:
                    account.session.place_order(
                        buy_or_sell="B",
                        product_type="C",
                        exchange="NSE",
                        tradingsymbol=tradingsymbol,
                        quantity=copied_quantity,
                        discloseqty=0,
                        price_type="MKT",
                        price=0.0,
                        retention="DAY",
                        amo=None,
                        remarks=f"Copier order for {tradingsymbol}"
                    )
                except Exception as e:
                    print(e)
        print("Order placement completed.")
        # logging.debug(f"Order placement completed for {account.user_id} with quantity {copied_quantity}.")
