# Ubuntu Production Manual Install Guide

Manual installation and troubleshooting guide for deploying `ISP Manager` on an Ubuntu server.

## Purpose

This document is a practical step-by-step guide for taking the current project from local development to a manually installed Ubuntu production-style deployment.

It covers:

- server requirements
- required software packages
- PostgreSQL setup
- Django app setup
- Gunicorn and Nginx setup
- HTTPS setup
- environment file layout
- manual smoke tests
- troubleshooting common deployment issues

## Important Current Project Note

The web application itself can be deployed on Ubuntu now.

However, there is one important operational limitation in the current codebase:

- the project documentation recommends a separate scheduler service
- the current repo does not yet include a first-class standalone scheduler management command
- under `Gunicorn`, scheduled jobs should not be assumed to be fully production-safe until a dedicated scheduler entrypoint is added

That means:

- web serving can be production-style now
- PostgreSQL can be production-style now
- billing, telemetry, and other scheduled automation should be treated carefully until scheduler separation is completed in code

For now, use this guide for the web + database deployment, and treat scheduler automation as a controlled follow-up task.

## Minimum Requirements

## Server Sizing

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

Create `/etc/ispmanager/ispmanager.env`:

```bash
sudo nano /etc/ispmanager/ispmanager.env
```

Recommended baseline:

```env
SECRET_KEY=replace-with-a-strong-random-secret
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,server-ip
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

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
- it is safer until a dedicated scheduler process is implemented cleanly

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
  --bind 127.0.0.1:8000 \
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
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/ispmanager /etc/nginx/sites-enabled/ispmanager
sudo nginx -t
sudo systemctl reload nginx
```

## Step 8: Enable HTTPS

Use Certbot:

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Then verify renewal:

```bash
sudo certbot renew --dry-run
```

## Step 9: Firewall Setup

If using UFW:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Do not open PostgreSQL publicly on the internet unless it is intentionally isolated behind private network controls.

## Step 10: Production Smoke Test

After services are running, test the following:

- homepage loads
- login page loads
- admin/operator login works
- subscriber list loads
- subscriber detail loads
- accounting dashboard loads
- billing snapshot pages load
- router pages load
- static CSS/JS files load correctly

CLI checks:

```bash
sudo systemctl status postgresql
sudo systemctl status ispmanager-web
sudo systemctl status nginx
curl -I http://127.0.0.1:8000
curl -I https://yourdomain.com
```

## Current Database Location in Production

If using PostgreSQL on Ubuntu, the project database is not stored in the repo folder.

Typical PostgreSQL storage location on Ubuntu:

```text
/var/lib/postgresql/<version>/main
```

Example:

```text
/var/lib/postgresql/16/main
```

The logical application database name remains:

```text
ispmanager
```

You can verify the real data directory with:

```bash
sudo -u postgres psql -d postgres -c "SHOW data_directory;"
```

## Manual Update Workflow

When deploying a new app version manually:

```bash
cd /opt/ispmanager
sudo -u ispmanager git pull
sudo -u ispmanager ./.venv/bin/pip install -r requirements.txt
set -a
source /etc/ispmanager/ispmanager.env
set +a
sudo -u ispmanager ./.venv/bin/python manage.py migrate
sudo -u ispmanager ./.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart ispmanager-web
sudo systemctl reload nginx
```

## Backups You Should Have

Minimum production backup set:

- PostgreSQL database backup
- `/etc/ispmanager/ispmanager.env`
- Nginx site config
- systemd unit files
- `/opt/ispmanager/media/` if media uploads are used

## Troubleshooting

## 1. `DisallowedHost`

Symptom:

- Django returns `DisallowedHost`

Fix:

- add the real domain or server IP to `ALLOWED_HOSTS`
- restart Gunicorn service after editing the env file

## 2. `OperationalError: connection refused`

Symptom:

- Django cannot connect to PostgreSQL

Checks:

```bash
sudo systemctl status postgresql
sudo -u postgres psql -d postgres -c "SELECT 1;"
ss -ltnp | grep 5432
```

Fix:

- confirm PostgreSQL is running
- confirm `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`
- confirm the database and role actually exist

