"""Regression tests for SpaceTradeWorker import resolution and multi-process singleton locking."""

from __future__ import annotations

import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

from flask_dashboard.services.trade_worker import (
    SpaceTradeWorker,
    start_space_trade_worker_daemon,
    stop_space_trade_worker_daemon,
)


class TestSpaceTradeWorkerImportsAndCycle:
    """Verifies SpaceTradeWorker runs without ModuleNotFoundError on trading_state."""

    def test_run_cycle_without_module_not_found(self):
        """Worker must execute a cycle cleanly without trading_state import failure."""
        worker = SpaceTradeWorker()
        result = worker.run_cycle()
        assert isinstance(result, dict)
        assert "status" in result
        assert "timestamp" in result
        assert "cycle" in result
        assert result["cycle"] >= 1

    def test_trading_state_accessible_from_flask_dashboard_and_root(self):
        """Ensure trading_state is importable and exposes core state management functions."""
        from flask_dashboard.services import trading_state as service_ts

        import trading_state

        assert hasattr(trading_state, "load_execution_state")
        assert hasattr(trading_state, "save_execution_state")
        assert hasattr(trading_state, "is_execution_authorized")

        assert hasattr(service_ts, "load_execution_state")
        assert hasattr(service_ts, "save_execution_state")
        assert hasattr(service_ts, "is_execution_authorized")


class TestWorkerSingletonAndLocking:
    """Verifies that calling start_space_trade_worker_daemon multiple times spawns only one worker."""

    def setup_method(self):
        stop_space_trade_worker_daemon()

    def teardown_method(self):
        stop_space_trade_worker_daemon()

    def test_multiple_starts_return_same_single_thread(self):
        """Calling start_space_trade_worker_daemon multiple times only spawns one thread."""
        with tempfile.NamedTemporaryFile() as tmp_lock:
            lock_path = tmp_lock.name

            # First start
            t1 = start_space_trade_worker_daemon(interval_seconds=10, lock_path=lock_path)
            assert t1 is not None
            assert t1.is_alive()

            # Second start in same process
            t2 = start_space_trade_worker_daemon(interval_seconds=10, lock_path=lock_path)
            assert t2 is t1
            assert threading.active_count() >= 1

            stop_space_trade_worker_daemon()
            assert not t1.is_alive()

    def test_cross_process_lock_blocks_duplicate_worker(self):
        """When lock file is held by another process, start_space_trade_worker_daemon returns None."""
        with tempfile.NamedTemporaryFile() as tmp_lock:
            lock_path = tmp_lock.name

            # Simulate another process holding the lock
            with patch("flask_dashboard.services.trade_worker._acquire_worker_process_lock", return_value=False):
                thread = start_space_trade_worker_daemon(interval_seconds=10, lock_path=lock_path)
                assert thread is None


class TestWorkerErrorBackoff:
    """Verifies error handling backoff in worker loop."""

    def setup_method(self):
        stop_space_trade_worker_daemon()

    def teardown_method(self):
        stop_space_trade_worker_daemon()

    def test_worker_daemon_handles_exception_with_backoff(self):
        """Worker loop catches exceptions in run_cycle and does not crash."""
        failing_worker = MagicMock(spec=SpaceTradeWorker)
        failing_worker.run_cycle.side_effect = RuntimeError("Simulated transient broker network failure")

        with tempfile.NamedTemporaryFile() as tmp_lock:
            lock_path = tmp_lock.name

            t = start_space_trade_worker_daemon(
                worker=failing_worker,
                interval_seconds=1,
                lock_path=lock_path,
            )
            assert t is not None
            assert t.is_alive()

            # Give it a moment to run at least one iteration and hit the error handler
            time.sleep(0.5)
            assert t.is_alive()
            assert failing_worker.run_cycle.called

            stop_space_trade_worker_daemon()
            assert not t.is_alive()
