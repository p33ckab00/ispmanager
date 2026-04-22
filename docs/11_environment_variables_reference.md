# Environment Variables Reference

Configuration reference for `ISP Manager` across development, staging, and production environments.

## Purpose

This document defines the recommended environment variables for running `ISP Manager` safely and consistently.

It is intended to support:

- local development
- staging
- Ubuntu production deployment
- PostgreSQL migration
- scheduler separation
- secure secret handling

## General Rules

### Rule 1

Do not hardcode production secrets in source files.

### Rule 2

Use environment variables or a protected environment file for:

- secrets
- DB credentials
- deployment-specific settings
- runtime mode switches

### Rule 3

Use different values per environment:

- development
- staging
- production

### Rule 4

Do not commit real secret values into Git.

## 1. Core Django Variables

### `DJANGO_SETTINGS_MODULE`

Purpose:

- tells Django which settings module to use

Typical value:

- `config.settings`

Required:

- yes

### `SECRET_KEY`

Purpose:

- Django cryptographic signing key

Required:

- yes

Production guidance:

- use a strong random secret
- never reuse weak defaults
- never commit real production value

### `DEBUG`

Purpose:

- enables or disables debug mode

Allowed values:

- `True`
- `False`

Production guidance:

- must be `False`

### `ALLOWED_HOSTS`

Purpose:

- controls allowed hostnames for Django requests

Typical values:

- `localhost,127.0.0.1`
- `yourdomain.com,www.yourdomain.com`

Production guidance:

- do not leave as wildcard if avoidable

## 2. Database Variables

These are the active database variables for the current PostgreSQL-only setup.

### `POSTGRES_DB`

Purpose:

- database name

Examples:

- `ispmanager`
- `ispmanager_staging`

### `POSTGRES_USER`

Purpose:

- database username

Example:

- `ispmanager`

### `POSTGRES_PASSWORD`

Purpose:

- database password

Production guidance:

- strong random value
- never hardcode

### `POSTGRES_HOST`

Purpose:

- database host

Examples:

- `127.0.0.1`
- `localhost`
- private DB host IP

### `POSTGRES_PORT`

Purpose:

- database port

Typical value:

- `5432`

### `DB_CONN_MAX_AGE`

Purpose:

- controls Django persistent DB connections

Typical production guidance:

- use moderate non-zero value if beneficial
- tune based on connection behavior and pooling strategy

## 3. CSRF / CORS / URL Variables

### `CSRF_TRUSTED_ORIGINS`

Purpose:

- trusted origins for CSRF-sensitive requests

Examples:

- `https://yourdomain.com`
- `https://www.yourdomain.com`

Production guidance:

- required if using HTTPS and reverse proxy

### `CORS_ALLOWED_ORIGINS`

Purpose:

- allowed origins for API calls if cross-origin access is needed

Examples:

- `http://localhost:8000`
- `https://app.yourdomain.com`

Production guidance:

- keep as narrow as possible

### `SITE_BASE_URL`

Purpose:

- canonical base URL for public links

Example:

- `https://isp.example.com`

Why this matters:

- SMS billing links
- public billing view links
- future email or portal links

Recommended:

- add and use this instead of hardcoded `localhost`

## 4. Scheduler Variables

These are important once moving toward production-safe scheduler separation.

### `ENABLE_INTERNAL_SCHEDULER`

Purpose:

- controls whether scheduler auto-starts inside the web app process

Suggested values:

- `true`
- `false`

Recommended usage:

- development: `true` optionally
- staging: `false`
- production: `false`

### `SCHEDULER_ROLE`

Purpose:

- identifies whether a process is a web process or scheduler process

Suggested values:

- `web`
- `scheduler`

Recommended production usage:

- Gunicorn service: `web`
- dedicated scheduler service: `scheduler`

### `SCHEDULER_LOG_LEVEL`

Purpose:

- allows independent scheduler verbosity tuning

Suggested values:

- `INFO`
- `WARNING`
- `ERROR`
- `DEBUG`

## 5. Security Variables

### `SECURE_SSL_REDIRECT`

Purpose:

- redirect all HTTP traffic to HTTPS

Production guidance:

- enable in production behind correct proxy setup

### `SESSION_COOKIE_SECURE`

Purpose:

- send session cookie only over HTTPS

Production guidance:

- `True` in production

### `CSRF_COOKIE_SECURE`

Purpose:

- send CSRF cookie only over HTTPS

Production guidance:

- `True` in production

### `SECURE_PROXY_SSL_HEADER`

Purpose:

- informs Django that HTTPS is terminated by reverse proxy

