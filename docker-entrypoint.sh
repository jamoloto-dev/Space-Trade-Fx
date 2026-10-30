#!/bin/sh
set -eu

# Ensure essential runtime environment variables have safe defaults if not provided
if [ -z "${SESSION_SECRET:-}" ] && [ -z "${SECRET_KEY:-}" ]; then
  export SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite:////app/trading.db"
fi

if [ -z "${LICENSE_PUBLIC_KEY_PEM:-}" ] || [ -z "${LICENSE_PRIVATE_KEY_PEM:-}" ]; then
  KEY_BITS="2048"
  if [ "${FLASK_ENV:-}" = "testing" ]; then
    KEY_BITS="512"
  fi
  eval "$(python3 -c "import rsa; pub, priv = rsa.newkeys($KEY_BITS); print('export LICENSE_PUBLIC_KEY_PEM=\"' + pub.save_pkcs1().decode().replace('\n', '\\\n') + '\"'); print('export LICENSE_PRIVATE_KEY_PEM=\"' + priv.save_pkcs1().decode().replace('\n', '\\\n') + '\"')")"
fi

# Schema changes are part of each release. The web process does not start
# until the transactional Alembic upgrade has completed successfully.
alembic upgrade head

# The lifecycle worker is an explicitly selected, separate process.  It is
# never spawned by Gunicorn or Flask's development reloader.
if [ "${1:-}" = "paper-worker" ]; then
  exec python -m flask_dashboard.paper_worker --interval "${PAPER_WORKER_INTERVAL:-30}"
fi

exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 4 --threads 2 --timeout 120 \
  --access-logfile - --error-logfile - --capture-output 'flask_dashboard:create_app()'
