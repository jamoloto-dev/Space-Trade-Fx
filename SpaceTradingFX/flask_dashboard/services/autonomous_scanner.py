"""Autonomous Background Trading Loop and Market Scanner Service.

Periodically executes market scans across monitored symbols, synchronizes
live open trade floating PnL/exits, and auto-executes high-confidence signals (>= 65%)
with strict duplicate-position protection.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from flask import Flask
from loguru import logger

_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event = threading.Event()
_scheduler_lock = threading.Lock()


def run_autonomous_cycle(app: Flask, force_scan: bool = False) -> dict[str, Any]:
    """Execute one complete cycle of open position synchronization, auto break-even, and circuit breaker protection."""
    from ..extensions import db
    from ..forex_data import is_rollover_window
    from ..models import BrokerAccount, Trade, TradingPreference
    from ..notifications import create_notification
    from ..trading_engine import TradingEngine
    from .broker_bridge import get_broker_telemetry

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "users_processed": 0,
        "positions_updated": 0,
        "signals_generated": 0,
        "auto_orders_executed": 0,
    }

    with app.app_context():
        try:
            # Query all active connected broker accounts
            connected_accounts = BrokerAccount.query.filter_by(is_connected=True).all()
            user_ids = {acct.user_id for acct in connected_accounts}

            # Also include users with currently open trades to update floating P/L
            open_trade_users = db.session.query(Trade.user_id).filter_by(status="open").distinct().all()
            user_ids.update(row[0] for row in open_trade_users)

            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.date().isoformat()
            today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

            for user_id in user_ids:
                report["users_processed"] += 1
                try:
                    engine = TradingEngine(user_id)

                    # 1. Synchronize open trades floating P/L, evaluate Auto Break-Even, and check TP/SL hits
                    closed_count = engine.update_open_trades()
                    report["positions_updated"] += closed_count

                    prefs = TradingPreference.query.filter_by(user_id=user_id).first()
                    strategy = dict(prefs.strategy_settings or {}) if prefs else {}

                    # 2. Reset circuit breaker if crossing into a new trading day
                    tripped_date = strategy.get("circuit_breaker_date")
                    if tripped_date and tripped_date != today_str:
                        strategy["circuit_breaker_tripped"] = False
                        strategy["circuit_breaker_date"] = None
                        if prefs:
                            prefs.strategy_settings = strategy
                            db.session.commit()

                    # 3. Daily Loss Circuit Breaker calculation
                    # Sum realized P/L of trades closed today
                    closed_today = Trade.query.filter(
                        Trade.user_id == user_id,
                        Trade.status == "closed",
                        Trade.closed_at >= today_start,
                    ).all()
                    today_realized_pnl = sum(
                        (t.profit_loss for t in closed_today if t.profit_loss is not None), Decimal("0.00")
                    )

                    # Sum floating P/L of currently open trades
                    open_trades = Trade.query.filter_by(user_id=user_id, status="open").all()
                    floating_pnl = sum(
                        (t.profit_loss for t in open_trades if t.profit_loss is not None), Decimal("0.00")
                    )
                    total_daily_pnl = today_realized_pnl + floating_pnl

                    # Telemetry balance check
                    telemetry = get_broker_telemetry(user_id)
                    balance = Decimal(str(telemetry.get("balance", "3000.00")))
                    if balance <= 0:
                        balance = Decimal("3000.00")

                    max_loss_pct = Decimal(str(strategy.get("max_daily_loss_pct", "5.0")))
                    max_loss_amount = (balance * (max_loss_pct / Decimal("100"))).quantize(Decimal("0.01"))

                    is_circuit_breaker_active = bool(strategy.get("circuit_breaker_tripped", False))

                    if total_daily_pnl <= -max_loss_amount:
                        if not is_circuit_breaker_active:
                            strategy["circuit_breaker_tripped"] = True
                            strategy["circuit_breaker_date"] = today_str
                            strategy["circuit_breaker_pnl"] = str(total_daily_pnl)
                            if prefs:
                                prefs.strategy_settings = strategy
                                prefs.trading_enabled = False
                                db.session.commit()
                            is_circuit_breaker_active = True

                            try:
                                create_notification(
                                    user_id=user_id,
                                    title="🚨 Daily Loss Circuit Breaker Tripped",
                                    message=(
                                        f"Protective Circuit Breaker Active: Total daily drawdown ({total_daily_pnl:.2f}) "
                                        f"reached -{max_loss_pct}% (Max: -{max_loss_amount:.2f}). "
                                        f"Auto-Pilot has been paused until tomorrow to preserve account margin."
                                    ),
                                    notification_type="system",
                                    data={
                                        "circuit_breaker": True,
                                        "daily_pnl": str(total_daily_pnl),
                                        "limit": str(max_loss_amount),
                                    },
                                )
                            except Exception:
                                pass
                            logger.warning(
                                "Circuit Breaker Tripped for user %s: Daily P/L %s reached limit -%s",
                                user_id,
                                total_daily_pnl,
                                max_loss_amount,
                            )

                    # 4. Check if Rollover spread protection is active
                    in_rollover = is_rollover_window(now_utc)

                    # 5. Check if user has Auto-Pilot enabled and not blocked
                    auto_pilot_enabled = bool(
                        prefs
                        and not is_circuit_breaker_active
                        and not in_rollover
                        and (
                            prefs.trading_enabled
                            or strategy.get("auto_pilot")
                            or strategy.get("automated_broker_trading")
                        )
                    )

                    if in_rollover and (prefs and prefs.trading_enabled):
                        logger.info(
                            "Rollover spread protection active (23:55-01:05 SAST), Auto-Pilot order execution paused for %s",
                            user_id,
                        )

                    if force_scan or auto_pilot_enabled:
                        before_count = Trade.query.filter_by(user_id=user_id, status="open").count()
                        signals = engine.analyze_markets(submit_automatically=auto_pilot_enabled)
                        after_count = Trade.query.filter_by(user_id=user_id, status="open").count()
                        report["signals_generated"] += len(signals)
                        report["auto_orders_executed"] += max(0, after_count - before_count)

                except Exception as user_exc:
                    logger.warning("Autonomous worker cycle failed for user %s: %s", user_id, user_exc)
                    db.session.rollback()

        except Exception as cycle_exc:
            logger.error("Error in autonomous worker cycle: %s", cycle_exc)
            db.session.rollback()

    return report


def _worker_loop(app: Flask, scan_interval_seconds: int = 900, sync_interval_seconds: int = 30) -> None:
    """Continuous non-blocking background loop."""
    logger.info(
        "Autonomous trading scheduler started (scan_interval=%ss, sync_interval=%ss)",
        scan_interval_seconds,
        sync_interval_seconds,
    )
    last_scan_time = 0.0

    while not _scheduler_stop_event.is_set():
        now = time.time()
        is_scan_due = (now - last_scan_time) >= scan_interval_seconds

        try:
            run_autonomous_cycle(app, force_scan=is_scan_due)
            if is_scan_due:
                last_scan_time = now
        except Exception as exc:
            logger.exception("Unexpected exception in autonomous scheduler loop: %s", exc)

        # Sleep in short increments to allow rapid shutdown
        sleep_elapsed = 0
        while sleep_elapsed < sync_interval_seconds and not _scheduler_stop_event.is_set():
            time.sleep(1)
            sleep_elapsed += 1

    logger.info("Autonomous trading scheduler terminated cleanly.")


def start_autonomous_scheduler(
    app: Flask,
    scan_interval_seconds: int = 900,
    sync_interval_seconds: int = 30,
) -> bool:
    """Start the non-blocking autonomous scheduler thread if not already active."""
    global _scheduler_thread

    # Never start the background thread during automated testing
    if app.config.get("TESTING"):
        return False

    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return True

        _scheduler_stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_worker_loop,
            args=(app, scan_interval_seconds, sync_interval_seconds),
            daemon=True,
            name="AutonomousBrokerScheduler",
        )
        _scheduler_thread.start()
        return True


def stop_autonomous_scheduler() -> None:
    """Signal the autonomous scheduler thread to stop."""
    global _scheduler_thread
    with _scheduler_lock:
        _scheduler_stop_event.set()
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            _scheduler_thread.join(timeout=3.0)
            _scheduler_thread = None
