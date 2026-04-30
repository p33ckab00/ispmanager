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

## Implementation Status

The first port-accurate implementation slice is now in code.

Implemented:

- router root node metadata on `NetworkNode`
- auto-sync of one router root node per active router with coordinates
- physical ethernet router interface endpoints through `Endpoint.router_interface`
- endpoint-to-endpoint wiring through `EndpointConnection`
- automatic internal PLC and FBT wiring for generated splitter endpoints
- endpoint wiring management inside the distribution detail page
- topology link detail visibility for wiring that uses the selected physical
  span
- subscriber mappings without exact endpoints marked as Needs Review
- map marker billing rings and telemetry/path-state line styling

Still future refinement:

- richer guided wizards for router-to-NAP, FBT-to-NAP, and FBT-to-PLC flows
- stronger bulk migration tools for historical node-only assignments
- permission-specific map visibility for billing rings
- deeper optical telemetry if actual optical signal data becomes available

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

## Corrected Design Model

The safest design is to separate four kinds of truth instead of forcing one
record type to do everything.

### Account Truth

`Subscriber`, invoices, payments, billing snapshots, lifecycle status, plans,
and customer identity remain account truth.

Premium NMS must never use physical topology edits to delete or rewrite account
truth. Physical mapping can affect topology status, assignment status, and
review flags, but it must not delete a subscriber or billing history.

### Physical Span Truth

`TopologyLink`, `Cable`, and `CableCore` describe physical spans between field
locations.

Examples:

- router site to NAP BOX 1
- NAP BOX 1 to NAP BOX 2
- pole splice to cabinet
- cabinet to another distribution point

This layer owns map geometry for shared feeder and distribution routes. It is
the right place for cable route vertices, cable capacity, installation type,
and core inventory.

### Port Wiring Truth

Endpoint connections describe exact input/output wiring.

Examples:

- router `ether7` to NAP BOX 1 input
- NAP BOX 1 input to FBT IN
- FBT PRIMARY 90% to NAP BOX 2 input
- FBT SECONDARY 10% to PLC 1x8 IN
- PLC output 3 to subscriber drop

This layer owns direction, endpoint occupancy, and whether the downstream path
has a valid upstream source. It may reference a `TopologyLink` and `CableCore`
when the connection crosses a physical span.

### Visual Truth

The map should be derived from the physical span layer, port wiring layer,
subscriber coordinates, telemetry, and billing state.

The map should not become a separate source of truth. Dragged/clicked/manual
vertices update the underlying span or subscriber drop geometry; the rendered
lines and marker styles are then recalculated.

## Real-World Field Workflow

The implementation should follow how field work is normally done: source,
feeder, distribution, split, drop, then subscriber.

### 1. Establish Source

The operator starts from the source of signal or service.

Valid source records:

- router with coordinates
- router physical ethernet port
- OLT node
- distribution cabinet
- splice panel

When the operator has not modeled an OLT, distribution box, or splice panel yet,
the router with coordinates becomes the practical root source for mapping.

### 2. Build Feeder Route

The operator creates or confirms the feeder route from the source to the first
field distribution point.

Example:

`Router site -> NAP BOX 1`

The physical span should be represented as a topology link with optional cable
and core inventory. The exact port wiring should then connect:

`router port -> NAP BOX 1 input`

This avoids a common design flaw: treating the map line itself as the port
assignment. The line is the route; the endpoint connection is the wiring.

### 3. Configure Node Internals

Inside a NAP, cabinet, splice box, or panel, the operator configures internal
objects such as:

- FBT splitter
- PLC splitter
- patch panel
- splice tray
- manual passthrough endpoint

Internal wiring inside the same node should not require drawing extra map
lines. It should be shown as a compact wiring view in the distribution detail
page.

### 4. Split or Pass Signal Downstream

For FBT, the operator wires the upstream input and downstream outputs.

Example:

