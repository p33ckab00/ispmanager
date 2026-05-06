# Past-Due Captive Portal Future Plan

## Purpose

This document records the future plan for an optional past-due captive billing
portal.

The feature is intended for overdue PPPoE clients who should still stay
connected enough to see a billing reminder, contact support, and open the ISP
Manager account portal. It is not intended to replace normal suspension,
payment posting, or the existing palugit workflow.

This is a planning document only. No production behavior is implemented by this
document.

## Product Goal

Add a service-enforcement state between `active` and `suspended`:

- the subscriber remains `active`
- the billing state is overdue or past due
- the subscriber is temporarily placed in a captive reminder environment
- the subscriber can reach ISP Manager billing and portal pages
- the subscriber is not fully suspended unless an admin chooses to suspend them

The feature should be optional because not every past-due client should be
captured automatically.

## Admin Modes

Past-due captive mode should have a global mode:

- `Off` - do not apply new captive enforcement
- `Monitor only` - detect eligible past-due clients, but do not change MikroTik
- `Auto enforce` - automatically apply captive mode to eligible clients

Turning the feature off should stop new enforcement. It should not silently
release clients that are already in captive mode. Existing captive clients
should be released by explicit admin action.

## Per-Client Controls

Each subscriber should have a captive preference:

- `auto` - eligible for automatic captive mode when global mode allows it
- `manual only` - visible as eligible, but only staff can apply captive mode
- `never captive` - excluded from automatic and bulk captive actions

Palugit remains separate. An active palugit hold should always prevent
automatic captive enforcement.

## MikroTik Provisioning

The system should provision the RB5009 through RouterOS API only. SSH should not
be required.

Provisioning should be explicit, through a router-level button such as:

- `Check Captive Setup`
- `Provision Captive Setup`
- `Rollback Captive Setup`

Provisioning must create or update only ISPManager-owned objects. Every object
created by the system should have a strong ownership tag in its MikroTik
comment, for example:

```text
ISPManager PastDue Captive owner=<router_id> key=<object_key>
```

Planned ISPManager-owned objects:

- PastDue PPP profile
- PastDue address-list
- firewall filter rules for captive clients
- DNS redirect or force-DNS NAT rules
- HTTP captive redirect NAT rule
- allow rules for the local ISP Manager captive portal IP or domain

RouterOS `/system/script` objects are out of scope for v1.

## Rollback Safety

Rollback must be surgical.

The system should store a local provisioning manifest for every router. The
manifest should track:

- RouterOS path or object type
- intended object name
- ownership tag
- RouterOS `.id` when known
- provisioned timestamp
- last verified timestamp
- last error

Rollback should delete only objects that are both:

- present in the ISP Manager manifest
- still tagged as ISPManager-owned on the router

Rollback must never delete untagged objects, even if they have the same name as
an ISPManager object.

If an object with the planned name already exists but does not have the
ISPManager ownership tag, provisioning should stop with a conflict warning.
The system should not adopt or modify manual MikroTik objects automatically.

If active captive subscribers exist on a router, rollback should release those
subscribers first. If any release fails, rollback should stop before deleting
the shared captive setup.

If the original PPP profile stored for a subscriber no longer exists during
release, the system should restore the router's selected base PPP profile and
show a warning to the admin.

## Captive Enforcement Flow

When a client is placed in captive mode:

1. store the subscriber's original PPP profile
2. change the subscriber's PPP secret to the PastDue profile
3. disconnect the active PPPoE session so the new profile applies immediately
4. add the active client IP to the PastDue address-list when available
5. record the enforcement state and any RouterOS warnings

When a client is released:

1. restore the original PPP profile, or the configured base profile if the
   original no longer exists
2. remove the client's PastDue address-list entries
3. disconnect the active PPPoE session so normal access applies immediately
4. clear captive state
5. record audit history

Full payment can release captive mode automatically when that setting is
enabled. Partial payment should keep the client captive unless staff manually
releases them.

## Firewall And DNS Defaults

The planned rule placement is:

- after established/related accept rules
- before broad client allow or drop policy where possible

DNS should be forced to the router or local resolver while a client is captive.
This makes captive detection more reliable than allowing arbitrary public DNS.

For PPPoE clients, the term "walled garden" means firewall allowlist behavior.
It does not mean MikroTik Hotspot `/ip/hotspot/walled-garden` objects in v1.

## Captive Portal Page

The portal should be hosted by ISP Manager on a local IP or local domain that is
reachable from subscriber traffic.

The page should identify the subscriber by source IP when possible. If the
source IP cannot be matched reliably, it should fall back to OTP or account
lookup.

The page should show:

- subscriber account name and username
- overdue invoices
- total amount due
- due dates
- payment instructions
- support contact
- link to the normal subscriber portal

The page should be read-only in v1. Actual payment recording remains an admin
workflow unless a future online payment integration is added.

## HTTPS Limitation

Captive portal behavior cannot cleanly redirect arbitrary HTTPS sites.

If a client opens `https://example.com`, the browser expects a certificate for
`example.com`. Redirecting that request to the ISP Manager captive portal would
cause a certificate mismatch, privacy warning, or blocked page. This is a
normal HTTPS security boundary, even inside the ISP network.

The system can support:

- HTTP redirect
- device captive-detection prompts
- direct access to the local ISP Manager captive portal
- blocking most traffic except DNS and the portal

The system should not promise clean HTTPS interception or transparent HTTPS
redirection for all websites and apps.

## LibreQoS Boundary

ISP Manager should not modify LibreQoS files, services, or configuration for
this feature.

LibreQoS already has its own systemd-based sync/update workflow. Any speed or
client-shaping changes caused by MikroTik client/profile changes should remain
the responsibility of that existing LibreQoS process.

The past-due captive feature should focus only on:

- ISP Manager billing state
- ISP Manager captive page
- RouterOS API provisioning
- RouterOS API apply/release actions

## Safety Gaps To Revisit Before Implementation

Before implementation starts, verify:

- exact local captive portal IP or domain
- which router base PPP profile should be copied
- how the current RB5009 firewall chains are ordered
- whether client source IP reaches Django directly or through a local proxy
- how diagnostics should display router provisioning drift
- which staff permissions can provision, rollback, apply, and release captive

## Chosen Defaults

- v1 supports PPPoE only
- global mode defaults to `Off`
- per-client preference defaults to `auto`
- provisioning is manual per router
- rollback deletes only ISPManager-tagged manifest objects
- active PPPoE sessions are kicked after profile changes
- DNS is forced to router or local resolver
- same-name untagged MikroTik objects block provisioning
- missing original PPP profile falls back to selected base profile
- no RouterOS scripts in v1
- no LibreQoS changes
