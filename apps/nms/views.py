from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_POST
from apps.routers.models import Router
from apps.subscribers.models import Subscriber, NetworkNode
from apps.core.models import AuditLog
from apps.nms.forms import (
    CableCoreAssignmentForm,
    EndpointConnectionForm,
    EndpointForm,
    GpsTraceImportForm,
    InternalDeviceForm,
    NetworkNodeForm,
    ServiceAttachmentForm,
    ServiceAttachmentGeometryForm,
    TopologyLinkForm,
    TopologyLinkGeometryForm,
)
from apps.nms.models import CableCoreAssignment, EndpointConnection, GpsTrace, Endpoint, InternalDevice, ServiceAttachment, TopologyLink
from apps.nms.services import (
    apply_core_assignment,
    build_nms_validation_report,
    delete_node_with_descendants,
    ensure_fbt_endpoints,
    ensure_plc_endpoints,
    get_attachment_core_assignments,
    get_attachment_review_flags,
    get_basic_node_assignment,
    get_cable_utilization_report,
    get_gps_trace_distance_km,
    get_node_delete_impact,
    get_outage_impact,
    get_power_budget_report,
    has_cable_tables,
    has_core_assignment_tables,
    get_topology_route_report,
    get_service_attachment,
    get_subscriber_billing_state,
    get_subscriber_topology_summary,
    has_distribution_tables,
    has_endpoint_connection_tables,
    has_gps_trace_tables,
    has_service_attachment_table,
    has_service_attachment_geometry_tables,
    has_topology_link_tables,
    refresh_attachment_review_state,
    refresh_all_attachment_review_states,
    release_core_assignment,
    serialize_network_node,
    serialize_service_attachment,
    serialize_topology_link,
    sync_all_core_assignment_statuses,
    sync_all_endpoint_statuses,
    sync_basic_node_summary,
    sync_endpoint_status,
    sync_router_roots_and_interface_endpoints,
)


def _merge_generated_port_counts(*results):
    return {
        'created_inputs': sum(result.get('created_inputs', 0) for result in results),
        'created_outputs': sum(result.get('created_outputs', 0) for result in results),
    }


@login_required
def nms_map(request):
    focus_subscriber = None
    subscriber_id = request.GET.get('subscriber')
    if subscriber_id:
        focus_subscriber = Subscriber.objects.filter(pk=subscriber_id).first()
    return render(request, 'nms/map.html', {
        'focus_subscriber': focus_subscriber,
        'cable_ready': has_cable_tables(),
        'service_attachment_ready': has_service_attachment_table(),
        'service_attachment_geometry_ready': has_service_attachment_geometry_tables(),
        'topology_links_ready': has_topology_link_tables(),
        'gps_trace_ready': has_gps_trace_tables(),
        'node_type_options': [{'value': value, 'label': label} for value, label in NetworkNode.TYPE_CHOICES],
        'router_options': list(
            Router.objects.filter(is_active=True).order_by('name').values('id', 'name')
        ),
    })


