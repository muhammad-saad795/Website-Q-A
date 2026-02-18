#!/usr/bin/env bash
set -e

echo "==> Installing Playwright browsers..."
playwright install chromium
echo "==> Playwright ready."

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
