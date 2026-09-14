"""Standalone, lease-protected paper lifecycle worker.

Run this module as a separate process.  It is intentionally not started by a
Flask request, debug reloader, or Gunicorn worker.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from . import create_app
from .extensions import db
from .models import PaperWorkerLease, Trade, TradingPreference, utcnow
from .trading_engine import TradingEngine

logger = logging.getLogger(__name__)
LEASE_NAME = "paper-lifecycle"


class PaperLifecycleWorker:
    def __init__(self, owner_id: str | None = None, lease_seconds: int = 45):
        self.owner_id = owner_id or uuid4().hex
        self.lease_seconds = lease_seconds

    def acquire_lease(self) -> bool:
        now = utcnow()
        expires = now + timedelta(seconds=self.lease_seconds)
        lease = db.session.get(PaperWorkerLease, LEASE_NAME)
        if lease and _as_utc(lease.expires_at) > now and lease.owner_id != self.owner_id:
            return False
        try:
            if lease is None:
                db.session.add(PaperWorkerLease(name=LEASE_NAME, owner_id=self.owner_id, expires_at=expires))
            else:
                # Compare every observed lease field in the UPDATE.  If another
                # process renewed it after our read, exactly one update wins.
                updated = db.session.execute(
                    update(PaperWorkerLease)
                    .where(
                        PaperWorkerLease.name == LEASE_NAME,
                        PaperWorkerLease.owner_id == lease.owner_id,
                        PaperWorkerLease.expires_at == lease.expires_at,
                    )
                    .values(owner_id=self.owner_id, expires_at=expires)
                )
                if int(getattr(updated, "rowcount", 0) or 0) != 1:
                    db.session.rollback()
                    return False
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False

    def release_lease(self) -> None:
        lease = db.session.get(PaperWorkerLease, LEASE_NAME)
        if lease and lease.owner_id == self.owner_id:
            lease.expires_at = utcnow()
            db.session.commit()

    def _record_cycle_result(self, result: dict[str, int | str]) -> None:
        """Persist only operational status; never put quotes or credentials in health."""
        lease = db.session.get(PaperWorkerLease, LEASE_NAME)
        if lease is None or lease.owner_id != self.owner_id:
            return
        now = utcnow()
        lease.last_cycle_at = now
        if int(result["exceptions"]) == 0:
            lease.last_success_at = now
            lease.last_error = None
        else:
            lease.last_error = f"{result['exceptions']} user lifecycle operation(s) failed"
        db.session.commit()

    def run_once(self) -> dict[str, int | str]:
        if not self.acquire_lease():
            return {"status": "standby", "users": 0, "opened": 0, "closed": 0, "exceptions": 0}
        result: dict[str, int | str] = {"status": "ok", "users": 0, "opened": 0, "closed": 0, "exceptions": 0}
        # Pausing blocks *new* intents only.  Users with open paper positions
        # remain in the lifecycle so their P/L, exits and reconciliation do
        # not silently stop.
        user_ids = {row[0] for row in db.session.query(TradingPreference.user_id).filter_by(trading_enabled=True).all()}
        user_ids.update(
            row[0]
            for row in db.session.query(Trade.user_id).filter(Trade.status.in_(("open", "closing"))).distinct().all()
        )
        for user_id in sorted(user_ids):
            result["users"] = int(result["users"]) + 1
            try:
                engine = TradingEngine(user_id)
                result["opened"] = int(result["opened"]) + engine.run_automated_cycle()
                result["closed"] = int(result["closed"]) + engine.update_open_trades()
                result["exceptions"] = int(result["exceptions"]) + engine.reconcile_paper_ledger().exception_count
            except Exception:
                db.session.rollback()
                result["exceptions"] = int(result["exceptions"]) + 1
                logger.exception("Paper lifecycle failed for user %s", user_id)
            # A long external-data call must not allow a second process to
            # take an otherwise healthy worker lease between users.
            if not self.acquire_lease():
                result["status"] = "lease_lost"
                result["exceptions"] = int(result["exceptions"]) + 1
                break
        self._record_cycle_result(result)
        return result


def _as_utc(value: datetime) -> datetime:
    """SQLite can round-trip timezone-aware columns as naive values."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SpaceTradingFX paper lifecycle worker.")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between cycles (minimum 5).")
    parser.add_argument("--once", action="store_true", help="Run exactly one lease-protected cycle.")
    args = parser.parse_args()
    interval = max(5, args.interval)
    app = create_app()
    # The lease remains valid throughout a normal cycle and sleep interval.
    # It is renewed between users; an abandoned process still expires.
    worker = PaperLifecycleWorker(lease_seconds=max(300, interval * 2 + 60))
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with app.app_context():
            while not stopping:
                logger.info("Paper lifecycle cycle: %s", worker.run_once())
                if args.once:
                    break
                time.sleep(interval)
    finally:
        with app.app_context():
            worker.release_lease()


if __name__ == "__main__":
    main()