@login_required
def nms_map_data(request):
    focus_subscriber_id = request.GET.get('subscriber')
    sync_router_roots_and_interface_endpoints()
    service_attachment_ready = has_service_attachment_table()
    service_attachment_geometry_ready = has_service_attachment_geometry_tables()
    topology_links_ready = has_topology_link_tables()
    distribution_ready = has_distribution_tables()
    cable_ready = has_cable_tables()
    gps_trace_ready = has_gps_trace_tables()
    routers = Router.objects.filter(
        is_active=True,
        latitude__isnull=False,
        longitude__isnull=False,
    ).values('id', 'name', 'host', 'status', 'latitude', 'longitude', 'location')

    subscribers = Subscriber.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).select_related('plan')
    nodes = NetworkNode.objects.select_related('router').filter(
        is_active=True,
        latitude__isnull=False,
        longitude__isnull=False,
    )
    attachments = []
    if service_attachment_ready:
        attachments = ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__internal_device',
            'endpoint__parent_node',
            'endpoint__router_interface',
            'endpoint__router_interface__traffic_cache',
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
        if service_attachment_geometry_ready:
            attachments = attachments.prefetch_related('vertices')
    topology_links = []
    if topology_links_ready:
        topology_links = TopologyLink.objects.select_related(
            'source_node',
            'target_node',
        )
        if cable_ready:
            topology_links = topology_links.select_related('cable')
        topology_links = topology_links.prefetch_related('vertices').filter(
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
            'endpoint__router_interface',
        ).filter(subscriber_id=focus_subscriber_id).first()
        if focus_attachment:
            focus_node = focus_attachment.node or (
                focus_attachment.endpoint.root_node if focus_attachment.endpoint_id else None
            )
            focus_node_id = focus_node.pk if focus_node else None

    attachment_by_subscriber_id = {}
    for attachment in attachments:
        attachment_by_subscriber_id[attachment.subscriber_id] = attachment

    router_root_by_router_id = {
        node.router_id: node
        for node in nodes
        if getattr(node, 'system_role', '') == 'router_root' and node.router_id
    }

    router_list = []
    for r in routers:
        root_node = router_root_by_router_id.get(r['id'])
        router_list.append({
            'type': 'router',
            'id': r['id'],
            'name': r['name'],
            'host': r['host'],
            'status': r['status'],
            'lat': r['latitude'],
            'lng': r['longitude'],
            'location': r['location'] or '',
            'root_node_id': root_node.pk if root_node else None,
        })

    sub_list = []
    for s in subscribers:
        attachment = attachment_by_subscriber_id.get(s.id)
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
            'id': s.id,
            'username': s.username,
            'name': s.full_name or s.username,
            'status': s.status,
            'mt_status': s.mt_status,
            'network_state': 'online' if s.mt_status == 'online' else 'offline' if s.mt_status == 'offline' else 'unknown',
            'billing_state': get_subscriber_billing_state(s),
            'lat': s.latitude,
            'lng': s.longitude,
            'ip': s.ip_address or '',
            'plan': s.plan.name if s.plan_id else '',
            'topology_status': attachment.status if attachment else 'unassigned',
            'mapped_node_id': mapped_node.pk if mapped_node else None,
            'mapped_node_name': mapped_node.name if mapped_node else '',
            'mapped_endpoint_name': mapped_endpoint_name,
            'workspace_url': reverse('nms-subscriber-workspace', args=[s.id]),
            'detail_url': reverse('subscriber-detail', args=[s.id]),
            'distribution_url': distribution_url,
        })

    node_list = []
    for node in nodes:
        serialized_node = serialize_network_node(node)
        serialized_node['type'] = 'network_node'
        node_list.append(serialized_node)

    attachment_list = []
    for attachment in attachments:
        mapped_node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
        if mapped_node is None:
            continue
        serialized_attachment = serialize_service_attachment(attachment)
        if len(serialized_attachment['points']) < 2:
            continue
        if focus_subscriber_id and str(attachment.subscriber_id) == str(focus_subscriber_id):
            serialized_attachment['points'] = serialized_attachment.get('full_points') or serialized_attachment['points']
        attachment_list.append(serialized_attachment)

    link_list = []
    for topology_link in topology_links:
        serialized_link = serialize_topology_link(
            topology_link,
            highlighted_node_id=focus_node_id,
        )
        if len(serialized_link['points']) < 2:
            continue
        link_list.append(serialized_link)

    gps_trace_list = []
    if gps_trace_ready:
        for trace in GpsTrace.objects.prefetch_related('points')[:25]:
            points = [
                [point.latitude, point.longitude]
                for point in trace.points.all()
            ]
            if len(points) < 2:
                continue
            gps_trace_list.append({
                'id': trace.id,
                'name': trace.name,
                'trace_type': trace.trace_type,
                'trace_type_label': trace.get_trace_type_display(),
                'source_label': trace.source_label or '',
                'point_count': len(points),
                'distance_km': round(get_gps_trace_distance_km(trace), 3),
                'points': points,
                'analytics_url': reverse('nms-analytics'),
            })

    return JsonResponse({
        'routers': router_list,
        'subscribers': sub_list,
        'nodes': node_list,
        'attachments': attachment_list,
        'links': link_list,
        'gps_traces': gps_trace_list,
        'service_attachment_ready': service_attachment_ready,
        'service_attachment_geometry_ready': service_attachment_geometry_ready,
        'topology_links_ready': topology_links_ready,
        'distribution_ready': distribution_ready,
        'cable_ready': cable_ready,
        'gps_trace_ready': gps_trace_ready,
        'focus_node_id': focus_node_id,
        'focus_subscriber_id': int(focus_subscriber_id) if focus_subscriber_id and focus_subscriber_id.isdigit() else None,
    })


