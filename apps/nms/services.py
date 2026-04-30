import math
from datetime import date

from django.db import DatabaseError, connection
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, F, Q
from django.urls import reverse
from apps.billing.models import Invoice
from apps.nms.models import (
    Cable,
    CableCoreAssignment,
    CableCore,
    Endpoint,
    EndpointConnection,
    GpsTrace,
    GpsTracePoint,
    InternalDevice,
    ServiceAttachment,
    ServiceAttachmentVertex,
    TopologyLink,
    TopologyLinkVertex,
)
from apps.routers.models import Router, RouterInterface
from apps.subscribers.models import NetworkNode, SubscriberNode


BADGE_CLASSES = {
    'unassigned': 'bg-gray-100 text-gray-600',
    'basic_node_only': 'bg-blue-50 text-blue-700',
    'mapped': 'bg-green-100 text-green-700',
    'needs_review': 'bg-amber-100 text-amber-700',
}

STANDARD_CORE_COLORS = [
    'Blue',
    'Orange',
    'Green',
    'Brown',
    'Slate',
    'White',
    'Red',
    'Black',
    'Yellow',
    'Violet',
    'Rose',
    'Aqua',
]


def has_model_table(model):
    try:
        return model._meta.db_table in connection.introspection.table_names()
    except DatabaseError:
        return False


def has_model_columns(model, required_columns):
    if not has_model_table(model):
        return False

    try:
        with connection.cursor() as cursor:
            table_description = connection.introspection.get_table_description(
                cursor,
                model._meta.db_table,
            )
    except DatabaseError:
        return False

    available_columns = {column.name for column in table_description}
    return all(column in available_columns for column in required_columns)


def has_service_attachment_table():
    return has_model_columns(ServiceAttachment, [
        'id',
        'subscriber_id',
        'node_id',
        'endpoint_id',
        'endpoint_label',
        'status',
        'notes',
        'assigned_by',
        'created_at',
        'updated_at',
    ])


def has_service_attachment_geometry_tables():
    return has_model_table(ServiceAttachmentVertex)


def has_topology_link_tables():
    return has_model_table(TopologyLink) and has_model_table(TopologyLinkVertex)


def has_distribution_tables():
    return has_model_columns(Endpoint, ['id', 'router_interface_id']) and has_model_table(InternalDevice)


def has_endpoint_connection_tables():
    return has_model_table(EndpointConnection)


def has_cable_tables():
    return has_model_table(Cable) and has_model_table(CableCore)


def has_core_assignment_tables():
    return has_model_table(CableCoreAssignment)


def has_gps_trace_tables():
    return has_model_table(GpsTrace) and has_model_table(GpsTracePoint)


def has_router_root_node_fields():
    return has_model_columns(NetworkNode, ['is_system', 'system_role'])


def get_service_attachment(subscriber, table_ready=None):
    if table_ready is None:
        table_ready = has_service_attachment_table()

    if not table_ready:
        return None
    try:
        return ServiceAttachment.objects.select_related(
            'node',
            'endpoint',
            'endpoint__internal_device',
            'endpoint__parent_node',
            'endpoint__router_interface',
            'endpoint__router_interface__traffic_cache',
        ).get(subscriber=subscriber)
    except ObjectDoesNotExist:
        return None


def get_basic_node_assignment(subscriber):
    try:
        return subscriber.node_assignment
    except ObjectDoesNotExist:
        return None


def sync_basic_node_summary(subscriber, node, endpoint_label=''):
    if node is None:
        SubscriberNode.objects.filter(subscriber=subscriber).delete()
        return

    SubscriberNode.objects.update_or_create(
        subscriber=subscriber,
        defaults={
            'node': node,
            'port_label': (endpoint_label or '')[:50],
        },
    )


def sync_endpoint_status(endpoint):
    if endpoint is None or not has_distribution_tables() or not has_service_attachment_table():
        return

    endpoint = Endpoint.objects.select_related('internal_device', 'parent_node').filter(pk=endpoint.pk).first()
    if endpoint is None:
        return

    if endpoint.status in ('inactive', 'damaged'):
        return

    has_active_attachment = ServiceAttachment.objects.filter(
        endpoint=endpoint,
        status='active',
    ).exists()
    new_status = 'occupied' if has_active_attachment else 'available'
    if endpoint.status != new_status:
        endpoint.status = new_status
        endpoint.save(update_fields=['status', 'updated_at'])


def ensure_router_root_node(router):
    if (
        router is None
        or not has_router_root_node_fields()
        or router.latitude is None
        or router.longitude is None
        or not router.is_active
    ):
        return None, False

    defaults = {
        'name': f"{router.name} Root",
        'node_type': 'router_site',
        'latitude': router.latitude,
        'longitude': router.longitude,
        'notes': 'Auto-managed Premium NMS router root node.',
        'is_active': True,
        'is_system': True,
    }
    node, created = NetworkNode.objects.update_or_create(
        router=router,
        system_role='router_root',
        defaults=defaults,
    )
    return node, created


def is_router_interface_assignable(interface):
    return bool(
        interface
        and interface.router_id
        and interface.router.is_active
        and interface.iface_type == 'ether'
        and not interface.is_dynamic
        and not interface.is_slave
    )


def get_router_interface_sequence(interface):
    digits = ''.join(character for character in (interface.name or '') if character.isdigit())
    if digits:
        try:
            return max(int(digits), 1)
        except ValueError:
            return interface.pk or 1
    return interface.pk or 1


def sync_router_interface_endpoint(interface):
    if not has_distribution_tables() or not is_router_interface_assignable(interface):
        return None, False

    root_node, _ = ensure_router_root_node(interface.router)
    if root_node is None:
        return None, False

    endpoint_type = 'access' if interface.role == 'client' else 'uplink'
    defaults = {
        'parent_node': root_node,
        'internal_device': None,
        'label': interface.display_name[:80],
        'endpoint_type': endpoint_type,
        'sequence': get_router_interface_sequence(interface),
        'notes': 'Auto-managed router physical ethernet endpoint.',
    }
    endpoint, created = Endpoint.objects.update_or_create(
        router_interface=interface,
        defaults=defaults,
    )
    if endpoint.status not in ('inactive', 'damaged'):
        sync_endpoint_status(endpoint)
    return endpoint, created


def sync_router_roots_and_interface_endpoints():
    if not has_router_root_node_fields():
        return {'router_nodes': 0, 'router_endpoints': 0}

    router_nodes = 0
    router_endpoints = 0
    routers = Router.objects.filter(
        is_active=True,
        latitude__isnull=False,
        longitude__isnull=False,
    )
    for router in routers:
        _, node_created = ensure_router_root_node(router)
        if node_created:
            router_nodes += 1

    if has_distribution_tables():
        interfaces = RouterInterface.objects.select_related('router').filter(
            router__is_active=True,
            router__latitude__isnull=False,
            router__longitude__isnull=False,
            iface_type='ether',
            is_dynamic=False,
            is_slave=False,
        )
        for interface in interfaces:
            _, endpoint_created = sync_router_interface_endpoint(interface)
            if endpoint_created:
                router_endpoints += 1

    return {
        'router_nodes': router_nodes,
        'router_endpoints': router_endpoints,
    }


