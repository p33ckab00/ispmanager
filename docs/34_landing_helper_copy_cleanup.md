# Landing Helper Copy Cleanup

## Summary

This update cleans up the public landing page so internal helper copy is no longer shown to normal visitors.

The homepage now separates:

- public-facing marketing content for guests and subscribers
- staff preview guidance for logged-in operators

## Problem Addressed

Some fallback text on the landing page was written as editorial guidance for staff, not as client-facing copy.

Examples included text such as:

- guidance about how the homepage should be used
- notes about content being editable from the admin side
- internal explanations about inquiries being saved inside the system

That kind of copy is useful while editing or previewing the page, but it should not appear on the live public homepage.

## Behavior After This Change

### Guest / public view

Guests now see clean public-facing fallback copy instead of internal editorial notes.

### Staff preview while logged in

Logged-in staff can still see helper-oriented fallback copy while previewing the homepage.

This keeps the preview useful without exposing internal guidance to clients.

## Scope

The cleanup was applied to the public landing page template in areas such as:

- hero copy
- hero stats
- network promise
- quick links
- operations highlights
- plans intro
- why-us section
- coverage section
- payment fallback notes
- FAQ intro and empty state
- inquiry section
- contact card fallback titles
- CTA banner
- footer fallback copy

## File Updated

- `templates/landing/public_home.html`

## Validation

The following checks were confirmed:

- `python manage.py check`
- guest homepage returned `200`
- staff preview homepage returned `200`
- internal helper copy is hidden from guest view
- helper copy remains visible in staff preview

## Intent

The landing page should feel polished and client-ready in live view.

If fallback content is needed, it should still sound like real public copy rather than editor instructions.
