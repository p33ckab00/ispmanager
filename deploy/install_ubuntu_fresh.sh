#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

APP_USER="${APP_USER:-ispmanager}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
APP_DIR="${APP_DIR:-/opt/ispmanager}"
ENV_DIR="${ENV_DIR:-/etc/ispmanager}"
ENV_FILE="${ENV_FILE:-${ENV_DIR}/ispmanager.env}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/backups/ispmanager}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-ispmanager}"
GUNICORN_PORT="${GUNICORN_PORT:-8193}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-3}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

POSTGRES_DB="${POSTGRES_DB:-ispmanager}"
POSTGRES_USER="${POSTGRES_USER:-ispmanager}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
SECRET_KEY="${SECRET_KEY:-}"

APP_DOMAIN="${APP_DOMAIN:-}"
APP_WWW_DOMAIN="${APP_WWW_DOMAIN:-}"
PRIMARY_IP="${PRIMARY_IP:-}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
ENABLE_CERTBOT="${ENABLE_CERTBOT:-0}"
ENABLE_CLOUDFLARED="${ENABLE_CLOUDFLARED:-0}"
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
CLOUDFLARED_ORIGIN_PORT="${CLOUDFLARED_ORIGIN_PORT:-8080}"

DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-}"
DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-}"
DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD:-}"

readonly LEGACY_DIR_HYPHEN="/opt/isp-manager"
readonly LIBREQOS_DIR="/opt/libreqos"
readonly WEB_SERVICE="ispmanager-web.service"
readonly SCHEDULER_SERVICE="ispmanager-scheduler.service"
readonly CLOUDFLARED_SERVICE="cloudflared.service"
readonly NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
readonly NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
readonly NGINX_DEFAULT_SITE_ENABLED="/etc/nginx/sites-enabled/default"

CLOUDFLARED_BIN=""
CLOUDFLARED_SERVICE_EXISTS=0
CLOUDFLARED_SERVICE_ACTIVE=0
CLOUDFLARED_REUSED=0
CLOUDFLARED_INSTALLED_BY_SCRIPT=0

log() {
  printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

warn() {
  printf '\n[WARN] %s\n' "$*" >&2
}

die() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

bool_is_true() {
  case "${1:-0}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Run this installer as root: sudo bash deploy/install_ubuntu_fresh.sh"
}

ensure_repo_root() {
  [[ -f "${REPO_ROOT}/manage.py" ]] || die "Could not find manage.py. Run the installer from inside the ISP Manager repo."
}

random_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

join_by_comma() {
  local IFS=,
  echo "$*"
}

run_as_app() {
  local cmd="$1"
  runuser -u "${APP_USER}" -- bash -lc "${cmd}"
}

ensure_primary_ip() {
  if [[ -z "${PRIMARY_IP}" ]]; then
    PRIMARY_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
}

detect_cloudflared_state() {
  CLOUDFLARED_BIN="$(command -v cloudflared || true)"
  CLOUDFLARED_SERVICE_EXISTS=0
  CLOUDFLARED_SERVICE_ACTIVE=0

  if systemctl cat "${CLOUDFLARED_SERVICE}" >/dev/null 2>&1; then
    CLOUDFLARED_SERVICE_EXISTS=1
  fi

  if systemctl is-active --quiet "${CLOUDFLARED_SERVICE}" 2>/dev/null; then
    CLOUDFLARED_SERVICE_ACTIVE=1
  fi
}

ensure_secrets() {
  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    POSTGRES_PASSWORD="$(random_secret)"
    log "Generated PostgreSQL password and wrote it to ${ENV_FILE}."
  fi

  if [[ -z "${SECRET_KEY}" ]]; then
    SECRET_KEY="$(random_secret)"
    log "Generated Django SECRET_KEY and wrote it to ${ENV_FILE}."
  fi
}

preflight_checks() {
  require_root
  ensure_repo_root
  ensure_primary_ip
  detect_cloudflared_state

  if bool_is_true "${ENABLE_CERTBOT}"; then
    [[ -n "${APP_DOMAIN}" ]] || die "ENABLE_CERTBOT=1 requires APP_DOMAIN."
    [[ -n "${LETSENCRYPT_EMAIL}" ]] || die "ENABLE_CERTBOT=1 requires LETSENCRYPT_EMAIL."
  fi

  if bool_is_true "${ENABLE_CLOUDFLARED}"; then
    [[ -n "${APP_DOMAIN}" ]] || die "ENABLE_CLOUDFLARED=1 requires APP_DOMAIN."
    if bool_is_true "${ENABLE_CERTBOT}"; then
      die "ENABLE_CLOUDFLARED=1 and ENABLE_CERTBOT=1 should not be used together. Tunnel mode already gives you public HTTPS at Cloudflare."
    fi

    if [[ -n "${CLOUDFLARED_BIN}" ]]; then
      log "Detected cloudflared binary at ${CLOUDFLARED_BIN}."
    else
      warn "cloudflared binary not detected yet."
    fi

    if [[ "${CLOUDFLARED_SERVICE_EXISTS}" -eq 1 ]]; then
      warn "Existing ${CLOUDFLARED_SERVICE} detected. The installer will preserve it and will not overwrite its token/config."
      if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN}" ]]; then
        warn "Provided CLOUDFLARE_TUNNEL_TOKEN will be ignored because an existing cloudflared service is already present."
      fi
    elif [[ -z "${CLOUDFLARE_TUNNEL_TOKEN}" ]]; then
      die "ENABLE_CLOUDFLARED=1 with no existing cloudflared.service requires CLOUDFLARE_TUNNEL_TOKEN for a fresh tunnel service install."
    fi
  fi

  if [[ -d "${LIBREQOS_DIR}" ]]; then
    log "Detected LibreQoS at ${LIBREQOS_DIR}. This installer will not modify it."
  else
    warn "LibreQoS path ${LIBREQOS_DIR} was not found. Continuing anyway."
  fi
}

