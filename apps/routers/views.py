import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.routers.models import Router, RouterInterface, InterfaceTrafficCache
from apps.routers.forms import RouterForm, RouterCoordinatesForm, InterfaceLabelForm
from apps.routers.services import (
    sync_interfaces,
    get_live_traffic,
    get_telemetry_stale_after_seconds,
    serialize_telemetry_cache,
)
from apps.routers import mikrotik
from apps.core.models import AuditLog
from apps.settings_app.models import RouterSettings


@login_required
def router_list(request):
    routers = Router.objects.filter(is_active=True)
    return render(request, 'routers/list.html', {'routers': routers})


@login_required
def router_add(request):
    if request.method == 'POST':
        form = RouterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            ok, result = mikrotik.test_connection(
                host=data['host'],
                username=data['username'],
                password=data['password'],
                port=data['api_port'],
            )
            if not ok:
                messages.error(request, f"Connection failed: {result}")
                return render(request, 'routers/add.html', {'form': form})

            router = form.save(commit=False)
            router.status = 'online'
            router.save()
            AuditLog.log('create', 'routers', f"Router added: {router.name}", user=request.user)
            messages.success(request, f"Router '{router.name}' added. Identity: {result}")
            return redirect('router-detail', pk=router.pk)
    else:
        from apps.settings_app.models import RouterSettings
        rs = RouterSettings.get_settings()
        form = RouterForm(initial={'api_port': rs.default_api_port})
    return render(request, 'routers/add.html', {'form': form})


@login_required
def router_detail(request, pk):
    router = get_object_or_404(Router, pk=pk)
    router_settings = RouterSettings.get_settings()
    physical = router.interfaces.filter(iface_type='ether').order_by('name')
    sessions = router.interfaces.filter(iface_type='pppoe-in').order_by('name')
    vlans = router.interfaces.filter(iface_type='vlan').order_by('name')
    bridges = router.interfaces.filter(iface_type='bridge').order_by('name')
    tunnels = router.interfaces.filter(iface_type__in=['wg', 'zerotier']).order_by('name')
    return render(request, 'routers/detail.html', {
        'router': router,
        'physical': physical,
        'sessions': sessions,
        'vlans': vlans,
        'bridges': bridges,
        'tunnels': tunnels,
        'telemetry_poll_ms': 1000,
        'telemetry_stale_after_seconds': get_telemetry_stale_after_seconds(router_settings.polling_interval_seconds),
    })


@login_required
def router_edit(request, pk):
    router = get_object_or_404(Router, pk=pk)
    if request.method == 'POST':
        form = RouterForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'routers', f"Router updated: {router.name}", user=request.user)
            messages.success(request, 'Router updated.')
            return redirect('router-detail', pk=router.pk)
    else:
        form = RouterForm(instance=router)
    return render(request, 'routers/edit.html', {'form': form, 'router': router})


@login_required
def router_delete(request, pk):
    router = get_object_or_404(Router, pk=pk)
    if request.method == 'POST':
        name = router.name
        router.is_active = False
        router.save()
        AuditLog.log('delete', 'routers', f"Router deactivated: {name}", user=request.user)
        messages.success(request, f"Router '{name}' removed.")
        return redirect('router-list')
    return render(request, 'routers/confirm_delete.html', {'router': router})


@login_required
def router_sync(request, pk):
    router = get_object_or_404(Router, pk=pk)
    ok, msg = sync_interfaces(router)
    if ok:
        AuditLog.log('sync', 'routers', f"Interfaces synced: {router.name}", user=request.user)
        messages.success(request, msg)
    else:
        messages.error(request, f"Sync failed: {msg}")
    return redirect('router-detail', pk=router.pk)


@login_required
def interface_detail(request, router_pk, iface_pk):
    router = get_object_or_404(Router, pk=router_pk)
    iface = get_object_or_404(RouterInterface, pk=iface_pk, router=router)
    router_settings = RouterSettings.get_settings()
    form = InterfaceLabelForm(instance=iface)
    if request.method == 'POST':
        form = InterfaceLabelForm(request.POST, instance=iface)
        if form.is_valid():
            form.save()
            messages.success(request, 'Interface updated.')
            return redirect('interface-detail', router_pk=router_pk, iface_pk=iface_pk)
    return render(request, 'routers/interface_detail.html', {
        'router': router,
        'iface': iface,
        'form': form,
        'telemetry_poll_ms': 1000,
        'telemetry_stale_after_seconds': get_telemetry_stale_after_seconds(router_settings.polling_interval_seconds),
    })


@login_required
def interface_traffic_poll(request, router_pk, iface_pk):
    router = get_object_or_404(Router, pk=router_pk)
    iface = get_object_or_404(RouterInterface, pk=iface_pk, router=router)
    data = get_live_traffic(router, iface.name)
    return render(request, 'routers/partials/traffic_widget.html', {
        'iface': iface,
        'traffic': data,
    })


@login_required
def router_live_traffic_cache(request, pk):
    router = get_object_or_404(Router, pk=pk)
    router_settings = RouterSettings.get_settings()
    stale_after_seconds = get_telemetry_stale_after_seconds(router_settings.polling_interval_seconds)
    interfaces = router.interfaces.exclude(iface_type='pppoe-in').select_related('traffic_cache').order_by('name')
    payload = {
        'router_id': router.pk,
        'router_status': router.status,
        'stale_after_seconds': stale_after_seconds,
        'interfaces': [
            serialize_telemetry_cache(
                iface,
                iface.traffic_cache if hasattr(iface, 'traffic_cache') else None,
                stale_after_seconds,
            )
            for iface in interfaces
        ],
    }
    return JsonResponse(payload)


@login_required
def interface_live_traffic_cache(request, router_pk, iface_pk):
    router = get_object_or_404(Router, pk=router_pk)
    iface = get_object_or_404(RouterInterface, pk=iface_pk, router=router)
    router_settings = RouterSettings.get_settings()
    stale_after_seconds = get_telemetry_stale_after_seconds(router_settings.polling_interval_seconds)
    cache = InterfaceTrafficCache.objects.filter(interface=iface).first()
    return JsonResponse(serialize_telemetry_cache(iface, cache, stale_after_seconds))


def test_connection_view(request):
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except Exception:
            return JsonResponse({'ok': False, 'message': 'Invalid JSON'})

        host = body.get('host', '')
        username = body.get('username', '')
        password = body.get('password', '')
        port = body.get('port', 8728)

        if not all([host, username, password]):
            return JsonResponse({'ok': False, 'message': 'Host, username and password are required.'})

        ok, result = mikrotik.test_connection(host, username, password, port)
        return JsonResponse({'ok': ok, 'message': result})

    return JsonResponse({'ok': False, 'message': 'POST required'})


@login_required
def router_coordinates(request, pk):
    router = get_object_or_404(Router, pk=pk)
    if request.method == 'POST':
        form = RouterCoordinatesForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coordinates updated.')
            return redirect('router-detail', pk=router.pk)
    else:
        form = RouterCoordinatesForm(instance=router)
    return render(request, 'routers/coordinates.html', {'router': router, 'form': form})
