import os

# Gunicorn configuration file
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
threads = 8
timeout = 600
worker_class = "gthread"
loglevel = "info"
accesslog = "-"
errorlog = "-"
