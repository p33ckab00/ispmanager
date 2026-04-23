# Network Topology Engine Implementation Plan

## Summary

This document defines the implementation plan for evolving the current `apps/nms` map into a structured topology, fiber inventory, and provisioning workspace.

This is a `planning-only` document.

- no code was generated in this task
- no implementation was applied
- this document breaks the recommended design into realistic phases before development begins

## Baseline and Problem Statement

Current NMS behavior is intentionally simple:

- routers and subscribers can appear on a map if they have coordinates
- there is no first-class representation for links, paths, cables, splitter internals, or assignment locks

That is useful as an operational overview, but it does not yet support:

- structured FTTH topology
- cable and core utilization
- NAP internals
- PLC and FBT behavior
- service assignment validation
- route editing with persistent geometry

The goal of this plan is to grow the current map into a real network inventory and topology system without turning the map into an unstructured drawing board.

## Primary Goals

- make the map a visual layer of structured network data
- support fiber, ethernet, wireless, and subscriber-drop relationships in one topology model
- allow node placement and path editing without sacrificing inventory integrity
- support optical distribution modeling for OLT, NAP, PLC, and FBT workflows
- prevent invalid assignments such as duplicate subscriber or PLC-port linkage

## Non-Goals for First Delivery

The first implementation should not attempt all advanced telecom behavior at once.

Non-goals for the early phases:

- full optical power-budget calculation
- outage impact simulation across every dependency
- automatic path inference from arbitrary geometry
- full GIS feature parity
- field workforce mobile capture suite
- rendering every cable core as a separate permanent map line

## Recommended Product Scope by Phase

### Phase 1. Structured Topology Foundation

Goal:

- move from point-only visibility to structured nodes, links, and path geometry

Recommended scope:

- add a generic `Node` concept for topology objects
- add a generic `Link` concept for connections
- support core node types needed for first rollout:
  - Router
  - OLT
  - NAP
  - Access Point
  - Pisowifi Device
  - Subscriber Location
  - Pole
  - Cabinet
- add map placement and coordinate editing
- add link creation between nodes
- add persistent path geometry with editable middle vertices
- add basic link typing:
  - fiber
  - ethernet
  - wireless
  - subscriber drop

Expected outcome:

- the product becomes a real topology workspace
- not yet full fiber-internals management

### Phase 2. Cable and Fiber Capacity Management

Goal:

- attach structured cable inventory to topology links

Recommended scope:

- introduce cable records with:
  - cable name or code
  - source and destination
  - total cores
  - installed status
  - aerial or underground flag
  - length
- introduce core records with:
  - core number
  - color
  - status
  - assigned use
- add cable and core inventory page
- add used versus spare summary on link detail

Expected outcome:

- fiber capacity becomes measurable and auditable

### Phase 3. Passive Devices and NAP Internals

Goal:

- support realistic optical distribution inside NAPs and related enclosures

Recommended scope:

- introduce internal devices under parent nodes
- support passive device types:
  - PLC
  - FBT
  - splice tray
  - patch panel
- add NAP internal detail view
- add PLC input and output inventory
- add FBT ratio configuration and output roles
- add splice and internal mapping views

Expected outcome:

- the system can model actual downstream optical distribution rather than only trunk connectivity

### Phase 4. Subscriber Provisioning and Eligibility Rules

Goal:

- connect service assignments to real topology resources

Recommended scope:

- introduce assignment records that bind subscriber service to an access endpoint
- support assignment sources such as:
  - PLC output
  - AP sector
  - direct router endpoint
- add subscriber assignment page
- hide already linked subscribers from normal unassigned lists
- hide occupied PLC outputs from available endpoint lists
- support unlink and reassign flows with auditability

Expected outcome:

- the topology model becomes operational for provisioning and capacity control

### Phase 5. Validation and Operational Warnings

Goal:

- prevent bad data from accumulating as the network grows

Recommended scope:

- duplicate core-use validation
- duplicate endpoint-assignment validation
- incompatible connection warnings
- dependency warnings on delete or unlink
- broken route or missing geometry alerts
- spare-capacity and occupancy summaries

Expected outcome:

- the system starts protecting operators from invalid or dangerous edits

### Phase 6. Field and Advanced Analytics Enhancements

Goal:

- improve real-world usability for field and operations teams

Recommended scope:

- GPS trace import
- coordinate-table editor improvements
- route simplification tools
- outage impact tracing
- optical budget estimation
- area-level capacity analytics

Expected outcome:

- advanced NOC and field workflows become possible without redesigning the core model

## Recommended Page Architecture

The best product shape is a map-centered workspace with detail pages for form-heavy tasks.

### 1. Map / Topology Workspace

Purpose:

- operational visualization and editing

Recommended functions:

- add node by click
- connect nodes
- select and inspect objects
- edit path vertices
- toggle layers
- switch work modes

Recommended layout:

- left inventory tree and filters
- center map canvas
- right detail sidebar
- optional bottom drawer for coordinates, warnings, or assignment tables

### 2. Nodes Page

Purpose:

- inventory table and form management for nodes

Recommended functions:

- filters by type, status, area, installation state
- bulk visibility of coordinates and linked counts
- form editing for selected node

### 3. Links and Cable Page

Purpose:

- dedicated management of topology links and physical cable inventory

Recommended functions:

- inspect connection endpoints
- edit cable metadata
- inspect core utilization
- review route length and status

