import signal
import threading
import time

from django.core.management.base import BaseCommand

from apps.core.scheduler import get_scheduler, start_scheduler


class Command(BaseCommand):
    help = 'Run the ISP Manager APScheduler process as a dedicated long-running service.'

    def handle(self, *args, **options):
        stop_event = threading.Event()

        def stop_scheduler(signum, frame):
            self.stdout.write(self.style.WARNING(f'Received signal {signum}; stopping scheduler...'))
            try:
                scheduler = get_scheduler()
                if scheduler.running:
                    scheduler.shutdown(wait=False)
            finally:
                stop_event.set()

        signal.signal(signal.SIGINT, stop_scheduler)
        signal.signal(signal.SIGTERM, stop_scheduler)

        start_scheduler()
        self.stdout.write(self.style.SUCCESS('Scheduler started. Press Ctrl+C to stop.'))

        try:
            while not stop_event.is_set():
                time.sleep(1)
        finally:
            scheduler = get_scheduler()
            if scheduler.running:
                scheduler.shutdown(wait=False)
            self.stdout.write(self.style.SUCCESS('Scheduler stopped.'))
