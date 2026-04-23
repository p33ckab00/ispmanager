# Subscribers Mobile Admin / Topology Workspace Discussion

## Summary

This discussion defines the recommended direction for the next-generation network topology workspace.

The most important principle is simple:

The map must not become only a drawing tool.
It should be the visual layer of a structured network inventory, topology, and provisioning engine.

That architecture keeps the system scalable as the product grows from a simple router-and-subscriber map into a real operational workspace for fiber distribution, assignment rules, and future network analysis.

This also gives the mobile-admin discussion a better foundation.
Instead of overloading the map itself with all business logic, the system should separate:

- physical assets
- connectivity
- passive distribution
- path geometry
- subscriber or service assignment rules

## Why This Direction Matters

The current project already has a simple network map and a lightweight subscriber-to-node assignment model.

That is a useful starting point, but it is not yet enough for a production-grade topology workspace because:

- the map currently behaves more like a viewer than an inventory engine
- subscriber assignment logic is still lightweight
- passive devices such as PLC and FBT are not yet modeled as structured distribution components
- path geometry and cable or core usage are not yet first-class operational objects

If the product keeps adding map features without first defining the underlying topology model, the result will become harder to validate, harder to extend, and easier to break.

The safer long-term direction is:

- generic topology engine first
- type-specific configuration second
- visual map workspace as the operating surface, not the source of truth by itself

## Core Principle

The system should separate four concerns clearly:

- `Node`: the physical object
- `Link`: the physical or logical connection
- `Config`: the behavior and capacity attached to a node, device, port, or cable
- `Assignment`: the actual usage of a resource by a subscriber or service

This avoids mixing map drawing, inventory data, and provisioning rules into one layer.

## Five Major Layers

### 1. Asset Inventory

This layer stores real physical objects in the network.

Examples:

- routers
- OLTs
- NAP boxes
- cabinets
- poles
- splice boxes
- patch panels
- access points
- PisoWifi devices
- subscriber endpoints

This is the inventory truth for what exists in the field.

### 2. Topology / Connectivity

This layer describes how assets are connected.

It should model:

- source and destination endpoints
- connection type
- path geometry
- parent-child containment where needed

Examples:

- router to OLT
- OLT to NAP
- NAP to downstream NAP
- AP uplink to router
- subscriber drop from distribution point

### 3. Fiber Capacity and Split Modeling

This layer adds structured optical distribution behavior.

It should model:

- cable core counts
- per-core status
- FBT ratios
- PLC types
- used versus available outputs
- pass-through versus split behavior

This is what allows the product to enforce real eligibility rules instead of just storing free-text notes.

### 4. Map and Path Editor

This layer is the visual workspace.

It should support:

- adding nodes by map click
- connecting assets
- editing link geometry
- viewing layers
- showing status and utilization

The map should be a strong operational interface, but not the only place where detailed technical configuration happens.

### 5. Provisioning and Subscriber Assignment Rules

This layer controls actual service usage.

It should govern:

- which endpoints are assignable
- which subscribers are still unlinked
- which PLC outputs are occupied
- which cable cores are already in use
- whether a subscriber may hold more than one active access path

This is the layer that prevents already-linked resources from appearing in assignment flows where they no longer belong.

## Recommended Domain Model

### `Area`

A first-class service area or site container.

Purpose:

- group nodes and links by operational area
- support future multi-area filtering
- avoid a permanently flat topology

### `Node`

The main physical object on the topology map.

Examples:

- router
- OLT
- NAP
- cabinet
- splice box
- access point
- PisoWifi node
- subscriber point

Recommended responsibilities:

- coordinates
- type
- status
- notes
- optional reference to an existing equipment record such as `Router`

### `Port`

A connection point on a node.

Examples:

- router interface
- OLT uplink port
- OLT PON port
- AP uplink
- NAP-facing access endpoint

Ports should control where connections are actually terminated instead of relying only on loose node-to-node links.

### `InternalDevice`

