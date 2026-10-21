"""
Test suite for strategy engine module.
"""

from decimal import Decimal

import pytest


class TestStrategyEngine:
    """Test cases for the strategy engine."""

    def test_import_strategy_engine(self):
        """Test that strategy_engine module can be imported."""
        from space_trading_fx.core.strategy_engine import run_strategy

        assert callable(run_strategy)

    def test_run_strategy_returns_dict(self):
        """Test that run_strategy returns a dictionary."""
        from space_trading_fx.core.strategy_engine import run_strategy

        result = run_strategy()
        assert isinstance(result, dict)
        assert "status" in result


class TestTradeExecutor:
    """Test cases for the trade executor."""

    def test_import_execute_trade(self):
        """Test that execute_trade function can be imported."""
        from space_trading_fx.trading.trade_executor import execute_trade

        assert callable(execute_trade)

    def test_execute_trade_with_parameters(self):
        """Test execute_trade with specific parameters."""
        from space_trading_fx.trading.trade_executor import execute_trade

        result = execute_trade(currency_pair="EURUSD", trade_type="BUY", amount=1.5)
        assert result["status"] == "filled"
        assert result["execution_mode"] == "broker"
        assert result["currency_pair"] == "EURUSD"
        assert result["trade_type"] == "BUY"
        assert result["amount"] == Decimal("1.5")

    def test_execute_trade_default_parameters(self):
        """Test execute_trade with default parameters."""
        from space_trading_fx.trading.trade_executor import execute_trade

        result = execute_trade()
        assert result["status"] == "filled"
        assert result["execution_mode"] == "broker"
        assert result["amount"] == 1


class TestSignalReader:
    """Test cases for the signal reader."""

    def test_import_signal_reader(self):
        """Test that signal_reader module can be imported."""
        from space_trading_fx.core.signal_reader import read_signals

        assert callable(read_signals)

    def test_read_signals_returns_list(self):
        """Test that read_signals returns a list."""
        from space_trading_fx.core.signal_reader import read_signals

        signals = read_signals()
        assert isinstance(signals, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
