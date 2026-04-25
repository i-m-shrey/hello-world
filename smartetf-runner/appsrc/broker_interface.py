from abc import ABC, abstractmethod

class BaseBroker(ABC):
    def __init__(self, broker_data):
        """
        broker_data = dict with broker credentials from DB
        """
        self.broker_data = broker_data

    @abstractmethod
    def login(self):
        pass

    @abstractmethod
    def place_order(self, symbol, quantity, order_type):
        pass


class FinvasiaBroker(BaseBroker):
    def login(self):
        print(f"Logging in to Finvasia for user: {self.broker_data['username']}")
        # Implement Finvasia login logic here using API key, TOTP, etc.
        # Save token if needed

    def place_order(self, symbol, quantity, order_type):
        print(f"Placing order via Finvasia: {symbol}, {quantity}, {order_type}")
        # Use authenticated session/token to place order
