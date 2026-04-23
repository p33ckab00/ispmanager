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
- `Phase 3`: partially started
- `Phase 4`: not started
- `Phase 5`: not started
- `Phase 6`: not started

### Important Rollout Note

The codebase now includes the current Premium NMS migration set:

- `apps/nms/migrations/0001_initial.py`
- `apps/nms/migrations/0002_topologylink_topologylinkvertex.py`
- `apps/nms/migrations/0003_internaldevice_endpoint_serviceattachment_endpoint_and_more.py`
- `apps/nms/migrations/0004_internaldevice_auto_generate_plc_outputs_and_more.py`

For production rollout, the database migrations must be applied and the running web service must be reloaded so the live process picks up the current NMS model layer.

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
- `templates/nms/links.html`
- `apps/nms/migrations/0002_topologylink_topologylinkvertex.py`

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

## Phase 4 Status: Not Started

Not yet implemented:

- FBT modeling
- cable inventory
- core inventory
- per-core allocation
- richer optical route structure

## Phase 5 Status: Not Started

Not yet implemented:

- dedicated validation center
- duplicate-assignment conflict workflows
- broken topology issue workflows
- advanced `Needs Review` operations dashboard

The `Needs Review` status exists in Phase 1, but the broader validation and operations layer does not yet exist.

## Phase 6 Status: Not Started

Not yet implemented:

- GPS trace import
- route analytics
- outage impact tracing
- power-budget estimation

## Recommended Next Steps

The cleanest next sequence is:

1. Apply the `nms` migrations.
2. Validate Phase 1, Phase 2, and Phase 3A flows in the browser.
3. Commit and push the current Premium NMS code changes.
4. Continue with `Phase 3B: PLC Modeling`.
5. Then follow with `Phase 3C: Eligibility and Review Rules`.

## Practical Interpretation

If someone asks, “What is already finished?” the best short answer is:

- Premium NMS Phase 1 is implemented in code.
- Premium NMS Phase 2 map workspace is implemented in code.
- Premium NMS Phase 3A endpoint foundation is implemented in code.
- The deeper topology engine phases are still pending.

If someone asks, “What is already live-ready?” the safer answer is:

- the code foundation is built
- the rollout still needs migration application and final production validation
