from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from apps.core.role_presets import sync_permission_group_presets


class RolePresetTests(TestCase):
    def test_sync_permission_group_presets_creates_expected_groups(self):
        sync_permission_group_presets(replace=True)

        expected_groups = {
            'ISP Admin',
            'ISP Cashier',
            'ISP Support',
            'ISP Installer',
            'ISP Read-only Auditor',
        }

        self.assertTrue(expected_groups.issubset(set(Group.objects.values_list('name', flat=True))))

    def test_cashier_group_gets_payment_and_refund_permissions(self):
        sync_permission_group_presets(replace=True)

        cashier = Group.objects.get(name='ISP Cashier')
        permission_codenames = set(cashier.permissions.values_list('codename', flat=True))

        self.assertIn('add_payment', permission_codenames)
        self.assertIn('change_accountcreditadjustment', permission_codenames)
        self.assertIn('add_expenserecord', permission_codenames)

    def test_read_only_auditor_gets_only_view_permissions(self):
        sync_permission_group_presets(replace=True)

        auditor = Group.objects.get(name='ISP Read-only Auditor')
        codenames = set(auditor.permissions.values_list('codename', flat=True))

        self.assertTrue(codenames)
        self.assertTrue(all(codename.startswith('view_') for codename in codenames))

    def test_admin_group_gets_all_permissions(self):
        sync_permission_group_presets(replace=True)

        admin = Group.objects.get(name='ISP Admin')

        self.assertEqual(admin.permissions.count(), Permission.objects.count())
