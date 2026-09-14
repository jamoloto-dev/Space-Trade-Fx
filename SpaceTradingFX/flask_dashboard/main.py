"""Console entry point for the web dashboard."""

from __future__ import annotations

import argparse

from . import create_app


def main():
    parser = argparse.ArgumentParser(description="Run the SpaceTradingFX paper-trading dashboard.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5000, type=int)
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode for local development.")
    args = parser.parse_args()
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
