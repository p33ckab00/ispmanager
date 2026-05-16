from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.backups.forms import BackupImportValidationForm, ProductionRestorePlanForm
from apps.backups.models import BackupJob, ProductionRestorePlan
from apps.backups.services import (
    BackupError,
    backup_download_path,
    cleanup_backup_retention,
    delete_backup_file,
    get_or_create_production_restore_plan,
    partial_backup_profile_options,
    production_restore_preflight,
    production_restore_plan_status,
    run_full_database_backup,
    run_partial_database_backup,
    run_restore_test,
    save_production_restore_plan,
    validate_backup_upload,
    verify_backup_file,
)
from apps.core.models import AuditLog
from apps.settings_app.models import BackupSettings


def _require_backup_permission(user, permission):
    if user.is_superuser or user.has_perm(permission):
        return
    raise PermissionDenied


@login_required
def dashboard(request):
    _require_backup_permission(request.user, 'backups.view_backupjob')
    backup_settings = BackupSettings.get_settings()
    jobs = BackupJob.objects.select_related('created_by').all()[:50]
    latest_success = BackupJob.objects.filter(
        job_type='export',
        status='completed',
    ).order_by('-completed_at', '-created_at').first()
    latest_failure = BackupJob.objects.filter(
        job_type='export',
        status='failed',
    ).order_by('-completed_at', '-created_at').first()
    latest_restore_test = BackupJob.objects.filter(
        job_type='restore_test',
    ).order_by('-completed_at', '-created_at').first()
    running_job = BackupJob.objects.filter(status='running', job_type='export').order_by('-started_at').first()
    running_restore_test = BackupJob.objects.filter(
        status='running',
        job_type='restore_test',
    ).order_by('-started_at').first()
    return render(request, 'backups/dashboard.html', {
        'backup_settings': backup_settings,
        'jobs': jobs,
        'latest_success': latest_success,
        'latest_failure': latest_failure,
        'latest_restore_test': latest_restore_test,
        'running_job': running_job,
        'running_restore_test': running_restore_test,
        'can_run_full_backup': (
            backup_settings.manual_backups_enabled
            and not running_job
            and (
                request.user.is_superuser
                or request.user.has_perm('backups.run_database_backup')
            )
        ),
        'partial_backup_profiles': partial_backup_profile_options(),
        'import_validation_form': BackupImportValidationForm(),
        'can_run_partial_backups': (
            backup_settings.manual_backups_enabled
            and backup_settings.partial_backups_enabled
            and not running_job
            and (
                request.user.is_superuser
                or request.user.has_perm('backups.run_database_backup')
            )
        ),
        'can_download_backups': (
            backup_settings.allow_backup_download
            and (
                request.user.is_superuser
                or request.user.has_perm('backups.download_database_backup')
            )
        ),
        'can_delete_backups': (
            backup_settings.allow_backup_delete
            and (
                request.user.is_superuser
                or request.user.has_perm('backups.delete_database_backup')
            )
        ),
        'can_validate_imports': (
            request.user.is_superuser
            or request.user.has_perm('backups.validate_database_backup')
        ),
        'can_run_restore_tests': (
            backup_settings.restore_test_enabled
            and not running_job
            and not running_restore_test
            and (
                request.user.is_superuser
                or request.user.has_perm('backups.run_restore_test')
            )
        ),
        'can_view_production_restore_preflight': request.user.is_superuser,
    })


