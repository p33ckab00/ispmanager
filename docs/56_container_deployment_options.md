# Container Deployment Options

Detailed deployment guide for running `ISP Manager` in containers.

This guide covers three deployment options:

1. Docker Compose all-in-one VPS
2. Hybrid container app with external host or managed services
3. Orchestrated deployment with Kubernetes or Docker Swarm

The current app is a Django modular monolith with:

- PostgreSQL as the only supported production database
- Gunicorn for HTTP application serving
- APScheduler for recurring billing, SMS, router, diagnostics, and usage jobs
- WhiteNoise support for static files
- local `media/` storage for uploaded or generated runtime files

## Non-Negotiable Production Rules

These rules apply to all container options.

### 1. Run One Web Service and One Scheduler Service

The web process must handle HTTP only.

The scheduler process must be a separate long-running process:

```bash
python manage.py run_scheduler
```

Do not let every Gunicorn worker own APScheduler jobs. Duplicate schedulers can duplicate billing, SMS, router polling, usage sampling, and overdue automation.

Production web containers must use:

```env
DISABLE_SCHEDULER=1
```

The dedicated scheduler container can use the same environment file. The explicit `run_scheduler` management command starts the scheduler intentionally.

### 2. PostgreSQL Must Be Persistent

Never run production PostgreSQL without a persistent volume, host directory, managed database, snapshot policy, and tested backup/restore workflow.

### 3. Media Must Be Persistent

The app uses:

```text
/app/media
```

or the equivalent project path inside the container. Mount it to a named volume, host directory, or object-storage-backed path if that is added later.

### 4. Static Files Must Be Collected on Release

Run this after image updates and before serving traffic:

```bash
python manage.py collectstatic --noinput
```

If a reverse proxy serves static files directly, the `staticfiles` directory must be shared between the release command and the proxy.

### 5. Deployments Must Back Up Before Migrations

Before every production migration:

```bash
pg_dump
```

plus media backup if the release changes uploaded/generated file handling.

### 6. Router Reachability Must Be Designed Intentionally

The app connects outward to MikroTik RouterOS and other network targets. Container networking must allow the app and scheduler containers to reach router management IPs.

Avoid Docker bridge subnets that overlap with ISP LAN, CGNAT, PPPoE, OLT, or router management networks.

## Shared App Image

Use one image for both `web` and `scheduler`. Only the command changes.

### Recommended File Layout

Example deployment directory:

```text
/opt/ispmanager-container/
  app/                         # git checkout of this repository
  env/
    ispmanager.prod.env         # not committed
  nginx/
    ispmanager.conf
  backups/
  compose.yaml
```

### Dockerfile Template

Create this at the repository root when enabling container deployment:

```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        fonts-dejavu-core \
        libffi-dev \
        libjpeg62-turbo-dev \
        libpq-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt \
    && pip install gunicorn

COPY . /app

# settings.py declares STATICFILES_DIRS=[BASE_DIR / 'static'].
# Keep an empty directory available even if the repo has no static/ folder yet.
RUN mkdir -p /app/static /app/staticfiles /app/media \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8193

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8193", "--workers", "3", "--timeout", "120"]
```

### .dockerignore Template

Create this at the repository root:

```dockerignore
.git
.rtk
.tools
.venv
.vscode
.cache
__pycache__
*.pyc
.env
media
staticfiles
backups
*.sql
*.sql.gz
```

## Shared Production Environment

Use an env file that is not committed to Git.

Template:

```env
DJANGO_SETTINGS_MODULE=config.settings
SECRET_KEY=replace-with-a-long-random-secret
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
SECURE_HSTS_PRELOAD=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax

POSTGRES_DB=ispmanager
POSTGRES_USER=ispmanager
POSTGRES_PASSWORD=replace-with-a-strong-password
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60

DISABLE_SCHEDULER=1

GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=120
```

For local HTTP-only staging, temporarily use:

```env
APP_BASE_URL=http://server-ip:8193
CORS_ALLOWED_ORIGINS=http://server-ip:8193
CSRF_TRUSTED_ORIGINS=http://server-ip:8193
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False
SECURE_PROXY_SSL_HEADER=
SECURE_HSTS_SECONDS=0
```

