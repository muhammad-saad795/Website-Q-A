#!/usr/bin/env bash
set -e

export PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers

echo "==> Starting gunicorn..."
exec gunicorn app:app \
  --worker-class gthread \
  --workers 1 \
  --threads 8 \
  --timeout 600 \
  --bind "0.0.0.0:${PORT:-8080}" \
  --log-level info \
  --access-logfile - \
  --error-logfile -
