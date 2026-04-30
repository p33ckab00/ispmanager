# Premium NMS Atomic User Manual

## Purpose

This manual is the operator-facing guide for the current Premium NMS workflow in
the ISP Manager codebase.

It explains the complete path from MikroTik router sync, coordinate updates,
router-root creation, node and link inventory, NAP/PLC/FBT configuration,
endpoint wiring, subscriber assignment, cable core assignment, map verification,
operations validation, and analytics.

The goal is atomic usage: one small action at a time, in the same order a field
operator or admin should perform the work.

## Source of Truth Rules

Use these rules before editing anything:

1. Routers are the source for MikroTik connectivity, router status, interfaces,
   and live interface traffic.
2. Subscribers are the source for customer identity, service account, MikroTik
   user data, coordinates, billing, and lifecycle status.
3. `NetworkNode` records are the source for physical field locations such as
   router sites, OLTs, cabinets, NAPs, splice boxes, access points, and other
   distribution points.
4. `TopologyLink` records are the physical span source of truth between nodes.
   This is where shared feeder and distribution geometry belongs.
5. `Endpoint` records are the exact ports or terminals inside a node, router
   root, PLC, FBT, patch panel, splice tray, or direct node endpoint.
6. `EndpointConnection` records are the port-to-port wiring source of truth.
   They describe upstream-to-downstream signal flow.
7. `ServiceAttachment` records are the subscriber-to-NMS assignment source of
   truth.
8. Premium paths on the map are computed service renderings. They should follow
   topology links, endpoint wiring, subscriber drop geometry, telemetry, and
   billing state. They should not become a separate physical source of truth.
9. Billing, payments, invoices, and subscriber account records must not be
   deleted by NMS topology cleanup.
10. Router, subscriber, and billing truth stay in their own modules; NMS links
    them together for field visibility.

## Modules Covered

The workflow uses these current modules:

- `/routers/`: MikroTik router inventory, API connection, sync, coordinates,
  interfaces, interface labels, interface roles, and live traffic cache.
- `/subscribers/`: customer/service account list, MikroTik subscriber sync,
  subscriber coordinates, lifecycle, billing summary, and NMS entry point.
- `/nms/`: live map, satellite/street layers, router/node/subscriber markers,
  topology links, premium paths, GPS traces, and path editing.
- `/nms/nodes/`: network node inventory and delete-impact review.
- `/nms/links/`: topology link inventory, fiber cable inventory, cable cores,
  and link-level endpoint wiring visibility.
- `/nms/distribution/<node_id>/`: NAP/node distribution detail, internal
  devices, endpoints, PLC/FBT ports, and endpoint wiring.
- `/nms/subscribers/<subscriber_id>/`: subscriber Premium NMS workspace,
  endpoint assignment, review state, and cable core assignment.
- `/nms/operations/`: validation report, review-state refresh, endpoint
  occupancy sync, router-root sync, and cable core status sync.
- `/nms/analytics/`: GPS trace import, route distance report, outage impact
  trace, cable utilization, and optical power-budget estimates.
- `/billing/`: invoices, snapshots, balances, and payment state used by NMS
  subscriber billing rings.
- `/accounting/`: income and expense records fed by payments; use this when
  reconciling billing and operational finance outside NMS.
- `/sms/`: billing and service messaging tools that can be used after NMS or
  outage review identifies affected subscribers.
- `/notifications/`: Telegram/event notification history for operational
  visibility outside the map.
- `/diagnostics/`: operations and service health context when sync or telemetry
  seems stale.
- `/dashboard/`: business and operational overview before entering detailed NMS
  work.
- `/auth/`: login/logout and access boundary.
- `/landing/`: public homepage and captive portal surfaces; not part of NMS
  topology, but part of the same operator system.
- `/data-exchange/`: CSV import/export workflows that can affect subscriber
  inventory before NMS mapping.
- `/settings/`: global ISP settings, billing settings, router settings, SMS,
  Telegram, and usage settings that support the broader workflow.
- `/api/v1/`: API surface for integrations.

## Full Codebase Module Reference

This section maps the current codebase modules to their NMS usage impact.

### Core, Auth, and Dashboard

Use these for system access and overview.

1. Log in through the auth flow.
2. Use the dashboard to review high-level ISP state.
3. Confirm the user has access to router, subscriber, billing, and NMS pages.
4. Use audit logs indirectly through module actions; NMS create/update/delete
   actions log operational history.

NMS impact:

- staff access controls who can perform topology changes
- dashboard context helps decide whether an issue is network, billing, or
  service health related
- audit logs record NMS changes such as node saves, link saves, endpoint wiring,
  GPS trace imports, and mapping updates

### Settings

Use settings before large operational work.

1. Confirm ISP identity and global settings.
2. Confirm billing settings before reading NMS billing rings.
3. Confirm router settings before relying on telemetry or sync cadence.
4. Confirm SMS and Telegram settings if affected-subscriber messaging is part
   of the workflow.
5. Confirm usage settings if live usage or subscriber usage context matters.

NMS impact:

- billing settings affect due/open/overdue interpretation
- router and usage settings affect telemetry expectations
- SMS/Telegram settings affect response workflows after outage analysis

### Routers

Use routers as the network source layer.

1. Add router.
2. Test MikroTik API connection.
3. Sync router.
4. Update coordinates.
5. Label interfaces.
6. Set interface roles.
7. Inspect interface traffic.

NMS impact:

- router coordinates become map source location
- physical ethernet interfaces become router endpoints
- interface traffic can drive live path state where mapped
- router sync can create or refresh interface inventory

### Subscribers

Use subscribers as the customer and account source layer.