def ensure_endpoint_connection(upstream_endpoint, downstream_endpoint, *, connection_type='internal', role='other', notes=''):
    if not has_endpoint_connection_tables() or upstream_endpoint is None or downstream_endpoint is None:
        return None, False

    connection, created = EndpointConnection.objects.update_or_create(
        upstream_endpoint=upstream_endpoint,
        downstream_endpoint=downstream_endpoint,
        defaults={
            'connection_type': connection_type,
            'role': role,
            'status': 'active',
            'notes': notes,
        },
    )
    return connection, created


def ensure_plc_endpoints(internal_device):
    if (
        internal_device is None
        or not has_distribution_tables()
        or not internal_device.is_plc
        or not internal_device.auto_generate_plc_outputs
    ):
        return {'created_inputs': 0, 'created_outputs': 0}

    desired_input_count = internal_device.effective_plc_input_count
    desired_output_count = internal_device.effective_plc_output_count
    created_inputs = 0
    created_outputs = 0

    existing_inputs = {
        endpoint.label
        for endpoint in internal_device.endpoints.filter(endpoint_type='uplink')
    }
    existing_outputs = {
        endpoint.label
        for endpoint in internal_device.endpoints.filter(endpoint_type='split_output')
    }

    for index in range(1, desired_input_count + 1):
        label = f"IN {index}"
        if label in existing_inputs:
            continue
        Endpoint.objects.create(
            internal_device=internal_device,
            label=label,
            endpoint_type='uplink',
            sequence=index,
            status='available',
            notes='Auto-generated PLC input port.',
        )
        created_inputs += 1

    for index in range(1, desired_output_count + 1):
        label = f"OUT {index}"
        if label in existing_outputs:
            continue
        Endpoint.objects.create(
            internal_device=internal_device,
            label=label,
            endpoint_type='split_output',
            sequence=index,
            status='available',
            notes='Auto-generated PLC output port.',
        )
        created_outputs += 1

    if has_endpoint_connection_tables():
        input_endpoint = internal_device.endpoints.filter(
            endpoint_type='uplink',
        ).order_by('sequence', 'id').first()
        if input_endpoint:
            for output_endpoint in internal_device.endpoints.filter(
                endpoint_type='split_output',
            ).order_by('sequence', 'id'):
                ensure_endpoint_connection(
                    input_endpoint,
                    output_endpoint,
                    connection_type='internal',
                    role='splitter_output',
                    notes='Auto-managed PLC internal split path.',
                )

    return {
        'created_inputs': created_inputs,
        'created_outputs': created_outputs,
    }


def ensure_fbt_endpoints(internal_device):
    if (
        internal_device is None
        or not has_distribution_tables()
        or not internal_device.is_fbt
        or not internal_device.auto_generate_fbt_outputs
    ):
        return {'created_inputs': 0, 'created_outputs': 0}

    primary_ratio, secondary_ratio = internal_device.fbt_ratio_parts
    created_inputs = 0
    created_outputs = 0

    input_endpoint = internal_device.endpoints.filter(
        endpoint_type='uplink',
        sequence=1,
    ).order_by('id').first()
    if input_endpoint is None:
        Endpoint.objects.create(
            internal_device=internal_device,
            label='IN 1',
            endpoint_type='uplink',
            sequence=1,
            status='available',
            notes='Auto-generated FBT input port.',
        )
        created_inputs += 1
    else:
        update_fields = []
        if input_endpoint.label != 'IN 1':
            input_endpoint.label = 'IN 1'
            update_fields.append('label')
        if input_endpoint.notes != 'Auto-generated FBT input port.':
            input_endpoint.notes = 'Auto-generated FBT input port.'
            update_fields.append('notes')
        if update_fields:
            input_endpoint.save(update_fields=update_fields + ['updated_at'])

    output_specs = [
        {
            'sequence': 1,
            'label': f"PRIMARY {primary_ratio}%",
            'endpoint_type': 'distribution',
            'notes': 'Auto-generated FBT primary pass-through output.',
        },
        {
            'sequence': 2,
            'label': f"SECONDARY {secondary_ratio}%",
            'endpoint_type': 'split_output',
            'notes': 'Auto-generated FBT secondary split output.',
        },
    ]

    for output_spec in output_specs:
        endpoint = internal_device.endpoints.filter(
            endpoint_type=output_spec['endpoint_type'],
            sequence=output_spec['sequence'],
        ).order_by('id').first()
        if endpoint is None:
            Endpoint.objects.create(
                internal_device=internal_device,
                label=output_spec['label'],
                endpoint_type=output_spec['endpoint_type'],
                sequence=output_spec['sequence'],
                status='available',
                notes=output_spec['notes'],
            )
            created_outputs += 1
            continue

        update_fields = []
        if endpoint.label != output_spec['label']:
            endpoint.label = output_spec['label']
            update_fields.append('label')
        if endpoint.notes != output_spec['notes']:
            endpoint.notes = output_spec['notes']
            update_fields.append('notes')
        if update_fields:
            endpoint.save(update_fields=update_fields + ['updated_at'])

    if has_endpoint_connection_tables():
        input_endpoint = internal_device.endpoints.filter(
            endpoint_type='uplink',
            sequence=1,
        ).order_by('id').first()
        primary_endpoint = internal_device.endpoints.filter(
            endpoint_type='distribution',
            sequence=1,
        ).order_by('id').first()
        secondary_endpoint = internal_device.endpoints.filter(
            endpoint_type='split_output',
            sequence=2,
        ).order_by('id').first()
        if input_endpoint and primary_endpoint:
            ensure_endpoint_connection(
                input_endpoint,
                primary_endpoint,
                connection_type='internal',
                role='passthrough',
                notes='Auto-managed FBT primary pass-through path.',
            )
        if input_endpoint and secondary_endpoint:
            ensure_endpoint_connection(
                input_endpoint,
                secondary_endpoint,
                connection_type='internal',
                role='splitter_output',
                notes='Auto-managed FBT secondary split path.',
            )

    return {
        'created_inputs': created_inputs,
        'created_outputs': created_outputs,
    }


def get_standard_core_color(sequence):
    if sequence <= 0:
        return STANDARD_CORE_COLORS[0]
    return STANDARD_CORE_COLORS[(sequence - 1) % len(STANDARD_CORE_COLORS)]


def sync_cable_cores(cable):
    if cable is None or not has_cable_tables():
        return {'created': 0, 'removed': 0}

    existing_cores = list(cable.cores.order_by('sequence'))
    existing_by_sequence = {core.sequence: core for core in existing_cores}
    created = 0
    removed = 0

    for sequence in range(1, cable.total_cores + 1):
        if sequence in existing_by_sequence:
            core = existing_by_sequence[sequence]
            expected_color = get_standard_core_color(sequence)
            if core.color_name != expected_color:
                core.color_name = expected_color
                core.save(update_fields=['color_name', 'updated_at'])
            continue

        CableCore.objects.create(
            cable=cable,
            sequence=sequence,
            color_name=get_standard_core_color(sequence),
            status='available',
        )
        created += 1

    removable_cores = [
        core for core in existing_cores
        if core.sequence > cable.total_cores
    ]
    for core in removable_cores:
        if core.status in ('used', 'reserved'):
            continue
        core.delete()
        removed += 1

    return {
        'created': created,
        'removed': removed,
    }


