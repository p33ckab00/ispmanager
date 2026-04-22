# Landing V2 Core Implementation Notes

## Summary

This update completes the first substantial public-site upgrade for the ISP Manager landing module.

The landing page is now treated as the real public homepage, with a stronger content model, live publish behavior, public inquiry capture, FAQ management, metadata support, and a responsive navigation fix.

## What Was Implemented

### 1. Public Homepage as the Main Site Entry

The public landing page is now the homepage at `/`.

Operational behavior:

- published homepage content is shown at `/`
- unpublished homepage falls back to the `coming_soon` page
- internal dashboard and setup routes remain separate

### 2. Landing V2 Core Content Model

The landing data model now supports richer public-site content beyond the original hero and contact copy.

Added support includes:

- SEO and social metadata
- FAQ content
- public inquiry submissions
- richer homepage section copy
- configurable hero statistics
- configurable quick links
- configurable plan section copy
- configurable why-us cards
- configurable coverage and payment copy
- configurable inquiry panel copy
- configurable contact and CTA banner copy
- configurable navigation labels
- configurable inquiry form labels and placeholders

## 3. Public Inquiry Workflow

The homepage now contains a public inquiry form.

Behavior:

- visitors can submit inquiries directly from the published homepage
- inquiries are stored in the database
- staff can review inquiries from the landing admin area
- inquiry statuses can be updated as:
  - `new`
  - `contacted`
  - `closed`

This gives the public site a working lead-capture path instead of acting only as a static brochure page.

## 4. FAQ Workflow

FAQ management is now handled in the landing module instead of hardcoding content in the homepage template.

Behavior:

- staff can add, edit, publish, and remove FAQs
- each FAQ belongs to a landing page
- only published FAQs appear on the public homepage

## 5. Metadata Support

The landing page now supports editable metadata fields for homepage SEO and preview control.

Supported metadata includes:

- `meta_title`
- `meta_description`
- `meta_keywords`
- `og_title`
- `og_description`

These values are rendered directly into the public homepage template.

## 6. Publish Behavior

The landing editor is wired directly to the live homepage.

Current behavior:

- if the homepage is published, saving edits updates the public page immediately
- if the homepage is unpublished, the public page does not show the edited landing content
- FAQ visibility is controlled separately through each FAQ's `is_published` field

## 7. Navigation Fix

A responsive bug existed where both the desktop navigation bar and the mobile nav sheet could appear together above the mobile breakpoint.

Fix applied:

- added a base `.nav-sheet { display: none; }`
- kept mobile nav-sheet visibility only inside the mobile breakpoint logic
- kept nav-sheet opening dependent on `.site-header.open`

Result:

- `821px and above`: desktop nav only
- `820px and below`: mobile nav-sheet behavior only

## 8. Configurability Expansion

The public homepage is now much more editable from the landing editor.

Configurable content now includes:

- top navigation labels
- admin login/dashboard/logout labels
- portal button and mobile portal labels
- inquiry form field labels
- inquiry form placeholders
- inquiry success message

This reduces the amount of hardcoded copy in the published homepage and makes future content changes safer for non-code updates.

## Files Updated

Primary implementation files:

- `apps/landing/models.py`
- `apps/landing/forms.py`
- `apps/landing/views.py`
- `apps/landing/urls.py`
- `templates/landing/public_home.html`
- `templates/landing/edit.html`
- `templates/landing/dashboard.html`
- `templates/landing/faqs.html`
- `templates/landing/inquiries.html`

## Migrations Added

- `apps/landing/migrations/0003_landingpage_meta_description_and_more.py`
- `apps/landing/migrations/0004_landingpage_about_card_eyebrow_and_more.py`
- `apps/landing/migrations/0005_landingpage_admin_login_label_and_more.py`

## Validation Performed

The following checks were completed during implementation:

- `manage.py migrate landing`
- `manage.py check`
- landing editor page returned `200`
- FAQ management page returned `200`
- inquiry management page returned `200`
- public homepage returned `200`
- published-page edit probe confirmed live updates on the public homepage
- responsive nav CSS structure confirmed the desktop/mobile overlap fix

## Remaining Nice-to-Have Work

The landing page is now significantly more operational, but these remain good next-phase enhancements:

- logo upload
- hero image support
- testimonials
- richer social sharing media support
- coverage map or area cards
- public application workflow beyond simple inquiry capture

## Final Implementation Definition

Landing V2 Core is now defined as:

- public homepage at `/`
- editable landing content with publish control
- admin login and dashboard/logout visibility on the landing page
- public inquiry form with staff review workflow
- FAQ management with publish control
- homepage metadata support
- responsive navigation fix
- expanded copy configurability for the live published page
