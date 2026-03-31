#!/bin/bash
# ============================================
# DigitalOcean Droplet Deployment Script
# Run this on a fresh Ubuntu 22.04+ Droplet
# ============================================
set -e

APP_NAME="seodada"
APP_DIR="/opt/$APP_NAME"
APP_USER="seodada"
PYTHON_VERSION="3.11"

echo "=== SEO Dada - DigitalOcean Droplet Setup ==="

# 1. System updates and dependencies
echo "[1/8] Installing system dependencies..."
apt-get update && apt-get upgrade -y
apt-get install -y \
    python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev \
    python3-pip \
    postgresql-client \
    nginx \
    certbot python3-certbot-nginx \
    git curl wget unzip \
    libpq-dev gcc \
    libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev \
    supervisor

# 2. Install Google Chrome (for Selenium)
echo "[2/8] Installing Google Chrome..."
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update && apt-get install -y google-chrome-stable

# 3. Create application user and directory
echo "[3/8] Setting up application user and directory..."
id -u $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER
mkdir -p $APP_DIR
chown -R $APP_USER:$APP_USER $APP_DIR

# 4. Copy application files (assumes you've uploaded them to /tmp/seo)
echo "[4/8] Setting up application..."
if [ -d "/tmp/seo" ]; then
    cp -r /tmp/seo/* $APP_DIR/
    chown -R $APP_USER:$APP_USER $APP_DIR
fi

# 5. Create virtual environment and install dependencies
echo "[5/8] Setting up Python environment..."
sudo -u $APP_USER bash -c "
    cd $APP_DIR
    python${PYTHON_VERSION} -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
"

# Create necessary directories
sudo -u $APP_USER mkdir -p $APP_DIR/{download_files,crawled_data,flask_session,static/uploads}
mkdir -p /var/log/$APP_NAME

# 6. Create systemd service
echo "[6/8] Creating systemd service..."
cat > /etc/systemd/system/${APP_NAME}.service << 'SERVICEEOF'
[Unit]
Description=SEO Dada Gunicorn Application
After=network.target

[Service]
User=seodada
Group=seodada
WorkingDirectory=/opt/seodada
Environment="PATH=/opt/seodada/venv/bin"
EnvironmentFile=/opt/seodada/.env
ExecStart=/opt/seodada/venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=seodada

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable $APP_NAME

# 7. Configure Nginx reverse proxy
echo "[7/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/$APP_NAME << 'NGINXEOF'
server {
    listen 80;
    server_name seodada.com www.seodada.com;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
    }

    location /static/ {
        alias /opt/seodada/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# 8. SSL with Let's Encrypt
echo "[8/8] Setting up SSL..."
echo "Run the following command to get SSL certificate:"
echo "  certbot --nginx -d seodada.com -d www.seodada.com"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your .env file to $APP_DIR/.env"
echo "  2. Set FLASK_ENV=production in .env"
echo "  3. Start the service: systemctl start $APP_NAME"
echo "  4. Run SSL setup: certbot --nginx -d seodada.com -d www.seodada.com"
echo "  5. Check logs: journalctl -u $APP_NAME -f"
echo ""