def get_assignable_cable_cores(*, current_assignment=None):
    if not has_cable_tables():
        return CableCore.objects.none()

    queryset = CableCore.objects.select_related(
        'cable',
        'cable__link',
        'cable__link__source_node',
        'cable__link__target_node',
    ).filter(
        cable__link__link_type='fiber',
        cable__status__in=['active', 'planned'],
    ).exclude(
        status='damaged',
    )

    current_core_id = getattr(current_assignment, 'core_id', None)
    if current_core_id:
        queryset = queryset.filter(Q(status='available') | Q(pk=current_core_id))
    else:
        queryset = queryset.filter(status='available')

    if has_core_assignment_tables():
        assigned_core_ids = CableCoreAssignment.objects.all()
        if current_assignment is not None and getattr(current_assignment, 'pk', None):
            assigned_core_ids = assigned_core_ids.exclude(pk=current_assignment.pk)
        queryset = queryset.exclude(
            pk__in=assigned_core_ids.values_list('core_id', flat=True)
        )

    return queryset.order_by(
        'cable__name',
        'cable__code',
        'sequence',
        'id',
    )


def apply_core_assignment(assignment):
    if assignment is None or not has_cable_tables():
        return

    core = assignment.core
    core.status = assignment.status
    core.assignment_label = assignment.resolved_label[:120]
    core.save(update_fields=['status', 'assignment_label', 'updated_at'])


def release_core_assignment(assignment):
    if assignment is None or not has_cable_tables():
        return

    core = assignment.core
    assignment.delete()
    if core.status != 'damaged':
        core.status = 'available'
    core.assignment_label = ''
    core.save(update_fields=['status', 'assignment_label', 'updated_at'])


def get_attachment_core_assignments(attachment):
    if attachment is None or not getattr(attachment, 'pk', None) or not has_core_assignment_tables():
        return []

    return list(
        attachment.core_assignments.select_related(
            'core',
            'core__cable',
            'core__cable__link',
            'core__cable__link__source_node',
            'core__cable__link__target_node',
        ).order_by(
            'core__cable__name',
            'core__sequence',
        )
    )


def get_eligible_endpoints(*, selected_node=None, current_attachment=None):
    if not has_distribution_tables():
        return Endpoint.objects.none()

    queryset = Endpoint.objects.select_related(
        'parent_node',
        'internal_device',
        'internal_device__parent_node',
        'router_interface',
        'router_interface__router',
    ).filter(
        Q(parent_node__is_active=True) | Q(internal_device__parent_node__is_active=True)
    ).exclude(
        status__in=['inactive', 'damaged']
    ).exclude(
        internal_device__device_type='fbt',
        endpoint_type='distribution',
    ).filter(
        Q(internal_device__isnull=True) | Q(internal_device__is_active=True)
    )

    if selected_node is not None:
        selected_node_id = getattr(selected_node, 'pk', selected_node)
        queryset = queryset.filter(
            Q(parent_node_id=selected_node_id)
            | Q(internal_device__parent_node_id=selected_node_id)
        )

    occupied_endpoint_ids = ServiceAttachment.objects.filter(
        status='active',
        endpoint_id__isnull=False,
    )
    if current_attachment is not None and getattr(current_attachment, 'pk', None):
        occupied_endpoint_ids = occupied_endpoint_ids.exclude(pk=current_attachment.pk)

    eligible_ids = list(
        queryset.exclude(
            pk__in=occupied_endpoint_ids.values_list('endpoint_id', flat=True)
        ).values_list('pk', flat=True)
    )

    current_endpoint_id = getattr(current_attachment, 'endpoint_id', None)
    if current_endpoint_id and current_endpoint_id not in eligible_ids:
        eligible_ids.append(current_endpoint_id)

    if not eligible_ids:
        return Endpoint.objects.none()

    return Endpoint.objects.select_related(
        'parent_node',
        'internal_device',
        'internal_device__parent_node',
        'router_interface',
        'router_interface__router',
    ).filter(pk__in=eligible_ids).order_by(
        'parent_node__name',
        'internal_device__parent_node__name',
        'internal_device__name',
        'sequence',
        'label',
    )


def is_source_endpoint(endpoint):
    if endpoint is None:
        return False
    if getattr(endpoint, 'router_interface_id', None):
        return True
    root_node = endpoint.root_node
    return bool(root_node and getattr(root_node, 'system_role', '') == 'router_root')


def get_active_upstream_connection(endpoint):
    if endpoint is None or not has_endpoint_connection_tables():
        return None
    return EndpointConnection.objects.select_related(
        'upstream_endpoint',
        'upstream_endpoint__parent_node',
        'upstream_endpoint__internal_device',
        'upstream_endpoint__internal_device__parent_node',
        'upstream_endpoint__router_interface',
        'downstream_endpoint',
        'downstream_endpoint__parent_node',
        'downstream_endpoint__internal_device',
        'downstream_endpoint__internal_device__parent_node',
        'topology_link',
        'topology_link__source_node',
        'topology_link__target_node',
        'cable_core',
        'cable_core__cable',
    ).filter(
        downstream_endpoint=endpoint,
        status='active',
    ).first()


def endpoint_has_upstream_path(endpoint):
    if endpoint is None:
        return False
    if is_source_endpoint(endpoint):
        return True
    if not has_endpoint_connection_tables():
        return False

    visited = set()
    current = endpoint
    while current and current.pk not in visited:
        visited.add(current.pk)
        connection = get_active_upstream_connection(current)
        if connection is None:
            return False
        current = connection.upstream_endpoint
        if is_source_endpoint(current):
            return True
    return False


def _append_unique_point(points, point):
    if point is None:
        return
    if not points or points[-1] != point:
        points.append(point)


def _node_point(node):
    if node and node.latitude is not None and node.longitude is not None:
        return [node.latitude, node.longitude]
    return None


def build_endpoint_upstream_points(endpoint):
    if endpoint is None or not has_endpoint_connection_tables():
        return []

    chain = []
    visited = set()
    current = endpoint
    while current and current.pk not in visited and not is_source_endpoint(current):
        visited.add(current.pk)
        connection = get_active_upstream_connection(current)
        if connection is None:
            break
        chain.append(connection)
        current = connection.upstream_endpoint

    points = []
    for connection in reversed(chain):
        if connection.topology_link_id:
            for point in build_topology_link_points(connection.topology_link):
                _append_unique_point(points, point)
            continue

        upstream_node = connection.upstream_endpoint.root_node
        downstream_node = connection.downstream_endpoint.root_node
        if upstream_node and downstream_node and upstream_node.pk != downstream_node.pk:
            _append_unique_point(points, _node_point(upstream_node))
            _append_unique_point(points, _node_point(downstream_node))
        else:
            _append_unique_point(points, _node_point(downstream_node or upstream_node))

    if not points:
        _append_unique_point(points, _node_point(endpoint.root_node))
    return points


