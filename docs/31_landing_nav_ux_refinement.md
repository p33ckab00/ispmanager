# Landing Nav UX Refinement

## Summary

This update refines the landing page header so the public homepage no longer mixes public, subscriber, and staff actions at the same visual level.

The main goal is to preserve the landing page as a public-facing experience while still allowing authenticated staff to preview and manage it without cluttering the main navigation.

## Problem

The previous landing header mixed three separate user flows:

- public browsing
- subscriber self-service
- staff/admin actions

This created a confusing header state where:

- `Dashboard` appeared as a public navigation option
- `Logout` was presented like a public CTA
- `My Account` sat beside staff actions, making the action hierarchy feel inconsistent

The result was a crowded header and weaker UX separation.

## UX Decision

The implemented direction is:

- keep the main landing header public-first
- move authenticated staff controls into a separate admin preview bar

This preserves the marketing/site-browsing experience while making it clear that staff is only previewing the public page.

## New Behavior

### Guest users

The main header now shows:

- `Plans`
- `Why Us`
- `Coverage`
- `Contact`

Right-side actions:

- `Admin Login` as a lightweight utility link
- `My Account`
- primary public CTA such as `See Plans`

### Authenticated staff users

The public header remains public-facing and keeps:

- `Plans`
- `Why Us`
- `Coverage`
- `Contact`
- `My Account`
- primary public CTA

Staff controls are moved into a dedicated preview bar above the header:

- `Edit Landing`
- `Dashboard`
- `Logout`

## Why This Is Better

This structure creates a cleaner separation of responsibilities:

- the header stays optimized for prospects and subscribers
- staff actions no longer compete visually with public CTAs
- `Dashboard` is no longer duplicated in the main navigation
- `Logout` is treated as an account utility, not a homepage CTA

## Mobile Impact

The mobile nav sheet keeps the same public-first approach.

It shows:

- public section links
- `Admin Login` only for guests
- subscriber portal link
- the primary CTA

Staff preview actions remain outside the public nav hierarchy through the preview bar pattern.

## Files Updated

- `templates/landing/public_home.html`

## Validation

The following checks were performed:

- `manage.py check`
- guest homepage returned `200`
- authenticated homepage returned `200`
- guest view had no preview bar
- authenticated view showed the preview bar
- authenticated view exposed `Edit Landing`, `Dashboard`, and `Logout` in the preview bar
- main public header no longer displayed redundant `Dashboard` actions

## Final UX Definition

The landing page now follows this header rule:

- public header for public and subscriber-facing navigation
- separate admin preview bar for staff-only controls

This is the recommended long-term pattern for the ISP Manager public homepage.
