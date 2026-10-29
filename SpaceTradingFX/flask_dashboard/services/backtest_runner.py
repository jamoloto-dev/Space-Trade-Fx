"""
Space-Trade-Fx Vectorized Strategy Backtesting Engine.

Executes strategies transpiled by SpaceTradeStrategyEngine against historical OHLCV data
and computes comprehensive institutional performance metrics, Sharpe ratios, drawdowns,
and equity curve series.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .strategy_transpiler import SpaceTradeStrategyEngine

logger = logging.getLogger("space_trading_fx.backtest_runner")


@dataclass
class BacktestConfig:
    """Configuration settings for strategy backtesting."""

    initial_capital: float = 10000.0
    lot_size: float = 0.10
    contract_size: float = 100000.0  # Standard Forex Lot
    spread_pips: float = 1.5
    slippage_pips: float = 0.5
    pip_size: float = 0.0001
    commission_per_lot: float = 7.0
    risk_free_rate_annual: float = 0.04


@dataclass
class BacktestReport:
    """Comprehensive institutional tear sheet report."""

    initial_capital: float
    ending_capital: float
    total_net_profit: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_dollars: float
    max_drawdown_pct: float
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpaceTradeBacktestRunner:
    """
    Space-Trade-Fx Institutional Vectorized Backtesting Engine.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.transpiler = SpaceTradeStrategyEngine()
        self.logger = logger

    def generate_synthetic_ohlcv(
        self,
        symbol: str = "EURUSD",
        bars: int = 500,
        start_price: float = 1.1000,
    ) -> pd.DataFrame:
        """Generate realistic synthetic OHLCV bars for testing and demonstration."""
        np.random.seed(42)
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=bars, freq="1h")
        volatility = 0.0008
        returns = np.random.normal(0.00005, volatility, size=bars)
        price_path = start_price * np.exp(np.cumsum(returns))

        highs = price_path + np.abs(np.random.normal(0, volatility * 0.7, size=bars))
        lows = price_path - np.abs(np.random.normal(0, volatility * 0.7, size=bars))
        opens = np.roll(price_path, 1)
        opens[0] = start_price
        volumes = np.random.randint(500, 5000, size=bars)

        df = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(highs, np.maximum(opens, price_path)),
                "low": np.minimum(lows, np.minimum(opens, price_path)),
                "close": price_path,
                "volume": volumes,
            },
            index=dates,
        )
        return df

    def run_backtest(
        self,
        strategy_instance: Any,
        data: pd.DataFrame,
    ) -> BacktestReport:
        """
        Execute backtest against a strategy instance with compute_indicators/generate_signals.
        """
        if data.empty or "close" not in data.columns:
            raise ValueError("Data must be a non-empty DataFrame containing 'close' column.")

        # Compute signals
        signals_df = strategy_instance.generate_signals(data)
        if "signal" not in signals_df.columns:
            raise ValueError("Strategy must generate a 'signal' column (+1, -1, 0).")

        cfg = self.config
        capital = cfg.initial_capital
        peak_equity = capital
        max_dd_dollars = 0.0
        max_dd_pct = 0.0

        current_pos: dict[str, Any] | None = None
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        returns_list: list[float] = []

        pip_cost = (cfg.spread_pips + cfg.slippage_pips) * cfg.pip_size

        for i in range(len(signals_df)):
            row = signals_df.iloc[i]
            bar_time = str(signals_df.index[i])
            close_px = float(row["close"])
            sig = int(row.get("signal", 0))

            # Update floating equity on open position
            floating_pnl = 0.0
            if current_pos:
                price_delta = close_px - current_pos["entry_price"]
                if current_pos["type"] == -1:  # SELL
                    price_delta = -price_delta
                floating_pnl = price_delta * current_pos["lots"] * cfg.contract_size

            bar_equity = capital + floating_pnl
            if bar_equity > peak_equity:
                peak_equity = bar_equity
            dd_dollars = peak_equity - bar_equity
            dd_pct = (dd_dollars / peak_equity * 100.0) if peak_equity > 0 else 0.0
            if dd_dollars > max_dd_dollars:
                max_dd_dollars = dd_dollars
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            equity_curve.append(
                {
                    "time": bar_time,
                    "balance": round(capital, 2),
                    "equity": round(bar_equity, 2),
                    "drawdown_pct": round(dd_pct, 2),
                }
            )

            # Signal evaluation for entry / exit
            if sig != 0:
                # Close existing opposite position
                if current_pos and current_pos["type"] != sig:
                    close_px_adj = close_px - (pip_cost if current_pos["type"] == 1 else -pip_cost)
                    pnl = (close_px_adj - current_pos["entry_price"]) * current_pos["lots"] * cfg.contract_size
                    if current_pos["type"] == -1:
                        pnl = -pnl
                    pnl -= cfg.commission_per_lot * current_pos["lots"]

                    capital += pnl
                    trades.append(
                        {
                            "entry_time": current_pos["entry_time"],
                            "exit_time": bar_time,
                            "type": "BUY" if current_pos["type"] == 1 else "SELL",
                            "lots": current_pos["lots"],
                            "entry_price": round(current_pos["entry_price"], 5),
                            "exit_price": round(close_px_adj, 5),
                            "profit_loss": round(pnl, 2),
                        }
                    )
                    ret = pnl / capital if capital > 0 else 0.0
                    returns_list.append(ret)
                    current_pos = None

                # Open new position if flat
                if not current_pos:
                    entry_px = close_px + (pip_cost if sig == 1 else -pip_cost)
                    current_pos = {
                        "type": sig,
                        "entry_time": bar_time,
                        "entry_price": entry_px,
                        "lots": cfg.lot_size,
                    }

        # Close open position at end of backtest
        if current_pos:
            last_row = signals_df.iloc[-1]
            last_close = float(last_row["close"])
            pnl = (last_close - current_pos["entry_price"]) * current_pos["lots"] * cfg.contract_size
            if current_pos["type"] == -1:
                pnl = -pnl
            capital += pnl
            trades.append(
                {
                    "entry_time": current_pos["entry_time"],
                    "exit_time": str(signals_df.index[-1]),
                    "type": "BUY" if current_pos["type"] == 1 else "SELL",
                    "lots": current_pos["lots"],
                    "entry_price": round(current_pos["entry_price"], 5),
                    "exit_price": round(last_close, 5),
                    "profit_loss": round(pnl, 2),
                }
            )

        # Performance summary
        total_profit = capital - cfg.initial_capital
        total_return_pct = (total_profit / cfg.initial_capital) * 100.0
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["profit_loss"] > 0)
        losing_trades = sum(1 for t in trades if t["profit_loss"] <= 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t["profit_loss"] for t in trades if t["profit_loss"] > 0)
        gross_loss = abs(sum(t["profit_loss"] for t in trades if t["profit_loss"] < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

        # Sharpe ratio calculation
        sharpe: float = 0.0
        if len(returns_list) > 2:
            std_dev = float(np.std(returns_list))
            mean_ret = float(np.mean(returns_list))
            daily_rf = cfg.risk_free_rate_annual / 252.0
            sharpe_calc = (mean_ret - daily_rf) / (std_dev + 1e-9) * math.sqrt(252.0)
            sharpe = round(float(sharpe_calc), 2)

        return BacktestReport(
            initial_capital=round(cfg.initial_capital, 2),
            ending_capital=round(capital, 2),
            total_net_profit=round(total_profit, 2),
            total_return_pct=round(total_return_pct, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=round(win_rate, 1),
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            max_drawdown_dollars=round(max_dd_dollars, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            equity_curve=equity_curve,
            trades=trades,
        )

    def backtest_source_code(
        self,
        source_code: str,
        source_language: str = "mq4",
        symbol: str = "EURUSD",
        bars: int = 300,
        data: pd.DataFrame | None = None,
    ) -> BacktestReport:
        """
        Transpiles source strategy code into Python and runs backtest immediately.
        """
        res = self.transpiler.transpile(
            source_code=source_code,
            target_language="python",
            source_language=source_language,
            strategy_name="BacktestCandidateStrategy",
        )
        if not res.success:
            raise RuntimeError(f"Strategy transpilation failed: {res.syntax_warnings}")

        namespace: dict[str, Any] = {}
        exec(res.target_code, namespace)  # noqa: S102
        strat_cls = namespace["BacktestCandidateStrategy"]
        strategy_instance = strat_cls(magic_number=88123, lot_size=self.config.lot_size)

        ohlcv = data if data is not None else self.generate_synthetic_ohlcv(symbol=symbol, bars=bars)
        return self.run_backtest(strategy_instance, ohlcv)
