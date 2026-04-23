from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_POST
from apps.routers.models import Router
from apps.subscribers.models import Subscriber, NetworkNode
from apps.core.models import AuditLog
from apps.nms.forms import (
    EndpointForm,
    InternalDeviceForm,
    ServiceAttachmentForm,
    TopologyLinkForm,
    TopologyLinkGeometryForm,
)
from apps.nms.models import Endpoint, InternalDevice, ServiceAttachment, TopologyLink
from apps.nms.services import (
    get_basic_node_assignment,
    get_service_attachment,
    get_subscriber_topology_summary,
    has_distribution_tables,
    has_service_attachment_table,
    has_topology_link_tables,
    serialize_topology_link,
    sync_basic_node_summary,
    sync_endpoint_status,
)


@login_required
def nms_map(request):
    focus_subscriber = None
    subscriber_id = request.GET.get('subscriber')
    if subscriber_id:
        focus_subscriber = Subscriber.objects.filter(pk=subscriber_id).first()
    return render(request, 'nms/map.html', {
        'focus_subscriber': focus_subscriber,
        'service_attachment_ready': has_service_attachment_table(),
        'topology_links_ready': has_topology_link_tables(),
    })


@login_required
def nms_map_data(request):
    focus_subscriber_id = request.GET.get('subscriber')
    service_attachment_ready = has_service_attachment_table()
    topology_links_ready = has_topology_link_tables()
    distribution_ready = has_distribution_tables()
    routers = Router.objects.filter(
        is_active=True,
        latitude__isnull=False,
        longitude__isnull=False,
    ).values('id', 'name', 'host', 'status', 'latitude', 'longitude', 'location')

    subscribers = Subscriber.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).select_related('plan').values(
        'id', 'username', 'full_name', 'status', 'mt_status',
        'latitude', 'longitude', 'ip_address', 'plan__name',
    )
    nodes = NetworkNode.objects.filter(
        is_active=True,
        latitude__isnull=False,
        longitude__isnull=False,
    ).values('id', 'name', 'node_type', 'latitude', 'longitude')
    attachments = []
    if service_attachment_ready:
        attachments = ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__internal_device',
            'endpoint__parent_node',
        ).filter(
            subscriber__latitude__isnull=False,
            subscriber__longitude__isnull=False,
        ).filter(
            Q(node__latitude__isnull=False, node__longitude__isnull=False)
            | Q(
                endpoint__parent_node__latitude__isnull=False,
                endpoint__parent_node__longitude__isnull=False,
            )
            | Q(
                endpoint__internal_device__parent_node__latitude__isnull=False,
                endpoint__internal_device__parent_node__longitude__isnull=False,
            )
        )
    topology_links = []
    if topology_links_ready:
        topology_links = TopologyLink.objects.select_related(
            'source_node',
            'target_node',
        ).prefetch_related('vertices').filter(
            source_node__latitude__isnull=False,
            source_node__longitude__isnull=False,
            target_node__latitude__isnull=False,
            target_node__longitude__isnull=False,
        )

    focus_node_id = None
    if focus_subscriber_id and service_attachment_ready:
        focus_attachment = ServiceAttachment.objects.select_related(
            'node',
            'endpoint',
            'endpoint__parent_node',
            'endpoint__internal_device__parent_node',
        ).filter(subscriber_id=focus_subscriber_id).first()
        if focus_attachment:
            focus_node = focus_attachment.node or (
                focus_attachment.endpoint.root_node if focus_attachment.endpoint_id else None
            )
            focus_node_id = focus_node.pk if focus_node else None

    attachment_by_subscriber_id = {}
    for attachment in attachments:
        attachment_by_subscriber_id[attachment.subscriber_id] = attachment

    router_list = []
    for r in routers:
        router_list.append({
            'type': 'router',
            'id': r['id'],
            'name': r['name'],
            'host': r['host'],
            'status': r['status'],
            'lat': r['latitude'],
            'lng': r['longitude'],
            'location': r['location'] or '',
        })

    sub_list = []
    for s in subscribers:
        attachment = attachment_by_subscriber_id.get(s['id'])
        mapped_node = None
        mapped_endpoint_name = ''
        distribution_url = ''
        if attachment:
            mapped_node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
            mapped_endpoint_name = attachment.resolved_endpoint_label
            if mapped_node:
                distribution_url = reverse('nms-distribution-detail', args=[mapped_node.pk])
        sub_list.append({
            'type': 'subscriber',
            'id': s['id'],
            'username': s['username'],
            'name': s['full_name'] or s['username'],
            'status': s['status'],
            'mt_status': s['mt_status'],
            'lat': s['latitude'],
            'lng': s['longitude'],
            'ip': s['ip_address'] or '',
            'plan': s['plan__name'] or '',
            'topology_status': attachment.status if attachment else 'unassigned',
            'mapped_node_id': mapped_node.pk if mapped_node else None,
            'mapped_node_name': mapped_node.name if mapped_node else '',
            'mapped_endpoint_name': mapped_endpoint_name,
            'workspace_url': reverse('nms-subscriber-workspace', args=[s['id']]),
            'detail_url': reverse('subscriber-detail', args=[s['id']]),
            'distribution_url': distribution_url,
        })

    node_list = []
    for n in nodes:
        node_list.append({
            'type': 'network_node',
            'id': n['id'],
            'name': n['name'],
            'node_type': n['node_type'],
            'lat': n['latitude'],
            'lng': n['longitude'],
            'distribution_url': reverse('nms-distribution-detail', args=[n['id']]) if distribution_ready else '',
        })

    attachment_list = []
    for attachment in attachments:
        mapped_node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
        if mapped_node is None:
            continue
        attachment_list.append({
            'subscriber_id': attachment.subscriber_id,
            'subscriber_name': attachment.subscriber.display_name,
            'subscriber_username': attachment.subscriber.username,
            'subscriber_detail_url': reverse('subscriber-detail', args=[attachment.subscriber_id]),
            'workspace_url': reverse('nms-subscriber-workspace', args=[attachment.subscriber_id]),
            'node_id': mapped_node.pk,
            'node_name': mapped_node.name,
            'status': attachment.status,
            'endpoint_label': attachment.resolved_endpoint_label,
            'subscriber_lat': attachment.subscriber.latitude,
            'subscriber_lng': attachment.subscriber.longitude,
            'node_lat': mapped_node.latitude,
            'node_lng': mapped_node.longitude,
        })

    link_list = []
    for topology_link in topology_links:
        serialized_link = serialize_topology_link(
            topology_link,
            highlighted_node_id=focus_node_id,
        )
        if len(serialized_link['points']) < 2:
            continue
        link_list.append(serialized_link)

    return JsonResponse({
        'routers': router_list,
        'subscribers': sub_list,
        'nodes': node_list,
        'attachments': attachment_list,
        'links': link_list,
        'service_attachment_ready': service_attachment_ready,
        'topology_links_ready': topology_links_ready,
        'distribution_ready': distribution_ready,
        'focus_node_id': focus_node_id,
        'focus_subscriber_id': int(focus_subscriber_id) if focus_subscriber_id and focus_subscriber_id.isdigit() else None,
    })