install_packages() {
  log "Installing Ubuntu packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    git rsync curl nginx \
    postgresql postgresql-contrib \
    certbot python3-certbot-nginx
}

install_cloudflared_if_needed() {
  if [[ -n "${CLOUDFLARED_BIN}" ]]; then
    log "Reusing installed cloudflared binary at ${CLOUDFLARED_BIN}."
    return 0
  fi

  log "Installing cloudflared from Cloudflare's package repository..."
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
  apt-get update
  apt-get install -y cloudflared
  CLOUDFLARED_BIN="$(command -v cloudflared || true)"
  [[ -n "${CLOUDFLARED_BIN}" ]] || die "cloudflared installation completed but the binary could not be found in PATH."
}

create_runtime_user() {
  log "Ensuring runtime user and directories exist..."

  if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${APP_GROUP}"
  fi

  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --gid "${APP_GROUP}" --create-home --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
  else
    usermod -g "${APP_GROUP}" "${APP_USER}"
  fi

  install -d -m 0750 "${ENV_DIR}"
  install -d -m 0755 "${BACKUP_ROOT}"
}

backup_path_copy() {
  local path="$1"
  local backup_dir="${BACKUP_ROOT}/config-${TIMESTAMP}"
  if [[ -e "${path}" || -L "${path}" ]]; then
    install -d -m 0755 "${backup_dir}"
    cp -a "${path}" "${backup_dir}/"
    log "Backed up ${path} to ${backup_dir}"
  fi
}

backup_directory_move() {
  local path="$1"
  if [[ -d "${path}" && ! "$(readlink -f "${path}")" =~ ^/tmp/ ]]; then
    local destination="${BACKUP_ROOT}/$(basename "${path}")-${TIMESTAMP}"
    mv "${path}" "${destination}"
    log "Moved existing directory ${path} to ${destination}"
  fi
}

stop_old_services() {
  for service in "${WEB_SERVICE}" "${SCHEDULER_SERVICE}"; do
    if systemctl cat "${service}" >/dev/null 2>&1; then
      systemctl stop "${service}" || true
    fi
  done
}

stage_source_tree() {
  STAGING_DIR="$(mktemp -d /tmp/ispmanager-src.XXXXXX)"
  export STAGING_DIR
  trap 'rm -rf "${STAGING_DIR:-}" "${SUPERUSER_SCRIPT:-}"' EXIT

  log "Staging repository contents from ${REPO_ROOT}..."
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.sqlite3' \
    --exclude 'media/' \
    --exclude 'staticfiles/' \
    "${REPO_ROOT}/" "${STAGING_DIR}/"
}

deploy_source_tree() {
  log "Backing up any legacy app directories..."
  stop_old_services
  backup_path_copy "${ENV_DIR}"
  backup_path_copy "/etc/systemd/system/${WEB_SERVICE}"
  backup_path_copy "/etc/systemd/system/${SCHEDULER_SERVICE}"
  backup_path_copy "${NGINX_SITE_AVAILABLE}"
  backup_path_copy "${NGINX_SITE_ENABLED}"

  if [[ "${LEGACY_DIR_HYPHEN}" != "${APP_DIR}" ]]; then
    backup_directory_move "${LEGACY_DIR_HYPHEN}"
  fi
  backup_directory_move "${APP_DIR}"

  log "Deploying fresh application tree into ${APP_DIR}..."
  install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0755 "${APP_DIR}"
  rsync -a "${STAGING_DIR}/" "${APP_DIR}/"
  install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0755 "${APP_DIR}/media"
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
}