A structured device that lives inside another node.

Examples:

- PLC splitter
- FBT splitter
- splice tray
- patch panel

These should usually appear inside a node detail view, not always as default standalone map objects.

### `Link`

A connection between two endpoints.

Supported examples:

- fiber
- ethernet
- wireless backhaul
- subscriber drop

Each link should know:

- source endpoint
- destination endpoint
- type
- status
- related geometry
- related cable inventory if applicable

### `Geometry`

The ordered list of path vertices for a link.

This should stay separate from link metadata.

Important rule:

- start point follows source node coordinates
- end point follows destination node coordinates
- only the middle vertices are freely editable

That keeps the route stable even when nodes move.

### `Cable`

A cable inventory record attached to a link.

Recommended fields:

- cable name or code
- total cores
- length
- installed status
- aerial or underground classification
- install date

### `Core`

A per-core record inside a cable.

Recommended responsibilities:

- color label
- used or spare state
- assignment notes
- endpoint mapping

This allows core-level validation and utilization reporting.

### `ServiceAttachment`

The binding between a subscriber and an access endpoint.

This is the core service-assignment object.

For the first serious release, the recommended rule is:

- one subscriber may have only one active physical access path at a time

This keeps provisioning safe and understandable while still allowing future expansion if backup-link behavior is ever added later.

### Validation / Rules Layer

This layer should not be treated as an afterthought.

It should explicitly check things such as:

- duplicate endpoint assignment
- duplicate cable core use
- exceeded cable capacity
- invalid device-to-device connections
- destructive deletes with active dependencies
- broken or inconsistent path data

## Recommended Page Architecture

The product should not force everything into one full-screen map page.

The best structure is a map-centered workspace plus dedicated detail pages for complex operations.

### 1. Map-Centered Topology Workspace

This is the main operational page.

Recommended layout:

- left panel: area tree, asset tree, and layer filters
- center: map canvas
- right panel: selected object inspector
- optional bottom tray: path coordinates, warnings, or assignment lists

Recommended toolbar modes:

- View
- Add Node
- Connect
- Edit Path
- Splitter
- Fiber Core
- Assignment
- GPS
- Layers

### 2. Assets / Nodes Page

A table-and-form page for structured inventory management.

Recommended content:

- node list
- filters by area and type
- creation and edit flows
- detail fields such as coordinates, model, notes, and installation status

### 3. Links / Cable Page

A dedicated inventory page for connectivity and cable tracking.

Recommended content:

- links list
- cable inventory
- source and destination endpoints
- core count
- utilization
- route length
- geometry edit entry points

### 4. Distribution Page

A dedicated page for internal passive distribution inside NAPs, closures, and cabinets.

Recommended content:

- incoming fibers
- splice mapping
- FBT configuration
- PLC configuration
- output availability
- served subscribers

This is where passive optical logic belongs.
It should not be forced entirely into the main map.

### 5. Subscriber Assignment Page

A dedicated provisioning page.

Recommended content:

- eligible subscribers
- eligible endpoints
- attach or unlink actions
- drop-link creation
- endpoint occupancy state

This page should use business rules to show only valid candidates.

### 6. Validation / Alerts Page

A central place for conflicts and operational warnings.

Recommended examples:

- duplicate assignments
- exhausted PLC outputs
- duplicate core allocations
- invalid topology combinations
- links or nodes with broken dependencies

## Recommended Product Boundary

The current `Subscribers` module should remain the system of record for subscriber identity, billing, payment relationships, lifecycle status, and plan or rate data.

That module is already operationally meaningful and should stay stable.

Recommended ownership split:

- `Subscribers` owns the customer account truth
- `NMS / Topology` owns the physical network visibility and advanced assignment truth

That means the product should work in two layers.

### Core Platform Layer

This is the non-premium operational base.

Recommended behavior:

- create and edit subscribers in the `Subscribers` module
- keep plan, billing settings, monthly rate, and lifecycle states there
- keep the existing simple node connection or node visibility there
- allow staff to see a basic node reference in subscriber listings and subscriber detail views