@login_required
@require_POST
def nms_create_link_api(request):
    if not has_topology_link_tables():
        return JsonResponse({
            'ok': False,
            'message': 'Topology link database migration is not applied yet.',
        }, status=503)

    form = TopologyLinkForm(request.POST)
    if form.is_valid():
        topology_link = form.save()
        topology_link = TopologyLink.objects.select_related(
            'source_node',
            'target_node',
        ).prefetch_related('vertices').get(pk=topology_link.pk)
        AuditLog.log(
            'create',
            'nms',
            f"Topology link created from map: {topology_link.display_name}",
            user=request.user,
        )
        return JsonResponse({
            'ok': True,
            'message': f"Topology link created: {topology_link.display_name}.",
            'link': serialize_topology_link(topology_link),
        })

    return JsonResponse({
        'ok': False,
        'errors': form.errors.get_json_data(),
    }, status=400)


@login_required
@require_POST
def nms_update_link_geometry_api(request, link_pk):
    if not has_topology_link_tables():
        return JsonResponse({
            'ok': False,
            'message': 'Topology link database migration is not applied yet.',
        }, status=503)

    topology_link = get_object_or_404(
        TopologyLink.objects.select_related('source_node', 'target_node').prefetch_related('vertices'),
        pk=link_pk,
    )
    form = TopologyLinkGeometryForm(request.POST, link=topology_link)
    if form.is_valid():
        form.save()
        topology_link.refresh_from_db()
        topology_link = TopologyLink.objects.select_related(
            'source_node',
            'target_node',
        ).prefetch_related('vertices').get(pk=topology_link.pk)
        AuditLog.log(
            'update',
            'nms',
            f"Topology link geometry updated: {topology_link.display_name}",
            user=request.user,
        )
        return JsonResponse({
            'ok': True,
            'message': f"Geometry updated for {topology_link.display_name}.",
            'link': serialize_topology_link(topology_link),
        })

    return JsonResponse({
        'ok': False,
        'errors': form.errors.get_json_data(),
    }, status=400)


