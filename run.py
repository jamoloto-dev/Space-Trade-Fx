#!/usr/bin/env python3
"""
SpaceTradingFX - Main Entry Point
Run this file to start the Flask application

Usage:
    python run.py                # Development mode
    python run.py --production   # Production mode (uses gunicorn if available)
"""

import os
import sys

# Add flask_dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'SpaceTradingFX', 'flask_dashboard'))

def main():
    """Run the SpaceTradingFX Flask application"""
    from app import app  # type: ignore
    import routes  # type: ignore  # noqa: F401 - Import routes to register them
    
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
    # Check for command line arguments
    if '--production' in sys.argv or '--prod' in sys.argv:
        os.environ['FLASK_DEBUG'] = 'False'
        try:
            import gunicorn  # type: ignore  # noqa: F401
            # If gunicorn is available, suggest using it
            print("For production, use: gunicorn -w 4 -b 0.0.0.0:5000 'SpaceTradingFX.flask_dashboard.app:app'")
        except ImportError:
            pass
    
    main()