Production guidance:

- configure only when proxy is correctly forwarding protocol headers

## 6. Static and Media Variables

### `STATIC_ROOT`

Purpose:

- target directory for collected static files

Production example:

- `/opt/ispmanager/staticfiles`

### `MEDIA_ROOT`

Purpose:

- directory for runtime-uploaded/generated files

Production example:

- `/opt/ispmanager/media`

### `MEDIA_URL`

Purpose:

- public URL prefix for media files

Typical value:

- `/media/`

## 7. Telegram Variables

You can keep these in DB settings, but environment variable support is also recommended for production bootstrap.

### `TELEGRAM_BOT_TOKEN`

Purpose:

- Telegram bot token

### `TELEGRAM_CHAT_ID`

Purpose:

- destination chat ID

### `TELEGRAM_ENABLE_NOTIFICATIONS`

Purpose:

- top-level Telegram enable flag

Suggested values:

- `true`
- `false`

Recommendation:

- DB may remain source of truth in-app
- env vars can seed or override in production if desired

## 8. SMS Variables

### `SEMAPHORE_API_KEY`

Purpose:

- SMS provider API key

### `SEMAPHORE_SENDER_NAME`

Purpose:

- sender name for SMS

### `ENABLE_BILLING_SMS`

Purpose:

- top-level billing SMS enable flag

## 9. Router / Telemetry Variables

### `ROUTER_DEFAULT_API_PORT`

Purpose:

- default MikroTik API port

### `ROUTER_CONNECTION_TIMEOUT_SECONDS`

Purpose:

- router connection timeout

### `ROUTER_POLLING_INTERVAL_SECONDS`

Purpose:

- router status / telemetry sampling interval

### `USAGE_SAMPLER_INTERVAL_MINUTES`

Purpose:

- subscriber usage sampling interval

## 10. Logging and Monitoring Variables

### `LOG_LEVEL`

Purpose:

- overall application logging level

Suggested values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`

### `DJANGO_LOG_LEVEL`

Purpose:

- optional Django-specific log tuning

### `GUNICORN_LOG_LEVEL`

Purpose:

- Gunicorn log verbosity

### `ENABLE_SENTRY`

Purpose:

- toggle Sentry or error tracking integration

Suggested values:

- `true`
- `false`

### `SENTRY_DSN`

Purpose:

- Sentry DSN if error tracking is enabled

## 11. Suggested Environment Profiles

## Development

Recommended characteristics:

- `DEBUG=True`
- PostgreSQL
- internal scheduler optional
- broad localhost origins acceptable
- lower security strictness

## Staging

Recommended characteristics:

- `DEBUG=False`
- PostgreSQL
- no internal web-process scheduler
- production-like host and HTTPS settings
- isolated staging secrets

## Production

Required characteristics:

- `DEBUG=False`
- PostgreSQL
- HTTPS-aware settings
- secure cookies
- restricted hosts
- internal scheduler disabled
- separate scheduler service

## 12. Example Variable Inventory by Environment

### Minimum Local Development Set

- `DJANGO_SETTINGS_MODULE`
- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

### Minimum Staging Set

- `DJANGO_SETTINGS_MODULE`
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `DB_ENGINE=postgresql`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_BASE_URL`
- `ENABLE_INTERNAL_SCHEDULER=false`
- `SCHEDULER_ROLE`

### Minimum Production Set

- `DJANGO_SETTINGS_MODULE`
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `DB_ENGINE=postgresql`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `CSRF_TRUSTED_ORIGINS`
- `CORS_ALLOWED_ORIGINS` if needed
- `SITE_BASE_URL`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `ENABLE_INTERNAL_SCHEDULER=false`
- `SCHEDULER_ROLE=web` for web service
- `SCHEDULER_ROLE=scheduler` for scheduler service

## 13. Recommended File Placement for Ubuntu Production

Suggested secure environment file:

- `/etc/ispmanager/ispmanager.env`

Recommended permissions:

- owned by root
- readable by service user only if required
- not world-readable

## 14. Recommended Next Step for Codebase

To support this document cleanly, the codebase should eventually:

- centralize env loading
- support PostgreSQL env-based config
- support `ENABLE_INTERNAL_SCHEDULER`
- support `SITE_BASE_URL`
- support secure production defaults

## 15. Final Recommendation

Use environment variables as the single deployment-time configuration layer for:

- database selection
- secrets
- security settings
- scheduler behavior
- deployment host details

This will make `ISP Manager` easier to:

- deploy to Ubuntu
- move to PostgreSQL
- separate scheduler from web workers
- harden for production
