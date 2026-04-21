from django_apscheduler.jobstores import DjangoJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)
_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone='Asia/Manila')
        _scheduler.add_jobstore(DjangoJobStore(), 'default')
    return _scheduler


def job_generate_invoices():
    from apps.billing.services import generate_invoices_for_all
    from apps.notifications.telegram import notify_event
    from apps.settings_app.models import BillingSettings
    try:
        settings = BillingSettings.get_settings()
        if not settings.enable_auto_generate:
            return
        created, skipped, errors = generate_invoices_for_all()
        notify_event('billing_generated', 'Invoices Generated',
                     f"Auto-generated {created} invoices. Skipped: {skipped}.")
        logger.info(f"Invoices: {created} created, {skipped} skipped")
    except Exception as e:
        logger.error(f"job_generate_invoices error: {e}")
        notify_event('api_error', 'Scheduler Error', f"Invoice generation failed: {e}")


def job_generate_snapshots():
    from apps.billing.services import generate_snapshot_for_subscriber
    from apps.subscribers.models import Subscriber
    from apps.settings_app.models import BillingSettings
    from datetime import date
    try:
        settings = BillingSettings.get_settings()
        if settings.billing_snapshot_mode == 'manual':
            return
        today = date.today()
        subs = Subscriber.objects.filter(
            status__in=['active', 'suspended'],
            cutoff_day=today.day,
        )
        created = 0
        for sub in subs:
            existing = sub.billing_snapshots.filter(cutoff_date=today).first()
            if not existing:
                generate_snapshot_for_subscriber(sub, settings)
                created += 1
        logger.info(f"Snapshots generated: {created}")
    except Exception as e:
        logger.error(f"job_generate_snapshots error: {e}")


def job_auto_freeze_drafts():
    from apps.billing.models import BillingSnapshot
    from apps.settings_app.models import BillingSettings
    from django.utils import timezone
    from datetime import timedelta
    try:
        settings = BillingSettings.get_settings()
        if settings.billing_snapshot_mode != 'draft':
            return
        cutoff_time = timezone.now() - timedelta(hours=settings.draft_auto_freeze_hours)
        drafts = BillingSnapshot.objects.filter(status='draft', created_at__lte=cutoff_time)
        count = 0
        for draft in drafts:
            draft.freeze(frozen_by='auto_scheduler')
            count += 1
        if count:
            logger.info(f"Auto-froze {count} draft snapshots")
    except Exception as e:
        logger.error(f"job_auto_freeze_drafts error: {e}")


def job_send_billing_sms():
    from apps.sms.services import send_bulk_billing_sms
    from apps.notifications.telegram import notify_event
    from apps.settings_app.models import SMSSettings
    try:
        settings = SMSSettings.get_settings()
        if not settings.enable_billing_sms:
            return
        results = send_bulk_billing_sms(sent_by='scheduler')
        sent = sum(1 for r in results if r['ok'])
        failed = sum(1 for r in results if not r['ok'])
        notify_event('sms_sent', 'Billing SMS Sent',
                     f"Scheduled billing SMS: {sent} sent, {failed} failed.")
    except Exception as e:
        logger.error(f"job_send_billing_sms error: {e}")


def job_mark_overdue():
    from apps.billing.services import mark_overdue_invoices
    try:
        count = mark_overdue_invoices()
        if count > 0:
            logger.info(f"Marked {count} invoices as overdue")
    except Exception as e:
        logger.error(f"job_mark_overdue error: {e}")


def job_sample_usage():
    from apps.subscribers.services import sample_subscriber_usage, purge_old_usage_samples
    from apps.routers.models import Router
    try:
        routers = Router.objects.filter(is_active=True, status='online')
        total = 0
        for router in routers:
            total += sample_subscriber_usage(router)
        purge_old_usage_samples()
        if total:
            logger.debug(f"Usage sampled: {total} sessions")
    except Exception as e:
        logger.error(f"job_sample_usage error: {e}")


def job_sync_router_status():
    from apps.routers.models import Router
    from apps.routers import mikrotik
    from apps.notifications.telegram import notify_event
    from django.utils import timezone
    routers = Router.objects.filter(is_active=True)
    for router in routers:
        old_status = router.status
        try:
            mikrotik.get_system_identity(router)
            if old_status != 'online':
                router.status = 'online'
                router.last_seen = timezone.now()
                router.save(update_fields=['status', 'last_seen'])
                notify_event('router_status', 'Router Online', f"{router.name} is back online.")
        except Exception:
            if old_status != 'offline':
                router.status = 'offline'
                router.save(update_fields=['status'])
                notify_event('router_status', 'Router Offline',
                             f"{router.name} ({router.host}) is not reachable.")


def job_auto_archive():
    from apps.subscribers.models import Subscriber
    from apps.subscribers.services import archive_subscriber
    from apps.settings_app.models import SubscriberSettings
    from datetime import timedelta
    try:
        settings = SubscriberSettings.get_settings()
        cutoff = date.today() - timedelta(days=settings.archive_after_days)
        subs = Subscriber.objects.filter(
            status__in=['disconnected', 'deceased'],
        ).filter(
            models.Q(disconnected_date__lte=cutoff) | models.Q(deceased_date__lte=cutoff)
        )
        for sub in subs:
            archive_subscriber(sub)
    except Exception as e:
        logger.error(f"job_auto_archive error: {e}")


def start_scheduler():
    from apps.settings_app.models import UsageSettings
    scheduler = get_scheduler()
    if scheduler.running:
        return

    scheduler.add_job(job_mark_overdue, CronTrigger(hour=0, minute=5),
                      id='mark_overdue', name='Mark Overdue Invoices',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_generate_invoices, CronTrigger(hour=0, minute=10),
                      id='generate_invoices', name='Auto Generate Invoices',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_generate_snapshots, CronTrigger(hour=0, minute=15),
                      id='generate_snapshots', name='Generate Billing Snapshots',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_auto_freeze_drafts, CronTrigger(hour='*/1'),
                      id='auto_freeze_drafts', name='Auto-Freeze Draft Snapshots',
                      replace_existing=True, misfire_grace_time=300)

    scheduler.add_job(job_send_billing_sms, CronTrigger(hour=8, minute=0),
                      id='billing_sms', name='Send Billing SMS',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_sync_router_status, CronTrigger(minute='*/5'),
                      id='router_status_check', name='Router Status Check',
                      replace_existing=True, misfire_grace_time=60)

    scheduler.add_job(job_sample_usage, IntervalTrigger(minutes=5),
                      id='sample_usage', name='Sample Subscriber Usage',
                      replace_existing=True, misfire_grace_time=60)

    scheduler.add_job(job_auto_archive, CronTrigger(hour=2, minute=0),
                      id='auto_archive', name='Auto Archive Subscribers',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.start()
    logger.info("Scheduler started with all jobs.")