This keeps billing and account operations stable even if the customer does not use premium NMS features.

### Premium NMS Layer

This is the advanced operational add-on.

Recommended behavior:

- add full map visibility
- add path geometry
- add ports and endpoints
- add PLC and FBT logic
- add cable and core usage
- add topology validation
- add advanced assignment rules

The premium layer should extend the subscriber experience, not replace the subscriber record itself.

## Recommended Ownership Model

To keep the architecture clean:

- do not duplicate billing truth inside NMS
- do not duplicate subscriber lifecycle state inside NMS
- do not make billing depend on NMS being enabled

Recommended relationship:

- `Subscriber` remains the master customer record
- `ServiceAttachment` in NMS points to `Subscriber`
- the subscriber page shows a summary of the current physical assignment
- the full assignment is edited inside premium NMS workflows

In simple terms:

- the subscriber exists because of the `Subscribers` module
- the physical path exists because of the `NMS / Topology` module

## Recommended UI Behavior Between Subscribers and NMS

The subscriber module should stay simple and operationally safe.

Recommended subscriber-side behavior:

- show current node summary
- show connection or assignment status
- optionally show current endpoint label or current port label
- provide a shortcut into the advanced NMS view when premium features are enabled

Do not force the subscriber page to become the place where staff edit:

- full PLC logic
- full FBT behavior
- path geometry
- cable or core allocation
- multi-hop topology mapping

Those advanced actions belong in the premium NMS workspace.

## When Premium NMS Is Enabled

Enabling premium NMS should not remove or replace the `Subscribers` page.

Instead, the product should become a two-workspace system:

- `Subscribers` remains the customer account and billing workspace
- `NMS / Topology` becomes the physical network and mapping workspace

This is the simplest mental model for staff:

- `Subscribers` answers: who is the customer, what is the plan, what is the billing state
- `NMS` answers: where is the customer connected, through which path, port, PLC, or node

### What Stays in the `Subscribers` Page

The `Subscribers` page should remain the default workflow for:

- customer creation
- plan changes
- rate changes
- billing settings
- status changes
- notes
- invoice and payment-related actions

This is important because the `Subscribers` module remains the source of truth for account and billing behavior.

### What Changes in the `Subscribers` Page

When premium NMS is enabled, the network-related part of the subscriber page should become a summary and shortcut layer instead of a full network editor.

Recommended subscriber-page network view:

- connected node summary
- current assignment status
- current endpoint or port summary if available
- buttons such as:
  - `Open in NMS`
  - `View Topology`
  - `Reassign in NMS`

### What Moves to the NMS Workspace

When premium NMS is enabled, these advanced actions should happen only in the NMS workspace:

- path and route editing
- PLC mapping
- FBT logic
- cable and core allocation
- endpoint occupancy control
- multi-hop physical topology assignment

That keeps the subscriber page clean while still giving NOC or installers a direct path into the advanced workspace.

### Rule for Basic Node Connection

The existing basic node connection in the subscriber workflow can still exist as a lightweight summary or starter association.

Recommended rule:

- if no advanced topology attachment exists yet, a basic node association may still be used
- if an active premium topology attachment already exists, the subscriber page should no longer directly overwrite it

At that point, the subscriber page should become:

- read-only summary for network attachment, or
- a shortcut into the NMS reassignment flow

This prevents the simple subscriber-side node action from bypassing premium topology rules.

## Concrete User Flows

These flows show how the product should behave in daily use while keeping `Subscribers` as source of truth and `NMS` as an optional premium layer.

### Example Subscriber

Use this example for the flows below:

- subscriber name: `Juan Dela Cruz`
- username: `juan01`
- plan: `50 Mbps Residential`
- current node summary: `NAP-01`

### CSR Flow

This is the everyday customer-account workflow.

