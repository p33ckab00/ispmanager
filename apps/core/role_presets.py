from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate


ROLE_GROUP_PRESETS = {
    'ISP Admin': {'all_permissions': True},
    'ISP Cashier': {
        'permissions': [
            ('subscribers', 'view_subscriber'),
            ('billing', 'view_invoice'),
            ('billing', 'add_invoice'),
            ('billing', 'change_invoice'),
            ('billing', 'view_payment'),
            ('billing', 'add_payment'),
            ('billing', 'view_paymentallocation'),
            ('billing', 'view_billingsnapshot'),
            ('billing', 'add_billingsnapshot'),
            ('billing', 'change_billingsnapshot'),
            ('billing', 'view_billingsnapshotitem'),
            ('billing', 'view_accountcreditadjustment'),
            ('billing', 'change_accountcreditadjustment'),
            ('accounting', 'view_incomerecord'),
            ('accounting', 'view_expenserecord'),
            ('accounting', 'add_expenserecord'),
            ('accounting', 'view_accountingentity'),
            ('accounting', 'view_accountingsettings'),
            ('accounting', 'view_accountingperiod'),
            ('accounting', 'view_chartofaccount'),
            ('accounting', 'view_journalentry'),
            ('accounting', 'view_journalline'),
            ('sms', 'view_smslog'),
        ],
    },
    'ISP Support': {
        'permissions': [
            ('subscribers', 'view_subscriber'),
            ('subscribers', 'change_subscriber'),
            ('subscribers', 'manage_subscriber_lifecycle'),
            ('billing', 'view_invoice'),
            ('billing', 'view_payment'),
            ('billing', 'view_billingsnapshot'),
            ('billing', 'view_accountcreditadjustment'),
            ('sms', 'view_smslog'),
            ('sms', 'add_smslog'),
            ('routers', 'view_router'),
            ('subscribers', 'view_networknode'),
            ('subscribers', 'view_subscribernode'),
            ('nms', 'view_serviceattachment'),
            ('nms', 'view_cable'),
            ('nms', 'view_cablecore'),
            ('nms', 'view_cablecoreassignment'),
            ('nms', 'view_gpstrace'),
            ('nms', 'view_gpstracepoint'),
        ],
    },
    'ISP Installer': {
        'permissions': [
            ('subscribers', 'view_subscriber'),
            ('subscribers', 'add_subscriber'),
            ('subscribers', 'change_subscriber'),
            ('subscribers', 'import_subscribers'),
            ('subscribers', 'view_networknode'),
            ('subscribers', 'add_subscribernode'),
            ('subscribers', 'change_subscribernode'),
            ('subscribers', 'view_subscribernode'),
            ('routers', 'view_router'),
            ('nms', 'view_serviceattachment'),
            ('nms', 'add_serviceattachment'),
            ('nms', 'change_serviceattachment'),
            ('nms', 'view_cable'),
            ('nms', 'view_cablecore'),
            ('nms', 'view_cablecoreassignment'),
            ('nms', 'add_cablecoreassignment'),
            ('nms', 'change_cablecoreassignment'),
            ('nms', 'delete_cablecoreassignment'),
            ('nms', 'view_gpstrace'),
            ('nms', 'add_gpstrace'),
            ('nms', 'change_gpstrace'),
            ('nms', 'delete_gpstrace'),
            ('nms', 'view_gpstracepoint'),
            ('nms', 'add_gpstracepoint'),
            ('nms', 'change_gpstracepoint'),
            ('nms', 'delete_gpstracepoint'),
        ],
    },
    'ISP Read-only Auditor': {
        'view_all_local_apps': True,
    },
}

LOCAL_PERMISSION_APP_LABELS = [
    'accounting',
    'billing',
    'core',
    'data_exchange',
    'diagnostics',
    'landing',
    'nms',
    'notifications',
    'routers',
    'settings_app',
    'sms',
    'subscribers',
]

_synced_after_migrate = False


def ensure_all_permissions_exist(verbosity=0):
    for app_config in django_apps.get_app_configs():
        if app_config.models_module is not None:
            create_permissions(app_config, verbosity=verbosity)


def _permission_queryset_for_preset(config):
    if config.get('all_permissions'):
        return Permission.objects.all()

    if config.get('view_all_local_apps'):
        return Permission.objects.filter(
            content_type__app_label__in=LOCAL_PERMISSION_APP_LABELS,
            codename__startswith='view_',
        )

    query = Permission.objects.none()
    for app_label, codename in config.get('permissions', []):
        query |= Permission.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        )
    return query


def sync_permission_group_presets(replace=False, verbosity=0):
    ensure_all_permissions_exist(verbosity=verbosity)

    results = []
    for group_name, config in ROLE_GROUP_PRESETS.items():
        group, created = Group.objects.get_or_create(name=group_name)
        permissions = list(_permission_queryset_for_preset(config).distinct())
        if replace:
            group.permissions.set(permissions)
        else:
            group.permissions.add(*permissions)
        results.append({
            'group': group,
            'created': created,
            'permission_count': len(permissions),
        })
    return results


def sync_permission_group_presets_after_migrate(sender, **kwargs):
    global _synced_after_migrate
    if _synced_after_migrate:
        return
    _synced_after_migrate = True
    sync_permission_group_presets(replace=False, verbosity=0)


def connect_role_preset_sync():
    post_migrate.connect(
        sync_permission_group_presets_after_migrate,
        dispatch_uid='ispmanager_sync_permission_group_presets',
    )
