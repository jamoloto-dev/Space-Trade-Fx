#!/usr/bin/env python3
"""
SpaceTradingFX - Main Entry Point
Run this file to start the Flask application

Usage:
    python run.py                # Development mode
    python run.py --production   # Production mode (uses gunicorn if available)
"""

import os

from dotenv import load_dotenv

# Explicitly load .env before evaluating any environment variables
load_dotenv()


def main():
    """Run the SpaceTradingFX Flask application"""
    # Verify MetaApi credentials presence and formatting at startup
    metaapi_token = os.getenv("METAAPI_TOKEN")
    if metaapi_token:
        clean_token = metaapi_token.strip()
        is_jwt = len(clean_token.split(".")) == 3 and clean_token.startswith("ey")
        masked = f"{clean_token[:8]}...{clean_token[-6:]}" if len(clean_token) > 20 else "***"
        print(
            f"[*] MetaApi Token detected: Present (length: {len(clean_token)}, format: {'Valid JWT' if is_jwt else 'String'}, masked: {masked})"
        )
    else:
        print("[!] Notice: METAAPI_TOKEN not configured in .env (MetaApi Cloud execution will be disabled).")

    from flask_dashboard import create_app

    app = create_app()

    # Configuration
    debug = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", 5000))

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    SpaceTradingFX                            ║
║              Automated Forex Trading Platform                ║
╠══════════════════════════════════════════════════════════════╣
║  Server: http://{host}:{port}                                ║
║  Mode: {"Development" if debug else "Production"}                                   ║
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
