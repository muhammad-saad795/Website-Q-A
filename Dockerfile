# ── Stage 1: Use the official Playwright image (Chromium pre-installed) ──────
# This image ships with Chromium, all system dependencies, and Python.
# No browser download needed at runtime — it's baked into the image.
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Railway injects $PORT at runtime; default to 8080 for local docker run
ENV PORT=8080

# Expose for documentation purposes
EXPOSE 8080

# Start gunicorn
CMD gunicorn app:app \
    --worker-class gthread \
    --workers 1 \
    --threads 8 \
    --timeout 600 \
    --bind "0.0.0.0:${PORT}" \
    --log-level info \
    --access-logfile - \
    --error-logfile -
