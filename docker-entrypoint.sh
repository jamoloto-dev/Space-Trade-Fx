#!/bin/sh
set -eu

# Schema changes are part of each release. The web process does not start
# until the transactional Alembic upgrade has completed successfully.
alembic upgrade head
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 120 \
  --access-logfile - --error-logfile - --capture-output 'flask_dashboard:create_app()'
