"""Institutional Quantitative Analytics, Portfolio Tear Sheets, and Risk Attribution.

Computes annualized Sharpe ratio, Sortino ratio, Calmar ratio, maximum drawdown,
profit factor, payoff ratio, and Value at Risk (VaR) from trade ledgers and equity curves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Sequence


@dataclass(frozen=True)
class QuantitativeTearSheet:
    """Comprehensive performance and risk tear sheet to institutional standards."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    total_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: Decimal
    average_trade: Decimal
    average_win: Decimal
    average_loss: Decimal
    payoff_ratio: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    var_95: Decimal
    var_99: Decimal
    total_fees: Decimal
    average_slippage: Decimal


def _to_decimal(val: Any) -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")


def compute_institutional_tear_sheet(
    trades: Sequence[Any],
    initial_equity: Decimal = Decimal("100000.00"),
    risk_free_rate: Decimal = Decimal("0.045"),  # 4.5% US Treasury benchmark
) -> QuantitativeTearSheet:
    """Compute institutional performance and risk metrics from closed trades."""
    if initial_equity <= 0:
        initial_equity = Decimal("100000.00")

    closed_trades = [t for t in trades if getattr(t, "status", "") == "closed"]
    total_trades = len(closed_trades)

    if total_trades == 0:
        return QuantitativeTearSheet(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=Decimal("0.00"),
            total_pnl=Decimal("0.00"),
            gross_profit=Decimal("0.00"),
            gross_loss=Decimal("0.00"),
            profit_factor=Decimal("0.00"),
            average_trade=Decimal("0.00"),
            average_win=Decimal("0.00"),
            average_loss=Decimal("0.00"),
            payoff_ratio=Decimal("0.00"),
            max_drawdown=Decimal("0.00"),
            max_drawdown_pct=Decimal("0.00"),
            annualized_return=Decimal("0.00"),
            annualized_volatility=Decimal("0.00"),
            sharpe_ratio=Decimal("0.00"),
            sortino_ratio=Decimal("0.00"),
            calmar_ratio=Decimal("0.00"),
            var_95=Decimal("0.00"),
            var_99=Decimal("0.00"),
            total_fees=Decimal("0.00"),
            average_slippage=Decimal("0.00"),
        )

    pnls: list[Decimal] = []
    fees_list: list[Decimal] = []
    slippages: list[Decimal] = []

    gross_profit = Decimal("0.00")
    gross_loss = Decimal("0.00")
    winning_count = 0
    losing_count = 0

    for trade in closed_trades:
        pnl = _to_decimal(getattr(trade, "profit_loss", 0))
        pnls.append(pnl)
        if pnl > 0:
            gross_profit += pnl
            winning_count += 1
        elif pnl < 0:
            gross_loss += abs(pnl)
            losing_count += 1

        # Extract fee and slippage data from signal_data / metadata if present
        signal_data = getattr(trade, "signal_data", {}) or {}
        fill_meta = signal_data.get("execution_fill") or {}
        fees_list.append(_to_decimal(fill_meta.get("total_fees", 0)))
        slippages.append(_to_decimal(fill_meta.get("slippage", 0)))

    total_pnl = sum(pnls, Decimal("0.00"))
    win_rate = ((Decimal(winning_count) / Decimal(total_trades)) * Decimal("100")).quantize(Decimal("0.01"))

    profit_factor = (
        (gross_profit / gross_loss).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if gross_loss > 0
        else (Decimal("99.99") if gross_profit > 0 else Decimal("0.00"))
    )

    average_trade = (total_pnl / Decimal(total_trades)).quantize(Decimal("0.01"))
    average_win = (
        (gross_profit / Decimal(winning_count)).quantize(Decimal("0.01")) if winning_count > 0 else Decimal("0.00")
    )
    average_loss = (
        (gross_loss / Decimal(losing_count)).quantize(Decimal("0.01")) if losing_count > 0 else Decimal("0.00")
    )
    payoff_ratio = (average_win / average_loss).quantize(Decimal("0.01")) if average_loss > 0 else Decimal("0.00")

    # Compute Equity Curve and Maximum Drawdown
    running_equity = initial_equity
    peak_equity = initial_equity
    max_drawdown_dollars = Decimal("0.00")
    max_drawdown_pct = Decimal("0.00")
    returns_pct: list[float] = []

    for pnl in pnls:
        prior_equity = running_equity
        running_equity += pnl
        if running_equity > peak_equity:
            peak_equity = running_equity

        drawdown_dollars = peak_equity - running_equity
        if drawdown_dollars > max_drawdown_dollars:
            max_drawdown_dollars = drawdown_dollars
            if peak_equity > 0:
                dd_pct = (drawdown_dollars / peak_equity) * Decimal("100")
                if dd_pct > max_drawdown_pct:
                    max_drawdown_pct = dd_pct.quantize(Decimal("0.01"))

        if prior_equity > 0:
            returns_pct.append(float(pnl / prior_equity))

    # Annualized Return and Volatility
    # Assume 252 trading days/periods per year
    periods = max(1, len(returns_pct))
    mean_return = sum(returns_pct) / periods
    variance = sum((r - mean_return) ** 2 for r in returns_pct) / periods if periods > 1 else 0.0
    stdev = math.sqrt(variance)

    annualized_vol = Decimal(str(round(stdev * math.sqrt(252) * 100, 2)))
    annualized_return = (((running_equity - initial_equity) / initial_equity) * Decimal("100")).quantize(
        Decimal("0.01")
    )

    # Downside Volatility for Sortino Ratio
    downside_variance = sum(min(0.0, r) ** 2 for r in returns_pct) / periods if periods > 0 else 0.0
    downside_stdev = math.sqrt(downside_variance) * math.sqrt(252)

    # Sharpe & Sortino Calculations
    rf_daily = float(risk_free_rate) / 252.0
    excess_mean = (mean_return - rf_daily) * 252.0
    annual_stdev = stdev * math.sqrt(252)

    if annual_stdev > 0.0001:
        sharpe = Decimal(str(round(excess_mean / annual_stdev, 2)))
    else:
        sharpe = Decimal("0.00")

    if downside_stdev > 0.0001:
        sortino = Decimal(str(round(excess_mean / downside_stdev, 2)))
    else:
        sortino = Decimal("0.00")

    calmar = (
        (annualized_return / max_drawdown_pct).quantize(Decimal("0.01")) if max_drawdown_pct > 0 else Decimal("0.00")
    )

    # Parametric Value at Risk (VaR)
    # 95% = 1.645 stdev, 99% = 2.326 stdev
    var_95 = (initial_equity * Decimal(str(round(1.645 * stdev, 4)))).quantize(Decimal("0.01"))
    var_99 = (initial_equity * Decimal(str(round(2.326 * stdev, 4)))).quantize(Decimal("0.01"))

    total_fees = sum(fees_list, Decimal("0.00"))
    avg_slippage = (sum(slippages, Decimal("0.00")) / Decimal(total_trades)).quantize(Decimal("0.0001"))

    return QuantitativeTearSheet(
        total_trades=total_trades,
        winning_trades=winning_count,
        losing_trades=losing_count,
        win_rate=win_rate,
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        average_trade=average_trade,
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=payoff_ratio,
        max_drawdown=max_drawdown_dollars,
        max_drawdown_pct=max_drawdown_pct,
        annualized_return=annualized_return,
        annualized_volatility=annualized_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        var_95=var_95,
        var_99=var_99,
        total_fees=total_fees,
        average_slippage=avg_slippage,
    )
