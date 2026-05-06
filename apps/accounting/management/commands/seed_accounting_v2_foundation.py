from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounting.services import available_coa_templates, create_accounting_foundation


class Command(BaseCommand):
    help = 'Create the Accounting v2 Slice 1A entity, periods, and ISP chart of accounts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            default='ISP Operator',
            help='Accounting entity display name to use if no active entity exists.',
        )
        parser.add_argument(
            '--legal-name',
            default='',
            help='Registered legal name to use if no active entity exists.',
        )
        parser.add_argument(
            '--tin',
            default='',
            help='Tax identification number to use if no active entity exists.',
        )
        parser.add_argument(
            '--address',
            default='',
            help='Registered address to use if no active entity exists.',
        )
        parser.add_argument(
            '--template',
            default='isp_non_vat_sole_prop',
            choices=[item['key'] for item in available_coa_templates()],
            help='ISP chart of accounts template to seed.',
        )
        parser.add_argument(
            '--year',
            type=int,
            default=timezone.localdate().year,
            help='Fiscal year for the first 12 monthly accounting periods.',
        )

    def handle(self, *args, **options):
        result = create_accounting_foundation(
            entity_name=options['name'],
            legal_name=options['legal_name'],
            tin=options['tin'],
            registered_address=options['address'],
            template_key=options['template'],
            fiscal_year=options['year'],
        )
        entity = result['entity']
        coa = result['coa']
        periods = result['periods']
        entity_status = 'created' if result['entity_created'] else 'reused'

        self.stdout.write(self.style.SUCCESS(
            f"Accounting entity {entity_status}: {entity}"
        ))
        self.stdout.write(
            f"COA template: {coa['template']['label']} "
            f"({coa['created']} created, {coa['updated']} updated, {coa['total']} total)"
        )
        self.stdout.write(
            f"Periods for {options['year']}: "
            f"{periods['created']} created, {len(periods['periods'])} total"
        )
        self.stdout.write(self.style.SUCCESS('Accounting v2 Slice 1A foundation is ready.'))