@login_required
def nms_links(request):
    if not has_topology_link_tables():
        messages.error(request, 'Topology link database migration is not applied yet.')
        return redirect('nms-map')

    selected_link = None
    selected_link_id = request.GET.get('link')
    if selected_link_id and selected_link_id.isdigit():
        selected_link = get_object_or_404(
            TopologyLink.objects.select_related('source_node', 'target_node').prefetch_related('vertices'),
            pk=selected_link_id,
        )

    if request.method == 'POST':
        is_create = selected_link is None
        form = TopologyLinkForm(request.POST, instance=selected_link)
        if form.is_valid():
            topology_link = form.save()
            AuditLog.log(
                'create' if is_create else 'update',
                'nms',
                f"Topology link saved: {topology_link.display_name}",
                user=request.user,
            )
            messages.success(request, f"Topology link saved: {topology_link.display_name}.")
            return redirect(f"{reverse('nms-links')}?link={topology_link.pk}")
    else:
        form = TopologyLinkForm(instance=selected_link)

    links = TopologyLink.objects.select_related('source_node', 'target_node').prefetch_related('vertices')
    return render(request, 'nms/links.html', {
        'form': form,
        'selected_link': selected_link,
        'links': links,
    })


@login_required
def nms_delete_link(request, link_pk):
    if not has_topology_link_tables():
        messages.error(request, 'Topology link database migration is not applied yet.')
        return redirect('nms-map')

    topology_link = get_object_or_404(TopologyLink, pk=link_pk)
    if request.method == 'POST':
        link_name = topology_link.display_name
        topology_link.delete()
        AuditLog.log(
            'delete',
            'nms',
            f"Topology link deleted: {link_name}",
            user=request.user,
        )
        messages.success(request, f"Topology link deleted: {link_name}.")
    return redirect('nms-links')


@login_required
def nms_subscriber_workspace(request, subscriber_pk):
    if not has_service_attachment_table():
        messages.error(request, 'Premium NMS database migration is not applied yet.')
        return redirect('subscriber-detail', pk=subscriber_pk)

    subscriber = get_object_or_404(Subscriber, pk=subscriber_pk)
    attachment = get_service_attachment(subscriber, table_ready=True)
    basic_assignment = get_basic_node_assignment(subscriber)
    distribution_ready = has_distribution_tables()

    if request.method == 'POST':
        is_create = attachment is None
        previous_endpoint = attachment.endpoint if attachment else None
        form = ServiceAttachmentForm(request.POST, instance=attachment)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.subscriber = subscriber
            if attachment.endpoint_id:
                attachment.node = attachment.endpoint.root_node
            attachment.assigned_by = request.user.username
            attachment.save()
            sync_basic_node_summary(subscriber, attachment.node, attachment.resolved_endpoint_label)
            if previous_endpoint and previous_endpoint.pk != attachment.endpoint_id:
                sync_endpoint_status(previous_endpoint)
            sync_endpoint_status(attachment.endpoint)
            AuditLog.log(
                'create' if is_create else 'update',
                'nms',
                f"Premium NMS mapping saved for {subscriber.username}",
                user=request.user,
            )
            messages.success(request, f"Premium NMS mapping saved for {subscriber.display_name}.")
            return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)
    else:
        initial = {}
        if not attachment and basic_assignment:
            initial = {
                'node': basic_assignment.node,
                'endpoint_label': basic_assignment.port_label,
            }
        form = ServiceAttachmentForm(instance=attachment, initial=initial)

    topology_summary = get_subscriber_topology_summary(subscriber, table_ready=True)
    return render(request, 'nms/subscriber_workspace.html', {
        'subscriber': subscriber,
        'attachment': attachment,
        'basic_assignment': basic_assignment,
        'form': form,
        'topology_summary': topology_summary,
        'distribution_ready': distribution_ready,
    })