### 4. OLT Management Page

Purpose:

- handle OLT-specific density and capacity data outside the map

Recommended functions:

- PON overview
- uplinks
- linked fibers
- served NAP relationships
- capacity summary

### 5. NAP and Passive Devices Page

Purpose:

- manage internal passive distribution clearly

Recommended functions:

- incoming fibers
- PLC and FBT inventory
- internal mapping
- splice view
- downstream service visibility

### 6. Subscriber Assignment Page

Purpose:

- controlled provisioning

Recommended functions:

- show available subscribers
- show eligible endpoints only
- assign, unlink, and reassign
- record drop details and service notes

### 7. Validation and Alerts Page

Purpose:

- surface conflicts and cleanup tasks

Recommended functions:

- invalid assignment queue
- over-capacity warnings
- unlinked or orphaned records
- geometry and dependency warnings

## Recommended Domain Model Direction

The implementation should prefer a generic topology-first model with type-specific extension data.

### Core entities

Recommended core entities:

- `Site` or `Area`
- `Node`
- `InternalDevice`
- `Port`
- `Link`
- `Cable`
- `Core`
- `Geometry`
- `Assignment`

### Modeling principle

Keep shared structure centralized:

- type
- status
- parent relationships
- coordinates
- connection references

Keep specialized behavior in type-specific configuration:

- router interfaces and IP metadata
- OLT PON port data
- PLC output counts
- FBT ratio behavior
- AP capacity rules

This avoids brittle page-per-type logic and keeps future support extensible.

## Map Interaction Plan

The map should be mode-driven.

Recommended modes:

- `View`
- `Add Node`
- `Connect`
- `Edit Path`
- `Assign Subscriber`
- `Fiber Core View`

### Add Node flow

1. user clicks map
2. system captures coordinates
3. small drawer asks for node type and basic identity
4. node is created
5. user can complete detailed configuration in sidebar or detail page

### Connect flow

1. user selects source
2. user selects target
3. system asks for link type
4. if fiber, system requests cable defaults
5. link is created with simple initial geometry

### Edit Path flow

1. user selects link
2. geometry handles appear
3. user adds, drags, or removes vertices
4. user may also switch to manual coordinate entry
5. advanced workflows may later support GPS import

## Validation Plan

The topology system should eventually enforce rules such as:

- a PLC output can only have one active subscriber assignment
- the same subscriber should not appear as available when already actively linked
- used cores cannot exceed cable capacity
- the same core should not be reused on the same cable segment
- incompatible node or port connections should trigger warning or block
- deleting nodes with dependent active links should require explicit confirmation and review
- moving a node should update connected link endpoints while preserving middle geometry

Validation should be added incrementally rather than all at once, but the data model should anticipate these constraints from the start.

## Migration and Adoption Strategy

The project already has router and subscriber coordinate data.

Recommended transition path:

### Step 1. Preserve current visibility value

Keep the existing simple map usable while the topology model is introduced.

### Step 2. Bootstrap known object types

Seed early topology records from existing operational objects where practical:

- routers
- subscribers with coordinates

### Step 3. Add manual infrastructure encoding

Allow staff to encode OLTs, NAPs, passive devices, and links gradually instead of requiring a one-time full network import.

### Step 4. Move provisioning onto structured assignments

Only after endpoint and passive-device modeling exist should subscriber assignment behavior start relying on the topology layer.

This reduces delivery risk and keeps the product useful through the transition.

## Recommended Acceptance Criteria by Rollout Wave

### Foundation acceptance criteria

- operators can add and place nodes on a map
- operators can connect nodes with typed links
- links retain editable geometry
- moving a node updates link endpoints correctly

### Fiber acceptance criteria

- operators can define a cable and its total cores
- used and spare capacity is visible per cable
- a link can show route and cable details without requiring map clutter

### Passive-device acceptance criteria

- NAP internals can store PLC and FBT devices
- PLC outputs show available versus occupied states
- passive-device placement is managed without cluttering the main map

### Provisioning acceptance criteria

- only eligible unlinked subscribers appear in normal assignment flows
- occupied endpoints do not appear as available choices
- unlinking restores endpoint availability

### Validation acceptance criteria

- invalid duplicate use cases are blocked or clearly warned
- dependency-breaking deletes require review
- warnings are visible in a dedicated operational view

## Key Risks and Design Guards

### Risk 1. Turning the map into a freehand editor

Guard:

- never let drawn lines become the source of truth without structured records behind them

### Risk 2. Hiding too much complexity inside one page

Guard:

- use the map for placement, connection, and visibility
- use sidebars and dedicated pages for deep configuration

### Risk 3. Overfitting early models to one technology path

Guard:

- use generic node, link, endpoint, and assignment concepts
- keep FTTH-specific behavior in type-aware configuration

### Risk 4. Building all telecom rules before basic usability exists

Guard:

- prioritize structured topology, then capacity, then provisioning rules, then advanced validation

## Final Recommendation

The best long-term path is:

- a map-centered topology workspace
- backed by structured inventory, cable, endpoint, and assignment models
- with dedicated pages for OLT, NAP internals, cable management, and subscriber assignment

The map should remain the operational visual layer.
It should not become the place where every technical rule lives.

That separation is what will keep the system extensible for:

- FTTH growth
- wireless backhaul
- pisowifi chains
- direct subscriber links
- future route analytics
- future optical-budget and outage tracing
