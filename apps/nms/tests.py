from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.nms.forms import CableCoreAssignmentForm
from apps.nms.models import (
    Cable,
    CableCoreAssignment,
    Endpoint,
    GpsTrace,
    GpsTracePoint,
    InternalDevice,
    ServiceAttachment,
    ServiceAttachmentVertex,
    TopologyLink,
)
from apps.nms.services import (
    apply_core_assignment,
    build_nms_validation_report,
    delete_node_with_descendants,
    get_outage_impact,
    get_gps_trace_distance_km,
    get_assignable_cable_cores,
    parse_gps_trace_points,
    release_core_assignment,
    sync_cable_cores,
)
from apps.routers.models import Router
from apps.subscribers.models import NetworkNode, Subscriber, SubscriberNode


class CableCoreAssignmentTests(TestCase):
    def setUp(self):
        self.source_node = NetworkNode.objects.create(
            name='OLT-01',
            node_type='olt',
            latitude=14.5901,
            longitude=120.9811,
        )
        self.target_node = NetworkNode.objects.create(
            name='NAP-01',
            node_type='splice_box',
            latitude=14.5911,
            longitude=120.9821,
        )
        self.link = TopologyLink.objects.create(
            name='OLT-01 to NAP-01',
            source_node=self.source_node,
            target_node=self.target_node,
            link_type='fiber',
            status='active',
        )
        self.cable = Cable.objects.create(
            link=self.link,
            name='Cable A',
            code='CAB-A',
            total_cores=3,
        )
        sync_cable_cores(self.cable)
        self.subscriber = Subscriber.objects.create(
            username='client-001',
            full_name='Client One',
        )
        self.attachment = ServiceAttachment.objects.create(
            subscriber=self.subscriber,
            node=self.target_node,
            status='active',
        )

    def test_core_assignment_syncs_inventory_status_and_label(self):
        core = self.cable.cores.get(sequence=1)
        assignment = CableCoreAssignment.objects.create(
            service_attachment=self.attachment,
            core=core,
            status='used',
        )

        apply_core_assignment(assignment)

        core.refresh_from_db()
        self.assertEqual(core.status, 'used')
        self.assertEqual(core.assignment_label, 'Client One')

    def test_releasing_core_assignment_returns_core_to_available(self):
        core = self.cable.cores.get(sequence=1)
        assignment = CableCoreAssignment.objects.create(
            service_attachment=self.attachment,
            core=core,
            status='reserved',
            label='Drop pending install',
        )
        apply_core_assignment(assignment)

        release_core_assignment(assignment)

        core.refresh_from_db()
        self.assertFalse(CableCoreAssignment.objects.exists())
        self.assertEqual(core.status, 'available')
        self.assertEqual(core.assignment_label, '')

    def test_assignable_cores_exclude_structured_and_damaged_cores(self):
        assigned_core = self.cable.cores.get(sequence=1)
        damaged_core = self.cable.cores.get(sequence=2)
        available_core = self.cable.cores.get(sequence=3)
        assignment = CableCoreAssignment.objects.create(
            service_attachment=self.attachment,
            core=assigned_core,
            status='used',
        )
        apply_core_assignment(assignment)
        damaged_core.status = 'damaged'
        damaged_core.save(update_fields=['status', 'updated_at'])

        assignable_ids = set(get_assignable_cable_cores().values_list('pk', flat=True))

        self.assertNotIn(assigned_core.pk, assignable_ids)
        self.assertNotIn(damaged_core.pk, assignable_ids)
        self.assertIn(available_core.pk, assignable_ids)

    def test_core_assignment_form_rejects_manually_reserved_core(self):
        reserved_core = self.cable.cores.get(sequence=1)
        reserved_core.status = 'reserved'
        reserved_core.assignment_label = 'Legacy reservation'
        reserved_core.save(update_fields=['status', 'assignment_label', 'updated_at'])

        form = CableCoreAssignmentForm(
            data={
                'core-core': reserved_core.pk,
                'core-status': 'used',
                'core-label': '',
                'core-notes': '',
            },
            attachment=self.attachment,
            prefix='core',
        )

        self.assertFalse(form.is_valid())
        self.assertIn('core', form.errors)

    def test_validation_report_flags_missing_endpoint_mapping(self):
        report = build_nms_validation_report()

        messages = [issue['message'] for issue in report['issues']]
        self.assertIn(
            'This mapping is active but still uses only a serving node or manual endpoint label.',
            messages,
        )

    def test_outage_impact_follows_directed_downstream_links(self):
        downstream_node = NetworkNode.objects.create(
            name='NAP-02',
            node_type='splice_box',
        )
        TopologyLink.objects.create(
            name='NAP-01 to NAP-02',
            source_node=self.target_node,
            target_node=downstream_node,
            link_type='fiber',
            status='active',
        )
        downstream_subscriber = Subscriber.objects.create(
            username='client-002',
            full_name='Client Two',
        )
        downstream_attachment = ServiceAttachment.objects.create(
            subscriber=downstream_subscriber,
            node=downstream_node,
            status='active',
        )

        impact = get_outage_impact(link=self.link)

        self.assertIn(self.attachment, impact['attachments'])
        self.assertIn(downstream_attachment, impact['attachments'])
        self.assertEqual(impact['subscriber_count'], 2)


