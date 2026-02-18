# Use the official Playwright image (Chromium pre-installed)
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

# Set production environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

WORKDIR /app

# Install dependencies directly into system Python (no venv needed in Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port
EXPOSE 8080

# Start gunicorn with 1 worker and multiple threads (best for async QA tasks)
CMD gunicorn app:app \
    --worker-class gthread \
    --workers 1 \
    --threads 8 \
    --timeout 600 \
    --bind "0.0.0.0:${PORT}" \
    --log-level info \
    --access-logfile - \
    --error-logfile -
