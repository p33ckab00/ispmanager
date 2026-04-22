# Router Telemetry UX Upgrade

## Summary

This update improves the router ethernet port cards and interface live view so telemetry feels smoother, clearer, and closer to a real network operations panel.

The goal was not to increase direct polling pressure on MikroTik devices. Instead, the UI now uses the existing cached telemetry flow and adds richer derived states plus browser-side interpolation for a smoother operator experience.

## Main Changes

### Router detail port cards

The ethernet port cards on the router detail page now include:

- separate `Link` and `Activity` LED behavior
- richer visual card states for:
  - `linked-idle`
  - `low`
  - `medium`
  - `high`
  - `burst`
  - `stale`
  - `down`
  - `error`
- smoothed RX/TX value transitions
- RX and TX mini activity meters
- telemetry freshness text
- traffic direction label such as:
  - `Quiet line`
  - `Download-heavy`
  - `Upload-heavy`
  - `Balanced traffic`

### Interface live view

The single-interface live telemetry page now includes:

- smoothed RX/TX number transitions
- improved activity badge mapping
- direction summary
- richer state detail
- freshness-aware status text

## Technical Approach

### Keep cache-based telemetry as source of truth

The update still relies on `InterfaceTrafficCache` rather than direct browser-to-router polling.

This keeps the design safer for:

- router load
- Django stability
- future production deployment

### Add derived telemetry metadata

The router telemetry payload now includes derived fields such as:

- `activity_level`
- `display_state`
- `link_state`
- `traffic_direction`
- `rx_signal_percent`
- `tx_signal_percent`
- `stale_after_seconds`

These are computed in the service layer so the UI does not need to guess behavior independently.

### Use client-side interpolation

To make updates feel smoother without increasing backend pressure, the browser animates current values toward each new cached sample.

This gives a more continuous visual feel while keeping the actual sample cadence sane.

## Files Updated

- `apps/routers/services.py`
- `apps/routers/views.py`
- `apps/routers/api_views.py`
- `templates/routers/detail.html`
- `templates/routers/interface_detail.html`

## Validation

The following checks passed during implementation:

- `python manage.py check`
- router detail page rendered successfully
- interface detail page rendered successfully
- router live cache endpoint returned the richer telemetry payload
- interface live cache endpoint returned the richer telemetry payload

## Design Notes

This release focuses on `smoother and more readable` telemetry, not hardware-grade real-time streaming.

That means:

- better visual continuity
- better operational readability
- safer system behavior

without reintroducing aggressive direct router polling.

## Recommended Next Phase

Possible follow-up enhancements:

- filter ports by `active`, `down`, or `stale`
- sort ports by busiest first
- compact vs detailed card mode
- small per-port sparkline history
- later SSE/WebSocket-based push if true live streaming becomes necessary
