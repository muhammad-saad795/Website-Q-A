# Use the official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (including gunicorn.conf.py)
COPY . .

# We use the Python configuration file to avoid all shell expansion issues
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
