# Autonomous Market Scanner & Trading Engine

SpaceTradingFX features a built-in autonomous market scanner and multi-timeframe trading engine capable of operating in **Swing Trading (1H/4H)** or **Ultra Scalping (M1/M5)** modes with fundamental **Macro AI News Sentiment Veto** gates.

---

## 1. Operating Modes

### A. Ultra Scalping Mode (M1 / M5)
- **Timeframes**: Evaluates 1-minute (`1m`) and 5-minute (`5m`) candlestick data.
- **Indicators**:
  - Exponential Moving Average: **EMA 5** and **EMA 13** for rapid trend shifts.
  - Relative Strength Index: **RSI 7** for fast overbought / oversold oscillation detection.
  - Average True Range: **ATR 5** for micro-pip volatility brackets.
- **Risk & Bracket Sizing**:
  - Ultra-tight micro-pip stop-loss: `1.0 × ATR(5)`
  - Ultra-tight take-profit: `1.5 × ATR(5)`
  - Designed for high-frequency signal capture closing within minutes.

### B. Swing Trading Mode (1H / 4H)
- **Timeframes**: Evaluates 1-hour (`1h`) and 4-hour (`4h`) candlestick data.
- **Indicators**:
  - Moving Averages: **EMA 20** and **EMA 50** for institutional trend confirmation.
  - Momentum: **RSI 14** and **MACD (12, 26, 9)**.
  - Volatility: **ATR 14** for structural support/resistance stop brackets.
- **Risk & Bracket Sizing**:
  - Stop-loss: `1.5 × ATR(14)`
  - Take-profit: `2.5 × ATR(14)`

---

## 2. Macro AI News Sentiment Veto Gate

Before any automated trade signal is permitted to dispatch to a broker bridge or ledger, it must pass the **Macro AI News Intelligence Gate** (`news_intelligence.py`):

1. **Live Fundamental News Ingestion**:
   - Gathers live real-time financial headlines for the currency pair currencies (e.g. Fed, ECB, BoE, BoJ, SARB, US Dollar, Euro, Rand).
2. **Sentiment Scoring**:
   - Calculates polarity scores from -1.0 (extremely bearish) to +1.0 (extremely bullish).
3. **Execution Veto**:
   - If a technical BUY signal is contradicted by strong bearish fundamental news (score $\le -0.40$), the trade is blocked:
     ```text
     WARNING in trading_engine: AI Veto Gate triggered for GBPUSD BUY:
     Macro AI Veto: BUY signal contradicted by strong BEARISH news (-0.50)
     (Trade execution blocked)
     ```
   - If a technical SELL signal is contradicted by strong bullish fundamental news (score $\ge +0.40$), the trade is blocked.

---

## 3. Configuration & Preference Management

User preferences and auto-pilot execution are stored in `trading_preferences` in the database:

- `currency_pairs`: List of symbols to scan (e.g., `["EURUSD", "GBPUSD", "USDJPY", "USDZAR"]`).
- `timeframe`: Timeframe string (`"1M"`, `"5M"`, `"15M"`, `"1H"`, `"4H"`, `"1D"`).
- `risk_percentage`: Decimal risk percentage per position (capped between `0.01%` and `2.0%`).
- `max_concurrent_trades`: Maximum allowed simultaneous open positions (1 to 20).
- `trading_enabled`: Master kill switch for user trading.
- `strategy_settings`:
  ```json
  {
    "auto_pilot": true,
    "scalping_mode": true,
    "automated_paper_trading": true
  }
  ```

---

## 4. Triggering the Autonomous Scanner

### Via Web Dashboard
When the Flask web server runs (`python run.py`), the background scheduler automatically triggers scan cycles at the configured polling interval.

### Programmatically
You can invoke a forced synchronous scan cycle via Python:

```python
from flask_dashboard import create_app
from flask_dashboard.services.autonomous_scanner import run_autonomous_cycle

app = create_app()
with app.app_context():
    summary = run_autonomous_cycle(app, force_scan=True)
    print("Autonomous Cycle Summary:", summary)
```