1. Sync subscribers from MikroTik or add manually.
2. Complete contact and billing details.
3. Add coordinates.
4. Review lifecycle status.
5. Open Premium NMS workspace from subscriber detail.
6. Use basic node assignment only as a transition path.

NMS impact:

- subscriber coordinates create client markers
- subscriber MikroTik status contributes live marker state
- subscriber billing state contributes marker ring state
- subscriber lifecycle affects operational interpretation
- Premium NMS mapping links the account to the field endpoint

### Billing

Use billing for financial truth.

1. Review invoices.
2. Review billing snapshots.
3. Review balances and payments.
4. Generate or inspect statements when needed.
5. Use payment state to explain billing ring state on the map.

NMS impact:

- overdue/open/ontime marker rings are billing-derived
- NMS must not rewrite invoices, payments, or billing history
- NMS can help locate affected customers, but billing remains the receivable
  source of truth

### Accounting

Use accounting for business reconciliation.

1. Review income and expense records.
2. Use monthly profit/loss context outside NMS.
3. Reconcile payment-driven income when needed.

NMS impact:

- accounting does not define topology
- field work and outages can explain operational expense, but NMS does not own
  accounting records

### SMS and Notifications

Use these after NMS identifies who needs communication.

1. Use SMS tools for affected subscriber messages.
2. Use billing SMS from subscriber detail when the issue is billing-related.
3. Use notifications/Telegram logs for operational visibility.
4. Use NMS outage impact before sending broad maintenance messages.

NMS impact:

- outage impact can identify target subscribers for communication
- billing rings can identify billing-related follow-up
- notifications are response tooling, not topology truth

### Diagnostics

Use diagnostics when sync, service, scheduler, or telemetry behavior is unclear.

1. Check service health.
2. Check scheduler truth.
3. Check router, billing, messaging, and usage diagnostics.
4. Use diagnostics before assuming the NMS model is wrong.

NMS impact:

- stale telemetry may make live dots or line state look wrong
- router/API failures can stop sync and traffic cache updates
- scheduler problems can affect background samples

### Landing and Portal

Use landing/captive portal as public-facing system surfaces.

1. Manage homepage or captive portal outside NMS.
2. Keep customer-facing pages separate from internal topology data.
3. Use subscriber portal for customer statements and usage where applicable.

NMS impact:

- none for physical topology
- portal/customer presentation should not expose internal NMS topology unless a
  future feature explicitly designs that boundary

### Data Exchange

Use data exchange for bulk data movement.

1. Export subscriber data before bulk cleanup.
2. Import subscribers through dry-run validation.
3. Import payments through the billing allocation flow.
4. Recheck subscriber coordinates after CSV changes.

NMS impact:

- bulk subscriber imports can create or update accounts before mapping
- coordinate imports can affect map visibility
- payment imports can affect billing rings

### NMS

Use NMS as the physical network and mapping layer.

1. Model physical nodes.
2. Model physical links.
3. Model cables and cores.
4. Model internal distribution devices.
5. Model endpoints.
6. Wire endpoints.
7. Assign subscribers.
8. Verify map rendering.
9. Run operations validation.
10. Use analytics for planning and incident review.

NMS impact:

- NMS is physical truth, wiring truth, and service attachment truth
- NMS reads router, subscriber, billing, and telemetry state
- NMS must not overwrite account, billing, or accounting truth

## High-Level Field Workflow

The clean real-world order is:

1. Add or sync the router.
2. Add router coordinates.
3. Sync router root and physical ethernet endpoints into NMS.
4. Add or verify field nodes such as NAPs, cabinets, splice boxes, OLTs, or
   access points.
5. Connect physical locations using topology links.
6. Add fiber cable inventory and cores on fiber topology links.
7. Configure internal devices inside a node, such as FBT, PLC, patch panel, or
   splice tray.
8. Generate or add endpoints.
9. Wire endpoints from upstream source to downstream distribution.
10. Sync subscribers or add subscriber records.
11. Add subscriber coordinates.
12. Assign the subscriber in the Premium NMS workspace to the final endpoint.
13. Assign cable core if the physical span uses tracked fiber cores.
14. Edit topology or subscriber drop geometry only where needed.
15. Open the map and verify markers, topology links, premium paths, and status
   indicators.
16. Run NMS Operations validation.
17. Use NMS Analytics for GPS traces, route checks, outage impact, cable
   utilization, and power-budget review.

## Phase 0: Pre-Flight Checklist

Do this before starting a new NMS mapping job:

1. Log in as a staff user that can access routers, subscribers, and NMS.
2. Confirm the router is reachable on the MikroTik API port, usually `8728`.
3. Confirm the router API username and password are correct.
4. Confirm the router has the physical interfaces you expect.
5. Confirm the subscriber exists or can be synced from MikroTik.
6. Prepare field coordinates for:
   - router site
   - NAP or cabinet
   - splice box or junction point
   - subscriber/client location
7. Prepare the physical route information:
   - source node
   - target node
   - cable type
   - cable name/code
   - number of cores
   - route vertices or GPS trace if available
8. Prepare distribution information:
   - NAP box name
   - PLC model, such as `1x8`
   - FBT ratio, such as `90/10`
   - port labels
   - fiber core number or color if tracked
9. Decide whether the subscriber is:
   - direct router ethernet
   - fed from NAP direct endpoint
   - fed from PLC output
   - fed through FBT and PLC
   - legacy node-only mapping that needs review

## Phase 1: Add or Sync the Router

Use this when the router is not yet in the system.

