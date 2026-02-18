#!/bin/bash

# Default to 8080 if PORT is not set
PORT="${PORT:-8080}"

echo "🚀 Starting Browser QA Tool on port ${PORT}..."

# Execute gunicorn
exec gunicorn app:app \
    --worker-class gthread \
    --workers 1 \
    --threads 8 \
    --timeout 600 \
    --bind "0.0.0.0:${PORT}" \
    --log-level info \
    --access-logfile - \
    --error-logfile -