`NAP BOX 1 input -> FBT IN`

Then:

`FBT PRIMARY 90% -> NAP BOX 2 input`

And:

`FBT SECONDARY 10% -> PLC 1x8 IN`

This matches field work: one side continues the main line, and one side feeds a
local split. The system should store the intended role of each FBT output, not
only the label, because field usage may vary.

### 5. Assign Access Port

The operator assigns the subscriber to the final access point:

- PLC output
- NAP output
- router ethernet port for direct ethernet service
- other access endpoint

New clean assignments require an exact endpoint. Old node-only mappings remain
visible but are marked Needs Review until the endpoint is selected.

### 6. Draw or Reuse Drop Route

After endpoint assignment, the system creates the subscriber drop path.

The upstream feeder/distribution route should be reused from existing topology
and endpoint graph data. The final subscriber drop remains editable using the
same tools already used for subscriber path vertices:

- click on map
- GPS trace
- manual coordinate entry

### 7. Validate Before Trusting

The Operations Center should confirm that the path is complete:

`source -> feeder -> node input -> splitter/pass-through -> final endpoint -> subscriber`

A subscriber can be visible on the map before the path is fully trusted, but
the topology state should show Needs Review until the upstream chain is valid.

## Target Network Flow

### Router as Root Node

When an active router has latitude and longitude:

- Premium NMS must expose that router as a root topology node.
- The system root node should be tied to the router record.
- Moving router coordinates should update the root node coordinates.
- The root node should be visible on the NMS map and usable as the source for
  NAP, PLC, FBT, and direct subscriber links.
- The map should avoid showing confusing duplicate router/root markers. The UI
  can show one combined marker with router styling while the graph uses the
  system root node internally.

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
- wiring role: feeder, passthrough, splitter_input, splitter_output, drop,
  direct_client, or other
- status: active, planned, inactive, or damaged
- optional topology link when the connection crosses between physical nodes
- optional cable core when the connection uses a tracked fiber core
- optional notes

The graph direction should always flow from upstream network source to
downstream subscriber side:

`router port -> NAP input -> FBT input -> FBT output -> PLC input -> PLC output -> subscriber`

Connections must prevent invalid loops and should flag broken paths when an
active downstream endpoint has no upstream source.

Endpoint connections should not replace topology links. A topology link answers
"where does this physical span run?" An endpoint connection answers "which port
feeds which port?"

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
- output role should be stored explicitly, because the field may use a primary
  or secondary leg differently from the default label in special cases

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
- do not silently mark the mapping fully clean if the selected endpoint has no
  valid upstream source

The operator should not need to manually build a separate map link for every
subscriber when the endpoint already belongs to a known NAP or router path.

The correct default is:

- endpoint selected and upstream path complete: `Mapped`
- endpoint selected but upstream path incomplete: `Needs Review`
- node-only legacy mapping: `Needs Review`
- no node and no endpoint: `Unassigned`

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
- focused full-path highlight for one selected subscriber instead of drawing
  every subscriber's full upstream path all the time
- animated running dash styling for active fiber spans and focused subscriber
  paths, including paths with manually edited vertices

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

For passive fiber paths, running dash state should be interpreted as service
or path state, not measured optical signal. True live telemetry exists only
where the system has router interface traffic, router state, or subscriber
MikroTik state.

### Client Dot and Billing Ring

Subscriber markers should show two different states:

- solid inner dot: live status from router or subscriber telemetry
- dashed outer ring: billing health
- online solid dots may pulse lightly
- overdue or open-balance billing rings may rotate subtly so billing attention
  is visible without confusing it with live network state

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

Billing rings should be layer-toggleable so technical field work can focus on
physical status when billing state is not relevant to the task.

## UI and UX Requirements

The workflow should feel like configuration, not data entry overload.

Required UI surfaces:

- map layer control for street and satellite view
- close zoom support for dense NAP and subscriber clusters
- router root node visible when coordinates exist
- distribution detail page showing NAP inputs, FBT ports, PLC ports, and
  endpoint connection status
- compact internal wiring view for same-node connections so operators do not
  need to draw map lines inside a NAP box
- endpoint picker in the subscriber NMS assignment flow
- clear Needs Review state for node-only legacy mappings
- path editor for subscriber links using click, GPS, and manual coordinate
  input
- path editor for topology or endpoint graph links using the same interaction
  model
- preview of the upstream chain before saving a subscriber assignment

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

The ideal operator flow is:

1. choose or confirm the source
2. connect source to NAP input
3. configure internals inside the NAP
4. wire splitter outputs
5. assign the subscriber to the final access endpoint
6. adjust the subscriber drop route if needed
7. resolve any Needs Review warnings

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

The delete screen should preview affected downstream subscribers, endpoint
connections, topology links, cables, and core assignments before the operator
confirms the delete. This prevents accidental loss of field mapping work.

## Validation and Operations

Operations Center should add checks for:

- router with coordinates but missing root NMS node
- root NMS node with stale router coordinates
- duplicate visible router/root marker state
- active endpoint with no upstream source
- occupied endpoint with no service attachment
- service attachment pointing to inactive or damaged endpoint
- PLC output assigned to more than one subscriber
- FBT primary pass-through output used as a normal subscriber access endpoint
- endpoint connection loop
- endpoint connection that duplicates a topology link without referencing it
- direct subscriber mapping without subscriber coordinates
- router interface endpoint with stale telemetry
- node-only subscriber mapping that still needs endpoint review
- subscriber marked Mapped even though the upstream chain is incomplete

Each validation issue should link to the correct repair screen.

## Data Migration and Compatibility

The implementation should be additive.

Expected migration work:

- add router endpoint records for eligible physical ethernet interfaces
- add endpoint connection records
- add explicit endpoint connection role/purpose metadata
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
- router marker and router root node do not render as confusing duplicates
- router without coordinates does not create a visible root node
- only eligible ethernet interfaces become assignable router endpoints
- FBT 90/10 creates IN, PRIMARY 90%, and SECONDARY 10% endpoints
- PLC 1x8 creates one input and eight output endpoints
- endpoint graph prevents loops
- endpoint connection can reference a topology link and cable core for a
  cross-node fiber span
- occupied PLC output cannot be assigned to a second subscriber
- subscriber assigned to endpoint with incomplete upstream chain becomes Needs
  Review
- node-only existing attachment becomes Needs Review, not deleted
- deleting a node preserves subscriber, router, and billing records

View and API tests:

- map data includes router root node and subscriber attachments
- map data includes telemetry status for direct router interface subscriber
- map data includes billing ring state
- map data derives shared upstream path from topology/endpoint graph data
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
- confirm one subscriber full-path highlight without drawing every upstream
  path for every subscriber at once
- verify animated line state, solid dot network state, and billing ring state

## Rollout Sequence

1. Add additive models and migrations for router root metadata, router endpoint
   inventory, and endpoint connections. Implemented.
2. Build services to sync router root nodes and eligible ethernet endpoints.
   Implemented.
3. Extend distribution detail to wire endpoint connections for NAP, FBT, PLC,
   router port, and downstream subscriber flows. Implemented as the first wiring
   form.
4. Upgrade subscriber assignment to endpoint-required selection while preserving
   existing node-only mappings as Needs Review. Implemented for review-state
   behavior; richer guided endpoint selection remains a refinement.
5. Extend map data and map rendering for shared paths, telemetry animation,
   solid client dot, and billing ring. Implemented as first-pass visual state.
6. Add operations validation checks and repair links. Implemented for router
   roots, endpoint wiring, and incomplete upstream path checks.
7. Run model, view, service, and browser smoke tests. In progress.
8. Apply migrations in production and reload the running web service. Required
   during deployment.

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