1. Open `/routers/`.
2. Click `Add Router`.
3. Enter `Name`.
4. Enter `Host`, using IP address or hostname.
5. Enter `API Port`.
6. Enter MikroTik API `Username`.
7. Enter MikroTik API `Password`.
8. Enter `Location` if known.
9. Enter `Description` if useful.
10. Click `Test Connection`.
11. Wait for the test result.
12. If the connection fails, correct the host, port, username, password, or
    MikroTik API access before saving.
13. When the test passes, save the router.
14. Return to `/routers/`.
15. Click `Sync` on the router.
16. Confirm that the router status updates.
17. Open the router detail page.
18. Confirm the interface list appears.
19. Open important interfaces and set labels or roles where needed.

Notes:

- Interface labels are admin-owned display labels.
- Router interface names are synced from MikroTik.
- NMS uses physical ethernet interfaces as assignable router endpoints.
- Live traffic cache comes from the router interface telemetry flow.

## Phase 2: Update Router Coordinates

Router coordinates are required before the router can become a visible NMS
source/root.

1. Open `/routers/`.
2. Open the router detail page.
3. Open `Update Coordinates`.
4. Enter `Location`.
5. Enter `Latitude`.
6. Enter `Longitude`.
7. Save coordinates.
8. Open `/nms/`.
9. Confirm that the router or its synced router-root node appears on the map.

Coordinate rules:

- Latitude must be the north/south value.
- Longitude must be the east/west value.
- Use decimal degrees.
- Example format: `14.599500`, `120.984200`.
- More decimal places give better placement for dense nodes.
- If nodes are very close together, use satellite view and closer zoom in the
  map.

## Phase 3: Sync Router Roots and Router Ports into NMS

The current implementation can create a system-managed router root node for each
active router that has coordinates.

1. Open `/nms/operations/`.
2. Click `Sync Router Roots & Ports`.
3. Read the success message.
4. Confirm how many router root nodes were added.
5. Confirm how many router ethernet endpoints were added.
6. Open `/nms/`.
7. Find the router site marker or router root node marker.
8. Open the router root node distribution page if needed.
9. Confirm physical ethernet ports exist as endpoints.

Important behavior:

- `/nms/data/` also runs router-root sync when the map data loads.
- Manual sync from `/nms/operations/` is still useful after adding coordinates
  or after router interface changes.
- One router root node is created per router with coordinates.
- Router root nodes are system-managed and linked to the router.
- Physical ethernet interfaces become router port endpoints.
- Non-physical interfaces are not normal clean assignment endpoints.

## Phase 4: Create or Update Field Nodes

Use field nodes for NAP boxes, cabinets, OLTs, splice boxes, access points, and
other distribution locations.

Option A: Create from the map.

1. Open `/nms/`.
2. Switch to `Add Node` mode.
3. Click the exact location on the map.
4. Enter node name.
5. Choose node type.
6. Link to a router if applicable.
7. Enter port count if useful.
8. Enter notes if needed.
9. Save.
10. Confirm the node marker appears.

Option B: Create from the nodes page.

1. Open `/nms/nodes/`.
2. Fill in the node form.
3. Enter `Name`.
4. Select `Node Type`.
5. Optionally select linked `Router`.
6. Enter `Latitude`.
7. Enter `Longitude`.
8. Enter `Port Count`.
9. Enter `Notes`.
10. Keep `Is Active` enabled for live nodes.
11. Save.

Current node types:

- Router Site
- OLT
- Distribution Cabinet
- Access Point
- Splice / Junction Box
- PisoWifi Node
- Other

Naming guide:

- Use field-friendly names like `NAP BOX 1`, `NAP BOX 2`, `CABINET A`,
  `SPLICE POLE 12`, or `ROUTER SITE MAIN`.
- Keep names stable after field deployment because links, endpoint wiring, and
  subscriber mappings reference them.
- Put location detail or install notes in notes, not only in the name.

## Phase 5: Build Physical Topology Links

Topology links represent real physical spans between nodes.

Use them for:

- router site to NAP
- OLT to cabinet
- cabinet to NAP
- NAP to NAP
- splice box to cabinet
- access point backhaul
- tracked direct cable span when it should be inventory-grade

Option A: Quick create from map.

1. Open `/nms/`.
2. Switch to `Connect Nodes`.
3. Click the upstream source node first.
4. Click the downstream target node second.
5. Enter link name or leave it as source-to-target.
6. Select link type.
7. Select status.
8. Enter notes.
9. Click `Create Link`.
10. Confirm the line appears on the map.

Option B: Detailed create from links page.

1. Open `/nms/links/`.
2. Enter link name.
3. Select source node.
4. Select target node.
5. Select link type.
6. Select status.
7. Enter notes.
8. If needed, enter geometry vertices.
9. If the link is fiber and you track cable inventory, fill the fiber cable
   section.
10. Save.

Link types:

- Fiber
- Ethernet
- Wireless Backhaul
- Power
- Other

Link statuses:

- Active
- Planned
- Inactive

Direction rule:

Always create links in the direction of service flow where possible:

`source/root/upstream -> field distribution/downstream`

Examples:

- `Router Site -> NAP BOX 1`
- `NAP BOX 1 -> NAP BOX 2`
- `CABINET A -> SPLICE BOX 3`

## Phase 6: Add Fiber Cable Inventory and Cores

Cable inventory is supported for fiber topology links.

1. Open `/nms/links/`.
2. Select an existing fiber link or create a new fiber link.
3. In `Fiber Cable Inventory`, enter cable name.
4. Enter cable code if you use one.
5. Enter total cores.
6. Enter cable length in meters if known.
7. Select installation type.
8. Select cable status.
9. Enter install date if known.
10. Enter cable notes.
11. Save.
12. Confirm the cable core inventory table appears.
13. Review generated cores and colors.

