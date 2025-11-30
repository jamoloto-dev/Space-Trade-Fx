# Space Trading FX

A Flask-based forex trading platform with license management and an automated trading bot.

## Project Structure

```
SpaceTradingFX/
├── space_trading_fx/          # Core trading bot package
│   ├── core/                  # Strategy engine and signal reading
│   ├── trading/               # Trade execution logic
│   ├── config/                # Configuration (settings)
│   ├── utils/                 # Logging and utilities
│   └── main.py                # Bot entry point
├── flask_dashboard/           # Web dashboard for license & trading management
│   ├── app.py                 # Flask app factory
│   ├── main.py                # Dashboard entry point (runs on port 5000)
│   ├── routes.py              # API routes and views
│   ├── models.py              # Database models
│   ├── license_manager.py      # License validation logic
│   ├── trading_engine.py       # Trading logic integration
│   ├── forex_data.py           # Forex data provider
│   └── templates/             # HTML templates
├── tests/                     # Unit tests
├── data/                      # Trading signals (signals.txt)
└── requirements.txt           # Python dependencies
```

## Setup

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
# OR from project root:
pip install -e .
```

### 3. Environment Variables

Create a `.env` file in the project root (example shown; adjust for production and do NOT commit real secrets):

```
SESSION_SECRET=your-secret-key-here
DATABASE_URL=postgresql://user:password@localhost/trading_db
# Or use SQLite (default): sqlite:///trading.db
# Feature flags
# Enable GPT-5 globally for all clients (default: true)
ENABLE_GPT5_FOR_ALL_CLIENTS=true
LICENSE_PRIVATE_KEY_PEM="-----BEGIN RSA PRIVATE KEY-----..."
LICENSE_PUBLIC_KEY_PEM="-----BEGIN RSA PUBLIC KEY-----..."
LICENSE_MAX_ACTIVATIONS=3
LICENSE_ACTIVATION_BASE_URL="https://your-domain.com/api/license"
```

## Running the Application

### Flask Dashboard (Web UI)

```bash
cd flask_dashboard
python main.py
```

The dashboard runs on `http://localhost:5000`

### Trading Bot

```bash
cd space_trading_fx
python main.py
```

The bot reads trading signals from `data/signals.txt`

## Key Components

### Core Package (`space_trading_fx/`)

- **strategy_engine.py** - Main strategy execution logic
- **signal_reader.py** - Reads trading signals from file
- **trade_executor.py** - Executes trades based on signals
- **logger.py** - Centralized logging with remote log transmission

### Flask Dashboard

- **License Management** - Create, validate, and activate licenses
- **Trading Preferences** - Configure currency pairs, risk levels, etc.
- **Account Summary** - View balance, open trades, P&L
- **Manual Trading** - Execute trades via web interface
- **Market Analysis** - Analyze forex market signals

## Testing

Run tests with pytest:

```bash
pytest tests/ -v
```

## Features

- ✅ User authentication and session management
- ✅ License-based access control
- ✅ Automated trading bot with signal reading
- ✅ Real-time forex data integration
- ✅ Trade execution and P&L tracking
- ✅ Web dashboard for manual control
- ✅ Logging with remote transmission
- ✅ Database persistence (PostgreSQL or SQLite)
- ✅ Feature flags (e.g., `ENABLE_GPT5_FOR_ALL_CLIENTS`)
- ✅ License activation & MT5 account binding

## Dependencies

See `requirements.txt` or `pyproject.toml` for the full list:

- Flask & Flask extensions (login, SQLAlchemy, dance)
- Loguru (advanced logging)
- Pandas (data analysis)
- Schedule (task scheduling)
- Requests (HTTP client)
- Pytest (testing)
- PSycopg2 (PostgreSQL driver)

## Security Notes

- Set `SESSION_SECRET` environment variable in production
- Do not commit `.env` files with real credentials
- Use strong, unique license keys for production
- Store API keys and secrets in environment variables only
- Provide RSA keys via `LICENSE_PRIVATE_KEY_PEM` / `LICENSE_PUBLIC_KEY_PEM` (avoid hardcoding)
- Limit activations using `LICENSE_MAX_ACTIVATIONS`; monitor via `/api/license/status`

## Development

### Adding Tests

Place unit tests in `tests/` directory with `test_` prefix:

```python
# tests/test_my_feature.py
def test_example():
    assert 1 + 1 == 2
```

### Code Style

- Follow PEP 8
- Use absolute imports within the `space_trading_fx` package
- Add docstrings to functions and classes

## Troubleshooting

**Import errors when running the bot:**
- Ensure `space_trading_fx` is in PYTHONPATH
- Run from the project root directory
- Check that venv is activated

**Database errors:**
- Set `DATABASE_URL` environment variable
- Run migrations if applicable
- Check database credentials

**Missing dependencies:**
- Reinstall: `pip install -r requirements.txt`
- Check Python version: requires Python >= 3.12

**License activation issues:**
- Add activation base URL to MT5: Tools → Options → Expert Advisors → Allow WebRequest for listed URL (`https://your-domain.com`)
- Confirm license key matches one issued after payment
- Ensure MT5 account/server in Preferences matches terminal values
- Check `/api/license/status?license_key=...` returns `ok:true`

## License

See LICENSE file for details.

## Continuous Integration

This project uses GitHub Actions for automated testing and linting:

- **Tests** (`.github/workflows/test.yml`): Runs pytest on every push and PR
- **Lint** (`.github/workflows/lint.yml`): Runs flake8, pylint, black, and isort checks

### Local Development Setup

#### 1. Install Pre-commit Hooks

To automatically run linting and formatting on commit:

```bash
pip install pre-commit
pre-commit install
```

Now code will be automatically formatted and checked before each commit.

#### 2. Run Tests Locally

```bash
pytest SpaceTradingFX/tests/ -v
```

#### 3. Run Linting Checks

```bash
# Check with flake8
flake8 SpaceTradingFX/space_trading_fx SpaceTradingFX/flask_dashboard

# Check with pylint
pylint SpaceTradingFX/space_trading_fx SpaceTradingFX/flask_dashboard

# Format code with black
black SpaceTradingFX/space_trading_fx SpaceTradingFX/flask_dashboard --line-length=120

# Sort imports with isort
isort SpaceTradingFX/space_trading_fx SpaceTradingFX/flask_dashboard
```

#### 4. Code Style Guidelines

- **Line length**: 120 characters (configured in `.pylintrc`, `setup.cfg`, `black`)
- **Formatter**: black (automatic via pre-commit)
- **Import sorter**: isort (automatic via pre-commit)
- **Linters**: flake8 and pylint
- **Python version**: 3.12+

All pull requests must pass the CI checks before merging.
