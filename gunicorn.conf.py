bind = "0.0.0.0:5000"
workers = 3  # Reduced workers
timeout = 120
keepalive = 2
max_requests = 800
max_requests_jitter = 50
preload_app = True

# Logging
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"

proc_name = 'seodada_gunicorn'
user = 'ec2-user'
group = 'ec2-user'
