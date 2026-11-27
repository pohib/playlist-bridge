from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from transfer.models import TransferJob


STALE_JOB_ERROR = (
    "Задача прервана: worker перестал отправлять heartbeat. "
    "Перед повтором проверь целевой плейлист Spotify — часть треков могла уже добавиться."
)


class Command(BaseCommand):
    help = "Safely mark Celery transfer jobs with an expired heartbeat as failed; never retries them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=60,
            help="Minimum heartbeat age before a running job is considered stale (default: 60).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report how many stale jobs would be marked failed.",
        )

    def handle(self, *args, **options):
        older_than_minutes = options["older_than_minutes"]
        if older_than_minutes < 1:
            raise CommandError("--older-than-minutes must be greater than zero.")

        now = timezone.now()
        cutoff = now - timedelta(minutes=older_than_minutes)
        stale_jobs = TransferJob.objects.filter(
            status=TransferJob.Status.RUNNING,
        ).filter(
            Q(heartbeat_at__lt=cutoff)
            | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
        )

        if options["dry_run"]:
            count = stale_jobs.count()
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} stale running transfer job(s) would be marked failed."
                )
            )
            return

        updated = stale_jobs.update(
            status=TransferJob.Status.FAILED,
            error=STALE_JOB_ERROR,
            finished_at=now,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Marked {updated} stale running transfer job(s) as failed. "
                "No task was retried."
            )
        )