Do not use the HTTP-only values for production.

## Option 1: Docker Compose All-In-One VPS

This is the recommended first container deployment.

### Best For

- one Ubuntu VPS
- simple operations
- first production or staging rollout
- app, scheduler, PostgreSQL, reverse proxy, and backups managed together

### Topology

```text
Internet
  |
  v
proxy container, ports 80/443
  |
  v
web container, Gunicorn on 8193
  |
  +--> PostgreSQL container, private Compose network
  |
  +--> media/static volumes

scheduler container
  |
  +--> same PostgreSQL container
  +--> router management networks if reachable from the host
```

### Host Preparation

Install Docker and Compose plugin on Ubuntu:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker version
docker compose version
```

Optional non-root Docker access:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

### Firewall

Public server:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

If using Cloudflare Tunnel only, expose only SSH and the tunnel's required outbound access. Do not expose the app port publicly.

### Compose Network Planning

Choose a Docker subnet that does not overlap with router, PPPoE, OLT, LAN, or management networks.

Example:

```yaml
networks:
  ispmanager_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.50.0/24
```

Check host routes first:

```bash
ip route
docker network ls
```

### Compose File Template

`compose.yaml`:

```yaml
name: ispmanager

services:
  db:
    image: postgres:16
    restart: unless-stopped
    env_file:
      - ./env/ispmanager.prod.env
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 10s
      timeout: 5s
      retries: 10
    networks:
      - ispmanager_net

  web:
    build:
      context: ./app
    restart: unless-stopped
    env_file:
      - ./env/ispmanager.prod.env
    environment:
      POSTGRES_HOST: db
      DISABLE_SCHEDULER: "1"
    command:
      - sh
      - -lc
      - >
        gunicorn config.wsgi:application
        --bind 0.0.0.0:8193
        --workers "$${GUNICORN_WORKERS:-3}"
        --timeout "$${GUNICORN_TIMEOUT:-120}"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - staticfiles_data:/app/staticfiles
      - media_data:/app/media
    expose:
      - "8193"
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8193/ >/dev/null || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
    networks:
      - ispmanager_net

  scheduler:
    build:
      context: ./app
    restart: unless-stopped
    env_file:
      - ./env/ispmanager.prod.env
    environment:
      POSTGRES_HOST: db
    command: ["python", "manage.py", "run_scheduler"]
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - media_data:/app/media
    networks:
      - ispmanager_net

  proxy:
    image: nginx:1.27-alpine
    restart: unless-stopped
    depends_on:
      web:
        condition: service_started
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/ispmanager.conf:/etc/nginx/conf.d/default.conf:ro
      - staticfiles_data:/staticfiles:ro
      - media_data:/media:ro
      - ./certbot/www:/var/www/certbot:ro
      - ./certbot/conf:/etc/letsencrypt:ro
    networks:
      - ispmanager_net

volumes:
  postgres_data:
  staticfiles_data:
  media_data:

networks:
  ispmanager_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.50.0/24
```

### Nginx Template for Option 1

`nginx/ispmanager.conf`:

```nginx
upstream ispmanager_web {
    server web:8193;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 20M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    client_max_body_size 20M;

    location /static/ {
        alias /staticfiles/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
    }

    location /media/ {
        alias /media/;
        expires 1h;
        add_header Cache-Control "private, max-age=3600";
    }

    location / {
        proxy_pass http://ispmanager_web;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 120s;
    }
}
```

For first boot before TLS certificates exist, start with an HTTP-only Nginx config, issue certificates, then switch to the HTTPS config.

### First Deploy Commands

Clone or update the repository:

```bash
sudo mkdir -p /opt/ispmanager-container
sudo chown -R "$USER":"$USER" /opt/ispmanager-container
cd /opt/ispmanager-container

