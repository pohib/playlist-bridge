import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("vk_to_spotify")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "dispatch-queued-transfers-every-minute": {
        "task": "transfer.tasks.dispatch_queued_transfers",
        "schedule": 60.0,
        "options": {"expires": 55},
    },
    "purge-old-security-events-monthly": {
        "task": "transfer.tasks.purge_old_security_events",
        "schedule": crontab(day_of_month=1, hour=3, minute=0),
    },
}
