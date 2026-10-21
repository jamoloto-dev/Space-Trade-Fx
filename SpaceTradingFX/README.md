# SpaceTradingFX Core & Dashboard

This directory contains the core application modules and test suite for the **SpaceTradingFX** platform.

---

## Architecture Overview

- **`flask_dashboard/`**: The core Flask application providing the web dashboard, user authentication, broker encryption, mobile interface, and autonomous trading services:
  - **`blueprints/mobile.py`**: Mobile views for `/m/home`, `/m/quotes` (timeframe and strategy toggle), `/m/history`, and `/m/connect-broker`.
  - **`blueprints/secure_auth.py`**: Session authentication, password hashing, and user registration.
  - **`services/autonomous_scanner.py`**: Autonomous market scanning engine supporting Swing (1H/4H) and Scalping (M1/M5) modes.
  - **`services/broker_bridge.py`**: Fernet-encrypted vault for MT4/MT5 broker account credentials.
  - **`services/news_intelligence.py`**: Fundamental news scraping and Macro AI Sentiment Veto Gate.
  - **`models.py`**: SQLAlchemy models for users, licenses, broker connections, and preferences.
  - **`trading_engine.py`**: Signal synthesis, risk validation, and trade dispatch logic.
  - **`license_manager.py`**: Cryptographic RSA licensing and subscription enforcement.
- **`space_trading_fx/`**: Supporting core calculation and strategy utilities.
- **`tests/`**: Complete pytest test suite (99 tests) with unit and integration coverage.

---

## Development Setup

### 1. Environment & Dependencies

From the project root:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with development requirements
pip install -e '.[dev]'
```

### 2. Configuration (`.env`)

Configure required environment variables in `.env` at the project root:

```env
FLASK_DEBUG=True
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
SESSION_SECRET=your-secure-session-key

# MetaApi Cloud integration
METAAPI_TOKEN=your_metaapi_cloud_token_here
METAAPI_ACCOUNT_ID=your_account_id_here
```

### 3. Database Schema

Initialize the SQLite database with Alembic:

```bash
alembic upgrade head
```

---

## Running the Application

### Web Dashboard
From the repository root:

```bash
python run.py
```
Access the dashboard locally at `http://127.0.0.1:5000`.

### Cloud Trading Robot
From the repository root:

```bash
# Check account telemetry
python metaapi_robot.py --info-only

# Execute a market order
python metaapi_robot.py --symbol EURUSD --volume 0.01 --action BUY
```

---

## Testing & Linting

### Running Pytest
```bash
pytest SpaceTradingFX/tests/ -v
```

### Code Style (Ruff)
```bash
# Check code style and formatting
ruff check .
ruff format --check .

# Auto-format
ruff format .
```
