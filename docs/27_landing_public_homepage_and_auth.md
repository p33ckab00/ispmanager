# Landing Page Public Homepage and Admin Auth Update

## Summary

The landing page is now the public homepage of the project.

Instead of sending visitors to the internal dashboard at `/`, the system now uses the public landing page as the main entry point. Internal staff still use `/dashboard/`, while subscribers still use the OTP-based portal under `/subscribers/portal/`.

This change also adds a clearer public/admin split:

- Public visitors see the landing page first
- Staff can log in from the landing page through an `Admin Login` action
- Logged-in staff can jump from the landing page to the internal dashboard
- Logging out now returns the user to the landing page instead of the login page

## What Changed

### 1. Public homepage routing

The root route `/` now renders the public landing page.

Result:

- `/` = public website
- `/dashboard/` = internal staff dashboard
- `/setup/` still remains available for first-run setup handling

This makes the project behave more like a real production ISP site, where the public homepage is the front door and internal tools stay behind login.

### 2. Landing page redesign

The public landing page was enhanced to feel more like a real ISP website instead of a minimal preview page.

Enhancements include:

- stronger hero section
- editable hero badge
- editable primary and secondary call-to-action buttons
- better plan presentation
- trust and support sections
- coverage section
- payment channels section
- clearer contact section
- stronger subscriber portal visibility
- mobile navigation improvements

### 3. New landing content fields

The landing content model now supports additional editable fields:

- `hero_badge`
- `hero_primary_cta_label`
- `hero_primary_cta_url`
- `hero_secondary_cta_label`
- `hero_secondary_cta_url`
- `coverage_title`
- `coverage_text`
- `support_hours`
- `payment_channels`

These fields are editable from the landing admin editor and allow the public page to be changed without code edits.

### 4. Admin Login from landing page

The landing page now shows an `Admin Login` action for unauthenticated visitors.

Behavior:

- guest user sees `Admin Login`
- guest user also still sees `My Account` for subscriber portal access
- authenticated staff sees `Dashboard` and `Logout` instead of `Admin Login`

This gives the public homepage dual purpose:

- public marketing and contact page for visitors
- quick entry point for internal staff

### 5. Logout redirect change

Staff logout now redirects to `/`.

Old behavior:

- logout returned to `/auth/login/`

New behavior:

- logout returns to the public landing page

This feels more natural now that the landing page is the public homepage.

## Files Involved

### Routing

- `config/urls.py`
- `apps/core/urls.py`
- `apps/landing/urls.py`

### Landing logic and model

- `apps/landing/models.py`
- `apps/landing/views.py`

### Auth/logout behavior

- `apps/core/views.py`
- `config/settings.py`

### Templates

- `templates/landing/public_home.html`
- `templates/landing/edit.html`
- `templates/landing/dashboard.html`

### Migration

- `apps/landing/migrations/0002_landingpage_coverage_text_landingpage_coverage_title_and_more.py`

## Validation Performed

The following checks were performed after the change:

- `python manage.py check`
- confirmed `/` returns `200`
- confirmed `/dashboard/` still redirects unauthenticated users to login
- confirmed `/setup/` behavior remains intact
- confirmed public landing page shows `Admin Login` for guests
- confirmed public landing page shows `Dashboard` and `Logout` for authenticated staff
- confirmed logout now redirects to `/`
- confirmed the landing migration applies successfully

## Important Notes

### 1. Landing content may still look generic until edited

If the homepage content fields are blank, the new public page uses fallback copy.

That means the structure is now stronger, but real branding still depends on filling in:

- hero text
- support hours
- payment channels
- coverage information
- plan list
- contact details

### 2. Staff dashboard behavior did not change

This update does not replace the internal dashboard.

It only changes which page is shown first to public visitors.

### 3. Subscriber portal remains separate

Subscriber self-service still uses:

- `/subscribers/portal/`

The landing page now exposes that more clearly as a customer-facing action.

## Recommended Next Enhancements

Now that the landing page is acting as the main public homepage, the next strongest improvements would be:

1. add an application or inquiry form
2. add testimonials or trust proofs
3. add FAQ content
4. add social links or Messenger/Facebook contact actions
5. add SEO metadata fields
6. add service-area map or area cards
7. add branding assets such as logo upload and hero background image

## Architectural Outcome

This change improves the separation between:

- public site experience
- staff operations dashboard
- subscriber self-service portal

That is the right direction for production deployment.
