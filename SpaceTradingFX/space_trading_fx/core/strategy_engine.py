from space_trading_fx.trading.trade_executor import execute_trade

def run_strategy():
    """Run the legacy strategy as a paper-only simulation."""
    result = execute_trade(currency_pair="EURUSD", trade_type="BUY", amount=1.0)
    return result
