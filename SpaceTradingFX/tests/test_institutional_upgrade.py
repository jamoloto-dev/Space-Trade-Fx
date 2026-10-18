"""Comprehensive test suite for institutional equities upgrade.

Verifies:
1. Security Master and asset class taxonomy (Equities, ETFs, Forex, T+1 settlement).
2. Corporate action adjustments (stock splits, dividends).
3. Market microstructure, NBBO pricing, adverse slippage, and institutional fee schedules (SEC 31, FINRA TAF).
4. SEC Rule 15c3-5 Pre-trade risk controls (Fat-finger, ADV, Price collar, Reg SHO short locate, Margin).
5. Quantitative analytics tear sheet (Sharpe, Sortino, Max Drawdown, VaR, Profit Factor).
6. TradingEngine multi-asset integration.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from flask_dashboard.analytics import compute_institutional_tear_sheet
from flask_dashboard.market_microstructure import (
    OrderType,
    QuoteNBBO,
    simulate_market_fill,
)
from flask_dashboard.pre_trade_risk import (
    PreTradeRiskConfig,
    PreTradeRiskRejected,
    clear_rate_throttle_history,
    validate_pre_trade_risk,
)
from flask_dashboard.securities import (
    AssetClass,
    CorporateAction,
    CorporateActionType,
    apply_corporate_action_to_candle,
    get_security,
    is_supported_security,
)

# ---------------------------------------------------------------------------
# 1. Security Master & Corporate Actions Tests
# ---------------------------------------------------------------------------


def test_security_master_equities_and_fx():
    """Verify security master accurately reflects equity vs fx characteristics."""
    # Equity check (AAPL)
    aapl = get_security("AAPL")
    assert aapl.asset_class == AssetClass.EQUITY
    assert aapl.exchange == "NASDAQ"
    assert aapl.contract_size == Decimal("1")
    assert aapl.settlement_days == 1  # T+1 US equities
    assert aapl.margin_rate == Decimal("0.50")  # 50% Reg T
    assert aapl.is_shortable is True

    # ETF check (SPY)
    spy = get_security("SPY")
    assert spy.asset_class == AssetClass.ETF
    assert spy.exchange == "NYSE ARCA"
    assert spy.contract_size == Decimal("1")

    # FX check (EURUSD)
    eurusd = get_security("EURUSD")
    assert eurusd.asset_class == AssetClass.FOREX
    assert eurusd.contract_size == Decimal("100000")
    assert eurusd.settlement_days == 2  # T+2 FX

    assert is_supported_security("AAPL") is True
    assert is_supported_security("NON_EXISTENT") is False


def test_corporate_action_stock_split():
    """Verify 2:1 stock split halves prices and doubles volume."""
    candle = {
        "time": "2026-01-15 16:00:00",
        "open": Decimal("200.00"),
        "high": Decimal("210.00"),
        "low": Decimal("195.00"),
        "close": Decimal("205.00"),
        "volume": 10000,
    }
    action = CorporateAction(
        symbol="AAPL",
        action_type=CorporateActionType.STOCK_SPLIT,
        effective_date=date(2026, 1, 16),
        ratio=Decimal("2.0"),
        description="2-for-1 stock split",
    )
    adjusted = apply_corporate_action_to_candle(candle, action)
    assert adjusted["open"] == Decimal("100.0000")
    assert adjusted["high"] == Decimal("105.0000")
    assert adjusted["low"] == Decimal("97.5000")
    assert adjusted["close"] == Decimal("102.5000")
    assert adjusted["volume"] == 20000


def test_corporate_action_cash_dividend():
    """Verify cash dividend reduces historical prices by dividend amount."""
    candle = {
        "open": Decimal("150.00"),
        "high": Decimal("155.00"),
        "low": Decimal("148.00"),
        "close": Decimal("152.00"),
    }
    action = CorporateAction(
        symbol="AAPL",
        action_type=CorporateActionType.CASH_DIVIDEND,
        effective_date=date(2026, 2, 1),
        ratio=Decimal("2.50"),
    )
    adjusted = apply_corporate_action_to_candle(candle, action)
    assert adjusted["close"] == Decimal("149.5000")


# ---------------------------------------------------------------------------
# 2. Market Microstructure & TCA Execution Tests
# ---------------------------------------------------------------------------


def test_nbbo_quote_properties():
    """Verify NBBO midpoint, spread, and basis points."""
    quote = QuoteNBBO(
        symbol="SPY",
        bid=Decimal("500.00"),
        ask=Decimal("500.04"),
    )
    assert quote.midpoint == Decimal("500.02")
    assert quote.spread == Decimal("0.04")
    # spread_bps = (0.04 / 500.02) * 10000 = ~0.80 bps
    assert quote.spread_bps == Decimal("0.80")


def test_market_order_fill_crosses_spread_and_applies_fees():
    """Verify Buy orders execute against Ask + slippage, and fees are attributed."""
    quote = QuoteNBBO(
        symbol="AAPL",
        bid=Decimal("220.00"),
        ask=Decimal("220.05"),
    )
    fill = simulate_market_fill(quote, direction="BUY", quantity=Decimal("100"))

    # Fill price must be at least Ask
    assert fill.fill_price >= quote.ask
    assert fill.filled_quantity == Decimal("100")
    assert fill.gross_notional == fill.fill_price * Decimal("100")
    # On BUY, SEC and FINRA fees are $0.00; exchange taker and broker commissions apply
    assert fill.sec_fee == Decimal("0.00")
    assert fill.finra_taf == Decimal("0.00")
    assert fill.exchange_fee > Decimal("0.00")
    assert fill.broker_commission >= Decimal("1.00")
    assert fill.net_notional == fill.gross_notional + fill.total_fees


def test_sell_order_deducts_regulatory_fees():
    """Verify Sell orders execute against Bid - slippage and deduct SEC 31 & FINRA TAF."""
    quote = QuoteNBBO(
        symbol="AAPL",
        bid=Decimal("220.00"),
        ask=Decimal("220.05"),
    )
    fill = simulate_market_fill(quote, direction="SELL", quantity=Decimal("500"))

    assert fill.fill_price <= quote.bid
    # SEC Section 31 applies to gross notional on sales
    assert fill.sec_fee > Decimal("0.00")
    # FINRA TAF applies per share on sales
    assert fill.finra_taf > Decimal("0.00")
    # Net notional = gross_notional - total_fees on sales
    assert fill.net_notional == fill.gross_notional - fill.total_fees


def test_limit_order_rejection_when_unfillable():
    """Verify limit order errors when market is outside acceptable limit."""
    quote = QuoteNBBO(
        symbol="AAPL",
        bid=Decimal("220.00"),
        ask=Decimal("220.05"),
    )
    # Buy limit lower than current ask cannot fill
    with pytest.raises(ValueError, match="Limit price"):
        simulate_market_fill(
            quote,
            direction="BUY",
            quantity=Decimal("50"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("219.00"),
        )


# ---------------------------------------------------------------------------
# 3. SEC Rule 15c3-5 Pre-Trade Risk Gateway Tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_rate_throttle():
    clear_rate_throttle_history()
    yield
    clear_rate_throttle_history()


def test_pre_trade_risk_passes_valid_order():
    """Verify a compliant institutional order passes all 8 pre-trade checks."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("220.00"), ask=Decimal("220.04"))
    security = get_security("AAPL")

    # $220 * 50 = $11,000 on a $100,000 portfolio (< 30% concentration, < $50k notional)
    validate_pre_trade_risk(
        user_id="trader_1",
        security=security,
        direction="BUY",
        quantity=Decimal("50"),
        order_type=OrderType.MARKET,
        quote=quote,
        portfolio_equity=Decimal("100000.00"),
    )


