# Network Topology Engine Discussion

## Summary

This document captures the product and architecture direction for evolving the current network map into a structured topology and provisioning system.

This is a `discussion-only` document.

- no code was generated
- no implementation was applied
- this document records the recommended long-term design before any model, API, or UI work begins

## Current Baseline

The repository already includes a basic `apps/nms` map view.

Current behavior:

- renders routers and subscribers on a Leaflet map
- reads coordinates directly from existing `Router` and `Subscriber` records
- supports visibility toggles and refresh
- does not yet model structured links, cables, ports, splitters, internal devices, or assignment rules

Important conclusion:

- the current map is a geographic visibility view
- it is not yet a real network inventory or topology engine

## Core Product Principle

The map should not become a drawing tool with ad hoc lines and labels.

The correct long-term design is:

- `inventory first`
- `topology second`
- `map as visual layer`

Meaning:

- physical and logical objects must exist as structured records
- the map should render those records
- provisioning and validation should run on structured relationships, not on drawn shapes alone

The most important framing is:

- `Node` = physical object
- `Link` = physical or logical connection
- `Config` = capacity, behavior, or type-specific settings
- `Assignment` = actual resource usage

## Recommended Architecture Layers

The best design is to split the solution into five major layers.

### 1. Asset Inventory

This layer stores real network objects such as:

- routers
- OLTs
- NAP boxes
- PLC splitters
- FBT splitters
- access points
- pisowifi devices
- subscriber endpoints
- poles
- cabinets
- junction boxes
- patch panels

This layer answers:

- what exists
- where it is
- what type it is
- whether it is active, installed, planned, damaged, or archived

### 2. Topology and Connectivity

This layer stores how assets connect to each other.

Examples:

- router to OLT
- OLT to NAP
- NAP to next NAP
- AP to upstream router
- subscriber to PLC output

This layer must support:

- node-to-node relationships
- port-to-port relationships where needed
- link type distinctions such as fiber, ethernet, wireless backhaul, or subscriber drop

### 3. Fiber Capacity and Split Modeling

This layer handles optical distribution details such as:

- cable core counts
- used versus spare cores
- core color mapping
- PLC type and output usage
- FBT ratio behavior
- passive device placement inside a NAP or closure

This is the layer that makes the system operationally useful for FTTH and hybrid fiber networks.

### 4. Map and Path Editor

This layer is the visual workspace.

Responsibilities:

- place nodes on the map
- render topology links
- edit path vertices
- show route length and path geometry
- toggle layers and density
- provide quick operational context

This layer should not become the only place where technical configuration happens.

### 5. Provisioning and Assignment Rules

This layer controls actual usage.

Examples:

- which subscriber is attached to which PLC output
- which OLT port serves which downstream path
- whether a subscriber endpoint is still available
- whether an assigned port should disappear from future selection lists

This layer is what prevents the system from becoming visually impressive but operationally unsafe.

## Recommended Domain Model

The safest long-term direction is a generic topology-first model with type-specific configuration.

### Site or Area

Represents a service area, project area, municipality, cluster, or operational region.

Recommended responsibilities:

- grouping of nodes
- filtering and access scope
- optional map defaults and service boundaries

### Node

Represents a physical object on the map.

Recommended base fields:

- `type`
- `name`
- `status`
- `latitude`
- `longitude`
- `location note`
- `installation state`
- `parent site or area`

Examples of node types:

- Router
- OLT
- NAP Box
- Access Point
- Pisowifi Device
- Pole
- Cabinet
- Junction Box
- Patch Panel
- Subscriber Location

### Internal Device

Represents devices housed inside another node.

Examples:

- PLC splitter inside a NAP
- FBT inside a closure
- splice tray inside a cabinet
- patch panel inside an enclosure

Important design principle:

- internal devices should usually not clutter the main map
- they should appear inside the selected node detail context

### Port or Endpoint

Represents the actual connection point on a node or internal device.

Examples:

- router interface
- OLT PON port
- PLC output port
- AP uplink port
- subscriber drop termination

This is important because links often connect endpoints, not just node bubbles.

### Link

Represents a connection between two nodes or endpoints.

Recommended types:

