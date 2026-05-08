import hashlib
import gzip
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings as django_settings
from django.utils import timezone

from apps.backups.models import BackupJob
from apps.core.models import AuditLog
from apps.settings_app.models import BackupSettings


class BackupError(Exception):
    pass


VALIDATION_UPLOAD_MAX_BYTES = 10 * 1024 * 1024 * 1024
ENCRYPTION_PASSPHRASE_ENV = 'BACKUP_ENCRYPTION_PASSPHRASE'


PARTIAL_BACKUP_PROFILES = {
    'business_critical': {
        'label': 'Business Critical',
        'description': 'Subscribers, billing, payments, accounting, core setup, settings, users, and permissions.',
        'app_labels': [
            'auth',
            'contenttypes',
            'core',
            'settings_app',
            'subscribers',
            'billing',
            'accounting',
        ],
    },
    'subscribers': {
        'label': 'Subscribers',
        'description': 'Subscriber records, plans, rate history, router references, users, settings, and permissions.',
        'app_labels': [
            'auth',
            'contenttypes',
            'settings_app',
            'routers',
            'subscribers',
        ],
    },
    'billing_payments': {
        'label': 'Billing and Payments',
        'description': 'Subscribers, invoices, payments, allocations, accounting links, users, settings, and permissions.',
        'app_labels': [
            'auth',
            'contenttypes',
            'settings_app',
            'subscribers',
            'billing',
            'accounting',
        ],
    },
    'accounting': {
        'label': 'Accounting',
        'description': 'Accounting records with subscriber and billing source dependencies.',
        'app_labels': [
            'auth',
            'contenttypes',
            'settings_app',
            'subscribers',
            'billing',
            'accounting',
        ],
    },
    'network_nms': {
        'label': 'Network and NMS',
        'description': 'Routers, interfaces, subscriber network nodes, NMS topology, users, settings, and permissions.',
        'app_labels': [
            'auth',
            'contenttypes',
            'settings_app',
            'routers',
            'subscribers',
            'nms',
        ],
    },
    'settings_content': {
        'label': 'Settings and Content',
        'description': 'System setup, settings, landing content, SMS templates/logs, notifications, users, and permissions.',
        'app_labels': [
            'auth',
            'contenttypes',
            'core',
            'settings_app',
            'landing',
            'sms',
            'notifications',
        ],
    },
}


def partial_backup_profile_options():
    return [
        {
            'value': value,
            'label': config['label'],
            'description': config['description'],
        }
        for value, config in PARTIAL_BACKUP_PROFILES.items()
    ]


def _database_config():
    database = django_settings.DATABASES['default']
    if database.get('ENGINE') != 'django.db.backends.postgresql':
        raise BackupError('Database backup is only supported for PostgreSQL deployments.')
    return database


def resolve_pg_dump_path(configured_path):
    raw_path = (configured_path or 'pg_dump').strip() or 'pg_dump'
    has_directory = os.path.sep in raw_path or (os.path.altsep and os.path.altsep in raw_path)

    if has_directory:
        candidate = Path(raw_path).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise BackupError(
            f"Configured pg_dump path is not executable: {candidate}. "
            "Set Backup & Restore pg_dump path to a valid PostgreSQL client binary."
        )

    found = shutil.which(raw_path)
    if found:
        return found

    candidates = [
        Path('/usr/bin') / raw_path,
        Path('/usr/local/bin') / raw_path,
    ]
    postgres_bin_root = Path('/usr/lib/postgresql')
    if postgres_bin_root.exists():
        candidates.extend(sorted(postgres_bin_root.glob(f'*/bin/{raw_path}'), reverse=True))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise BackupError(
        "PostgreSQL backup tool pg_dump was not found. "
        "Set Backup & Restore pg_dump path to /usr/bin/pg_dump or install postgresql-client."
    )


def resolve_openssl_path():
    found = shutil.which('openssl')
    if found:
        return found

    for candidate in [Path('/usr/bin/openssl'), Path('/usr/local/bin/openssl')]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise BackupError('OpenSSL was not found. Install openssl before enabling encrypted backups.')


