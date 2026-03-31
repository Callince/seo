import os

# Bind to PORT env var (DigitalOcean injects this) or default to 8080
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = int(os.environ.get('GUNICORN_WORKERS', '3'))
timeout = 120
keepalive = 2
max_requests = 800
max_requests_jitter = 50
preload_app = True

# Log to stdout/stderr for DigitalOcean App Platform log collection
accesslog = "-"
errorlog = "-"
loglevel = "info"

proc_name = 'seodada_gunicorn'
