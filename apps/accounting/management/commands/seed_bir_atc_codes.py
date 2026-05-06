from django.core.management.base import BaseCommand

from apps.accounting.services import seed_bir_atc_codes


class Command(BaseCommand):
    help = 'Seed the Accounting v2 BIR ATC catalog used by withholding workflows.'

    def handle(self, *args, **options):
        result = seed_bir_atc_codes()
        self.stdout.write(self.style.SUCCESS(
            f"BIR ATC catalog seeded: {result['created']} created, "
            f"{result['updated']} updated, {result['total']} total."
        ))