git clone https://github.com/p33ckab00/ispmanager.git app
mkdir -p env nginx backups certbot/www certbot/conf
chmod 700 env backups
```

Create `env/ispmanager.prod.env` using the shared production template.

Build and start PostgreSQL:

```bash
cd /opt/ispmanager-container
docker compose --env-file env/ispmanager.prod.env build
docker compose --env-file env/ispmanager.prod.env up -d db
docker compose --env-file env/ispmanager.prod.env ps
docker compose --env-file env/ispmanager.prod.env logs -f db
```

Run Django release tasks:

```bash
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py migrate
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py collectstatic --noinput
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py check --deploy
```

Create the initial superuser:

```bash
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py createsuperuser
```

Start the stack:

```bash
docker compose --env-file env/ispmanager.prod.env up -d web scheduler proxy
docker compose --env-file env/ispmanager.prod.env ps
```

### TLS With Certbot Container

HTTP-only bootstrap config must expose `/.well-known/acme-challenge/`.

Issue certificate:

```bash
docker run --rm \
  -v /opt/ispmanager-container/certbot/www:/var/www/certbot \
  -v /opt/ispmanager-container/certbot/conf:/etc/letsencrypt \
  certbot/certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --email admin@yourdomain.com \
  --agree-tos \
  --no-eff-email \
  -d yourdomain.com \
  -d www.yourdomain.com
```

Reload proxy after switching to HTTPS config:

```bash
docker compose --env-file env/ispmanager.prod.env restart proxy
```

Renew manually:

```bash
docker run --rm \
  -v /opt/ispmanager-container/certbot/www:/var/www/certbot \
  -v /opt/ispmanager-container/certbot/conf:/etc/letsencrypt \
  certbot/certbot renew --webroot --webroot-path /var/www/certbot

docker compose --env-file env/ispmanager.prod.env exec proxy nginx -s reload
```

Cron example:

```bash
sudo crontab -e
```

```cron
15 3 * * * docker run --rm -v /opt/ispmanager-container/certbot/www:/var/www/certbot -v /opt/ispmanager-container/certbot/conf:/etc/letsencrypt certbot/certbot renew --webroot --webroot-path /var/www/certbot && docker compose --project-directory /opt/ispmanager-container --env-file /opt/ispmanager-container/env/ispmanager.prod.env exec -T proxy nginx -s reload
```

### Cloudflare Tunnel Variant

If Cloudflare Tunnel is the public entrypoint:

- proxy can listen only on the internal Docker network or host loopback
- set `APP_BASE_URL=https://yourdomain.com`
- keep `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https`
- ensure the tunnel forwards `X-Forwarded-Proto: https`
- do not expose `8193` publicly

Optional service:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run --token "$${CLOUDFLARED_TOKEN}"
    environment:
      CLOUDFLARED_TOKEN: ${CLOUDFLARED_TOKEN}
    networks:
      - ispmanager_net
```

Cloudflare route target example:

```text
http://proxy:80
```

### Smoke Test Commands

```bash
docker compose --env-file env/ispmanager.prod.env ps
docker compose --env-file env/ispmanager.prod.env logs --tail=100 web
docker compose --env-file env/ispmanager.prod.env logs --tail=100 scheduler
docker compose --env-file env/ispmanager.prod.env logs --tail=100 proxy

curl -I https://yourdomain.com/
curl -I https://yourdomain.com/static/admin/css/base.css
```

Check Django:

```bash
docker compose --env-file env/ispmanager.prod.env exec web python manage.py check --deploy
docker compose --env-file env/ispmanager.prod.env exec web python manage.py showmigrations
```

Verify DB:

```bash
set -a
. ./env/ispmanager.prod.env
set +a

docker compose --env-file env/ispmanager.prod.env exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select now();"
```

### Backup Commands

Create a timestamped backup:

```bash
cd /opt/ispmanager-container
set -a
. ./env/ispmanager.prod.env
set +a

mkdir -p backups

docker compose --env-file env/ispmanager.prod.env exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > "backups/ispmanager-db-$(date +%Y%m%d-%H%M%S).sql.gz"

docker run --rm \
  -v ispmanager_media_data:/media:ro \
  -v /opt/ispmanager-container/backups:/backups \
  alpine tar -czf "/backups/ispmanager-media-$(date +%Y%m%d-%H%M%S).tar.gz" -C /media .