Installation types:

- Aerial
- Underground
- Indoor
- Mixed

Cable statuses:

- Active
- Planned
- Inactive
- Damaged

Core statuses:

- Available
- Reserved
- Used
- Damaged

Rules:

- Cable inventory is fiber-only.
- Fiber links with cable inventory need total cores greater than zero.
- A cable needs a cable name.
- Total core count cannot be reduced below the number of used or reserved
  cores.
- Damaged cores cannot be assigned to subscribers.

## Phase 7: Import GPS Trace for Survey or As-Built Routes

GPS traces are optional but useful for real route geometry.

1. Open `/nms/analytics/`.
2. Find `Import GPS Trace`.
3. Enter trace name.
4. Select trace type.
5. Enter source label if useful.
6. Enter captured date/time if known.
7. Enter notes.
8. Paste coordinates into `Coordinates`.
9. Use one point per line.
10. Save/import the trace.
11. Confirm the trace appears in recent GPS traces.
12. Open `/nms/`.
13. Turn on `GPS Traces`.
14. Confirm the trace appears on the map.

Coordinate format:

```text
14.59950,120.98420
14.60010,120.98550
14.60050,120.98600,pole 12
```

Rules:

- Each line must start with `lat,lng`.
- Optional note may follow after another comma.
- Latitude must be between `-90` and `90`.
- Longitude must be between `-180` and `180`.

## Phase 8: Edit Physical Path Geometry

Use path geometry when straight lines are not accurate enough.

1. Open `/nms/`.
2. Switch to `Edit Path`.
3. Click a topology link or subscriber path.
4. Review the selected path in the inspector.
5. Add middle vertices by clicking the map.
6. Drag a handle to move a vertex.
7. Click a handle to remove a vertex.
8. Optionally load a GPS trace.
9. Optionally click `Add GPS Point` to add current browser GPS point.
10. Review the `Middle Vertices` text area.
11. Click `Save Geometry`.
12. Confirm the path redraws.

Geometry rule:

- Start and end stay anchored to the source and target.
- The text area stores middle vertices only.
- Do not duplicate the source coordinate as the first middle vertex.
- Do not duplicate the target coordinate as the last middle vertex.

When to edit topology link geometry:

- shared feeder route changes
- NAP-to-NAP path changes
- field cable route is surveyed
- a cable is rerouted

When to edit subscriber attachment geometry:

- final drop route to the subscriber is not a straight line
- the drop uses poles, walls, or bends that need to be shown
- the subscriber branch needs separate route detail

Do not edit subscriber drop geometry to fake an upstream feeder route. Upstream
shared route belongs to topology links and endpoint wiring.

## Phase 9: Configure Distribution Internals

Use the distribution detail page for NAP internals, splitters, patch panels,
splice trays, and direct node endpoints.

1. Open `/nms/`.
2. Click a node marker.
3. Click `Open Distribution`.
4. Review endpoint inventory.
5. Review direct node endpoints.
6. Review internal devices.
7. Review endpoint wiring.

To add an internal device:

1. Open the node distribution page.
2. Fill `Add Internal Device`.
3. Enter device name.
4. Select device type.
5. Enter slot label if useful.
6. If PLC, choose PLC model or output count.
7. If FBT, choose FBT ratio.
8. Keep auto-generate enabled when you want ports created automatically.
9. Enter notes.
10. Save.
11. Confirm generated input/output endpoints.

Internal device types:

- PLC Splitter
- FBT Splitter
- Patch Panel
- Splice Tray
- Other

PLC choices:

- `1x4`
- `1x8`
- `1x16`
- `1x32`

FBT ratio choices:

- `95/5`
- `90/10`
- `85/15`
- `80/20`
- `75/25`
- `70/30`
- `65/35`
- `60/40`
- `55/45`
- `50/50`

PLC behavior:

- A PLC normally has one input endpoint.
- The output count comes from the PLC model or explicit output count.
- Each output can become a final subscriber access endpoint.
- Occupied, inactive, and damaged endpoints should not be used for new clean
  assignments.

FBT behavior:

- An FBT has one `IN`.
- It has two outputs.
- The primary output usually represents the larger ratio.
- The secondary output usually represents the smaller ratio.
- Example for `90/10`: primary 90 percent can continue the main path, secondary
  10 percent can feed a local PLC.
- Field usage can vary, so endpoint wiring should express the actual direction.

## Phase 10: Add Manual Endpoints

Use manual endpoints when a node needs an input, output, access port, splice
terminal, or custom field port that was not generated by PLC/FBT sync.

1. Open `/nms/distribution/<node_id>/`.
2. Find `Add Endpoint`.
3. Select internal device or choose direct node endpoint.
4. Enter endpoint label.
5. Select endpoint type.
6. Enter sequence.
7. Select status.
8. Enter notes.
9. Save.
10. Confirm it appears in endpoint inventory.

Endpoint types:

- Access Port
- Uplink
- Distribution
- Split Output
- Other

Endpoint statuses:

- Available
- Occupied
- Inactive
- Damaged

Recommended labels:

- `IN`
- `OUT 1`
- `OUT 2`
- `PLC OUT 3`
- `NAP INPUT`
- `DROP 01`
- `PATCH A1`
- `SPLICE 01`

## Phase 11: Wire Endpoints

Endpoint wiring is where port-accurate mapping happens.

