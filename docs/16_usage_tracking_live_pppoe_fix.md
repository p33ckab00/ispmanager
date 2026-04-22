# Usage Tracking Live PPPoE Interface Fix

## Summary
This follow-up change completes the subscriber usage repair by switching the sampler to a live RouterOS source that actually exposes per-subscriber counters.

## Root Cause Found
The router did not return `bytes-in` and `bytes-out` counters from `/ppp/active`, so subscriber usage samples were being stored with zero values even though active sessions existed.

Observed live payload behavior:
- `/ppp/active` returned session identity and uptime data only.
- Dynamic PPPoE interfaces under `/interface` exposed the real counters:
  - `rx-byte`
  - `tx-byte`
  - `rx-packet`
  - `tx-packet`
- PPPoE interface names used the pattern `\<pppoe-USERNAME\>`.

## Change Implemented

### 1. Dynamic PPPoE Interface Stats Fallback
Added a RouterOS helper that reads `/interface print stats` and maps dynamic `pppoe-in` interfaces back to subscriber usernames.

Files:
- `apps/routers/mikrotik.py`
- `apps/subscribers/services.py`

### 2. Subscriber Usage Sampler Updated
The usage sampler now:
- pulls active PPP sessions
- loads dynamic PPPoE interface stats for the same router
- resolves per-subscriber counters from interface stats when PPP active counters are missing
- keeps session-aware delta handling

Files:
- `apps/subscribers/services.py`

## Validation Result
Live verification after the fix showed:
- non-zero `SubscriberUsageSample` rows
- non-zero `SubscriberUsageDaily` rows
- `get_usage_chart_data(..., 'this_cycle')` returning `has_data = True`

Example verified outcomes:
- `LitoYamb` had non-zero `rx_bytes` and `tx_bytes`
- multiple subscribers produced non-zero daily totals for the current date
- usage chart payloads contained non-zero RX/TX values

## Operational Impact
Subscriber usage charts should now start reflecting real traffic for active PPPoE users on routers that expose dynamic PPPoE interface stats.

## Remaining Note
This solution depends on the target router continuing to expose per-session counters via dynamic `/interface` rows. If another router model or RouterOS version behaves differently, a device-specific collector fallback may still be needed.
