from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.subscribers.models import Subscriber, NetworkNode


class ServiceAttachment(models.Model):
    STATUS_CHOICES = [
        ('active', 'Mapped'),
        ('needs_review', 'Needs Review'),
    ]

    subscriber = models.OneToOneField(
        Subscriber,
        on_delete=models.CASCADE,
        related_name='service_attachment',
    )
    node = models.ForeignKey(
        NetworkNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_attachments',
    )
    endpoint = models.ForeignKey(
        'Endpoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_attachments',
    )
    endpoint_label = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    assigned_by = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['subscriber__username']
        constraints = [
            models.UniqueConstraint(
                fields=['endpoint'],
                condition=Q(status='active') & Q(endpoint__isnull=False),
                name='nms_unique_active_attachment_per_endpoint',
            ),
        ]

    def clean(self):
        if self.status == 'active' and self.node_id is None:
            raise ValidationError('Active mappings must have a serving node.')

        if self.endpoint_id:
            endpoint_node_id = self.endpoint.root_node_id
            if self.node_id and endpoint_node_id != self.node_id:
                raise ValidationError('Selected endpoint does not belong to the chosen serving node.')
            if self.status == 'active' and self.endpoint.status in ('inactive', 'damaged'):
                raise ValidationError('Inactive or damaged endpoints cannot be assigned to active mappings.')

    def __str__(self):
        node_name = self.node.name if self.node else 'Missing node'
        return f"{self.subscriber.username} -> {node_name}"

    @property
    def is_mapped(self):
        return self.status == 'active' and self.node_id is not None

    @property
    def resolved_endpoint_label(self):
        if self.endpoint_id:
            return self.endpoint.display_name
        return self.endpoint_label or ''


class ServiceAttachmentVertex(models.Model):
    service_attachment = models.ForeignKey(
        ServiceAttachment,
        on_delete=models.CASCADE,
        related_name='vertices',
    )
    sequence = models.PositiveIntegerField()
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ['sequence']
        unique_together = [('service_attachment', 'sequence')]

    def __str__(self):
        return f"{self.service_attachment_id} #{self.sequence}"


class InternalDevice(models.Model):
    DEVICE_TYPE_CHOICES = [
        ('plc', 'PLC Splitter'),
        ('fbt', 'FBT Splitter'),
        ('patch_panel', 'Patch Panel'),
        ('splice_tray', 'Splice Tray'),
        ('other', 'Other'),
    ]

    PLC_MODEL_CHOICES = [
        ('', 'Not a PLC'),
        ('1x4', '1x4'),
        ('1x8', '1x8'),
        ('1x16', '1x16'),
        ('1x32', '1x32'),
    ]

    FBT_RATIO_CHOICES = [
        ('', 'Not an FBT'),
        ('95/5', '95/5'),
        ('90/10', '90/10'),
        ('85/15', '85/15'),
        ('80/20', '80/20'),
        ('75/25', '75/25'),
        ('70/30', '70/30'),
        ('65/35', '65/35'),
        ('60/40', '60/40'),
        ('55/45', '55/45'),
        ('50/50', '50/50'),
    ]

    parent_node = models.ForeignKey(
        NetworkNode,
        on_delete=models.CASCADE,
        related_name='internal_devices',
    )
    name = models.CharField(max_length=100)
    device_type = models.CharField(max_length=30, choices=DEVICE_TYPE_CHOICES, default='other')
    slot_label = models.CharField(max_length=50, blank=True)
    plc_model = models.CharField(max_length=10, choices=PLC_MODEL_CHOICES, blank=True)
    plc_input_count = models.PositiveIntegerField(default=0)
    plc_output_count = models.PositiveIntegerField(default=0)
    auto_generate_plc_outputs = models.BooleanField(default=False)
    fbt_ratio = models.CharField(max_length=10, choices=FBT_RATIO_CHOICES, blank=True)
    auto_generate_fbt_outputs = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['parent_node__name', 'name', 'id']

    def clean(self):
        if self.device_type == 'plc':
            if not self.plc_model and self.plc_output_count <= 0:
                raise ValidationError('PLC devices need a PLC model or an explicit output count.')
            if self.fbt_ratio:
                raise ValidationError('PLC devices cannot define an FBT ratio.')
            if self.auto_generate_fbt_outputs:
                self.auto_generate_fbt_outputs = False
        elif self.device_type == 'fbt':
            if not self.fbt_ratio:
                raise ValidationError('FBT devices need a ratio such as 70/30, 80/20, or 90/10.')
            if self.plc_model:
                raise ValidationError('FBT devices cannot use a PLC model.')
            if self.plc_input_count or self.plc_output_count:
                raise ValidationError('FBT devices cannot define PLC input/output counts.')
            if self.auto_generate_plc_outputs:
                self.auto_generate_plc_outputs = False
        else:
            if self.plc_model:
                raise ValidationError('Only PLC devices can use a PLC model.')
            if self.plc_input_count or self.plc_output_count:
                raise ValidationError('Only PLC devices can define PLC input/output counts.')
            if self.auto_generate_plc_outputs:
                self.auto_generate_plc_outputs = False
            if self.fbt_ratio:
                raise ValidationError('Only FBT devices can use an FBT ratio.')
            if self.auto_generate_fbt_outputs:
                self.auto_generate_fbt_outputs = False

    @property
    def is_plc(self):
        return self.device_type == 'plc'

    @property
    def is_fbt(self):
        return self.device_type == 'fbt'

    @property
    def effective_plc_input_count(self):
        if not self.is_plc:
            return 0
        return self.plc_input_count or 1

    @property
    def effective_plc_output_count(self):
        if not self.is_plc:
            return 0
        if self.plc_output_count:
            return self.plc_output_count
        if self.plc_model and 'x' in self.plc_model:
            _, output_count = self.plc_model.lower().split('x', 1)
            try:
                return int(output_count)
            except ValueError:
                return 0
        return 0

    @property
    def effective_fbt_input_count(self):
        if not self.is_fbt:
            return 0
        return 1

    @property
    def effective_fbt_output_count(self):
        if not self.is_fbt:
            return 0
        return 2

    @property
    def fbt_ratio_parts(self):
        if not self.is_fbt or not self.fbt_ratio or '/' not in self.fbt_ratio:
            return (0, 0)
        primary_ratio, secondary_ratio = self.fbt_ratio.split('/', 1)
        try:
            return (int(primary_ratio), int(secondary_ratio))
        except ValueError:
            return (0, 0)

    @property
    def display_name(self):
        if self.slot_label:
            return f"{self.name} ({self.slot_label})"
        return self.name

    def __str__(self):
        return f"{self.parent_node.name} / {self.display_name}"