setup_python_env() {
  log "Creating Python virtual environment and installing dependencies..."
  run_as_app "cd '${APP_DIR}' && python3 -m venv .venv"
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install --upgrade pip wheel"
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install -r requirements.txt"
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install gunicorn"
}

setup_postgres() {
  log "Creating or updating PostgreSQL role and database..."
  local postgres_user_sql
  local postgres_password_sql
  local postgres_db_sql

  postgres_user_sql="$(sql_escape "${POSTGRES_USER}")"
  postgres_password_sql="$(sql_escape "${POSTGRES_PASSWORD}")"
  postgres_db_sql="$(sql_escape "${POSTGRES_DB}")"

  systemctl enable --now postgresql

  sudo -u postgres psql postgres <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${postgres_user_sql}') THEN
        CREATE ROLE "${POSTGRES_USER}" WITH LOGIN PASSWORD '${postgres_password_sql}';
    ELSE
        ALTER ROLE "${POSTGRES_USER}" WITH LOGIN PASSWORD '${postgres_password_sql}';
    END IF;
END
\$\$;
SQL

  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${postgres_db_sql}'" | grep -q 1; then
    sudo -u postgres createdb -O "${POSTGRES_USER}" "${POSTGRES_DB}"
  fi

  sudo -u postgres psql -d "${POSTGRES_DB}" -c "ALTER SCHEMA public OWNER TO \"${POSTGRES_USER}\";" >/dev/null
  sudo -u postgres psql -d "${POSTGRES_DB}" -c "GRANT ALL ON SCHEMA public TO \"${POSTGRES_USER}\";" >/dev/null
}

write_env_file() {
  local scheme="$1"
  local secure="$2"
  local secure_bool="False"
  local ssl_redirect="False"
  local hsts_seconds="0"
  local secure_proxy=""
  local base_host
  local base_url
  local allowed_hosts=()
  local cors_origins=()
  local csrf_origins=()

  if [[ "${secure}" == "1" ]]; then
    secure_bool="True"
    ssl_redirect="True"
    hsts_seconds="31536000"
    secure_proxy="HTTP_X_FORWARDED_PROTO,https"
  fi

  base_host="${APP_DOMAIN:-${PRIMARY_IP:-127.0.0.1}}"
  base_url="${scheme}://${base_host}"

  allowed_hosts+=(localhost 127.0.0.1)
  [[ -n "${PRIMARY_IP}" ]] && allowed_hosts+=("${PRIMARY_IP}")
  [[ -n "${APP_DOMAIN}" ]] && allowed_hosts+=("${APP_DOMAIN}") && cors_origins+=("${scheme}://${APP_DOMAIN}") && csrf_origins+=("${scheme}://${APP_DOMAIN}")
  [[ -n "${APP_WWW_DOMAIN}" ]] && allowed_hosts+=("${APP_WWW_DOMAIN}") && cors_origins+=("${scheme}://${APP_WWW_DOMAIN}") && csrf_origins+=("${scheme}://${APP_WWW_DOMAIN}")

  if [[ -z "${APP_DOMAIN}" && -n "${PRIMARY_IP}" ]]; then
    cors_origins+=("${scheme}://${PRIMARY_IP}")
    csrf_origins+=("${scheme}://${PRIMARY_IP}")
  fi

  cat > "${ENV_FILE}" <<EOF
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=$(join_by_comma "${allowed_hosts[@]}")
APP_BASE_URL=${base_url}
CORS_ALLOWED_ORIGINS=$(join_by_comma "${cors_origins[@]}")
CSRF_TRUSTED_ORIGINS=$(join_by_comma "${csrf_origins[@]}")
SESSION_COOKIE_SECURE=${secure_bool}
CSRF_COOKIE_SECURE=${secure_bool}
SECURE_SSL_REDIRECT=${ssl_redirect}
SECURE_PROXY_SSL_HEADER=${secure_proxy}
SECURE_HSTS_SECONDS=${hsts_seconds}
SECURE_HSTS_INCLUDE_SUBDOMAINS=${secure_bool}
SECURE_HSTS_PRELOAD=${secure_bool}
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax

POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60

DISABLE_SCHEDULER=1
EOF

  chown root:"${APP_GROUP}" "${ENV_FILE}"
  chmod 0640 "${ENV_FILE}"
}

