# MetaApi Cloud Trading Robot Guide

The `metaapi_robot.py` script is an institutional-grade, asynchronous trading robot powered by the [`metaapi-cloud-sdk`](https://metaapi.cloud/docs/client/) Python package. It interfaces directly with MT4 and MT5 broker accounts in the cloud without requiring a locally installed MetaTrader desktop terminal.

---

## 1. Prerequisites and Installation

Install dependencies from the workspace virtual environment:

```bash
# Ensure virtual environment is activated
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the MetaApi Cloud SDK and python-dotenv
pip install metaapi-cloud-sdk python-dotenv
```

---

## 2. Configuration (`.env`)

The robot loads its credentials securely via `python-dotenv` from the root `.env` file:

```env
# MetaApi Provisioning & RPC API Token (from https://app.metaapi.cloud/token)
METAAPI_TOKEN=your_metaapi_token_here

# Target MetaTrader Account ID (optional; if omitted, the robot auto-discovers registered accounts)
METAAPI_ACCOUNT_ID=f911e0d0-5bdd-400b-9b10-521c304d9d84
```

> [!IMPORTANT]
> Never commit `.env` or credentials to version control. The `.gitignore` file is configured to exclude all `.env` files.

---

## 3. Usage & Command-Line Interface

Run the robot directly from the repository root:

```bash
python metaapi_robot.py [OPTIONS]
```

### CLI Arguments

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--symbol` | `str` | `EURUSD` | Trading symbol (e.g., `EURUSD`, `GBPUSD`, `USDJPY`, `USDZAR`) |
| `--volume` | `float` | `0.01` | Order lot size (e.g., `0.01` micro lot, `0.10` mini lot, `1.0` standard lot) |
| `--action` | `str` | `BUY` | Market order action: `BUY` or `SELL` |
| `--account-id` | `str` | `None` | Override the MetaApi account ID from `.env` |
| `--info-only` | `flag` | `False` | Display live account telemetry and connection status without placing orders |

---

## 4. Execution Examples

### A. Telemetry & Account Status Only (Dry Run)
Inspect balance, equity, margin, leverage, and server connection without placing trades:

```bash
python metaapi_robot.py --info-only
```

**Sample Output**:
```text
============================================================
               LIVE METAAPI ACCOUNT TELEMETRY
============================================================
  Broker Server : IFXBrokers-Real
  Currency      : ZAR
  Balance       : ZAR 3,000.00
  Equity        : ZAR 3,000.00
  Free Margin   : ZAR 3,000.00
  Leverage      : 1:500
============================================================
```

### B. Execute a Test Market Buy Order
```bash
python metaapi_robot.py --symbol EURUSD --volume 0.01 --action BUY
```

### C. Execute a Market Sell Order on USDZAR
```bash
python metaapi_robot.py --symbol USDZAR --volume 0.05 --action SELL
```

---

## 5. Architecture & Execution Lifecycle

`metaapi_robot.py` follows a strict institutional execution lifecycle:

```text
[Load .env] ──► [Initialize MetaApi Client] ──► [Resolve Account ID]
                                                        │
┌───────────────────────────────────────────────────────┘
▼
[Deploy Cloud Instance (if UNDEPLOYED)]
│
▼
[Wait for Broker Terminal Connection (wait_connected)]
│
▼
[Establish Synchronized RPC Connection (wait_synchronized)]
│
▼
[Query Live Account Telemetry (balance, equity, margin)]
│
▼
[Dispatch Market Order (BUY / SELL)] ──► Log Order Ticket & Position ID
│
▼
[Clean RPC Connection Teardown in finally: block]
```

---

## 6. Troubleshooting & Cloud Deployment Status

### Account Deployment Declined (403 Forbidden)
```text
Account deployment declined by MetaApi: To allow trading account deployment please top up your account.
```
- **Cause**: MetaApi hosts dedicated MetaTrader terminal instances on cloud infrastructure. New or undeployed accounts require active subscription credits on the MetaApi platform before the instance can be deployed to `DEPLOYED` status.
- **Resolution**:
  1. Log in to [app.metaapi.cloud](https://app.metaapi.cloud).
  2. Verify your subscription status or add cloud credits under billing.
  3. Deploy the account instance directly in the MetaApi dashboard.
  4. Re-run `python metaapi_robot.py`.
