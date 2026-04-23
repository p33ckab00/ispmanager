from django.db import DatabaseError, connection
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.urls import reverse
from apps.nms.models import (
    Cable,
    CableCore,
    Endpoint,
    InternalDevice,
    ServiceAttachment,
    TopologyLink,
    TopologyLinkVertex,
)
from apps.subscribers.models import SubscriberNode


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


def has_topology_link_tables():
    return has_model_table(TopologyLink) and has_model_table(TopologyLinkVertex)


def has_distribution_tables():
    return has_model_table(InternalDevice) and has_model_table(Endpoint)


def has_cable_tables():
    return has_model_table(Cable) and has_model_table(CableCore)


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


def get_eligible_endpoints(*, selected_node=None, current_attachment=None):
    if not has_distribution_tables():
        return Endpoint.objects.none()

    queryset = Endpoint.objects.select_related(
        'parent_node',
        'internal_device',
        'internal_device__parent_node',
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
    ).filter(pk__in=eligible_ids).order_by(
        'parent_node__name',
        'internal_device__parent_node__name',
        'internal_device__name',
        'sequence',
        'label',
    )


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
    elif attachment.status == 'needs_review':
        add_flag('manual_review', 'This mapping is still marked as needing review.')

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
        'router_id': node.router_id,
        'router_name': node.router.name if node.router_id else '',
        'distribution_url': reverse('nms-distribution-detail', args=[node.id]) if has_distribution_tables() else '',
        'edit_url': f"{reverse('nms-nodes')}?node={node.id}",
    }