def build_service_attachment_full_points(attachment):
    points = []
    if attachment.endpoint_id:
        for point in build_endpoint_upstream_points(attachment.endpoint):
            _append_unique_point(points, point)

    if not points:
        serving_node = get_attachment_serving_node(attachment)
        _append_unique_point(points, _node_point(serving_node))

    if has_service_attachment_geometry_tables():
        for vertex in attachment.vertices.all():
            _append_unique_point(points, [vertex.latitude, vertex.longitude])

    subscriber = attachment.subscriber
    if subscriber.latitude is not None and subscriber.longitude is not None:
        _append_unique_point(points, [subscriber.latitude, subscriber.longitude])

    return points


def get_attachment_review_flags(attachment):
    if attachment is None:
        return []

    flags = []
    endpoint = attachment.endpoint
    node = attachment.node or (endpoint.root_node if endpoint else None)

    def add_flag(code, message):
        flags.append({
            'code': code,
            'message': message,
        })

    if node is None:
        add_flag('missing_node', 'No serving node is attached to this mapping.')
    elif not node.is_active:
        add_flag('inactive_node', 'The serving node is inactive.')

    if endpoint:
        endpoint_root = endpoint.root_node
        if endpoint_root is None:
            add_flag('missing_endpoint_node', 'The selected endpoint is no longer attached to a valid node.')
        elif attachment.node_id and endpoint_root.pk != attachment.node_id:
            add_flag('node_endpoint_mismatch', 'The selected endpoint belongs to a different node than the saved serving node.')

        if endpoint.internal_device_id and not endpoint.internal_device.is_active:
            add_flag('inactive_internal_device', 'The internal device for this endpoint is inactive.')

        if endpoint.internal_device_id and endpoint.internal_device.device_type == 'fbt' and endpoint.endpoint_type == 'distribution':
            add_flag(
                'fbt_pass_through_endpoint',
                'The selected endpoint is an FBT primary pass-through output and should not be used as a subscriber access endpoint.',
            )

        if endpoint.status == 'inactive':
            add_flag('inactive_endpoint', 'The selected endpoint is inactive.')
        elif endpoint.status == 'damaged':
            add_flag('damaged_endpoint', 'The selected endpoint is marked as damaged.')

        conflicting_attachment = ServiceAttachment.objects.filter(
            endpoint=endpoint,
            status='active',
        )
        if attachment.pk:
            conflicting_attachment = conflicting_attachment.exclude(pk=attachment.pk)
        if conflicting_attachment.exists():
            add_flag('endpoint_occupied', 'The selected endpoint is already occupied by another active subscriber mapping.')
        if not endpoint_has_upstream_path(endpoint):
            add_flag('incomplete_upstream_path', 'The selected endpoint has no complete upstream path back to a router source.')
    else:
        add_flag('missing_exact_endpoint', 'This mapping is still node-only and needs an exact endpoint or router port.')
        if attachment.status == 'needs_review':
            add_flag('manual_review', 'This mapping is still marked as needing review.')

    if getattr(attachment, 'pk', None) and has_core_assignment_tables():
        for assignment in get_attachment_core_assignments(attachment):
            core = assignment.core
            cable = core.cable
            if cable.link.link_type != 'fiber':
                add_flag('non_fiber_core_assignment', 'A cable core assignment is attached to a non-fiber link.')
            if cable.status == 'inactive':
                add_flag('inactive_cable_assignment', 'A cable core assignment uses an inactive cable.')
            elif cable.status == 'damaged':
                add_flag('damaged_cable_assignment', 'A cable core assignment uses a damaged cable.')
            if core.status == 'damaged':
                add_flag('damaged_core_assignment', 'A cable core assignment uses a damaged core.')
            elif core.status != assignment.status:
                add_flag('core_status_mismatch', 'A cable core assignment status does not match the cable core inventory status.')

    return flags


def refresh_attachment_review_state(attachment, *, preserve_manual_review=True):
    review_flags = get_attachment_review_flags(attachment)
    if review_flags:
        attachment.status = 'needs_review'
    elif not preserve_manual_review and attachment.status == 'needs_review':
        attachment.status = 'active'
    return review_flags


def get_cable_review_flags(cable):
    if cable is None:
        return []

    flags = []

    def add_flag(code, message):
        flags.append({
            'code': code,
            'message': message,
        })

    if cable.link.link_type != 'fiber':
        add_flag('non_fiber_link', 'Cable inventory is attached to a link that is not marked as fiber.')

    if cable.total_cores <= 0:
        add_flag('invalid_core_count', 'Cable total core count must be greater than zero.')

    actual_core_count = cable.cores.count()
    if actual_core_count != cable.total_cores:
        add_flag('core_inventory_mismatch', 'Cable core records do not match the configured total core count.')

    if cable.status == 'damaged':
        add_flag('damaged_cable', 'Cable is marked as damaged.')

    if has_core_assignment_tables():
        mismatched_assignment = CableCoreAssignment.objects.filter(
            core__cable=cable,
        ).exclude(
            core__status=F('status'),
        ).exists()
        if mismatched_assignment:
            add_flag('core_assignment_status_mismatch', 'One or more structured core assignments do not match the core inventory status.')

    return flags


def get_subscriber_topology_summary(subscriber, table_ready=None):
    attachment = get_service_attachment(subscriber, table_ready=table_ready)
    basic_assignment = get_basic_node_assignment(subscriber)

    key = 'unassigned'
    label = 'Unassigned'
    node = None
    endpoint_label = ''
    notes = ''

    if attachment:
        review_flags = get_attachment_review_flags(attachment)
        node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
        endpoint_label = attachment.resolved_endpoint_label
        notes = attachment.notes or ''
        if review_flags or attachment.status == 'needs_review' or attachment.node_id is None:
            key = 'needs_review'
            label = 'Needs Review'
        else:
            key = 'mapped'
            label = 'Mapped'
    elif basic_assignment:
        node = basic_assignment.node
        endpoint_label = basic_assignment.port_label or ''
        key = 'basic_node_only'
        label = 'Basic Node Only'

    node_name = node.name if node else ''
    node_type = node.get_node_type_display() if node else ''
    has_map_context = bool(
        node
        and subscriber.latitude is not None
        and subscriber.longitude is not None
        and node.latitude is not None
        and node.longitude is not None
    )

    return {
        'key': key,
        'label': label,
        'badge_classes': BADGE_CLASSES[key],
        'node_name': node_name,
        'node_type': node_type,
        'endpoint_label': endpoint_label,
        'endpoint_display_name': endpoint_label,
        'notes': notes,
        'review_flags': review_flags if attachment else [],
        'has_attachment': bool(attachment),
        'has_basic_assignment': bool(basic_assignment),
        'node_is_locked': bool(attachment),
        'show_basic_assignment_warning': bool(attachment and basic_assignment),
        'can_assign_in_nms': key in ('unassigned', 'basic_node_only'),
        'can_reassign_in_nms': bool(attachment),
        'can_view_topology': has_map_context and bool(attachment),
        'workspace_url': reverse('nms-subscriber-workspace', args=[subscriber.pk]),
        'map_url': f"{reverse('nms-map')}?subscriber={subscriber.pk}",
        'distribution_url': reverse('nms-distribution-detail', args=[node.pk]) if node else '',
    }


