from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import AccountingSourcePosting, JournalEntry
from apps.accounting.services import (
    create_credit_adjustment_source_draft,
    create_invoice_source_draft,
    create_invoice_void_source_draft,
    create_invoice_waiver_source_draft,
    create_payment_allocation_advance_application_draft,
    create_payment_source_draft,
)
from apps.billing.models import AccountCreditAdjustment, Invoice, Payment, PaymentAllocation


SOURCE_CHOICES = [
    'all',
    'invoices',
    'payments',
    'advance-applications',
    'credit-adjustments',
    'waivers',
    'voids',
]


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Invalid date {value!r}. Use YYYY-MM-DD.") from exc


def _apply_date_filter(qs, field_name, start_date, end_date):
    if start_date:
        qs = qs.filter(**{f"{field_name}__date__gte": start_date})
    if end_date:
        qs = qs.filter(**{f"{field_name}__date__lte": end_date})
    return qs


def _posting_from_result(result):
    if isinstance(result, AccountingSourcePosting):
        return result
    if isinstance(result, JournalEntry):
        return result.source_posting_records.order_by('-updated_at').first()
    return None


class Command(BaseCommand):
    help = 'Backfill Accounting v2 draft source postings for existing billing records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            default='all',
            choices=SOURCE_CHOICES,
            help='Source family to backfill. Defaults to all.',
        )
        parser.add_argument(
            '--from-date',
            default='',
            help='Start date filter in YYYY-MM-DD format.',
        )
        parser.add_argument(
            '--to-date',
            default='',
            help='End date filter in YYYY-MM-DD format.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Maximum records per selected source family. Defaults to no limit.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show matched counts without creating or updating source postings.',
        )

    def _source_sets(self):
        return {
            'invoices': {
                'label': 'Invoices',
                'qs': Invoice.objects.exclude(status__in=['waived', 'voided']).order_by('created_at', 'pk'),
                'date_field': 'created_at',
                'handler': create_invoice_source_draft,
            },
            'payments': {
                'label': 'Payments',
                'qs': Payment.objects.all().order_by('paid_at', 'pk'),
                'date_field': 'paid_at',
                'handler': create_payment_source_draft,
            },
            'advance-applications': {
                'label': 'Advance applications',
                'qs': PaymentAllocation.objects.select_related('payment', 'invoice').order_by('created_at', 'pk'),
                'date_field': 'created_at',
                'handler': create_payment_allocation_advance_application_draft,
            },
            'credit-adjustments': {
                'label': 'Credit adjustments',
                'qs': AccountCreditAdjustment.objects.order_by('effective_at', 'pk'),
                'date_field': 'effective_at',
                'handler': create_credit_adjustment_source_draft,
            },
            'waivers': {
                'label': 'Invoice waivers',
                'qs': Invoice.objects.filter(status='waived').order_by('voided_at', 'pk'),
                'date_field': 'voided_at',
                'handler': create_invoice_waiver_source_draft,
            },
            'voids': {
                'label': 'Invoice voids',
                'qs': Invoice.objects.filter(status='voided').order_by('voided_at', 'pk'),
                'date_field': 'voided_at',
                'handler': create_invoice_void_source_draft,
            },
        }

    def _run_source_set(self, key, config, start_date, end_date, limit, dry_run):
        qs = _apply_date_filter(config['qs'], config['date_field'], start_date, end_date)
        matched = qs.count()
        to_process = min(matched, limit) if limit else matched
        if dry_run:
            self.stdout.write(f"{config['label']}: {to_process} matched")
            return Counter(matched=to_process)

        records = list(qs[:limit]) if limit else qs.iterator(chunk_size=200)
        counts = Counter(matched=to_process)
        for source in records:
            try:
                result = config['handler'](source)
            except Exception as exc:
                counts['errors'] += 1
                self.stderr.write(f"{key}: {source.pk} failed: {exc}")
                continue

            posting = _posting_from_result(result)
            status = posting.status if posting else getattr(result, 'status', 'unknown')
            counts[status or 'unknown'] += 1
        return counts

    def handle(self, *args, **options):
        start_date = _parse_date(options['from_date'])
        end_date = _parse_date(options['to_date'])
        if start_date and end_date and end_date < start_date:
            raise CommandError('--to-date cannot be before --from-date.')
        limit = max(options['limit'] or 0, 0)
        selected = SOURCE_CHOICES[1:] if options['source'] == 'all' else [options['source']]
        source_sets = self._source_sets()

        grand_total = Counter()
        for key in selected:
            counts = self._run_source_set(
                key,
                source_sets[key],
                start_date,
                end_date,
                limit,
                options['dry_run'],
            )
            grand_total.update(counts)
            if not options['dry_run']:
                self.stdout.write(
                    f"{source_sets[key]['label']}: "
                    f"{counts['matched']} matched, "
                    f"{counts['draft']} draft, "
                    f"{counts['posted']} posted, "
                    f"{counts['blocked']} blocked, "
                    f"{counts['skipped']} skipped, "
                    f"{counts['errors']} errors"
                )

        label = 'Dry run complete' if options['dry_run'] else 'Backfill complete'
        self.stdout.write(self.style.SUCCESS(
            f"{label}: {grand_total['matched']} matched, "
            f"{grand_total['draft']} draft, "
            f"{grand_total['posted']} posted, "
            f"{grand_total['blocked']} blocked, "
            f"{grand_total['skipped']} skipped, "
            f"{grand_total['errors']} errors"
        ))
