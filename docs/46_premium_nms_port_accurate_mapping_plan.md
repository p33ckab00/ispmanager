# Premium NMS Port-Accurate Mapping Plan

## Summary

This document captures the next Premium NMS implementation slice after the current
map, node, link, distribution, FBT, PLC, cable, core, GPS, and analytics
foundation.

The main gap is not basic visibility anymore. The remaining gap is
port-accurate flow mapping:

- a router with coordinates must behave as the root NMS node when no OLT,
  distribution box, or splice panel is modeled yet
- NAP, FBT, PLC, router ethernet ports, and subscriber drops need explicit
  input/output relationships
- subscriber assignments should connect to exact endpoints instead of only a
  general node
- the map should show shared physical paths and live/billing state clearly

This plan keeps the current Subscriber module behavior intact. Subscribers stay
the account and billing source of truth. Premium NMS becomes the physical
network truth.

## Decisions Locked

- Router node behavior: auto-create or auto-sync one system NMS root node per
  router that has coordinates.
- Port graph depth: implement explicit endpoint-to-endpoint connections.
- Subscriber assignment behavior: require an exact endpoint or router ethernet
  port for clean new assignments.
- Router interface eligibility: expose physical ethernet interfaces only by
  default.
- Telemetry source: use best available live data, preferring router interface
  traffic where mapped and falling back to subscriber MikroTik status.
- Billing ring source: use billing health, with overdue, open/partial/due soon,
  clear/ontime, and unknown/non-billable states.
- Subscriber UI entry point: upgrade the existing Subscriber detail assignment
  flow into an endpoint picker instead of replacing the Subscriber module.
- Existing node-only data: preserve it and show it as Needs Review until an
  exact endpoint is selected.

## Current Baseline

Premium NMS already has:

- router, subscriber, and network node markers on the map
- street and satellite map layers
- closer map zoom support for dense nodes
- topology links with editable vertices
- subscriber service attachment lines with editable vertices
- node delete behavior that removes NMS data under the node while preserving
  router, subscriber, billing, and account records
- internal devices for PLC, FBT, patch panel, splice tray, and other node
  internals
- PLC endpoint generation
- FBT endpoint generation with ratios from 95/5 down to 50/50
- cable and cable core inventory
- structured cable core assignments
- GPS trace import and map visibility
- operations validation and analytics foundation

The current model is still mostly node-centric at the flow level. It can show
that a subscriber is mapped to a node or endpoint, but it does not yet express
that router ether7 feeds NAP BOX 1 input, FBT 90/10 output feeds NAP BOX 2, and
FBT 10 output feeds PLC 1x8 input.

## Target Network Flow

### Router as Root Node

When an active router has latitude and longitude:

- Premium NMS must expose that router as a root topology node.
- The system root node should be tied to the router record.
- Moving router coordinates should update the root node coordinates.
- The root node should be visible on the NMS map and usable as the source for
  NAP, PLC, FBT, and direct subscriber links.

If the operator later adds OLT, distribution box, or splice panel nodes, those
nodes can be inserted between the router root and downstream NAPs without
deleting existing subscriber mappings.

### Router Interfaces as Endpoints

Router interfaces should become assignable endpoints when:

- the interface belongs to an active router
- `iface_type` is `ether`
- the interface is not dynamic
- the interface is not a slave port unless the operator explicitly enables it
  later

Default examples:

- router ethernet port feeding NAP BOX 1
- router ethernet port feeding a direct subscriber drop
- router ethernet port feeding an OLT or distribution node

Non-default examples that should not be exposed in v1:

- VLAN interfaces
- bridge interfaces
- PPPoE sessions
- WireGuard, ZeroTier, and loopback interfaces

### Endpoint Graph

Premium NMS should add a connection layer between endpoints.

Each endpoint connection should describe:

- upstream endpoint
- downstream endpoint
- connection type: fiber, ethernet, patch, splice, internal, or other
- status: active, planned, inactive, or damaged
- optional topology link when the connection crosses between physical nodes
- optional cable core when the connection uses a tracked fiber core
- optional notes

The graph direction should always flow from upstream network source to
downstream subscriber side:

`router port -> NAP input -> FBT input -> FBT output -> PLC input -> PLC output -> subscriber`

Connections must prevent invalid loops and should flag broken paths when an
active downstream endpoint has no upstream source.

## NAP, FBT, and PLC Behavior

### NAP Input

Each NAP should have at least one explicit input endpoint.

NAP BOX 1 can be connected directly to:

- router root node
- router ethernet port
- OLT output
- distribution box output
- splice panel output
- another NAP output