def build_topology_link_points(link):
    points = []

    if (
        link.source_node.latitude is not None
        and link.source_node.longitude is not None
    ):
        points.append([link.source_node.latitude, link.source_node.longitude])

    for vertex in link.vertices.all():
        points.append([vertex.latitude, vertex.longitude])

    if (
        link.target_node.latitude is not None
        and link.target_node.longitude is not None
    ):
        points.append([link.target_node.latitude, link.target_node.longitude])

    return points


def build_topology_link_geometry_text(link):
    return '\n'.join(
        f"{vertex.latitude},{vertex.longitude}" for vertex in link.vertices.all()
    )


def get_attachment_serving_node(attachment):
    if attachment.node_id:
        return attachment.node
    if attachment.endpoint_id:
        return attachment.endpoint.root_node
    return None


def build_service_attachment_points(attachment):
    points = []
    serving_node = get_attachment_serving_node(attachment)

    if (
        serving_node
        and serving_node.latitude is not None
        and serving_node.longitude is not None
    ):
        points.append([serving_node.latitude, serving_node.longitude])

    if has_service_attachment_geometry_tables():
        for vertex in attachment.vertices.all():
            points.append([vertex.latitude, vertex.longitude])

    subscriber = attachment.subscriber
    if (
        subscriber.latitude is not None
        and subscriber.longitude is not None
    ):
        points.append([subscriber.latitude, subscriber.longitude])

    return points


def build_service_attachment_geometry_text(attachment):
    if not has_service_attachment_geometry_tables():
        return ''
    return '\n'.join(
        f"{vertex.latitude},{vertex.longitude}" for vertex in attachment.vertices.all()
    )


def get_subscriber_billing_state(subscriber):
    if not getattr(subscriber, 'is_billable', True):
        return 'non_billable'

    open_invoices = Invoice.objects.filter(
        subscriber=subscriber,
        status__in=['open', 'partial', 'overdue'],
    )
    if open_invoices.filter(Q(status='overdue') | Q(due_date__lt=date.today())).exists():
        return 'overdue'
    if any(invoice.remaining_balance > 0 for invoice in open_invoices):
        return 'open'
    return 'clear'


def get_attachment_line_state(attachment):
    endpoint = attachment.endpoint
    if endpoint and endpoint.router_interface_id:
        try:
            cache = endpoint.router_interface.traffic_cache
        except ObjectDoesNotExist:
            cache = None
        if cache:
            if cache.activity_state == 'active':
                return 'active'
            if cache.activity_state in ('down', 'error'):
                return 'down'
            if cache.activity_state == 'idle':
                return 'idle'

    if attachment.subscriber.mt_status == 'online':
        return 'active'
    if attachment.subscriber.mt_status == 'offline':
        return 'down'
    if attachment.status == 'needs_review':
        return 'review'
    return 'unknown'


def serialize_service_attachment(attachment):
    serving_node = get_attachment_serving_node(attachment)
    vertices = list(attachment.vertices.all()) if has_service_attachment_geometry_tables() else []
    upstream_complete = endpoint_has_upstream_path(attachment.endpoint) if attachment.endpoint_id else False
    full_points = build_service_attachment_full_points(attachment)
    return {
        'id': attachment.id,
        'subscriber_id': attachment.subscriber_id,
        'subscriber_name': attachment.subscriber.display_name,
        'subscriber_username': attachment.subscriber.username,
        'subscriber_detail_url': reverse('subscriber-detail', args=[attachment.subscriber_id]),
        'workspace_url': reverse('nms-subscriber-workspace', args=[attachment.subscriber_id]),
        'node_id': serving_node.pk if serving_node else None,
        'node_name': serving_node.name if serving_node else '',
        'status': attachment.status,
        'endpoint_label': attachment.resolved_endpoint_label,
        'subscriber_lat': attachment.subscriber.latitude,
        'subscriber_lng': attachment.subscriber.longitude,
        'node_lat': serving_node.latitude if serving_node else None,
        'node_lng': serving_node.longitude if serving_node else None,
        'vertex_count': len(vertices),
        'geometry_text': '\n'.join(
            f"{vertex.latitude},{vertex.longitude}" for vertex in vertices
        ),
        'points': build_service_attachment_points(attachment),
        'full_points': full_points,
        'upstream_complete': upstream_complete,
        'line_state': get_attachment_line_state(attachment),
        'billing_state': get_subscriber_billing_state(attachment.subscriber),
    }


def serialize_topology_link(link, *, highlighted_node_id=None):
    vertices = list(link.vertices.all())
    points = build_topology_link_points(link)
    cable = getattr(link, 'cable', None) if has_cable_tables() else None
    cable_review_flags = get_cable_review_flags(cable) if cable else []

    return {
        'id': link.id,
        'name': link.display_name,
        'link_type': link.link_type,
        'status': link.status,
        'source_node_id': link.source_node_id,
        'source_node_name': link.source_node.name,
        'source_node_lat': link.source_node.latitude,
        'source_node_lng': link.source_node.longitude,
        'target_node_id': link.target_node_id,
        'target_node_name': link.target_node.name,
        'target_node_lat': link.target_node.latitude,
        'target_node_lng': link.target_node.longitude,
        'vertex_count': len(vertices),
        'geometry_text': '\n'.join(
            f"{vertex.latitude},{vertex.longitude}" for vertex in vertices
        ),
        'notes': link.notes or '',
        'cable_name': cable.name if cable else '',
        'cable_code': cable.code if cable else '',
        'cable_total_cores': cable.total_cores if cable else 0,
        'cable_used_cores': cable.used_core_count if cable else 0,
        'cable_available_cores': cable.available_core_count if cable else 0,
        'cable_status': cable.status if cable else '',
        'cable_review_flags': cable_review_flags,
        'points': points,
        'is_focus_related': bool(
            highlighted_node_id
            and highlighted_node_id in (link.source_node_id, link.target_node_id)
        ),
        'edit_url': f"{reverse('nms-links')}?link={link.id}",
    }


def serialize_network_node(node):
    return {
        'id': node.id,
        'name': node.name,
        'node_type': node.node_type,
        'node_type_label': node.get_node_type_display(),
        'lat': node.latitude,
        'lng': node.longitude,
        'port_count': node.port_count,
        'notes': node.notes or '',
        'is_active': node.is_active,
        'is_system': getattr(node, 'is_system', False),
        'system_role': getattr(node, 'system_role', ''),
        'router_id': node.router_id,
        'router_name': node.router.name if node.router_id else '',
        'distribution_url': reverse('nms-distribution-detail', args=[node.id]) if has_distribution_tables() else '',
        'edit_url': f"{reverse('nms-nodes')}?node={node.id}",
    }


