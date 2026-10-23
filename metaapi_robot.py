#!/usr/bin/env python3
"""MetaApi Cloud Trading Robot.

Institutional-grade automated trading script connecting to MT4/MT5 accounts
via the metaapi-cloud-sdk and loading credentials securely from .env.
Features an autonomous scanning loop, live telemetry ingestion, AI adaptive
sentiment learning, dynamic position sizing, and strict risk guardrails with
inter-trade cooldown periods.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from dotenv import load_dotenv

# Explicitly invoke load_dotenv before reading any environment variables
load_dotenv()

try:
    from metaapi_cloud_sdk import MetaApi
except ImportError:
    MetaApi = None  # type: ignore[assignment,misc]

try:
    from analytics.order_flow import OrderFlowEngine
except ImportError:
    OrderFlowEngine = None  # type: ignore[assignment,misc]

try:
    from models.signal_engine import SignalEngine
except ImportError:
    SignalEngine = None  # type: ignore[assignment,misc]

try:
    from analytics.trailing_stop import TrailingStopManager
except ImportError:
    TrailingStopManager = None  # type: ignore[assignment,misc]


def setup_logging(log_file: str = "metaapi_robot.log") -> logging.Logger:
    """Configure comprehensive console and rotating file logging."""
    bot_logger = logging.getLogger("MetaApiRobot")
    bot_logger.setLevel(logging.INFO)

    if not bot_logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setFormatter(formatter)
        bot_logger.addHandler(c_handler)

        try:
            f_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
            f_handler.setFormatter(formatter)
            bot_logger.addHandler(f_handler)
        except Exception:
            pass

    return bot_logger


logger = setup_logging()


def check_token_format(token: str | None) -> dict[str, Any]:
    """Inspect and report whether the METAAPI_TOKEN is present and correctly formatted."""
    if not token or not str(token).strip():
        return {
            "present": False,
            "length": 0,
            "is_jwt": False,
            "masked": "None",
            "message": "Token is missing or empty.",
        }
    clean = str(token).strip()
    parts = clean.split(".")
    is_jwt = len(parts) == 3 and clean.startswith("ey")
    masked = f"{clean[:8]}...{clean[-6:]}" if len(clean) > 20 else "***"
    return {
        "present": True,
        "length": len(clean),
        "is_jwt": is_jwt,
        "masked": masked,
        "message": "Token is present and formatted as a valid JWT."
        if is_jwt
        else "Token is present but not standard JWT format.",
    }


def handle_metaapi_auth_error(exc: Exception, token: str | None = None) -> bool:
    """Check if exception is a 401 Unauthorized, log detailed diagnostics, and return True if handled."""
    status_code = getattr(exc, "status_code", None)
    err_msg = str(exc)
    is_401 = (status_code == 401) or ("401" in err_msg and ("Unauthorized" in err_msg or "unauthorized" in err_msg))
    if is_401:
        diag = check_token_format(token)
        logger.error(
            "❌ MetaApi Authentication 401 Unauthorized: Invalid or expired API token.\n"
            "   Token diagnostics:\n"
            "   - Present: %s\n"
            "   - Length: %s characters\n"
            "   - Format: %s\n"
            "   - Masked: %s\n"
            "   - Status: %s\n"
            "👉 Action required: Generate a fresh token from https://app.metaapi.cloud/token and update METAAPI_TOKEN in your .env file.",
            diag["present"],
            diag["length"],
            "Valid JWT" if diag["is_jwt"] else "Custom/Non-JWT string",
            diag["masked"],
            diag["message"],
        )
        return True
    return False


def load_credentials() -> tuple[str, str | None]:
    """Load API token and optional account ID from environment variables (.env)."""
    load_dotenv()
    token = os.getenv("METAAPI_TOKEN") or os.getenv("METAAPI_tOKEN") or os.getenv("META_API_TOKEN")
    diag = check_token_format(token)
    if not token or not diag["present"]:
        logger.error(
            "METAAPI_TOKEN not found in environment or .env file.\n"
            "Token diagnostics: Present: %s, Length: %s.\n"
            "Please add METAAPI_TOKEN=your_token to your .env file.",
            diag["present"],
            diag["length"],
        )
        sys.exit(1)

    account_id = os.getenv("METAAPI_ACCOUNT_ID") or os.getenv("ACCOUNT_ID")
    return token.strip(), account_id.strip() if account_id else None


async def resolve_account_id(api: MetaApi, requested_id: str | None = None) -> str:
    """Retrieve the specified account ID or auto-discover the first registered account."""
    if requested_id:
        return requested_id

    logger.info("No account ID specified. Discovering registered MetaApi accounts...")
    try:
        raw_res = await api.metatrader_account_api._metatrader_account_client.get_accounts({}, "2")
        items = (
            raw_res.get("items", []) if isinstance(raw_res, dict) else (raw_res if isinstance(raw_res, list) else [])
        )
        if not items:
            raise RuntimeError("No trading accounts found in MetaApi account registry.")

        account = items[0]
        acc_id = account.get("_id") or account.get("id")
        logger.info(
            "Auto-selected account: %s (Server: %s | Login: %s | State: %s)",
            acc_id,
            account.get("server"),
            account.get("login"),
            account.get("state"),
        )
        return str(acc_id)
    except Exception as exc:
        logger.error("Failed to discover MetaApi accounts: %s", exc)
        raise


async def fetch_account_information(connection) -> dict[str, Any]:
    """Fetch and print live account telemetry (currency, balance, equity, margin)."""
    logger.info("Querying live account telemetry...")
    info = await connection.get_account_information()

    currency = info.get("currency", "USD")
    raw_bal = float(info.get("balance", 0.0))
    credit = float(info.get("credit", 0.0))
    balance = raw_bal - credit if (credit > 0 and raw_bal > credit) else raw_bal
    equity = float(info.get("equity", 0.0))
    free_margin = float(info.get("freeMargin", 0.0))
    leverage = info.get("leverage", "1:100")
    server = info.get("server", "Unknown")

    print("\n" + "=" * 60)
    print("               LIVE METAAPI ACCOUNT TELEMETRY")
    print("=" * 60)
    print(f"  Broker Server : {server}")
    print(f"  Currency      : {currency}")
    print(f"  Balance       : {currency} {balance:,.2f} (Credit: {currency} {credit:,.2f})")
    print(f"  Equity        : {currency} {equity:,.2f}")
    print(f"  Free Margin   : {currency} {free_margin:,.2f}")
    print(f"  Leverage      : 1:{leverage}")
    print("=" * 60 + "\n")

    return info


def calculate_position_size(
    equity: float,
    risk_pct: float = 1.5,
    sl_pips: float = 25.0,
    pip_value_per_lot: float = 10.0,
    min_volume: float = 0.01,
    max_volume: float = 50.0,
    volume_step: float = 0.01,
) -> float:
    """Calculate dynamic position size based on account equity and strict risk limits."""
    if equity <= 0:
        return min_volume

    risk_capital = equity * (max(0.1, min(risk_pct, 10.0)) / 100.0)
    denom = max(1.0, sl_pips) * max(0.1, pip_value_per_lot)
    raw_lots = risk_capital / denom

    steps = round(raw_lots / volume_step)
    sized_lots = max(min_volume, steps * volume_step)
    final_lots = min(max_volume, sized_lots)

    logger.info(
        "Dynamic Position Sizing: Equity: $%.2f | Risk: %.1f%% ($%.2f) | SL: %.1f pips | Computed: %.3f lots -> Sized: %.2f lots",
        equity,
        risk_pct,
        risk_capital,
        sl_pips,
        raw_lots,
        final_lots,
    )
    return round(final_lots, 2)


def check_drawdown_circuit_breaker(
    starting_balance: float,
    current_equity: float,
    max_drawdown_pct: float = 5.0,
) -> tuple[bool, float]:
    """Halt trading if daily drawdown exceeds threshold (e.g. 5%)."""
    if starting_balance <= 0 or current_equity >= starting_balance:
        return False, 0.0

    drawdown_pct = ((starting_balance - current_equity) / starting_balance) * 100.0
    if drawdown_pct >= max_drawdown_pct:
        logger.warning(
            "🚨 DRAWDOWN CIRCUIT BREAKER TRIGGERED: Current Drawdown %.2f%% exceeds safety limit of %.2f%%! Trading halted.",
            drawdown_pct,
            max_drawdown_pct,
        )
        return True, drawdown_pct

    logger.info("Drawdown Check Passed: Current Drawdown %.2f%% (Limit: %.2f%%)", drawdown_pct, max_drawdown_pct)
    return False, drawdown_pct


def get_recent_trade_history(db_path: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Query recent trade outcomes from SQLite/trading.db to evaluate performance streaks."""
    if not db_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, "trading.db")

    if not os.path.isfile(db_path):
        return {
            "total_evaluated": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "consecutive_losses": 0,
            "risk_multiplier": 1.0,
        }

    try:
        import sqlite3

        with sqlite3.connect(db_path, timeout=3.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT profit_loss FROM trades WHERE status='closed' AND profit_loss IS NOT NULL ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

        if not rows:
            return {
                "total_evaluated": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "consecutive_losses": 0,
                "risk_multiplier": 1.0,
            }

        pnl_list = [float(r[0]) for r in rows]
        wins = sum(1 for p in pnl_list if p > 0)
        losses = sum(1 for p in pnl_list if p <= 0)
        win_rate = (wins / len(pnl_list)) * 100.0

        consecutive_losses = 0
        for p in pnl_list:
            if p <= 0:
                consecutive_losses += 1
            else:
                break

        risk_multiplier = 1.0
        if consecutive_losses >= 3:
            risk_multiplier = 0.5
        elif consecutive_losses >= 2:
            risk_multiplier = 0.75

        return {
            "total_evaluated": len(pnl_list),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "consecutive_losses": consecutive_losses,
            "risk_multiplier": risk_multiplier,
        }
    except Exception as exc:
        logger.debug("Trade history evaluation notice: %s", exc)
        return {
            "total_evaluated": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "consecutive_losses": 0,
            "risk_multiplier": 1.0,
        }


def evaluate_ai_context(symbol: str, action: str, db_path: str | None = None) -> dict[str, Any]:
    """Ingest macroeconomic news sentiment, AI Veto rules, and historical trade outcomes."""
    history = get_recent_trade_history(db_path)
    sentiment = {"score": 0.0, "sentiment": "NEUTRAL", "headline": "No active macro data"}
    ai_veto_active = False
    ai_veto_reason = None

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        stfx_dir = os.path.join(base_dir, "SpaceTradingFX")
        if stfx_dir not in sys.path:
            sys.path.insert(0, stfx_dir)
        from flask_dashboard.services.news_intelligence import check_ai_veto, evaluate_macro_sentiment

        raw_sym = symbol.split(".")[0].upper()
        sentiment = evaluate_macro_sentiment(raw_sym)
        ai_veto_active, ai_veto_reason = check_ai_veto(raw_sym, action, sentiment)
    except Exception as exc:
        logger.debug("AI news intelligence evaluation notice: %s", exc)

    return {
        "veto": ai_veto_active,
        "veto_reason": ai_veto_reason,
        "sentiment": sentiment,
        "history": history,
        "risk_multiplier": history.get("risk_multiplier", 1.0),
    }


def evaluate_market_signal(symbol: str, timeframe: str = "1H") -> dict[str, Any]:
    """Evaluate market technical indicators and return directional signal."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        stfx_dir = os.path.join(base_dir, "SpaceTradingFX")
        if stfx_dir not in sys.path:
            sys.path.insert(0, stfx_dir)
        from flask_dashboard.forex_data import LiveMarketScanner

        scanner = LiveMarketScanner()
        raw_sym = symbol.split(".")[0].upper()
        sig = scanner.analyze_signal(raw_sym, timeframe=timeframe)
        if "confidence" not in sig:
            sig["confidence"] = float(sig.get("strength", 50.0))
        return sig
    except Exception as exc:
        logger.debug("Market signal scanner evaluation notice for %s: %s", symbol, exc)
        return {
            "currency_pair": symbol,
            "signal": "HOLD",
            "strength": 50,
            "confidence": 50.0,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
        }


async def check_risk_guardrails(
    connection,
    symbol: str,
    lot_size: float,
    max_open_trades: int = 3,
    free_margin: float = 0.0,
    required_margin: float = 0.0,
) -> tuple[bool, str | None]:
    """Enforce exposure caps, duplicate positions, and free margin guardrails."""
    try:
        positions = await connection.get_positions()
    except Exception as exc:
        logger.warning("Could not query open positions: %s. Proceeding with caution.", exc)
        positions = []

    # 1. Concurrent open trades limit
    if len(positions) >= max_open_trades:
        reason = f"Exposure Cap Reached: Account has {len(positions)} open positions (Limit: {max_open_trades})."
        return False, reason

    # 2. Duplicate symbol exposure
    raw_sym = symbol.split(".")[0].upper()
    for pos in positions:
        pos_sym = str(pos.get("symbol", "")).split(".")[0].upper()
        if pos_sym == raw_sym:
            reason = (
                f"Duplicate Symbol Position: Active position ({pos.get('id')}) already exists for {pos.get('symbol')}."
            )
            return False, reason

    # 3. Free margin check
    if required_margin > 0 and free_margin < required_margin:
        reason = f"Insufficient Free Margin: Available ${free_margin:.2f} < Required ${required_margin:.2f}."
        return False, reason

    return True, None


async def resolve_tradable_symbol(connection, symbol: str) -> str:
    """Resolve symbol to broker-specific tradable symbol if base symbol is disabled (e.g. EURUSD -> EURUSD.ifx or T100 -> T100.ifx_m)."""
    try:
        spec = await connection.get_symbol_specification(symbol)
        if spec and spec.get("tradeMode") in {
            "SYMBOL_TRADE_MODE_FULL",
            "SYMBOL_TRADE_MODE_LONGONLY",
            "SYMBOL_TRADE_MODE_SHORTONLY",
        }:
            return symbol
    except Exception:
        pass

    clean_base = symbol.split(".")[0].rstrip("m").rstrip("_")
    candidates = [
        f"{symbol}_m",
        f"{symbol}.ifx",
        f"{symbol}.ifx_m",
        f"{clean_base}.ifx_m",
        f"{clean_base}.ifx",
        f"{clean_base}m",
        f"{clean_base}_m",
        f"{clean_base}.c",
        f"{clean_base}pro",
        f"{clean_base}+",
        f"{clean_base}.r",
    ]
    seen = {symbol}
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            cand_spec = await connection.get_symbol_specification(cand)
            if cand_spec and cand_spec.get("tradeMode") in {
                "SYMBOL_TRADE_MODE_FULL",
                "SYMBOL_TRADE_MODE_LONGONLY",
                "SYMBOL_TRADE_MODE_SHORTONLY",
            }:
                logger.info(
                    "Broker symbol auto-resolved: '%s' is disabled, using active tradable symbol '%s'",
                    symbol,
                    cand,
                )
                return cand
        except Exception:
            continue
    return symbol


async def monitor_open_positions(
    connection,
    interval: float = 10.0,
    stop_event: asyncio.Event | None = None,
    tp_pnl: float | None = None,
    sl_pnl: float | None = None,
    max_cycles: int | None = None,
    trailing_manager: TrailingStopManager | None = None,
) -> list[dict[str, Any]]:
    """Periodically fetch all open positions, log telemetry and P/L, and enforce TP/SL exits."""
    logger.info("📡 Position monitoring background worker started (interval: %.1fs)...", interval)
    cycle = 0
    all_closed: list[dict[str, Any]] = []

    while True:
        cycle += 1
        if stop_event and stop_event.is_set():
            logger.info("Position monitor received stop signal. Exiting worker loop.")
            break

        try:
            positions = await connection.get_positions()
            if not positions:
                logger.info("📊 [POSITION MONITOR] No open positions currently active on account.")
            else:
                logger.info("════════════════════════════════════════════════════════════")
                logger.info("   📊 OPEN POSITION MONITOR (%d ACTIVE)", len(positions))
                logger.info("════════════════════════════════════════════════════════════")
                for pos in positions:
                    pos_id = str(pos.get("id"))
                    symbol = pos.get("symbol", "Unknown")
                    pos_type = pos.get("type", "BUY")
                    vol = float(pos.get("volume", 0.0))
                    open_price = float(pos.get("openPrice", 0.0))
                    curr_price = float(pos.get("currentPrice", open_price))
                    pnl = float(pos.get("profit", 0.0))
                    sl = pos.get("stopLoss")
                    tp = pos.get("takeProfit")

                    action_str = "BUY" if "BUY" in str(pos_type).upper() else "SELL"
                    pnl_sign = "+" if pnl >= 0 else ""
                    logger.info(
                        "  • Ticket #%s: %s %s %.2f lots | Entry: %.5f -> Current: %.5f | P/L: %s$%.2f | SL: %s | TP: %s",
                        pos_id,
                        symbol,
                        action_str,
                        vol,
                        open_price,
                        curr_price,
                        pnl_sign,
                        pnl,
                        f"{float(sl):.5f}" if sl is not None else "None",
                        f"{float(tp):.5f}" if tp is not None else "None",
                    )

                    # Synchronize real-time floating P/L and lot size to local trading.db if present
                    try:
                        import sqlite3

                        db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")
                        if os.path.exists(db_file):
                            with sqlite3.connect(db_file, timeout=2.0) as db_conn:
                                cur = db_conn.cursor()
                                cur.execute(
                                    """
                                    UPDATE trades
                                    SET profit_loss = ?, lot_size = ?, updated_at = datetime('now')
                                    WHERE broker_order_id = ? OR mt5_ticket = ?
                                    """,
                                    (round(pnl, 2), round(vol, 2), pos_id, pos_id),
                                )
                                if cur.rowcount == 0:
                                    clean_sym = symbol.replace(".ifx", "").upper()
                                    cur.execute(
                                        """
                                        UPDATE trades
                                        SET broker_order_id = ?, mt5_ticket = ?, profit_loss = ?, lot_size = ?, updated_at = datetime('now')
                                        WHERE id IN (
                                            SELECT id FROM trades
                                            WHERE (currency_pair = ? OR currency_pair = ?)
                                              AND status = 'open'
                                              AND (broker_order_id IS NULL OR broker_order_id = '')
                                            LIMIT 1
                                        )
                                        """,
                                        (pos_id, pos_id, round(pnl, 2), round(vol, 2), clean_sym, symbol),
                                    )
                                db_conn.commit()
                    except Exception as db_err:
                        logger.debug("Local db sync from monitor skipped: %s", db_err)

                    # Target & Risk Enforcement (TP/SL)
                    should_close = False
                    close_reason = ""

                    # 1. Floating P/L targets (dollar-based)
                    if tp_pnl is not None and pnl >= tp_pnl:
                        should_close = True
                        close_reason = f"Take-Profit Target Hit: Floating P/L (${pnl:+.2f}) >= Target (+${tp_pnl:.2f})"
                    elif sl_pnl is not None and pnl <= -abs(sl_pnl):
                        should_close = True
                        close_reason = (
                            f"Stop-Loss Threshold Hit: Floating P/L (${pnl:+.2f}) <= Max Loss (-${abs(sl_pnl):.2f})"
                        )

                    # 2. Price-level breaches
                    if not should_close and sl is not None:
                        sl_val = float(sl)
                        if (action_str == "BUY" and curr_price <= sl_val) or (
                            action_str == "SELL" and curr_price >= sl_val
                        ):
                            should_close = True
                            close_reason = f"Stop-Loss Level Hit: Price {curr_price:.5f} breached SL {sl_val:.5f}"

                    if not should_close and tp is not None:
                        tp_val = float(tp)
                        if (action_str == "BUY" and curr_price >= tp_val) or (
                            action_str == "SELL" and curr_price <= tp_val
                        ):
                            should_close = True
                            close_reason = f"Take-Profit Level Hit: Price {curr_price:.5f} reached TP {tp_val:.5f}"

                    if should_close:
                        logger.info(
                            "🎯 Initiating automated position close for #%s (%s): %s", pos_id, symbol, close_reason
                        )
                        try:
                            close_res = await connection.close_position(pos_id)
                            closed_info = {
                                "position_id": pos_id,
                                "symbol": symbol,
                                "reason": close_reason,
                                "result": close_res,
                            }
                            all_closed.append(closed_info)
                            logger.info(
                                "✅ Position #%s Successfully Closed via MetaApi RPC! Result: %s",
                                pos_id,
                                close_res.get("orderId") or close_res.get("numericCode") or "CLOSED",
                            )
                        except Exception as close_err:
                            logger.error("❌ Failed to close position #%s: %s", pos_id, close_err)
                    elif trailing_manager:
                        # 3. Automated Break-Even & Trailing Stop Management
                        try:
                            be_eval = trailing_manager.evaluate_and_trail(
                                position=pos,
                                current_market_price=curr_price,
                            )
                            if be_eval.get("should_modify"):
                                new_be_sl = be_eval["new_stop_loss"]
                                logger.info(
                                    "🛡️ [BREAK-EVEN TRAILING STOP] Position #%s (%s): %s",
                                    pos_id,
                                    symbol,
                                    be_eval.get("reason"),
                                )
                                await connection.modify_position(
                                    position_id=pos_id,
                                    stop_loss=new_be_sl,
                                    take_profit=tp,
                                )
                                logger.info(
                                    "✅ Position #%s SL successfully updated to Break-Even (%.5f)!",
                                    pos_id,
                                    new_be_sl,
                                )
                        except Exception as trail_exc:
                            logger.error(
                                "❌ Failed to modify break-even SL for position #%s: %s",
                                pos_id,
                                trail_exc,
                            )

        except Exception as exc:
            # Resilience: Catch network hiccups and transient errors without crashing
            logger.warning("Transient notice in position monitoring worker: %s", exc)

        if max_cycles and cycle >= max_cycles:
            logger.info("Position monitor reached max cycles (%d). Exiting.", max_cycles)
            break

        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(interval)

    return all_closed


async def execute_market_order(
    connection,
    symbol: str,
    volume: float,
    action: str = "BUY",
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> dict[str, Any]:
    """Place a market order (BUY/SELL) with comprehensive error handling and logging."""
    action_clean = action.strip().upper()
    if action_clean not in {"BUY", "SELL"}:
        raise ValueError(f"Invalid order action: {action}. Expected 'BUY' or 'SELL'.")

    actual_symbol = await resolve_tradable_symbol(connection, symbol)

    logger.info(
        "Submitting %s market order: %s lots of %s (SL: %s, TP: %s)...",
        action_clean,
        volume,
        actual_symbol,
        stop_loss if stop_loss is not None else "None",
        take_profit if take_profit is not None else "None",
    )

    try:
        if action_clean == "BUY":
            res = await connection.create_market_buy_order(
                symbol=actual_symbol,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        else:
            res = await connection.create_market_sell_order(
                symbol=actual_symbol,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

        order_id = res.get("orderId") or res.get("numericCode")
        logger.info(
            "✅ %s Order Successfully Filled! Ticket ID: %s | Position ID: %s | SL: %s | TP: %s",
            action_clean,
            order_id,
            res.get("positionId"),
            stop_loss,
            take_profit,
        )
        return res

    except Exception as exc:
        logger.error(
            "❌ Market %s order execution failed for %s (%s lots): %s",
            action_clean,
            symbol,
            volume,
            exc,
        )
        raise


async def run_trading_robot(
    symbol: str = "EURUSD",
    symbols: list[str] | None = None,
    volume: float | None = None,
    action: str | None = None,
    account_id: str | None = None,
    execute_order: bool = True,
    risk_pct: float = 1.5,
    max_open_trades: int = 3,
    max_drawdown_pct: float = 5.0,
    sl_pips: float = 25.0,
    tp_pips: float = 50.0,
    min_confidence: float = 80.0,
    loop: bool = False,
    interval_seconds: float = 30.0,
    cooldown_seconds: float = 60.0,
    max_cycles: int | None = None,
    monitor_positions: bool = True,
    monitor_interval: float = 10.0,
    tp_pnl: float | None = None,
    sl_pnl: float | None = None,
    auto_be: bool = False,
    be_trigger_pips: float = 20.0,
    be_buffer_pips: float = 2.0,
) -> None:
    """Core autonomous trading loop: monitor telemetry, evaluate AI signals, manage risk, and trade."""
    token, env_account_id = load_credentials()
    target_account_id = account_id or env_account_id

    if MetaApi is None:
        raise ImportError(
            "metaapi-cloud-sdk is required to connect to MetaApi. "
            "Please install it using: pip install metaapi-cloud-sdk"
        )

    logger.info("Initializing MetaApi client...")
    diag = check_token_format(token)
    logger.info(
        "MetaApi token verified (Present: %s, Length: %s, Format: %s, Masked: %s)",
        diag["present"],
        diag["length"],
        "Valid JWT" if diag["is_jwt"] else "String",
        diag["masked"],
    )
    api = MetaApi(token=token)

    connection = None
    target_symbols = symbols if symbols else [symbol]
    last_trade_time: float = 0.0
    cycle_count = 0
    stop_event = asyncio.Event()
    monitor_task = None

    order_flow = OrderFlowEngine(window_size=100) if OrderFlowEngine else None
    signal_engine = SignalEngine(confidence_threshold=min_confidence / 100.0) if SignalEngine else None
    trailing_manager = (
        TrailingStopManager(trigger_pips=be_trigger_pips, buffer_pips=be_buffer_pips)
        if (auto_be and TrailingStopManager)
        else None
    )

    try:
        # Step 1: Resolve Account
        resolved_id = await resolve_account_id(api, target_account_id)
        logger.info("Retrieving account instance [%s]...", resolved_id)
        account = await api.metatrader_account_api.get_account(resolved_id)

        # Step 2: Ensure Account is Deployed & Connected
        if account.state != "DEPLOYED":
            logger.info("Deploying MetaApi cloud account instance (current state: %s)...", account.state)
            try:
                await account.deploy()
            except Exception as deploy_err:
                logger.error(
                    "Account deployment declined by MetaApi: %s\n"
                    "👉 Tip: Ensure your MetaApi account has cloud credits or deploy the account on the MetaApi web dashboard.",
                    deploy_err,
                )
                raise

        logger.info("Waiting for account terminal to connect to broker server...")
        await account.wait_connected()
        logger.info("Broker terminal connected (Connection status: %s).", account.connection_status)

        # Step 3: Establish RPC connection and synchronize terminal state
        logger.info("Opening RPC connection and synchronizing market state...")
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        logger.info("Terminal synchronized successfully.")

        # Step 4: Launch Concurrent Position Monitoring Worker
        if monitor_positions:
            monitor_task = asyncio.create_task(
                monitor_open_positions(
                    connection=connection,
                    interval=monitor_interval,
                    stop_event=stop_event,
                    tp_pnl=tp_pnl,
                    sl_pnl=sl_pnl,
                    trailing_manager=trailing_manager,
                )
            )

        # Step 5: Autonomous Scanning & Execution Loop
        while True:
            cycle_count += 1
            now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            logger.info("════════════════════════════════════════════════════════════")
            logger.info("   AUTONOMOUS SCAN CYCLE #%d [%s]", cycle_count, now_utc_str)
            logger.info("════════════════════════════════════════════════════════════")

            # 5.1. Query Live Account Telemetry (Balance and Equity)
            acct_info = await fetch_account_information(connection)
            raw_bal = float(acct_info.get("balance", 0.0))
            credit = float(acct_info.get("credit", 0.0))
            balance = raw_bal - credit if (credit > 0 and raw_bal > credit) else raw_bal
            equity = float(acct_info.get("equity", balance))
            free_margin = float(acct_info.get("freeMargin", equity))

            # 5.2. Drawdown Circuit Breaker
            is_circuit_broken, dd_pct = check_drawdown_circuit_breaker(
                starting_balance=balance,
                current_equity=equity,
                max_drawdown_pct=max_drawdown_pct,
            )
            if is_circuit_broken:
                logger.warning("Daily drawdown limit reached (%.2f%%). Pausing cycle for next interval.", dd_pct)
                if not loop or (max_cycles and cycle_count >= max_cycles):
                    break
                await asyncio.sleep(interval_seconds)
                continue

            # 5.3. Trade Cooldown Waiting Period (Prevent Over-Trading)
            now_ts = time.time()
            elapsed_since_trade = now_ts - last_trade_time
            if last_trade_time > 0 and elapsed_since_trade < cooldown_seconds:
                remaining_wait = cooldown_seconds - elapsed_since_trade
                logger.info(
                    "⏳ Trade Cooldown Active: %.1fs remaining of %.1fs waiting period. Pausing trade execution.",
                    remaining_wait,
                    cooldown_seconds,
                )
                if not loop or (max_cycles and cycle_count >= max_cycles):
                    break
                await asyncio.sleep(interval_seconds)
                continue

            # 5.4. Evaluate AI Signals & Strategy across monitored symbols
            order_executed_this_cycle = False
            for sym in target_symbols:
                # Restrict volatile indices (e.g. T100, USTEC, NAS100)
                if any(idx in sym.upper() for idx in ("T100", "USTEC", "NAS100", "US30", "GER30")):
                    logger.warning(
                        "Symbol %s restricted: Volatile index trading disabled to protect capital. Skipping.", sym
                    )
                    continue

                actual_sym = await resolve_tradable_symbol(connection, sym)

                # Guardrail check: max open trades and duplicate symbol position
                guardrail_passed, guardrail_reason = await check_risk_guardrails(
                    connection=connection,
                    symbol=actual_sym,
                    lot_size=0.01,
                    max_open_trades=max_open_trades,
                    free_margin=free_margin,
                    required_margin=0.0,
                )
                if not guardrail_passed:
                    logger.info("Guardrail active for %s: %s", actual_sym, guardrail_reason)
                    continue

                # Strategy signal evaluation
                signal_data = evaluate_market_signal(sym)
                target_action = action if action else signal_data.get("signal", "HOLD")
                confidence = float(signal_data.get("confidence", signal_data.get("strength", 50.0)))

                if target_action not in {"BUY", "SELL"}:
                    logger.info(
                        "Market scan for %s: %s (Confidence: %.1f%%). No trade action required.",
                        sym,
                        target_action,
                        confidence,
                    )
                    continue

                # Strict Trend Filter (200 EMA): Never fight the trend!
                indicators = signal_data.get("indicators", {})
                ema200 = indicators.get("ema200")
                market_price = float(signal_data.get("price") or signal_data.get("entry_price") or 0.0)
                if ema200 and market_price > 0:
                    if target_action == "BUY" and market_price < ema200:
                        logger.warning(
                            "🚨 Strict Trend Filter Block: Refusing BUY for %s because price (%.5f) is below 200 EMA (%.5f) (Bearish Regime). Never fighting the trend.",
                            sym,
                            market_price,
                            ema200,
                        )
                        continue
                    elif target_action == "SELL" and market_price > ema200:
                        logger.warning(
                            "🚨 Strict Trend Filter Block: Refusing SELL for %s because price (%.5f) is above 200 EMA (%.5f) (Bullish Regime). Never fighting the trend.",
                            sym,
                            market_price,
                            ema200,
                        )
                        continue

                if confidence < min_confidence and not action:
                    logger.info(
                        "Signal %s for %s confidence %.1f%% < minimum %.1f%% (80%%+ high-probability threshold). Skipping.",
                        target_action,
                        sym,
                        confidence,
                        min_confidence,
                    )
                    continue

                # AI Adaptive Context & News Sentiment Veto
                ai_ctx = evaluate_ai_context(sym, target_action)
                if ai_ctx.get("veto"):
                    logger.warning(
                        "AI Veto Gate triggered for %s %s: %s. Order execution blocked.",
                        sym,
                        target_action,
                        ai_ctx.get("veto_reason"),
                    )
                    continue

                # Ingest real-time price into Order Flow Analytics Engine
                try:
                    price_info = await connection.get_symbol_price(actual_sym)
                except Exception:
                    price_info = None

                if price_info and order_flow:
                    order_flow.ingest_metaapi_price(price_info)

                # Order Flow Imbalance & ML Signal Confidence Scoring
                final_confidence = confidence
                if signal_engine and not action:
                    of_imbalance = order_flow.calculate_imbalance() if order_flow else 0.0
                    macro_sent = (
                        float(ai_ctx.get("sentiment", {}).get("score", 0.0))
                        if isinstance(ai_ctx.get("sentiment"), dict)
                        else 0.0
                    )
                    ml_eval = signal_engine.evaluate_signal(
                        order_flow_imbalance=of_imbalance,
                        technical_score=confidence,
                        macro_sentiment=macro_sent,
                        symbol=actual_sym,
                        direction=target_action,
                    )
                    final_confidence = float(ml_eval.get("confidence", confidence))
                    if not ml_eval.get("execute", True):
                        logger.info(
                            "ML Signal Confidence %.1f%% below threshold %.1f%% for %s %s. Skipping order.",
                            final_confidence,
                            ml_eval.get("threshold", min_confidence),
                            actual_sym,
                            target_action,
                        )
                        continue

                # 5.5. Dynamic Balance-Aware Position Sizing
                adjusted_risk_pct = risk_pct * float(ai_ctx.get("risk_multiplier", 1.0))
                try:
                    spec = await connection.get_symbol_specification(actual_sym)
                    min_vol = float(spec.get("minVolume", 0.01))
                    max_vol = float(spec.get("maxVolume", 50.0))
                    vol_step = float(spec.get("volumeStep", 0.01))
                    digits = int(spec.get("digits", 5))
                    pip_size = float(spec.get("pipSize", 0.0001))
                except Exception:
                    min_vol, max_vol, vol_step, digits, pip_size = 0.01, 50.0, 0.01, 5, 0.0001

                sized_volume = (
                    volume
                    if volume is not None
                    else calculate_position_size(
                        equity=equity,
                        risk_pct=adjusted_risk_pct,
                        sl_pips=sl_pips,
                        min_volume=min_vol,
                        max_volume=max_vol,
                        volume_step=vol_step,
                    )
                )

                leverage = float(acct_info.get("leverage", 100))
                approx_req_margin = (sized_volume * 100000.0) / max(1.0, leverage)
                margin_passed, margin_reason = await check_risk_guardrails(
                    connection=connection,
                    symbol=actual_sym,
                    lot_size=sized_volume,
                    max_open_trades=max_open_trades,
                    free_margin=free_margin,
                    required_margin=approx_req_margin,
                )
                if not margin_passed:
                    logger.warning("Order on %s halted by margin check: %s", actual_sym, margin_reason)
                    continue

                # 5.6. Enforce Stop Loss and Take Profit Brackets
                try:
                    price_info = await connection.get_symbol_price(actual_sym)
                    entry = (
                        float(price_info.get("ask" if target_action.upper() == "BUY" else "bid", 1.0))
                        if price_info
                        else 1.08500
                    )
                except Exception:
                    entry = 1.08500

                if target_action.upper() == "BUY":
                    calc_sl = round(entry - (sl_pips * pip_size), digits)
                    calc_tp = round(entry + (tp_pips * pip_size), digits)
                else:
                    calc_sl = round(entry + (sl_pips * pip_size), digits)
                    calc_tp = round(entry - (tp_pips * pip_size), digits)

                # 5.7. Execute Market Order Directly via MetaApi RPC Connection
                if execute_order:
                    logger.info(
                        "Dispatched Market Order: %s %s (%.2f lots, SL: %s, TP: %s) via MetaApi RPC...",
                        target_action,
                        actual_sym,
                        sized_volume,
                        calc_sl,
                        calc_tp,
                    )
                    try:
                        trade_res = await execute_market_order(
                            connection=connection,
                            symbol=actual_sym,
                            volume=sized_volume,
                            action=target_action,
                            stop_loss=calc_sl,
                            take_profit=calc_tp,
                        )
                        if signal_engine and trade_res:
                            ticket_id = str(trade_res.get("orderId") or trade_res.get("numericCode") or "")
                            signal_engine.log_trade_outcome(
                                symbol=actual_sym,
                                actual_profit=0.0,
                                confidence=final_confidence,
                                ticket=ticket_id,
                            )
                        last_trade_time = time.time()
                        order_executed_this_cycle = True
                        logger.info(
                            "Order confirmed in MetaTrader terminal. Initializing %s-second trade cooldown.",
                            cooldown_seconds,
                        )
                        break
                    except Exception as exec_err:
                        logger.error(
                            "Transient order execution failure for %s: %s. Continuing monitoring.",
                            actual_sym,
                            exec_err,
                        )
                else:
                    logger.info("Execution flag not set. Skipping live order dispatch.")

            if not loop or (max_cycles and cycle_count >= max_cycles):
                logger.info("Autonomous execution finished (%d cycle completed). Exiting.", cycle_count)
                break

            sleep_dur = cooldown_seconds if order_executed_this_cycle else interval_seconds
            logger.info("Waiting %.1fs until next market scan cycle...", sleep_dur)
            await asyncio.sleep(sleep_dur)

    except Exception as exc:
        handle_metaapi_auth_error(exc, token)
        raise

    finally:
        stop_event.set()
        if monitor_task and not monitor_task.done():
            try:
                await asyncio.wait_for(monitor_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                monitor_task.cancel()
        if connection:
            logger.info("Closing RPC connection cleanly...")
            try:
                await connection.close()
            except Exception as close_exc:
                logger.warning("Notice on connection closure: %s", close_exc)
        logger.info("Robot routine completed.")


def main():
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(description="MetaApi Cloud Autonomous Trading Robot")
    parser.add_argument(
        "--symbols",
        default="EURUSD.ifx,GBPUSD.ifx,USDJPY.ifx",
        help="Comma-separated symbols to monitor (default: EURUSD.ifx,GBPUSD.ifx,USDJPY.ifx)",
    )
    parser.add_argument("--symbol", help="Single symbol shorthand (overrides --symbols if specified)")
    parser.add_argument(
        "--volume",
        type=float,
        default=None,
        help="Optional lot size override (if omitted, dynamically calculated based on account equity)",
    )
    parser.add_argument(
        "--action",
        choices=["BUY", "SELL"],
        default=None,
        help="Optional manual order action override (default: dynamic strategy evaluation)",
    )
    parser.add_argument("--account-id", help="MetaApi Account ID (default: read from METAAPI_ACCOUNT_ID in .env)")
    parser.add_argument(
        "--info-only",
        action="store_true",
        help="Only display account information without placing market orders",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously in an autonomous market monitoring loop",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Interval in seconds between scan cycles in loop mode (default: 30s)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=60.0,
        help="Cooldown waiting period in seconds between trade executions (default: 60s)",
    )
    parser.add_argument(
        "--risk-pct",
        type=float,
        default=1.5,
        help="Risk percentage per trade for dynamic sizing (default: 1.5%%)",
    )
    parser.add_argument(
        "--max-open-trades",
        type=int,
        default=3,
        help="Maximum concurrent open positions allowed (default: 3)",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=float,
        default=5.0,
        help="Daily drawdown percentage circuit breaker threshold (default: 5.0%%)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=80.0,
        help="Minimum signal confidence threshold to trigger a trade (default: 80.0%%)",
    )
    parser.add_argument(
        "--sl-pips",
        type=float,
        default=25.0,
        help="Stop Loss distance in pips (default: 25.0)",
    )
    parser.add_argument(
        "--tp-pips",
        type=float,
        default=50.0,
        help="Take Profit distance in pips (default: 50.0)",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        default=True,
        help="Enable automated background open position monitoring (default: True)",
    )
    parser.add_argument(
        "--no-monitor",
        dest="monitor",
        action="store_false",
        help="Disable background open position monitoring",
    )
    parser.add_argument(
        "--monitor-interval",
        type=float,
        default=10.0,
        help="Interval in seconds for background position monitoring (default: 10.0s)",
    )
    parser.add_argument(
        "--tp-pnl",
        type=float,
        default=None,
        help="Floating Take-Profit profit target in dollars to auto-close position (e.g. 5.0 for +$5)",
    )
    parser.add_argument(
        "--sl-pnl",
        type=float,
        default=None,
        help="Floating Stop-Loss loss threshold in dollars to auto-close position (e.g. 3.0 for -$3)",
    )
    parser.add_argument(
        "--auto-be",
        action="store_true",
        default=False,
        help="Enable automated break-even trailing stop loss (default: False)",
    )
    parser.add_argument(
        "--no-auto-be",
        dest="auto_be",
        action="store_false",
        help="Disable automated break-even trailing stop loss",
    )
    parser.add_argument(
        "--be-trigger-pips",
        type=float,
        default=20.0,
        help="Profit in pips required to trigger break-even stop (default: 20.0)",
    )
    parser.add_argument(
        "--be-buffer-pips",
        type=float,
        default=2.0,
        help="Buffer in pips past entry to lock in for spread/commissions (default: 2.0)",
    )

    args = parser.parse_args()

    symbol_list = [args.symbol] if args.symbol else [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    while True:
        try:
            asyncio.run(
                run_trading_robot(
                    symbols=symbol_list,
                    volume=args.volume,
                    action=args.action,
                    account_id=args.account_id,
                    execute_order=not args.info_only,
                    risk_pct=args.risk_pct,
                    max_open_trades=args.max_open_trades,
                    max_drawdown_pct=args.max_drawdown_pct,
                    sl_pips=args.sl_pips,
                    tp_pips=args.tp_pips,
                    min_confidence=args.min_confidence,
                    loop=args.loop,
                    interval_seconds=args.interval,
                    cooldown_seconds=args.cooldown,
                    monitor_positions=args.monitor,
                    monitor_interval=args.monitor_interval,
                    tp_pnl=args.tp_pnl,
                    sl_pnl=args.sl_pnl,
                    auto_be=args.auto_be,
                    be_trigger_pips=args.be_trigger_pips,
                    be_buffer_pips=args.be_buffer_pips,
                )
            )
            if not args.loop:
                break
        except KeyboardInterrupt:
            logger.info("Autonomous robot loop terminated by user.")
            break
        except Exception as exc:
            if not handle_metaapi_auth_error(exc, os.getenv("METAAPI_TOKEN")):
                logger.error("Notice encountered in robot worker: %s", exc)
            if not args.loop:
                sys.exit(1)
            logger.info("Auto-reconnecting robot loop in %.1fs...", args.interval)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
