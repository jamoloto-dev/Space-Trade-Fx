"""
Space-Trade-Fx Unified Autonomous Trade Worker.

Consolidates autonomous scanning and robot execution loops into a single,
collision-free, risk-governed worker engine supporting in-process scheduling
and standalone daemon execution.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .execution_broker import ExecutionBroker, OrderIntent, OrderResult, PaperExecutionBroker
from .risk_manager import RiskAssessmentResult, SpaceTradeRiskManager

logger = logging.getLogger("space_trading_fx.trade_worker")


class SpaceTradeWorker:
    """
    Unified Space-Trade-Fx Autonomous Worker Engine.
    Executes scans, applies institutional risk guardrails, and routes orders.
    """

    def __init__(
        self,
        broker: ExecutionBroker | None = None,
        risk_manager: SpaceTradeRiskManager | None = None,
        symbols: list[str] | None = None,
        min_confidence_pct: float = 65.0,
    ) -> None:
        self.broker = broker or PaperExecutionBroker()
        self.risk_manager = risk_manager or SpaceTradeRiskManager()
        self.symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY", "USDZAR", "XAUUSD"]
        self.min_confidence_pct = min_confidence_pct
        self.is_running = False
        self.last_cycle_timestamp: str | None = None
        self.cycle_count = 0

    def run_cycle(self) -> dict[str, Any]:
        """
        Execute a single autonomous scanning and execution cycle.
        """
        from trading_state import load_execution_state, save_execution_state

        self.cycle_count += 1
        now_utc = datetime.now(timezone.utc).isoformat()
        self.last_cycle_timestamp = now_utc

        # 1. Check Global Auto-Pilot Authority
        if not load_execution_state():
            logger.info("SpaceTradeWorker: Auto-pilot execution paused / on hold.")
            return {
                "status": "paused",
                "timestamp": now_utc,
                "cycle": self.cycle_count,
                "trades_executed": 0,
            }

        # 2. Check Account-Level Circuit Breakers
        telemetry = self.broker.get_telemetry()
        is_tripped, dd_pct = self.risk_manager.check_circuit_breaker(telemetry)
        if is_tripped:
            logger.warning(
                f"SpaceTradeWorker: Circuit breaker tripped ({dd_pct:.2f}% daily drawdown). Disabling auto-pilot."
            )
            save_execution_state(False, source="circuit_breaker")
            return {
                "status": "circuit_breaker_tripped",
                "drawdown_pct": dd_pct,
                "timestamp": now_utc,
                "trades_executed": 0,
            }

        executed_orders: list[OrderResult] = []
        rejected_intents: list[dict[str, Any]] = []

        # 3. Scan Symbols & Evaluate Signals
        for sym in self.symbols:
            # Check maximum positions limit before computing signal
            open_positions = self.broker.get_positions()
            if len(open_positions) >= self.risk_manager.limits.max_open_positions:
                logger.info("SpaceTradeWorker: Max open positions limit reached; skipping further scans.")
                break

            # Prevent duplicate position on same symbol (handling .ifx broker suffixes)
            clean_sym = sym.replace(".ifx", "").replace(".IFX", "").upper()
            if any(p.symbol.replace(".ifx", "").replace(".IFX", "").upper() == clean_sym for p in open_positions):
                continue

            # Generate synthetic or model signal
            signal = self._evaluate_market_signal(sym)
            if not signal or signal.get("action") not in ("BUY", "SELL"):
                continue

            confidence = float(signal.get("confidence", 0.0))
            if confidence < self.min_confidence_pct:
                continue

            action = signal["action"]
            target_symbol = sym
            if hasattr(self.broker, "resolve_symbol"):
                target_symbol = self.broker.resolve_symbol(sym)

            intent = OrderIntent(
                symbol=target_symbol,
                trade_type=action,
                lot_size=0.01,
                magic_number=88123,
                comment=f"SpaceTrade AI ({confidence:.0f}%)",
            )

            # 4. Pre-Trade Risk Evaluation
            risk_eval: RiskAssessmentResult = self.risk_manager.evaluate_pre_trade_risk(
                intent=intent,
                broker=self.broker,
            )

            if not risk_eval.allowed:
                logger.info(f"SpaceTradeWorker: Risk vetoed order on {sym}: {', '.join(risk_eval.reasons)}")
                rejected_intents.append({"symbol": sym, "reasons": risk_eval.reasons})
                continue

            # 5. Order Execution
            order_res = self.broker.submit_order(intent)
            if order_res.success:
                logger.info(f"SpaceTradeWorker: Successfully executed {action} on {sym} (Ticket: {order_res.ticket})")
                executed_orders.append(order_res)
            else:
                logger.error(f"SpaceTradeWorker: Order placement failed on {sym}: {order_res.error}")

        return {
            "status": "completed",
            "timestamp": now_utc,
            "cycle": self.cycle_count,
            "trades_executed": len(executed_orders),
            "orders": [o.ticket for o in executed_orders if o.ticket],
            "rejected_count": len(rejected_intents),
        }

    def _evaluate_market_signal(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate market conditions and return trade intent with confidence score."""
        try:
            from models.signal_engine import SignalEngine

            sig_eng = SignalEngine()
            # Feed baseline market pulse
            sig = sig_eng.evaluate_signal(
                order_flow_imbalance=0.25,
                technical_score=0.60,
                macro_sentiment=0.10,
                symbol=symbol,
                direction="BUY",
            )
            return sig
        except Exception:
            # Deterministic baseline signal generator for tests/dev
            return {"action": "HOLD", "confidence": 50.0}

    async def run_daemon(self, interval_seconds: int = 15, stop_event: asyncio.Event | None = None) -> None:
        """Run worker as an asynchronous continuous daemon."""
        self.is_running = True
        logger.info(f"SpaceTradeWorker daemon started with {interval_seconds}s interval.")
        try:
            while self.is_running:
                if stop_event and stop_event.is_set():
                    break
                try:
                    self.run_cycle()
                except Exception as exc:
                    logger.error(f"SpaceTradeWorker cycle error: {exc}")

                await asyncio.sleep(interval_seconds)
        finally:
            self.is_running = False
            logger.info("SpaceTradeWorker daemon stopped.")