1. Open `/nms/distribution/<node_id>/`.
2. Find `Wire Endpoints`.
3. Choose upstream endpoint.
4. Choose downstream endpoint.
5. Choose connection type.
6. Choose wiring role.
7. If the wiring crosses physical nodes, choose the topology link it uses.
8. If it uses a tracked fiber core, choose the cable core.
9. Choose status.
10. Enter notes.
11. Save.
12. Confirm the connection appears in `Endpoint Wiring`.

Connection types:

- Fiber
- Ethernet
- Patch Cord
- Splice
- Internal Wiring
- Other

Wiring roles:

- Feeder
- Pass-through
- Splitter Input
- Splitter Output
- Drop
- Direct Client
- Other

Wiring statuses:

- Active
- Planned
- Inactive
- Damaged

Direction rule:

Always wire from upstream source to downstream user side:

```text
router port -> NAP input -> FBT input -> FBT output -> PLC input -> PLC output -> subscriber
```

Same-node examples:

```text
NAP BOX 1 input -> FBT IN
FBT SECONDARY 10% -> PLC 1x8 IN
PLC IN -> PLC OUT 1
```

Cross-node examples:

```text
Router ether7 -> NAP BOX 1 input
FBT PRIMARY 90% -> NAP BOX 2 input
Cabinet output -> Splice Box input
```

Rules:

- Same-box internal wiring does not need a topology link.
- Cross-node wiring should reference the topology link it physically uses.
- If a cable core is selected, the system can infer the topology link from that
  core.
- Cable core must belong to the selected topology link.
- One active upstream source is allowed per downstream endpoint.
- Endpoint wiring cannot connect an endpoint to itself.
- Endpoint wiring cannot create a loop.
- At least one endpoint in the wiring must belong to the node page you are
  currently managing.

## Phase 12: Sync Endpoint and Device Ports

Use sync actions when generated endpoints need to be refreshed.

PLC ports:

1. Open the node distribution page.
2. Find the PLC internal device.
3. Click `Sync PLC Ports`.
4. Confirm generated input/output count.
5. Review endpoint inventory.

FBT ports:

1. Open the node distribution page.
2. Find the FBT internal device.
3. Click `Sync FBT Ports`.
4. Confirm generated input/output count.
5. Review endpoint inventory.

Global endpoint occupancy:

1. Open `/nms/operations/`.
2. Click `Sync Endpoint Occupancy`.
3. Confirm synced endpoint count.
4. Return to distribution pages if endpoint status looks stale.

## Phase 13: Sync or Add Subscribers

Subscriber data comes from the Subscribers module.

Option A: Sync from MikroTik.

1. Open `/subscribers/`.
2. Click `Sync from MikroTik`.
3. Wait for sync to finish.
4. Search for the subscriber.
5. Open the subscriber detail page.
6. Confirm username, router, profile, IP, and MikroTik status.

Option B: Add manually.

1. Open `/subscribers/add/`.
2. Enter username.
3. Select service type.
4. Enter MikroTik password/profile if needed.
5. Enter customer contact details.
6. Select plan or monthly rate.
7. Set billing settings.
8. Set status.
9. Save.

Subscriber fields that matter for NMS:

- router
- username
- full name
- status
- MikroTik status
- plan
- IP address
- latitude
- longitude
- billing status through invoices and snapshots

## Phase 14: Update Subscriber Coordinates

Subscriber coordinates are required for visible client markers and subscriber
drop paths.

1. Open `/subscribers/`.
2. Search for the subscriber.
3. Open the subscriber detail page.
4. Click `Edit`.
5. Enter address if needed.
6. Enter latitude.
7. Enter longitude.
8. Save.
9. Open `/nms/`.
10. Turn on `Subscribers`.
11. Confirm the subscriber marker appears.

Coordinate tips:

- Use exact installation point when possible.
- For house-to-NAP drops, use the customer premises endpoint, not the barangay
  center or billing address centroid.
- For dense rows of houses, use satellite view and closer zoom.

## Phase 15: Create Basic Node Assignment When Needed

The existing subscriber detail page still has a basic node assignment panel.

Use it only as a quick first mapping or legacy transition step.

1. Open subscriber detail.
2. Find `Basic Node Assignment`.
3. Select a node.
4. Optionally enter port label.
5. Save node assignment.
6. The system creates the first Premium NMS map entry automatically.
7. Open the NMS workspace for that subscriber.
8. Convert the node-only mapping into an exact endpoint mapping when possible.

Rules:

- If a Premium NMS mapping already exists, basic node assignment is locked.
- Node-only mappings stay visible but should be treated as `Needs Review`.
- Clean new mappings should use exact endpoints.

## Phase 16: Assign Subscriber in Premium NMS Workspace

This is the clean subscriber mapping step.

1. Open subscriber detail.
2. Click `Assign in NMS`, `Reassign in NMS`, or `Open in NMS`.
3. Confirm you are on `/nms/subscribers/<subscriber_id>/`.
4. Review current topology status.
5. Select serving node.
6. Select exact endpoint.
7. Enter manual endpoint label only if endpoint tables are unavailable or the
   endpoint is not yet modeled.
8. Set topology status.
9. Enter notes.
10. Save.
11. Read the success or warning message.
12. If warned as `Needs Review`, follow the review flags.
13. Open `View Topology` to inspect the subscriber on the map.

Clean mapping status:

- `Mapped`: endpoint is selected and upstream path is complete.
- `Needs Review`: endpoint is missing, upstream path is incomplete, node-only
  mapping exists, endpoint/cable/core problem exists, or validation found a
  concern.
- `Unassigned`: no Premium NMS mapping exists.

Endpoint assignment rules:

- Exact endpoint is preferred.
- Active mappings require a serving node.
- Endpoint must belong to the selected serving node.
- Inactive or damaged endpoints cannot be assigned to active mappings.
- One endpoint can have only one active subscriber mapping.
- When an endpoint is selected, the serving node is resolved from the endpoint.

