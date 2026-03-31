#!/bin/bash
# ============================================
# DigitalOcean Droplet Deployment Script
# Run this on a fresh Ubuntu 22.04+ Droplet
# Usage: bash deploy_digitalocean.sh
# ============================================
set -e

APP_NAME="seodada"
APP_DIR="/opt/$APP_NAME"
APP_USER="seodada"
GITHUB_REPO="https://github.com/Callince/seo.git"
DOMAIN="seodada.com"

echo "=========================================="
echo "  SEO Dada - DigitalOcean Droplet Setup"
echo "=========================================="

# 1. Add swap space (important for 2GB Droplets)
echo ""
echo "[1/9] Adding swap space..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  -> 2GB swap added"
else
    echo "  -> Swap already exists, skipping"
fi

# 2. System updates and dependencies
echo ""
echo "[2/9] Installing system dependencies..."
apt-get update && apt-get upgrade -y
apt-get install -y \
    software-properties-common \
    python3 python3-venv python3-dev python3-pip \
    postgresql-client \
    nginx \
    certbot python3-certbot-nginx \
    git curl wget unzip \
    libpq-dev gcc \
    libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev \
    ufw

# 3. Install Google Chrome (for Selenium)
echo ""
echo "[3/9] Installing Google Chrome..."
if ! command -v google-chrome &> /dev/null; then
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
    apt-get update && apt-get install -y google-chrome-stable
    echo "  -> Chrome installed: $(google-chrome --version)"
else
    echo "  -> Chrome already installed: $(google-chrome --version)"
fi

# 4. Configure firewall
echo ""
echo "[4/9] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
echo "  -> Firewall enabled (SSH + Nginx)"

# 5. Create application user and clone code
echo ""
echo "[5/9] Setting up application..."
id -u $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER
mkdir -p $APP_DIR

if [ -d "$APP_DIR/.git" ]; then
    echo "  -> Pulling latest code..."
    cd $APP_DIR && sudo -u $APP_USER git pull origin main
else
    echo "  -> Cloning from GitHub..."
    rm -rf $APP_DIR/*
    sudo -u $APP_USER git clone $GITHUB_REPO $APP_DIR
fi
chown -R $APP_USER:$APP_USER $APP_DIR

# 6. Create virtual environment and install dependencies
echo ""
echo "[6/9] Setting up Python environment..."
sudo -u $APP_USER bash -c "
    cd $APP_DIR
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
"

# Create necessary directories
sudo -u $APP_USER mkdir -p $APP_DIR/{download_files,crawled_data,flask_session,static/uploads}

# 7. Create systemd service
echo ""
echo "[7/9] Creating systemd service..."
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

# Resource limits
LimitNOFILE=65535
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable $APP_NAME
echo "  -> systemd service created and enabled"

# 8. Configure Nginx reverse proxy
echo ""
echo "[8/9] Configuring Nginx..."
cat > /etc/nginx/sites-available/$APP_NAME << NGINXEOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    client_max_body_size 16M;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }

    location /static/ {
        alias /opt/seodada/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /robots.txt {
        alias /opt/seodada/static/robots.txt;
    }

    location /favicon.ico {
        alias /opt/seodada/static/images/favicon.ico;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
echo "  -> Nginx configured and restarted"

# 9. Summary
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  App directory : $APP_DIR"
echo "  Service name  : $APP_NAME"
echo "  Nginx config  : /etc/nginx/sites-available/$APP_NAME"
echo ""
echo "  NEXT STEPS:"
echo "  ─────────────────────────────────────"
echo "  1. Create the .env file:"
echo "     nano $APP_DIR/.env"
echo "     (paste your environment variables)"
echo ""
echo "  2. Set ownership:"
echo "     chown $APP_USER:$APP_USER $APP_DIR/.env"
echo "     chmod 600 $APP_DIR/.env"
echo ""
echo "  3. Start the application:"
echo "     systemctl start $APP_NAME"
echo ""
echo "  4. Check it's running:"
echo "     systemctl status $APP_NAME"
echo "     curl http://localhost:8080"
echo ""
echo "  5. Point your domain DNS to this Droplet IP:"
echo "     $(curl -s ifconfig.me 2>/dev/null || echo '<your-droplet-ip>')"
echo ""
echo "  6. Setup SSL (after DNS propagates):"
echo "     certbot --nginx -d $DOMAIN -d www.$DOMAIN"
echo ""
echo "  USEFUL COMMANDS:"
echo "  ─────────────────────────────────────"
echo "  View logs     : journalctl -u $APP_NAME -f"
echo "  Restart app   : systemctl restart $APP_NAME"
echo "  Restart nginx : systemctl restart nginx"
echo "  Update code   : cd $APP_DIR && sudo -u $APP_USER git pull && systemctl restart $APP_NAME"
echo ""
