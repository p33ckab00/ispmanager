from django.core.management.base import BaseCommand

from apps.core.role_presets import sync_permission_group_presets


class Command(BaseCommand):
    help = 'Create or update ISP Manager permission group presets.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Replace each preset group permission set instead of adding missing permissions.',
        )

    def handle(self, *args, **options):
        results = sync_permission_group_presets(
            replace=options['replace'],
            verbosity=options.get('verbosity', 1),
        )
        mode = 'replaced' if options['replace'] else 'synced'
        for result in results:
            status = 'created' if result['created'] else 'updated'
            self.stdout.write(
                self.style.SUCCESS(
                    f"{result['group'].name}: {status}, {result['permission_count']} permission(s) {mode}"
                )
            )