def calculate_distance_km(point_a, point_b):
    lat1, lng1 = point_a
    lat2, lng2 = point_b
    earth_radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def calculate_path_distance_km(points):
    distance = 0
    for index in range(1, len(points)):
        distance += calculate_distance_km(points[index - 1], points[index])
    return distance


def get_link_geometry_distance_km(link):
    return calculate_path_distance_km(build_topology_link_points(link))


def get_link_inventory_distance_km(link):
    cable = getattr(link, 'cable', None) if has_cable_tables() else None
    if cable and cable.length_meters:
        return float(cable.length_meters) / 1000
    return get_link_geometry_distance_km(link)


def parse_gps_trace_points(coordinates_text):
    points = []
    for line_number, raw_line in enumerate((coordinates_text or '').splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split(',')]
        if len(parts) < 2:
            raise ValueError(f'Line {line_number} must start with "lat,lng".')

        try:
            latitude = float(parts[0])
            longitude = float(parts[1])
        except ValueError as exc:
            raise ValueError(f'Line {line_number} contains invalid coordinates.') from exc

        if not -90 <= latitude <= 90:
            raise ValueError(f'Line {line_number} latitude must be between -90 and 90.')
        if not -180 <= longitude <= 180:
            raise ValueError(f'Line {line_number} longitude must be between -180 and 180.')

        note = ', '.join(parts[2:])[:120] if len(parts) > 2 else ''
        points.append({
            'sequence': len(points) + 1,
            'latitude': latitude,
            'longitude': longitude,
            'note': note,
        })

    if len(points) < 2:
        raise ValueError('GPS traces need at least two coordinate points.')

    return points


def get_gps_trace_distance_km(trace):
    points = [
        (point.latitude, point.longitude)
        for point in trace.points.all()
    ]
    return calculate_path_distance_km(points)


def get_topology_route_report():
    if not has_topology_link_tables():
        return []

    links = TopologyLink.objects.select_related(
        'source_node',
        'target_node',
    ).prefetch_related('vertices')
    if has_cable_tables():
        links = links.select_related('cable').prefetch_related('cable__cores')

    report = []
    for link in links:
        cable = getattr(link, 'cable', None) if has_cable_tables() else None
        geometry_km = get_link_geometry_distance_km(link)
        inventory_km = get_link_inventory_distance_km(link)
        report.append({
            'link': link,
            'geometry_km': round(geometry_km, 3),
            'inventory_km': round(inventory_km, 3),
            'uses_inventory_length': bool(cable and cable.length_meters),
            'core_total': cable.total_cores if cable else 0,
            'core_used': cable.used_core_count if cable else 0,
            'core_available': cable.available_core_count if cable else 0,
            'utilization_percent': round((cable.used_core_count / cable.total_cores) * 100, 1) if cable and cable.total_cores else 0,
        })
    return report


def get_cable_utilization_report():
    if not has_cable_tables():
        return []

    return [
        {
            'cable': cable,
            'used': cable.used_core_count,
            'available': cable.available_core_count,
            'total': cable.total_cores,
            'utilization_percent': round((cable.used_core_count / cable.total_cores) * 100, 1) if cable.total_cores else 0,
            'review_flags': get_cable_review_flags(cable),
        }
        for cable in Cable.objects.select_related(
            'link',
            'link__source_node',
            'link__target_node',
        ).prefetch_related('cores').order_by('name', 'id')
    ]


def get_endpoint_splitter_loss_db(endpoint):
    if endpoint is None or not endpoint.internal_device_id:
        return 0

    device = endpoint.internal_device
    if device.is_plc:
        losses = {
            '1x4': 7.2,
            '1x8': 10.5,
            '1x16': 13.7,
            '1x32': 17.0,
        }
        return losses.get(device.plc_model, 0)

    if device.is_fbt and endpoint.endpoint_type == 'split_output':
        _, secondary_ratio = device.fbt_ratio_parts
        losses = {
            5: 13.7,
            10: 10.5,
            15: 8.8,
            20: 7.4,
            25: 6.5,
            30: 5.7,
            35: 5.0,
            40: 4.4,
            45: 3.9,
            50: 3.5,
        }
        return losses.get(secondary_ratio, 0)

    return 0


def estimate_attachment_power_budget(attachment):
    core_assignments = get_attachment_core_assignments(attachment)
    cable_distance_km = 0
    missing_length = False
    for assignment in core_assignments:
        link = assignment.core.cable.link
        cable = assignment.core.cable
        if cable.length_meters:
            cable_distance_km += float(cable.length_meters) / 1000
        else:
            cable_distance_km += get_link_geometry_distance_km(link)
            missing_length = True

    endpoint_loss_db = get_endpoint_splitter_loss_db(attachment.endpoint)
    fiber_loss_db = cable_distance_km * 0.35
    connector_loss_db = 0.6
    estimated_loss_db = fiber_loss_db + endpoint_loss_db + connector_loss_db
    budget_db = 28.0

    flags = []
    if not core_assignments:
        flags.append('No structured cable core assignment yet.')
    if missing_length:
        flags.append('Using map geometry for at least one cable length estimate.')

    return {
        'attachment': attachment,
        'core_assignments': core_assignments,
        'cable_distance_km': round(cable_distance_km, 3),
        'fiber_loss_db': round(fiber_loss_db, 2),
        'endpoint_loss_db': round(endpoint_loss_db, 2),
        'connector_loss_db': connector_loss_db,
        'estimated_loss_db': round(estimated_loss_db, 2),
        'budget_db': budget_db,
        'margin_db': round(budget_db - estimated_loss_db, 2),
        'flags': flags,
    }


def get_power_budget_report(limit=75):
    if not has_service_attachment_table():
        return []

    attachments = ServiceAttachment.objects.select_related(
        'subscriber',
        'node',
        'endpoint',
        'endpoint__internal_device',
        'endpoint__parent_node',
    ).filter(status='active').order_by('subscriber__username')[:limit]
    return [
        estimate_attachment_power_budget(attachment)
        for attachment in attachments
    ]


def _attachment_node_id(attachment):
    if attachment.node_id:
        return attachment.node_id
    if attachment.endpoint_id:
        return attachment.endpoint.root_node_id
    return None


def get_downstream_node_ids_from_link(link):
    if not has_topology_link_tables():
        return set()

    adjacency = {}
    active_links = TopologyLink.objects.filter(status='active').values_list(
        'source_node_id',
        'target_node_id',
    )
    for source_node_id, target_node_id in active_links:
        adjacency.setdefault(source_node_id, set()).add(target_node_id)

    impacted = {link.target_node_id}
    queue = [link.target_node_id]
    blocked_node_id = link.source_node_id
    while queue:
        node_id = queue.pop(0)
        for next_node_id in adjacency.get(node_id, set()):
            if next_node_id == blocked_node_id or next_node_id in impacted:
                continue
            impacted.add(next_node_id)
            queue.append(next_node_id)
    return impacted