tar -czf "backups/ispmanager-config-$(date +%Y%m%d-%H%M%S).tar.gz" env nginx compose.yaml
```

Copy backups off the server:

```bash
rsync -avz /opt/ispmanager-container/backups/ backup-user@backup-host:/srv/backups/ispmanager/
```

### Restore Commands

For a clean restore into an empty database:

```bash
cd /opt/ispmanager-container
set -a
. ./env/ispmanager.prod.env
set +a

docker compose --env-file env/ispmanager.prod.env stop web scheduler

gunzip -c backups/ispmanager-db-YYYYMMDD-HHMMSS.sql.gz \
  | docker compose --env-file env/ispmanager.prod.env exec -T db \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

docker run --rm \
  -v ispmanager_media_data:/media \
  -v /opt/ispmanager-container/backups:/backups \
  alpine sh -lc 'rm -rf /media/* && tar -xzf /backups/ispmanager-media-YYYYMMDD-HHMMSS.tar.gz -C /media'

docker compose --env-file env/ispmanager.prod.env up -d web scheduler
```

For production incidents, restore into a separate database first whenever possible, inspect data, then decide whether to replace live data.

### Update and Redeploy Commands

```bash
cd /opt/ispmanager-container/app
git fetch origin
git checkout main
git pull --ff-only origin main

cd /opt/ispmanager-container

# Backup before migration.
set -a
. ./env/ispmanager.prod.env
set +a
docker compose --env-file env/ispmanager.prod.env exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > "backups/predeploy-$(date +%Y%m%d-%H%M%S).sql.gz"

# Stop scheduler so no recurring job runs during migration.
docker compose --env-file env/ispmanager.prod.env stop scheduler

docker compose --env-file env/ispmanager.prod.env build web scheduler
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py migrate
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py collectstatic --noinput
docker compose --env-file env/ispmanager.prod.env up -d web scheduler proxy

docker compose --env-file env/ispmanager.prod.env ps
docker compose --env-file env/ispmanager.prod.env logs --tail=100 web scheduler
```

### Rollback

If code deploy fails before migrations:

```bash
cd /opt/ispmanager-container/app
git log --oneline -10
git checkout <previous-good-commit>

cd /opt/ispmanager-container
docker compose --env-file env/ispmanager.prod.env build web scheduler
docker compose --env-file env/ispmanager.prod.env up -d web scheduler
```

If migrations were applied and must be reversed, restore from the predeploy DB backup after confirming the data loss impact.

## Option 2: Hybrid Containers With External Services

This keeps the app containerized but moves some stateful or edge services outside Compose.

### Common Variants

Variant A:

- app and scheduler in containers
- PostgreSQL on the host
- Nginx and TLS on the host

Variant B:

- app and scheduler in containers
- managed PostgreSQL or private DB VM
- Nginx, Caddy, Traefik, Cloudflare Tunnel, or load balancer outside the app stack

### Best For

- production teams that want host-managed DB backups
- servers that already have Nginx/Cloudflared
- easier database upgrades
- app redeploys without touching DB container lifecycle

### Topology

```text
Internet
  |
  v
host Nginx/Caddy/Cloudflared
  |
  v
web container on 127.0.0.1:8193
  |
  v
host PostgreSQL, private DB VM, or managed PostgreSQL

scheduler container
  |
  v
same external PostgreSQL
```

### External PostgreSQL on Ubuntu Host

Install:

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Create database and user:

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE ispmanager;
CREATE USER ispmanager WITH PASSWORD 'replace-with-strong-password';
ALTER ROLE ispmanager SET client_encoding TO 'utf8';
ALTER ROLE ispmanager SET default_transaction_isolation TO 'read committed';
ALTER ROLE ispmanager SET timezone TO 'Asia/Manila';
GRANT ALL PRIVILEGES ON DATABASE ispmanager TO ispmanager;
\q
```

For PostgreSQL 15 and newer, also ensure schema permissions:

```bash
sudo -u postgres psql -d ispmanager
```

```sql
GRANT ALL ON SCHEMA public TO ispmanager;
ALTER SCHEMA public OWNER TO ispmanager;
\q
```