## Phase 17: Assign Cable Core to Subscriber

Use this when the subscriber mapping uses tracked fiber cores.

1. Save the Premium NMS mapping first.
2. Stay in the subscriber NMS workspace.
3. Find `Cable Core Assignments`.
4. Select an available fiber core.
5. Choose `Reserved` or `Used`.
6. Enter label if needed.
7. Enter notes.
8. Click `Assign Core`.
9. Confirm the core appears in assignments.
10. Open `/nms/links/` and inspect the related link if needed.

To release a core:

1. Open the subscriber NMS workspace.
2. Find the existing core assignment.
3. Click release/remove.
4. Confirm the core status returns through the release workflow.

Rules:

- Mapping must exist before core assignment.
- Core assignment is fiber-only.
- Inactive or damaged cables cannot receive new core assignments.
- Damaged cores cannot be assigned.
- Only available cores can receive a new structured assignment.
- Each cable core can have only one structured assignment.

## Phase 18: Verify Map Rendering

Open `/nms/` after every important mapping change.

1. Turn on `Routers`.
2. Turn on `Nodes`.
3. Turn on `Topology Links`.
4. Turn on `Subscribers`.
5. Turn on `Premium Paths`.
6. Turn on `GPS Traces` if needed.
7. Use street view for general layout.
8. Use satellite view for dense physical placement.
9. Zoom closer when nodes are very close together.
10. Click the router or router root node.
11. Click the NAP or distribution node.
12. Click topology links.
13. Click the subscriber marker.
14. Click the premium path line.
15. Confirm inspector data matches the field plan.

Map indicators:

- Router markers come from active routers with coordinates, unless represented
  by a synced router-root node.
- Node markers come from active network nodes with coordinates.
- Subscriber markers come from subscriber coordinates.
- Topology links come from physical node-to-node links with coordinates.
- Premium paths come from service attachments and computed endpoint upstream
  path.
- GPS traces come from imported trace points.

Subscriber marker meaning:

- Solid inner dot indicates network/live status when available.
- Dashed outer ring indicates billing health.
- Online dots may pulse.
- Overdue or open-balance rings may animate.

Line meaning:

- Topology link line is physical span inventory.
- Premium path line is computed subscriber service route.
- Active fiber spans and focused paths can use animated dash styling.
- Passive fiber dash animation is service/path display state, not guaranteed
  optical telemetry.

## Phase 19: Focus One Subscriber Path

Use focused topology when checking one subscriber from source to endpoint.

1. Open subscriber detail.
2. Click `View Topology`, or open `/nms/?subscriber=<subscriber_id>`.
3. Wait for the map to load.
4. Confirm the subscriber marker is visible.
5. Confirm the assigned node or endpoint is visible.
6. Confirm related topology links highlight when data is available.
7. Click the premium path.
8. Confirm whether the path says upstream complete or needs review.

If the full upstream path is incomplete:

1. Open the mapped node distribution page.
2. Check endpoint wiring.
3. Ensure the selected endpoint has an upstream source.
4. Add missing endpoint connections.
5. Reference topology links for cross-node wiring.
6. Return to subscriber workspace.
7. Save or refresh review state.
8. Reopen focused topology.

## Phase 20: Run Operations Validation

Use `/nms/operations/` as the NMS health center.

1. Open `/nms/operations/`.
2. Review the validation report.
3. Read severity, category, title, and message.
4. Click action links where available.
5. Fix the underlying issue.
6. Return to operations.
7. Click `Refresh Review States`.
8. Click `Sync Endpoint Occupancy`.
9. Click `Sync Router Roots & Ports` if router data or coordinates changed.
10. Click `Sync Core Assignment Status` if cable/core assignment state may be
    stale.
11. Confirm the report improves.

Operation buttons:

- `Refresh Review States`: recalculates subscriber NMS review flags and mapping
  state.
- `Sync Endpoint Occupancy`: recalculates endpoint occupied/available state from
  active service attachments.
- `Sync Router Roots & Ports`: creates or updates router root nodes and router
  ethernet endpoints.
- `Sync Core Assignment Status`: syncs structured subscriber core assignments
  back to cable core statuses and labels.

Typical issues to fix:

- subscriber mapping has no endpoint
- endpoint has no upstream path
- endpoint is inactive or damaged
- subscriber has coordinates missing
- topology link has missing coordinates
- fiber cable has no usable cores
- cable core assignment status mismatch
- cross-node endpoint wiring has no topology link
- cable core belongs to a different topology link

## Phase 21: Use Analytics

Use `/nms/analytics/` for planning and review.

Route distance report:

1. Open `/nms/analytics/`.
2. Review route distance rows.
3. Compare geometry distance and cable inventory distance.
4. Fix geometry or cable length if the report exposes wrong data.

Outage impact trace:

1. Open `/nms/analytics/`.
2. Select outage type: node or link.
3. Select node or link.
4. Run trace.
5. Review impacted downstream nodes and subscribers.
6. Use the result for field dispatch or customer support.

Cable utilization:

1. Open `/nms/analytics/`.
2. Review cable utilization.
3. Look at used cores versus total cores.
4. Plan expansion before links are exhausted.

Power budget estimates:

1. Open `/nms/analytics/`.
2. Review subscriber estimates.
3. Look for splitters and long route risks.
4. Treat this as an estimate unless actual optical measurements are integrated.

GPS trace management:

1. Import survey or as-built trace.
2. Use it as visual reference on the map.
3. Load it into geometry editing when matching route vertices.
4. Delete obsolete traces when no longer useful.

