from django.db import DatabaseError, connection
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from apps.nms.models import (
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


def get_subscriber_topology_summary(subscriber, table_ready=None):
    attachment = get_service_attachment(subscriber, table_ready=table_ready)
    basic_assignment = get_basic_node_assignment(subscriber)

    key = 'unassigned'
    label = 'Unassigned'
    node = None
    endpoint_label = ''
    notes = ''

    if attachment:
        node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
        endpoint_label = attachment.resolved_endpoint_label
        notes = attachment.notes or ''
        if attachment.status == 'needs_review' or attachment.node_id is None:
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
        'points': points,
        'is_focus_related': bool(
            highlighted_node_id
            and highlighted_node_id in (link.source_node_id, link.target_node_id)
        ),
        'edit_url': f"{reverse('nms-links')}?link={link.id}",
    }