def get_downstream_node_ids_from_node(node):
    if not has_topology_link_tables():
        return {node.pk}

    adjacency = {}
    active_links = TopologyLink.objects.filter(status='active').values_list(
        'source_node_id',
        'target_node_id',
    )
    for source_node_id, target_node_id in active_links:
        adjacency.setdefault(source_node_id, set()).add(target_node_id)

    impacted = {node.pk}
    queue = [node.pk]
    while queue:
        node_id = queue.pop(0)
        for next_node_id in adjacency.get(node_id, set()):
            if next_node_id in impacted:
                continue
            impacted.add(next_node_id)
            queue.append(next_node_id)
    return impacted


def get_outage_impact(*, node=None, link=None):
    if link is not None:
        impacted_node_ids = get_downstream_node_ids_from_link(link)
        target_label = link.display_name
    elif node is not None:
        impacted_node_ids = get_downstream_node_ids_from_node(node)
        target_label = node.name
    else:
        impacted_node_ids = set()
        target_label = ''

    attachments = []
    if impacted_node_ids and has_service_attachment_table():
        for attachment in ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__internal_device',
            'endpoint__parent_node',
        ).filter(status='active').order_by('subscriber__username'):
            if _attachment_node_id(attachment) in impacted_node_ids:
                attachments.append(attachment)

    impacted_nodes = NetworkNode.objects.filter(pk__in=impacted_node_ids).order_by('name')
    return {
        'target_label': target_label,
        'node_ids': impacted_node_ids,
        'nodes': impacted_nodes,
        'attachments': attachments,
        'subscriber_count': len(attachments),
        'node_count': len(impacted_node_ids),
    }


def build_nms_validation_report():
    issues = []

    def add_issue(severity, category, title, message, *, action_url='', action_label='Open'):
        issues.append({
            'severity': severity,
            'category': category,
            'title': title,
            'message': message,
            'action_url': action_url,
            'action_label': action_label,
        })

    if has_service_attachment_table():
        attachments = ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__internal_device',
            'endpoint__parent_node',
        ).order_by('subscriber__username')
        for attachment in attachments:
            for flag in get_attachment_review_flags(attachment):
                add_issue(
                    'critical' if flag['code'] in {'endpoint_occupied', 'missing_node', 'damaged_endpoint', 'damaged_core_assignment'} else 'warning',
                    'Subscriber Mapping',
                    attachment.subscriber.display_name,
                    flag['message'],
                    action_url=reverse('nms-subscriber-workspace', args=[attachment.subscriber_id]),
                    action_label='Resolve in NMS',
                )

            node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
            if attachment.status == 'active' and not attachment.endpoint_id:
                add_issue(
                    'info',
                    'Subscriber Mapping',
                    attachment.subscriber.display_name,
                    'This mapping is active but still uses only a serving node or manual endpoint label.',
                    action_url=reverse('nms-subscriber-workspace', args=[attachment.subscriber_id]),
                    action_label='Add Endpoint',
                )
            if node and (
                attachment.subscriber.latitude is None
                or attachment.subscriber.longitude is None
                or node.latitude is None
                or node.longitude is None
            ):
                add_issue(
                    'info',
                    'Map Readiness',
                    attachment.subscriber.display_name,
                    'Subscriber or serving node coordinates are missing, so topology visualization is limited.',
                    action_url=reverse('nms-subscriber-workspace', args=[attachment.subscriber_id]),
                    action_label='Open Mapping',
                )

        duplicate_endpoints = ServiceAttachment.objects.filter(
            status='active',
            endpoint_id__isnull=False,
        ).values('endpoint_id').annotate(active_count=Count('id')).filter(active_count__gt=1)
        for duplicate in duplicate_endpoints:
            add_issue(
                'critical',
                'Endpoint Occupancy',
                f"Endpoint #{duplicate['endpoint_id']}",
                f"{duplicate['active_count']} active subscriber mappings point to the same endpoint.",
                action_url=reverse('nms-map'),
                action_label='Open Map',
            )

    if has_router_root_node_fields():
        for router in Router.objects.filter(is_active=True, latitude__isnull=False, longitude__isnull=False):
            root_nodes = NetworkNode.objects.filter(router=router, system_role='router_root')
            if not root_nodes.exists():
                add_issue(
                    'warning',
                    'Router Root',
                    router.name,
                    'Router has coordinates but no Premium NMS router root node yet.',
                    action_url=reverse('nms-operations'),
                    action_label='Sync Router Roots',
                )
            elif root_nodes.count() > 1:
                add_issue(
                    'critical',
                    'Router Root',
                    router.name,
                    'Router has more than one root NMS node.',
                    action_url=reverse('nms-nodes'),
                    action_label='Review Nodes',
                )
            else:
                root_node = root_nodes.first()
                if root_node.latitude != router.latitude or root_node.longitude != router.longitude:
                    add_issue(
                        'warning',
                        'Router Root',
                        router.name,
                        'Router root node coordinates do not match the router coordinates.',
                        action_url=f"{reverse('nms-nodes')}?node={root_node.pk}",
                        action_label='Open Node',
                    )

    if has_distribution_tables() and has_service_attachment_table():
        endpoints = Endpoint.objects.select_related(
            'parent_node',
            'internal_device',
            'internal_device__parent_node',
            'router_interface',
            'router_interface__router',
        )
        for endpoint in endpoints:
            if endpoint.status in ('inactive', 'damaged'):
                continue
            has_active_attachment = ServiceAttachment.objects.filter(
                endpoint=endpoint,
                status='active',
            ).exists()
            expected_status = 'occupied' if has_active_attachment else 'available'
            if endpoint.status != expected_status:
                root_node = endpoint.root_node
                add_issue(
                    'warning',
                    'Endpoint Occupancy',
                    endpoint.display_name,
                    f"Endpoint inventory says {endpoint.get_status_display()}, but active mappings imply {expected_status}.",
                    action_url=reverse('nms-distribution-detail', args=[root_node.pk]) if root_node else reverse('nms-map'),
                    action_label='Open Distribution',
                )
            if not is_source_endpoint(endpoint) and not endpoint_has_upstream_path(endpoint):
                root_node = endpoint.root_node
                add_issue(
                    'info',
                    'Endpoint Wiring',
                    endpoint.display_name,
                    'Endpoint has no active upstream path back to a router source.',
                    action_url=reverse('nms-distribution-detail', args=[root_node.pk]) if root_node else reverse('nms-map'),
                    action_label='Open Distribution',
                )

    if has_endpoint_connection_tables():
        for connection in EndpointConnection.objects.select_related(
            'upstream_endpoint',
            'upstream_endpoint__parent_node',
            'upstream_endpoint__internal_device__parent_node',
            'downstream_endpoint',
            'downstream_endpoint__parent_node',
            'downstream_endpoint__internal_device__parent_node',
            'topology_link',
            'cable_core',
            'cable_core__cable',
        ):
            upstream_node = connection.upstream_endpoint.root_node
            downstream_node = connection.downstream_endpoint.root_node
            if (
                upstream_node
                and downstream_node
                and upstream_node.pk != downstream_node.pk
                and not connection.topology_link_id
            ):
                add_issue(
                    'warning',
                    'Endpoint Wiring',
                    connection.display_name,
                    'Cross-node endpoint wiring should reference the physical topology link it uses.',
                    action_url=reverse('nms-distribution-detail', args=[downstream_node.pk]),
                    action_label='Open Distribution',
                )
            if connection.cable_core_id and connection.topology_link_id and connection.cable_core.cable.link_id != connection.topology_link_id:
                add_issue(
                    'critical',
                    'Endpoint Wiring',
                    connection.display_name,
                    'Endpoint wiring references a cable core from a different topology link.',
                    action_url=reverse('nms-distribution-detail', args=[downstream_node.pk]) if downstream_node else reverse('nms-map'),
                    action_label='Open Distribution',
                )

    if has_cable_tables():
        for cable in Cable.objects.select_related(
            'link',
            'link__source_node',
            'link__target_node',
        ).prefetch_related('cores'):
            for flag in get_cable_review_flags(cable):
                add_issue(
                    'critical' if flag['code'] in {'damaged_cable', 'invalid_core_count'} else 'warning',
                    'Cable Inventory',
                    cable.display_name,
                    flag['message'],
                    action_url=f"{reverse('nms-links')}?link={cable.link_id}",
                    action_label='Open Link',
                )

            if cable.used_core_count >= cable.total_cores and cable.total_cores:
                add_issue(
                    'info',
                    'Capacity',
                    cable.display_name,
                    'All cable cores are already used or reserved.',
                    action_url=f"{reverse('nms-links')}?link={cable.link_id}",
                    action_label='Open Link',
                )

    if has_topology_link_tables():
        links = TopologyLink.objects.select_related('source_node', 'target_node').prefetch_related('vertices')
        for link in links:
            if link.source_node_id == link.target_node_id:
                add_issue(
                    'critical',
                    'Topology Link',
                    link.display_name,
                    'Source and target nodes are the same.',
                    action_url=f"{reverse('nms-links')}?link={link.pk}",
                    action_label='Fix Link',
                )
            if (
                link.source_node.latitude is None
                or link.source_node.longitude is None
                or link.target_node.latitude is None
                or link.target_node.longitude is None
            ):
                add_issue(
                    'warning',
                    'Map Readiness',
                    link.display_name,
                    'One or both endpoint nodes are missing coordinates, so this link cannot render fully on the map.',
                    action_url=f"{reverse('nms-links')}?link={link.pk}",
                    action_label='Open Link',
                )

    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    issues.sort(key=lambda issue: (severity_order.get(issue['severity'], 9), issue['category'], issue['title']))
    return {
        'issues': issues,
        'critical_count': sum(1 for issue in issues if issue['severity'] == 'critical'),
        'warning_count': sum(1 for issue in issues if issue['severity'] == 'warning'),
        'info_count': sum(1 for issue in issues if issue['severity'] == 'info'),
        'total_count': len(issues),
    }


