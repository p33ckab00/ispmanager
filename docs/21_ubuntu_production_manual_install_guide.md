# Ubuntu Production Manual Install Guide

Manual installation and fresh-install deployment guide for running `ISP Manager` on an Ubuntu production server.

## Purpose

This guide is written for the real deployment scenario where:

- `LibreQoS` already exists at `/opt/libreqos`
- an older `ISP Manager` deployment may exist at `/opt/isp-manager`
- you want a fresh production install of the current codebase
- you want a safe backup path before replacing anything
- you want a repeatable way to redeploy future updates after go-live

It covers:

- preflight and backup workflow
- coexistence with LibreQoS
- manual Ubuntu production installation
- the new one-click installer script
- Cloudflared tunnel-safe deployment mode
- future redeploy/update workflow
- PostgreSQL, Gunicorn, Nginx, and scheduler setup
- smoke testing and rollback basics
- troubleshooting common deployment failures

## Current Production Model

The recommended Ubuntu production layout is:

- `Nginx` as the public reverse proxy
- `Gunicorn` serving Django on `127.0.0.1:8193`
- `PostgreSQL` as the only application database
- `ispmanager-web.service` for web traffic
- `ispmanager-scheduler.service` for APScheduler jobs

Important rule:

- keep scheduler startup disabled inside the web service with `DISABLE_SCHEDULER=1`
- run scheduled jobs only through `python manage.py run_scheduler`

If you deploy behind `cloudflared`:

- public HTTPS terminates at Cloudflare
- `cloudflared` forwards traffic to a localhost-only Nginx listener
- the installer and manual guide should preserve any existing `cloudflared` service instead of overwriting it blindly

## Safe Server Layout

For your current server situation, the recommended layout is:

- keep LibreQoS untouched at `/opt/libreqos`
- treat `/opt/isp-manager` as legacy and back it up before deploying
- use `/opt/ispmanager` as the fresh canonical app path for the current production install
- keep deployment-specific secrets in `/etc/ispmanager/ispmanager.env`

This means:

- `LibreQoS` stays separate
- the old hyphenated app path becomes backup material
- the new production path stays aligned with the rest of the project documentation

## Minimum Requirements

### Minimum for a small live rollout

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
- off-server backups or VM snapshots

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
- PostgreSQL `5432` should not be public unless intentionally isolated on a private network

## Preflight Checklist

Before deployment:

1. confirm LibreQoS is healthy and should remain untouched
2. confirm the old app path that should be backed up:
   - usually `/opt/isp-manager`
   - sometimes `/opt/ispmanager`
3. confirm your production domain or public server IP
4. decide whether you will enable Let's Encrypt during install
5. prepare:
   - PostgreSQL app password
   - Django `SECRET_KEY`
   - optional first superuser credentials
6. if you plan to use Cloudflare Tunnel:
   - check if `cloudflared` is already installed
   - check if `cloudflared.service` already exists and may already be serving other apps
   - prepare a `CLOUDFLARE_TUNNEL_TOKEN` only if you expect a fresh cloudflared service install

## Required Ubuntu Packages

Install these packages first:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev \
  build-essential libpq-dev \
  git rsync curl nginx \
  postgresql postgresql-contrib \
  certbot python3-certbot-nginx
