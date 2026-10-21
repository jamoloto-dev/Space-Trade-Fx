"""Unit tests for the MetaApi trading robot script."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import metaapi_robot


def test_load_credentials(monkeypatch):
    monkeypatch.setenv("METAAPI_TOKEN", "mock_metaapi_token_12345")
    monkeypatch.setenv("METAAPI_ACCOUNT_ID", "mock_acc_999")

    token, account_id = metaapi_robot.load_credentials()
    assert token == "mock_metaapi_token_12345"
    assert account_id == "mock_acc_999"


def test_fetch_account_information():
    mock_conn = MagicMock()
    mock_conn.get_account_information = AsyncMock(
        return_value={
            "currency": "USD",
            "balance": 10500.50,
            "equity": 10720.00,
            "freeMargin": 9800.25,
            "leverage": 500,
            "server": "IFXBrokers-Real",
        }
    )

    info = asyncio.run(metaapi_robot.fetch_account_information(mock_conn))
    assert info["currency"] == "USD"
    assert info["balance"] == 10500.50
    assert info["equity"] == 10720.00
    assert info["freeMargin"] == 9800.25


def test_execute_market_buy_order():
    mock_conn = MagicMock()
    mock_conn.create_market_buy_order = AsyncMock(
        return_value={"orderId": "12345678", "positionId": "87654321", "numericCode": 10009}
    )

    res = asyncio.run(
        metaapi_robot.execute_market_order(
            connection=mock_conn,
            symbol="EURUSD",
            volume=0.01,
            action="BUY",
            stop_loss=1.05000,
            take_profit=1.06000,
        )
    )
    assert res["orderId"] == "12345678"
    mock_conn.create_market_buy_order.assert_awaited_once_with(
        symbol="EURUSD",
        volume=0.01,
        stop_loss=1.05000,
        take_profit=1.06000,
    )


def test_execute_market_sell_order():
    mock_conn = MagicMock()
    mock_conn.create_market_sell_order = AsyncMock(
        return_value={"orderId": "99988877", "positionId": "55544433", "numericCode": 10009}
    )

    res = asyncio.run(
        metaapi_robot.execute_market_order(
            connection=mock_conn,
            symbol="GBPUSD",
            volume=0.02,
            action="SELL",
        )
    )
    assert res["orderId"] == "99988877"
    mock_conn.create_market_sell_order.assert_awaited_once_with(
        symbol="GBPUSD",
        volume=0.02,
        stop_loss=None,
        take_profit=None,
    )


def test_execute_market_order_invalid_action():
    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="Invalid order action"):
        asyncio.run(
            metaapi_robot.execute_market_order(
                connection=mock_conn,
                symbol="EURUSD",
                volume=0.01,
                action="HOLD",
            )
        )


def test_metaapi_missing_dependency(monkeypatch):
    monkeypatch.setattr(metaapi_robot, "MetaApi", None)
    monkeypatch.setenv("METAAPI_TOKEN", "mock_token")
    with pytest.raises(ImportError, match="metaapi-cloud-sdk is required"):
        asyncio.run(metaapi_robot.run_trading_robot())


def test_check_token_format():
    # Valid JWT
    valid_jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVm"
    res = metaapi_robot.check_token_format(valid_jwt)
    assert res["present"] is True
    assert res["is_jwt"] is True
    assert "..." in res["masked"]

    # Missing / None / Empty
    assert metaapi_robot.check_token_format(None)["present"] is False
    assert metaapi_robot.check_token_format("")["present"] is False
    assert metaapi_robot.check_token_format("   ")["present"] is False

    # Non-JWT string
    res_raw = metaapi_robot.check_token_format("raw_api_key_string")
    assert res_raw["present"] is True
    assert res_raw["is_jwt"] is False


def test_handle_metaapi_auth_error():
    # 401 exception with status_code attribute
    exc_obj = Exception("Request failed with 401 Unauthorized")
    exc_obj.status_code = 401
    handled = metaapi_robot.handle_metaapi_auth_error(exc_obj, "mock.token.part")
    assert handled is True

    # 401 exception with message text
    exc_msg = Exception("401 Unauthorized: Invalid token credentials")
    assert metaapi_robot.handle_metaapi_auth_error(exc_msg, "mock.token.part") is True

    # Non-401 exception
    exc_500 = Exception("500 Internal Server Error")
    exc_500.status_code = 500
    assert metaapi_robot.handle_metaapi_auth_error(exc_500, "mock.token.part") is False


def test_resolve_tradable_symbol_with_suffix():
    mock_conn = MagicMock()

    async def mock_get_spec(sym):
        if sym == "EURUSD":
            return {"tradeMode": "SYMBOL_TRADE_MODE_DISABLED"}
        if sym == "EURUSD.ifx":
            return {"tradeMode": "SYMBOL_TRADE_MODE_FULL"}
        return None

    mock_conn.get_symbol_specification = AsyncMock(side_effect=mock_get_spec)

    resolved = asyncio.run(metaapi_robot.resolve_tradable_symbol(mock_conn, "EURUSD"))
    assert resolved == "EURUSD.ifx"


def test_calculate_position_size():
    # Small account ($10) should safely clamp to min_volume (0.01 lots)
    small_size = metaapi_robot.calculate_position_size(equity=10.0, risk_pct=1.5, sl_pips=25.0)
    assert small_size == 0.01

    # Large account ($10,000) risking 2% with 25 pip SL ($200 risk / (25 * 10)) -> 0.80 lots
    large_size = metaapi_robot.calculate_position_size(equity=10000.0, risk_pct=2.0, sl_pips=25.0)
    assert large_size == 0.80

    # Zero/negative equity fallback
    zero_size = metaapi_robot.calculate_position_size(equity=0.0)
    assert zero_size == 0.01


def test_check_drawdown_circuit_breaker():
    # 2% drawdown (below 5% limit) -> False
    tripped, pct = metaapi_robot.check_drawdown_circuit_breaker(
        starting_balance=1000.0, current_equity=980.0, max_drawdown_pct=5.0
    )
    assert tripped is False
    assert abs(pct - 2.0) < 0.01

    # 6% drawdown (above 5% limit) -> True
    tripped, pct = metaapi_robot.check_drawdown_circuit_breaker(
        starting_balance=1000.0, current_equity=940.0, max_drawdown_pct=5.0
    )
    assert tripped is True
    assert abs(pct - 6.0) < 0.01


def test_check_risk_guardrails():
    mock_conn = MagicMock()
    # Mock open positions
    mock_conn.get_positions = AsyncMock(
        return_value=[
            {"id": "pos-1", "symbol": "USDJPY.ifx"},
            {"id": "pos-2", "symbol": "GBPUSD.ifx"},
        ]
    )

    # Allowed when under max_open_trades and no duplicate symbol
    passed, reason = asyncio.run(
        metaapi_robot.check_risk_guardrails(
            connection=mock_conn,
            symbol="EURUSD.ifx",
            lot_size=0.01,
            max_open_trades=3,
            free_margin=100.0,
            required_margin=20.0,
        )
    )
    assert passed is True
    assert reason is None

    # Blocked when max_open_trades reached
    passed, reason = asyncio.run(
        metaapi_robot.check_risk_guardrails(
            connection=mock_conn,
            symbol="EURUSD.ifx",
            lot_size=0.01,
            max_open_trades=2,
            free_margin=100.0,
            required_margin=20.0,
        )
    )
    assert passed is False
    assert "Exposure Cap Reached" in reason

    # Blocked on duplicate symbol
    passed, reason = asyncio.run(
        metaapi_robot.check_risk_guardrails(
            connection=mock_conn,
            symbol="USDJPY.ifx",
            lot_size=0.01,
            max_open_trades=5,
            free_margin=100.0,
            required_margin=20.0,
        )
    )
    assert passed is False
    assert "Duplicate Symbol Position" in reason

    # Blocked on insufficient free margin
    passed, reason = asyncio.run(
        metaapi_robot.check_risk_guardrails(
            connection=mock_conn,
            symbol="EURUSD.ifx",
            lot_size=0.01,
            max_open_trades=5,
            free_margin=10.0,
            required_margin=25.0,
        )
    )
    assert passed is False
    assert "Insufficient Free Margin" in reason


def test_evaluate_ai_context_nonexistent_db():
    ctx = metaapi_robot.evaluate_ai_context("EURUSD", "BUY", db_path="/tmp/nonexistent.db")
    assert "veto" in ctx
    assert "history" in ctx
    assert ctx["risk_multiplier"] == 1.0