def encryption_status():
    try:
        openssl_path = resolve_openssl_path()
        openssl_error = ''
    except BackupError as exc:
        openssl_path = ''
        openssl_error = str(exc)

    passphrase_configured = bool(os.environ.get(ENCRYPTION_PASSPHRASE_ENV))
    ok = bool(openssl_path and passphrase_configured)
    error = ''
    if not openssl_path:
        error = openssl_error
    elif not passphrase_configured:
        error = f"{ENCRYPTION_PASSPHRASE_ENV} is not set in the service environment."

    return {
        'ok': ok,
        'openssl_path': openssl_path,
        'passphrase_configured': passphrase_configured,
        'error': error,
        'env_var': ENCRYPTION_PASSPHRASE_ENV,
    }


def _backup_root(settings):
    root = Path(settings.backup_root).expanduser()
    if not root.is_absolute():
        raise BackupError('Backup root must be an absolute filesystem path.')
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        root.chmod(0o750)
    except OSError:
        pass
    return root


def _ensure_free_space(root, minimum_free_space_mb):
    minimum_bytes = int(minimum_free_space_mb) * 1024 * 1024
    free_bytes = shutil.disk_usage(root).free
    if free_bytes < minimum_bytes:
        raise BackupError(
            f"Backup storage has only {free_bytes // (1024 * 1024)} MB free; "
            f"{minimum_free_space_mb} MB is required."
        )


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _path_within_root(path, root):
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _backup_file_path(job, backup_settings):
    if not job.file_path:
        raise BackupError('This backup job does not have an available file path.')
    root = Path(backup_settings.backup_root).expanduser()
    path = Path(job.file_path).expanduser()
    if not path.is_absolute():
        raise BackupError('Backup file path is not absolute.')
    if not root.exists():
        raise BackupError('Configured backup root does not exist.')
    if not path.exists() or not path.is_file():
        raise BackupError('Backup file is missing from disk.')
    if not _path_within_root(path, root):
        raise BackupError('Backup file path is outside the configured backup root.')
    return path


def _filename(settings, job_id, profile):
    timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d-%H%M%S')
    return f"{settings.filename_prefix}-{profile}-{timestamp}-{job_id}.dump"


def _pg_dump_command(backup_settings, database, output_path, table_names=None):
    command = [
        resolve_pg_dump_path(backup_settings.pg_dump_path),
        '--format=custom',
        '--no-owner',
        '--no-privileges',
        '--file',
        str(output_path),
    ]

    if database.get('HOST'):
        command.extend(['--host', str(database['HOST'])])
    if database.get('PORT'):
        command.extend(['--port', str(database['PORT'])])
    if database.get('USER'):
        command.extend(['--username', str(database['USER'])])

    for table_name in table_names or []:
        command.extend(['--table', table_name])

    command.extend(['--dbname', str(database['NAME'])])
    return command


def _pg_environment(database):
    env = os.environ.copy()
    password = database.get('PASSWORD')
    if password:
        env['PGPASSWORD'] = str(password)
    env.setdefault('PGCONNECT_TIMEOUT', '15')
    return env


def _safe_process_error(process):
    text = (process.stderr or process.stdout or '').strip()
    if not text:
        text = f"pg_dump exited with status {process.returncode}."
    return text[:4000]