If no OLT, distribution box, or splice panel exists yet, the router root is the
valid upstream source.

### FBT 90/10 Example

For an FBT device with ratio `90/10`:

- `IN` receives the upstream main line.
- `PRIMARY 90%` continues the main/pass-through path.
- `SECONDARY 10%` feeds the local split path.

Example target flow:

`Router -> NAP BOX 1 input -> FBT IN`

Then:

`FBT PRIMARY 90% -> NAP BOX 2 input`

And:

`FBT SECONDARY 10% -> PLC 1x8 IN -> PLC outputs 1 to 8 -> subscribers`

The same rule applies to the supported ratios:

- 95/5
- 90/10
- 85/15
- 80/20
- 75/25
- 70/30
- 65/35
- 60/40
- 55/45
- 50/50

### PLC 1x8 Example

For a PLC device with model `1x8`:

- one input endpoint receives upstream feed
- eight output endpoints are generated
- each output endpoint can serve one subscriber assignment
- occupied, inactive, or damaged outputs are excluded from clean assignment
  choices

The PLC output is treated as the final distribution endpoint before the
subscriber drop, unless another downstream object is explicitly modeled.

## Subscriber Assignment Flow

### From Subscriber Detail

The Subscriber module remains the starting point for staff who already work
there.

The assignment panel should become an NMS endpoint picker:

- choose router, NAP, or distribution node
- choose exact endpoint or router ethernet port
- show endpoint availability
- show basic path health
- save one active service attachment

New clean assignments must choose an exact endpoint.

### Existing Basic Node Assignments

Existing basic node assignments should not be deleted or rewritten.

When a subscriber has only a node-level mapping:

- keep the map visibility
- show the topology state as Needs Review
- keep the line editable
- prompt the operator to select an exact endpoint when they next reassign

This protects historical data while moving new operations to the cleaner
endpoint model.

### Auto-Link Behavior

When a subscriber is assigned to an exact endpoint:

- create or update the service attachment
- mark the endpoint occupied
- create the downstream subscriber drop path automatically
- reuse the upstream path from the endpoint graph
- allow the final subscriber drop vertices to be edited like current subscriber
  link geometry

The operator should not need to manually build a separate map link for every
subscriber when the endpoint already belongs to a known NAP or router path.

### Direct Router Ethernet Subscriber

Direct subscriber links must support cases such as:

`Router ether7 -> Subscriber diannajoseraspi`

For this flow:

- `ether7` is selected as the endpoint
- the service attachment points to the router ethernet endpoint
- the line type is ethernet
- telemetry can use the router interface traffic cache directly
- the subscriber remains the last endpoint

## Shared Paths and Map Rendering

### Shared Physical Path

NAP-to-NAP and NAP-to-client lines should share path geometry where practical.

The map should render:

- upstream shared paths once as topology or endpoint graph paths
- subscriber drops as short final branches from the assigned endpoint to the
  client coordinates
- editable vertices for both node-to-node links and subscriber drops

If a subscriber path has no custom vertices yet, it should default to:

`assigned endpoint/root node coordinates -> subscriber coordinates`

If a topology link or endpoint connection has geometry, subscriber path
highlighting should follow that upstream geometry first, then the final drop.

### Running Dash Lines

Connected lines should support animated dash styling.

The animation should communicate state:

- active/live telemetry: moving dash
- idle/unknown: slow or muted dash
- offline/down/damaged: static or warning style

The line should not become unreadable on dense maps. It should stay thin enough
for nearby nodes while still showing direction and status.

### Client Dot and Billing Ring

Subscriber markers should show two different states:

- solid inner dot: live status from router or subscriber telemetry
- dashed outer ring: billing health

Solid dot defaults:

- green: online
- red: offline
- gray: unknown

Billing ring defaults:

- red: overdue
- amber: open, partial, due soon, or current balance
- green: clear or on time
- gray: non-billable or unknown

This keeps network state and billing state visually separate.

## UI and UX Requirements

The workflow should feel like configuration, not data entry overload.

Required UI surfaces:

- map layer control for street and satellite view
- close zoom support for dense NAP and subscriber clusters
- router root node visible when coordinates exist
- distribution detail page showing NAP inputs, FBT ports, PLC ports, and
  endpoint connection status
- endpoint picker in the subscriber NMS assignment flow
- clear Needs Review state for node-only legacy mappings
- path editor for subscriber links using click, GPS, and manual coordinate
  input
- path editor for topology or endpoint graph links using the same interaction
  model

The UI should avoid making operators understand database terms. It should speak
in field terms:

- router port
- NAP input
- FBT IN
- FBT 90 output
- FBT 10 output
- PLC IN
- PLC output 1
- client drop

## Delete Behavior

Node deletion should continue to remove only NMS data under the selected node.

Allowed under-node deletions:

- internal devices
- endpoints
- endpoint connections owned by those endpoints
- topology links connected to the node
- cable and cable core data under those links
- cable core assignments under those cables
- service attachment endpoint references under that node
- service attachment vertices for those subscriber drops when the attachment is
  being reset to Needs Review

Must not delete:

- router records
- subscriber records
- invoices
- payments
- billing snapshots
- account lifecycle history
- upstream nodes above the selected node

When a deleted node was part of an active subscriber path, affected subscribers
should become Needs Review instead of disappearing from the account system.

## Validation and Operations

Operations Center should add checks for:

- router with coordinates but missing root NMS node
- root NMS node with stale router coordinates
- active endpoint with no upstream source
- occupied endpoint with no service attachment
- service attachment pointing to inactive or damaged endpoint
- PLC output assigned to more than one subscriber
- FBT primary pass-through output used as a normal subscriber access endpoint
- endpoint connection loop
- direct subscriber mapping without subscriber coordinates
- router interface endpoint with stale telemetry
- node-only subscriber mapping that still needs endpoint review

Each validation issue should link to the correct repair screen.

## Data Migration and Compatibility

The implementation should be additive.

Expected migration work:

- add router endpoint records for eligible physical ethernet interfaces
- add endpoint connection records
- add metadata needed to distinguish system router root nodes from manually
  created field nodes
- add optional telemetry and billing display fields to map serialization if
  needed

Existing `ServiceAttachment`, `TopologyLink`, `InternalDevice`, `Endpoint`,
`Cable`, `CableCore`, and `CableCoreAssignment` records should remain valid.

No subscriber, invoice, payment, or billing snapshot data should be migrated or
deleted for this slice.

## Test Plan

Model and service tests:

- router with coordinates creates or syncs one root NMS node
- router without coordinates does not create a visible root node
- only eligible ethernet interfaces become assignable router endpoints
- FBT 90/10 creates IN, PRIMARY 90%, and SECONDARY 10% endpoints
- PLC 1x8 creates one input and eight output endpoints
- endpoint graph prevents loops
- occupied PLC output cannot be assigned to a second subscriber
- node-only existing attachment becomes Needs Review, not deleted
- deleting a node preserves subscriber, router, and billing records

View and API tests:

- map data includes router root node and subscriber attachments
- map data includes telemetry status for direct router interface subscriber
- map data includes billing ring state
- subscriber assignment requires exact endpoint for new clean mappings
- endpoint picker excludes occupied, inactive, damaged, and disallowed FBT
  pass-through endpoints
- path geometry saves for subscriber drops and node-to-node links

Browser smoke tests:

- switch map between street and satellite layers
- zoom into dense nearby nodes
- connect Router to NAP BOX 1
- configure FBT 90/10 under NAP BOX 1
- connect FBT primary output to NAP BOX 2
- connect FBT secondary output to PLC 1x8 input
- assign eight subscribers to PLC outputs
- assign a direct ethernet subscriber to router `ether7`
- verify animated line state, solid dot network state, and billing ring state

## Rollout Sequence

1. Add additive models and migrations for router root metadata, router endpoint
   inventory, and endpoint connections.
2. Build services to sync router root nodes and eligible ethernet endpoints.
3. Extend distribution detail to wire endpoint connections for NAP, FBT, PLC,
   router port, and downstream subscriber flows.
4. Upgrade subscriber assignment to endpoint-required selection while preserving
   existing node-only mappings as Needs Review.
5. Extend map data and map rendering for shared paths, telemetry animation,
   solid client dot, and billing ring.
6. Add operations validation checks and repair links.
7. Run model, view, service, and browser smoke tests.
8. Apply migrations in production and reload the running web service.

## Acceptance Criteria

The slice is complete when:

- routers with coordinates are visible and usable as NMS root nodes
- router ethernet ports can be selected as exact upstream or subscriber
  endpoints
- NAP BOX 1 can connect to the router when no OLT or distribution node exists
- FBT IN, primary output, and secondary output can be wired explicitly
- PLC input and outputs can be wired explicitly
- subscribers can be assigned to exact PLC outputs or router ethernet ports
- legacy node-only mappings remain visible but are marked Needs Review
- subscriber path vertices stay editable through click, GPS, and manual input
- map lines reflect live telemetry where available
- client marker dot reflects online/offline
- client marker ring reflects billing health
- node deletion removes only downstream NMS records and never deletes account or
  billing truth