@login_required
def nms_operations(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'refresh_review_states':
            result = refresh_all_attachment_review_states()
            AuditLog.log(
                'update',
                'nms',
                f"Premium NMS review states refreshed: {result['updated']} mapping(s) updated",
                user=request.user,
            )
            messages.success(request, f"Review states refreshed. Updated {result['updated']} mapping(s).")
            return redirect('nms-operations')

        if action == 'sync_endpoint_statuses':
            result = sync_all_endpoint_statuses()
            AuditLog.log(
                'update',
                'nms',
                f"Premium NMS endpoint statuses synced: {result['synced']} endpoint(s)",
                user=request.user,
            )
            messages.success(request, f"Endpoint statuses synced for {result['synced']} endpoint(s).")
            return redirect('nms-operations')

        if action == 'sync_router_roots':
            result = sync_router_roots_and_interface_endpoints()
            AuditLog.log(
                'update',
                'nms',
                (
                    f"Premium NMS router roots synced: {result['router_nodes']} root node(s), "
                    f"{result['router_endpoints']} router endpoint(s)"
                ),
                user=request.user,
            )
            messages.success(
                request,
                (
                    f"Router roots synced. Added {result['router_nodes']} root node(s) and "
                    f"{result['router_endpoints']} router ethernet endpoint(s)."
                ),
            )
            return redirect('nms-operations')

        if action == 'sync_core_assignments':
            result = sync_all_core_assignment_statuses()
            AuditLog.log(
                'update',
                'nms',
                f"Premium NMS core assignment statuses synced: {result['synced']} assignment(s)",
                user=request.user,
            )
            messages.success(request, f"Core assignment statuses synced for {result['synced']} assignment(s).")
            return redirect('nms-operations')

        messages.error(request, 'Unknown NMS operations action.')
        return redirect('nms-operations')

    report = build_nms_validation_report()
    return render(request, 'nms/operations.html', {
        'report': report,
        'service_attachment_ready': has_service_attachment_table(),
        'distribution_ready': has_distribution_tables(),
        'cable_ready': has_cable_tables(),
        'core_assignment_ready': has_core_assignment_tables(),
        'topology_links_ready': has_topology_link_tables(),
        'gps_trace_ready': has_gps_trace_tables(),
    })


@login_required
def nms_analytics(request):
    gps_trace_ready = has_gps_trace_tables()
    trace_form = GpsTraceImportForm() if gps_trace_ready else None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'import_trace':
            if not gps_trace_ready:
                messages.error(request, 'GPS trace database migration is not applied yet.')
                return redirect('nms-analytics')

            trace_form = GpsTraceImportForm(request.POST)
            if trace_form.is_valid():
                trace = trace_form.save(created_by=request.user.username)
                AuditLog.log(
                    'create',
                    'nms',
                    f"GPS trace imported: {trace.name}",
                    user=request.user,
                )
                messages.success(request, f"GPS trace imported: {trace.name}.")
                return redirect('nms-analytics')
        elif action == 'delete_trace':
            if not gps_trace_ready:
                messages.error(request, 'GPS trace database migration is not applied yet.')
                return redirect('nms-analytics')

            trace = get_object_or_404(GpsTrace, pk=request.POST.get('trace_pk'))
            trace_name = trace.name
            trace.delete()
            AuditLog.log(
                'delete',
                'nms',
                f"GPS trace deleted: {trace_name}",
                user=request.user,
            )
            messages.success(request, f"GPS trace deleted: {trace_name}.")
            return redirect('nms-analytics')
        else:
            messages.error(request, 'Unknown NMS analytics action.')
            return redirect('nms-analytics')

    selected_outage_type = request.GET.get('outage_type') or ''
    selected_outage_id = request.GET.get('outage_id') or ''
    outage_impact = None
    selected_outage_target = None
    if selected_outage_id.isdigit():
        if selected_outage_type == 'node':
            selected_outage_target = NetworkNode.objects.filter(pk=selected_outage_id).first()
            if selected_outage_target:
                outage_impact = get_outage_impact(node=selected_outage_target)
        elif selected_outage_type == 'link':
            selected_outage_target = TopologyLink.objects.select_related('source_node', 'target_node').filter(pk=selected_outage_id).first()
            if selected_outage_target:
                outage_impact = get_outage_impact(link=selected_outage_target)

    gps_traces = []
    if gps_trace_ready:
        for trace in GpsTrace.objects.prefetch_related('points')[:25]:
            trace.distance_km = round(get_gps_trace_distance_km(trace), 3)
            gps_traces.append(trace)

    return render(request, 'nms/analytics.html', {
        'trace_form': trace_form,
        'gps_trace_ready': gps_trace_ready,
        'gps_traces': gps_traces,
        'route_report': get_topology_route_report(),
        'cable_report': get_cable_utilization_report(),
        'power_budget_report': get_power_budget_report(),
        'node_options': NetworkNode.objects.filter(is_active=True).order_by('name'),
        'link_options': TopologyLink.objects.select_related('source_node', 'target_node').order_by('name', 'id') if has_topology_link_tables() else [],
        'selected_outage_type': selected_outage_type,
        'selected_outage_id': selected_outage_id,
        'selected_outage_target': selected_outage_target,
        'outage_impact': outage_impact,
        'topology_links_ready': has_topology_link_tables(),
        'cable_ready': has_cable_tables(),
        'service_attachment_ready': has_service_attachment_table(),
    })


@login_required
@require_POST
def nms_create_node_api(request):
    form = NetworkNodeForm(request.POST)
    if form.is_valid():
        node = form.save()
        node = NetworkNode.objects.select_related('router').get(pk=node.pk)
        AuditLog.log(
            'create',
            'nms',
            f"Network node created from map: {node.name}",
            user=request.user,
        )
        return JsonResponse({
            'ok': True,
            'message': f"Network node created: {node.name}.",
            'node': serialize_network_node(node),
        })

    return JsonResponse({
        'ok': False,
        'errors': form.errors.get_json_data(),
    }, status=400)


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
        )
        if has_cable_tables():
            topology_link = topology_link.select_related('cable')
        topology_link = topology_link.prefetch_related('vertices').get(pk=topology_link.pk)
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
        )
        if has_cable_tables():
            topology_link = topology_link.select_related('cable')
        topology_link = topology_link.prefetch_related('vertices').get(pk=topology_link.pk)
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
@require_POST
def nms_update_attachment_geometry_api(request, attachment_pk):
    if not has_service_attachment_table() or not has_service_attachment_geometry_tables():
        return JsonResponse({
            'ok': False,
            'message': 'Subscriber mapping geometry database migration is not applied yet.',
        }, status=503)

    attachment = get_object_or_404(
        ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__parent_node',
            'endpoint__internal_device__parent_node',
            'endpoint__router_interface',
        ).prefetch_related('vertices'),
        pk=attachment_pk,
    )
    form = ServiceAttachmentGeometryForm(request.POST, attachment=attachment)
    if form.is_valid():
        form.save()
        attachment.refresh_from_db()
        attachment = ServiceAttachment.objects.select_related(
            'subscriber',
            'node',
            'endpoint',
            'endpoint__parent_node',
            'endpoint__internal_device__parent_node',
            'endpoint__router_interface',
            'endpoint__router_interface__traffic_cache',
        ).prefetch_related('vertices').get(pk=attachment.pk)
        AuditLog.log(
            'update',
            'nms',
            f"Subscriber path geometry updated for {attachment.subscriber.username}",
            user=request.user,
        )
        return JsonResponse({
            'ok': True,
            'message': f"Subscriber path updated for {attachment.subscriber.display_name}.",
            'attachment': serialize_service_attachment(attachment),
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

    cable_ready = has_cable_tables()
    core_assignment_ready = has_core_assignment_tables()
    endpoint_connection_ready = has_endpoint_connection_tables()
    selected_link = None
    selected_link_endpoint_connections = []
    selected_link_id = request.GET.get('link')
    if selected_link_id and selected_link_id.isdigit():
        selected_link_queryset = TopologyLink.objects.select_related('source_node', 'target_node')
        if cable_ready:
            selected_link_queryset = selected_link_queryset.select_related('cable').prefetch_related('cable__cores')
        selected_link = get_object_or_404(
            selected_link_queryset.prefetch_related('vertices'),
            pk=selected_link_id,
        )
        if cable_ready and core_assignment_ready and getattr(selected_link, 'cable', None):
            assignments = CableCoreAssignment.objects.select_related(
                'service_attachment',
                'service_attachment__subscriber',
                'core',
            ).filter(core__cable=selected_link.cable)
            assignment_by_core_id = {
                assignment.core_id: assignment
                for assignment in assignments
            }
            for core in selected_link.cable.cores.all():
                core.structured_core_assignment = assignment_by_core_id.get(core.pk)
        if endpoint_connection_ready:
            selected_link_endpoint_connections = EndpointConnection.objects.select_related(
                'upstream_endpoint',
                'upstream_endpoint__parent_node',
                'upstream_endpoint__internal_device__parent_node',
                'upstream_endpoint__router_interface',
                'downstream_endpoint',
                'downstream_endpoint__parent_node',
                'downstream_endpoint__internal_device__parent_node',
                'downstream_endpoint__router_interface',
                'cable_core',
                'cable_core__cable',
            ).filter(topology_link=selected_link).order_by('upstream_endpoint__label', 'downstream_endpoint__label')

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

    links = TopologyLink.objects.select_related('source_node', 'target_node')
    if cable_ready:
        links = links.select_related('cable').prefetch_related('cable__cores')
    links = links.prefetch_related('vertices')
    return render(request, 'nms/links.html', {
        'form': form,
        'selected_link': selected_link,
        'links': links,
        'cable_ready': cable_ready,
        'core_assignment_ready': core_assignment_ready,
        'endpoint_connection_ready': endpoint_connection_ready,
        'selected_link_endpoint_connections': selected_link_endpoint_connections,
    })


@login_required
def nms_nodes(request):
    selected_node = None
    selected_node_id = request.GET.get('node')
    if selected_node_id and selected_node_id.isdigit():
        selected_node = get_object_or_404(
            NetworkNode.objects.select_related('router'),
            pk=selected_node_id,
        )

    if request.method == 'POST':
        is_create = selected_node is None
        form = NetworkNodeForm(request.POST, instance=selected_node)
        if form.is_valid():
            node = form.save()
            AuditLog.log(
                'create' if is_create else 'update',
                'nms',
                f"Network node saved: {node.name}",
                user=request.user,
            )
            messages.success(request, f"Network node saved: {node.name}.")
            return redirect(f"{reverse('nms-nodes')}?node={node.pk}")
    else:
        form = NetworkNodeForm(instance=selected_node)

    nodes = NetworkNode.objects.select_related('router').order_by('name')
    delete_impact = get_node_delete_impact(selected_node) if selected_node else None
    return render(request, 'nms/nodes.html', {
        'form': form,
        'selected_node': selected_node,
        'nodes': nodes,
        'delete_impact': delete_impact,
    })


@login_required
@require_POST
def nms_delete_node(request, node_pk):
    node = get_object_or_404(NetworkNode, pk=node_pk)
    node_name = node.name
    with transaction.atomic():
        impact = delete_node_with_descendants(node)
        AuditLog.log(
            'delete',
            'nms',
            (
                f"Network node deleted: {node_name}. "
                f"Removed {impact['service_attachment_count']} mapping(s), "
                f"{impact['subscriber_node_count']} subscriber node reference(s), "
                f"{impact['topology_link_count']} topology link(s), "
                f"{impact['internal_device_count']} internal device(s), "
                f"{impact['endpoint_count']} endpoint(s), "
                f"{impact['cable_count']} cable(s), and "
                f"{impact['cable_core_count']} cable core(s)."
            ),
            user=request.user,
        )
    messages.success(
        request,
        (
            f"Deleted node {node_name}. Removed related NMS data under this node; "
            "routers, subscribers, billing, and account records were kept."
        ),
    )
    return redirect('nms-nodes')


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
    core_assignment_ready = has_core_assignment_tables()
    selected_node = None
    review_flags = get_attachment_review_flags(attachment) if attachment else []
    form = None
    core_assignment_form = None

    if request.method == 'POST':
        action = request.POST.get('action') or 'save_mapping'

        if action == 'assign_core':
            if not attachment:
                messages.error(request, 'Save the Premium NMS mapping before assigning cable cores.')
                return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)
            if not core_assignment_ready:
                messages.error(request, 'Cable core assignment database migration is not applied yet.')
                return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)

            core_assignment_form = CableCoreAssignmentForm(
                request.POST,
                attachment=attachment,
                prefix='core',
            )
            if core_assignment_form.is_valid():
                core_assignment = core_assignment_form.save(commit=False)
                core_assignment.assigned_by = request.user.username
                core_assignment.save()
                apply_core_assignment(core_assignment)
                AuditLog.log(
                    'create',
                    'nms',
                    f"Cable core assigned for {subscriber.username}: {core_assignment.core}",
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Cable core assigned: {core_assignment.core.cable.display_name} core {core_assignment.core.sequence}.",
                )
                return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)

            selected_node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
            form = ServiceAttachmentForm(instance=attachment, selected_node=selected_node)
        elif action == 'release_core':
            if not attachment or not core_assignment_ready:
                messages.error(request, 'No cable core assignment is available to release.')
                return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)

            core_assignment = get_object_or_404(
                CableCoreAssignment.objects.select_related(
                    'core',
                    'core__cable',
                    'service_attachment',
                ),
                pk=request.POST.get('assignment_pk'),
                service_attachment=attachment,
            )
            core_label = f"{core_assignment.core.cable.display_name} core {core_assignment.core.sequence}"
            release_core_assignment(core_assignment)
            AuditLog.log(
                'delete',
                'nms',
                f"Cable core released for {subscriber.username}: {core_label}",
                user=request.user,
            )
            messages.success(request, f"Cable core released: {core_label}.")
            return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)
        else:
            is_create = attachment is None
            previous_endpoint = attachment.endpoint if attachment else None
            selected_node_id = request.POST.get('node')
            if selected_node_id and selected_node_id.isdigit():
                selected_node = NetworkNode.objects.filter(pk=selected_node_id, is_active=True).first()
            form = ServiceAttachmentForm(request.POST, instance=attachment, selected_node=selected_node)
            if form.is_valid():
                attachment = form.save(commit=False)
                attachment.subscriber = subscriber
                if attachment.endpoint_id:
                    attachment.node = attachment.endpoint.root_node
                review_flags = refresh_attachment_review_state(attachment)
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
                if review_flags:
                    messages.warning(
                        request,
                        f"Premium NMS mapping saved for {subscriber.display_name}, but it still needs review.",
                    )
                else:
                    messages.success(request, f"Premium NMS mapping saved for {subscriber.display_name}.")
                return redirect('nms-subscriber-workspace', subscriber_pk=subscriber.pk)
    if form is None:
        initial = {}
        if not attachment and basic_assignment:
            initial = {
                'node': basic_assignment.node,
                'endpoint_label': basic_assignment.port_label,
            }
            selected_node = basic_assignment.node
        elif attachment:
            selected_node = attachment.node or (attachment.endpoint.root_node if attachment.endpoint_id else None)
        form = ServiceAttachmentForm(instance=attachment, initial=initial, selected_node=selected_node)

    if core_assignment_ready and attachment:
        core_assignments = get_attachment_core_assignments(attachment)
        if core_assignment_form is None:
            core_assignment_form = CableCoreAssignmentForm(
                attachment=attachment,
                prefix='core',
            )
    else:
        core_assignments = []
    topology_summary = get_subscriber_topology_summary(subscriber, table_ready=True)
    return render(request, 'nms/subscriber_workspace.html', {
        'subscriber': subscriber,
        'attachment': attachment,
        'basic_assignment': basic_assignment,
        'form': form,
        'core_assignment_form': core_assignment_form,
        'core_assignments': core_assignments,
        'core_assignment_ready': core_assignment_ready,
        'topology_summary': topology_summary,
        'distribution_ready': distribution_ready,
        'review_flags': review_flags,
        'selected_node': selected_node,
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
        core_assignments = get_attachment_core_assignments(attachment)
        for core_assignment in core_assignments:
            release_core_assignment(core_assignment)
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
    endpoint_connection_form = EndpointConnectionForm(parent_node=node, prefix='connection')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_device':
            device_form = InternalDeviceForm(request.POST, prefix='device')
            if device_form.is_valid():
                internal_device = device_form.save(commit=False)
                internal_device.parent_node = node
                internal_device.save()
                generated_ports = _merge_generated_port_counts(
                    ensure_plc_endpoints(internal_device),
                    ensure_fbt_endpoints(internal_device),
                )
                AuditLog.log(
                    'create',
                    'nms',
                    f"Internal device added to {node.name}: {internal_device.display_name}",
                    user=request.user,
                )
                if generated_ports['created_inputs'] or generated_ports['created_outputs']:
                    messages.success(
                        request,
                        (
                            f"Internal device added: {internal_device.display_name}. "
                            f"Generated {generated_ports['created_inputs']} input port(s) and "
                            f"{generated_ports['created_outputs']} output port(s)."
                        ),
                    )
                else:
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
        elif action == 'create_endpoint_connection':
            endpoint_connection_form = EndpointConnectionForm(request.POST, parent_node=node, prefix='connection')
            if endpoint_connection_form.is_valid():
                endpoint_connection = endpoint_connection_form.save()
                AuditLog.log(
                    'create',
                    'nms',
                    f"Endpoint wiring added for {node.name}: {endpoint_connection.display_name}",
                    user=request.user,
                )
                messages.success(request, f"Endpoint wiring added: {endpoint_connection.display_name}.")
                return redirect('nms-distribution-detail', node_pk=node.pk)
        elif action == 'delete_endpoint_connection':
            if not has_endpoint_connection_tables():
                messages.error(request, 'Endpoint connection database migration is not applied yet.')
                return redirect('nms-distribution-detail', node_pk=node.pk)
            endpoint_connection = get_object_or_404(
                EndpointConnection,
                pk=request.POST.get('connection_pk'),
            )
            connection_name = endpoint_connection.display_name
            endpoint_connection.delete()
            AuditLog.log(
                'delete',
                'nms',
                f"Endpoint wiring removed for {node.name}: {connection_name}",
                user=request.user,
            )
            messages.success(request, f"Endpoint wiring removed: {connection_name}.")
            return redirect('nms-distribution-detail', node_pk=node.pk)
        elif action == 'sync_plc_outputs':
            internal_device = get_object_or_404(
                InternalDevice.objects.filter(parent_node=node),
                pk=request.POST.get('device_pk'),
            )
            generated_ports = ensure_plc_endpoints(internal_device)
            AuditLog.log(
                'update',
                'nms',
                f"PLC ports synced for {node.name}: {internal_device.display_name}",
                user=request.user,
            )
            messages.success(
                request,
                (
                    f"PLC ports synced for {internal_device.display_name}. "
                    f"Added {generated_ports['created_inputs']} input port(s) and "
                    f"{generated_ports['created_outputs']} output port(s)."
                ),
            )
            return redirect('nms-distribution-detail', node_pk=node.pk)
        elif action == 'sync_fbt_outputs':
            internal_device = get_object_or_404(
                InternalDevice.objects.filter(parent_node=node),
                pk=request.POST.get('device_pk'),
            )
            generated_ports = ensure_fbt_endpoints(internal_device)
            AuditLog.log(
                'update',
                'nms',
                f"FBT ports synced for {node.name}: {internal_device.display_name}",
                user=request.user,
            )
            messages.success(
                request,
                (
                    f"FBT ports synced for {internal_device.display_name}. "
                    f"Added {generated_ports['created_inputs']} input port(s) and "
                    f"{generated_ports['created_outputs']} output port(s)."
                ),
            )
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
    review_attachments = []
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
        for attachment in active_attachments:
            attachment.review_flags = get_attachment_review_flags(attachment)
            if attachment.review_flags:
                review_attachments.append(attachment)
    for endpoint in all_endpoints:
        endpoint.active_attachment = attachment_by_endpoint_id.get(endpoint.id)

    endpoint_connections = []
    if has_endpoint_connection_tables():
        endpoint_ids = [endpoint.pk for endpoint in all_endpoints]
        endpoint_connections = EndpointConnection.objects.select_related(
            'upstream_endpoint',
            'upstream_endpoint__parent_node',
            'upstream_endpoint__internal_device',
            'upstream_endpoint__internal_device__parent_node',
            'upstream_endpoint__router_interface',
            'downstream_endpoint',
            'downstream_endpoint__parent_node',
            'downstream_endpoint__internal_device',
            'downstream_endpoint__internal_device__parent_node',
            'downstream_endpoint__router_interface',
            'topology_link',
            'topology_link__source_node',
            'topology_link__target_node',
            'cable_core',
            'cable_core__cable',
        ).filter(
            Q(upstream_endpoint_id__in=endpoint_ids)
            | Q(downstream_endpoint_id__in=endpoint_ids)
        ).order_by('upstream_endpoint__label', 'downstream_endpoint__label', 'id')

    return render(request, 'nms/distribution_detail.html', {
        'node': node,
        'device_form': device_form,
        'endpoint_form': endpoint_form,
        'endpoint_connection_form': endpoint_connection_form,
        'endpoint_connections': endpoint_connections,
        'internal_devices': internal_devices,
        'direct_endpoints': direct_endpoints,
        'all_endpoints': all_endpoints,
        'active_attachments': active_attachments,
        'review_attachments': review_attachments,
        'service_attachment_ready': has_service_attachment_table(),
        'endpoint_connection_ready': has_endpoint_connection_tables(),
    })
