from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from apps.routers.models import Router
from apps.subscribers.models import Subscriber


@login_required
def nms_map(request):
    return render(request, 'nms/map.html')


@login_required
def nms_map_data(request):
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
        })

    return JsonResponse({
        'routers': router_list,
        'subscribers': sub_list,
    })