```

## Recommended Runtime Paths

- app user: `ispmanager`
- app root: `/opt/ispmanager`
- virtualenv: `/opt/ispmanager/.venv`
- environment file: `/etc/ispmanager/ispmanager.env`
- backup root: `/opt/backups/ispmanager`
- Gunicorn bind: `127.0.0.1:8193`

## One-Click Fresh Installation Script

The repo now includes:

- `deploy/install_ubuntu_fresh.sh`

This script is designed for:

- fresh Ubuntu deployment
- safe coexistence with `/opt/libreqos`
- automatic backup of:
  - `/opt/isp-manager`
  - `/opt/ispmanager`
  - old app env/config/service files when present

### What the script does

The script will:

1. install Ubuntu packages
2. preserve `/opt/libreqos`
3. backup any existing `ISP Manager` app/config paths
4. copy the current repo into `/opt/ispmanager`
5. create the Python virtual environment
6. install requirements and Gunicorn
7. create or update the PostgreSQL app role and database
8. create `/etc/ispmanager/ispmanager.env`
9. run:
   - `migrate`
   - `collectstatic`
   - `check`
10. create:
   - `ispmanager-web.service`
   - `ispmanager-scheduler.service`
   - Nginx site config
11. optionally request a Let's Encrypt certificate
12. optionally create the first Django superuser if credentials are provided

The script intentionally does not copy:

- your local repo `.env`
- SQLite files such as `db.sqlite3`
- local `media/`
- local `staticfiles/`

That keeps the Ubuntu install fresh and production-oriented instead of inheriting local development state.

### Recommended usage from a fresh repo clone

Clone the repo somewhere temporary on the Ubuntu server first:

```bash
cd /tmp
git clone <your-repo-url> ispmanager-deploy
cd ispmanager-deploy
```

Important:

- review the checked-out branch before running the installer
- the script deploys the code currently present in that repo clone
- it does not pull a second copy from Git on its own

Then run the installer:

```bash
sudo APP_DOMAIN=isp.example.com \
  APP_WWW_DOMAIN=www.isp.example.com \
  LETSENCRYPT_EMAIL=ops@example.com \
  POSTGRES_PASSWORD='replace-with-strong-password' \
  DJANGO_SUPERUSER_USERNAME=admin \
  DJANGO_SUPERUSER_EMAIL=admin@example.com \
  DJANGO_SUPERUSER_PASSWORD='replace-with-strong-password' \
  ENABLE_CERTBOT=1 \
  bash deploy/install_ubuntu_fresh.sh
```

### HTTP-first test install by IP

If you want to test first without DNS/SSL:

```bash
sudo PRIMARY_IP=203.0.113.10 \
  POSTGRES_PASSWORD='replace-with-strong-password' \
  ENABLE_CERTBOT=0 \
  bash deploy/install_ubuntu_fresh.sh
```

### Supported installer environment variables

Most useful variables:

- `APP_DOMAIN`
- `APP_WWW_DOMAIN`
- `PRIMARY_IP`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `LETSENCRYPT_EMAIL`
- `ENABLE_CERTBOT`
- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_EMAIL`
- `DJANGO_SUPERUSER_PASSWORD`

Defaults:

- app path: `/opt/ispmanager`
- env file: `/etc/ispmanager/ispmanager.env`
- PostgreSQL DB: `ispmanager`
- PostgreSQL user: `ispmanager`
- Gunicorn port: `8193`

### One-click install with Cloudflared tunnel mode

Use this mode when:

- you want Cloudflare Tunnel as the public entry point
- you do not want to expose public `80/443` directly from the server
- you want Nginx to listen only on localhost for the tunnel origin

Recommended command when no existing cloudflared service is present:

```bash
sudo ENABLE_CLOUDFLARED=1 \
  APP_DOMAIN=app.example.com \
  CLOUDFLARE_TUNNEL_TOKEN='paste-your-tunnel-token-here' \
  POSTGRES_PASSWORD='replace-with-strong-password' \
  DJANGO_SUPERUSER_USERNAME=admin \
  DJANGO_SUPERUSER_EMAIL=admin@example.com \
  DJANGO_SUPERUSER_PASSWORD='replace-with-strong-password' \
  bash deploy/install_ubuntu_fresh.sh
```

What this mode does:

- configures Django as HTTPS-aware from the beginning
- binds Nginx to `127.0.0.1:8080`
- installs `cloudflared` only if it is not already installed
- installs a fresh `cloudflared.service` only when one does not already exist
- skips Certbot because public TLS is handled by Cloudflare

If an existing `cloudflared.service` is already on the server:

- the installer preserves it
- it does not overwrite the existing token or config
- you must confirm in the Cloudflare dashboard that your hostname points to:

```text
http://127.0.0.1:8080
```

### Safe detection rules for Cloudflared

Before using tunnel mode manually, check:

```bash
command -v cloudflared
sudo systemctl status cloudflared
```

Interpretation:

- if `cloudflared` exists and `cloudflared.service` already runs:
  - preserve it
  - do not blindly reinstall it
  - reuse the existing tunnel service if it already fits your environment
- if `cloudflared` exists but there is no service:
  - you may install a service if you have the correct tunnel token
- if `cloudflared` does not exist:
  - fresh install is fine
  - then install the service with the tunnel token

## Manual Fresh Installation Workflow

Use this path if you want to do everything manually instead of using the one-click installer.

## Step 1: Backup Old App Paths Safely

Create a backup root:

```bash
sudo mkdir -p /opt/backups/ispmanager
```

If the old app exists at `/opt/isp-manager`, back it up:

```bash
sudo mv /opt/isp-manager /opt/backups/ispmanager/isp-manager-$(date +%Y%m%d-%H%M%S)
```

