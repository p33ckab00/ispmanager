# Premium NMS Current Implementation Status

## Summary

This document tracks the current implementation status of `Premium NMS` against the phased plan defined in [Premium NMS Phased Implementation Plan](41_premium_nms_phased_implementation_plan.md).

The goal is to make it easy to see:

- which phase work is already implemented in code
- which phase work is only partially started
- which phases are still pending
- what still needs to happen before the completed work is fully operational in production

This is a status guide, not a replacement for the phased roadmap.

## Current Status Snapshot

### Overall State

- `Phase 1`: implemented in code
- `Phase 2`: implemented in code
- `Phase 3`: implemented in code
- `Phase 4`: implemented in code
- `Phase 5`: implemented in code
- `Phase 6`: implemented in code as a practical field and analytics foundation

### Important Rollout Note

The codebase now includes the current Premium NMS migration set:

- `apps/nms/migrations/0001_initial.py`
- `apps/nms/migrations/0002_topologylink_topologylinkvertex.py`
- `apps/nms/migrations/0003_internaldevice_endpoint_serviceattachment_endpoint_and_more.py`
- `apps/nms/migrations/0004_internaldevice_auto_generate_plc_outputs_and_more.py`
- `apps/nms/migrations/0005_cable_cablecore.py`
- `apps/nms/migrations/0006_internaldevice_auto_generate_fbt_outputs_and_more.py`
- `apps/nms/migrations/0007_cablecoreassignment.py`
- `apps/nms/migrations/0008_gpstrace_gpstracepoint.py`
- `apps/nms/migrations/0009_expand_fbt_ratio_choices.py`
- `apps/nms/migrations/0010_serviceattachmentvertex.py`

For production rollout, the database migrations must be applied and the running web service must be reloaded so the live process picks up the current NMS model layer.

### Known Remaining Gap: Port-Accurate Flow Mapping

The current implementation has enough inventory to model routers, NAP nodes,
internal devices, FBT ratios, PLC ports, cables, cores, GPS traces, topology
links, and subscriber drop geometry. The next gap is the physical flow between
exact inputs and outputs.

The next planned slice is documented in [Premium NMS Port-Accurate Mapping Plan](46_premium_nms_port_accurate_mapping_plan.md).

That slice covers:

- router-origin NMS nodes for routers that already have coordinates
- physical router ethernet ports as assignable endpoints
- explicit endpoint-to-endpoint links for NAP inputs, FBT IN/output ports, PLC
  IN/output ports, router ports, and subscriber drops
- endpoint-required subscriber assignments for new clean mappings
- legacy node-only mappings preserved as `Needs Review`
- shared NAP-to-NAP-to-client paths on the map
- telemetry-aware running dash lines
- subscriber marker solid-dot online/offline state
- subscriber marker billing-health rings

## Phase 1 Status: Implemented in Code

### Goal of Phase 1

Create the first real `Premium NMS` workflow without breaking the existing `Subscribers` module as the source of truth for customer and billing state.

### What Is Already Implemented

#### 1. Premium Attachment Model

The first premium physical-network attachment record now exists in code:

- `ServiceAttachment`

This establishes a dedicated premium record for physical assignment, separate from billing and customer-account truth.

Implemented files:

- `apps/nms/models.py`
- `apps/nms/migrations/0001_initial.py`

#### 2. Premium NMS Workspace

A subscriber-specific Premium NMS workspace is now implemented.

This provides a place to:

- create premium mapping
- update premium mapping
- remove premium mapping
- promote a basic legacy node assignment into a premium mapping

Implemented files:

- `apps/nms/views.py`
- `apps/nms/urls.py`
- `apps/nms/forms.py`
- `templates/nms/subscriber_workspace.html`

#### 3. Subscriber Topology Summary

Subscriber pages now support topology summary states:

- `Unassigned`
- `Basic Node Only`
- `Mapped`
- `Needs Review`

This keeps the `Subscribers` module as the account-facing page while showing premium topology state clearly.

Implemented files:

- `apps/nms/services.py`
- `apps/subscribers/views.py`
- `templates/subscribers/list.html`
- `templates/subscribers/detail.html`

#### 4. NMS Actions From Subscriber Workflow

The subscriber workflow now has dedicated Premium NMS actions:

- `Assign in NMS`
- `Reassign in NMS`
- `Open in NMS`
- `View Topology`

This means premium mapping now has a clear operational entry point without turning the subscriber page into a full topology editor.

#### 5. Legacy Quick Assignment Guard

The old basic node assignment flow is now guarded when a premium mapping exists.

That means:

