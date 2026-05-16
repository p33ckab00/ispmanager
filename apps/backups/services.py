import hashlib
import gzip
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from django.apps import apps as django_apps
from django.conf import settings as django_settings
from django.db import connection
from django.utils import timezone

from apps.backups.models import BackupJob, ProductionRestorePlan
from apps.core.models import AuditLog
from apps.settings_app.models import BackupSettings


class BackupError(Exception):
    pass


VALIDATION_UPLOAD_MAX_BYTES = 10 * 1024 * 1024 * 1024
ENCRYPTION_PASSPHRASE_ENV = 'BACKUP_ENCRYPTION_PASSPHRASE'
REMOTE_SFTP_HOST_ENV = 'BACKUP_REMOTE_SFTP_HOST'
REMOTE_SFTP_USER_ENV = 'BACKUP_REMOTE_SFTP_USER'
REMOTE_SFTP_DIR_ENV = 'BACKUP_REMOTE_SFTP_DIR'
REMOTE_SFTP_PORT_ENV = 'BACKUP_REMOTE_SFTP_PORT'
REMOTE_SFTP_KEY_ENV = 'BACKUP_REMOTE_SFTP_KEY'
REMOTE_SFTP_KNOWN_HOSTS_ENV = 'BACKUP_REMOTE_SFTP_KNOWN_HOSTS'
RESTORE_TEST_MAINTENANCE_DB_ENV = 'BACKUP_RESTORE_TEST_MAINTENANCE_DB'


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


RESTORE_TEST_KEY_MODELS = [
    ('core', 'SystemSetup', 'System setup'),
    ('subscribers', 'Subscriber', 'Subscribers'),
    ('billing', 'Invoice', 'Invoices'),
    ('billing', 'Payment', 'Payments'),
    ('billing', 'PaymentAllocation', 'Payment allocations'),
    ('billing', 'BillingSnapshot', 'Billing snapshots'),
    ('accounting', 'IncomeRecord', 'Income records'),
    ('accounting', 'ExpenseRecord', 'Expense records'),
    ('routers', 'Router', 'Routers'),
    ('subscribers', 'NetworkNode', 'Network nodes'),
]


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