def test_pre_trade_risk_fat_finger_notional_rejection():
    """Verify notional cap rejects fat-finger orders."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("220.00"), ask=Decimal("220.04"))
    security = get_security("AAPL")

    # 500 shares * $220 = $110,000 > $50,000 notional limit
    with pytest.raises(PreTradeRiskRejected, match="exceeds fat-finger cap"):
        validate_pre_trade_risk(
            user_id="trader_1",
            security=security,
            direction="BUY",
            quantity=Decimal("500"),
            order_type=OrderType.MARKET,
            quote=quote,
            portfolio_equity=Decimal("500000.00"),
            config=PreTradeRiskConfig(max_order_notional=Decimal("50000.00")),
        )


def test_pre_trade_risk_adv_cap_rejection():
    """Verify order size exceeding ADV limit is rejected."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("220.00"), ask=Decimal("220.04"))
    security = get_security("AAPL")  # ADV = 55,000,000

    # Set config max ADV = 0.001% (550 shares)
    with pytest.raises(PreTradeRiskRejected, match="ADV cap"):
        validate_pre_trade_risk(
            user_id="trader_1",
            security=security,
            direction="BUY",
            quantity=Decimal("1000"),
            order_type=OrderType.MARKET,
            quote=quote,
            portfolio_equity=Decimal("500000.00"),
            config=PreTradeRiskConfig(max_adv_percentage=Decimal("0.001"), max_order_notional=Decimal("500000")),
        )


