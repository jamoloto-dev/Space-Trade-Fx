Setup and environment variables
===============================

This project uses a few environment variables to configure authentication and a default local admin user used for development and testing.

Default admin (development)
- `DEFAULT_ADMIN_EMAIL` - Email for the default admin user created at app startup. Default: `molotojafta30@gmail.com`.
- `DEFAULT_ADMIN_FIRST` - First name for the admin. Default: `Jafta`.
- `DEFAULT_ADMIN_LAST` - Last name for the admin. Default: `Moloto`.
- `DEFAULT_ADMIN_ID` - The DB `id` for the default admin. Default: `jafta-moloto`.

Authentication / OIDC
- `AUTH_CLIENT_ID` or `OIDC_CLIENT_ID` - The OAuth/OIDC client id to use for the provider. No default for production; a `dev-client-id` is used when not provided.
- `ISSUER_URL` or `OIDC_ISSUER_URL` - The OIDC issuer base URL (e.g. `https://auth.example.com/oidc`). Default for local development: `http://localhost:8000/oidc`.

Notes
- For production, set the real `AUTH_CLIENT_ID` and `ISSUER_URL` and do not rely on the development defaults.
- You can override the default admin by setting `DEFAULT_ADMIN_EMAIL` (and related vars) before starting the app.

Example (bash)
```bash
export DEFAULT_ADMIN_EMAIL="molotojafta30@gmail.com"
export DEFAULT_ADMIN_FIRST="Jafta"
export DEFAULT_ADMIN_LAST="Moloto"
export DEFAULT_ADMIN_ID="jafta-moloto"

# OIDC provider settings (production)
export AUTH_CLIENT_ID="your-client-id"
export ISSUER_URL="https://auth.example.com/oidc"

# Feature flags
export ENABLE_GPT5_FOR_ALL_CLIENTS=true
export LICENSE_PRIVATE_KEY_PEM="-----BEGIN RSA PRIVATE KEY-----..."
export LICENSE_PUBLIC_KEY_PEM="-----BEGIN RSA PUBLIC KEY-----..."
export LICENSE_MAX_ACTIVATIONS=3
export LICENSE_ACTIVATION_BASE_URL="https://your-domain.com/api/license"

# Start the app (example)
python SpaceTradingFX/flask_dashboard/main.py
```

License activation flow (summary)
1. User purchases license; Stripe/Ozow webhook creates license record.
2. User runs EA which calls POST `$LICENSE_ACTIVATION_BASE_URL/activate` with license key + MT5 account.
3. Server records activation if within `LICENSE_MAX_ACTIVATIONS`.
4. EA periodically calls GET `$LICENSE_ACTIVATION_BASE_URL/status?license_key=...` to validate.
5. Admin can revoke license by changing status or (future) revocation endpoint.

MetaTrader setup
- Add `https://your-domain.com` under Tools → Options → Expert Advisors → Allow WebRequest for listed URL
- Confirm account number and server captured in Preferences screen so binding succeeds.

Default admin password (development)
- `DEFAULT_ADMIN_PASSWORD` - Optional. If provided, the seeded default admin will use this password for local login. Only use this for development/testing; do NOT set a plaintext password in production.

Trading direction preferences
- Each user can set per-pair direction preferences via the UI at `GET /preferences`.
- `direction_preferences` is stored on the `TradingPreference` model as JSON, e.g. `{ "EURUSD": "BUY", "GBPUSD": "BOTH" }`.
- Values are: `BOTH`, `BUY`, or `SELL`. The bot will only open trades that match the configured direction for a pair.

Admin local login (JSON)
- POST `/admin/login` with `{"email": "you@example.com", "password": "secret"}` to authenticate as an admin. Successful login will set the Flask session cookie.

License management (admin)
- GET `/admin/licenses` - list licenses
- POST `/admin/licenses/create` - create a license (JSON: `user_id`, optional `license_type`, `max_active_trades`)
- POST `/admin/licenses/<id>/status` - change status (JSON: `status`)


If you need help configuring a real OIDC provider, tell me which provider you want to use and I can add step-by-step setup notes.
