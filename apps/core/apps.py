from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    label = 'core'

    def ready(self):
        from apps.core.role_presets import connect_role_preset_sync
        connect_role_preset_sync()

        import os
        if os.environ.get('RUN_MAIN') != 'true':
            return
        if os.environ.get('DISABLE_SCHEDULER') == '1':
            return
        argv = ' '.join(os.sys.argv)
        if any(cmd in argv for cmd in ['migrate', 'makemigrations', 'collectstatic', 'shell', 'test']):
            return
        try:
            from apps.core.scheduler import start_scheduler
            start_scheduler()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler failed to start: {e}")