class Endpoint(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('inactive', 'Inactive'),
        ('damaged', 'Damaged'),
    ]

    ENDPOINT_TYPE_CHOICES = [
        ('access', 'Access Port'),
        ('uplink', 'Uplink'),
        ('distribution', 'Distribution'),
        ('split_output', 'Split Output'),
        ('other', 'Other'),
    ]

    parent_node = models.ForeignKey(
        NetworkNode,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='endpoints',
    )
    internal_device = models.ForeignKey(
        InternalDevice,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='endpoints',
    )
    router_interface = models.OneToOneField(
        'routers.RouterInterface',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='nms_endpoint',
    )
    label = models.CharField(max_length=80)
    endpoint_type = models.CharField(max_length=30, choices=ENDPOINT_TYPE_CHOICES, default='access')
    sequence = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sequence', 'label', 'id']

    def clean(self):
        if bool(self.parent_node_id) == bool(self.internal_device_id):
            raise ValidationError('Endpoint must belong either to a node or to an internal device.')
        if self.router_interface_id:
            if self.internal_device_id:
                raise ValidationError('Router interface endpoints must belong directly to a router root node.')
            if not self.parent_node_id:
                raise ValidationError('Router interface endpoints need a router root node.')
            if self.parent_node.router_id != self.router_interface.router_id:
                raise ValidationError('Router interface endpoint node must belong to the same router.')

    @property
    def root_node(self):
        if self.parent_node_id:
            return self.parent_node
        if self.internal_device_id:
            return self.internal_device.parent_node
        return None

    @property
    def root_node_id(self):
        if self.parent_node_id:
            return self.parent_node_id
        if self.internal_device_id:
            return self.internal_device.parent_node_id
        return None

    @property
    def display_name(self):
        if self.router_interface_id:
            return f"Router Port / {self.router_interface.display_name}"
        if self.internal_device_id:
            return f"{self.internal_device.display_name} / {self.label}"
        return self.label

    def __str__(self):
        root_node = self.root_node.name if self.root_node else 'Unassigned'
        return f"{root_node} / {self.display_name}"