If an older install already exists at `/opt/ispmanager`, back that up too:

```bash
sudo mv /opt/ispmanager /opt/backups/ispmanager/ispmanager-$(date +%Y%m%d-%H%M%S)
```

Do not move or delete:

```bash
/opt/libreqos
```

That directory is outside the ISP Manager deployment path and should be preserved.

## Step 2: Create Runtime User and Directories

```bash
sudo adduser --system --group --home /opt/ispmanager --shell /usr/sbin/nologin ispmanager
sudo mkdir -p /opt/ispmanager
sudo mkdir -p /etc/ispmanager
sudo chown -R ispmanager:ispmanager /opt/ispmanager
sudo chmod 750 /etc/ispmanager
```

## Step 3: Deploy the Project Code

Clone or copy the repo into `/opt/ispmanager`:

```bash
sudo -u ispmanager git clone <your-repo-url> /opt/ispmanager
cd /opt/ispmanager
```

If you deploy from a local copy instead of Git, fix ownership:

```bash
sudo chown -R ispmanager:ispmanager /opt/ispmanager
```

## Step 4: Create the Python Virtual Environment

```bash
cd /opt/ispmanager
sudo -u ispmanager python3 -m venv .venv
sudo -u ispmanager ./.venv/bin/pip install --upgrade pip wheel
sudo -u ispmanager ./.venv/bin/pip install -r requirements.txt
sudo -u ispmanager ./.venv/bin/pip install gunicorn
```

## Step 5: Prepare PostgreSQL

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

## Step 6: Create the Production Environment File

A starter template is included in the repo:

- `deploy/ispmanager_ubuntu.env.template`

Create `/etc/ispmanager/ispmanager.env`:

```bash
sudo cp /opt/ispmanager/deploy/ispmanager_ubuntu.env.template /etc/ispmanager/ispmanager.env
sudo nano /etc/ispmanager/ispmanager.env
```

Recommended baseline for real HTTPS production:

```env
SECRET_KEY=replace-with-a-strong-random-secret
DEBUG=False
ALLOWED_HOSTS=isp.example.com,www.isp.example.com,server-ip,localhost,127.0.0.1
APP_BASE_URL=https://isp.example.com
CORS_ALLOWED_ORIGINS=https://isp.example.com,https://www.isp.example.com
CSRF_TRUSTED_ORIGINS=https://isp.example.com,https://www.isp.example.com
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

- it prevents accidental scheduler startup inside Gunicorn workers
- it reserves recurring jobs for the dedicated scheduler service

Secure the env file:

```bash
sudo chown root:ispmanager /etc/ispmanager/ispmanager.env
sudo chmod 640 /etc/ispmanager/ispmanager.env
```

## Step 7: Run Django Migrations and Static Collection

```bash
cd /opt/ispmanager
set -a
source /etc/ispmanager/ispmanager.env
set +a

sudo -u ispmanager ./.venv/bin/python manage.py migrate
sudo -u ispmanager mkdir -p /opt/ispmanager/media
sudo -u ispmanager ./.venv/bin/python manage.py collectstatic --noinput
sudo -u ispmanager ./.venv/bin/python manage.py check
```

Create the first admin user if needed:

```bash
sudo -u ispmanager ./.venv/bin/python manage.py createsuperuser
```

## Step 8: Create the Gunicorn systemd Service

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
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/ispmanager/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8193 --workers 3 --timeout 120
Restart=always
RestartSec=5
UMask=0027

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

## Step 8B: Create the Scheduler systemd Service

Create `/etc/systemd/system/ispmanager-scheduler.service`:

```ini
[Unit]
Description=ISP Manager Scheduler Service
Wants=network-online.target
After=network-online.target postgresql.service

[Service]
User=ispmanager
Group=ispmanager
WorkingDirectory=/opt/ispmanager
EnvironmentFile=/etc/ispmanager/ispmanager.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/ispmanager/.venv/bin/python manage.py run_scheduler
Restart=always
RestartSec=5
UMask=0027

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

## Step 9: Configure Nginx

Create `/etc/nginx/sites-available/ispmanager`:

```nginx
server {
    listen 80;
    server_name isp.example.com www.isp.example.com;

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

Enable and reload:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/ispmanager /etc/nginx/sites-enabled/ispmanager
sudo nginx -t
sudo systemctl reload nginx
```

### Nginx if you are using Cloudflared

