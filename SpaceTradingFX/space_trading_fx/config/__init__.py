# space_trading_fx.py
from datetime import datetime
count_total = 0

# ✅ Temporary mock API — replace this later with your real broker API
class MockBrokerAPI:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self._balance =  1000.0
        print(f"Mock API initialized with {email}")

    def connect(self):
        print("Mock connected to broker.")

    def change_balance(self, mode):
        print(f"Balance mode changed to {mode}.")

    def disconnect(self):
        print("Disconnected from broker.")

    def get_balance(self):
        return (f"R{self._balance}")

    def get_balance_mode(self):
        return "Real"
    
    def add_balance(self, amount):
        self._balance += amount  # ✅ Add profit to current balance
        print(f" Added R{amount}. New Balance: R{self._balance}")
        return self._balance
    
    def get_all_open_time(self,profit=80):
      
        self.add_balance(profit)
        return {
            "turbo": {
                "USD/JPY": {
                    "open": True,
                    "open_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "close_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "profit": profit,
                    "timeframe": "1m",
                    "currency_pair": "USD/JPY"
                }
            }
        }

    def get_all_profit(self):
        return {
            "USD/JPY": {
                "turbo": 80,
                "binary": 75,
                "digital": 85
            }
        }

    def get_digital_payout(self, currency_pairs, timeframe):
        return 85,currency_pairs,timeframe

    def subscribe_strike_list(self, currency_pairs, timeframe):
        return f"Subscribed to {currency_pairs} ({timeframe})"

    def unsubscribe_strike_list(self, currency_pairs, timeframe):
        return f"Unsubscribed from {currency_pairs} ({timeframe})"

    def buy_digital_spot(self, currency_pairs, amount, subscribe, timeframe):
        return f"Bought {amount} of {currency_pairs} at {timeframe} {subscribe}"

    def sell_digital_spot(self, currency_pairs, amount, subscribe, timeframe):
        return f"Sold {amount} of {currency_pairs} at {timeframe} {subscribe}"


class Space_TradingFX:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.api = MockBrokerAPI(email, password)

        self.api.connect()
        self.api.change_balance("Real")

        print(f"Connected successfully to {self.api.get_balance_mode()} account.")

        self.balance = self.api.get_balance()
        self.currency_pairs = None
        self.type = None
        self.timeframe = None

    def get_all_open_time(self):
        self.balance = self.api.get_balance()
        print(f"Your current balance is: {self.balance}")
        return self.api.get_all_open_time()

    def payout(self, currency_pairs, type, timeframe):
        if type == "binary":
            return self.api.get_digital_payout(currency_pairs, timeframe)
        elif type == "digital":
            return self.api.get_digital_payout(currency_pairs, timeframe)
        elif type in ["turbo", "binary-turbo", "binary-digital", "turbo-digital"]:
            return self.api.get_all_profit().get(currency_pairs, {}).get(type, "N/A")
        else:
            return self.api.get_digital_payout(currency_pairs, timeframe)

    def pairs(self):
        open_times = self.get_all_open_time()

        for market_type in ["turbo", "binary", "digital"]:
            print(f"\nMarket Type: {market_type.upper()}")
            market_pairs = open_times.get(market_type, {})
            for currency_name, pair in market_pairs.items():
                if pair["open"]:
                    payout_value = self.payout(currency_name, market_type, "1m")
                    print(f"[{market_type.upper()}] {currency_name} | Payout: {payout_value}")
                    print(f"Symbol: {currency_name}")
                    print(f"Open Time: {pair['open_time']}")
                    print(f"Close Time: {pair['close_time']}")
                    print(f"Profit: {pair['profit']}")
                    print(f"Timeframe: {pair['timeframe']}")
                    print(f"Currency Pair: {pair['currency_pair']}")
                else:
                    print(f"[{market_type.upper()}]: {currency_name} | Payout: CLOSED")

    def get_balance(self):
        return self.api.get_balance()

    def get_balance_mode(self):
        return self.api.get_balance_mode()

    def change_balance(self, mode):
        return self.api.change_balance(mode)

    def connect(self):
        return self.api.connect()

    def disconnect(self):
        return self.api.disconnect()


def main():
    raise RuntimeError(
        "The legacy mock broker is disabled. Use environment-managed credentials only "
        "after the broker-adapter security architecture is implemented."
    )


if __name__ == "__main__":
    main()