run_django_setup() {
  log "Running Django migrations, collectstatic, and check..."
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py migrate"
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py collectstatic --noinput"
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py check"
}

create_superuser_if_requested() {
  if [[ -z "${DJANGO_SUPERUSER_USERNAME}" || -z "${DJANGO_SUPERUSER_PASSWORD}" ]]; then
    return 0
  fi

  log "Creating or updating Django superuser ${DJANGO_SUPERUSER_USERNAME}..."
  SUPERUSER_SCRIPT="$(mktemp /tmp/ispmanager-superuser.XXXXXX.py)"
  cat > "${SUPERUSER_SCRIPT}" <<'PY'
from django.contrib.auth import get_user_model
import os

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

user, created = User.objects.get_or_create(
    username=username,
    defaults={
        "email": email,
        "is_staff": True,
        "is_superuser": True,
    },
)

if email and user.email != email:
    user.email = email

user.is_staff = True
user.is_superuser = True
user.set_password(password)
user.save()

print(f"superuser_ready:{username}")
PY

  runuser -u "${APP_USER}" -- env \
    DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME}" \
    DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD}" \
    DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL}" \
    bash -lc "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py shell < '${SUPERUSER_SCRIPT}'"
}

write_web_service() {
  cat > "/etc/systemd/system/${WEB_SERVICE}" <<EOF
[Unit]
Description=ISP Manager Gunicorn Web Service
After=network.target postgresql.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:${GUNICORN_PORT} --workers ${GUNICORN_WORKERS} --timeout ${GUNICORN_TIMEOUT}
Restart=always
RestartSec=5
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
}

write_scheduler_service() {
  cat > "/etc/systemd/system/${SCHEDULER_SERVICE}" <<EOF
[Unit]
Description=ISP Manager Scheduler Service
Wants=network-online.target
After=network-online.target postgresql.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/python manage.py run_scheduler
Restart=always
RestartSec=5
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
}

write_nginx_site() {
  local server_names="_"
  local listen_line="listen 80;"
  local forwarded_proto="\$scheme"
  if [[ -n "${APP_DOMAIN}" && -n "${APP_WWW_DOMAIN}" ]]; then
    server_names="${APP_DOMAIN} ${APP_WWW_DOMAIN}"
  elif [[ -n "${APP_DOMAIN}" ]]; then
    server_names="${APP_DOMAIN}"
  elif [[ -n "${PRIMARY_IP}" ]]; then
    server_names="${PRIMARY_IP} _"
  fi

  if bool_is_true "${ENABLE_CLOUDFLARED}"; then
    listen_line="listen 127.0.0.1:${CLOUDFLARED_ORIGIN_PORT};"
    forwarded_proto="https"
  fi

  cat > "${NGINX_SITE_AVAILABLE}" <<EOF
server {
    ${listen_line}
    server_name ${server_names};

    client_max_body_size 20M;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
    }

    location /media/ {
        alias ${APP_DIR}/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:${GUNICORN_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${forwarded_proto};
    }
}
EOF

  ln -sf "${NGINX_SITE_AVAILABLE}" "${NGINX_SITE_ENABLED}"
  if [[ -L "${NGINX_DEFAULT_SITE_ENABLED}" ]]; then
    rm -f "${NGINX_DEFAULT_SITE_ENABLED}"
  fi
}

setup_cloudflared() {
  if ! bool_is_true "${ENABLE_CLOUDFLARED}"; then
    return 0
  fi

  detect_cloudflared_state

  if [[ "${CLOUDFLARED_SERVICE_EXISTS}" -eq 1 ]]; then
    CLOUDFLARED_REUSED=1
    log "Preserving existing ${CLOUDFLARED_SERVICE}. No automatic token/config changes will be made."
    return 0
  fi

  install_cloudflared_if_needed

  log "Installing fresh cloudflared service using the provided tunnel token..."
  cloudflared service install "${CLOUDFLARE_TUNNEL_TOKEN}"
  systemctl enable --now "${CLOUDFLARED_SERVICE}"
  CLOUDFLARED_INSTALLED_BY_SCRIPT=1
}

start_services() {
  log "Writing systemd and Nginx service files..."
  write_web_service
  write_scheduler_service
  write_nginx_site

  systemctl daemon-reload
  nginx -t
  systemctl enable --now "${WEB_SERVICE}"
  systemctl enable --now "${SCHEDULER_SERVICE}"
  systemctl enable nginx
  systemctl restart nginx
  setup_cloudflared
}

