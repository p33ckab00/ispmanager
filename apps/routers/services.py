import math
from django.utils import timezone
from apps.routers.models import Router, RouterInterface, InterfaceTrafficCache, InterfaceTrafficSnapshot
from apps.routers import mikrotik


IFACE_TYPE_MAP = {
    'ether': 'ether',
    'vlan': 'vlan',
    'bridge': 'bridge',
    'pppoe-in': 'pppoe-in',
    'wg': 'wg',
    'zerotier': 'zerotier',
    'loopback': 'loopback',
}

LOW_ACTIVITY_THRESHOLD_BPS = 1_000_000
MEDIUM_ACTIVITY_THRESHOLD_BPS = 25_000_000
HIGH_ACTIVITY_THRESHOLD_BPS = 100_000_000


def detect_iface_type(iface):
    raw_type = iface.get('type', 'other').lower()
    for key in IFACE_TYPE_MAP:
        if key in raw_type:
            return IFACE_TYPE_MAP[key]
    return 'other'


def sync_interfaces(router):
    try:
        ifaces = mikrotik.get_interfaces(router)
    except Exception as e:
        router.status = 'offline'
        router.save(update_fields=['status'])
        return False, str(e)

    synced_names = []

    for iface in ifaces:
        name = iface.get('name', '')
        if not name:
            continue

        flags = iface.get('flags', '')
        iface_type = detect_iface_type(iface)

        existing = RouterInterface.objects.filter(router=router, name=name).first()

        if existing:
            existing.iface_type = iface_type
            existing.mac_address = iface.get('mac-address', '')
            existing.actual_mtu = int(iface.get('actual-mtu', 0)) or None
            existing.is_running = 'R' in flags
            existing.is_slave = 'S' in flags
            existing.is_dynamic = 'D' in flags
            existing.last_synced = timezone.now()
            existing.save()
        else:
            RouterInterface.objects.create(
                router=router,
                name=name,
                iface_type=iface_type,
                mac_address=iface.get('mac-address', ''),
                actual_mtu=int(iface.get('actual-mtu', 0)) or None,
                is_running='R' in flags,
                is_slave='S' in flags,
                is_dynamic='D' in flags,
            )

        synced_names.append(name)

    router.status = 'online'
    router.last_seen = timezone.now()
    router.save(update_fields=['status', 'last_seen'])

    try:
        from apps.nms.services import sync_router_roots_and_interface_endpoints
        sync_router_roots_and_interface_endpoints()
    except Exception:
        pass

    return True, f"Synced {len(synced_names)} interfaces."


def get_live_traffic(router, interface_name):
    try:
        data = mikrotik.get_interface_traffic(router, interface_name)
        return {
            'rx_bps': int(data.get('rx-bits-per-second', 0)),
            'tx_bps': int(data.get('tx-bits-per-second', 0)),
            'rx_pps': int(data.get('rx-packets-per-second', 0)),
            'tx_pps': int(data.get('tx-packets-per-second', 0)),
            'rx_mbps': round(int(data.get('rx-bits-per-second', 0)) / 1_000_000, 2),
            'tx_mbps': round(int(data.get('tx-bits-per-second', 0)) / 1_000_000, 2),
        }
    except Exception as e:
        return {'error': str(e)}


def get_telemetry_stale_after_seconds(polling_interval_seconds):
    interval = max(1, int(polling_interval_seconds or 1))
    return max(5, interval * 3)


def get_traffic_direction(rx_bps, tx_bps):
    rx_bps = max(0, int(rx_bps or 0))
    tx_bps = max(0, int(tx_bps or 0))
    if rx_bps == 0 and tx_bps == 0:
        return 'quiet'
    if rx_bps > tx_bps * 1.3:
        return 'rx-heavy'
    if tx_bps > rx_bps * 1.3:
        return 'tx-heavy'
    return 'balanced'


def get_activity_level(rx_bps, tx_bps):
    total_bps = max(0, int(rx_bps or 0)) + max(0, int(tx_bps or 0))
    if total_bps <= 0:
        return 'linked-idle'
    if total_bps < LOW_ACTIVITY_THRESHOLD_BPS:
        return 'low'
    if total_bps < MEDIUM_ACTIVITY_THRESHOLD_BPS:
        return 'medium'
    if total_bps < HIGH_ACTIVITY_THRESHOLD_BPS:
        return 'high'
    return 'burst'


def get_signal_percent(bits_per_second):
    bits_per_second = max(0, int(bits_per_second or 0))
    if bits_per_second <= 0:
        return 0
    mbps = bits_per_second / 1_000_000
    scaled = 8 + (28 * math.log10(mbps + 1))
    return min(100, max(6, int(round(scaled))))


