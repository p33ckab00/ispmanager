from rest_framework import serializers
from apps.routers.models import Router, RouterInterface, InterfaceTrafficSnapshot, InterfaceTrafficCache


class RouterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Router
        fields = ['id', 'name', 'host', 'api_port', 'description', 'location',
                  'latitude', 'longitude', 'status', 'last_seen', 'is_active', 'created_at']
        read_only_fields = ['status', 'last_seen']


class RouterInterfaceSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    is_physical = serializers.ReadOnlyField()
    is_session = serializers.ReadOnlyField()

    class Meta:
        model = RouterInterface
        fields = ['id', 'router', 'name', 'iface_type', 'role', 'label',
                  'mac_address', 'actual_mtu', 'is_running', 'is_slave',
                  'is_dynamic', 'comment', 'display_name', 'is_physical',
                  'is_session', 'last_synced']


class TrafficSnapshotSerializer(serializers.ModelSerializer):
    rx_mbps = serializers.ReadOnlyField()
    tx_mbps = serializers.ReadOnlyField()

    class Meta:
        model = InterfaceTrafficSnapshot
        fields = ['id', 'interface', 'rx_bits_per_second', 'tx_bits_per_second',
                  'rx_packets_per_second', 'tx_packets_per_second',
                  'rx_mbps', 'tx_mbps', 'recorded_at']


class TrafficCacheSerializer(serializers.ModelSerializer):
    rx_mbps = serializers.ReadOnlyField()
    tx_mbps = serializers.ReadOnlyField()
    interface_name = serializers.CharField(source='interface.name', read_only=True)
    interface_display_name = serializers.CharField(source='interface.display_name', read_only=True)

    class Meta:
        model = InterfaceTrafficCache
        fields = [
            'interface', 'interface_name', 'interface_display_name',
            'rx_bits_per_second', 'tx_bits_per_second',
            'rx_packets_per_second', 'tx_packets_per_second',
            'rx_mbps', 'tx_mbps', 'activity_state', 'error', 'sampled_at',
        ]
