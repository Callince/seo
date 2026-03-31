# SEO Dada - DigitalOcean Droplet Deployment Guide

Complete guide to deploy SEO Dada on a DigitalOcean Droplet with Ubuntu, Nginx, SSL, and PostgreSQL.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create a Droplet](#2-create-a-droplet)
3. [SSH Key Setup](#3-ssh-key-setup)
4. [Initial Server Setup](#4-initial-server-setup)
5. [Clone and Install Application](#5-clone-and-install-application)
6. [Configure Environment Variables](#6-configure-environment-variables)
7. [Setup Systemd Service](#7-setup-systemd-service)
8. [Configure Nginx](#8-configure-nginx)
9. [Start the Application](#9-start-the-application)
10. [Restore Database](#10-restore-database)
11. [Run Seed Script](#11-run-seed-script)
12. [DNS Configuration (GoDaddy)](#12-dns-configuration-godaddy)
13. [SSL Certificate Setup](#13-ssl-certificate-setup)
14. [Run Tests](#14-run-tests)
15. [Maintenance Commands](#15-maintenance-commands)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Prerequisites

- DigitalOcean account
- GitHub repository with the application code (`Callince/seo`)
- Domain name (e.g., `seodada.com`) managed via GoDaddy or any registrar
- DigitalOcean Managed PostgreSQL database (already provisioned)
- SMTP credentials (Gmail app passwords for `support@seodada.com` and `payment@seodada.com`)
- Razorpay API keys
- reCAPTCHA v2 keys

---

## 2. Create a Droplet

1. Go to [cloud.digitalocean.com/droplets/new](https://cloud.digitalocean.com/droplets/new)
2. Select the following options:

| Setting         | Value                          |
|-----------------|--------------------------------|
| **Image**       | Ubuntu 24.04 LTS               |
| **Plan**        | Regular, $12-16/mo (2GB RAM)   |
| **Region**      | Bangalore (BLR1)               |
| **Auth**        | SSH Key (see Step 3)           |
| **Hostname**    | `seodada`                      |

3. Click **Create Droplet**
4. Note the **Droplet IP address** (e.g., `168.144.17.119`)

---

## 3. SSH Key Setup

If you don't have an SSH key on your local machine, generate one:

```bash
ssh-keygen -t ed25519 -C "seodada-droplet" -f ~/.ssh/id_ed25519 -N ""
```

View your public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the full output (starts with `ssh-ed25519 ...`) and paste it in the DigitalOcean SSH key dialog during Droplet creation.

Test the connection:

```bash
ssh root@<DROPLET_IP>
```

---

## 4. Initial Server Setup

SSH into the Droplet and run these commands:

### 4.1 Add Swap Space (important for 2GB Droplets)

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 4.2 Install System Dependencies

```bash
apt-get update && apt-get upgrade -y
apt-get install -y \
    software-properties-common \
    python3 python3-full python3-venv python3-dev python3-pip \
    postgresql-client \
    nginx \
    certbot python3-certbot-nginx \
    git curl wget unzip \
    libpq-dev gcc \
    libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev \
    ufw
```

### 4.3 Install Google Chrome (required for Selenium)

```bash
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update && apt-get install -y google-chrome-stable
```

### 4.4 Configure Firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

---

## 5. Clone and Install Application

### 5.1 Create Application User

```bash
useradd -r -m -s /bin/bash seodada
mkdir -p /opt/seodada
chown seodada:seodada /opt/seodada
```

### 5.2 Clone the Repository

```bash
sudo -u seodada git clone https://github.com/Callince/seo.git /opt/seodada
```

### 5.3 Create Python Virtual Environment

```bash
cd /opt/seodada
sudo -u seodada python3 -m venv venv
sudo -u seodada /opt/seodada/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u seodada /opt/seodada/venv/bin/pip install -r requirements.txt
```

### 5.4 Create Required Directories

```bash
sudo -u seodada mkdir -p /opt/seodada/{download_files,crawled_data,flask_session,static/uploads}
```

---

## 6. Configure Environment Variables

Create the `.env` file:

```bash
nano /opt/seodada/.env
```

Paste the following (replace placeholder values with your actual credentials):

```env
# Flask
FLASK_ENV=production
SECRET_KEY=<generate-with: python3 -c "import secrets; print(secrets.token_hex(32))">

# Database (DigitalOcean Managed PostgreSQL)
DB_USERNAME=doadmin
DB_PASSWORD=<your-db-password>
DB_HOST=<your-db-host>.db.ondigitalocean.com
DB_PORT=25060
DB_NAME=defaultdb
DB_SSLMODE=require

# Email/SMTP
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USE_SSL=False
MAIL_USERNAME=support@seodada.com
MAIL_PASSWORD=<support-app-password>
MAIL_DEFAULT_SENDER=support@seodada.com
MAIL_SUPPORT_USERNAME=support@seodada.com
MAIL_SUPPORT_PASSWORD=<support-app-password>
MAIL_SUPPORT_SENDER=support@seodada.com
MAIL_PAYMENT_USERNAME=payment@seodada.com
MAIL_PAYMENT_PASSWORD=<payment-app-password>
MAIL_PAYMENT_SENDER=payment@seodada.com
USE_GMAIL_API=False

# Redis (optional)
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Razorpay
RAZORPAY_KEY_ID=<your-razorpay-key>
RAZORPAY_KEY_SECRET=<your-razorpay-secret>
RAZORPAY_WEBHOOK_SECRET=<your-webhook-secret>

# reCAPTCHA v2
RECAPTCHA_SITE_KEY=<your-site-key>
RECAPTCHA_SECRET_KEY=<your-secret-key>

# Security
CRON_SECRET=<generate-random-string>
SUPER_ADMIN_PASSWORD=<strong-admin-password>

# Site
SITE_URL=https://seodada.com
```

Secure the file:

```bash
chown seodada:seodada /opt/seodada/.env
chmod 600 /opt/seodada/.env
```

---

## 7. Setup Systemd Service

Create the service file:

```bash
cat > /etc/systemd/system/seodada.service << 'EOF'
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
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
```

Enable the service:

```bash
systemctl daemon-reload
systemctl enable seodada
```

---

## 8. Configure Nginx

Create the Nginx config:

```bash
cat > /etc/nginx/sites-available/seodada << 'EOF'
server {
    listen 80;
    server_name seodada.com www.seodada.com;

    client_max_body_size 16M;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }

    location /static/ {
        alias /opt/seodada/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
EOF
```

Enable the site and restart Nginx:

```bash
ln -sf /etc/nginx/sites-available/seodada /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

---

## 9. Start the Application

```bash
systemctl start seodada
```

Verify it's running:

```bash
systemctl status seodada
curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/
# Should output: 200
```

---

## 10. Restore Database

If migrating from an existing server with a database backup (`flaskdb_backup.sql`):

### 10.1 Fix Owner References

On your local machine, replace the old database owner with the DO user:

```bash
cp flaskdb_backup.sql flaskdb_backup_do.sql
sed -i 's/OWNER TO flaskuser/OWNER TO doadmin/g' flaskdb_backup_do.sql
sed -i 's/Owner: flaskuser/Owner: doadmin/g' flaskdb_backup_do.sql
```

### 10.2 Upload to Droplet

```bash
scp flaskdb_backup_do.sql root@<DROPLET_IP>:/tmp/
```

### 10.3 Stop the App and Restore

```bash
ssh root@<DROPLET_IP>
systemctl stop seodada
```

Drop existing tables:

```bash
export PGPASSWORD='<your-db-password>'
DB_HOST="<your-db-host>.db.ondigitalocean.com"

psql -h $DB_HOST -p 25060 -U doadmin -d defaultdb -c "
DO \$\$ DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END \$\$;
"
```

Restore the backup:

```bash
psql -h $DB_HOST -p 25060 -U doadmin -d defaultdb < /tmp/flaskdb_backup_do.sql
```

Verify:

```bash
psql -h $DB_HOST -p 25060 -U doadmin -d defaultdb -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
```

Restart the app:

```bash
systemctl start seodada
```

---

## 11. Run Seed Script

If starting with a fresh database (no backup), seed default data:

```bash
cd /opt/seodada
sudo -u seodada /opt/seodada/venv/bin/python seed.py
```

This creates:
- Super admin account (`manikandan@fourdm.com`)
- Default subscription plans (Basic, Standard, Premium)
- Default website settings

Options:

```bash
python seed.py              # Create tables + seed data
python seed.py --tables     # Only create tables
python seed.py --seed       # Only seed data (tables must exist)
python seed.py --reset      # Drop all tables and recreate (DESTRUCTIVE)
```

---

## 12. DNS Configuration (GoDaddy)

1. Log in to [dcc.godaddy.com](https://dcc.godaddy.com/)
2. Go to your domain > **DNS** > **DNS Records**
3. **Delete** any existing CNAME record for `www` (conflicts with A records)
4. Update/create these A records:

| Type | Name  | Value            | TTL         |
|------|-------|------------------|-------------|
| A    | `@`   | `<DROPLET_IP>`   | 600 seconds |
| A    | `www` | `<DROPLET_IP>`   | 600 seconds |

5. Wait 5-30 minutes for DNS propagation

Verify propagation:

```bash
nslookup seodada.com 8.8.8.8
nslookup www.seodada.com 8.8.8.8
```

Both should return your Droplet IP.

---

## 13. SSL Certificate Setup

After DNS has propagated, run:

```bash
certbot --nginx -d seodada.com -d www.seodada.com --non-interactive --agree-tos --email support@seodada.com --redirect
```

This will:
- Obtain a free Let's Encrypt SSL certificate
- Configure Nginx for HTTPS
- Auto-redirect HTTP to HTTPS
- Set up automatic renewal

Verify HTTPS:

```bash
curl -s -o /dev/null -w '%{http_code}' https://seodada.com/
# Should output: 200
```

---

## 14. Run Tests

Run the full test suite on the Droplet:

```bash
cd /opt/seodada
sudo -u seodada bash -c 'source venv/bin/activate && set -a && source .env && set +a && python -m pytest tests/ -v --tb=short'
```

Expected: 221 tests passed.

---

## 15. Maintenance Commands

### Application

```bash
# View live logs
journalctl -u seodada -f

# Restart application
systemctl restart seodada

# Stop application
systemctl stop seodada

# Check status
systemctl status seodada
```

### Deploy Updates

```bash
cd /opt/seodada
sudo -u seodada git pull origin main
systemctl restart seodada
```

### Nginx

```bash
# Test config
nginx -t

# Restart
systemctl restart nginx

# View logs
tail -f /var/log/nginx/error.log
```

### SSL Certificate

```bash
# Check expiry
certbot certificates

# Manual renewal (auto-renewal is set up already)
certbot renew

# Test auto-renewal
certbot renew --dry-run
```

### Database

```bash
# Connect to database
export PGPASSWORD='<your-db-password>'
psql -h <db-host> -p 25060 -U doadmin -d defaultdb

# Create a backup
pg_dump -h <db-host> -p 25060 -U doadmin defaultdb > backup_$(date +%Y%m%d).sql
```

### Server

```bash
# Check disk space
df -h

# Check memory
free -h

# Check running processes
htop
```

---

## 16. Troubleshooting

### App returns 500 error

```bash
# Check application logs
journalctl -u seodada --no-pager -n 50

# Check Flask log file
cat /opt/seodada/flask_app.log
```

### App won't start

```bash
# Test manually
cd /opt/seodada
sudo -u seodada bash -c 'source venv/bin/activate && set -a && source .env && set +a && python -c "from app import create_app; app = create_app(); print(\"OK\")"'
```

### Database connection fails

```bash
# Test connection from Droplet
export PGPASSWORD='<your-db-password>'
psql -h <db-host> -p 25060 -U doadmin -d defaultdb -c "SELECT 1"
```

If connection refused: Add the Droplet IP to the database's **Trusted Sources** in DigitalOcean dashboard (Databases > your cluster > Settings > Trusted Sources).

### Nginx returns 502 Bad Gateway

The application is not running or not listening on port 8080:

```bash
systemctl status seodada
systemctl restart seodada
```

### SSL certificate renewal fails

```bash
# Check certbot logs
cat /var/log/letsencrypt/letsencrypt.log

# Manual renewal
certbot renew --force-renewal
```

### Missing Python package

```bash
cd /opt/seodada
sudo -u seodada /opt/seodada/venv/bin/pip install <package-name>
systemctl restart seodada
```

---

## Architecture Overview

```
Internet
    |
    v
[Nginx :80/:443] -- SSL termination, static files, reverse proxy
    |
    v
[Gunicorn :8080] -- 3 workers, 120s timeout
    |
    v
[Flask App] -- Blueprints: auth, admin, payment, seo_tools, public
    |
    v
[PostgreSQL] -- DigitalOcean Managed Database (SSL required)
```

### Key File Locations

| File/Directory                          | Purpose                        |
|-----------------------------------------|--------------------------------|
| `/opt/seodada/`                         | Application root               |
| `/opt/seodada/.env`                     | Environment variables          |
| `/opt/seodada/venv/`                    | Python virtual environment     |
| `/opt/seodada/gunicorn.conf.py`         | Gunicorn configuration         |
| `/opt/seodada/wsgi.py`                  | WSGI entry point               |
| `/etc/systemd/system/seodada.service`   | Systemd service file           |
| `/etc/nginx/sites-available/seodada`    | Nginx site configuration       |
| `/etc/letsencrypt/live/seodada.com/`    | SSL certificates               |

---

## Cost Summary

| Resource                          | Cost/Month |
|-----------------------------------|------------|
| Droplet (2GB RAM, 1 vCPU)        | $16        |
| Managed PostgreSQL (Basic)        | ~$15       |
| SSL (Let's Encrypt)              | Free       |
| **Total**                         | **~$31**   |