## 3. `password authentication failed`

Symptom:

- PostgreSQL rejects login

Fix:

- reset the role password in PostgreSQL
- update `/etc/ispmanager/ispmanager.env`
- restart `ispmanager-web`

Example:

```bash
sudo -u postgres psql -d postgres -c "ALTER ROLE ispmanager WITH PASSWORD 'new-strong-password';"
```

## 4. `relation does not exist`

Symptom:

- app boots but fails when opening pages or services

Cause:

- migrations were not applied to PostgreSQL

Fix:

```bash
cd /opt/ispmanager
set -a
source /etc/ispmanager/ispmanager.env
set +a
sudo -u ispmanager ./.venv/bin/python manage.py migrate
```

## 5. Static files missing or broken CSS

Symptom:

- app loads without styling
- admin pages look unformatted

Fix:

```bash
sudo -u ispmanager ./.venv/bin/python manage.py collectstatic --noinput
sudo nginx -t
sudo systemctl reload nginx
```

Also verify:

- Nginx `alias` points to `/opt/ispmanager/staticfiles/`
- `staticfiles/` exists and is readable

## 6. `502 Bad Gateway`

Symptom:

- Nginx returns `502`

Checks:

```bash
sudo systemctl status ispmanager-web
journalctl -u ispmanager-web -n 100 --no-pager
```

Fix:

- confirm Gunicorn is running
- confirm Gunicorn listens on `127.0.0.1:8000`
- confirm Nginx proxy target matches Gunicorn bind address

## 7. Gunicorn service fails to start

Common causes:

- bad env file
- missing dependency
- migration error
- wrong working directory
- wrong Python path in `ExecStart`

Checks:

```bash
journalctl -u ispmanager-web -n 200 --no-pager
```

## 8. `ModuleNotFoundError: psycopg`

Symptom:

- app fails when Django starts with PostgreSQL settings

Fix:

```bash
cd /opt/ispmanager
sudo -u ispmanager ./.venv/bin/pip install -r requirements.txt
```

If compile/build errors occur, confirm:

```bash
sudo apt install -y libpq-dev python3-dev build-essential
```

## 9. CSRF verification failed

Common causes:

- HTTPS proxy headers not forwarded correctly
- missing correct host/origin settings
- cookies/domain mismatch

Check:

- `ALLOWED_HOSTS`
- HTTPS domain used in browser
- reverse proxy headers in Nginx

## 10. PostgreSQL works but scheduler jobs do not run

This is an important current project limitation.

Because the codebase does not yet expose a dedicated production scheduler command, do not assume scheduled jobs are fully production-ready just because the web app is running.

Recommended action:

- keep web deployment stable first
- add a dedicated scheduler entrypoint/service as a follow-up implementation
- until then, treat billing/telemetry automation as an explicitly managed operational task

## 11. Router telemetry pages load but data seems stale

Checks:

- confirm router connectivity from the server
- confirm PostgreSQL writes are succeeding
- confirm related jobs or manual sync actions are actually being run
- confirm MikroTik credentials and reachability from the Ubuntu host

## 12. Permission denied writing media or static files

Fix ownership:

```bash
sudo chown -R ispmanager:ispmanager /opt/ispmanager/media
sudo chown -R ispmanager:ispmanager /opt/ispmanager/staticfiles
```

## 13. Port 80 or 443 already in use

Check:

```bash
sudo ss -ltnp | grep ':80\|:443'
```

Fix:

- stop conflicting service
- fix duplicate Nginx/site setup
- disable unused web servers such as Apache if not needed

## 14. Server restart test

Before calling the deployment stable, test reboot persistence:

```bash
sudo reboot
```

After reboot, confirm:

```bash
sudo systemctl status postgresql
sudo systemctl status ispmanager-web
sudo systemctl status nginx
```

## Recommended Follow-Up Improvements

After this manual production-style install is stable, the next high-value follow-up tasks are:

1. add a dedicated scheduler entrypoint and systemd scheduler service
2. add structured logging and log rotation
3. automate PostgreSQL backups
4. harden `ALLOWED_HOSTS`, cookies, and HTTPS-related Django settings
5. add staging deployment before first public rollout
