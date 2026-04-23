# Premium NMS Exact UI Boundary

## Summary

This document defines the exact UI and workflow boundary between the core `Subscribers` module and the premium `NMS / Topology` workspace.

The goal is to keep the product operationally clear:

- `Subscribers` remains the source of truth for customer identity, billing, plan, rate, and lifecycle state
- `Premium NMS` becomes the source of truth for physical network visibility, service attachment, route, port, PLC, and topology mapping

This means enabling premium NMS should not remove the subscriber workflow.
Instead, it should add a second specialized workspace for network operations.

## Core Rule

The UI must answer two different questions in two different places:

- `Subscribers`: who is the customer and what is the account or billing state
- `NMS`: where and how is the customer physically connected

If this boundary is blurred, staff will eventually update the wrong thing in the wrong page and the product will become harder to trust.

## Product Boundary

### What the `Subscribers` Module Owns

The `Subscribers` module remains the primary workspace for:

- customer creation
- plan selection
- monthly rate
- billing effective date
- cutoff or due overrides
- account status
- notes
- invoices
- payments
- lifecycle actions such as suspend, reconnect, disconnect, deceased, archive

This page must stay reliable even when premium NMS is disabled.

### What Premium `NMS / Topology` Owns

The premium NMS workspace owns:

- map visibility
- topology view
- node-to-node connectivity
- service attachment
- ports and endpoints
- PLC mapping
- FBT mapping
- cable and core usage
- route geometry
- assignment validation
- reassignment workflow

This is where advanced physical network logic belongs.

## Exact UI Boundary

### 1. Subscriber List Page

The subscriber list remains part of the `Subscribers` module.

Recommended columns:

- subscriber name
- username
- plan
- status
- billing state or open balance summary
- node summary
- topology summary
- action buttons

Recommended network-related display:

- `Node`: short summary only, such as `NAP-01`
- `Topology`: `Unassigned`, `Basic Node Only`, `Mapped`, or `Needs Review`

Recommended actions:

- always show `View Subscriber`
- when premium NMS is enabled:
  - show `Open in NMS`
- when subscriber is unassigned and premium is enabled:
  - optionally show `Assign in NMS`

What should not happen on the list page:

- no PLC editing
- no route editing
- no core assignment
- no advanced reassignment from the list row

### 2. Subscriber Detail Page

The subscriber detail page remains the account-control page.

Recommended sections that stay here:

- subscriber profile
- plan and rate
- billing settings
- invoice history
- payment history
- usage summary
- account status actions

Recommended network section when premium NMS is disabled:

- current node summary
- simple connect or disconnect to basic node if supported by the core product

Recommended network section when premium NMS is enabled:

- connected node summary
- current endpoint summary
- topology status
- last mapped or assigned state if helpful

Recommended buttons when premium NMS is enabled:

- `Open in NMS`
- `View Topology`
- `Assign in NMS` when unassigned
- `Reassign in NMS` when an active topology attachment exists

What should not be editable here when premium NMS is enabled:

- PLC output selection
- FBT routing
- cable or core assignment
- route or path geometry
- multi-hop topology mapping

The subscriber detail page should show network truth as a summary, not as a second full editor.

### 3. Subscriber Edit Page

The subscriber edit page stays focused on account and billing information.

Recommended editable fields:

- full name
- phone
- email
- address
- latitude and longitude if subscriber location is still tracked there
- billing effective date
- cutoff override
- due offset override
- billable flag
- notes
- lifecycle-safe status options

Recommended behavior when premium NMS is enabled:

- do not turn this form into a topology editor
- if basic node association still exists, treat it as summary-only or starter-only behavior
- do not allow this page to overwrite an existing premium service attachment directly

### 4. Premium NMS Workspace

Premium NMS becomes the network-operations workspace.

Recommended top-level areas:

- topology map workspace
- node and asset inventory
- links and cables
- distribution or passive device management
- assignment workspace
- validation or alerts page

Recommended NMS responsibilities:

- visualize the physical path
- choose source endpoint
- assign subscriber to endpoint
- build or edit route geometry
- validate occupancy and eligibility
- handle reassignment safely

This is where the user should do real topology work.

## Button and State Logic

The UI should change based on subscriber state and premium availability.

### State A: Premium Disabled

Subscriber list:

- show node summary if basic node link exists
- no premium NMS buttons

Subscriber detail:

- allow simple node reference or basic node connect if the core product supports it
- no topology editor

### State B: Premium Enabled, Subscriber Unassigned

Subscriber list:

- show topology status as `Unassigned`
- show `Open in NMS`
- optionally show `Assign in NMS`

Subscriber detail:

- show node summary if one exists
- show network status as `Unassigned`
- primary action becomes `Assign in NMS`

NMS:

- subscriber appears in eligible unassigned pool
- valid endpoints appear in assignable pool

### State C: Premium Enabled, Basic Node Only

This is the transitional state where a subscriber may have a basic node reference but no full premium attachment yet.

Subscriber list:

- show node summary
- show topology status as `Basic Node Only`
- show `Open in NMS`

Subscriber detail:

- show current node summary
- show action `Promote to NMS Mapping`

NMS:

- staff selects endpoint, path, and attachment details
- once saved, status becomes `Mapped`

### State D: Premium Enabled, Fully Mapped

Subscriber list:

- show node summary
- show topology status as `Mapped`
- show `Open in NMS`

Subscriber detail:

- show connected node
- show endpoint summary
- show `View Topology`
- show `Reassign in NMS`

NMS:

- current active attachment is visible
- endpoint is marked occupied
- subscriber no longer appears in generic unassigned pools

### State E: Premium Enabled, Needs Review

This is used when topology data is incomplete or has a validation warning.

Examples:

- endpoint missing
- attachment broken
- mapped node no longer valid
- dependency removed

Subscriber list:

- topology status becomes `Needs Review`
- show `Open in NMS`

Subscriber detail:

- show warning summary
- show `Resolve in NMS`

NMS:

- validation warning appears in assignment or alerts view

## Quick Connect to Node Behavior

This is the most important boundary rule because it is where the core product can accidentally bypass premium topology rules.

### Recommended Rule

- if premium NMS is disabled, the basic node connection may stay editable
- if premium NMS is enabled but no premium attachment exists yet, the basic node connection may be used only as a starter association
- if a premium service attachment already exists, the basic node connection must not overwrite it directly

At that point, the subscriber-side node action should become:

- read-only summary, or
- a redirect or shortcut to `Reassign in NMS`

### Why This Rule Matters

Without this rule, staff could:

- change the node on the subscriber page
- leave the premium endpoint assignment unchanged
- create mismatched account and topology state

That would break trust in both pages.

## Exact Workflow Steps

### Workflow 1: Create Subscriber Without Premium NMS

1. CSR opens `Subscribers`.
2. CSR creates a new subscriber.
3. CSR fills in plan, rate, billing dates, and status.
4. CSR optionally links a simple node reference.
5. Subscriber is now operational for billing and account workflows.

Result:

- subscriber is active in the core platform
- no premium topology mapping is required

### Workflow 2: Create Subscriber With Premium NMS Enabled

1. CSR opens `Subscribers`.
2. CSR creates the subscriber record first.
3. CSR saves plan, rate, billing settings, and account status.
4. Subscriber detail shows network status as `Unassigned`.
5. CSR or NOC clicks `Assign in NMS`.
6. NMS opens the subscriber-specific assignment flow.
7. Staff chooses the serving node, endpoint, and route.
8. NMS saves the service attachment.
9. Endpoint becomes occupied.
10. Subscriber detail now shows topology status as `Mapped`.

Result:

- subscriber truth remains in `Subscribers`
- physical assignment truth now lives in `NMS`

### Workflow 3: Promote Basic Node to Full Premium Mapping

1. Subscriber already exists with only a basic node summary such as `NAP-01`.
2. Premium NMS is enabled later.
3. Subscriber detail shows topology status as `Basic Node Only`.
4. Staff clicks `Promote to NMS Mapping`.
5. NMS opens with the node context preselected if possible.
6. Staff selects the real endpoint, port, PLC output, and path.
7. NMS creates the full `ServiceAttachment`.
8. Subscriber status becomes `Mapped`.

Result:

- no billing truth changes
- the basic node reference evolves into a full premium topology attachment

### Workflow 4: View Mapped Subscriber

1. NOC opens `Subscribers`.
2. NOC opens subscriber detail.
3. The page shows:
   - node summary
   - endpoint summary
   - topology state
4. NOC clicks `View Topology`.
5. NMS opens the map and highlights the current path.

Result:

- subscriber page stays clean
- network tracing happens in the correct workspace

### Workflow 5: Reassign Subscriber

1. NOC opens subscriber detail.
2. NOC clicks `Reassign in NMS`.
3. NMS loads the current attachment.
4. NMS shows the current endpoint as occupied by that subscriber.
5. NOC selects a new valid endpoint.
6. NMS validates:
   - endpoint availability
   - one active physical path rule
   - topology consistency
7. NMS replaces the old active attachment.
8. Old endpoint becomes available again.
9. New endpoint becomes occupied.
10. Subscriber detail now reflects the new summary.

Result:

- reassignment happens in one place
- subscriber page remains an account summary surface

### Workflow 6: Handle Validation Issue

1. Subscriber shows topology status as `Needs Review`.
2. Staff opens `Resolve in NMS`.
3. NMS shows the exact problem:
   - missing endpoint
   - broken node
   - invalid route
   - stale attachment
4. Staff fixes the topology data.
5. Validation clears.
6. Subscriber detail returns to `Mapped` or another valid state.

Result:

- warnings stay visible on the subscriber side
- repair happens in the NMS side

## Recommended Labels and Actions

Keep labels direct and role-friendly.

Recommended subscriber-side labels:

- `Open in NMS`
- `Assign in NMS`
- `View Topology`
- `Reassign in NMS`
- `Resolve in NMS`

Recommended topology status labels:

- `Unassigned`
- `Basic Node Only`
- `Mapped`
- `Needs Review`

## Permissions and Roles

Recommended role behavior:

- `CSR`: create and edit subscribers, view network summary, optionally trigger `Assign in NMS` if allowed
- `NOC`: full use of premium NMS mapping and reassignment actions
- `Finance`: access subscriber billing state but no topology editing
- `Admin`: full access to both layers

This keeps ownership clean across teams.

## Recommended Final UI Principle

The safest long-term UI design is:

- `Subscribers` is always the account workspace
- `NMS` is always the physical topology workspace
- the subscriber page shows the current network summary
- the NMS page performs the real network changes

If the product follows that rule consistently, premium NMS can become powerful without destabilizing the core subscriber and billing workflows.