1. CSR opens the `Subscribers` module.
2. CSR creates or edits `Juan Dela Cruz`.
3. CSR sets:
   - contact information
   - plan
   - monthly rate
   - billing effective date
   - account status
4. If the operation only needs a simple infrastructure reference, CSR connects the subscriber to a node such as `NAP-01`.
5. Subscriber listing still shows the node reference as part of the normal account workflow.
6. Billing, invoices, payments, and status logic continue to read only from the `Subscribers` module.

Simple meaning:

- the customer can exist and be billed even without premium NMS
- the node reference is visible, but it is still only a basic operational summary

### NOC Flow

This is the network-operations workflow without needing full premium topology editing every time.

1. NOC opens the subscriber detail page.
2. NOC sees a short network summary such as:
   - connected node: `NAP-01`
   - assignment status: `Active`
   - endpoint summary if available
3. If the issue is simple, NOC can use that summary to identify where the subscriber is currently associated.
4. If the issue needs detailed tracing, NOC opens the premium NMS view from the subscriber page.
5. NOC checks the physical path, endpoint, and node chain there instead of editing advanced topology data directly inside the subscriber form.

Simple meaning:

- subscriber pages remain readable
- NOC can still jump to the advanced network context when needed

### Premium NMS Flow

This is the advanced mapping and provisioning workflow.

1. Subscriber `Juan Dela Cruz` is already created in `Subscribers`.
2. Staff opens the premium NMS workspace from the subscriber detail page or from the topology workspace.
3. NMS loads the subscriber by `subscriber_id`.
4. Staff selects the physical serving path, for example:
   - `OLT-01`
   - `NAP-01`
   - `PLC 1x8`
   - `Port 3`
5. Staff creates or confirms the `ServiceAttachment`.
6. NMS marks the chosen endpoint as occupied.
7. NMS removes `Juan Dela Cruz` from other unassigned endpoint pools because the subscriber is already linked.
8. NMS updates the subscriber-facing summary so the subscriber page now shows the latest connection status and node or endpoint summary.

Simple meaning:

- the advanced topology is edited in NMS
- the subscriber record remains the same billing and account source of truth
- the subscriber page receives a summary, not the full topology editor

### Reassignment Flow

This is the workflow when a subscriber must move to another endpoint.

1. NOC opens the premium NMS assignment view for `Juan Dela Cruz`.
2. NOC sees the current active attachment, for example `NAP-01 -> PLC Port 3`.
3. NOC selects a new valid endpoint.
4. NMS checks that:
   - the new endpoint is available
   - the subscriber is allowed only one active physical path
5. NMS unlinks or replaces the old active attachment.
6. The old endpoint becomes available again.
7. The new endpoint becomes occupied.
8. The subscriber summary in the `Subscribers` module refreshes to reflect the new topology attachment.

Simple meaning:

- reassignment happens in NMS
- subscriber truth remains intact
- endpoint availability stays correct automatically

### No-Premium Workflow

This is the expected behavior when premium NMS is not enabled.

1. Staff still creates the subscriber in `Subscribers`.
2. Staff still manages billing, plan, and status there.
3. Staff may still connect the subscriber to a basic node reference.
4. The system does not require path editing, PLC mapping, or cable-core logic.
5. The ISP can continue running billing and customer operations normally.

Simple meaning:

- the core product is still complete enough for non-premium use
- premium NMS adds network depth and visibility, not billing ownership

## Core Workflows

### Workflow A: Add Infrastructure

1. Add a node on the map.
2. Choose the node type and auto-fill coordinates from the click location.
3. Save the node record.
4. Add another node such as an OLT, NAP, or cabinet.
5. Connect the two nodes.
6. Choose the connection type.
7. If the link is fiber, define cable and core information.
8. Open the detail or distribution view when the node contains passive internals.
9. Add PLC, FBT, or splice components if needed.
10. Save the topology and capacity state.

### Workflow B: Add Subscriber