If containers need to reach host PostgreSQL, bind PostgreSQL to a private host address or use Docker host gateway.

`postgresql.conf` example:

```conf
listen_addresses = '127.0.0.1,172.17.0.1'
```

`pg_hba.conf` example:

```conf
host    ispmanager    ispmanager    172.17.0.0/16    scram-sha-256
```

Restart:

```bash
sudo systemctl restart postgresql
sudo ss -ltnp | grep 5432
```

### Hybrid Env File

If using host PostgreSQL from Docker on Linux:

```env
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432
```

Compose must add:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

If using a private DB VM:

```env
POSTGRES_HOST=10.10.20.15
POSTGRES_PORT=5432
```

If using a managed DB that requires SSL, verify whether environment-level `PGSSLMODE=require` is enough for the runtime. If not, add explicit Django database SSL options before production use.

### Hybrid Compose Template

`compose.yaml` without PostgreSQL and without containerized proxy:

```yaml
name: ispmanager

services:
  web:
    build:
      context: ./app
    restart: unless-stopped
    env_file:
      - ./env/ispmanager.prod.env
    environment:
      DISABLE_SCHEDULER: "1"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    command:
      - sh
      - -lc
      - >
        gunicorn config.wsgi:application
        --bind 0.0.0.0:8193
        --workers "$${GUNICORN_WORKERS:-3}"
        --timeout "$${GUNICORN_TIMEOUT:-120}"
    ports:
      - "127.0.0.1:8193:8193"
    volumes:
      - /srv/ispmanager/staticfiles:/app/staticfiles
      - /srv/ispmanager/media:/app/media

  scheduler:
    build:
      context: ./app
    restart: unless-stopped
    env_file:
      - ./env/ispmanager.prod.env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    command: ["python", "manage.py", "run_scheduler"]
    volumes:
      - /srv/ispmanager/media:/app/media
```

Prepare host directories:

```bash
sudo mkdir -p /srv/ispmanager/staticfiles /srv/ispmanager/media
```

Build the image, then match host directory ownership to the container user:

```bash
docker compose --env-file env/ispmanager.prod.env build web
APP_UID="$(docker compose --env-file env/ispmanager.prod.env run --rm web id -u)"
APP_GID="$(docker compose --env-file env/ispmanager.prod.env run --rm web id -g)"
sudo chown -R "${APP_UID}:${APP_GID}" /srv/ispmanager
```

Recheck permissions if the Dockerfile user changes later.

### Host Nginx Template