## Complete Scenario A: Router to NAP to Subscriber Through PLC

Use this for a typical fiber subscriber served from a NAP PLC output.

1. Add router in `/routers/`.
2. Test router API connection.
3. Save router.
4. Sync router.
5. Update router coordinates.
6. Open `/nms/operations/`.
7. Click `Sync Router Roots & Ports`.
8. Open `/nms/nodes/`.
9. Create `NAP BOX 1` with coordinates.
10. Open `/nms/`.
11. Use `Connect Nodes`.
12. Select router root node as source.
13. Select `NAP BOX 1` as target.
14. Create a fiber topology link.
15. Open `/nms/links/`.
16. Select the new link.
17. Add fiber cable inventory.
18. Enter cable name, total cores, install type, and status.
19. Save.
20. Open distribution detail for `NAP BOX 1`.
21. Add a direct node endpoint labeled `NAP INPUT`.
22. Add internal device `PLC 1`.
23. Set device type to PLC.
24. Set PLC model to `1x8`.
25. Save and generate PLC ports.
26. Wire router ethernet endpoint to `NAP INPUT`.
27. Select connection type `Fiber`.
28. Select role `Feeder`.
29. Select the router-to-NAP topology link.
30. Select a cable core if tracked.
31. Save wiring.
32. Wire `NAP INPUT` to `PLC 1 / IN`.
33. Use connection type `Internal Wiring` or `Patch Cord`.
34. Use role `Splitter Input`.
35. Save wiring.
36. Sync subscribers or add subscriber.
37. Edit subscriber coordinates.
38. Open subscriber detail.
39. Open Premium NMS workspace.
40. Select `NAP BOX 1`.
41. Select `PLC 1 / OUT 1` or the correct output.
42. Save mapping.
43. Assign cable core in subscriber workspace if needed.
44. Open `View Topology`.
45. Confirm premium path is visible.
46. Run `/nms/operations/` validation.

## Complete Scenario B: FBT 90/10 Feeding NAP 2 and PLC 1x8

Use this when one FBT output continues the main line and the smaller split feeds
a local PLC.

1. Sync router and coordinates.
2. Sync router roots and ports.
3. Create `NAP BOX 1`.
4. Create `NAP BOX 2`.
5. Create topology link `Router Site -> NAP BOX 1`.
6. Create topology link `NAP BOX 1 -> NAP BOX 2`.
7. Add cable/core inventory on fiber links if tracked.
8. Open distribution detail for `NAP BOX 1`.
9. Add direct endpoint `NAP 1 INPUT`.
10. Add FBT internal device.
11. Set FBT ratio to `90/10`.
12. Save and generate FBT endpoints.
13. Add PLC internal device.
14. Set PLC model to `1x8`.
15. Save and generate PLC endpoints.
16. Wire router ethernet endpoint to `NAP 1 INPUT`.
17. Attach that wiring to `Router Site -> NAP BOX 1` topology link.
18. Select cable core if tracked.
19. Wire `NAP 1 INPUT` to `FBT IN`.
20. Wire `FBT PRIMARY 90%` to `NAP BOX 2` input.
21. Attach that cross-node wiring to `NAP BOX 1 -> NAP BOX 2` topology link.
22. Wire `FBT SECONDARY 10%` to `PLC IN`.
23. Wire PLC output to subscriber through subscriber NMS workspace assignment.
24. Open the focused subscriber topology map.
25. Confirm the path follows router to NAP 1, internal split, PLC output, and
    subscriber drop.
26. Run operations validation.

## Complete Scenario C: Direct Router Ethernet Subscriber

Use this when a client is connected directly to a router port, such as
`ether7`.

1. Add and sync the router.
2. Update router coordinates.
3. Open `/nms/operations/`.
4. Click `Sync Router Roots & Ports`.
5. Confirm router ethernet endpoints exist.
6. Sync or add the subscriber.
7. Edit subscriber coordinates.
8. Open subscriber Premium NMS workspace.
9. Select the router root node.
10. Select the exact router ethernet endpoint, such as `Router Port / ether7`.
11. Save mapping.
12. If the direct cable route should be inventoried, create a topology link or
    tracked drop span for that physical route.
13. Edit subscriber drop geometry if the route is not straight.
14. Open map and verify the direct premium path.
15. Use interface telemetry to help read live status when available.

## Complete Scenario D: Legacy Node-Only Subscriber Cleanup

Use this when old subscribers have only basic node assignment.

1. Open `/subscribers/`.
2. Search for subscriber.
3. Open subscriber detail.
4. Confirm topology summary shows basic node or needs review.
5. Open NMS workspace.
6. Confirm node is preselected from basic assignment.
7. Select exact endpoint.
8. Save.
9. Assign cable core if needed.
10. Open map.
11. Confirm the subscriber path is still visible.
12. Run operations validation.
13. Repeat for other node-only subscribers.

## Complete Scenario E: Survey Route Correction Using GPS Trace

Use this after field team records a route.

1. Open `/nms/analytics/`.
2. Import GPS trace from survey log.
3. Open `/nms/`.
4. Turn on GPS traces.
5. Switch to `Edit Path`.
6. Click the topology link that follows the surveyed route.
7. Load the GPS trace.
8. Review middle vertices.
9. Remove bad points if needed.
10. Save geometry.
11. Inspect route distance in analytics.
12. Update cable length if the measured cable inventory differs.

## Delete and Cleanup Guide

Deleting topology links:

1. Open `/nms/links/`.
2. Select the link.
3. Review cable/core inventory and endpoint wiring that uses it.
4. Confirm it is safe to remove.
5. Delete the topology link.
6. Rebuild or reassign endpoint wiring if needed.
7. Run operations validation.

