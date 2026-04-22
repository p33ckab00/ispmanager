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