- Fiber
- Ethernet
- Wireless backhaul
- Subscriber drop
- logical service path if needed later

Recommended responsibilities:

- stores connection intent
- stores operational status
- references endpoints
- references geometry
- references cable details when the link is cable-backed

### Cable

Represents the physical cable attached to a link.

Recommended fields:

- cable code or name
- cable type
- total cores or pairs
- aerial or underground
- installed date
- length
- status

### Core

Represents an individual fiber core.

Recommended fields:

- core number
- standard color
- status
- assigned use

This supports proper fiber inventory without forcing every cable to be drawn as separate lines.

### Geometry

Represents the path of a link.

Recommended structure:

- source endpoint follows source node location
- destination endpoint follows destination node location
- middle vertices are stored as ordered editable points

This keeps geometry stable when nodes move while preserving the path shape.

### Assignment

Represents actual usage of an access resource.

Examples:

- subscriber assigned to PLC output 7
- subscriber assigned to AP sector
- subscriber assigned to direct router port

This is the layer that drives availability filtering.

## Recommended Page Architecture

The system should not force everything into a single map page.

The best page set is a map-centered workspace plus dedicated detail pages for complex operations.

### 1. Map / Topology Page

This is the primary visual workspace.

Recommended responsibilities:

- show nodes and links
- add node by map click
- connect nodes
- edit path vertices
- view utilization summaries
- switch visual modes

Recommended toolbar:

- Add Node
- Add Link
- Edit Path
- Splitter Mode
- Fiber Core View
- Subscriber Assignment View
- GPS Capture
- Layer Toggles

### 2. Node Management Page

This is the inventory and form-centric page for node configuration.

Recommended responsibilities:

- edit device identity and type
- edit coordinates and location metadata
- edit notes and installation state
- view linked devices and child devices
- manage type-specific properties

### 3. Links and Cable Management Page

This page manages physical and logical connections.

Recommended responsibilities:

- view source and destination
- manage link type
- manage cable details
- inspect route length
- inspect used versus spare capacity

### 4. OLT Management Page

This page handles OLT-specific operational complexity.

Recommended responsibilities:

- PON ports
- uplinks
- served downstream areas
- connected fibers
- capacity view

### 5. NAP and Passive Devices Page

This page handles NAP internals and passive optical distribution.

Recommended responsibilities:

- incoming fibers
- splice mapping
- FBT devices
- PLC devices
- internal layout
- downstream subscriber reach

### 6. Subscriber Assignment Page

This page is the provisioning layer.

Recommended responsibilities:

- show eligible unlinked subscribers
- show available assignable endpoints
- create assignment
- unlink or reassign
- record drop details

### 7. Validation and Alerts Page

This page surfaces operational conflicts.

Examples:

- duplicate resource assignments
- overused cable cores
- incomplete paths
- unlinked subscribers waiting for service
- broken routes after asset deletion or relocation

## Recommended Map UX

The map needs explicit modes instead of one overloaded cursor.

Recommended modes:

- `View`
- `Add node`
- `Connect`
- `Edit path`
- `Assign subscriber`
- `Fiber core visualization`

Reason:

- reduces accidental edits
- makes intent clear
- keeps complex actions predictable

### Add Node Behavior

Recommended flow:

1. user clicks the map
2. system opens a small drawer or modal
3. user chooses node type
4. coordinates are auto-filled from the click
5. user saves and then completes type-specific details

### Connect Behavior

Recommended flow:

1. user selects source node or endpoint
2. user selects target node or endpoint
3. system asks for connection type
4. if fiber, system asks for cable properties and capacity
5. system creates a straight path by default
6. user can refine the route later in path edit mode

### Edit Path Behavior

Recommended capabilities:

- click line to add vertex
- drag vertex to move
- delete vertex
- manually encode coordinates
- import GPS trace or field points

## Fiber and Splitter Modeling Direction

The map will remain limited if fiber and passive devices are stored as plain text notes.

### Fiber Cable Requirements

Each cable should support:

- cable code
- source and destination
- total cores
- color scheme
- used and spare counts
- route length
- status
- physical installation type

Recommended visual behavior:

- default map view shows one cable line
- sidebar or popup shows core breakdown
- advanced mode may optionally show parallel color strands

