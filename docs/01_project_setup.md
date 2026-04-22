# Step 01 - Project Setup + core app

## Status: DONE

---

## What Was Built

### Project Structure
```
ispmanager/
├── manage.py
├── .env
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── settings.py       # Main Django settings
│   ├── urls.py           # Root URL config
│   ├── api_urls.py       # All DRF /api/v1/ routes
│   └── wsgi.py
├── apps/
│   ├── __init__.py
│   ├── core/             # BUILT - see below
│   ├── settings_app/     # Stubbed
│   ├── routers/          # Stubbed
│   ├── subscribers/      # Stubbed
│   ├── billing/          # Stubbed
│   ├── accounting/       # Stubbed
│   ├── sms/              # Stubbed
│   ├── notifications/    # Stubbed
│   ├── diagnostics/      # Stubbed
│   └── landing/          # Stubbed
├── templates/
│   ├── base.html
│   ├── core/
│   │   ├── setup.html    # First-run wizard
│   │   ├── login.html
│   │   └── dashboard.html
│   └── partials/
│       ├── sidebar.html
│       ├── topbar.html
│       └── messages.html
├── static/
│   ├── css/
│   ├── js/
│   └── img/
└── docs/
```

---

## core App Files

| File | Purpose |
|------|---------|
| apps/core/models.py | SystemSetup, AuditLog models |
| apps/core/middleware.py | FirstRunMiddleware - redirects to /setup/ if not configured |
| apps/core/context_processors.py | Injects isp_name, isp_logo into all templates |
| apps/core/forms.py | FirstRunForm - ISP info + admin account creation |
| apps/core/views.py | setup_wizard, login_view, logout_view, dashboard |
| apps/core/urls.py | / and /setup/ routes |
| apps/core/auth_urls.py | /auth/login/ and /auth/logout/ |
| apps/core/dashboard_urls.py | /dashboard/ |
| apps/core/api_urls.py | /api/v1/core/ endpoints |
| apps/core/serializers.py | SystemSetupSerializer, AuditLogSerializer |
| apps/core/api_views.py | SetupStatusView, AuditLogListView |

---

## Key Models

### SystemSetup
- Singleton model (pk=1 always)
- Tracks: is_configured, isp_name, isp_address, isp_phone, isp_email, isp_logo
- get_setup() classmethod returns or creates the single instance

### AuditLog
- Tracks every action across all modules
- Fields: user, action, module, description, ip_address, created_at
- log() classmethod for easy logging from anywhere

---

## Key Decisions

- First-run wizard creates the one admin account then disables further signups
- FirstRunMiddleware blocks ALL routes except /setup/, /auth/, /static/, /admin/
- All templates use TailwindCSS via CDN - no build step needed
- HTMX and Alpine.js loaded via CDN for interactivity
- TIME_ZONE set to Asia/Manila

---

## Dependencies Installed

```
Django==5.0.6
djangorestframework==3.15.2
django-cors-headers==4.4.0
django-environ==0.11.2
djangorestframework-simplejwt==5.3.1
Pillow==10.4.0
routeros-api==0.17.0
requests==2.32.3
python-telegram-bot==21.4
django-apscheduler==0.6.2
whitenoise==6.7.0
django-extensions==3.2.3
```

---

## How to Run

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
python manage.py migrate

# 4. Start server
python manage.py runserver 0.0.0.0:8193

# 5. Open browser
http://localhost:8193
# You will be redirected to /setup/ automatically
```

---

## API Endpoints (core)

| Method | URL | Description |
|--------|-----|-------------|
| GET | /api/v1/core/setup-status/ | Check if system is configured (public) |
| GET | /api/v1/core/audit-logs/ | List all audit logs (auth required) |

---

## Known Warnings

- `urllib3` version mismatch warning from `requests` library - this is harmless, does not affect functionality.

---

## Next Step
Step 02: settings_app - global settings + per-module settings storage