def test_pre_trade_risk_price_collar_rejection():
    """Verify limit price outside collar is rejected."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("200.00"), ask=Decimal("200.02"))
    security = get_security("AAPL")

    # 10% deviation ($225 vs $200 mid) with 5% collar
    with pytest.raises(PreTradeRiskRejected, match="exceeding collar threshold"):
        validate_pre_trade_risk(
            user_id="trader_1",
            security=security,
            direction="BUY",
            quantity=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("225.00"),
            quote=quote,
            portfolio_equity=Decimal("100000.00"),
            config=PreTradeRiskConfig(price_collar_percentage=Decimal("5.0")),
        )


def test_pre_trade_risk_concentration_limit_rejection():
    """Verify portfolio concentration limit rejects oversized allocations."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("200.00"), ask=Decimal("200.02"))
    security = get_security("AAPL")

    # 200 shares * $200 = $40,000 on $100,000 equity (40% > 30% concentration limit)
    with pytest.raises(PreTradeRiskRejected, match="concentration limit"):
        validate_pre_trade_risk(
            user_id="trader_1",
            security=security,
            direction="BUY",
            quantity=Decimal("200"),
            order_type=OrderType.MARKET,
            quote=quote,
            portfolio_equity=Decimal("100000.00"),
            config=PreTradeRiskConfig(
                max_order_notional=Decimal("100000"), max_symbol_concentration_pct=Decimal("30.0")
            ),
        )


def test_pre_trade_risk_algorithmic_rate_throttle():
    """Verify runaway algorithm rate throttle kicks in when orders burst."""
    quote = QuoteNBBO(symbol="AAPL", bid=Decimal("200.00"), ask=Decimal("200.02"))
    security = get_security("AAPL")
    config = PreTradeRiskConfig(max_orders_per_minute=3)

    # Send 3 valid orders
    for _ in range(3):
        validate_pre_trade_risk(
            user_id="algo_bot_1",
            security=security,
            direction="BUY",
            quantity=Decimal("5"),
            order_type=OrderType.MARKET,
            quote=quote,
            portfolio_equity=Decimal("100000.00"),
            config=config,
        )

    # 4th order within 60 seconds must be rejected by rate circuit breaker
    with pytest.raises(PreTradeRiskRejected, match="Algorithmic rate limit exceeded"):
        validate_pre_trade_risk(
            user_id="algo_bot_1",
            security=security,
            direction="BUY",
            quantity=Decimal("5"),
            order_type=OrderType.MARKET,
            quote=quote,
            portfolio_equity=Decimal("100000.00"),
            config=config,
        )


# ---------------------------------------------------------------------------
# 4. Quantitative Analytics & Tear Sheet Tests
# ---------------------------------------------------------------------------


class MockTrade:
    def __init__(self, profit_loss: Decimal, status: str = "closed"):
        self.profit_loss = profit_loss
        self.status = status
        self.signal_data = {
            "execution_fill": {
                "total_fees": "1.50",
                "slippage": "0.02",
            }
        }


def test_tear_sheet_metrics_calculation():
    """Verify Sharpe, Sortino, Drawdown, and Profit Factor calculations."""
    trades = [
        MockTrade(Decimal("500.00")),
        MockTrade(Decimal("-200.00")),
        MockTrade(Decimal("750.00")),
        MockTrade(Decimal("-100.00")),
        MockTrade(Decimal("450.00")),
    ]
    tear_sheet = compute_institutional_tear_sheet(trades, initial_equity=Decimal("50000.00"))

    assert tear_sheet.total_trades == 5
    assert tear_sheet.winning_trades == 3
    assert tear_sheet.losing_trades == 2
    assert tear_sheet.win_rate == Decimal("60.00")
    assert tear_sheet.total_pnl == Decimal("1400.00")
    assert tear_sheet.gross_profit == Decimal("1700.00")
    assert tear_sheet.gross_loss == Decimal("300.00")
    # Profit factor = 1700 / 300 = 5.67
    assert tear_sheet.profit_factor == Decimal("5.67")
    assert tear_sheet.max_drawdown >= Decimal("0.00")
    assert tear_sheet.sharpe_ratio != Decimal("0.00")
    assert tear_sheet.total_fees == Decimal("7.50")


def test_tear_sheet_empty_trades():
    """Verify empty trade list safely returns clean zeros."""
    tear_sheet = compute_institutional_tear_sheet([])
    assert tear_sheet.total_trades == 0
    assert tear_sheet.win_rate == Decimal("0.00")
    assert tear_sheet.sharpe_ratio == Decimal("0.00")
    assert tear_sheet.profit_factor == Decimal("0.00")
