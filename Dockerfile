# Use the official Playwright image (Chromium pre-installed)
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

# Set production environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Railway provides the PORT environment variable
ENV PORT=8080

WORKDIR /app

# Install dependencies directly into system Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port (for documentation)
EXPOSE 8080

# We use 'sh -c' to ensure the $PORT environment variable is expanded correctly
CMD ["sh", "-c", "gunicorn app:app --worker-class gthread --workers 1 --threads 8 --timeout 600 --bind 0.0.0.0:${PORT} --log-level info --access-logfile - --error-logfile -"]
