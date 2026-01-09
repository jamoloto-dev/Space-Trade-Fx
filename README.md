# SpaceTradingFX 🚀

**Automated Forex Trading Platform with Flask Dashboard**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

SpaceTradingFX is a comprehensive forex trading platform featuring:
- 📊 Real-time market analysis with technical indicators
- 🤖 Automated trading strategies
- 📱 Mobile-responsive dashboard
- 💳 Stripe payment integration for licenses
- 🔐 Secure license management system
- 👥 Mentor/referral system
- 📧 Email notifications
- 🔗 MetaTrader 5 integration (Windows)

## Quick Start

### 1. Clone and Setup
```bash
git clone <repository-url>
cd Space-Trade-Fx
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac
pip install -e .
```

### 2. Configure Environment
Create a `.env` file in the project root:
```env
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///trading.db

# Stripe (Optional)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...

# Email Notifications (Optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# MT5 Trading (Optional - Windows only)
MT5_ACCOUNT=12345678
MT5_PASSWORD=your-password
MT5_SERVER=ICMarkets-Demo
```

### 3. Run the Application
```bash
python run.py
```
Visit http://127.0.0.1:5000

## Project Structure

```
Space-Trade-Fx/
├── run.py                          # Main entry point
├── pyproject.toml                  # Project configuration
├── SpaceTradingFX/
│   ├── flask_dashboard/            # Flask web application
│   │   ├── app.py                  # Flask app initialization
│   │   ├── routes.py               # Web routes and views
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── main.py                 # Alternative entry point
│   │   │
│   │   ├── # Business Logic
│   │   ├── trading_engine.py       # Core trading logic
│   │   ├── forex_data.py           # Market data provider
│   │   ├── license_manager.py      # License validation
│   │   ├── mt5_connector.py        # MetaTrader 5 integration
│   │   ├── notifications.py        # Notification service
│   │   ├── mentor_system.py        # Referral/commission system
│   │   ├── payments.py             # Stripe payment flow
│   │   │
│   │   ├── # API & Admin
│   │   ├── activation_api.py       # License activation API
│   │   ├── admin.py                # Admin panel
│   │   ├── auth.py                 # OAuth authentication
│   │   │
│   │   ├── api/                    # API module
│   │   │   └── __init__.py
│   │   ├── services/               # Services module
│   │   │   └── __init__.py
│   │   ├── templates/              # Jinja2 templates
│   │   ├── instance/               # Instance-specific data
│   │   └── logs/                   # Application logs
│   │
│   ├── space_trading_fx/           # Legacy trading module
│   │   ├── core/                   # Strategy engine
│   │   ├── trading/                # Trade execution
│   │   ├── config/                 # Settings
│   │   └── utils/                  # Utilities
│   │
│   ├── tests/                      # Test suite
│   ├── docs/                       # Documentation
│   └── data/                       # Signal data
│
└── venv/                           # Virtual environment
```

## Features

### License System
- Three tiers: Basic ($29.99), Premium ($99.99), Professional ($199.99)
- Short license keys: `XXXX-XXXX-XXXX` format
- Activation limits (3 per license by default)
- Automatic expiration handling

### Mobile Dashboard
- Responsive design with pink/burgundy theme
- Real-time account status
- Trading symbol configuration
- MetaTrader linking
- Notification center
- Trade history

### Mentor/Referral System
- 3-digit mentor IDs
- 10% commission on referral purchases
- Commission tracking and payouts

## Development

### Run Tests
```bash
pytest SpaceTradingFX/tests/
```

### Code Style
```bash
ruff check SpaceTradingFX/
ruff format SpaceTradingFX/
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/license/activate` | POST | Activate a license |
| `/api/license/status` | GET | Check license status |
| `/api/account-summary` | GET | Get account summary |
| `/api/forex-data/<pair>` | GET | Get forex data |
| `/api/mt5/connect` | POST | Connect to MT5 |
| `/payments/create-checkout-session` | POST | Create Stripe checkout |

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

For support, email support@spacetradingfx.com or open an issue.
