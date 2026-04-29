from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.settings_app.models import BillingSettings, SMSSettings, TelegramSettings, RouterSettings
from apps.settings_app.forms import (
    SystemInfoForm, BillingSettingsForm, SMSSettingsForm,
    TelegramSettingsForm, RouterSettingsForm
)
from apps.core.models import SystemSetup, AuditLog

NAV_ITEMS = [
    ('/settings/system/', 'System Info', 'fa-building', 'system'),
    ('/settings/billing/', 'Billing', 'fa-file-invoice-dollar', 'billing'),
    ('/settings/sms/', 'SMS', 'fa-sms', 'sms'),
    ('/settings/telegram/', 'Telegram', 'fa-paper-plane', 'telegram'),
    ('/settings/router/', 'Router', 'fa-router', 'router'),
    ('/settings/subscriber/', 'Subscriber', 'fa-users', 'subscriber'),
    ('/settings/usage/', 'Usage Tracking', 'fa-chart-bar', 'usage'),
]

TELEGRAM_NOTIFY_FIELDS = [
    ('notify_new_subscriber', 'New subscriber added'),
    ('notify_subscriber_status_change', 'Subscriber status changed'),
    ('notify_router_status', 'Router connected / disconnected'),
    ('notify_billing_generated', 'Billing snapshot generated'),
    ('notify_payment_received', 'Payment recorded'),
    ('notify_sms_sent', 'SMS sent'),
    ('notify_plan_change', 'Plan or rate changed'),
    ('notify_settings_change', 'Settings changed'),
    ('notify_api_errors', 'MikroTik API errors'),
]

def _ctx(active):
    return {'nav_items': NAV_ITEMS, 'active': active}


@login_required
def settings_index(request):
    return redirect('settings-system-info')


@login_required
def system_info(request):
    setup = SystemSetup.get_setup()
    if request.method == 'POST':
        form = SystemInfoForm(request.POST, request.FILES, instance=setup)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'settings', 'System info updated', user=request.user)
            messages.success(request, 'System information updated.')
            return redirect('settings-system-info')
    else:
        form = SystemInfoForm(instance=setup)
    ctx = _ctx('system')
    ctx['form'] = form
    return render(request, 'settings_app/system_info.html', ctx)


@login_required
def billing_settings(request):
    obj = BillingSettings.get_settings()
    if request.method == 'POST':
        form = BillingSettingsForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'settings', 'Billing settings updated', user=request.user)
            messages.success(request, 'Billing settings saved.')
            return redirect('settings-billing')
    else:
        form = BillingSettingsForm(instance=obj)
    ctx = _ctx('billing')
    ctx['form'] = form
    return render(request, 'settings_app/billing_settings.html', ctx)


@login_required
def sms_settings(request):
    obj = SMSSettings.get_settings()
    if request.method == 'POST':
        form = SMSSettingsForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'settings', 'SMS settings updated', user=request.user)
            messages.success(request, 'SMS settings saved.')
            return redirect('settings-sms')
    else:
        form = SMSSettingsForm(instance=obj)
    ctx = _ctx('sms')
    ctx['form'] = form
    return render(request, 'settings_app/sms_settings.html', ctx)


@login_required
def telegram_settings(request):
    obj = TelegramSettings.get_settings()
    if request.method == 'POST':
        form = TelegramSettingsForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'settings', 'Telegram settings updated', user=request.user)
            messages.success(request, 'Telegram settings saved.')
            return redirect('settings-telegram')
    else:
        form = TelegramSettingsForm(instance=obj)
    notify_values = {f: getattr(obj, f) for f, _ in TELEGRAM_NOTIFY_FIELDS}
    ctx = _ctx('telegram')
    ctx.update({'form': form, 'notify_fields': TELEGRAM_NOTIFY_FIELDS, 'notify_values': notify_values})
    return render(request, 'settings_app/telegram_settings.html', ctx)


@login_required
def router_settings(request):
    obj = RouterSettings.get_settings()
    if request.method == 'POST':
        form = RouterSettingsForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            AuditLog.log('update', 'settings', 'Router settings updated', user=request.user)
            messages.success(request, 'Router settings saved.')
            return redirect('settings-router')
    else:
        form = RouterSettingsForm(instance=obj)
    ctx = _ctx('router')
    ctx['form'] = form
    return render(request, 'settings_app/router_settings.html', ctx)


@login_required
def subscriber_settings(request):
    from apps.settings_app.models import SubscriberSettings
    obj = SubscriberSettings.get_settings()
    if request.method == 'POST':
        obj.mikrotik_auto_suspend = 'mikrotik_auto_suspend' in request.POST
        obj.mikrotik_auto_reconnect = 'mikrotik_auto_reconnect' in request.POST
        obj.auto_reconnect_after_full_payment = 'auto_reconnect_after_full_payment' in request.POST
        disconnected_policy = request.POST.get('disconnected_billing_policy', 'preserve_balance')
        allowed_policies = {choice[0] for choice in SubscriberSettings.DISCONNECTED_BILLING_POLICY_CHOICES}
        obj.disconnected_billing_policy = (
            disconnected_policy
            if disconnected_policy in allowed_policies
            else 'preserve_balance'
        )
        credit_policy = request.POST.get('disconnected_credit_policy', 'preserve_credit')
        allowed_credit_policies = {choice[0] for choice in SubscriberSettings.DISCONNECTED_CREDIT_POLICY_CHOICES}
        obj.disconnected_credit_policy = (
            credit_policy
            if credit_policy in allowed_credit_policies
            else 'preserve_credit'
        )
        obj.archive_after_days = int(request.POST.get('archive_after_days', 90))
        obj.save()
        AuditLog.log('update', 'settings', 'Subscriber settings updated', user=request.user)
        messages.success(request, 'Subscriber settings saved.')
        return redirect('settings-subscriber')
    ctx = _ctx('subscriber')
    ctx['obj'] = obj
    return render(request, 'settings_app/subscriber_settings.html', ctx)


@login_required
def usage_settings(request):
    from apps.settings_app.models import UsageSettings
    obj = UsageSettings.get_settings()
    if request.method == 'POST':
        obj.enabled = 'enabled' in request.POST
        obj.sampler_interval_minutes = int(request.POST.get('sampler_interval_minutes', 5))
        obj.raw_retention_days = int(request.POST.get('raw_retention_days', 14))
        obj.daily_retention_days = int(request.POST.get('daily_retention_days', 365))
        obj.cutoff_snapshot_enabled = 'cutoff_snapshot_enabled' in request.POST
        obj.save()
        AuditLog.log('update', 'settings', 'Usage settings updated', user=request.user)
        messages.success(request, 'Usage settings saved.')
        return redirect('settings-usage')
    ctx = _ctx('usage')
    ctx['obj'] = obj
    return render(request, 'settings_app/usage_settings.html', ctx)