- basic subscriber-side node assignment can still be used when premium mapping is not active
- once a premium mapping exists, reassignment should happen inside Premium NMS
- the old quick form no longer acts as an unsafe bypass path

This is one of the most important Phase 1 protections.

#### 6. Legacy Summary Sync

Premium NMS now mirrors the selected premium node and endpoint label back into the older lightweight subscriber node summary.

This allows:

- subscriber pages to continue showing simple node summary
- older UI surfaces to remain readable
- the system to transition gradually from basic node association toward premium topology workflow

#### 7. Subscriber Assignment Auto-Mapping

The existing Subscriber detail page `Basic Node Assignment` form now creates the first Premium NMS mapping automatically when a node is selected and no premium mapping exists yet.

This keeps the Subscriber module workflow familiar while making the subscriber immediately visible in the NMS map as a basic node-level service attachment. Detailed endpoint, PLC, FBT, fiber, cable, and core inventory work still belongs inside Premium NMS.

### What Phase 1 Currently Delivers

From a product perspective, Phase 1 now delivers:

- a real premium assignment model
- a real premium workspace
- summary-only topology visibility inside `Subscribers`
- a protected handoff from `Subscribers` to `NMS`
- one active premium physical assignment per subscriber

This means Premium NMS is no longer only a concept or docs-only plan.

### What Still Needs To Happen Before Phase 1 Is Fully Operational

Phase 1 is implemented in code, but these rollout steps are still needed:

- apply the new migration to the database
- perform end-to-end UI validation using actual browser workflow
- confirm create, update, remove, and fallback behavior with real records
- commit and push the code changes when approved

### Verification Already Performed

The following checks were already run during implementation:

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- template load checks for updated subscriber and NMS templates
- smoke checks for:
  - `subscriber_list`
  - `subscriber_detail`
  - `nms_map_data`

Known existing warning:

- `staticfiles.W004` for missing `/opt/ispmanager/static`

This warning is pre-existing and not specific to Premium NMS.

## Phase 2 Status: Implemented in Code

### What Phase 2 Now Delivers

The Premium NMS map workspace is now implemented in code as a real operational surface, not just a visibility prototype.

Implemented Phase 2 pieces:

- router markers
- subscriber markers
- network node markers
- dedicated node management page over the existing `NetworkNode` table
- map-based `Add Node` workflow with click-to-place coordinates
- premium attachment path lines
- first-class topology link records
- topology link inventory page
- selected object inspector
- `Connect Nodes` workflow on the map
- path geometry editor
- editable route vertices
- focused topology view for a selected subscriber

Implemented files:

- `apps/nms/models.py`
- `apps/nms/forms.py`
- `apps/nms/services.py`
- `apps/nms/views.py`
- `apps/nms/urls.py`
- `templates/nms/map.html`
- `templates/nms/nodes.html`
- `templates/nms/links.html`
- `apps/nms/migrations/0002_topologylink_topologylinkvertex.py`

### Phase 2C Clarification

`Add Node` is now treated as a Phase 2 gap-closure slice rather than a late-stage feature.

Important implementation detail:

- it writes to the existing `subscribers.NetworkNode` table
- it does not replace or migrate the node table
- it does not rewrite billing, invoice, accounting, or subscriber records
- it is additive to the live system

### What Still Needs To Happen Before Phase 2 Is Fully Operational

The Phase 2 code is present, but production rollout still needs:

- database migration application
- browser validation of `Connect Nodes`
- browser validation of `Edit Path`
- final save-flow testing using live data

## Phase 3 Status: Partially Started

### What Has Started

Phase 3A endpoint foundation is now implemented in code.

This includes:

- `InternalDevice` model
- `Endpoint` model
- endpoint-aware `ServiceAttachment`
- automatic endpoint occupancy sync
- distribution detail page per node
- endpoint selection inside the Premium NMS subscriber workspace
- distribution links from map and subscriber surfaces

Implemented files:

- `apps/nms/models.py`
- `apps/nms/forms.py`
- `apps/nms/services.py`
- `apps/nms/views.py`
- `apps/nms/urls.py`
- `templates/nms/subscriber_workspace.html`
- `templates/nms/distribution_detail.html`
- `templates/nms/map.html`
- `apps/nms/migrations/0003_internaldevice_endpoint_serviceattachment_endpoint_and_more.py`

### What Is Still Missing In Phase 3

The following Phase 3 items are still pending:

- broader endpoint-state validation workflows beyond local assignment and distribution review surfaces

So the correct status is:

- `Phase 3A endpoint foundation`: implemented in code
- `Phase 3B PLC modeling`: implemented in code
- `Phase 3C eligibility and review rules`: implemented in code

## Phase 4 Status: Implemented in Code

### What Has Started

Phase 4A cable and core foundation is now implemented in code, Phase 4B FBT modeling is now implemented in code, and Phase 4C structured core assignment rules are now implemented in code.

This includes:

- `Cable` model bound to a topology link
- `CableCore` model for per-core inventory
- auto-generated standard core colors
- fiber-link cable form fields on the topology links page
- per-link cable/core visibility in the map and links UI
- FBT ratio-aware internal device settings
- auto-generated FBT input, primary pass-through, and secondary split outputs
- subscriber-assignment guardrails that keep FBT pass-through outputs out of normal endpoint eligibility
- `CableCoreAssignment` model for structured subscriber-to-core allocation
- assignment and release workflow from the subscriber Premium NMS workspace
- automatic sync from structured assignment state back into `CableCore.status` and `CableCore.assignment_label`
- link inventory visibility for structured core assignments
- review flags for inactive or damaged cable/core assignment problems and status mismatches

Implemented files:

- `apps/nms/models.py`
- `apps/nms/forms.py`
- `apps/nms/services.py`
- `apps/nms/views.py`
- `apps/core/role_presets.py`
- `templates/nms/links.html`
- `templates/nms/map.html`
- `templates/nms/distribution_detail.html`
- `templates/nms/subscriber_workspace.html`
- `apps/nms/migrations/0005_cable_cablecore.py`
- `apps/nms/migrations/0006_internaldevice_auto_generate_fbt_outputs_and_more.py`
- `apps/nms/migrations/0007_cablecoreassignment.py`
- `apps/nms/tests.py`

### Follow-On Refinement Areas

The following items are now better treated as future refinement rather than blockers for the Phase 4 implementation:

- richer optical route structure
- deeper optical behavior beyond the initial FBT pass-through/split modeling
- multi-segment optical path semantics beyond the current per-core allocation records

So the correct status is:

- `Phase 4A cable and core foundation`: implemented in code
- `Phase 4B FBT modeling`: implemented in code
- `Phase 4C core assignment rules`: implemented in code

## Phase 5 Status: Implemented in Code

Phase 5 validation and operations support is now implemented in code.

This includes:

- dedicated validation center
- duplicate-assignment conflict workflows
- broken topology issue workflows
- advanced `Needs Review` operations dashboard
- endpoint occupancy sync action
- core assignment status sync action
- review-state refresh action
- validation issue links back to the correct NMS repair workspace

Implemented files:

- `apps/nms/services.py`
- `apps/nms/views.py`
- `apps/nms/urls.py`
- `templates/nms/operations.html`
- `templates/partials/sidebar.html`

## Phase 6 Status: Implemented in Code

Phase 6 field and analytics foundation is now implemented in code.

This includes:

- GPS trace import
- route analytics
- outage impact tracing
- power-budget estimation
- cable utilization reporting
- GPS trace visibility on the Premium NMS map

Implemented files:

- `apps/nms/models.py`
- `apps/nms/forms.py`
- `apps/nms/services.py`
- `apps/nms/views.py`
- `apps/nms/urls.py`
- `templates/nms/analytics.html`
- `templates/nms/map.html`
- `apps/nms/migrations/0008_gpstrace_gpstracepoint.py`

## Recommended Next Steps

The cleanest next sequence is:

1. Validate the Phase 4C, Phase 5, and Phase 6 flows in the browser using real fiber links, distribution nodes, subscriber mappings, and GPS trace data.
2. Restart or reload the running web service so production picks up the latest NMS code.
3. Implement the port-accurate mapping slice documented in [Premium NMS Port-Accurate Mapping Plan](46_premium_nms_port_accurate_mapping_plan.md).
4. Continue future refinements around richer optical path semantics and deeper field reporting.

## Practical Interpretation

If someone asks, “What is already finished?” the best short answer is:

- Premium NMS Phase 1 is implemented in code.
- Premium NMS Phase 2 map workspace is implemented in code.
- Premium NMS Phase 3 endpoint foundation, PLC modeling, and review rules are implemented in code.
- Premium NMS Phase 4A cable/core foundation, Phase 4B FBT modeling, and Phase 4C core assignment rules are implemented in code.
- Premium NMS Phase 5 validation and operations workflows are implemented in code.
- Premium NMS Phase 6 field and analytics foundation is implemented in code.

If someone asks, “What is already live-ready?” the safer answer is:

- the code foundation is built
- the rollout still needs migration application and final production validation