@login_required
@require_POST
def run_full_backup(request):
    _require_backup_permission(request.user, 'backups.run_database_backup')
    try:
        job = run_full_database_backup(user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Full database backup completed: {job.file_name}")
    return redirect('backups-dashboard')


@login_required
@require_POST
def run_partial_backup(request, profile):
    _require_backup_permission(request.user, 'backups.run_database_backup')
    try:
        job = run_partial_database_backup(profile=profile, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{job.get_profile_display()} backup completed: {job.file_name}")
    return redirect('backups-dashboard')


@login_required
@require_POST
def validate_backup_upload_view(request):
    _require_backup_permission(request.user, 'backups.validate_database_backup')
    form = BackupImportValidationForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('backups-dashboard')
    try:
        job = validate_backup_upload(form.cleaned_data['file'], user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Backup file validated: {job.file_name}")
    return redirect('backups-dashboard')


@login_required
@require_POST
def run_restore_test_view(request, pk):
    _require_backup_permission(request.user, 'backups.run_restore_test')
    source_job = get_object_or_404(BackupJob, pk=pk)
    try:
        job = run_restore_test(source_job, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Restore test completed for {source_job.file_name}.")
    return redirect('backups-dashboard')


@login_required
def production_restore_preflight_view(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    source_job = get_object_or_404(BackupJob, pk=pk)
    context = production_restore_preflight(source_job)
    context['existing_plan'] = ProductionRestorePlan.objects.filter(
        source_backup_job=source_job,
        source_checksum_sha256=source_job.checksum_sha256,
    ).order_by('-updated_at', '-created_at').first()
    return render(request, 'backups/production_restore_preflight.html', context)


@login_required
@require_POST
def create_production_restore_plan_view(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    source_job = get_object_or_404(BackupJob, pk=pk)
    try:
        plan, created = get_or_create_production_restore_plan(source_job, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
        return redirect('backups-production-restore-preflight', pk=source_job.pk)
    if created:
        messages.success(request, 'Production restore plan draft created.')
    else:
        messages.info(request, 'Opened the existing production restore plan for this backup checksum.')
    return redirect('backups-production-restore-plan', pk=plan.pk)


@login_required
def production_restore_plan_view(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    plan = get_object_or_404(
        ProductionRestorePlan.objects.select_related('source_backup_job', 'created_by', 'updated_by'),
        pk=pk,
    )
    if request.method == 'POST':
        form = ProductionRestorePlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            status = save_production_restore_plan(plan, user=request.user)
            AuditLog.log(
                'update',
                'backups',
                f"Production restore plan #{plan.pk} saved with status {plan.status}",
                user=request.user,
            )
            if status['ready']:
                messages.success(request, 'Production restore plan is ready for a future execution slice.')
            else:
                messages.success(request, 'Production restore plan draft saved.')
            return redirect('backups-production-restore-plan', pk=plan.pk)
    else:
        form = ProductionRestorePlanForm(instance=plan)
    status = production_restore_plan_status(plan)
    return render(request, 'backups/production_restore_plan.html', {
        'plan': plan,
        'form': form,
        **status,
    })


@login_required
@require_POST
def cleanup_retention(request):
    _require_backup_permission(request.user, 'backups.delete_database_backup')
    try:
        result = cleanup_backup_retention(user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Retention cleanup complete: {len(result['deleted'])} deleted, {len(result['skipped'])} skipped.",
        )
    return redirect('backups-dashboard')


@login_required
def download_backup(request, pk):
    _require_backup_permission(request.user, 'backups.download_database_backup')
    job = get_object_or_404(BackupJob, pk=pk)
    try:
        path = backup_download_path(job, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
        return redirect('backups-dashboard')
    return FileResponse(
        path.open('rb'),
        as_attachment=True,
        filename=job.file_name or path.name,
        content_type='application/octet-stream',
    )


@login_required
@require_POST
def verify_backup(request, pk):
    _require_backup_permission(request.user, 'backups.view_backupjob')
    job = get_object_or_404(BackupJob, pk=pk)
    try:
        result = verify_backup_file(job, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        if result['matches_recorded_checksum']:
            messages.success(request, f"Checksum verified for {job.file_name}.")
        else:
            messages.error(request, f"Checksum mismatch for {job.file_name}.")
    return redirect('backups-dashboard')


@login_required
@require_POST
def delete_backup(request, pk):
    _require_backup_permission(request.user, 'backups.delete_database_backup')
    job = get_object_or_404(BackupJob, pk=pk)
    try:
        delete_backup_file(job, user=request.user)
    except BackupError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Backup file deleted: {job.file_name}")
    return redirect('backups-dashboard')