If the server uses Cloudflare Tunnel as the public entry point, prefer a localhost-only Nginx listener:

```nginx
server {
    listen 127.0.0.1:8080;
    server_name app.example.com;

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
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

This keeps the app private to the tunnel while still letting Django understand requests as HTTPS.

### Cloudflared published application route

Cloudflare’s published application route should point the public hostname to the local Nginx origin, for example:

- hostname: `app.example.com`
- service URL: `http://127.0.0.1:8080`

If you are using a remotely-managed tunnel, install the service with:

```bash
sudo cloudflared service install <TUNNEL_TOKEN>
sudo systemctl enable --now cloudflared
```

If `cloudflared.service` already exists for another workload:

- do not overwrite it blindly
- add or update the application route in the Cloudflare dashboard instead
- verify the ISP Manager hostname targets the local origin above

## Step 10: Enable HTTPS

Once DNS is pointing correctly:

```bash
sudo certbot --nginx -d isp.example.com -d www.isp.example.com
```

If you are using Cloudflared tunnel mode, you normally skip this step because Cloudflare already terminates public HTTPS.

Then re-check the env file values:

- `APP_BASE_URL=https://isp.example.com`
- `CSRF_TRUSTED_ORIGINS=https://isp.example.com,https://www.isp.example.com`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_SSL_REDIRECT=True`
- `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https`

Restart services after env changes:

```bash
sudo systemctl restart ispmanager-web
sudo systemctl restart ispmanager-scheduler
```

## Step 11: Manual Smoke Test

```bash
sudo systemctl status postgresql
sudo systemctl status ispmanager-web
sudo systemctl status ispmanager-scheduler
sudo systemctl status nginx
curl -I http://127.0.0.1:8193
curl -I http://isp.example.com
```

If HTTPS is active:

```bash
curl -I https://isp.example.com
```

If you are using Cloudflared, also test the local tunnel origin:

```bash
curl -I http://127.0.0.1:8080
sudo systemctl status cloudflared
```

Validate in browser:

- public homepage loads
- admin login loads
- dashboard loads
- subscriber list/detail loads
- billing snapshots page loads
- accounting pages load
- routers page loads
- public billing links resolve correctly

## Rollback Basics

If the fresh deployment must be rolled back:

1. stop the new services
2. restore the previous app directory from `/opt/backups/ispmanager`
3. restore:
   - old env file
   - old systemd units
   - old Nginx site file
4. reload systemd
5. reload Nginx
6. start the previous services again

Typical rollback commands:

```bash
sudo systemctl stop ispmanager-web ispmanager-scheduler
sudo systemctl daemon-reload
sudo systemctl reload nginx
```

Then restore the backup paths you want to reactivate.

## Troubleshooting

### Script or manual deploy should not touch LibreQoS

LibreQoS should remain at:

```bash
/opt/libreqos
```

If anything in your plan would overwrite or move that path, stop and correct the install target first.

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

- broken env file
- PostgreSQL connection problem
- app code not fully copied
- scheduler command missing from deployed version

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

If you are using Cloudflared, also check:

```bash
sudo journalctl -u cloudflared -n 100 --no-pager
curl -I http://127.0.0.1:8080
```

Cloudflare documents that a `502` in tunnel mode often means the tunnel is up but `cloudflared` cannot reach the configured local origin service or protocol.

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

For this Ubuntu production deployment:

- preserve LibreQoS at `/opt/libreqos`
- backup the old `/opt/isp-manager` deployment instead of deleting it blindly
- deploy fresh into `/opt/ispmanager`
- keep secrets in `/etc/ispmanager/ispmanager.env`
- run scheduler as its own service
- if Cloudflared already exists, preserve it first and reuse deliberately
- use HTTPS before treating the server as truly live

For your first real server attempt, the safest flow is:

1. clone the repo to a temporary location
2. run `deploy/install_ubuntu_fresh.sh`
3. verify services and homepage
4. verify billing, accounting, routers, and scheduler behavior
5. only then decide whether to retire the old backup completely

## Future Updates After Go-Live

Once the server is already live, do not keep using the fresh installer for routine code updates.

Use:

- `deploy/redeploy_ubuntu_update.sh`

That script is intended for:

- new code deployment
- dependency refresh
- migration rollout
- static file rebuild

See also:

- [Cloudflared Checking and Route Checklist](35_cloudflared_dashboard_route_checklist.md)
- [Ubuntu Redeploy and Upgrade Script](36_ubuntu_redeploy_upgrade_script.md)
