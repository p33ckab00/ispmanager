from django_apscheduler.jobstores import DjangoJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging
from datetime import date
from django.db import models
from django.conf import settings

logger = logging.getLogger(__name__)
_scheduler = None


def using_sqlite():
    return settings.DATABASES['default']['ENGINE'].endswith('sqlite3')


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone='Asia/Manila')
        if not using_sqlite():
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


def job_sample_router_traffic():
    from apps.routers.models import Router
    from apps.routers.services import sample_router_traffic
    routers = Router.objects.filter(is_active=True, status='online')
    sampled = 0
    for router in routers:
        try:
            sampled += sample_router_traffic(router)
        except Exception as e:
            logger.error(f"job_sample_router_traffic error on {router.name}: {e}")
    if sampled:
        logger.debug("Router telemetry cached for %s interfaces", sampled)


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


def job_auto_suspend_overdue():
    from apps.billing.models import Invoice
    from apps.settings_app.models import BillingSettings
    from apps.subscribers.models import Subscriber
    from apps.subscribers.services import suspend_subscriber

    settings = BillingSettings.get_settings()
    if not settings.enable_auto_disconnect:
        return

    overdue_subscribers = Subscriber.objects.filter(
        status='active',
        invoices__status='overdue',
    ).distinct()

    suspended = 0
    for subscriber in overdue_subscribers:
        ok, err = suspend_subscriber(subscriber, suspended_by='scheduler')
        suspended += 1
        if err:
            logger.warning("Auto-suspend updated %s with MikroTik warning: %s", subscriber.username, err)
    if suspended:
        logger.info("Auto-suspended %s overdue subscribers", suspended)


def start_scheduler():
    from apps.settings_app.models import UsageSettings, RouterSettings, SMSSettings
    scheduler = get_scheduler()
    if scheduler.running:
        return
    usage_settings = UsageSettings.get_settings()
    router_settings = RouterSettings.get_settings()
    sms_settings = SMSSettings.get_settings()
    sms_hour, sms_minute = 8, 0
    try:
        hour_text, minute_text = sms_settings.billing_sms_schedule.split(':', 1)
        sms_hour = max(0, min(23, int(hour_text)))
        sms_minute = max(0, min(59, int(minute_text)))
    except Exception:
        logger.warning("Invalid billing SMS schedule '%s'; defaulting to 08:00", sms_settings.billing_sms_schedule)

    scheduler.add_job(job_mark_overdue, CronTrigger(hour=0, minute=5),
                      id='mark_overdue', name='Mark Overdue Invoices',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_auto_suspend_overdue, CronTrigger(minute='*/15'),
                      id='auto_suspend_overdue', name='Auto Suspend Overdue Subscribers',
                      replace_existing=True, misfire_grace_time=300)

    scheduler.add_job(job_generate_invoices, CronTrigger(hour=0, minute=10),
                      id='generate_invoices', name='Auto Generate Invoices',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_generate_snapshots, CronTrigger(hour=0, minute=15),
                      id='generate_snapshots', name='Generate Billing Snapshots',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.add_job(job_auto_freeze_drafts, CronTrigger(hour='*/1'),
                      id='auto_freeze_drafts', name='Auto-Freeze Draft Snapshots',
                      replace_existing=True, misfire_grace_time=300)

    scheduler.add_job(job_send_billing_sms, CronTrigger(hour=sms_hour, minute=sms_minute),
                      id='billing_sms', name='Send Billing SMS',
                      replace_existing=True, misfire_grace_time=3600)

    router_interval = max(1, router_settings.polling_interval_seconds)
    if using_sqlite():
        router_interval = max(router_interval, 15)
    scheduler.add_job(job_sync_router_status, IntervalTrigger(seconds=router_interval),
                      id='router_status_check', name='Router Status Check',
                      replace_existing=True, misfire_grace_time=60)

    scheduler.add_job(job_sample_router_traffic, IntervalTrigger(seconds=router_interval),
                      id='sample_router_traffic', name='Cache Router Interface Traffic',
                      replace_existing=True, misfire_grace_time=max(60, router_interval))

    usage_interval = max(1, usage_settings.sampler_interval_minutes)
    scheduler.add_job(job_sample_usage, IntervalTrigger(minutes=usage_interval),
                      id='sample_usage', name='Sample Subscriber Usage',
                      replace_existing=True, misfire_grace_time=60)

    scheduler.add_job(job_auto_archive, CronTrigger(hour=2, minute=0),
                      id='auto_archive', name='Auto Archive Subscribers',
                      replace_existing=True, misfire_grace_time=3600)

    scheduler.start()
    if router_settings.sync_on_startup and not using_sqlite():
        try:
            job_sync_router_status()
            job_sample_router_traffic()
        except Exception as e:
            logger.warning("Startup sync failed: %s", e)
    logger.info("Scheduler started with all jobs.")
