from django import forms
from django.db.models import Q
from apps.nms.models import (
    Cable,
    CableCore,
    CableCoreAssignment,
    Endpoint,
    EndpointConnection,
    GpsTrace,
    GpsTracePoint,
    InternalDevice,
    ServiceAttachment,
    ServiceAttachmentVertex,
    TopologyLink,
    TopologyLinkVertex,
)
from apps.nms.services import (
    apply_core_assignment,
    get_eligible_endpoints,
    get_assignable_cable_cores,
    has_cable_tables,
    has_distribution_tables,
    has_endpoint_connection_tables,
    parse_gps_trace_points,
    sync_cable_cores,
)
from apps.subscribers.models import NetworkNode


class ServiceAttachmentForm(forms.ModelForm):
    class Meta:
        model = ServiceAttachment
        fields = ['node', 'endpoint', 'endpoint_label', 'status', 'notes']
        widgets = {
            'node': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'endpoint': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'endpoint_label': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.selected_node = kwargs.pop('selected_node', None)
        super().__init__(*args, **kwargs)
        self.fields['node'].queryset = NetworkNode.objects.filter(is_active=True).order_by('name')
        self.fields['node'].empty_label = '-- Select node --'
        if has_distribution_tables():
            endpoint_queryset = get_eligible_endpoints(
                selected_node=self.selected_node,
                current_attachment=self.instance if self.instance.pk else None,
            )
            self.fields['endpoint'].queryset = endpoint_queryset
            self.fields['endpoint'].empty_label = '-- No endpoint selected --'
            self.fields['endpoint'].label_from_instance = (
                lambda endpoint: f"{endpoint.root_node.name if endpoint.root_node else 'Unknown'} / "
                f"{endpoint.display_name} [{endpoint.get_status_display()}]"
            )
        else:
            self.fields['endpoint'].queryset = Endpoint.objects.none()
            self.fields['endpoint'].empty_label = '-- Endpoint tables unavailable --'
        self.fields['endpoint_label'].required = False
        self.fields['endpoint_label'].label = 'Manual Endpoint Label'
        self.fields['endpoint'].required = False
        self.fields['notes'].required = False
        self.eligible_endpoint_count = self.fields['endpoint'].queryset.count()

    def clean_endpoint_label(self):
        return (self.cleaned_data.get('endpoint_label') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        node = cleaned_data.get('node')
        endpoint = cleaned_data.get('endpoint')
        status = cleaned_data.get('status')

        if not node and status == 'active':
            raise forms.ValidationError('Select a node before marking this subscriber as mapped.')

        if endpoint and not node:
            cleaned_data['node'] = endpoint.root_node
            node = cleaned_data['node']

        if endpoint and node and endpoint.root_node_id != node.pk:
            raise forms.ValidationError('Selected endpoint does not belong to the chosen serving node.')

        if endpoint and endpoint.status in ('inactive', 'damaged') and status == 'active':
            raise forms.ValidationError('Inactive or damaged endpoints cannot be assigned to active mappings.')

        if endpoint and status == 'active':
            conflicting_attachment = ServiceAttachment.objects.filter(
                endpoint=endpoint,
                status='active',
            )
            if self.instance.pk:
                conflicting_attachment = conflicting_attachment.exclude(pk=self.instance.pk)
            if conflicting_attachment.exists():
                raise forms.ValidationError('This endpoint is already occupied by another active subscriber mapping.')

        return cleaned_data


class CableCoreAssignmentForm(forms.ModelForm):
    class Meta:
        model = CableCoreAssignment
        fields = ['core', 'status', 'label', 'notes']
        widgets = {
            'core': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'label': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.attachment = kwargs.pop('attachment')
        super().__init__(*args, **kwargs)
        current_assignment = self.instance if self.instance.pk else None
        self.fields['core'].queryset = get_assignable_cable_cores(
            current_assignment=current_assignment,
        )
        self.fields['core'].empty_label = '-- Select available fiber core --'
        self.fields['core'].label_from_instance = self._core_label
        self.fields['label'].required = False
        self.fields['label'].label = 'Assignment Label'
        self.fields['notes'].required = False
        self.assignable_core_count = self.fields['core'].queryset.count()

    def _core_label(self, core):
        link = core.cable.link
        return (
            f"{core.cable.display_name} core {core.sequence} ({core.color_name}) - "
            f"{link.source_node.name} -> {link.target_node.name}"
        )

    def clean_label(self):
        return (self.cleaned_data.get('label') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        core = cleaned_data.get('core')
        if core and self.attachment is None:
            raise forms.ValidationError('Save the Premium NMS mapping before assigning cable cores.')
        return cleaned_data

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.service_attachment = self.attachment
        if commit:
            assignment.save()
            apply_core_assignment(assignment)
        return assignment


class GpsTraceImportForm(forms.ModelForm):
    coordinates_text = forms.CharField(
        label='Coordinates',
        widget=forms.Textarea(attrs={
            'rows': 8,
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono',
            'placeholder': '14.59950,120.98420\n14.60010,120.98550',
        }),
        help_text='One point per line using lat,lng. Optional notes may follow after another comma.',
    )

    class Meta:
        model = GpsTrace
        fields = ['name', 'trace_type', 'source_label', 'captured_at', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'trace_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'source_label': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'captured_at': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['captured_at'].required = False
        self.fields['captured_at'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
        self.fields['source_label'].required = False
        self.fields['notes'].required = False

    def clean_coordinates_text(self):
        coordinates_text = self.cleaned_data.get('coordinates_text') or ''
        try:
            self._trace_points = parse_gps_trace_points(coordinates_text)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return coordinates_text

    def save(self, commit=True, created_by=''):
        trace = super().save(commit=False)
        trace.created_by = created_by
        if commit:
            trace.save()
            GpsTracePoint.objects.bulk_create([
                GpsTracePoint(
                    trace=trace,
                    sequence=point['sequence'],
                    latitude=point['latitude'],
                    longitude=point['longitude'],
                    note=point['note'],
                )
                for point in getattr(self, '_trace_points', [])
            ])
        return trace


class InternalDeviceForm(forms.ModelForm):
    class Meta:
        model = InternalDevice
        fields = [
            'name',
            'device_type',
            'slot_label',
            'plc_model',
            'plc_input_count',
            'plc_output_count',
            'auto_generate_plc_outputs',
            'fbt_ratio',
            'auto_generate_fbt_outputs',
            'notes',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'device_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'slot_label': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'plc_model': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'plc_input_count': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'min': '0',
            }),
            'plc_output_count': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'min': '0',
            }),
            'fbt_ratio': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['auto_generate_plc_outputs'].initial = True
            self.fields['auto_generate_fbt_outputs'].initial = True
        self.fields['plc_input_count'].required = False
        self.fields['plc_output_count'].required = False
        self.fields['fbt_ratio'].required = False


class EndpointForm(forms.ModelForm):
    class Meta:
        model = Endpoint
        fields = ['internal_device', 'label', 'endpoint_type', 'sequence', 'status', 'notes']
        widgets = {
            'internal_device': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'label': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'endpoint_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'sequence': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'min': '1',
            }),
            'status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.parent_node = kwargs.pop('parent_node')
        super().__init__(*args, **kwargs)
        self.fields['internal_device'].required = False
        self.fields['internal_device'].empty_label = '-- Direct node endpoint --'
        self.fields['internal_device'].queryset = InternalDevice.objects.filter(
            parent_node=self.parent_node,
            is_active=True,
        ).order_by('name')

    def clean_internal_device(self):
        internal_device = self.cleaned_data.get('internal_device')
        if internal_device and internal_device.parent_node_id != self.parent_node.pk:
            raise forms.ValidationError('Selected internal device does not belong to this node.')
        return internal_device

    def save(self, commit=True):
        endpoint = super().save(commit=False)
        if endpoint.internal_device_id:
            endpoint.parent_node = None
        else:
            endpoint.parent_node = self.parent_node
        if commit:
            endpoint.save()
        return endpoint


class EndpointConnectionForm(forms.ModelForm):
    class Meta:
        model = EndpointConnection
        fields = [
            'upstream_endpoint',
            'downstream_endpoint',
            'connection_type',
            'role',
            'topology_link',
            'cable_core',
            'status',
            'notes',
        ]
        widgets = {
            'upstream_endpoint': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'downstream_endpoint': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'connection_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'role': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'topology_link': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'cable_core': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.parent_node = kwargs.pop('parent_node')
        super().__init__(*args, **kwargs)
        endpoint_queryset = Endpoint.objects.select_related(
            'parent_node',
            'internal_device',
            'internal_device__parent_node',
            'router_interface',
            'router_interface__router',
        ).filter(
            Q(parent_node__is_active=True) | Q(internal_device__parent_node__is_active=True)
        ).exclude(status__in=['inactive', 'damaged']).order_by(
            'parent_node__name',
            'internal_device__parent_node__name',
            'internal_device__name',
            'sequence',
            'label',
        )
        self.fields['upstream_endpoint'].queryset = endpoint_queryset
        self.fields['downstream_endpoint'].queryset = endpoint_queryset
        self.fields['upstream_endpoint'].label_from_instance = self._endpoint_label
        self.fields['downstream_endpoint'].label_from_instance = self._endpoint_label
        self.fields['topology_link'].queryset = TopologyLink.objects.select_related(
            'source_node',
            'target_node',
        ).order_by('name', 'id')
        self.fields['topology_link'].required = False
        self.fields['topology_link'].empty_label = '-- Same-box/internal or no span --'
        self.fields['cable_core'].required = False
        self.fields['cable_core'].empty_label = '-- No cable core --'
        if has_cable_tables():
            self.fields['cable_core'].queryset = CableCore.objects.select_related(
                'cable',
                'cable__link',
            ).exclude(status='damaged').order_by('cable__name', 'sequence')
        else:
            self.fields['cable_core'].queryset = CableCore.objects.none()
            self.fields['cable_core'].disabled = True
        if not has_endpoint_connection_tables():
            for field in self.fields.values():
                field.disabled = True

    def _endpoint_label(self, endpoint):
        root_node = endpoint.root_node
        root_label = root_node.name if root_node else 'Unknown'
        return f"{root_label} / {endpoint.display_name} [{endpoint.get_status_display()}]"

    def clean(self):
        cleaned_data = super().clean()
        upstream_endpoint = cleaned_data.get('upstream_endpoint')
        downstream_endpoint = cleaned_data.get('downstream_endpoint')
        topology_link = cleaned_data.get('topology_link')
        cable_core = cleaned_data.get('cable_core')

        if cable_core and topology_link is None:
            cleaned_data['topology_link'] = cable_core.cable.link
            topology_link = cleaned_data['topology_link']

        if cable_core and topology_link and cable_core.cable.link_id != topology_link.pk:
            raise forms.ValidationError('Selected cable core does not belong to the selected topology link.')

        if upstream_endpoint and downstream_endpoint:
            current_node_ids = {
                endpoint.root_node_id
                for endpoint in [upstream_endpoint, downstream_endpoint]
                if endpoint.root_node_id
            }
            if self.parent_node.pk not in current_node_ids:
                raise forms.ValidationError('At least one endpoint in the wiring must belong to this node.')

        return cleaned_data


class NetworkNodeForm(forms.ModelForm):
    class Meta:
        model = NetworkNode
        fields = [
            'name',
            'node_type',
            'router',
            'latitude',
            'longitude',
            'port_count',
            'notes',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'node_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'router': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'latitude': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'step': '0.000001',
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'step': '0.000001',
            }),
            'port_count': forms.NumberInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
                'min': '0',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['router'].required = False
        self.fields['router'].queryset = self.fields['router'].queryset.filter(
            is_active=True,
        ).order_by('name')
        self.fields['router'].empty_label = '-- No linked router --'
        self.fields['latitude'].required = False
        self.fields['longitude'].required = False
        self.fields['port_count'].required = False

    def clean_port_count(self):
        return self.cleaned_data.get('port_count') or 0


class TopologyLinkForm(forms.ModelForm):
    geometry_text = forms.CharField(
        required=False,
        label='Geometry Vertices',
        help_text='Optional middle points only, one "lat,lng" pair per line. Start and end stay anchored to the selected nodes.',
        widget=forms.Textarea(attrs={
            'rows': 6,
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono',
            'placeholder': '14.59950,120.98420\n14.60010,120.98550',
        }),
    )
    cable_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )
    cable_code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )
    cable_total_cores = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            'min': '0',
        }),
    )
    cable_length_meters = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            'min': '0',
            'step': '0.01',
        }),
    )
    cable_installation_type = forms.ChoiceField(
        required=False,
        choices=Cable.INSTALLATION_TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )
    cable_status = forms.ChoiceField(
        required=False,
        choices=Cable.STATUS_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )
    cable_installed_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )
    cable_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
        }),
    )

    class Meta:
        model = TopologyLink
        fields = ['name', 'source_node', 'target_node', 'link_type', 'status', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'source_node': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'target_node': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'link_type': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        node_queryset = NetworkNode.objects.filter(is_active=True).order_by('name')
        self.fields['source_node'].queryset = node_queryset
        self.fields['target_node'].queryset = node_queryset
        self.cable_table_ready = has_cable_tables()

        if self.instance.pk:
            vertices = list(self.instance.vertices.all())
            self.fields['geometry_text'].initial = '\n'.join(
                f"{vertex.latitude},{vertex.longitude}" for vertex in vertices
            )
            if self.cable_table_ready:
                cable = getattr(self.instance, 'cable', None)
                if cable:
                    self.fields['cable_name'].initial = cable.name
                    self.fields['cable_code'].initial = cable.code
                    self.fields['cable_total_cores'].initial = cable.total_cores
                    self.fields['cable_length_meters'].initial = cable.length_meters
                    self.fields['cable_installation_type'].initial = cable.installation_type
                    self.fields['cable_status'].initial = cable.status
                    self.fields['cable_installed_on'].initial = cable.installed_on
                    self.fields['cable_notes'].initial = cable.notes

        if not self.cable_table_ready:
            for field_name in [
                'cable_name',
                'cable_code',
                'cable_total_cores',
                'cable_length_meters',
                'cable_installation_type',
                'cable_status',
                'cable_installed_on',
                'cable_notes',
            ]:
                self.fields[field_name].disabled = True

    def clean_geometry_text(self):
        geometry_text = (self.cleaned_data.get('geometry_text') or '').strip()
        geometry_points = []

        for line_number, raw_line in enumerate(geometry_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 2:
                raise forms.ValidationError(
                    f'Line {line_number} must be in "lat,lng" format.'
                )

            try:
                latitude = float(parts[0])
                longitude = float(parts[1])
            except ValueError as exc:
                raise forms.ValidationError(
                    f'Line {line_number} contains invalid coordinates.'
                ) from exc

            geometry_points.append((latitude, longitude))

        self._geometry_points = geometry_points
        return geometry_text

    def clean(self):
        cleaned_data = super().clean()
        link_type = cleaned_data.get('link_type')
        cable_name = (cleaned_data.get('cable_name') or '').strip()
        cable_code = (cleaned_data.get('cable_code') or '').strip()
        cable_total_cores = cleaned_data.get('cable_total_cores') or 0
        cable_length = cleaned_data.get('cable_length_meters')
        cable_notes = (cleaned_data.get('cable_notes') or '').strip()
        cable_installation_type = cleaned_data.get('cable_installation_type')
        cable_status = cleaned_data.get('cable_status')
        cable_installed_on = cleaned_data.get('cable_installed_on')

        has_cable_data = any([
            cable_name,
            cable_code,
            cable_total_cores,
            cable_length,
            cable_notes,
            cable_installation_type,
            cable_status,
            cable_installed_on,
        ])

        if has_cable_data and link_type != 'fiber':
            raise forms.ValidationError('Cable inventory is currently supported only for fiber links.')

        if link_type == 'fiber' and has_cable_data:
            if cable_total_cores <= 0:
                raise forms.ValidationError('Fiber links with cable inventory need a total core count greater than zero.')
            if not cable_name:
                raise forms.ValidationError('Provide a cable name when adding fiber cable inventory.')

        existing_cable = getattr(self.instance, 'cable', None) if self.instance.pk and self.cable_table_ready else None
        if existing_cable and cable_total_cores and cable_total_cores < existing_cable.used_core_count:
            raise forms.ValidationError(
                f'Cable total cores cannot be reduced below the {existing_cable.used_core_count} used or reserved cores.'
            )

        self._cable_data = {
            'has_cable_data': has_cable_data,
            'name': cable_name,
            'code': cable_code,
            'total_cores': cable_total_cores,
            'length_meters': cable_length,
            'installation_type': cable_installation_type or 'aerial',
            'status': cable_status or 'active',
            'installed_on': cable_installed_on,
            'notes': cable_notes,
        }
        return cleaned_data

    def save(self, commit=True):
        if not commit:
            raise ValueError('TopologyLinkForm.save requires commit=True.')

        link = super().save(commit=True)
        link.vertices.all().delete()
        TopologyLinkVertex.objects.bulk_create([
            TopologyLinkVertex(
                link=link,
                sequence=index,
                latitude=point[0],
                longitude=point[1],
            )
            for index, point in enumerate(getattr(self, '_geometry_points', []), start=1)
        ])

        if self.cable_table_ready:
            cable_data = getattr(self, '_cable_data', {})
            cable = getattr(link, 'cable', None)
            if cable_data.get('has_cable_data'):
                if cable is None:
                    cable = Cable(link=link)
                cable.name = cable_data['name']
                cable.code = cable_data['code']
                cable.total_cores = cable_data['total_cores']
                cable.length_meters = cable_data['length_meters']
                cable.installation_type = cable_data['installation_type']
                cable.status = cable_data['status']
                cable.installed_on = cable_data['installed_on']
                cable.notes = cable_data['notes']
                cable.save()
                sync_cable_cores(cable)
            elif cable is not None and cable.used_core_count == 0:
                cable.delete()
        return link


class TopologyLinkGeometryForm(forms.Form):
    geometry_text = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.link = kwargs.pop('link')
        super().__init__(*args, **kwargs)

    def clean_geometry_text(self):
        geometry_text = (self.cleaned_data.get('geometry_text') or '').strip()
        geometry_points = []

        for line_number, raw_line in enumerate(geometry_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 2:
                raise forms.ValidationError(
                    f'Line {line_number} must be in "lat,lng" format.'
                )

            try:
                latitude = float(parts[0])
                longitude = float(parts[1])
            except ValueError as exc:
                raise forms.ValidationError(
                    f'Line {line_number} contains invalid coordinates.'
                ) from exc

            geometry_points.append((latitude, longitude))

        self._geometry_points = geometry_points
        return geometry_text

    def save(self):
        self.link.vertices.all().delete()
        TopologyLinkVertex.objects.bulk_create([
            TopologyLinkVertex(
                link=self.link,
                sequence=index,
                latitude=point[0],
                longitude=point[1],
            )
            for index, point in enumerate(getattr(self, '_geometry_points', []), start=1)
        ])
        return self.link


class ServiceAttachmentGeometryForm(forms.Form):
    geometry_text = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.attachment = kwargs.pop('attachment')
        super().__init__(*args, **kwargs)

    def clean_geometry_text(self):
        geometry_text = (self.cleaned_data.get('geometry_text') or '').strip()
        geometry_points = []

        for line_number, raw_line in enumerate(geometry_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 2:
                raise forms.ValidationError(
                    f'Line {line_number} must be in "lat,lng" format.'
                )

            try:
                latitude = float(parts[0])
                longitude = float(parts[1])
            except ValueError as exc:
                raise forms.ValidationError(
                    f'Line {line_number} contains invalid coordinates.'
                ) from exc

            geometry_points.append((latitude, longitude))

        self._geometry_points = geometry_points
        return geometry_text

    def save(self):
        self.attachment.vertices.all().delete()
        ServiceAttachmentVertex.objects.bulk_create([
            ServiceAttachmentVertex(
                service_attachment=self.attachment,
                sequence=index,
                latitude=point[0],
                longitude=point[1],
            )
            for index, point in enumerate(getattr(self, '_geometry_points', []), start=1)
        ])
        return self.attachment
