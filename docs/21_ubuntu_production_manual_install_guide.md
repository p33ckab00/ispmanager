# Ubuntu Production Manual Install Guide

Manual installation and troubleshooting guide for deploying `ISP Manager` on an Ubuntu server.

## Purpose

This document is a practical step-by-step guide for taking the current project from local development to a manually installed Ubuntu production deployment.

It covers:

- server requirements
- required software packages
- PostgreSQL setup
- Django app setup
- Gunicorn and Nginx setup
- HTTPS setup
- environment file layout
- dedicated scheduler service setup
- manual smoke tests
- troubleshooting common deployment issues

## Current Production Model

The current recommended Ubuntu production layout is:

- `Nginx` as the public reverse proxy
- `Gunicorn` serving Django on `127.0.0.1:8193`
- `PostgreSQL` as the only application database
- `ispmanager-web.service` for web traffic
- `ispmanager-scheduler.service` for APScheduler jobs

Important rule:

- keep scheduler startup disabled inside the web service with `DISABLE_SCHEDULER=1`
- run scheduled jobs through the dedicated `manage.py run_scheduler` process only

## Minimum Requirements

### Minimum for small live rollout

- `2 vCPU`
- `4 GB RAM`
- `40 GB SSD`
- stable internet connection
- static public IP or fixed DNS target

### Recommended starting point

- `4 vCPU`
- `8 GB RAM`
- `80 GB SSD`
- daily backups
- separate backup storage or snapshot support

## OS and Runtime

- `Ubuntu Server 22.04 LTS` or newer
- `Python 3.10+`
- `PostgreSQL 15+`
- `Nginx`
- `Gunicorn`

## Network and DNS

Recommended:

- one domain or subdomain, for example `isp.example.com`
- firewall enabled
- only ports `22`, `80`, and `443` exposed publicly
- PostgreSQL `5432` should not be public unless you intentionally isolate DB on a private network

## Required Ubuntu Packages

Install these packages first:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  python3 python3-venv python3-dev \
  build-essential libpq-dev \
  git nginx \
  postgresql postgresql-contrib \
  certbot python3-certbot-nginx
```

## Recommended Linux User and Paths

Use a dedicated runtime user:

- Linux user: `ispmanager`
- app root: `/opt/ispmanager`
- virtualenv: `/opt/ispmanager/.venv`
- environment file: `/etc/ispmanager/ispmanager.env`
- Gunicorn working dir: `/opt/ispmanager`

Create the user and directories:

```bash
sudo adduser --system --group --home /opt/ispmanager ispmanager
sudo mkdir -p /opt/ispmanager
sudo mkdir -p /etc/ispmanager
sudo chown -R ispmanager:ispmanager /opt/ispmanager
sudo chmod 750 /etc/ispmanager
```

## Step 1: Deploy the Project Code

Clone or copy the repo into `/opt/ispmanager`:

```bash
sudo -u ispmanager git clone <your-repo-url> /opt/ispmanager
cd /opt/ispmanager
```

If you deploy from a zip or local copy instead of Git, make sure file ownership is correct:

```bash
sudo chown -R ispmanager:ispmanager /opt/ispmanager
```

## Step 2: Create the Python Virtual Environment

```bash
cd /opt/ispmanager
sudo -u ispmanager python3 -m venv .venv
sudo -u ispmanager ./.venv/bin/pip install --upgrade pip wheel
sudo -u ispmanager ./.venv/bin/pip install -r requirements.txt
sudo -u ispmanager ./.venv/bin/pip install gunicorn
```

## Step 3: Prepare PostgreSQL

Switch to the PostgreSQL superuser:

```bash
sudo -u postgres psql
```

Create the app role and database:

```sql
CREATE ROLE ispmanager WITH LOGIN PASSWORD 'replace-with-strong-password';
CREATE DATABASE ispmanager OWNER ispmanager;
\q
```

Optional privilege hardening:

```bash
sudo -u postgres psql -d ispmanager -c "ALTER SCHEMA public OWNER TO ispmanager;"
sudo -u postgres psql -d ispmanager -c "GRANT ALL ON SCHEMA public TO ispmanager;"
```

## Step 4: Create the Production Environment File

A safe starter template is included in the repo:

- `deploy/ispmanager_ubuntu.env.template`

Create `/etc/ispmanager/ispmanager.env`:

```bash
sudo cp /opt/ispmanager/deploy/ispmanager_ubuntu.env.template /etc/ispmanager/ispmanager.env
sudo nano /etc/ispmanager/ispmanager.env
```

Recommended baseline:

```env
SECRET_KEY=replace-with-a-strong-random-secret
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,server-ip
APP_BASE_URL=https://yourdomain.com
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax

POSTGRES_DB=ispmanager
POSTGRES_USER=ispmanager
POSTGRES_PASSWORD=replace-with-strong-password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60

DISABLE_SCHEDULER=1
```

Why `DISABLE_SCHEDULER=1` here:

- it prevents accidental scheduler startup behavior in the web service
- it keeps Gunicorn workers from owning job execution
- it reserves recurring jobs for the dedicated scheduler service

Secure the environment file:

```bash
sudo chown root:ispmanager /etc/ispmanager/ispmanager.env
sudo chmod 640 /etc/ispmanager/ispmanager.env
```

## Step 5: Run Django Migrations and Static Collection

Load the env file and run setup commands:

```bash
cd /opt/ispmanager
set -a
source /etc/ispmanager/ispmanager.env
set +a