def serialize_telemetry_cache(interface, cache, stale_after_seconds):
    sample_age_seconds = None
    if cache and cache.sampled_at:
        sample_age_seconds = max(
            0.0,
            round((timezone.now() - cache.sampled_at).total_seconds(), 1),
        )

    rx_bps = int(getattr(cache, 'rx_bits_per_second', 0) or 0)
    tx_bps = int(getattr(cache, 'tx_bits_per_second', 0) or 0)
    rx_pps = int(getattr(cache, 'rx_packets_per_second', 0) or 0)
    tx_pps = int(getattr(cache, 'tx_packets_per_second', 0) or 0)
    error = getattr(cache, 'error', '') or ''

    link_state = 'up' if interface.is_running else 'down'
    activity_level = 'unknown'
    display_state = 'unknown'

    if error:
        display_state = 'error'
    elif link_state == 'down':
        activity_level = 'down'
        display_state = 'down'
    elif cache:
        activity_level = get_activity_level(rx_bps, tx_bps)
        if sample_age_seconds is not None and sample_age_seconds > stale_after_seconds:
            display_state = 'stale'
        else:
            display_state = activity_level

    return {
        'interface_id': interface.pk,
        'name': interface.name,
        'display_name': interface.display_name,
        'rx_bps': rx_bps,
        'tx_bps': tx_bps,
        'rx_pps': rx_pps,
        'tx_pps': tx_pps,
        'rx_mbps': round(rx_bps / 1_000_000, 2),
        'tx_mbps': round(tx_bps / 1_000_000, 2),
        'activity_state': getattr(cache, 'activity_state', 'unknown'),
        'activity_level': activity_level,
        'display_state': display_state,
        'link_state': link_state,
        'traffic_direction': get_traffic_direction(rx_bps, tx_bps),
        'rx_signal_percent': get_signal_percent(rx_bps),
        'tx_signal_percent': get_signal_percent(tx_bps),
        'total_signal_percent': get_signal_percent(rx_bps + tx_bps),
        'sampled_at': cache.sampled_at.isoformat() if cache and cache.sampled_at else None,
        'sample_age_seconds': sample_age_seconds,
        'stale_after_seconds': stale_after_seconds,
        'error': error,
    }


def sample_router_traffic(router):
    """
    Polls live traffic for non-session interfaces and stores a latest-state cache row.
    The UI can then refresh quickly against cached values instead of calling MikroTik directly.
    """
    interfaces = router.interfaces.exclude(iface_type='pppoe-in').order_by('name')
    sampled = 0

    for iface in interfaces:
        try:
            data = get_live_traffic(router, iface.name)
            if data.get('error'):
                InterfaceTrafficCache.objects.update_or_create(
                    interface=iface,
                    defaults={
                        'rx_bits_per_second': 0,
                        'tx_bits_per_second': 0,
                        'rx_packets_per_second': 0,
                        'tx_packets_per_second': 0,
                        'activity_state': 'error',
                        'error': data['error'][:255],
                    },
                )
                continue

            rx_bps = data['rx_bps']
            tx_bps = data['tx_bps']
            rx_pps = data['rx_pps']
            tx_pps = data['tx_pps']

            if not iface.is_running:
                activity_state = 'down'
            elif rx_bps > 0 or tx_bps > 0:
                activity_state = 'active'
            else:
                activity_state = 'idle'

            InterfaceTrafficCache.objects.update_or_create(
                interface=iface,
                defaults={
                    'rx_bits_per_second': rx_bps,
                    'tx_bits_per_second': tx_bps,
                    'rx_packets_per_second': rx_pps,
                    'tx_packets_per_second': tx_pps,
                    'activity_state': activity_state,
                    'error': '',
                },
            )
            InterfaceTrafficSnapshot.objects.create(
                interface=iface,
                rx_bits_per_second=rx_bps,
                tx_bits_per_second=tx_bps,
                rx_packets_per_second=rx_pps,
                tx_packets_per_second=tx_pps,
            )
            sampled += 1
        except Exception as e:
            InterfaceTrafficCache.objects.update_or_create(
                interface=iface,
                defaults={
                    'rx_bits_per_second': 0,
                    'tx_bits_per_second': 0,
                    'rx_packets_per_second': 0,
                    'tx_packets_per_second': 0,
                    'activity_state': 'error',
                    'error': str(e)[:255],
                },
            )

    return sampled
