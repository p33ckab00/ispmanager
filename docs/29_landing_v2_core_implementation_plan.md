# Landing V2 Core Implementation Plan

## Summary

This document defines the implementation plan for the next landing-page feature wave.

Target scope:

- public inquiry form
- FAQ management and public FAQ section
- SEO and metadata fields

This phase intentionally does not yet include testimonials, logo upload, hero image upload, or coverage maps.

## Goals

### Primary goals

- turn the landing page into a real lead-capture page
- reduce repetitive pre-sales and billing-related questions
- improve public metadata and production readiness
- keep the implementation clean and maintainable

### Non-goals for this phase

- full CRM workflow
- automated sales pipeline
- testimonial management
- logo/hero image uploads
- advanced map integration

## Proposed Data Model

### 1. Extend `LandingPage`

Add page-level metadata fields:

- `meta_title`
- `meta_description`
- `meta_keywords` optional
- `og_title`
- `og_description`

These are singleton fields and belong on the existing landing page model.

### 2. Add `LandingInquiry`

Recommended fields:

- `full_name`
- `mobile_number`
- `service_address`
- `preferred_plan` optional
- `message`
- `status`
- `created_at`
- `updated_at`

Recommended status choices:

- `new`
- `contacted`
- `closed`

Purpose:

- receive and store public inquiries
- allow staff to review them from the admin side

### 3. Add `LandingFAQ`

Recommended fields:

- `page`
- `question`
- `answer`
- `is_published`
- `sort_order`

Purpose:

- editable homepage FAQ section
- easy ordering and publish control

## Public-Side Implementation Plan

### A. Inquiry Form Section on Landing Page

Add a dedicated section on the homepage for inquiries.

Recommended content:

- short heading
- short explanation
- simple form

Recommended fields in the public form:

- full name
- mobile number
- area or address
- preferred plan
- message

Recommended behavior:

- POST to a public landing endpoint
- validate required fields
- save `LandingInquiry`
- show success message after submission
- keep the UX simple and reassuring

### B. FAQ Section on Landing Page

Add a public FAQ section below plans or near contact.

Recommended UI:

- accordion-style question list
- simple open/close interaction
- mobile-friendly layout

Data source:

- only `is_published=True` FAQs
- ordered by `sort_order`

### C. SEO / Metadata in Public Homepage Template

Enhance the homepage template so it uses dedicated meta fields when present.

Recommended precedence:

1. `meta_title` or `og_title`
2. fallback to hero title
3. fallback to `isp_name`

For meta description:

1. `meta_description` or `og_description`
2. fallback to hero subtitle
3. fallback to about text

## Admin-Side Implementation Plan

### A. Landing Editor Form Enhancements

Extend the landing editor to allow editing:

- `meta_title`
- `meta_description`
- `meta_keywords`
- `og_title`
- `og_description`

These should be part of the homepage editing experience.

### B. FAQ Management

Recommended options:

- simplest path: use a landing FAQ admin/list page with add/edit/delete actions
- or integrate FAQ management into the existing landing dashboard area

Preferred implementation:

- separate management views for FAQs
- keep consistent with current landing plan management style

### C. Inquiry Review Page

Add a simple staff-facing inquiry list page.

Minimum useful capabilities:

- list all inquiries
- show submitted details
- filter by status
- update status

This does not need to become a full CRM.

## Routing Plan

### Public routes

Add routes for:

- public inquiry submission
- optional inquiry success handling if needed

### Admin routes

Add routes for:

- landing FAQ management
- landing inquiry list
- landing inquiry status updates

All admin routes should require authentication.

## UI/UX Plan

### Inquiry form UX

The form should feel short and low-friction.

Recommended style:

- no excessive number of fields
- clear success message
- reassuring copy like:
  - “Tell us where you are located and what plan you’re interested in.”
  - “Our team will reach out to confirm availability.”

### FAQ UX

Keep it simple and scannable.

Recommended pattern:

- accordion
- one question visible per row
- clear typography
- good spacing on mobile

### Editor UX

SEO fields can live in a clearly named section such as:

- `Search / Social Metadata`

That keeps them separate from hero and contact content.

## Validation Plan

### Functional checks

1. public homepage still loads
2. inquiry form submits successfully
3. inquiry record is saved in DB
4. inquiry list is visible to staff
5. FAQ items display only when published
6. FAQ ordering works
7. meta title and description render correctly in page source

### Regression checks

1. existing landing content still renders correctly
2. plans still display correctly
3. subscriber portal link still works
4. admin login from landing still works
5. internal dashboard access is unaffected

## Security and Quality Notes

### For inquiry forms

Minimum acceptable first-version safeguards:

- CSRF protection through Django
- field validation
- avoid overcomplicating with file uploads

Possible later safeguards:

- spam protection
- rate limiting
- honeypot field

### For content management

Keep landing editor input lightweight and plain text first.
Avoid introducing rich text editors unless there is a clear need.

## Implementation Order

Recommended build order:

1. add model changes and migrations
2. extend landing editor with SEO fields
3. add FAQ model, views, admin pages, and public section
4. add inquiry model, public form, and staff review page
5. update homepage template and messaging
6. run functional and regression checks
7. document the implementation after completion

## Success Criteria

This phase is successful when:

- the public landing page can capture new inquiries
- staff can review inquiries from the system
- FAQ is editable and visible on the public site
- metadata fields are editable and reflected in page output
- current public homepage behavior remains stable

## Recommended GO Scope

If approved for implementation, the exact next code scope should be:

- extend `LandingPage` for metadata
- add `LandingFAQ`
- add `LandingInquiry`
- add homepage inquiry form section
- add homepage FAQ section
- add staff FAQ/inquiry management pages
- update landing editor for metadata fields