Deleting nodes:

1. Open `/nms/nodes/`.
2. Select the node.
3. Review delete impact.
4. Confirm affected mappings, subscriber node references, topology links,
   internal devices, endpoints, cables, cable cores, and core assignments.
5. Delete only when this physical node is truly being removed from NMS.
6. Confirm routers, subscribers, billing, and account records are kept.
7. Reassign affected subscribers if needed.
8. Run operations validation.

Removing subscriber NMS mapping:

1. Open subscriber Premium NMS workspace.
2. Review active mapping and cable core assignments.
3. Click remove mapping.
4. Confirm cable core assignments are released.
5. Confirm basic node summary is kept.
6. Reassign later if needed.

## Troubleshooting

Router not visible on map:

1. Confirm router is active.
2. Confirm latitude and longitude are saved.
3. Open `/nms/operations/`.
4. Click `Sync Router Roots & Ports`.
5. Refresh `/nms/`.
6. Check whether the router is represented as a router-root node instead of a
   separate router marker.

Router ports not available as endpoints:

1. Confirm router was synced.
2. Confirm interfaces exist in router detail.
3. Confirm interfaces are physical ethernet.
4. Open `/nms/operations/`.
5. Click `Sync Router Roots & Ports`.
6. Open router root distribution detail and inspect endpoints.

Subscriber not visible on map:

1. Confirm subscriber has latitude and longitude.
2. Confirm subscriber was saved after coordinate update.
3. Turn on `Subscribers` in map visibility.
4. Search subscriber list and open detail.
5. Check account status and mapping state.

Premium path not visible:

1. Confirm subscriber has coordinates.
2. Confirm mapped node has coordinates.
3. Confirm Premium NMS mapping exists.
4. Confirm `Premium Paths` is enabled on the map.
5. Confirm selected endpoint or node still exists.
6. Refresh review states in `/nms/operations/`.

Full upstream path is incomplete:

1. Open subscriber NMS workspace.
2. Read review flags.
3. Open mapped node distribution detail.
4. Confirm selected endpoint has upstream endpoint connection.
5. Confirm cross-node wiring references topology links.
6. Confirm topology links have correct direction.
7. Save missing endpoint wiring.
8. Refresh review states.

Cannot assign endpoint:

1. Confirm endpoint belongs to the selected node.
2. Confirm endpoint is not inactive.
3. Confirm endpoint is not damaged.
4. Confirm endpoint is not already occupied by another active subscriber.
5. Run endpoint occupancy sync.

Cannot assign cable core:

1. Confirm subscriber mapping is saved.
2. Confirm topology link is fiber.
3. Confirm fiber cable inventory exists.
4. Confirm the core is available.
5. Confirm cable is not inactive or damaged.
6. Confirm core is not damaged.
7. Confirm the core is not already assigned.

Geometry save fails:

1. Check each line uses `lat,lng`.
2. Remove extra words unless they are in GPS trace import, not geometry editor.
3. Remove blank invalid lines.
4. Confirm latitude and longitude are valid numbers.
5. Save again.

Map feels cluttered:

1. Toggle off GPS traces.
2. Toggle off premium paths.
3. Filter link type.
4. Filter link status.
5. Use satellite view for dense areas.
6. Focus one subscriber from subscriber detail or workspace.

Billing ring looks wrong:

1. Open subscriber detail.
2. Check invoices and snapshots.
3. Check latest payment allocation.
4. Confirm billing status is expected.
5. Regenerate or review billing snapshot if needed.

Live dot looks wrong:

1. Check subscriber MikroTik status.
2. Check router online status.
3. Check interface traffic cache.
4. Check diagnostics if telemetry is stale.
5. Resync router or subscriber if needed.

## Daily Operator Checklist

1. Open `/nms/operations/`.
2. Review validation issues.
3. Sync router roots and ports after router/interface changes.
4. Sync endpoint occupancy after bulk subscriber mapping work.
5. Sync core assignment status after cable/core edits.
6. Open `/nms/`.
7. Verify topology links and premium paths.
8. Open `/nms/analytics/`.
9. Check outage impact or cable utilization when planning field work.
10. Fix `Needs Review` mappings before considering NMS data clean.

## Recommended Data Hygiene

1. Always add coordinates before expecting map visibility.
2. Name nodes consistently.
3. Keep topology link direction upstream to downstream.
4. Keep endpoint wiring direction upstream to downstream.
5. Use topology links for physical spans.
6. Use endpoint connections for port wiring.
7. Use service attachments for subscriber assignment.
8. Use subscriber drop geometry only for final client branch route.
9. Use cable core assignments when fiber core inventory matters.
10. Run validation after bulk changes.
11. Do not use map drawing as a substitute for port wiring.
12. Do not duplicate upstream feeder geometry inside every subscriber path.
13. Keep old node-only mappings visible but review and upgrade them to exact
    endpoint mappings.

## Final Clean Mapping Definition

A subscriber mapping is clean when all of these are true:

1. Subscriber exists.
2. Subscriber has coordinates.
3. Subscriber has a Premium NMS `ServiceAttachment`.
4. Service attachment has serving node.
5. Service attachment has exact endpoint.
6. Endpoint is available/occupied correctly and not damaged/inactive.
7. Endpoint has valid upstream path unless it is a valid source endpoint.
8. Cross-node endpoint wiring references the physical topology link it uses.
9. Cable core assignment is valid if a tracked fiber core is required.
10. Topology links have correct source/target coordinates.
11. Premium path renders on the map.
12. Operations validation has no blocking issue for that subscriber.