@login_required
def nms_remove_service_attachment(request, subscriber_pk):
    if not has_service_attachment_table():
        messages.error(request, 'Premium NMS database migration is not applied yet.')
        return redirect('subscriber-detail', pk=subscriber_pk)

    subscriber = get_object_or_404(Subscriber, pk=subscriber_pk)
    attachment = get_service_attachment(subscriber, table_ready=True)
    if request.method == 'POST' and attachment:
        previous_endpoint = attachment.endpoint
        attachment.delete()
        sync_endpoint_status(previous_endpoint)
        AuditLog.log(
            'delete',
            'nms',
            f"Premium NMS mapping removed for {subscriber.username}",
            user=request.user,
        )
        messages.success(
            request,
            f"Premium NMS mapping removed for {subscriber.display_name}. Basic node summary was kept.",
        )
    return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)


@login_required
def nms_distribution_detail(request, node_pk):
    if not has_distribution_tables():
        messages.error(request, 'Distribution and endpoint tables are not applied yet.')
        return redirect('nms-map')

    node = get_object_or_404(
        NetworkNode.objects.select_related('router'),
        pk=node_pk,
    )

    device_form = InternalDeviceForm(prefix='device')
    endpoint_form = EndpointForm(parent_node=node, prefix='endpoint')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_device':
            device_form = InternalDeviceForm(request.POST, prefix='device')
            if device_form.is_valid():
                internal_device = device_form.save(commit=False)
                internal_device.parent_node = node
                internal_device.save()
                AuditLog.log(
                    'create',
                    'nms',
                    f"Internal device added to {node.name}: {internal_device.display_name}",
                    user=request.user,
                )
                messages.success(request, f"Internal device added: {internal_device.display_name}.")
                return redirect('nms-distribution-detail', node_pk=node.pk)
        elif action == 'create_endpoint':
            endpoint_form = EndpointForm(request.POST, parent_node=node, prefix='endpoint')
            if endpoint_form.is_valid():
                endpoint = endpoint_form.save()
                sync_endpoint_status(endpoint)
                AuditLog.log(
                    'create',
                    'nms',
                    f"Endpoint added to {node.name}: {endpoint.display_name}",
                    user=request.user,
                )
                messages.success(request, f"Endpoint added: {endpoint.display_name}.")
                return redirect('nms-distribution-detail', node_pk=node.pk)
        else:
            messages.error(request, 'Unknown distribution action.')

    internal_devices = InternalDevice.objects.filter(parent_node=node).prefetch_related(
        'endpoints',
    ).order_by('device_type', 'name', 'id')
    all_endpoints = list(Endpoint.objects.select_related(
        'parent_node',
        'internal_device',
        'internal_device__parent_node',
    ).filter(
        Q(parent_node=node) | Q(internal_device__parent_node=node)
    ).order_by(
        'internal_device__name',
        'sequence',
        'label',
        'id',
    ))
    direct_endpoints = [endpoint for endpoint in all_endpoints if endpoint.parent_node_id == node.pk]

    active_attachments = []
    attachment_by_endpoint_id = {}
    if has_service_attachment_table():
        active_attachments = list(
            ServiceAttachment.objects.select_related(
                'subscriber',
                'endpoint',
                'node',
            ).filter(
                Q(node=node)
                | Q(endpoint__parent_node=node)
                | Q(endpoint__internal_device__parent_node=node)
            ).order_by('subscriber__username')
        )
        attachment_by_endpoint_id = {
            attachment.endpoint_id: attachment
            for attachment in active_attachments
            if attachment.endpoint_id
        }
    for endpoint in all_endpoints:
        endpoint.active_attachment = attachment_by_endpoint_id.get(endpoint.id)

    return render(request, 'nms/distribution_detail.html', {
        'node': node,
        'device_form': device_form,
        'endpoint_form': endpoint_form,
        'internal_devices': internal_devices,
        'direct_endpoints': direct_endpoints,
        'all_endpoints': all_endpoints,
        'active_attachments': active_attachments,
        'service_attachment_ready': has_service_attachment_table(),
    })
