#!/usr/bin/env python3
"""MetaApi Cloud Trading Robot.

Institutional-grade automated trading script connecting to MT4/MT5 accounts
via the metaapi-cloud-sdk and loading credentials securely from .env.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Explicitly invoke load_dotenv before reading any environment variables
load_dotenv()

try:
    from metaapi_cloud_sdk import MetaApi
except ImportError:
    MetaApi = None  # type: ignore[assignment,misc]

# Configure institutional logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MetaApiRobot")


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
    # Explicitly invoke load_dotenv() before reading METAAPI_TOKEN
    load_dotenv()

    # Support standard and case-insensitive variations found in .env
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
    balance = info.get("balance", 0.0)
    equity = info.get("equity", 0.0)
    free_margin = info.get("freeMargin", 0.0)
    leverage = info.get("leverage", "1:100")
    server = info.get("server", "Unknown")

    print("\n" + "=" * 60)
    print("               LIVE METAAPI ACCOUNT TELEMETRY")
    print("=" * 60)
    print(f"  Broker Server : {server}")
    print(f"  Currency      : {currency}")
    print(f"  Balance       : {currency} {balance:,.2f}")
    print(f"  Equity        : {currency} {equity:,.2f}")
    print(f"  Free Margin   : {currency} {free_margin:,.2f}")
    print(f"  Leverage      : 1:{leverage}")
    print("=" * 60 + "\n")

    return info


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

    logger.info(
        "Submitting %s market order: %s lots of %s (SL: %s, TP: %s)...",
        action_clean,
        volume,
        symbol,
        stop_loss if stop_loss is not None else "None",
        take_profit if take_profit is not None else "None",
    )

    try:
        if action_clean == "BUY":
            res = await connection.create_market_buy_order(
                symbol=symbol,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        else:
            res = await connection.create_market_sell_order(
                symbol=symbol,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

        order_id = res.get("orderId") or res.get("numericCode")
        logger.info(
            "✅ %s Order Successfully Filled! Ticket ID: %s | Position ID: %s",
            action_clean,
            order_id,
            res.get("positionId"),
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
    volume: float = 0.01,
    action: str = "BUY",
    account_id: str | None = None,
    execute_order: bool = True,
) -> None:
    """Core execution lifecycle: authenticate, connect, synchronize, query, and trade."""
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
        await fetch_account_information(connection)

        # Step 5: Execute Test Market Order
        if execute_order:
            await execute_market_order(
                connection=connection,
                symbol=symbol,
                volume=volume,
                action=action,
            )
        else:
            logger.info("Execution flag not set. Skipping test market order.")

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
    parser.add_argument("--volume", type=float, default=0.01, help="Lot size / volume (default: 0.01)")
    parser.add_argument("--action", choices=["BUY", "SELL"], default="BUY", help="Order action (default: BUY)")
    parser.add_argument("--account-id", help="MetaApi Account ID (default: read from METAAPI_ACCOUNT_ID in .env)")
    parser.add_argument(
        "--info-only",
        action="store_true",
        help="Only display account information without placing a market order",
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