def resolve_postgres_tool_path(tool_name, backup_settings=None):
    backup_settings = backup_settings or BackupSettings.get_settings()
    if tool_name == 'pg_dump':
        return resolve_pg_dump_path(backup_settings.pg_dump_path)

    candidates = []
    try:
        candidates.append(Path(resolve_pg_dump_path(backup_settings.pg_dump_path)).with_name(tool_name))
    except BackupError:
        pass

    found = shutil.which(tool_name)
    if found:
        candidates.append(Path(found))

    candidates.extend([
        Path('/usr/bin') / tool_name,
        Path('/usr/local/bin') / tool_name,
    ])
    postgres_bin_root = Path('/usr/lib/postgresql')
    if postgres_bin_root.exists():
        candidates.extend(sorted(postgres_bin_root.glob(f'*/bin/{tool_name}'), reverse=True))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise BackupError(
        f"PostgreSQL restore-test tool {tool_name} was not found. "
        "Install postgresql-client before enabling restore tests."
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


def restore_test_status(backup_settings=None):
    backup_settings = backup_settings or BackupSettings.get_settings()
    status = {
        'enabled': backup_settings.restore_test_enabled,
        'ok': False,
        'ready': False,
        'error': '',
        'maintenance_database': '',
        'can_create_database': False,
        'tools': {},
        'env_var': RESTORE_TEST_MAINTENANCE_DB_ENV,
    }
    if not backup_settings.restore_test_enabled:
        status.update({'ok': True, 'error': 'Restore tests are disabled.'})
        return status

    try:
        _database_config()
        tools = {
            tool_name: resolve_postgres_tool_path(tool_name, backup_settings)
            for tool_name in ('pg_restore', 'createdb', 'dropdb')
        }
        maintenance_database = _clean_env_value(RESTORE_TEST_MAINTENANCE_DB_ENV) or 'postgres'
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(rolcreatedb OR rolsuper, FALSE)
                FROM pg_roles
                WHERE rolname = current_user
                """
            )
            row = cursor.fetchone()
        can_create_database = bool(row and row[0])
        if not can_create_database:
            raise BackupError(
                'Restore tests require the configured PostgreSQL role to have CREATEDB capability.'
            )
        status.update({
            'ok': True,
            'ready': True,
            'maintenance_database': maintenance_database,
            'can_create_database': can_create_database,
            'tools': tools,
        })
    except Exception as exc:
        status['error'] = str(exc)
    return status


def _resolve_sftp_path():
    found = shutil.which('sftp')
    if found:
        return found

    for candidate in [Path('/usr/bin/sftp'), Path('/usr/local/bin/sftp')]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise BackupError('OpenSSH sftp was not found. Install openssh-client before enabling SFTP remote copy.')


def _clean_env_value(name):
    value = (os.environ.get(name) or '').strip()
    if any(char in value for char in ('\x00', '\n', '\r')):
        raise BackupError(f'{name} contains an unsupported control character.')
    return value


def _sftp_batch_quote(value):
    if any(char in value for char in ('\x00', '\n', '\r')):
        raise BackupError('SFTP path contains an unsupported control character.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def remote_copy_status(backup_settings=None):
    backup_settings = backup_settings or BackupSettings.get_settings()
    status = {
        'enabled': backup_settings.remote_copy_enabled,
        'backend': backup_settings.remote_backend,
        'ok': False,
        'ready': False,
        'error': '',
        'sftp_path': '',
        'host': '',
        'user': '',
        'remote_dir': '',
        'port': '',
        'key_configured': False,
        'known_hosts_configured': False,
        'env_vars': {
            'host': REMOTE_SFTP_HOST_ENV,
            'user': REMOTE_SFTP_USER_ENV,
            'remote_dir': REMOTE_SFTP_DIR_ENV,
            'port': REMOTE_SFTP_PORT_ENV,
            'key': REMOTE_SFTP_KEY_ENV,
            'known_hosts': REMOTE_SFTP_KNOWN_HOSTS_ENV,
        },
    }

    if not backup_settings.remote_copy_enabled:
        status.update({'ok': True, 'error': 'Remote copy is disabled.'})
        return status
    if backup_settings.remote_backend == 'none':
        status['error'] = 'Remote copy is enabled but remote backend is set to None.'
        return status
    if backup_settings.remote_backend != 'sftp':
        status['error'] = f"Remote backend {backup_settings.remote_backend} is not implemented yet."
        return status

    try:
        sftp_path = _resolve_sftp_path()
        host = _clean_env_value(REMOTE_SFTP_HOST_ENV)
        user = _clean_env_value(REMOTE_SFTP_USER_ENV)
        remote_dir = _clean_env_value(REMOTE_SFTP_DIR_ENV)
        port_value = _clean_env_value(REMOTE_SFTP_PORT_ENV) or '22'
        key_path = _clean_env_value(REMOTE_SFTP_KEY_ENV)
        known_hosts_path = _clean_env_value(REMOTE_SFTP_KNOWN_HOSTS_ENV)

        missing = [
            env_name
            for env_name, env_value in [
                (REMOTE_SFTP_HOST_ENV, host),
                (REMOTE_SFTP_USER_ENV, user),
                (REMOTE_SFTP_DIR_ENV, remote_dir),
            ]
            if not env_value
        ]
        if missing:
            raise BackupError(f"Missing required SFTP remote copy environment variable(s): {', '.join(missing)}.")

        try:
            port = int(port_value)
        except ValueError as exc:
            raise BackupError(f'{REMOTE_SFTP_PORT_ENV} must be a TCP port number.') from exc
        if not 1 <= port <= 65535:
            raise BackupError(f'{REMOTE_SFTP_PORT_ENV} must be between 1 and 65535.')

        key_configured = False
        if key_path:
            expanded_key = Path(key_path).expanduser()
            if not expanded_key.is_file() or not os.access(expanded_key, os.R_OK):
                raise BackupError(f'{REMOTE_SFTP_KEY_ENV} does not point to a readable key file.')
            key_configured = True
            key_path = str(expanded_key)

        known_hosts_configured = False
        if known_hosts_path:
            expanded_known_hosts = Path(known_hosts_path).expanduser()
            if not expanded_known_hosts.is_file() or not os.access(expanded_known_hosts, os.R_OK):
                raise BackupError(f'{REMOTE_SFTP_KNOWN_HOSTS_ENV} does not point to a readable known_hosts file.')
            known_hosts_configured = True
            known_hosts_path = str(expanded_known_hosts)

        status.update({
            'ok': True,
            'ready': True,
            'sftp_path': sftp_path,
            'host': host,
            'user': user,
            'remote_dir': remote_dir,
            'port': str(port),
            'key_configured': key_configured,
            'key_path': key_path,
            'known_hosts_configured': known_hosts_configured,
            'known_hosts_path': known_hosts_path,
        })
    except BackupError as exc:
        status['error'] = str(exc)
    return status


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
    try:
        if not root.exists():
            raise BackupError('Configured backup root does not exist.')
        if not path.exists() or not path.is_file():
            raise BackupError('Backup file is missing from disk.')
    except OSError as exc:
        raise BackupError(f'Backup file is not accessible: {exc}') from exc
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


def _safe_process_error(process, tool_name='pg_dump'):
    text = (process.stderr or process.stdout or '').strip()
    if not text:
        text = f"{tool_name} exited with status {process.returncode}."
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
        raise BackupError(_safe_process_error(process, tool_name='openssl'))
    if not encrypted_temp_path.exists() or encrypted_temp_path.stat().st_size <= 0:
        raise BackupError('OpenSSL completed but did not produce a non-empty encrypted backup file.')
    return status


def _decrypt_backup_file(source_path, decrypted_temp_path):
    status = encryption_status()
    if not status['ok']:
        raise BackupError(f"Encrypted restore test is not ready: {status['error']}")

    process = subprocess.run(
        [
            status['openssl_path'],
            'enc',
            '-d',
            '-aes-256-cbc',
            '-pbkdf2',
            '-iter',
            '200000',
            '-in',
            str(source_path),
            '-out',
            str(decrypted_temp_path),
            '-pass',
            f'env:{ENCRYPTION_PASSPHRASE_ENV}',
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise BackupError(_safe_process_error(process, tool_name='openssl'))
    if not decrypted_temp_path.exists() or decrypted_temp_path.stat().st_size <= 0:
        raise BackupError('OpenSSL completed but did not produce a non-empty decrypted backup file.')
    return status


def _copy_backup_remote(local_path, backup_settings):
    status = remote_copy_status(backup_settings)
    started_at = timezone.now()
    summary = {
        'enabled': backup_settings.remote_copy_enabled,
        'backend': backup_settings.remote_backend,
        'status': 'skipped',
        'started_at': started_at.isoformat(),
    }
    if not backup_settings.remote_copy_enabled:
        return summary
    if not status['ok']:
        raise BackupError(status['error'])

    batch_path = None
    try:
        batch = (
            f"cd {_sftp_batch_quote(status['remote_dir'])}\n"
            f"put {_sftp_batch_quote(str(local_path))} {_sftp_batch_quote(local_path.name)}\n"
        )
        batch_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            prefix='ispmanager-backup-sftp-',
            suffix='.batch',
            delete=False,
        )
        batch_path = Path(batch_file.name)
        with batch_file:
            batch_file.write(batch)
        try:
            batch_path.chmod(0o600)
        except OSError:
            pass

        command = [
            status['sftp_path'],
            '-o',
            'BatchMode=yes',
            '-o',
            'StrictHostKeyChecking=yes',
            '-o',
            'ConnectTimeout=20',
        ]
        if status.get('known_hosts_path'):
            command.extend(['-o', f"UserKnownHostsFile={status['known_hosts_path']}"])
        if status.get('key_path'):
            command.extend(['-i', status['key_path'], '-o', 'IdentitiesOnly=yes'])
        command.extend([
            '-P',
            status['port'],
            '-b',
            str(batch_path),
            f"{status['user']}@{status['host']}",
        ])

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if process.returncode != 0:
            raise BackupError(_safe_process_error(process, tool_name='sftp'))
        completed_at = timezone.now()
        return {
            **summary,
            'status': 'completed',
            'completed_at': completed_at.isoformat(),
            'host': status['host'],
            'user': status['user'],
            'remote_dir': status['remote_dir'],
            'remote_file': local_path.name,
            'bytes_sent': local_path.stat().st_size,
        }
    except subprocess.TimeoutExpired as exc:
        raise BackupError('SFTP remote copy timed out after 600 seconds.') from exc
    finally:
        if batch_path and batch_path.exists():
            batch_path.unlink()


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


def _postgres_cli_connection_args(database):
    args = []
    if database.get('HOST'):
        args.extend(['--host', str(database['HOST'])])
    if database.get('PORT'):
        args.extend(['--port', str(database['PORT'])])
    if database.get('USER'):
        args.extend(['--username', str(database['USER'])])
    return args


def _run_postgres_command(command, database, tool_name, timeout):
    try:
        process = subprocess.run(
            command,
            env=_pg_environment(database),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f'{tool_name} timed out after {timeout} seconds.') from exc
    if process.returncode != 0:
        raise BackupError(_safe_process_error(process, tool_name=tool_name))
    return process


def _restore_test_database_name(job_id):
    timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d%H%M%S')
    return f'ispmanager_restoretest_{job_id}_{timestamp}'


def _restore_test_key_table_specs():
    specs = []
    for app_label, model_name, label in RESTORE_TEST_KEY_MODELS:
        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:
            continue
        specs.append({
            'label': label,
            'table_name': model._meta.db_table,
        })
    return specs


def _restore_test_connection_kwargs(database, database_name):
    kwargs = {
        'dbname': database_name,
        'connect_timeout': 15,
    }
    mapping = {
        'USER': 'user',
        'PASSWORD': 'password',
        'HOST': 'host',
        'PORT': 'port',
    }
    for config_key, connection_key in mapping.items():
        value = database.get(config_key)
        if value not in (None, ''):
            kwargs[connection_key] = str(value)
    return kwargs


def _collect_restore_validation(database, target_database, expected_tables=None):
    with psycopg.connect(**_restore_test_connection_kwargs(database, target_database)) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
                """
            )
            table_names = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pg_catalog.pg_constraint c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace
                WHERE n.nspname = 'public'
                  AND c.contype = 'f'
                """
            )
            foreign_key_count = int(cursor.fetchone()[0])

            key_table_counts = []
            for spec in _restore_test_key_table_specs():
                if spec['table_name'] not in table_names:
                    continue
                cursor.execute(
                    sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(spec['table_name']))
                )
                key_table_counts.append({
                    **spec,
                    'row_count': int(cursor.fetchone()[0]),
                })

            migration_count = None
            if 'django_migrations' in table_names:
                cursor.execute('SELECT COUNT(*) FROM django_migrations')
                migration_count = int(cursor.fetchone()[0])

    expected_tables = sorted(set(expected_tables or []))
    missing_expected_tables = sorted(set(expected_tables) - set(table_names))
    missing_key_tables = [
        spec for spec in _restore_test_key_table_specs()
        if spec['table_name'] not in table_names
    ]
    return {
        'table_count': len(table_names),
        'public_tables': table_names,
        'foreign_key_count': foreign_key_count,
        'migration_count': migration_count,
        'key_table_counts': key_table_counts,
        'missing_key_tables': missing_key_tables,
        'expected_table_count': len(expected_tables),
        'missing_expected_tables': missing_expected_tables,
    }


def _create_restore_test_database(database, backup_settings, target_database):
    status = restore_test_status(backup_settings)
    if not status['ok']:
        raise BackupError(f"Restore test is enabled but not ready: {status['error']}")
    command = [
        status['tools']['createdb'],
        *_postgres_cli_connection_args(database),
        '--maintenance-db',
        status['maintenance_database'],
        '--template',
        'template0',
        target_database,
    ]
    _run_postgres_command(command, database, tool_name='createdb', timeout=60)
    return status


def _drop_restore_test_database(database, restore_status, target_database):
    command = [
        restore_status['tools']['dropdb'],
        *_postgres_cli_connection_args(database),
        '--maintenance-db',
        restore_status['maintenance_database'],
        '--if-exists',
        target_database,
    ]
    _run_postgres_command(command, database, tool_name='dropdb', timeout=60)


def _restore_backup_into_database(database, restore_status, target_database, restore_path):
    command = [
        restore_status['tools']['pg_restore'],
        *_postgres_cli_connection_args(database),
        '--no-owner',
        '--no-privileges',
        '--exit-on-error',
        '--dbname',
        target_database,
        str(restore_path),
    ]
    _run_postgres_command(command, database, tool_name='pg_restore', timeout=1800)


def _materialize_restore_source(source_job, source_path):
    encrypted = bool(
        source_path.name.endswith('.enc')
        or source_job.summary_json.get('encryption', {}).get('enabled')
    )
    if not encrypted:
        return source_path, None, False

    handle = tempfile.NamedTemporaryFile(
        prefix='ispmanager-restore-test-',
        suffix='.dump',
        delete=False,
    )
    temp_path = Path(handle.name)
    handle.close()
    try:
        _decrypt_backup_file(source_path, temp_path)
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return temp_path, temp_path, True


def run_restore_test(source_job, user=None):
    backup_settings = BackupSettings.get_settings()
    if not backup_settings.restore_test_enabled:
        raise BackupError('Restore tests are disabled in Backup & Restore settings.')
    if source_job.job_type != 'export':
        raise BackupError('Restore tests can only run from database export backup jobs.')
    if source_job.status != 'completed':
        raise BackupError('Restore tests require a completed database export backup.')
    if source_job.pg_dump_format != 'custom':
        raise BackupError('Restore tests currently support PostgreSQL custom-format backups only.')
    if BackupJob.objects.filter(status='running', job_type='restore_test').exists():
        raise BackupError('Another restore test is already running.')
    if BackupJob.objects.filter(status='running', job_type='export').exists():
        raise BackupError('Wait for the running database backup to finish before starting a restore test.')

    database = _database_config()
    job = BackupJob.objects.create(
        job_type='restore_test',
        profile=source_job.profile,
        status='running',
        file_name=source_job.file_name,
        file_size_bytes=source_job.file_size_bytes,
        checksum_sha256=source_job.checksum_sha256,
        pg_dump_format=source_job.pg_dump_format,
        source_database=source_job.source_database,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        started_at=timezone.now(),
        summary_json={
            'source_backup_job_id': source_job.pk,
            'source_file_name': source_job.file_name,
            'source_checksum_sha256': source_job.checksum_sha256,
            'temporary_database': True,
            'production_database_unchanged': True,
        },
    )
    target_database = _restore_test_database_name(job.pk)
    job.summary_json = {
        **job.summary_json,
        'target_database': target_database,
    }
    job.save(update_fields=['summary_json'])

    restore_status = None
    restore_path = None
    temporary_restore_path = None
    database_created = False
    checksum_verified = False
    source_encrypted = False
    validation = {}
    failure = None
    cleanup_error = ''

    try:
        source_path = _backup_file_path(source_job, backup_settings)
        actual_checksum = _sha256_file(source_path)
        if source_job.checksum_sha256 and actual_checksum != source_job.checksum_sha256:
            raise BackupError('Backup checksum mismatch; restore test was not started.')
        checksum_verified = bool(source_job.checksum_sha256)
        restore_path, temporary_restore_path, source_encrypted = _materialize_restore_source(
            source_job,
            source_path,
        )
        restore_status = _create_restore_test_database(database, backup_settings, target_database)
        database_created = True
        _restore_backup_into_database(database, restore_status, target_database, restore_path)
        validation = _collect_restore_validation(
            database,
            target_database,
            expected_tables=source_job.summary_json.get('tables', []),
        )
        if validation['table_count'] <= 0:
            raise BackupError('Restore test completed but no public tables were restored.')
        if validation['missing_expected_tables']:
            raise BackupError(
                'Restore test is missing expected table(s): '
                + ', '.join(validation['missing_expected_tables'])
            )
    except Exception as exc:
        failure = exc
    finally:
        if database_created and restore_status:
            try:
                _drop_restore_test_database(database, restore_status, target_database)
            except Exception as exc:
                cleanup_error = str(exc)
        if temporary_restore_path and temporary_restore_path.exists():
            temporary_restore_path.unlink()

    completed_at = timezone.now()
    cleanup_summary = {
        'attempted': database_created,
        'completed': bool(database_created and not cleanup_error),
        'error': cleanup_error,
    }
    report = {
        'completed_at': completed_at.isoformat(),
        'target_database': target_database,
        'source_encrypted': source_encrypted,
        'checksum_verified_before_restore': checksum_verified,
        'validation': validation,
        'cleanup': cleanup_summary,
    }

    if failure or cleanup_error:
        message_parts = []
        if failure:
            message_parts.append(str(failure))
        if cleanup_error:
            message_parts.append(f'Temporary database cleanup failed: {cleanup_error}')
        message = ' '.join(message_parts)
        job.status = 'failed'
        job.error_report = message[:4000]
        job.completed_at = completed_at
        job.summary_json = {
            **job.summary_json,
            **report,
        }
        job.save(update_fields=['status', 'error_report', 'completed_at', 'summary_json'])
        AuditLog.log(
            'system',
            'backups',
            f"Restore test failed for {source_job.file_name}: {message[:500]}",
            user=user,
        )
        if isinstance(failure, BackupError):
            raise failure
        raise BackupError(message) from failure

    job.status = 'completed'
    job.completed_at = completed_at
    job.summary_json = {
        **job.summary_json,
        **report,
    }
    job.save(update_fields=['status', 'completed_at', 'summary_json'])
    AuditLog.log(
        'system',
        'backups',
        f"Restore test completed for {source_job.file_name}: {validation['table_count']} table(s) restored",
        user=user,
    )
    return job


def _preflight_check(key, label, passed, detail, category='automatic'):
    return {
        'key': key,
        'label': label,
        'passed': bool(passed),
        'detail': detail,
        'category': category,
    }


def production_restore_preflight(source_job):
    backup_settings = BackupSettings.get_settings()
    latest_matching_restore_test = BackupJob.objects.filter(
        job_type='restore_test',
        status='completed',
        summary_json__source_backup_job_id=source_job.pk,
    ).order_by('-completed_at', '-created_at').first()
    running_exports = BackupJob.objects.filter(status='running', job_type='export').count()
    running_restore_tests = BackupJob.objects.filter(status='running', job_type='restore_test').count()

    file_path = None
    file_error = ''
    if source_job.job_type == 'export' and source_job.status == 'completed':
        try:
            file_path = _backup_file_path(source_job, backup_settings)
        except BackupError as exc:
            file_error = str(exc)

    restore_test_matches_checksum = bool(
        latest_matching_restore_test
        and latest_matching_restore_test.summary_json.get('source_checksum_sha256')
        and latest_matching_restore_test.summary_json.get('source_checksum_sha256') == source_job.checksum_sha256
    )
    remote_copy_summary = source_job.summary_json.get('remote_copy', {})
    encryption_summary = source_job.summary_json.get('encryption', {})

    automatic_checks = [
        _preflight_check(
            'superuser_required',
            'Superuser authorization',
            True,
            'This page is accessible only to a superuser session.',
        ),
        _preflight_check(
            'full_export',
            'Full database export selected',
            source_job.job_type == 'export' and source_job.profile == 'full',
            (
                'Selected backup is a full database export.'
                if source_job.job_type == 'export' and source_job.profile == 'full'
                else 'Production restore candidates must be completed full database exports.'
            ),
        ),
        _preflight_check(
            'completed_export',
            'Backup job completed',
            source_job.status == 'completed',
            (
                'Selected backup completed successfully.'
                if source_job.status == 'completed'
                else 'Selected backup is not completed.'
            ),
        ),
        _preflight_check(
            'local_artifact',
            'Local backup artifact available',
            bool(file_path),
            (
                f'Artifact is available at {file_path}.'
                if file_path
                else file_error or 'Local artifact is not available.'
            ),
        ),
        _preflight_check(
            'checksum_recorded',
            'Checksum recorded',
            bool(source_job.checksum_sha256),
            (
                'A SHA-256 checksum is recorded for the selected artifact.'
                if source_job.checksum_sha256
                else 'No recorded checksum exists for this artifact.'
            ),
        ),
        _preflight_check(
            'matching_restore_test',
            'Matching restore test completed',
            restore_test_matches_checksum,
            (
                f"Restore test #{latest_matching_restore_test.pk} completed for this exact checksum."
                if restore_test_matches_checksum
                else 'No completed restore test for this exact backup checksum was found.'
            ),
        ),
        _preflight_check(
            'no_running_backup_jobs',
            'No backup or restore-test job is running',
            running_exports == 0 and running_restore_tests == 0,
            (
                'No export or restore-test jobs are currently running.'
                if running_exports == 0 and running_restore_tests == 0
                else f'{running_exports} export job(s) and {running_restore_tests} restore-test job(s) are still running.'
            ),
        ),
    ]

    advisory_checks = [
        _preflight_check(
            'artifact_encryption',
            'Artifact encryption status',
            encryption_summary.get('enabled', False),
            (
                'Selected artifact is encrypted.'
                if encryption_summary.get('enabled', False)
                else 'Selected artifact is not encrypted.'
            ),
            category='advisory',
        ),
        _preflight_check(
            'remote_copy',
            'Remote copy status',
            remote_copy_summary.get('status') == 'completed',
            (
                'Selected artifact has a completed remote copy record.'
                if remote_copy_summary.get('status') == 'completed'
                else 'No completed remote copy record is attached to this artifact.'
            ),
            category='advisory',
        ),
    ]

    manual_requirements = [
        {
            'key': 'current_state_backup',
            'label': 'Fresh current-state backup',
            'detail': 'Take a new full backup immediately before any destructive restore so rollback has a recovery point.',
        },
        {
            'key': 'maintenance_window',
            'label': 'Maintenance window approved',
            'detail': 'Confirm the outage window, approver, and operator responsible for the restore.',
        },
        {
            'key': 'scheduler_stopped',
            'label': 'Scheduler stopped',
            'detail': 'Stop scheduler automation before write-bearing restore work begins.',
        },
        {
            'key': 'writes_blocked',
            'label': 'Application writes stopped',
            'detail': 'Place the app in downtime or otherwise prevent writes before replacing live data.',
        },
        {
            'key': 'rollback_plan',
            'label': 'Rollback plan ready',
            'detail': 'Document how to return to the pre-restore state if validation fails.',
        },
        {
            'key': 'post_restore_validation',
            'label': 'Post-restore validation ready',
            'detail': 'Prepare the subscriber, billing, payment, settings, and smoke-test checklist.',
        },
    ]

    blockers = [item for item in automatic_checks if not item['passed']]
    return {
        'source_job': source_job,
        'file_path': file_path,
        'latest_matching_restore_test': latest_matching_restore_test,
        'automatic_checks': automatic_checks,
        'advisory_checks': advisory_checks,
        'manual_requirements': manual_requirements,
        'blockers': blockers,
        'ready_for_future_execution_slice': not blockers,
        'generated_at': timezone.now(),
    }


def _restore_plan_check(key, label, passed, detail):
    return {
        'key': key,
        'label': label,
        'passed': bool(passed),
        'detail': detail,
    }


def production_restore_plan_status(plan):
    preflight = production_restore_preflight(plan.source_backup_job)
    now = timezone.now()
    pinned_checksum_matches = bool(
        plan.source_checksum_sha256
        and plan.source_checksum_sha256 == plan.source_backup_job.checksum_sha256
    )
    maintenance_window_is_usable = bool(
        plan.maintenance_window_starts_at
        and plan.maintenance_window_ends_at
        and plan.maintenance_window_ends_at > now
    )
    manual_checks = [
        _restore_plan_check(
            'pinned_checksum',
            'Pinned backup checksum still matches',
            pinned_checksum_matches,
            (
                'Plan checksum matches the selected backup artifact.'
                if pinned_checksum_matches
                else 'Selected backup checksum changed after this plan was created.'
            ),
        ),
        _restore_plan_check(
            'maintenance_window_details',
            'Maintenance window recorded',
            maintenance_window_is_usable,
            (
                'Maintenance window start and end are recorded, and the window has not ended.'
                if maintenance_window_is_usable
                else 'Record a maintenance window whose end time has not passed.'
            ),
        ),
        _restore_plan_check(
            'authorized_by',
            'Authorization recorded',
            bool(plan.authorized_by_name.strip()),
            (
                f'Authorized by {plan.authorized_by_name}.'
                if plan.authorized_by_name.strip()
                else 'Record who authorized the production restore.'
            ),
        ),
        _restore_plan_check(
            'rollback_plan',
            'Rollback plan documented',
            bool(plan.rollback_plan.strip()),
            (
                'Rollback plan text is recorded.'
                if plan.rollback_plan.strip()
                else 'Document the rollback plan.'
            ),
        ),
        _restore_plan_check(
            'post_restore_validation_plan',
            'Post-restore validation documented',
            bool(plan.post_restore_validation_plan.strip()),
            (
                'Post-restore validation plan text is recorded.'
                if plan.post_restore_validation_plan.strip()
                else 'Document the post-restore validation plan.'
            ),
        ),
        _restore_plan_check(
            'current_state_backup_confirmed',
            'Fresh current-state backup confirmed',
            plan.current_state_backup_confirmed,
            (
                'Operator confirmed a fresh current-state backup exists before destructive restore work.'
                if plan.current_state_backup_confirmed
                else 'Confirm a fresh current-state backup before destructive restore work.'
            ),
        ),
        _restore_plan_check(
            'maintenance_window_confirmed',
            'Maintenance window confirmed',
            plan.maintenance_window_confirmed,
            (
                'Operator confirmed the maintenance window is approved.'
                if plan.maintenance_window_confirmed
                else 'Confirm the approved maintenance window.'
            ),
        ),
        _restore_plan_check(
            'scheduler_stop_confirmed',
            'Scheduler stop confirmed',
            plan.scheduler_stop_confirmed,
            (
                'Operator confirmed scheduler automation will be stopped before restore work.'
                if plan.scheduler_stop_confirmed
                else 'Confirm scheduler automation will be stopped before restore work.'
            ),
        ),
        _restore_plan_check(
            'writes_blocked_confirmed',
            'Application writes stop confirmed',
            plan.writes_blocked_confirmed,
            (
                'Operator confirmed app writes will be stopped before live data replacement.'
                if plan.writes_blocked_confirmed
                else 'Confirm application writes will be stopped before live data replacement.'
            ),
        ),
        _restore_plan_check(
            'rollback_plan_confirmed',
            'Rollback plan confirmed',
            plan.rollback_plan_confirmed,
            (
                'Operator confirmed the rollback plan is ready.'
                if plan.rollback_plan_confirmed
                else 'Confirm the rollback plan is ready.'
            ),
        ),
        _restore_plan_check(
            'post_restore_validation_confirmed',
            'Post-restore validation confirmed',
            plan.post_restore_validation_confirmed,
            (
                'Operator confirmed the validation checklist is ready.'
                if plan.post_restore_validation_confirmed
                else 'Confirm the validation checklist is ready.'
            ),
        ),
    ]
    blockers = [
        *preflight['blockers'],
        *[item for item in manual_checks if not item['passed']],
    ]
    return {
        'plan': plan,
        'preflight': preflight,
        'manual_checks': manual_checks,
        'blockers': blockers,
        'ready': not blockers,
        'effective_status_label': 'Ready' if not blockers else 'Draft',
    }


def get_or_create_production_restore_plan(source_job, user=None):
    if source_job.job_type != 'export' or source_job.profile != 'full':
        raise BackupError('Production restore plans require a full database export backup.')
    if source_job.status != 'completed':
        raise BackupError('Production restore plans require a completed database export backup.')
    if not source_job.checksum_sha256:
        raise BackupError('Production restore plans require a recorded backup checksum.')

    plan = ProductionRestorePlan.objects.filter(
        source_backup_job=source_job,
        source_checksum_sha256=source_job.checksum_sha256,
    ).order_by('-updated_at', '-created_at').first()
    if plan:
        return plan, False

    plan = ProductionRestorePlan.objects.create(
        source_backup_job=source_job,
        source_checksum_sha256=source_job.checksum_sha256,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        updated_by=user if getattr(user, 'is_authenticated', False) else None,
    )
    save_production_restore_plan(plan, user=user)
    AuditLog.log(
        'system',
        'backups',
        f"Production restore plan created for backup #{source_job.pk}: {source_job.file_name}",
        user=user,
    )
    return plan, True


def save_production_restore_plan(plan, user=None):
    status = production_restore_plan_status(plan)
    now = timezone.now()
    plan.preflight_snapshot_json = {
        'generated_at': status['preflight']['generated_at'].isoformat(),
        'automatic_checks': status['preflight']['automatic_checks'],
        'advisory_checks': status['preflight']['advisory_checks'],
        'ready_for_future_execution_slice': status['preflight']['ready_for_future_execution_slice'],
    }
    plan.updated_by = user if getattr(user, 'is_authenticated', False) else plan.updated_by
    if status['ready']:
        if plan.status != 'ready':
            plan.ready_at = now
        plan.status = 'ready'
    else:
        plan.status = 'draft'
        plan.ready_at = None
    plan.save(update_fields=[
        'status',
        'preflight_snapshot_json',
        'updated_by',
        'ready_at',
        'updated_at',
    ])
    return production_restore_plan_status(plan)


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
        remote_copy_summary = {'enabled': False}
        if backup_settings.remote_copy_enabled:
            try:
                remote_copy_summary = _copy_backup_remote(final_path, backup_settings)
                AuditLog.log(
                    'system',
                    'backups',
                    f"Remote backup copy completed for {filename}",
                    user=user,
                )
            except Exception as exc:
                remote_copy_summary = {
                    'enabled': True,
                    'backend': backup_settings.remote_backend,
                    'status': 'failed',
                    'error': str(exc)[:4000],
                    'completed_at': timezone.now().isoformat(),
                }
                AuditLog.log(
                    'system',
                    'backups',
                    f"Remote backup copy failed for {filename}: {str(exc)[:500]}",
                    user=user,
                )
        completed_at = timezone.now()
        job.status = 'completed'
        job.file_size_bytes = size
        job.checksum_sha256 = checksum
        job.completed_at = completed_at
        job.summary_json = {
            **job.summary_json,
            'completed_at': completed_at.isoformat(),
            'encryption': encryption_summary,
            'remote_copy': remote_copy_summary,
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
