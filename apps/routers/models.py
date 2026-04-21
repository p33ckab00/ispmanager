from django.db import models


class Router(models.Model):
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('unknown', 'Unknown'),
    ]

    name = models.CharField(max_length=100)
    host = models.CharField(max_length=255, help_text='IP address or hostname')
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=255)
    api_port = models.IntegerField(default=8728)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unknown')
    last_seen = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.host})"


class RouterInterface(models.Model):
    TYPE_CHOICES = [
        ('ether', 'Ethernet'),
        ('vlan', 'VLAN'),
        ('bridge', 'Bridge'),
        ('pppoe-in', 'PPPoE Session'),
        ('wg', 'WireGuard'),
        ('zerotier', 'ZeroTier'),
        ('loopback', 'Loopback'),
        ('other', 'Other'),
    ]

    ROLE_CHOICES = [
        ('uplink', 'Uplink'),
        ('olt', 'OLT'),
        ('libreqos', 'LibreQoS'),
        ('libreqos_mgmt', 'LibreQoS Management'),
        ('wifi', 'WiFi / Access Points'),
        ('pppoe', 'PPPoE'),
        ('dhcp', 'DHCP / IPoE'),
        ('management', 'Management'),
        ('client', 'Client'),
        ('pisowifi', 'PisoWifi'),
        ('other', 'Other'),
    ]

    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='interfaces')
    name = models.CharField(max_length=100)
    iface_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='other')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='other')
    label = models.CharField(max_length=100, blank=True, help_text='Custom admin label')
    mac_address = models.CharField(max_length=20, blank=True)
    actual_mtu = models.IntegerField(null=True, blank=True)
    is_running = models.BooleanField(default=False)
    is_slave = models.BooleanField(default=False)
    is_dynamic = models.BooleanField(default=False)
    comment = models.CharField(max_length=255, blank=True)
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('router', 'name')
        ordering = ['name']

    def __str__(self):
        return f"{self.router.name} - {self.name}"

    @property
    def display_name(self):
        return self.label if self.label else self.name

    @property
    def is_physical(self):
        return self.iface_type == 'ether'

    @property
    def is_session(self):
        return self.iface_type == 'pppoe-in'


class InterfaceTrafficSnapshot(models.Model):
    interface = models.ForeignKey(RouterInterface, on_delete=models.CASCADE, related_name='snapshots')
    rx_bits_per_second = models.BigIntegerField(default=0)
    tx_bits_per_second = models.BigIntegerField(default=0)
    rx_packets_per_second = models.IntegerField(default=0)
    tx_packets_per_second = models.IntegerField(default=0)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']
        get_latest_by = 'recorded_at'

    def __str__(self):
        return f"{self.interface.name} @ {self.recorded_at}"

    @property
    def rx_mbps(self):
        return round(self.rx_bits_per_second / 1_000_000, 2)

    @property
    def tx_mbps(self):
        return round(self.tx_bits_per_second / 1_000_000, 2)


class InterfaceTrafficCache(models.Model):
    ACTIVITY_CHOICES = [
        ('active', 'Active'),
        ('idle', 'Idle'),
        ('down', 'Down'),
        ('error', 'Error'),
        ('unknown', 'Unknown'),
    ]

    interface = models.OneToOneField(RouterInterface, on_delete=models.CASCADE, related_name='traffic_cache')
    rx_bits_per_second = models.BigIntegerField(default=0)
    tx_bits_per_second = models.BigIntegerField(default=0)
    rx_packets_per_second = models.IntegerField(default=0)
    tx_packets_per_second = models.IntegerField(default=0)
    activity_state = models.CharField(max_length=20, choices=ACTIVITY_CHOICES, default='unknown')
    error = models.CharField(max_length=255, blank=True)
    sampled_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sampled_at']

    def __str__(self):
        return f"{self.interface.name} live cache"

    @property
    def rx_mbps(self):
        return round(self.rx_bits_per_second / 1_000_000, 2)

    @property
    def tx_mbps(self):
        return round(self.tx_bits_per_second / 1_000_000, 2)
