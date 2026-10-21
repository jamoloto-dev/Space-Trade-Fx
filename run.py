#!/usr/bin/env python3
"""
SpaceTradingFX - Main Entry Point
Run this file to start the Flask application

Usage:
    python run.py                # Development mode
    python run.py --production   # Production mode (uses gunicorn if available)
"""

import os


def main():
    """Run the SpaceTradingFX Flask application"""
    from flask_dashboard import create_app

    app = create_app()

    # Configuration
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5000))

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    SpaceTradingFX                            ║
║              Automated Forex Trading Platform                ║
╠══════════════════════════════════════════════════════════════╣
║  Server: http://{host}:{port}                                ║
║  Mode: {'Development' if debug else 'Production'}                                   ║
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
