"""Quarantined legacy broker demo.

The old package represented a broker connection and a "real" balance using
hard-coded mock behaviour. It is retained only to give callers a clear,
fail-closed migration error.
"""


class BrokerIntegrationDisabledError(RuntimeError):
    pass


class MockBrokerAPI:
    def __init__(self, *args, **kwargs):
        raise BrokerIntegrationDisabledError("Broker integrations are disabled; SpaceTradingFX is paper-trading only.")


class Space_TradingFX(MockBrokerAPI):
    pass


def main() -> None:
    raise BrokerIntegrationDisabledError("The legacy broker demo is quarantined; use the paper dashboard.")


if __name__ == "__main__":
    main()
