# Developer Setup Guide

This guide covers setting up and running SpaceTradingFX locally for development and testing.

---

## 1. Environment Setup

From the repository root directory:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies in editable mode
pip install -e '.[dev]'
```

---

## 2. Environment Configuration

Create a `.env` file in the project root:

```env
# Server
FLASK_DEBUG=True
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
SESSION_SECRET=local-development-session-secret

# MetaApi Cloud Credentials
METAAPI_TOKEN=your_metaapi_cloud_token
METAAPI_ACCOUNT_ID=your_metaapi_account_id

# Database
# If omitted, defaults to SQLite trading.db in the repository root
# DATABASE_URL=postgresql://user:password@localhost:5432/trading_db
```

---

## 3. Database Initialization

Apply database migrations:

```bash
alembic upgrade head
```

To create an administrator account:

```bash
python -m SpaceTradingFX.flask_dashboard.bootstrap_admin admin@example.com
```

---

## 4. Execution

### Start Web Server
```bash
python run.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Run MetaApi Trading Robot
```bash
# View account status and telemetry
python metaapi_robot.py --info-only

# Run market execution
python metaapi_robot.py --symbol EURUSD --volume 0.01 --action BUY
```

---

## 5. Verification

Verify the system before submitting changes:

```bash
# Run complete test suite (99 tests)
pytest SpaceTradingFX/tests/ -v

# Run linting and formatting checks
ruff check .
ruff format --check .
```
