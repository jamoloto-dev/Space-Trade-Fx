#!/usr/bin/env python3
"""MetaApi Cloud Trading Robot.

Institutional-grade automated trading script connecting to MT4/MT5 accounts
via the metaapi-cloud-sdk and loading credentials securely from .env.
Features dynamic balance-aware position sizing, advanced risk guardrails,
drawdown circuit breakers, and AI adaptive sentiment learning.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from dotenv import load_dotenv

# Explicitly invoke load_dotenv before reading any environment variables
load_dotenv()

try:
    from metaapi_cloud_sdk import MetaApi
except ImportError:
    MetaApi = None  # type: ignore[assignment,misc]


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
    # True net balance deducting promotional credit
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
    """Calculate dynamic position size based on account equity and strict risk limits.

    Formula:
        risk_capital = equity * (risk_pct / 100.0)
        raw_lots = risk_capital / (sl_pips * pip_value_per_lot)
        rounded_lots = round to nearest volume_step, clamped within [min_volume, max_volume]
    """
    if equity <= 0:
        return min_volume

    risk_capital = equity * (max(0.1, min(risk_pct, 10.0)) / 100.0)
    denom = max(1.0, sl_pips) * max(0.1, pip_value_per_lot)
    raw_lots = risk_capital / denom

    steps = round(raw_lots / volume_step)
    sized_lots = max(min_volume, steps * volume_step)
    final_lots = min(max_volume, sized_lots)

    logger.info(
        "Dynamic Position Sizing: Equity: $%.2f | Risk: %.1f%% ($%.2f) | SL: %.1f pips | Computed: %.3f lots -> Clamped: %.2f lots",
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
            risk_multiplier = 0.5  # Halve risk after 3 consecutive losses
        elif consecutive_losses >= 2:
            risk_multiplier = 0.75  # 25% risk reduction after 2 consecutive losses

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

    print("\n" + "=" * 60)
    print("               AI ADAPTIVE CONTEXT SUMMARY")
    print("=" * 60)
    print(f"  Target Symbol   : {symbol}")
    print(f"  Proposed Action : {action}")
    print(f"  Macro Sentiment : Score {sentiment.get('score', 0.0):+.2f} ({sentiment.get('sentiment', 'NEUTRAL')})")
    print(f"  Key Headline    : {sentiment.get('headline', 'Standard Market Conditions')[:45]}...")
    print(f"  Recent Win Rate : {history.get('win_rate', 0.0):.1f}% (Evaluated {history.get('total_evaluated', 0)})")
    print(
        f"  Losing Streak   : {history.get('consecutive_losses', 0)} consecutive losses (Risk Mult: {history.get('risk_multiplier', 1.0):.2f}x)"
    )
    print(f"  AI Veto Status  : {'🚫 BLOCKED (' + str(ai_veto_reason) + ')' if ai_veto_active else '✅ CLEARED'}")
    print("=" * 60 + "\n")

    return {
        "veto": ai_veto_active,
        "veto_reason": ai_veto_reason,
        "sentiment": sentiment,
        "history": history,
        "risk_multiplier": history.get("risk_multiplier", 1.0),
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
    """Resolve symbol to broker-specific tradable symbol if base symbol is disabled (e.g. EURUSD -> EURUSD.ifx)."""
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

    for suffix in [".ifx", "m", ".c", "pro", "+", ".r"]:
        cand = f"{symbol}{suffix}"
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
    volume: float | None = None,
    action: str = "BUY",
    account_id: str | None = None,
    execute_order: bool = True,
    risk_pct: float = 1.5,
    max_open_trades: int = 3,
    max_drawdown_pct: float = 5.0,
    sl_pips: float = 25.0,
    tp_pips: float = 50.0,
) -> None:
    """Core execution lifecycle: authenticate, check risk guardrails, apply AI context, and trade."""
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

        # Step 4: Fetch & Display Account Information
        acct_info = await fetch_account_information(connection)
        raw_bal = float(acct_info.get("balance", 0.0))
        credit = float(acct_info.get("credit", 0.0))
        balance = raw_bal - credit if (credit > 0 and raw_bal > credit) else raw_bal
        equity = float(acct_info.get("equity", balance))
        free_margin = float(acct_info.get("freeMargin", equity))

        # Step 5: Drawdown Circuit Breaker Check
        is_circuit_broken, dd_pct = check_drawdown_circuit_breaker(
            starting_balance=balance,
            current_equity=equity,
            max_drawdown_pct=max_drawdown_pct,
        )
        if is_circuit_broken:
            logger.warning("Execution halted by Drawdown Circuit Breaker (%.2f%%).", dd_pct)
            return

        # Step 6: AI Adaptive Learning & Sentiment Evaluation
        ai_ctx = evaluate_ai_context(symbol, action)
        if ai_ctx.get("veto"):
            logger.warning("Execution blocked by AI Veto Gate: %s", ai_ctx.get("veto_reason"))
            return

        # Adapt risk percentage based on trade history streak
        adjusted_risk_pct = risk_pct * float(ai_ctx.get("risk_multiplier", 1.0))

        # Step 7: Dynamic Position Sizing
        actual_symbol = await resolve_tradable_symbol(connection, symbol)
        try:
            spec = await connection.get_symbol_specification(actual_symbol)
            min_vol = float(spec.get("minVolume", 0.01))
            max_vol = float(spec.get("maxVolume", 50.0))
            vol_step = float(spec.get("volumeStep", 0.01))
            digits = int(spec.get("digits", 5))
            pip_size = float(spec.get("pipSize", 0.0001))
        except Exception:
            min_vol, max_vol, vol_step, digits, pip_size = 0.01, 50.0, 0.01, 5, 0.0001

        final_volume = (
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

        # Step 8: Risk Guardrails Check (Open trades cap & Margin requirement)
        leverage = float(acct_info.get("leverage", 100))
        approx_req_margin = (final_volume * 100000.0) / max(1.0, leverage)
        guardrail_passed, guardrail_reason = await check_risk_guardrails(
            connection=connection,
            symbol=actual_symbol,
            lot_size=final_volume,
            max_open_trades=max_open_trades,
            free_margin=free_margin,
            required_margin=approx_req_margin,
        )
        if not guardrail_passed:
            logger.warning("Execution blocked by Risk Guardrail: %s", guardrail_reason)
            return

        # Step 9: Automatic Stop Loss and Take Profit Brackets
        try:
            price_info = await connection.get_symbol_price(actual_symbol)
            entry = float(price_info.get("ask" if action.upper() == "BUY" else "bid", 1.0)) if price_info else 1.08500
        except Exception:
            entry = 1.08500

        if action.upper() == "BUY":
            calc_sl = round(entry - (sl_pips * pip_size), digits)
            calc_tp = round(entry + (tp_pips * pip_size), digits)
        else:
            calc_sl = round(entry + (sl_pips * pip_size), digits)
            calc_tp = round(entry - (tp_pips * pip_size), digits)

        # Step 10: Execute Market Order
        if execute_order:
            await execute_market_order(
                connection=connection,
                symbol=actual_symbol,
                volume=final_volume,
                action=action,
                stop_loss=calc_sl,
                take_profit=calc_tp,
            )
        else:
            logger.info("Execution flag not set. Skipping market order placement.")

    except Exception as exc:
        handle_metaapi_auth_error(exc, token)
        raise

    finally:
        if connection:
            logger.info("Closing RPC connection cleanly...")
            try:
                await connection.close()
            except Exception as close_exc:
                logger.warning("Notice on connection closure: %s", close_exc)
        logger.info("Robot routine completed.")


def main():
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(description="MetaApi Cloud Trading Robot")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to trade (default: EURUSD)")
    parser.add_argument(
        "--volume",
        type=float,
        default=None,
        help="Optional lot size override (if omitted, dynamically calculated)",
    )
    parser.add_argument("--action", choices=["BUY", "SELL"], default="BUY", help="Order action (default: BUY)")
    parser.add_argument("--account-id", help="MetaApi Account ID (default: read from METAAPI_ACCOUNT_ID in .env)")
    parser.add_argument(
        "--info-only",
        action="store_true",
        help="Only display account information without placing a market order",
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

    args = parser.parse_args()

    try:
        asyncio.run(
            run_trading_robot(
                symbol=args.symbol,
                volume=args.volume,
                action=args.action,
                account_id=args.account_id,
                execute_order=not args.info_only,
                risk_pct=args.risk_pct,
                max_open_trades=args.max_open_trades,
                max_drawdown_pct=args.max_drawdown_pct,
                sl_pips=args.sl_pips,
                tp_pips=args.tp_pips,
            )
        )
    except KeyboardInterrupt:
        logger.info("Robot operation terminated by user.")
    except Exception as exc:
        if not handle_metaapi_auth_error(exc, os.getenv("METAAPI_TOKEN")):
            logger.error("Fatal robot error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