### FBT Requirements

An FBT should not be stored only as a text value such as `80/20`.

Recommended behavior model:

- ratio
- one input
- multiple outputs
- designated pass-through output
- designated split output
- hosted inside a parent node

Reason:

- enables topology tracing
- supports future power-budget estimation
- makes path validation possible

### PLC Requirements

A PLC should have a real output model.

Recommended fields:

- type such as `1x4`, `1x8`, `1x16`, `1x32`
- input count
- output count
- used outputs
- available outputs
- housed inside which parent node

This is necessary for proper assignment locking and operational visibility.

## Assignment and Eligibility Logic

The key provisioning rule is:

- if a resource is already linked, it should not appear in normal available-assignment lists

This must apply to both sides of the assignment.

### Subscriber Rules

A subscriber should usually have:

- zero or one active physical access path per service

The subscriber should disappear from generic unlinked assignment pools once linked, unless:

- unlinked
- disconnected
- archived
- explicitly filtered for reassign flows

### PLC Port Rules

A PLC output port should support:

- one active assignment at a time

Once assigned:

- port becomes occupied
- port is hidden from standard available lists

### AP and Router Endpoint Rules

Wireless or direct ethernet resources may allow multiple clients, but still need capacity and eligibility rules.

Examples:

- AP sector may support multiple clients up to configured limits
- router interface may be single-assignment or shared depending on service model

This is why availability must be rule-driven, not just filter-driven.

## Recommended Detail Views by Object

### Router

Recommended sidebar tabs:

- Details
- Ports
- Links
- Connected Devices
- Notes
- Map Position

### OLT

Recommended sidebar tabs:

- Details
- PON Ports
- Uplink Ports
- Connected Fibers
- Served NAPs
- Capacity

### NAP

Recommended sidebar tabs:

- Details
- Incoming Fibers
- Internal Devices
- FBT and PLC Layout
- Subscribers Served
- Splice or Port Mapping

### PLC

Recommended sidebar tabs:

- Details
- Input
- Outputs
- Port Assignment
- Availability

### Link

Recommended sidebar tabs:

- Details
- Endpoints
- Path Vertices
- Fiber Cores
- Utilization
- Route Length

## Internal Device Handling

A major usability rule is to avoid overloading the main map with every internal splitter object.

Recommended behavior:

- main map shows the outer node such as NAP or cabinet
- internal device management happens inside the node detail context

Example inside a NAP:

- incoming fiber lands on splice or tray
- FBT taps one branch and passes through another
- PLC outputs serve subscriber drops

This is far clearer than drawing every internal passive object on the large-area map at all times.

## Validation Rules That Must Exist

At minimum, the topology engine should eventually enforce rules such as:

- PLC output cannot be assigned to multiple subscribers at the same time
- same fiber core cannot be assigned twice on the same segment
- used cores cannot exceed cable capacity
- already linked subscriber cannot be assigned again through normal flows
- incompatible node types should warn before connection
- active dependent links should block unsafe node deletion unless explicitly forced
- unlinking a PLC port makes it available again
- moving a node updates connected link endpoints
- deleting a link triggers dependency review for assignments and served paths

## Recommended UI Shell

The most practical working layout is:

- left panel for asset tree and filters
- center canvas for the map
- right sidebar for selected-object details
- optional bottom panel for coordinates, logs, warnings, and assignment lists

This is more scalable than a pure full-screen map because many network tasks are form-heavy and table-heavy.

## Recommended Long-Term Architecture Principle

The strongest design recommendation is:

- use a generic topology engine with type-specific configuration panels

Do not hardcode all future behavior into separate disconnected pages like only `router page`, `OLT page`, or `NAP page`.

Why this matters:

- the system already serves mixed ISP realities
- future support may include wireless backhaul, direct ONU links, pisowifi chains, splice closures, and power-budget logic
- a generic engine makes those additions incremental instead of destructive

## Suggested Rollout Philosophy

Do not build every advanced rule on day one.

The right progression is:

1. structured nodes and links
2. path editing and cable basics
3. passive device and subscriber assignment logic
4. deeper validation and optical behavior
5. field tooling such as GPS trace import and route analytics

That keeps the product usable early while protecting long-term architecture quality.
