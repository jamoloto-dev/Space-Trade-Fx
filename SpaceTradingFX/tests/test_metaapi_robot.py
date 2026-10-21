"""Unit tests for the MetaApi trading robot script."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
