# ruff: noqa: I001
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from transfer.models import TransferJob
from transfer.services.transfer_dispatch import dispatch_transfer_job


STALE_JOB_ERROR = (
    "Задача прервана: worker перестал отправлять heartbeat. "
    "Перед повтором проверь целевой плейлист Spotify — часть треков могла уже добавиться."
)


class Command(BaseCommand):
    help = "Resume stale transfers only when a Spotify target playlist was checkpointed; fail unsafe jobs."

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
            help="Only report how many stale jobs would be resumed or marked failed.",
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

        recoverable_ids = []
        failed_ids = []
        for job in stale_jobs.only("pk", "checkpoint", "target_playlist"):
            checkpoint = job.checkpoint if isinstance(job.checkpoint, dict) else {}
            if (
                checkpoint.get("target_playlist_id")
                or job.target_playlist
                or (checkpoint.get("report") and not checkpoint.get("playlist_create_pending"))
            ):
                recoverable_ids.append(job.pk)
            else:
                failed_ids.append(job.pk)

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(recoverable_ids)} stale job(s) are resumable; "
                    f"{len(failed_ids)} job(s) would be marked failed."
                )
            )
            return

        failed = TransferJob.objects.filter(pk__in=failed_ids).update(
            status=TransferJob.Status.FAILED,
            error=STALE_JOB_ERROR,
            finished_at=now,
        )
        resumed = TransferJob.objects.filter(
            pk__in=recoverable_ids,
            status=TransferJob.Status.RUNNING,
        ).update(
            status=TransferJob.Status.QUEUED,
            error="",
            started_at=None,
            heartbeat_at=None,
            finished_at=None,
            dispatch_attempted_at=None,
        )
        dispatched = 0
        for job_id in recoverable_ids:
            if dispatch_transfer_job(job_id, retry_after_seconds=1):
                dispatched += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Resumed {resumed} stale transfer job(s); dispatched {dispatched}. "
                f"Marked {failed} job(s) failed because no safe target playlist was saved."
            )
        )
