# Premium NMS Phased Implementation Plan

## Summary

This document defines the recommended phased rollout for `Premium NMS`.

The main goal is to build premium topology capability without destabilizing the current production workflows that already depend on the `Subscribers` module, billing flows, and existing operational pages.

The safest implementation direction is:

- keep `Subscribers` as the source of truth for customer and billing state
- build `Premium NMS` as a separate but integrated physical-network workspace
- ship value in stages instead of attempting the entire target-state topology suite in one release

This phased approach reduces rollout risk, keeps the product usable during implementation, and creates natural checkpoints for validation before the next layer is added.

## Why a Phased Rollout Is Recommended

The Premium NMS vision is broad.

It includes:

- topology state
- service attachment
- map workspace
- path editing
- passive optical distribution
- cable and core inventory
- validation and alerts
- later field and analytics tools

Trying to ship all of that in one implementation wave would create unnecessary risk.

The main risks of a one-shot build would be:

- unclear ownership between `Subscribers` and `NMS`
- broken billing or subscriber workflows
- hard-to-test topology logic
- too many unfinished UI states at the same time
- production rollout pressure before the operational model is proven

This is why Premium NMS should be rolled out in controlled phases.

## Guiding Principles

### 1. Protect the Core Product

The existing `Subscribers` module must remain stable.

Core operations such as:

- creating subscribers
- updating plans
- billing
- payments
- lifecycle changes

must keep working even if Premium NMS is not enabled.

### 2. Build Premium Value Early

Each phase should provide a usable premium improvement, not just hidden infrastructure.

This helps validate product direction earlier and reduces the risk of building a large feature stack that nobody can use until the very end.

### 3. Separate Account Truth From Physical Network Truth

The product boundary must remain consistent:

- `Subscribers` owns customer and billing truth
- `NMS` owns physical topology and advanced network assignment truth

### 4. Avoid Bypass Paths

Whenever premium topology state exists, core subscriber pages should not silently override it using simpler UI shortcuts.

That means the phased rollout must include clear transition rules for:

- basic node association
- premium attachment
- reassignment
- review states

## Phase 1: Premium NMS Foundation

### Goal

Establish the first real premium NMS behavior while keeping implementation scope controlled.

This phase creates the operational boundary between `Subscribers` and `NMS`.

### Included

- topology or NMS domain foundation
- topology status per subscriber
- `Open in NMS`
- `Assign in NMS`
- `View Topology`
- `Reassign in NMS`
- `ServiceAttachment`
- one active physical path rule
- basic node to premium mapping promotion
- subscriber page network summary only

### Not Yet Included

- full map-heavy editing
- PLC internals
- FBT logic
- cable and core tracking
- advanced validation center
- GPS and analytics features

### Primary Outcome

Premium NMS becomes a real add-on workflow instead of only a future idea.

### Success Criteria

- subscribers can remain operational in the core product without NMS
- premium-enabled subscribers can be assigned through a dedicated NMS flow
- subscriber detail pages show topology status and NMS actions
- reassignment does not happen through unsafe basic shortcuts

## Phase 2: Map Workspace

### Goal

Add a practical visual topology workspace.

This phase turns Premium NMS into a visible operational map instead of only a record-and-assignment layer.

### Included

- map-centered NMS page
- node rendering
- link rendering
- connect nodes
- basic path geometry editing
- selected object drawer
- layer toggles
- topology highlight for a subscriber path

### Not Yet Included

- deep passive optical internals
- full cable-core logic
- rich validation dashboards
- advanced field tooling

### Primary Outcome

Staff can now see and navigate the physical topology visually.

### Success Criteria

- nodes and links are visible on the map
- operators can open mapped subscriber topology from the subscriber workflow
- basic route and geometry editing is operational
- the map adds operational value without becoming the only place for configuration

## Phase 3: Distribution and Endpoint Modeling

### Goal

Introduce real endpoint-based provisioning behavior.

This phase moves the product from “node summary” toward structured network distribution.

### Included

- NAP internals
- PLC devices
- internal endpoints
- occupancy rules
- assignment eligibility filtering
- endpoint availability states

### Not Yet Included

- FBT ratio behavior
- detailed cable-core allocation rules
- advanced validation and operations dashboards

### Primary Outcome

Assignment becomes endpoint-aware instead of only node-aware.

### Success Criteria

- subscribers can be attached to actual endpoints
- occupied outputs are excluded from available assignment lists
- endpoint states are visible in assignment workflows
- subscriber-side summary reflects endpoint-level assignment cleanly

## Phase 4: Advanced Fiber Logic

### Goal

Add structured fiber-distribution intelligence for serious FTTH operations.

### Included

- FBT modeling
- cable inventory
- core inventory
- per-core allocation
- pass-through versus split behavior
- richer route and link metadata

### Primary Outcome

Premium NMS becomes a more complete fiber-distribution planning and provisioning tool.

### Success Criteria

- cable records can describe actual deployed capacity
- core-level usage can be tracked
- FBT and PLC behavior is no longer just free-text or notes
- assignment and topology data can reflect real optical distribution structure

## Phase 5: Validation and Operations Layer

### Goal

Make the Premium NMS environment self-checking and safer for production use.

### Included

- validation alerts
- duplicate assignment detection
- occupied-endpoint conflict detection
- broken mapping detection
- invalid dependency warnings
- stale or incomplete topology states
- `Needs Review` workflows

### Primary Outcome

Premium NMS becomes easier to trust operationally because it can detect and expose problems instead of silently carrying bad state.

### Success Criteria

- invalid topology states are surfaced clearly
- subscriber-side topology summary can reflect warning state
- operations staff can find and fix broken mappings from a dedicated flow
- assignment conflicts are prevented or highlighted consistently

## Phase 6: Field and Analytics Features

### Goal

Add higher-end field and operational intelligence features after the core NMS model is already stable.

### Included

- GPS trace import
- route analytics
- outage impact tracing
- future power-budget estimation
- advanced operational reporting

### Primary Outcome

Premium NMS grows from a topology workspace into a more complete operational planning and network-analysis platform.

### Success Criteria

- field data can be brought into the topology workflow safely
- route analysis becomes useful for troubleshooting and planning
- outage tracing can identify affected subscribers or paths
- advanced reporting adds value beyond basic visualization

## Recommended Implementation Order

The best order is:

1. Phase 1: Foundation
2. Phase 2: Map Workspace
3. Phase 3: Distribution and Endpoint Modeling
4. Phase 4: Advanced Fiber Logic
5. Phase 5: Validation and Operations Layer
6. Phase 6: Field and Analytics Features

This order is recommended because:

- it protects the billing and subscriber core first
- it delivers usable premium workflows early
- it introduces technical depth only after the workflow boundary is proven
- it delays expensive advanced features until the product model is already stable

## Recommended First Build Scope

If implementation starts now, the recommended first build scope is only:

- `Phase 1`

This is the safest first deliverable because it creates:

- premium value
- a real NMS workflow
- clear subscriber-to-NMS boundary
- a migration path toward the map and topology-heavy phases

without committing immediately to the entire long-term topology system.

## Final Recommendation

Premium NMS is ready for implementation, but not as one massive all-at-once release.

The recommended strategy is:

- build the boundary first
- ship the first real premium assignment workflow
- add visual topology second
- add structured distribution third
- add advanced fiber and operational intelligence only after the product model is proven

This is the most practical way to deliver Premium NMS without putting the existing production workflows at unnecessary risk.