`/etc/nginx/sites-available/ispmanager`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 20M;

    location /static/ {
        alias /srv/ispmanager/staticfiles/;
    }

    location /media/ {
        alias /srv/ispmanager/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8193;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Enable:

```bash
sudo ln -sf /etc/nginx/sites-available/ispmanager /etc/nginx/sites-enabled/ispmanager
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Issue TLS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
sudo systemctl status certbot.timer
```

After TLS, set env:

```env
APP_BASE_URL=https://yourdomain.com
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
```

Reload app:

```bash
docker compose --env-file env/ispmanager.prod.env up -d web scheduler
```

### Hybrid First Deploy Commands

```bash
cd /opt/ispmanager-container
docker compose --env-file env/ispmanager.prod.env build

docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py migrate
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py collectstatic --noinput
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py createsuperuser

docker compose --env-file env/ispmanager.prod.env up -d web scheduler
docker compose --env-file env/ispmanager.prod.env ps
```

### Hybrid Backup Commands

If DB is on host:

```bash
set -a
. /opt/ispmanager-container/env/ispmanager.prod.env
set +a

mkdir -p /opt/ispmanager-container/backups

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  -h 127.0.0.1 \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  | gzip > "/opt/ispmanager-container/backups/ispmanager-db-$(date +%Y%m%d-%H%M%S).sql.gz"

tar -czf "/opt/ispmanager-container/backups/ispmanager-media-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /srv/ispmanager/media .
```

If DB is managed, use the provider's snapshot system plus logical dumps from a trusted host.

### Hybrid Update Commands

```bash
cd /opt/ispmanager-container/app
git fetch origin
git checkout main
git pull --ff-only origin main

cd /opt/ispmanager-container
docker compose --env-file env/ispmanager.prod.env stop scheduler

# Take DB backup here.

docker compose --env-file env/ispmanager.prod.env build web scheduler
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py migrate
docker compose --env-file env/ispmanager.prod.env run --rm web python manage.py collectstatic --noinput
docker compose --env-file env/ispmanager.prod.env up -d web scheduler
sudo nginx -t && sudo systemctl reload nginx
```

## Option 3: Kubernetes or Docker Swarm

Use this only when the operational complexity is justified.

For most ISP Manager deployments, Kubernetes or Swarm should come after Compose is proven in staging or production.

### Best For

- multiple app nodes
- image registry based releases
- infrastructure team already operating Kubernetes or Swarm
- web horizontal scaling
- stronger rollout and rollback controls

### Hard Rule

Scale web if needed.

Do not scale scheduler above one replica unless the app later gains distributed locking or leader election.

```text
web replicas:       2 or more allowed after validation
scheduler replicas: exactly 1
```

### Recommended Production Shape

Use managed PostgreSQL or a dedicated DB VM outside the cluster when possible.

In-cluster PostgreSQL is acceptable for staging or small deployments only if the cluster has:

- durable volumes
- storage class with backups
- node failure recovery
- tested restore workflow

### Container Registry Flow

Example with GitHub Container Registry:

```bash
cd /opt/ispmanager
export IMAGE_TAG="$(git rev-parse --short HEAD)"
export IMAGE="ghcr.io/p33ckab00/ispmanager:${IMAGE_TAG}"

docker build -t "$IMAGE" .
docker push "$IMAGE"
```

Also tag stable releases:

```bash
docker tag "$IMAGE" ghcr.io/p33ckab00/ispmanager:prod
docker push ghcr.io/p33ckab00/ispmanager:prod
```

### Kubernetes Namespace

```bash
kubectl create namespace ispmanager
kubectl config set-context --current --namespace=ispmanager
```

### Kubernetes Secret

Do not commit real secrets. Create them with CLI or a sealed secret workflow.

```bash
kubectl create secret generic ispmanager-secret \
  --from-literal=SECRET_KEY='replace-with-a-long-random-secret' \
  --from-literal=POSTGRES_PASSWORD='replace-with-a-strong-password'
```

### Kubernetes ConfigMap

```bash
kubectl create configmap ispmanager-config \
  --from-literal=DJANGO_SETTINGS_MODULE='config.settings' \
  --from-literal=DEBUG='False' \
  --from-literal=ALLOWED_HOSTS='yourdomain.com,www.yourdomain.com' \
  --from-literal=APP_BASE_URL='https://yourdomain.com' \
  --from-literal=CORS_ALLOWED_ORIGINS='https://yourdomain.com,https://www.yourdomain.com' \
  --from-literal=CSRF_TRUSTED_ORIGINS='https://yourdomain.com,https://www.yourdomain.com' \
  --from-literal=SESSION_COOKIE_SECURE='True' \
  --from-literal=CSRF_COOKIE_SECURE='True' \
  --from-literal=SECURE_SSL_REDIRECT='True' \
  --from-literal=SECURE_PROXY_SSL_HEADER='HTTP_X_FORWARDED_PROTO,https' \
  --from-literal=SECURE_HSTS_SECONDS='31536000' \
  --from-literal=SECURE_HSTS_INCLUDE_SUBDOMAINS='True' \
  --from-literal=SECURE_HSTS_PRELOAD='False' \
  --from-literal=SESSION_COOKIE_SAMESITE='Lax' \
  --from-literal=CSRF_COOKIE_SAMESITE='Lax' \
  --from-literal=POSTGRES_DB='ispmanager' \
  --from-literal=POSTGRES_USER='ispmanager' \
  --from-literal=POSTGRES_HOST='private-db-host-or-service-name' \
  --from-literal=POSTGRES_PORT='5432' \
  --from-literal=POSTGRES_CONN_MAX_AGE='60' \
  --from-literal=DISABLE_SCHEDULER='1' \
  --from-literal=GUNICORN_WORKERS='3' \
  --from-literal=GUNICORN_TIMEOUT='120'
```

### Kubernetes PVCs

If static and media are served by the app through WhiteNoise and Django media routing, a media PVC is the most important one.

For reverse-proxy static serving, use a shared static PVC too.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ispmanager-media
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ispmanager-staticfiles
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 2Gi
```

If running more than one web replica and files must be mounted across nodes, use `ReadWriteMany` storage, bake collected static files into the image, or move media to object storage in a future app change. `ReadWriteOnce` PVCs can block multi-node scheduling.

### Kubernetes Web Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ispmanager-web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ispmanager-web
  template:
    metadata:
      labels:
        app: ispmanager-web
    spec:
      containers:
        - name: web
          image: ghcr.io/p33ckab00/ispmanager:prod
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8193
          envFrom:
            - configMapRef:
                name: ispmanager-config
            - secretRef:
                name: ispmanager-secret
          env:
            - name: DISABLE_SCHEDULER
              value: "1"
          command:
            - sh
            - -lc
            - >
              gunicorn config.wsgi:application
              --bind 0.0.0.0:8193
              --workers "${GUNICORN_WORKERS:-3}"
              --timeout "${GUNICORN_TIMEOUT:-120}"
          readinessProbe:
            httpGet:
              path: /
              port: 8193
            initialDelaySeconds: 20
            periodSeconds: 15
          livenessProbe:
            httpGet:
              path: /
              port: 8193
            initialDelaySeconds: 60
            periodSeconds: 30
          volumeMounts:
            - name: media
              mountPath: /app/media
            - name: staticfiles
              mountPath: /app/staticfiles
      volumes:
        - name: media
          persistentVolumeClaim:
            claimName: ispmanager-media
        - name: staticfiles
          persistentVolumeClaim:
            claimName: ispmanager-staticfiles
```

### Kubernetes Scheduler Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ispmanager-scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ispmanager-scheduler
  template:
    metadata:
      labels:
        app: ispmanager-scheduler
    spec:
      containers:
        - name: scheduler
          image: ghcr.io/p33ckab00/ispmanager:prod
          imagePullPolicy: IfNotPresent
          envFrom:
            - configMapRef:
                name: ispmanager-config
            - secretRef:
                name: ispmanager-secret
          command: ["python", "manage.py", "run_scheduler"]
          volumeMounts:
            - name: media
              mountPath: /app/media
      volumes:
        - name: media
          persistentVolumeClaim:
            claimName: ispmanager-media
```

Do not attach an HPA to `ispmanager-scheduler`.

### Kubernetes Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ispmanager-web
spec:
  selector:
    app: ispmanager-web
  ports:
    - name: http
      port: 80
      targetPort: 8193
```

### Kubernetes Ingress

Example for Nginx Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ispmanager
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "20m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "120"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "120"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - yourdomain.com
        - www.yourdomain.com
      secretName: ispmanager-tls
  rules:
    - host: yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ispmanager-web
                port:
                  number: 80
    - host: www.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ispmanager-web
                port:
                  number: 80
```

With cert-manager:

```bash
kubectl annotate ingress ispmanager cert-manager.io/cluster-issuer=letsencrypt-prod
```

### Kubernetes Migration Job

Run migrations as a one-off Job before rolling out new web/scheduler pods.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: ispmanager-release
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: release
          image: ghcr.io/p33ckab00/ispmanager:prod
          envFrom:
            - configMapRef:
                name: ispmanager-config
            - secretRef:
                name: ispmanager-secret
          command:
            - sh
            - -lc
            - python manage.py migrate && python manage.py collectstatic --noinput
          volumeMounts:
            - name: staticfiles
              mountPath: /app/staticfiles
            - name: media
              mountPath: /app/media
      volumes:
        - name: staticfiles
          persistentVolumeClaim:
            claimName: ispmanager-staticfiles
        - name: media
          persistentVolumeClaim:
            claimName: ispmanager-media
```

Run:

```bash
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/web.yaml
kubectl apply -f k8s/scheduler.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

kubectl delete job ispmanager-release --ignore-not-found
kubectl apply -f k8s/release-job.yaml
kubectl wait --for=condition=complete job/ispmanager-release --timeout=300s
kubectl logs job/ispmanager-release
```

Restart workloads after a successful release job:

```bash
kubectl rollout restart deployment/ispmanager-web
kubectl rollout restart deployment/ispmanager-scheduler
kubectl rollout status deployment/ispmanager-web
kubectl rollout status deployment/ispmanager-scheduler
```

### Kubernetes Operational Commands

```bash
kubectl get pods
kubectl get deploy
kubectl get ingress
kubectl logs deploy/ispmanager-web --tail=100
kubectl logs deploy/ispmanager-scheduler --tail=100
kubectl exec deploy/ispmanager-web -- python manage.py check --deploy
kubectl exec deploy/ispmanager-web -- python manage.py showmigrations
```

Scale web:

```bash
kubectl scale deployment/ispmanager-web --replicas=3
```

Keep scheduler at one:

```bash
kubectl scale deployment/ispmanager-scheduler --replicas=1
```

### Kubernetes Backup

If PostgreSQL is external, use external backup tooling plus logical dumps.

Example logical dump from a temporary pod if `pg_dump` is available in the image:

```bash
kubectl run pgdump-$(date +%s) \
  --rm -i --restart=Never \
  --image=postgres:16 \
  --env="PGPASSWORD=replace-with-password" \
  -- pg_dump -h private-db-host -U ispmanager -d ispmanager \
  > "ispmanager-db-$(date +%Y%m%d-%H%M%S).sql"
```

Media backup depends on the storage class. Use provider snapshots or a backup tool such as Velero/restic for PVC data.

### Docker Swarm Variant

If Kubernetes is too heavy but Compose single-host is not enough, Docker Swarm is a middle option.

Initialize:

```bash
docker swarm init
docker network create --driver overlay --attachable ispmanager_net
```

Create secrets:

```bash
printf 'replace-with-a-long-random-secret' | docker secret create ispmanager_secret_key -
printf 'replace-with-strong-password' | docker secret create ispmanager_postgres_password -
```

Use a stack file where:

- `web` can have multiple replicas after validation
- `scheduler` has exactly one replica
- PostgreSQL is preferably external or pinned to a node with durable storage

Deploy:

```bash
docker stack deploy -c stack.yaml ispmanager
docker stack services ispmanager
docker service logs ispmanager_web --tail 100
docker service logs ispmanager_scheduler --tail 100
```

Scale web:

```bash
docker service scale ispmanager_web=3
```

Keep scheduler single:

```bash
docker service scale ispmanager_scheduler=1
```

## Deployment Decision Matrix

| Need | Choose |
| --- | --- |
| Fastest safe production container rollout | Option 1 |
| Existing host Nginx/PostgreSQL already stable | Option 2 |
| Managed DB required | Option 2 or 3 |
| Multiple app nodes | Option 3 |
| Minimal operations burden | Option 1 |
| Strongest rollout/rollback controls | Option 3 |
| Router management network is complex | Option 2, with host networking or carefully routed bridge network |

## Recommended Path

Use this progression:

1. Start with Option 1 in staging.
2. Validate billing, SMS, router sync, diagnostics, and usage sampling.
3. Move to Option 1 production if one VPS is enough.
4. Move PostgreSQL or proxy outside containers later if operations require it.
5. Use Option 3 only after Compose operations are proven and there is a real scaling or orchestration need.

## Final Production Checklist

Before go-live:

- `DEBUG=False`
- strong `SECRET_KEY`
- strict `ALLOWED_HOSTS`
- `APP_BASE_URL` is the HTTPS public URL
- `POSTGRES_HOST` matches the selected topology
- PostgreSQL has persistent storage and backups
- media has persistent storage and backups
- `DISABLE_SCHEDULER=1` on web
- exactly one scheduler process is running
- migrations run successfully
- `collectstatic` runs successfully
- HTTPS works
- secure cookies are enabled
- router management IPs are reachable from web and scheduler containers
- billing generation is tested
- payment posting is tested
- scheduler diagnostics show expected job activity
- restore has been tested from backup
