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
WEB_SERVICE="${WEB_SERVICE:-ispmanager-web.service}"
SCHEDULER_SERVICE="${SCHEDULER_SERVICE:-ispmanager-scheduler.service}"
PRESERVE_MEDIA="${PRESERVE_MEDIA:-1}"
REBUILD_VENV="${REBUILD_VENV:-0}"

readonly LIBREQOS_DIR="/opt/libreqos"
readonly NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
readonly NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
readonly CLOUDFLARED_SERVICE="cloudflared.service"

STAGING_DIR=""
BACKUP_DIR=""

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
  [[ "${EUID}" -eq 0 ]] || die "Run this redeploy as root: sudo bash deploy/redeploy_ubuntu_update.sh"
}

ensure_repo_root() {
  [[ -f "${REPO_ROOT}/manage.py" ]] || die "Could not find manage.py. Run this from inside the ISP Manager repo."
}

ensure_existing_deployment() {
  [[ -d "${APP_DIR}" ]] || die "Expected deployed app directory at ${APP_DIR}."
  [[ -f "${ENV_FILE}" ]] || die "Expected deployment env file at ${ENV_FILE}."
  [[ -x "${APP_DIR}/.venv/bin/python" || "${REBUILD_VENV}" == "1" ]] || die "Expected existing virtualenv at ${APP_DIR}/.venv or use REBUILD_VENV=1."
}

run_as_app() {
  local cmd="$1"
  runuser -u "${APP_USER}" -- bash -lc "${cmd}"
}

preflight_checks() {
  require_root
  ensure_repo_root
  ensure_existing_deployment

  if [[ -d "${LIBREQOS_DIR}" ]]; then
    log "Detected LibreQoS at ${LIBREQOS_DIR}. This redeploy will not modify it."
  fi

  if systemctl is-active --quiet "${CLOUDFLARED_SERVICE}" 2>/dev/null; then
    log "Detected active ${CLOUDFLARED_SERVICE}. It will be preserved."
  fi
}

prepare_paths() {
  BACKUP_DIR="${BACKUP_ROOT}/redeploy-${TIMESTAMP}"
  STAGING_DIR="$(mktemp -d /tmp/ispmanager-redeploy.XXXXXX)"
  export BACKUP_DIR STAGING_DIR
  trap 'rm -rf "${STAGING_DIR:-}"' EXIT

  install -d -m 0755 "${BACKUP_ROOT}"
  install -d -m 0755 "${BACKUP_DIR}"
}

backup_current_state() {
  log "Backing up current deployment state to ${BACKUP_DIR}..."
  install -d -m 0755 "${BACKUP_DIR}/app"

  rsync -a \
    --exclude '.venv/' \
    --exclude 'media/' \
    --exclude 'staticfiles/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${APP_DIR}/" "${BACKUP_DIR}/app/"

  cp -a "${ENV_FILE}" "${BACKUP_DIR}/" || true
  cp -a "/etc/systemd/system/${WEB_SERVICE}" "${BACKUP_DIR}/" || true
  cp -a "/etc/systemd/system/${SCHEDULER_SERVICE}" "${BACKUP_DIR}/" || true
  cp -a "${NGINX_SITE_AVAILABLE}" "${BACKUP_DIR}/" || true
  cp -a "${NGINX_SITE_ENABLED}" "${BACKUP_DIR}/" || true
}

stage_new_source() {
  log "Staging repo contents from ${REPO_ROOT}..."
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

stop_app_services() {
  log "Stopping app services for redeploy..."
  systemctl stop "${WEB_SERVICE}" || true
  systemctl stop "${SCHEDULER_SERVICE}" || true
}

update_app_tree() {
  log "Updating deployed app tree in ${APP_DIR}..."

  local rsync_cmd=(
    rsync -a --delete
    --exclude '.venv/'
    --exclude 'staticfiles/'
    --exclude '__pycache__/'
    --exclude '*.pyc'
  )

  if bool_is_true "${PRESERVE_MEDIA}"; then
    rsync_cmd+=(--exclude 'media/')
  fi

  "${rsync_cmd[@]}" "${STAGING_DIR}/" "${APP_DIR}/"
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
}

setup_python_env() {
  if bool_is_true "${REBUILD_VENV}"; then
    log "Rebuilding Python virtual environment..."
    rm -rf "${APP_DIR}/.venv"
    run_as_app "cd '${APP_DIR}' && python3 -m venv .venv"
  fi

  if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    log "Creating Python virtual environment..."
    run_as_app "cd '${APP_DIR}' && python3 -m venv .venv"
  fi

  log "Installing Python dependencies..."
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install --upgrade pip wheel"
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install -r requirements.txt"
  run_as_app "cd '${APP_DIR}' && ./.venv/bin/pip install gunicorn"
}

run_django_tasks() {
  log "Running Django migrate, collectstatic, and check..."
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py migrate"
  if bool_is_true "${PRESERVE_MEDIA}"; then
    run_as_app "mkdir -p '${APP_DIR}/media'"
  fi
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py collectstatic --noinput"
  run_as_app "cd '${APP_DIR}' && set -a && source '${ENV_FILE}' && set +a && ./.venv/bin/python manage.py check"
}

start_app_services() {
  log "Restarting services..."
  systemctl daemon-reload
  nginx -t
  systemctl restart "${WEB_SERVICE}"
  systemctl restart "${SCHEDULER_SERVICE}"
  systemctl restart nginx
}

print_summary() {
  log "Redeploy complete."
  printf '\nSummary:\n'
  printf '  App directory: %s\n' "${APP_DIR}"
  printf '  Env file reused: %s\n' "${ENV_FILE}"
  printf '  Backup snapshot: %s\n' "${BACKUP_DIR}"
  printf '  Web service: %s\n' "${WEB_SERVICE}"
  printf '  Scheduler service: %s\n' "${SCHEDULER_SERVICE}"
  if systemctl is-active --quiet "${CLOUDFLARED_SERVICE}" 2>/dev/null; then
    printf '  Cloudflared: active and preserved\n'
  fi
}

main() {
  preflight_checks
  prepare_paths
  backup_current_state
  stage_new_source
  stop_app_services
  update_app_tree
  setup_python_env
  run_django_tasks
  start_app_services
  print_summary
}

main "$@"