def _encrypt_backup_file(source_path, encrypted_temp_path):
    status = encryption_status()
    if not status['ok']:
        raise BackupError(f"Backup encryption is enabled but not ready: {status['error']}")

    env = os.environ.copy()
    process = subprocess.run(
        [
            status['openssl_path'],
            'enc',
            '-aes-256-cbc',
            '-salt',
            '-pbkdf2',
            '-iter',
            '200000',
            '-in',
            str(source_path),
            '-out',
            str(encrypted_temp_path),
            '-pass',
            f'env:{ENCRYPTION_PASSPHRASE_ENV}',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise BackupError(_safe_process_error(process))
    if not encrypted_temp_path.exists() or encrypted_temp_path.stat().st_size <= 0:
        raise BackupError('OpenSSL completed but did not produce a non-empty encrypted backup file.')
    return status


def _detect_backup_format(sample):
    stripped = sample.lstrip()
    if sample.startswith(b'PGDMP'):
        return 'custom'
    sql_markers = (
        b'-- PostgreSQL database dump',
        b'SET ',
        b'CREATE ',
        b'ALTER ',
        b'COPY ',
    )
    if any(stripped.startswith(marker) for marker in sql_markers):
        return 'plain_sql'
    return 'unknown'


def _read_validation_sample(path, compression):
    if compression == 'gzip':
        with gzip.open(path, 'rb') as handle:
            return handle.read(65536)
    with path.open('rb') as handle:
        return handle.read(65536)


def _validate_temp_backup_file(path, filename):
    suffix = filename.lower()
    with path.open('rb') as handle:
        first_bytes = handle.read(8)
    compression = 'gzip' if suffix.endswith('.gz') or first_bytes.startswith(b'\x1f\x8b') else ''
    sample = _read_validation_sample(path, compression)
    if not sample:
        raise BackupError('Uploaded backup file is empty or unreadable.')
    detected_format = _detect_backup_format(sample)
    if detected_format == 'unknown':
        raise BackupError('Uploaded file is readable but does not look like a supported PostgreSQL backup.')
    return {
        'compression': compression,
        'pg_dump_format': detected_format,
    }


def _profile_table_names(profile):
    if profile == 'full':
        return []
    config = PARTIAL_BACKUP_PROFILES.get(profile)
    if not config:
        raise BackupError('Unknown partial backup profile.')

    app_labels = set(config['app_labels'])
    table_names = set()
    for model in django_apps.get_models(include_auto_created=True):
        options = model._meta
        if options.proxy or not options.managed:
            continue
        if options.app_label in app_labels and options.db_table:
            table_names.add(options.db_table)

    if not table_names:
        raise BackupError('Partial backup profile did not resolve to any database tables.')
    return sorted(table_names)


def run_database_backup(profile='full', user=None, trigger='manual'):
    backup_settings = BackupSettings.get_settings()
    if trigger == 'manual' and not backup_settings.manual_backups_enabled:
        raise BackupError('Manual database backups are disabled in Backup & Restore settings.')
    if trigger.startswith('scheduled') and not backup_settings.scheduled_backups_enabled:
        return None
    if trigger == 'scheduled_weekly' and not backup_settings.weekly_backup_enabled:
        return None
    if profile != 'full' and not backup_settings.partial_backups_enabled:
        raise BackupError('Partial database backups are disabled in Backup & Restore settings.')

    if BackupJob.objects.filter(status='running', job_type='export').exists():
        raise BackupError('Another database backup is already running.')

    database = _database_config()
    root = _backup_root(backup_settings)
    _ensure_free_space(root, backup_settings.minimum_free_space_mb)
    table_names = _profile_table_names(profile)

    job = BackupJob.objects.create(
        job_type='export',
        profile=profile,
        status='running',
        pg_dump_format='custom',
        source_database=str(database['NAME']),
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        started_at=timezone.now(),
        summary_json={
            'backup_root': str(root),
            'format': 'custom',
            'owner_privileges_included': False,
            'profile': profile,
            'partial': profile != 'full',
            'trigger': trigger,
            'table_count': len(table_names),
            'tables': table_names,
        },
    )
    filename = _filename(backup_settings, job.pk, profile)
    final_path = root / filename
    temp_path = root / f".{filename}.tmp"
    encrypted_temp_path = root / f".{filename}.enc.tmp"
    job.file_name = filename
    job.file_path = str(final_path)
    job.save(update_fields=['file_name', 'file_path'])

    try:
        if temp_path.exists():
            temp_path.unlink()
        if encrypted_temp_path.exists():
            encrypted_temp_path.unlink()

        process = subprocess.run(
            _pg_dump_command(backup_settings, database, temp_path, table_names=table_names),
            env=_pg_environment(database),
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise BackupError(_safe_process_error(process))
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            raise BackupError('pg_dump completed but did not produce a non-empty backup file.')

        temp_path.replace(final_path)
        try:
            final_path.chmod(0o600)
        except OSError:
            pass

        encryption_summary = {'enabled': False}
        if backup_settings.encryption_enabled:
            encrypted_final_path = root / f"{filename}.enc"
            if encrypted_final_path.exists():
                encrypted_final_path.unlink()
            status = _encrypt_backup_file(final_path, encrypted_temp_path)
            encrypted_temp_path.replace(encrypted_final_path)
            try:
                encrypted_final_path.chmod(0o600)
            except OSError:
                pass
            final_path.unlink()
            final_path = encrypted_final_path
            filename = encrypted_final_path.name
            job.file_name = filename
            job.file_path = str(final_path)
            encryption_summary = {
                'enabled': True,
                'tool': 'openssl',
                'openssl_path': status['openssl_path'],
                'cipher': 'aes-256-cbc',
                'kdf': 'pbkdf2',
                'iterations': 200000,
                'passphrase_env': ENCRYPTION_PASSPHRASE_ENV,
            }

        checksum = _sha256_file(final_path)
        size = final_path.stat().st_size
        completed_at = timezone.now()
        job.status = 'completed'
        job.file_size_bytes = size
        job.checksum_sha256 = checksum
        job.completed_at = completed_at
        job.summary_json = {
            **job.summary_json,
            'completed_at': completed_at.isoformat(),
            'encryption': encryption_summary,
        }
        job.save(update_fields=[
            'file_name',
            'file_path',
            'status',
            'file_size_bytes',
            'checksum_sha256',
            'completed_at',
            'summary_json',
        ])
        AuditLog.log(
            'system',
            'backups',
            f"{job.get_profile_display()} database backup completed: {filename} ({size} bytes)",
            user=user,
        )
        return job
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        if encrypted_temp_path.exists():
            encrypted_temp_path.unlink()
        message = str(exc)
        job.status = 'failed'
        job.error_report = message[:4000]
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_report', 'completed_at'])
        AuditLog.log(
            'system',
            'backups',
            f"{job.get_profile_display()} database backup failed: {message[:500]}",
            user=user,
        )
        if isinstance(exc, BackupError):
            raise
        raise BackupError(message) from exc


def run_full_database_backup(user=None):
    return run_database_backup(profile='full', user=user, trigger='manual')


def run_partial_database_backup(profile, user=None):
    if profile == 'full':
        raise BackupError('Use the full backup action for full database backups.')
    return run_database_backup(profile=profile, user=user, trigger='manual')


def run_scheduled_database_backup(weekly=False):
    backup_settings = BackupSettings.get_settings()
    trigger = 'scheduled_weekly' if weekly else 'scheduled_daily'
    return run_database_backup(
        profile=backup_settings.scheduled_backup_profile,
        user=None,
        trigger=trigger,
    )


def validate_backup_upload(upload, user=None):
    job = BackupJob.objects.create(
        job_type='import_validation',
        profile='full',
        status='running',
        file_name=upload.name,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        started_at=timezone.now(),
        summary_json={
            'validation_only': True,
            'restored_to_database': False,
        },
    )
    temp_path = None
    digest = hashlib.sha256()
    size = 0

    try:
        suffix = ''.join(Path(upload.name).suffixes[-2:]) or Path(upload.name).suffix or '.upload'
        temp = tempfile.NamedTemporaryFile(prefix='ispmanager-backup-validate-', suffix=suffix, delete=False)
        temp_path = Path(temp.name)
        with temp:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > VALIDATION_UPLOAD_MAX_BYTES:
                    raise BackupError('Uploaded backup file exceeds the validation size limit.')
                digest.update(chunk)
                temp.write(chunk)

        if size <= 0:
            raise BackupError('Uploaded backup file is empty.')

        validation = _validate_temp_backup_file(temp_path, upload.name)
        completed_at = timezone.now()
        job.status = 'completed'
        job.file_size_bytes = size
        job.checksum_sha256 = digest.hexdigest()
        job.compression = validation['compression']
        job.pg_dump_format = validation['pg_dump_format']
        job.completed_at = completed_at
        job.summary_json = {
            **job.summary_json,
            'completed_at': completed_at.isoformat(),
            'file_size_bytes': size,
            'checksum_sha256': job.checksum_sha256,
            'compression': job.compression,
            'pg_dump_format': job.pg_dump_format,
        }
        job.save(update_fields=[
            'status',
            'file_size_bytes',
            'checksum_sha256',
            'compression',
            'pg_dump_format',
            'completed_at',
            'summary_json',
        ])
        AuditLog.log(
            'system',
            'backups',
            f"Backup import validation completed: {upload.name}",
            user=user,
        )
        return job
    except Exception as exc:
        message = str(exc)
        job.status = 'failed'
        job.file_size_bytes = size
        job.checksum_sha256 = digest.hexdigest() if size else ''
        job.error_report = message[:4000]
        job.completed_at = timezone.now()
        job.save(update_fields=[
            'status',
            'file_size_bytes',
            'checksum_sha256',
            'error_report',
            'completed_at',
        ])
        AuditLog.log(
            'system',
            'backups',
            f"Backup import validation failed: {message[:500]}",
            user=user,
        )
        if isinstance(exc, BackupError):
            raise
        raise BackupError(message) from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def verify_backup_file(job, user=None):
    if job.status != 'completed':
        raise BackupError('Only completed backup jobs can be verified.')
    backup_settings = BackupSettings.get_settings()
    path = _backup_file_path(job, backup_settings)
    checksum = _sha256_file(path)
    size = path.stat().st_size
    matches = bool(job.checksum_sha256 and checksum == job.checksum_sha256)
    verified_at = timezone.now()
    job.summary_json = {
        **job.summary_json,
        'last_verification': {
            'verified_at': verified_at.isoformat(),
            'checksum_sha256': checksum,
            'file_size_bytes': size,
            'matches_recorded_checksum': matches,
        },
    }
    job.save(update_fields=['summary_json'])
    AuditLog.log(
        'system',
        'backups',
        f"Backup checksum verified for {job.file_name}: {'matched' if matches else 'mismatch'}",
        user=user,
    )
    return {
        'checksum_sha256': checksum,
        'file_size_bytes': size,
        'matches_recorded_checksum': matches,
    }


def backup_download_path(job, user=None):
    if job.status != 'completed':
        raise BackupError('Only completed backup jobs can be downloaded.')
    backup_settings = BackupSettings.get_settings()
    if not backup_settings.allow_backup_download:
        raise BackupError('Backup downloads are disabled in Backup & Restore settings.')
    path = _backup_file_path(job, backup_settings)
    AuditLog.log(
        'system',
        'backups',
        f"Backup file downloaded: {job.file_name}",
        user=user,
    )
    return path


def delete_backup_file(job, user=None):
    if job.status != 'completed':
        raise BackupError('Only completed backup jobs can be deleted.')
    backup_settings = BackupSettings.get_settings()
    if not backup_settings.allow_backup_delete:
        raise BackupError('Backup deletes are disabled in Backup & Restore settings.')
    path = _backup_file_path(job, backup_settings)
    path.unlink()
    deleted_at = timezone.now()
    job.summary_json = {
        **job.summary_json,
        'deleted_at': deleted_at.isoformat(),
        'deleted_file_path': str(path),
        'deleted_by': getattr(user, 'username', '') if user else '',
    }
    job.file_path = ''
    job.save(update_fields=['file_path', 'summary_json'])
    AuditLog.log(
        'system',
        'backups',
        f"Backup file deleted: {job.file_name}",
        user=user,
    )
    return job


def cleanup_backup_retention(user=None):
    backup_settings = BackupSettings.get_settings()
    keep_count = max(1, int(backup_settings.retention_keep_last))
    candidates = list(
        BackupJob.objects.filter(
            job_type='export',
            status='completed',
        )
        .exclude(file_path='')
        .order_by('-completed_at', '-created_at', '-pk')
    )
    protected = candidates[:keep_count]
    cleanup_candidates = candidates[keep_count:]
    deleted = []
    skipped = []

    for job in cleanup_candidates:
        if job.summary_json.get('deleted_at'):
            skipped.append({'job_id': job.pk, 'file_name': job.file_name, 'reason': 'already deleted'})
            continue
        try:
            path = _backup_file_path(job, backup_settings)
        except BackupError as exc:
            skipped.append({'job_id': job.pk, 'file_name': job.file_name, 'reason': str(exc)})
            continue
        path.unlink()
        deleted_at = timezone.now()
        job.summary_json = {
            **job.summary_json,
            'deleted_at': deleted_at.isoformat(),
            'deleted_file_path': str(path),
            'deleted_by': getattr(user, 'username', '') if user else '',
            'deleted_reason': 'retention_cleanup',
        }
        job.file_path = ''
        job.save(update_fields=['file_path', 'summary_json'])
        deleted.append({'job_id': job.pk, 'file_name': job.file_name})

    AuditLog.log(
        'system',
        'backups',
        f"Backup retention cleanup completed: deleted={len(deleted)} skipped={len(skipped)} keep={len(protected)}",
        user=user,
    )
    return {
        'deleted': deleted,
        'skipped': skipped,
        'kept_count': len(protected),
        'retention_keep_last': keep_count,
    }