class GpsTraceAnalyticsTests(TestCase):
    def test_parse_gps_trace_points_accepts_notes(self):
        points = parse_gps_trace_points(
            '14.59950,120.98420,start\n14.60010,120.98550,end'
        )

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]['note'], 'start')
        self.assertEqual(points[1]['sequence'], 2)

    def test_gps_trace_distance_uses_trace_points(self):
        trace = GpsTrace.objects.create(name='Survey A')
        GpsTracePoint.objects.create(
            trace=trace,
            sequence=1,
            latitude=14.59950,
            longitude=120.98420,
        )
        GpsTracePoint.objects.create(
            trace=trace,
            sequence=2,
            latitude=14.60010,
            longitude=120.98550,
        )

        distance = get_gps_trace_distance_km(trace)

        self.assertGreater(distance, 0)


class ServiceAttachmentGeometryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='nms-admin',
            password='secret',
        )
        self.node = NetworkNode.objects.create(
            name='NAP-GEO',
            node_type='splice_box',
            latitude=14.5901,
            longitude=120.9811,
        )
        self.subscriber = Subscriber.objects.create(
            username='client-geo',
            full_name='Client Geometry',
            latitude=14.5951,
            longitude=120.9861,
        )
        self.attachment = ServiceAttachment.objects.create(
            subscriber=self.subscriber,
            node=self.node,
            status='active',
        )

    def test_update_attachment_geometry_api_saves_vertices(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('nms-update-attachment-geometry-api', args=[self.attachment.pk]),
            {'geometry_text': '14.5911,120.9821\n14.5921,120.9831'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(ServiceAttachmentVertex.objects.filter(service_attachment=self.attachment).count(), 2)
        self.assertEqual(payload['attachment']['vertex_count'], 2)
        self.assertEqual(len(payload['attachment']['points']), 4)

    def test_map_data_serializes_attachment_path_points(self):
        ServiceAttachmentVertex.objects.create(
            service_attachment=self.attachment,
            sequence=1,
            latitude=14.5911,
            longitude=120.9821,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('nms-map-data'))

        self.assertEqual(response.status_code, 200)
        attachment = response.json()['attachments'][0]
        self.assertEqual(attachment['id'], self.attachment.pk)
        self.assertEqual(attachment['vertex_count'], 1)
        self.assertEqual(attachment['points'][1], [14.5911, 120.9821])


class NetworkNodeDeleteTests(TestCase):
    def test_delete_node_removes_descendants_but_keeps_router_and_subscriber(self):
        router = Router.objects.create(
            name='Core Router',
            host='192.0.2.1',
            username='admin',
            password='secret',
        )
        source_node = NetworkNode.objects.create(
            router=router,
            name='OLT-Delete',
            node_type='olt',
        )
        node = NetworkNode.objects.create(
            router=router,
            name='NAP-Delete',
            node_type='splice_box',
        )
        subscriber = Subscriber.objects.create(username='delete-node-client')
        SubscriberNode.objects.create(subscriber=subscriber, node=node, port_label='P1')
        attachment = ServiceAttachment.objects.create(
            subscriber=subscriber,
            node=node,
            endpoint_label='P1',
            status='active',
        )
        device = InternalDevice.objects.create(
            parent_node=node,
            name='PLC A',
            device_type='other',
        )
        Endpoint.objects.create(
            internal_device=device,
            label='OUT 1',
            endpoint_type='access',
            sequence=1,
        )
        link = TopologyLink.objects.create(
            name='Delete Link',
            source_node=source_node,
            target_node=node,
            link_type='fiber',
        )
        cable = Cable.objects.create(
            link=link,
            name='Delete Cable',
            total_cores=2,
        )
        sync_cable_cores(cable)
        core = cable.cores.get(sequence=1)
        CableCoreAssignment.objects.create(
            service_attachment=attachment,
            core=core,
            status='used',
        )

        impact = delete_node_with_descendants(node)

        self.assertEqual(impact['service_attachment_count'], 1)
        self.assertEqual(impact['subscriber_node_count'], 1)
        self.assertEqual(impact['internal_device_count'], 1)
        self.assertEqual(impact['endpoint_count'], 1)
        self.assertEqual(impact['topology_link_count'], 1)
        self.assertEqual(impact['cable_count'], 1)
        self.assertEqual(impact['cable_core_count'], 2)
        self.assertTrue(Router.objects.filter(pk=router.pk).exists())
        self.assertTrue(Subscriber.objects.filter(pk=subscriber.pk).exists())
        self.assertTrue(NetworkNode.objects.filter(pk=source_node.pk).exists())
        self.assertFalse(NetworkNode.objects.filter(pk=node.pk).exists())
        self.assertFalse(ServiceAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(SubscriberNode.objects.filter(subscriber=subscriber).exists())
        self.assertFalse(TopologyLink.objects.filter(pk=link.pk).exists())
