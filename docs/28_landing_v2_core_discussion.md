# Landing Page V2 Core Discussion

## Summary

The landing page now works as the public homepage of the ISP Manager project.

That gives the project a proper public front door, but the current landing page is still strongest as a branded public information page rather than a full conversion page.

The next recommended phase is `Landing V2 Core`.

This phase should focus on turning the landing page into a more practical business asset by adding:

- a public inquiry or application form
- an editable FAQ section
- SEO and metadata support

These features should come before more visual or branding-heavy features such as testimonials, logo upload, hero images, or coverage maps.

## Why This Is the Right Next Step

At this stage of the project, the billing and subscriber workflows are already becoming operationally meaningful.

That means the public landing page should now do more than look presentable.
It should help with actual day-to-day ISP needs such as:

- collecting new leads
- reducing repetitive pre-sales questions
- improving discoverability and page quality
- guiding visitors toward the right next action

This is why the next wave should prioritize conversion and clarity over decoration.

## Current Landing Strengths

The current landing page already provides:

- a public homepage at `/`
- editable hero content
- editable plans section
- editable contact section
- editable coverage and support copy
- public access to the subscriber portal
- admin login access from the homepage

This is a strong foundation.

## Current Gaps

The current landing page still lacks several things needed for a stronger real-world ISP site.

### 1. No public inquiry capture

Visitors can read the page, but they still cannot directly submit an inquiry, service request, or installation interest through the website itself.

### 2. No FAQ management

The page does not yet have a structured FAQ area that answers the common questions an ISP receives every day.

### 3. No SEO-specific controls

The page title and summary are still mostly derived from content fields.
There is no dedicated control for:

- meta title
- meta description
- Open Graph summary fields

### 4. Branding still depends mostly on typography and color

The page feels much stronger than before, but it does not yet support:

- logo upload
- hero image
- brand asset uploads

These are useful, but they are not the highest-value next step.

## Recommended Scope for Landing V2 Core

### A. Public Inquiry Form

This should be the highest-priority feature.

The landing page should allow a visitor to submit a basic inquiry or service-interest form.

Recommended fields:

- full name
- mobile number
- address or area
- preferred plan
- message or notes

Recommended outcomes:

- save inquiry into the database
- show success feedback on the public site
- optionally notify staff via Telegram later

This gives the landing page actual lead-generation value.

### B. FAQ Section

This should be the second highest-priority feature.

Recommended FAQ topics for an ISP site:

- what areas are served
- how long installation takes
- how to pay bills
- due dates and billing reminders
- what happens when payment is late
- whether routers or installation devices are included
- support hours

The FAQ should be fully editable from the admin side.

### C. SEO and Metadata Fields

This should be the third priority within the same feature wave.

Recommended fields on the landing page model:

- `meta_title`
- `meta_description`
- optional `meta_keywords`
- `og_title`
- `og_description`

These improve both production readiness and public discoverability.

## Recommended Scope to Delay

The following features are valuable, but should be handled after `Landing V2 Core`:

### 1. Testimonials

Testimonials improve trust, but they are lower priority than inquiry capture and FAQ.
They are also weaker if there are not yet strong real customer testimonials to publish.

### 2. Logo Upload

Logo upload is useful for branding polish, but it does not solve a business workflow problem by itself.

### 3. Hero Image Upload

This is a good enhancement later, but it should come after the functional sections are in place.

### 4. Coverage Map

A map can look good, but it adds complexity and maintenance overhead.
For now, area text or area cards are enough.

## Proposed Information Architecture

The cleanest model for the next landing phase is to separate singleton content from repeatable content.

### Keep on `LandingPage`

Use `LandingPage` for singleton page-level content such as:

- hero content
- CTA labels and links
- coverage text
- support hours
- payment channels
- meta fields
- future logo and hero image fields

### Add separate models for repeatable content

Recommended new models:

- `LandingInquiry`
- `LandingFAQ`
- later: `LandingTestimonial`

This keeps the schema clean and easier to maintain.

## Recommended Public Workflow

### Visitor flow

1. Visitor opens `/`
2. Visitor reads plans, coverage, FAQ, and contact details
3. Visitor either:
   - opens the subscriber portal
   - clicks admin login if staff
   - submits an inquiry form if interested in service

### Staff flow

1. Staff opens `/`
2. Staff uses admin login or dashboard access
3. Staff checks inquiry entries from the admin side
4. Staff contacts the lead manually or through a future CRM/sales workflow

## Recommended Admin Workflow

The landing management area should eventually support:

- homepage content editing
- plan editing
- FAQ management
- inquiry review list
- status tracking for inquiries

Recommended inquiry statuses:

- `new`
- `contacted`
- `closed`

This is enough for a first operational version.

## Risks and Considerations

### 1. Public form abuse

Any public inquiry form can attract spam.
For the first version, this risk may be acceptable, but later we may want:

- rate limiting
- honeypot field
- CAPTCHA or similar anti-bot measure

### 2. Operational follow-through

A public inquiry form only helps if staff actually check and respond.
So the admin-side visibility matters almost as much as the form itself.

### 3. Scope discipline

It is tempting to combine inquiry forms, testimonials, branding assets, maps, and SEO into one big landing overhaul.
That would slow things down.

The better path is:

- first build the practical landing workflow
- then add branding and trust enhancements after

## Recommended Decision

The recommended next implementation scope is:

### `Landing V2 Core`

Include:

- public inquiry form
- FAQ model and FAQ section
- SEO/meta fields

Do not include yet:

- testimonials
- logo upload
- hero image upload
- coverage map

## Expected Outcome

After `Landing V2 Core`, the public homepage should:

- look like a real ISP public site
- answer common questions
- collect inquiries directly
- support better production metadata
- act as a more useful business entry point instead of only a public brochure page

## Follow-up Phase After This

Once `Landing V2 Core` is stable, the next recommended landing phase is:

### `Landing Branding and Trust`

That later phase can include:

- testimonials
- logo upload
- hero image support
- richer visual branding
- optional coverage map or area cards