sudo -u ispmanager ./.venv/bin/python manage.py migrate
sudo -u ispmanager ./.venv/bin/python manage.py collectstatic --noinput
sudo -u ispmanager ./.venv/bin/python manage.py check
```

Create the first admin user if needed:

```bash
sudo -u ispmanager ./.venv/bin/python manage.py createsuperuser
```

## Step 6: Create the Gunicorn systemd Service

Create `/etc/systemd/system/ispmanager-web.service`:

```ini
[Unit]
Description=ISP Manager Gunicorn Web Service
After=network.target postgresql.service

[Service]
User=ispmanager
Group=ispmanager
WorkingDirectory=/opt/ispmanager
EnvironmentFile=/etc/ispmanager/ispmanager.env
ExecStart=/opt/ispmanager/.venv/bin/gunicorn config.wsgi:application \
  --bind 127.0.0.1:8193 \
  --workers 3 \
  --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ispmanager-web
sudo systemctl start ispmanager-web
sudo systemctl status ispmanager-web
```

## Step 6B: Create the Scheduler systemd Service

Create `/etc/systemd/system/ispmanager-scheduler.service`:

```ini
[Unit]
Description=ISP Manager Scheduler Service
After=network.target postgresql.service

[Service]
User=ispmanager
Group=ispmanager
WorkingDirectory=/opt/ispmanager
EnvironmentFile=/etc/ispmanager/ispmanager.env
ExecStart=/opt/ispmanager/.venv/bin/python manage.py run_scheduler
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ispmanager-scheduler
sudo systemctl start ispmanager-scheduler
sudo systemctl status ispmanager-scheduler
```

## Step 7: Configure Nginx

Create `/etc/nginx/sites-available/ispmanager`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 20M;

    location /static/ {
        alias /opt/ispmanager/staticfiles/;
    }

    location /media/ {
        alias /opt/ispmanager/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8193;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/ispmanager /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Step 8: Enable HTTPS

Once DNS is pointing correctly:

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Then re-check your env file values:

- `APP_BASE_URL=https://yourdomain.com`
- `CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_SSL_REDIRECT=True`
- `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https`

## Step 9: Manual Smoke Test

Run these checks after deployment:

```bash
sudo systemctl status postgresql
sudo systemctl status ispmanager-web
sudo systemctl status ispmanager-scheduler
sudo systemctl status nginx
curl -I http://127.0.0.1:8193
curl -I https://yourdomain.com
```

Validate in browser:

- login page loads
- dashboard loads
- subscriber list/detail loads
- billing snapshots page loads
- accounting pages load
- routers page loads
- public billing short links resolve correctly

## Troubleshooting

### Gunicorn service does not start

Check:

```bash
sudo journalctl -u ispmanager-web -n 100 --no-pager
```

Common causes:

- bad env file path
- missing Python dependencies
- PostgreSQL credentials incorrect
- migrations not applied

### Scheduler service does not start

Check:

```bash
sudo journalctl -u ispmanager-scheduler -n 100 --no-pager
```

Common causes:

- missing `EnvironmentFile`
- PostgreSQL connection problem
- web env forgot `DISABLE_SCHEDULER=1` and scheduler is colliding with web startup assumptions
- project code not updated to latest repo state

### PostgreSQL connection fails

Check:

```bash
sudo systemctl status postgresql
sudo -u postgres psql
sudo -u postgres psql -d ispmanager -c "\dt"
```

Common causes:

- wrong DB name
- wrong user/password
- PostgreSQL not running
- local auth policy mismatch

### Static files missing

Re-run:

```bash
cd /opt/ispmanager
set -a
source /etc/ispmanager/ispmanager.env
set +a
sudo -u ispmanager ./.venv/bin/python manage.py collectstatic --noinput
```

### Nginx returns `502 Bad Gateway`

Check:

```bash
sudo systemctl status ispmanager-web
sudo journalctl -u ispmanager-web -n 100 --no-pager
sudo nginx -t
```

Most common cause:

- Gunicorn is not listening on `127.0.0.1:8193`

### HTTPS works but forms fail with CSRF

Check:

- `APP_BASE_URL`
- `CSRF_TRUSTED_ORIGINS`
- `SECURE_PROXY_SSL_HEADER`
- Nginx `X-Forwarded-Proto` header

### Billing SMS links point to wrong host or port

Check:

- `APP_BASE_URL` in `/etc/ispmanager/ispmanager.env`

The app now uses `APP_BASE_URL` for public billing links.

## Final Recommendation

For Ubuntu production, keep the deployment model clean:

- `Nginx` handles public HTTPS
- `Gunicorn` handles web traffic on `127.0.0.1:8193`
- `PostgreSQL` stores all application data
- `ispmanager-scheduler.service` runs recurring jobs
- `/etc/ispmanager/ispmanager.env` holds deployment-specific configuration

This is the safest manual deployment path for the current codebase.
