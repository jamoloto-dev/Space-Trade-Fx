#!/bin/sh
set -eu

# Schema changes are part of each release. The web process does not start
# until the transactional Alembic upgrade has completed successfully.
alembic upgrade head

# The lifecycle worker is an explicitly selected, separate process.  It is
# never spawned by Gunicorn or Flask's development reloader.
if [ "${1:-}" = "paper-worker" ]; then
  exec python -m flask_dashboard.paper_worker --interval "${PAPER_WORKER_INTERVAL:-30}"
fi

exec gunicorn --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 120 \
  --access-logfile - --error-logfile - --capture-output 'flask_dashboard:create_app()'