class EndpointConnection(models.Model):
    CONNECTION_TYPE_CHOICES = [
        ('fiber', 'Fiber'),
        ('ethernet', 'Ethernet'),
        ('patch', 'Patch Cord'),
        ('splice', 'Splice'),
        ('internal', 'Internal Wiring'),
        ('other', 'Other'),
    ]

    ROLE_CHOICES = [
        ('feeder', 'Feeder'),
        ('passthrough', 'Pass-through'),
        ('splitter_input', 'Splitter Input'),
        ('splitter_output', 'Splitter Output'),
        ('drop', 'Drop'),
        ('direct_client', 'Direct Client'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('inactive', 'Inactive'),
        ('damaged', 'Damaged'),
    ]

    upstream_endpoint = models.ForeignKey(
        Endpoint,
        on_delete=models.CASCADE,
        related_name='downstream_connections',
    )
    downstream_endpoint = models.ForeignKey(
        Endpoint,
        on_delete=models.CASCADE,
        related_name='upstream_connections',
    )
    connection_type = models.CharField(max_length=20, choices=CONNECTION_TYPE_CHOICES, default='fiber')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='feeder')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    topology_link = models.ForeignKey(
        'TopologyLink',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='endpoint_connections',
    )
    cable_core = models.ForeignKey(
        'CableCore',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='endpoint_connections',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['upstream_endpoint__label', 'downstream_endpoint__label', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['upstream_endpoint', 'downstream_endpoint'],
                name='uniq_nms_endpoint_connection_pair',
            ),
            models.UniqueConstraint(
                fields=['downstream_endpoint'],
                condition=Q(status='active'),
                name='uniq_nms_active_upstream_per_downstream_endpoint',
            ),
        ]

    def clean(self):
        if self.upstream_endpoint_id and self.upstream_endpoint_id == self.downstream_endpoint_id:
            raise ValidationError('Endpoint connection cannot connect an endpoint to itself.')

        if self.cable_core_id and self.topology_link_id and self.cable_core.cable.link_id != self.topology_link_id:
            raise ValidationError('Selected cable core does not belong to the selected topology link.')

        if self.topology_link_id and self.upstream_endpoint_id and self.downstream_endpoint_id:
            upstream_node_id = self.upstream_endpoint.root_node_id
            downstream_node_id = self.downstream_endpoint.root_node_id
            if upstream_node_id and downstream_node_id and upstream_node_id != downstream_node_id:
                if (
                    self.topology_link.source_node_id != upstream_node_id
                    or self.topology_link.target_node_id != downstream_node_id
                ):
                    raise ValidationError('Topology link direction must match the upstream and downstream endpoint nodes.')

        if self._creates_loop():
            raise ValidationError('Endpoint connection would create a loop in the port graph.')

    def _creates_loop(self):
        if not self.upstream_endpoint_id or not self.downstream_endpoint_id:
            return False

        visited = set()
        queue = [self.downstream_endpoint_id]
        while queue:
            endpoint_id = queue.pop(0)
            if endpoint_id == self.upstream_endpoint_id:
                return True
            if endpoint_id in visited:
                continue
            visited.add(endpoint_id)
            queryset = EndpointConnection.objects.filter(
                upstream_endpoint_id=endpoint_id,
                status__in=['active', 'planned'],
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            queue.extend(queryset.values_list('downstream_endpoint_id', flat=True))
        return False

    @property
    def display_name(self):
        return f"{self.upstream_endpoint.display_name} -> {self.downstream_endpoint.display_name}"

    @property
    def source_node(self):
        return self.upstream_endpoint.root_node

    @property
    def target_node(self):
        return self.downstream_endpoint.root_node

    def __str__(self):
        return self.display_name


class TopologyLink(models.Model):
    LINK_TYPE_CHOICES = [
        ('fiber', 'Fiber'),
        ('ethernet', 'Ethernet'),
        ('wireless', 'Wireless Backhaul'),
        ('power', 'Power'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('inactive', 'Inactive'),
    ]

    name = models.CharField(max_length=100, blank=True)
    source_node = models.ForeignKey(
        NetworkNode,
        on_delete=models.CASCADE,
        related_name='outgoing_topology_links',
    )
    target_node = models.ForeignKey(
        NetworkNode,
        on_delete=models.CASCADE,
        related_name='incoming_topology_links',
    )
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, default='fiber')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']

    def clean(self):
        if self.source_node_id and self.source_node_id == self.target_node_id:
            raise ValidationError('Source node and target node must be different.')

    @property
    def display_name(self):
        if self.name:
            return self.name
        return f"{self.source_node.name} -> {self.target_node.name}"

    def __str__(self):
        return self.display_name

    @property
    def used_core_count(self):
        cable = getattr(self, 'cable', None)
        if cable is None:
            return 0
        return cable.used_core_count

    @property
    def total_core_count(self):
        cable = getattr(self, 'cable', None)
        if cable is None:
            return 0
        return cable.total_cores


class Cable(models.Model):
    INSTALLATION_TYPE_CHOICES = [
        ('aerial', 'Aerial'),
        ('underground', 'Underground'),
        ('indoor', 'Indoor'),
        ('mixed', 'Mixed'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('planned', 'Planned'),
        ('inactive', 'Inactive'),
        ('damaged', 'Damaged'),
    ]

    link = models.OneToOneField(
        TopologyLink,
        on_delete=models.CASCADE,
        related_name='cable',
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100, blank=True)
    total_cores = models.PositiveIntegerField(default=0)
    length_meters = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    installation_type = models.CharField(max_length=20, choices=INSTALLATION_TYPE_CHOICES, default='aerial')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    installed_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']

    def clean(self):
        if self.total_cores <= 0:
            raise ValidationError('Cable total cores must be greater than zero.')

    @property
    def display_name(self):
        return self.code or self.name

    @property
    def used_core_count(self):
        return self.cores.filter(status__in=['used', 'reserved']).count()

    @property
    def available_core_count(self):
        return max(self.total_cores - self.used_core_count, 0)

    def __str__(self):
        return f"{self.link.display_name} / {self.display_name}"


class CableCore(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('reserved', 'Reserved'),
        ('used', 'Used'),
        ('damaged', 'Damaged'),
    ]

    cable = models.ForeignKey(
        Cable,
        on_delete=models.CASCADE,
        related_name='cores',
    )
    sequence = models.PositiveIntegerField()
    color_name = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    assignment_label = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sequence']
        unique_together = [('cable', 'sequence')]

    def __str__(self):
        return f"{self.cable.display_name} core {self.sequence}"


class CableCoreAssignment(models.Model):
    STATUS_CHOICES = [
        ('reserved', 'Reserved'),
        ('used', 'Used'),
    ]

    service_attachment = models.ForeignKey(
        ServiceAttachment,
        on_delete=models.CASCADE,
        related_name='core_assignments',
    )
    core = models.OneToOneField(
        CableCore,
        on_delete=models.CASCADE,
        related_name='structured_assignment',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='used')
    label = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    assigned_by = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['core__cable__name', 'core__sequence', 'id']

    def clean(self):
        if not self.core_id:
            return

        if self.core.cable.link.link_type != 'fiber':
            raise ValidationError('Cable core assignments are only available on fiber links.')

        if self.core.cable.status in ('inactive', 'damaged'):
            raise ValidationError('Inactive or damaged cables cannot receive core assignments.')

        if self.core.status == 'damaged':
            raise ValidationError('Damaged cores cannot be assigned.')

        existing_assignment = CableCoreAssignment.objects.filter(core=self.core)
        if self.pk:
            existing_assignment = existing_assignment.exclude(pk=self.pk)
        if existing_assignment.exists():
            raise ValidationError('This core already has a structured assignment.')

        if not self.pk and self.core.status in ('reserved', 'used'):
            raise ValidationError('Only available cores can receive a new structured assignment.')

    @property
    def resolved_label(self):
        if self.label:
            return self.label
        return self.service_attachment.subscriber.display_name

    def __str__(self):
        return f"{self.core} assigned to {self.service_attachment.subscriber.username}"


class GpsTrace(models.Model):
    TRACE_TYPE_CHOICES = [
        ('survey', 'Survey'),
        ('as_built', 'As Built'),
        ('maintenance', 'Maintenance'),
        ('outage', 'Outage'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=120)
    trace_type = models.CharField(max_length=30, choices=TRACE_TYPE_CHOICES, default='survey')
    source_label = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=100, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'name']

    @property
    def point_count(self):
        return self.points.count()

    def __str__(self):
        return self.name


class GpsTracePoint(models.Model):
    trace = models.ForeignKey(
        GpsTrace,
        on_delete=models.CASCADE,
        related_name='points',
    )
    sequence = models.PositiveIntegerField()
    latitude = models.FloatField()
    longitude = models.FloatField()
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['sequence']
        unique_together = [('trace', 'sequence')]

    def clean(self):
        if not -90 <= self.latitude <= 90:
            raise ValidationError('Latitude must be between -90 and 90.')
        if not -180 <= self.longitude <= 180:
            raise ValidationError('Longitude must be between -180 and 180.')

    def __str__(self):
        return f"{self.trace_id} #{self.sequence}"


class TopologyLinkVertex(models.Model):
    link = models.ForeignKey(
        TopologyLink,
        on_delete=models.CASCADE,
        related_name='vertices',
    )
    sequence = models.PositiveIntegerField()
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ['sequence']
        unique_together = [('link', 'sequence')]

    def __str__(self):
        return f"{self.link_id} #{self.sequence}"
