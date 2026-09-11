"""Quarantined compatibility surface for the former MT5 integration.

SpaceTradingFX is paper-trading only.  No MT5 SDK, credentials, connection or
order execution is loaded by this application.  Keeping these names avoids an
import-time break for older callers while making every live operation fail
closed.
"""

from __future__ import annotations

MT5_AVAILABLE = False


class LiveBrokerDisabledError(RuntimeError):
    pass


class MT5Connector:
    """Deprecated stub that rejects all live broker operations."""

    def __init__(self, *args, **kwargs):
        self.connected = False
        self.last_error = "Live MT5 integration is disabled; this product supports paper trading only."

    def _disabled(self, *args, **kwargs):
        raise LiveBrokerDisabledError(self.last_error)

    initialize = _disabled
    login = _disabled
    connect = _disabled
    get_account_info = _disabled
    get_symbol_info = _disabled
    open_position = _disabled
    close_position = _disabled
    get_positions = _disabled
    get_history = _disabled
    modify_position = _disabled

    def disconnect(self) -> None:
        self.connected = False

    def get_last_error(self) -> str:
        return self.last_error


def get_mt5_connector() -> MT5Connector:
    return MT5Connector()


def is_mt5_available() -> bool:
    return False
