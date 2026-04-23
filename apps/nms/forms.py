from django import forms
from apps.nms.models import (
    Endpoint,
    InternalDevice,
    ServiceAttachment,
    TopologyLink,
    TopologyLinkVertex,
)
from apps.nms.services import get_eligible_endpoints, has_distribution_tables
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
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['auto_generate_plc_outputs'].initial = True
        self.fields['plc_input_count'].required = False
        self.fields['plc_output_count'].required = False


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

        if self.instance.pk:
            vertices = list(self.instance.vertices.all())
            self.fields['geometry_text'].initial = '\n'.join(
                f"{vertex.latitude},{vertex.longitude}" for vertex in vertices
            )

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