enable_certbot_if_requested() {
  if bool_is_true "${ENABLE_CLOUDFLARED}"; then
    log "Cloudflared mode is enabled. Skipping Certbot because public TLS terminates at Cloudflare."
    return 0
  fi

  if ! bool_is_true "${ENABLE_CERTBOT}"; then
    warn "ENABLE_CERTBOT=0. Leaving the app in HTTP-safe mode for now."
    return 0
  fi

  log "Requesting Let's Encrypt certificate for ${APP_DOMAIN}..."
  if [[ -n "${APP_WWW_DOMAIN}" ]]; then
    certbot --nginx --non-interactive --agree-tos --redirect -m "${LETSENCRYPT_EMAIL}" -d "${APP_DOMAIN}" -d "${APP_WWW_DOMAIN}"
  else
    certbot --nginx --non-interactive --agree-tos --redirect -m "${LETSENCRYPT_EMAIL}" -d "${APP_DOMAIN}"
  fi

  log "Switching environment to HTTPS production settings..."
  write_env_file "https" "1"
  systemctl restart "${WEB_SERVICE}"
  systemctl restart "${SCHEDULER_SERVICE}"
  systemctl reload nginx
}

print_summary() {
  log "Fresh Ubuntu deployment complete."
  printf '\nSummary:\n'
  printf '  LibreQoS path preserved: %s\n' "${LIBREQOS_DIR}"
  printf '  App directory: %s\n' "${APP_DIR}"
  printf '  Environment file: %s\n' "${ENV_FILE}"
  printf '  Backup root: %s\n' "${BACKUP_ROOT}"
  printf '  Web service: %s\n' "${WEB_SERVICE}"
  printf '  Scheduler service: %s\n' "${SCHEDULER_SERVICE}"
  printf '  Nginx site: %s\n' "${NGINX_SITE_AVAILABLE}"
  printf '  Database: %s\n' "${POSTGRES_DB}"
  printf '  Database user: %s\n' "${POSTGRES_USER}"

  if bool_is_true "${ENABLE_CLOUDFLARED}"; then
    printf '  Tunnel mode: enabled\n'
    printf '  Tunnel origin URL: http://127.0.0.1:%s\n' "${CLOUDFLARED_ORIGIN_PORT}"
    if [[ "${CLOUDFLARED_REUSED}" -eq 1 ]]; then
      printf '  cloudflared service: existing service preserved\n'
      warn "Existing cloudflared service was preserved. Confirm in the Cloudflare dashboard that ${APP_DOMAIN} routes to http://127.0.0.1:${CLOUDFLARED_ORIGIN_PORT}."
    elif [[ "${CLOUDFLARED_INSTALLED_BY_SCRIPT}" -eq 1 ]]; then
      printf '  cloudflared service: installed by this script\n'
      warn "Confirm in the Cloudflare dashboard that the tunnel publishes ${APP_DOMAIN} to http://127.0.0.1:${CLOUDFLARED_ORIGIN_PORT}."
    fi
    printf '  Base URL: https://%s\n' "${APP_DOMAIN}"
  elif bool_is_true "${ENABLE_CERTBOT}"; then
    printf '  Base URL: https://%s\n' "${APP_DOMAIN}"
  elif [[ -n "${APP_DOMAIN}" ]]; then
    printf '  Base URL: http://%s\n' "${APP_DOMAIN}"
    warn "HTTPS was not enabled. Run certbot before treating this server as fully live."
  elif [[ -n "${PRIMARY_IP}" ]]; then
    printf '  Base URL: http://%s\n' "${PRIMARY_IP}"
    warn "This is an IP-based HTTP deployment. Move to DNS + HTTPS before true production use."
  fi

  if [[ -z "${DJANGO_SUPERUSER_USERNAME}" ]]; then
    printf '\nNext step:\n'
    printf '  sudo -u %s %s/.venv/bin/python manage.py createsuperuser\n' "${APP_USER}" "${APP_DIR}"
  fi
}

main() {
  preflight_checks
  ensure_secrets
  install_packages
  create_runtime_user
  stage_source_tree
  deploy_source_tree
  setup_python_env
  setup_postgres
  if bool_is_true "${ENABLE_CLOUDFLARED}"; then
    write_env_file "https" "1"
  else
    write_env_file "http" "0"
  fi
  run_django_setup
  create_superuser_if_requested
  start_services
  enable_certbot_if_requested
  print_summary
}

main "$@"