_worker_daemon_thread: threading.Thread | None = None
_worker_daemon_stop = threading.Event()
_worker_daemon_lock = threading.Lock()


def start_space_trade_worker_daemon(
    app: Any | None = None,
    worker: SpaceTradeWorker | None = None,
    interval_seconds: int = 30,
) -> threading.Thread | None:
    """Start SpaceTradeWorker as an in-process background daemon thread."""
    global _worker_daemon_thread, _worker_daemon_stop

    with _worker_daemon_lock:
        if _worker_daemon_thread and _worker_daemon_thread.is_alive():
            return _worker_daemon_thread

        _worker_daemon_stop.clear()
        active_worker = worker or SpaceTradeWorker()

        def _thread_target():
            logger.info("SpaceTradeWorker in-process daemon started (interval=%ss)", interval_seconds)
            while not _worker_daemon_stop.is_set():
                try:
                    if app:
                        with app.app_context():
                            from ..models import BrokerAccount
                            from .execution_broker import LiveMetaApiBroker

                            # If user connected broker, attach live broker adapter
                            acct = BrokerAccount.query.filter_by(is_connected=True).first()
                            if acct and not isinstance(active_worker.broker, LiveMetaApiBroker):
                                active_worker.broker = LiveMetaApiBroker(user_id=acct.user_id)
                            active_worker.run_cycle()
                    else:
                        active_worker.run_cycle()
                except Exception as exc:
                    logger.error("Error in SpaceTradeWorker daemon cycle: %s", exc)

                sleep_elapsed = 0
                while sleep_elapsed < interval_seconds and not _worker_daemon_stop.is_set():
                    time.sleep(1)
                    sleep_elapsed += 1

            logger.info("SpaceTradeWorker in-process daemon stopped.")

        t = threading.Thread(target=_thread_target, name="SpaceTradeWorkerDaemon", daemon=True)
        t.start()
        _worker_daemon_thread = t
        return t


def stop_space_trade_worker_daemon() -> None:
    """Signal the in-process SpaceTradeWorker daemon thread to stop."""
    global _worker_daemon_stop
    _worker_daemon_stop.set()