def refresh_all_attachment_review_states():
    if not has_service_attachment_table():
        return {'updated': 0}

    updated = 0
    for attachment in ServiceAttachment.objects.select_related(
        'subscriber',
        'node',
        'endpoint',
        'endpoint__internal_device',
        'endpoint__parent_node',
    ):
        old_status = attachment.status
        refresh_attachment_review_state(attachment, preserve_manual_review=False)
        if attachment.status != old_status:
            attachment.save(update_fields=['status', 'updated_at'])
            updated += 1
    return {'updated': updated}


def sync_all_endpoint_statuses():
    if not has_distribution_tables():
        return {'synced': 0}

    synced = 0
    for endpoint in Endpoint.objects.all():
        sync_endpoint_status(endpoint)
        synced += 1
    return {'synced': synced}


def sync_all_core_assignment_statuses():
    if not has_core_assignment_tables():
        return {'synced': 0}

    synced = 0
    for assignment in CableCoreAssignment.objects.select_related(
        'service_attachment',
        'service_attachment__subscriber',
        'core',
        'core__cable',
    ):
        apply_core_assignment(assignment)
        synced += 1
    return {'synced': synced}


def _node_attachment_queryset(node):
    if not has_service_attachment_table():
        return ServiceAttachment.objects.none()

    attachment_filter = Q(node=node)
    if has_distribution_tables():
        attachment_filter |= Q(endpoint__parent_node=node)
        attachment_filter |= Q(endpoint__internal_device__parent_node=node)
    return ServiceAttachment.objects.filter(attachment_filter).distinct()


def _node_topology_link_queryset(node):
    if not has_topology_link_tables():
        return TopologyLink.objects.none()
    return TopologyLink.objects.filter(Q(source_node=node) | Q(target_node=node)).distinct()


def get_node_delete_impact(node):
    attachments = _node_attachment_queryset(node)
    topology_links = _node_topology_link_queryset(node)

    internal_device_count = 0
    endpoint_count = 0
    if has_distribution_tables():
        internal_device_count = InternalDevice.objects.filter(parent_node=node).count()
        endpoint_count = Endpoint.objects.filter(
            Q(parent_node=node) | Q(internal_device__parent_node=node)
        ).count()

    cable_count = 0
    cable_core_count = 0
    core_assignment_count = 0
    if has_cable_tables():
        cables = Cable.objects.filter(link__in=topology_links)
        cable_count = cables.count()
        cable_core_count = CableCore.objects.filter(cable__in=cables).count()
        if has_core_assignment_tables():
            core_assignment_count = CableCoreAssignment.objects.filter(
                Q(core__cable__in=cables) | Q(service_attachment__in=attachments)
            ).distinct().count()

    return {
        'service_attachment_count': attachments.count(),
        'subscriber_node_count': SubscriberNode.objects.filter(node=node).count(),
        'internal_device_count': internal_device_count,
        'endpoint_count': endpoint_count,
        'topology_link_count': topology_links.count(),
        'cable_count': cable_count,
        'cable_core_count': cable_core_count,
        'core_assignment_count': core_assignment_count,
    }


def delete_node_with_descendants(node):
    impact = get_node_delete_impact(node)
    attachments = list(_node_attachment_queryset(node).prefetch_related('vertices'))
    if has_core_assignment_tables():
        for assignment in CableCoreAssignment.objects.select_related(
            'core',
        ).filter(service_attachment__in=attachments):
            release_core_assignment(assignment)
    for attachment in attachments:
        if has_service_attachment_geometry_tables():
            attachment.vertices.all().delete()
        attachment.node = None
        attachment.endpoint = None
        attachment.endpoint_label = f"Removed with node {node.name}"[:80]
        attachment.status = 'needs_review'
        attachment.save(update_fields=['node', 'endpoint', 'endpoint_label', 'status', 'updated_at'])
    node.delete()
    return impact
