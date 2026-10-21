# SpaceTradingFX

Institutional-grade Forex Trading Platform, Autonomous Market Scanner, and MetaApi Cloud Trading Robot.

[![Test Suite](https://img.shields.io/badge/pytest-99%20passed-brightgreen.svg)](#testing)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-black.svg)](#linting--formatting)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue.svg)](#prerequisites)

---

## Overview

SpaceTradingFX combines a multi-timeframe forex analytical platform, an autonomous market scanner, and an automated cloud trading robot:

1. **Flask Web Dashboard (`http://127.0.0.1:5000`)**:
   - Mobile-first institutional trading interface (`/m/home`, `/m/quotes`, `/m/history`, `/m/connect-broker`, `/admin/ui`).
   - Strategy switcher: **Swing Trading (1H/4H)** and **Ultra Scalping (M1/M5)**.
   - Encrypted MT4/MT5 broker vault using Fernet symmetric encryption.
   - Cryptographically signed RSA-2048 licensing with multi-tier subscription controls.

2. **Autonomous Market Scanner**:
   - Continuous scanning of major and exotic currency pairs (`EURUSD`, `GBPUSD`, `USDJPY`, `USDZAR`).
   - Technical multi-timeframe analysis: EMA, RSI, MACD, and ATR volatility brackets.
   - **Macro AI News Sentiment Veto Gate**: Live fundamental news analysis blocking technical signals that contradict macroeconomic news sentiment.

3. **MetaApi Cloud Trading Robot (`metaapi_robot.py`)**:
   - Connects to MetaTrader 4 and 5 accounts via the [`metaapi-cloud-sdk`](https://metaapi.cloud/docs/client/).
   - Credential security via `python-dotenv` and `.env` (`METAAPI_TOKEN`, `METAAPI_ACCOUNT_ID`).
   - Real-time account telemetry (server, currency, balance, equity, margin, leverage).
   - Automated market order placement (`BUY`/`SELL`) with stop-loss and take-profit scaling.

---

## Quickstart

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Virtual environment (`venv` or `virtualenv`)

### 2. Environment Setup

```bash
# Clone and enter the repository
git clone https://github.com/jamoloto-dev/Space-Trade-Fx.git
cd Space-Trade-Fx

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package in editable mode with development dependencies
pip install -e '.[dev]'
```

### 3. Configure Credentials (`.env`)

Create a `.env` file in the project root:

```env
# Flask Dashboard Configuration
FLASK_DEBUG=True
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
SESSION_SECRET=generate-a-strong-session-secret-key

# MetaApi Cloud Robot Credentials
METAAPI_TOKEN=your_metaapi_cloud_token_here
METAAPI_ACCOUNT_ID=f911e0d0-5bdd-400b-9b10-521c304d9d84

# Database (defaults to local SQLite trading.db if omitted)
# DATABASE_URL=postgresql://user:password@localhost:5432/trading_db

# Optional Licensing RSA Keypairs (auto-generated ephemerally if omitted)
# LICENSE_PUBLIC_KEY_PEM="-----BEGIN PUBLIC KEY-----\n..."
# LICENSE_PRIVATE_KEY_PEM="-----BEGIN RSA PRIVATE KEY-----\n..."
```

### 4. Database Migrations

Initialize and apply database schemas:

```bash
alembic upgrade head
```

---

## Running the Applications

### A. Start the Flask Web Dashboard

Launch the server locally on port 5000:

```bash
python run.py
```

The application is accessible at:
- **Mobile Platform**: [http://127.0.0.1:5000/m/home](http://127.0.0.1:5000/m/home)
- **Market Quotes & Scalping Switcher**: [http://127.0.0.1:5000/m/quotes](http://127.0.0.1:5000/m/quotes)
- **Connect Broker (MT4/MT5)**: [http://127.0.0.1:5000/m/connect-broker](http://127.0.0.1:5000/m/connect-broker)
- **Administrator Panel**: [http://127.0.0.1:5000/admin/ui](http://127.0.0.1:5000/admin/ui)
- **Health Probe**: [http://127.0.0.1:5000/health/live](http://127.0.0.1:5000/health/live)

#### Bootstrap an Administrator
To create or elevate an administrator account:

```bash
python -m SpaceTradingFX.flask_dashboard.bootstrap_admin admin@example.com
```

---

### B. Run the MetaApi Trading Robot

Execute the standalone trading script:

```bash
# Query live account telemetry only (balance, equity, margin)
python metaapi_robot.py --info-only

# Execute a market order (default: 0.01 lots EURUSD BUY)
python metaapi_robot.py --symbol EURUSD --volume 0.01 --action BUY

# Custom symbol and order action
python metaapi_robot.py --symbol USDZAR --volume 0.05 --action SELL
```

See [docs/ROBOT_GUIDE.md](docs/ROBOT_GUIDE.md) for full robot documentation and deployment options.

---

### C. Run the Autonomous Market Scanner

The scanner runs automatically in the background when starting `run.py`. To execute an on-demand scan cycle manually:

```python
from flask_dashboard import create_app
from flask_dashboard.services.autonomous_scanner import run_autonomous_cycle

app = create_app()
with app.app_context():
    summary = run_autonomous_cycle(app, force_scan=True)
    print("Cycle Summary:", summary)
```

See [docs/AUTONOMOUS_TRADING.md](docs/AUTONOMOUS_TRADING.md) for strategy parameters and sentiment veto configuration.

---

## Testing & Quality Assurance

### Testing
Run the complete test suite with pytest:

```bash
pytest SpaceTradingFX/tests/ -v
```

All **99 unit and integration tests** pass, covering:
- Authentication & defensive user loader (`test_phase0_security.py`)
- MetaApi trading robot lifecycle & mocking (`test_metaapi_robot.py`)
- Scalping mode & tight ATR stops (`test_scalping_mode.py`)
- Multi-timeframe confluence & Macro AI News sentiment veto (`test_institutional_risk_and_mtf.py`, `test_news_intelligence.py`)
- Broker encryption vault & bridge routing (`test_broker_bridge.py`)
- License provisioning & validation (`test_activation_api.py`)

### Linting & Formatting
The project enforces strict code style using [Ruff](https://astral.sh/ruff):

```bash
# Verify formatting
ruff format --check .

# Apply automatic formatting
ruff format .

# Check code linting
ruff check .
```

---

## Architecture & Project Structure

```text
Space-Trade-Fx/
├── run.py                             # Flask application entry point (http://127.0.0.1:5000)
├── metaapi_robot.py                   # MetaApi cloud trading robot script
├── docs/                              # Detailed guides
│   ├── ROBOT_GUIDE.md                 # MetaApi robot usage, telemetry & orders
│   └── AUTONOMOUS_TRADING.md          # Autonomous scanner & Macro AI News Veto
├── SpaceTradingFX/
│   ├── flask_dashboard/               # Flask Web Application & Core Services
│   │   ├── blueprints/
│   │   │   ├── mobile.py              # Mobile-first trading & quotes surface
│   │   │   └── secure_auth.py         # Session management & user authentication
│   │   ├── services/
│   │   │   ├── autonomous_scanner.py  # Background scanner daemon & scheduler
│   │   │   ├── broker_bridge.py       # Encrypted credential vault & MT4/MT5 bridge
│   │   │   └── news_intelligence.py   # Macro AI fundamental news sentiment gate
│   │   ├── models.py                  # SQLAlchemy data models (User, BrokerAccount, etc.)
│   │   ├── trading_engine.py          # Institutional risk & signal execution engine
│   │   ├── forex_data.py              # Live & fallback market candle feed
│   │   └── license_manager.py         # RSA cryptographic license verification
│   └── tests/                         # Pytest test suite (99 passing tests)
├── pyproject.toml                     # Project dependencies & tool configurations
├── pytest.ini                         # Pytest discovery & marker settings
└── README.md                          # Platform documentation
```

---

## Security Guidelines

- **Zero Plaintext Credentials**: Broker credentials stored in `broker_accounts` are encrypted with Fernet symmetric keys.
- **Never Commit Secrets**: Keep all tokens (`METAAPI_TOKEN`, `SESSION_SECRET`, `STRIPE_*`) strictly inside untracked `.env` files.
- **Defensive Error Handling**: The user loader and API endpoints fail closed without leaking sensitive stack traces.
