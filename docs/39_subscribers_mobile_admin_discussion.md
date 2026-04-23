# Subscribers Admin Mobile-Friendliness Discussion

## Summary

This document captures the discussion and audit findings for making the authenticated admin `/subscribers/` module mobile-friendly.

This is a `discussion-only` note.

- no code was generated
- no implementation was applied
- this document records the current audit, recommended direction, and rollout strategy before UI work begins

## Scope

This discussion applies to the authenticated admin subscriber management flow:

- `/subscribers/`
- `/subscribers/<id>/`
- `/subscribers/add/`
- `/subscribers/<id>/edit/`
- related subscriber status-action pages such as disconnect, deceased, palugit, and similar admin flows

This does `not` refer to the subscriber self-service portal.

## Problem Statement

On mobile devices, the subscribers admin module is difficult to use.

The most visible symptom reported was:

- on `/subscribers/`, the per-subscriber `View` action is not visible or is effectively inaccessible on smaller screens

The audit shows that this is not a backend routing problem.
It is primarily a responsive layout problem affecting both the shared admin shell and the subscribers templates themselves.

## Audit Findings

### 1. The admin shell is desktop-only

The authenticated layout currently assumes a permanent desktop sidebar and fixed left-offset main content.

Relevant files:

- `templates/base.html`
- `templates/partials/sidebar.html`
- `templates/partials/topbar.html`

Observed issues:

- main content always uses a left offset for the sidebar
- topbar also assumes the sidebar is permanently visible
- sidebar is fixed and always rendered with desktop width
- there is no mobile drawer behavior or small-screen breakpoint handling

Impact:

- even before the subscribers table renders, the mobile viewport already loses usable width

### 2. The subscribers list is table-first with no mobile fallback

Relevant file:

- `templates/subscribers/list.html`

Observed issues:

- the page uses a wide multi-column table
- the `View` link is placed in the last column
- the table container uses clipped overflow instead of horizontal scroll
- there is no mobile card/list alternative

Impact:

- on small screens, the final action column is easy to push off-screen
- the user may not realize there is a `View` action at all

### 3. The list page controls are also desktop-first

Relevant file:

- `templates/subscribers/list.html`

Observed issues:

- top action buttons are arranged in a horizontal toolbar
- search and filters are arranged in a single horizontal row
- there is no mobile stacking strategy for filters and actions

Impact:

- the page becomes cramped on phones
- controls compete with table width instead of helping navigation

### 4. The subscriber detail page is also not mobile-friendly

Relevant file:

- `templates/subscribers/detail.html`

Observed issues:

- header actions are wide and numerous
- tab navigation is desktop-style and width-heavy
- information grids remain multi-column on small screens
- billing, payments, snapshots, and history still use wide tables
- a right sidebar is always present as a real sidebar

Impact:

- even if the user reaches a subscriber detail page, mobile usability remains poor

### 5. Add/Edit pages are also desktop-first

Relevant files:

- `templates/subscribers/add.html`
- `templates/subscribers/edit.html`

Observed issues:

- form fields use two-column grid layouts by default
- action buttons are arranged for desktop width
- there is no mobile-first form stacking strategy

Impact:

- manual subscriber creation and editing are harder than necessary on phones

## Important Clarification

The audit did not find evidence of a broken subscriber detail route.

Relevant backend files:

- `apps/subscribers/urls.py`
- `apps/subscribers/views.py`

Conclusion:

- the problem is a frontend responsiveness issue
- the existing subscriber detail route and view flow are structurally fine

## Agreed Design Direction

The best path is not to force the current desktop table to fit every mobile screen.

The recommended direction is:

- keep dense table layouts for desktop and larger tablets
- use mobile-appropriate cards, stacked sections, wrapped actions, and scroll-safe navigation on smaller screens

In short:

- desktop = dense operational tables
- mobile = readable cards and stacked task flows

## Recommended Implementation Strategy

### Phase 1. Make the shared admin shell responsive

This should come first because every authenticated admin page depends on it.

Recommended behavior:

- keep the current sidebar on desktop
- convert the sidebar into a mobile drawer on phones
- remove permanent left-margin assumptions from the main content area on mobile
- allow the topbar to span the full mobile width

Expected outcome:

- the subscribers module gets real usable screen width on mobile
- improvements also benefit other admin modules later

### Phase 2. Redesign `/subscribers/` for mobile

Recommended strategy:

- keep the existing table for desktop breakpoints
- add a dedicated mobile card layout for smaller screens

Each subscriber card should prioritize:

- display name
- username
- status
- MikroTik status
- plan
- rate
- phone
- a clear `View` action

Recommended interaction:

- either make the entire card tap-to-open
- or show a strong primary `View` button

Recommended control strategy:

- stack search and filters vertically on mobile
- keep the primary operational action visible
- move secondary actions into a less dominant row or compact control area

### Phase 3. Make `/subscribers/<id>/` mobile-friendly

Recommended strategy:

- stack the page vertically on mobile
- remove the concept of a persistent right sidebar on phones
- move sidebar information into stacked cards inside the main flow
- keep tabs, but make them horizontally scrollable or compact

Recommended mobile priorities:

- subscriber identity and status
- primary actions such as payment and suspend/reconnect
- readable account info
- usable billing visibility

Recommended table handling:

- short term: wrap wide tables in horizontal scroll containers
- better long term: convert invoice/payment/history rows into mobile cards or condensed stacked lists

### Phase 4. Make add/edit and status forms mobile-friendly

Recommended strategy:

- use single-column form layouts on mobile
- keep two-column layouts only for wider screens
- make primary action buttons easier to tap
- simplify bottom action rows for thumb use

This applies to:

- add subscriber
- edit subscriber
- palugit form
- disconnect form
- deceased form
- archive-related confirmation flows

## Screen-by-Screen Discussion Notes

### `/subscribers/`

Recommended mobile approach:

- mobile cards instead of full-width dense table
- visible and obvious `View` action
- stacked filters
- simpler action bar hierarchy

### `/subscribers/<id>/`

Recommended mobile approach:

- stacked header
- wrapped quick actions
- horizontally scrollable or compact tabs
- one-column info sections
- no true right sidebar on phones

### `/subscribers/add/`

Recommended mobile approach:

- one-column form
- full-width or dominant primary submit button
- lower visual weight for cancel action

### `/subscribers/<id>/edit/`

Recommended mobile approach:

- one-column form
- preserve current data model and admin workflow
- improve spacing, readability, and tap comfort

### Status-action pages

Recommended mobile approach:

- simple stacked forms
- strong confirm action
- readable summary context about which subscriber is being changed

## Recommended Rollout Order

The lowest-risk and highest-value sequence is:

1. responsive admin shell
2. mobile-friendly subscribers list
3. mobile-friendly subscriber detail page
4. mobile-friendly add/edit and status forms
5. optional later refinement for billing/history mobile cards

## What Is Not Recommended

The discussion also narrowed down several approaches that are not recommended as the primary solution:

- forcing the current subscriber table to remain the only mobile layout
- relying only on clipped table overflow
- hiding important actions in tiny low-visibility links
- keeping the detail right sidebar as a sidebar on phones
- trying to solve the problem as a backend or route issue

## Current Status

Current status after discussion:

- issue confirmed
- root cause identified as responsive UI/layout design
- no implementation started yet
- this document exists to preserve decision history before coding

## Next Step

The next step, when approved, should be implementation planning and template refactor work for the responsive admin shell and the `/subscribers/` mobile experience.