1. Add or confirm the subscriber location.
2. Open the assignment workflow.
3. Show only valid, eligible endpoints.
4. Select the source endpoint.
5. Create the service attachment.
6. Create or confirm the subscriber drop link if needed.
7. Mark the endpoint as occupied.
8. Remove the subscriber from other unassigned pools automatically.

### Workflow C: Edit Path Geometry

1. Select a link.
2. Open path editing mode.
3. Add a vertex by clicking on the line.
4. Drag existing vertices.
5. Delete a vertex when needed.
6. Optionally edit coordinates manually.
7. Optionally import or capture GPS points later.
8. Save the geometry without breaking the source and destination anchors.

## Key Business Rules

These rules should be explicit and enforced in the data model and service layer.

### One Active Physical Access Path Per Subscriber

For the first serious topology release:

- a subscriber can have zero or one active physical access path
- reassigning requires unlinking or replacing the existing active attachment

### Linked Subscribers Should Not Reappear as Unassigned

Once a subscriber already has an active `ServiceAttachment`:

- do not show that subscriber in generic unassigned pools
- only show them again if the attachment is removed, archived, or marked inactive

### Occupied Endpoints Should Not Reappear as Available

If a PLC output, splitter output, or equivalent endpoint is already linked:

- mark it as occupied
- exclude it from available endpoint lists by default

### Occupied Cores Should Not Reappear as Spare

If a cable core is already used for a segment or mapped service:

- it must not be shown as spare
- duplicate allocation should be blocked by validation

### Geometry Should Stay Stable When Nodes Move

When a node coordinate changes:

- connected link start or end anchors update automatically
- the middle vertices remain intact

This avoids destroying carefully edited route geometry every time a device position is corrected.

## UX Notes for the Workspace

The map should use explicit modes rather than one all-purpose cursor behavior.

Recommended modes:

- view mode
- add node mode
- connect mode
- edit path mode
- assign subscriber mode
- fiber core visualization mode

The default map should stay readable.

Recommended behavior:

- show one main cable line by default
- show utilization badges or summaries
- expose core-by-core detail in the inspector or advanced mode

Internal passive devices such as PLC and FBT should normally live in node detail views instead of always cluttering the main geographic map.

## Phased Rollout

### Phase 1: Basic Topology Workspace

Focus on:

- add nodes
- set coordinates
- connect nodes
- add and edit path vertices
- basic link typing
- basic fiber cable and core count data

### Phase 2: PLC and Assignment

Focus on:

- structured node ports
- NAP or cabinet internals
- PLC device modeling
- subscriber assignment lock and unlock behavior

### Phase 3: FBT and Validation

Focus on:

- FBT ratio modeling
- core-level allocation rules
- validation engine
- richer eligibility filtering

### Phase 4: GPS, Analytics, and Budgeting

Focus on:

- GPS capture or import
- power budget estimation
- route analytics
- outage impact tracing

## Migration Note

The existing `NetworkNode` and `SubscriberNode` models should be treated as legacy bridge structures, not the final long-term topology design.

Recommended migration direction:

- keep current lightweight assignment behavior working during transition
- introduce a cleaner dedicated topology domain for `Area`, `Node`, `Link`, `Cable`, `Core`, and `ServiceAttachment`
- backfill or migrate legacy assignment data into the new model
- retire direct dependency on the legacy bridge models once topology parity is achieved

This keeps current operations intact while allowing the system to grow into a real topology engine instead of a map with scattered side logic.

## Final Direction

The strongest long-term design for this product is:

- generic topology engine
- structured inventory and distribution data
- rule-based provisioning and validation
- map-centered workspace for visibility and editing
- dedicated detail pages for complex technical configuration

That direction will scale better than hardcoding most logic into one map page or one device-specific screen at a time.

It also creates a cleaner foundation for future expansion into:

- deeper FTTH workflows
- wireless backhaul visualization
- direct ONU or port mapping
- richer outage analysis
- power-budget and route-analysis features

The map should remain important, but the system should treat it as the operating surface of a topology platform, not the topology platform itself.
