"""Append-only audit-event helpers for sensitive dashboard actions."""

from __future__ import annotations

from typing import Any

from flask import request

from .extensions import db
from .models import AuditEvent


def record_audit_event(
    action: str,
    *,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Stage a redacted audit event in the current database transaction."""
    event = AuditEvent(
        action=action,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        request_id=request.headers.get("X-Request-ID", "")[:64] or None,
    )
    db.session.add(event)
    return event
