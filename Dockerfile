# Use the official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway provides $PORT. We use the Shell form of CMD to ensure variable expansion.
CMD gunicorn app:app \
    --worker-class gthread \
    --workers 1 \
    --threads 8 \
    --timeout 600 \
    --bind 0.0.0.0:$PORT \
    --log-level info \
    --access-logfile - \
    --error-logfile -
