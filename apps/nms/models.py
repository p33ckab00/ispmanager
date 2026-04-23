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
        ('70/30', '70/30'),
        ('80/20', '80/20'),
        ('90/10', '90/10'),
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
        if self.internal_device_id:
            return f"{self.internal_device.display_name} / {self.label}"
        return self.label

    def __str__(self):
        root_node = self.root_node.name if self.root_node else 'Unassigned'
        return f"{root_node} / {self.display_name}"


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
