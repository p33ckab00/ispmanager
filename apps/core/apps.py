from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    label = 'core'

    def ready(self):
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            return
        try:
            from apps.core.scheduler import start_scheduler
            start_scheduler()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler failed to start: {e}")
