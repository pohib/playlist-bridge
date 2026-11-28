"""Durable dispatch helpers for PostgreSQL-backed transfer jobs."""
import logging
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from ..models import TransferJob

logger = logging.getLogger(__name__)


def dispatch_transfer_job(job_id, *, retry_after_seconds=120):
    """Acquire a dispatch lease and publish a job UUID to Celery once."""
    if retry_after_seconds < 1:
        raise ValueError("retry_after_seconds must be greater than zero")

    now = timezone.now()
    retry_before = now - timedelta(seconds=retry_after_seconds)
    eligible = TransferJob.objects.filter(
        pk=job_id,
        status=TransferJob.Status.QUEUED,
    ).filter(
        Q(dispatch_attempted_at__isnull=True)
        | Q(dispatch_attempted_at__lte=retry_before)
    )
    claimed = eligible.update(
        dispatch_attempted_at=now,
        dispatch_attempts=F("dispatch_attempts") + 1,
    )
    if claimed != 1:
        return False

    try:
        from ..tasks import run_transfer

        run_transfer.delay(str(job_id))
    except Exception as exc:
        logger.exception("Could not dispatch queued transfer job %s", job_id)
        from .integration_event_recorder import record_worker_failure

        record_worker_failure(
            job_id=job_id,
            error=exc,
            operation="dispatch_transfer_job",
        )
        return False

    return True


def dispatch_pending_transfers(
    *,
    retry_after_seconds=120,
    batch_size=100,
    dry_run=False,
):
    """Dispatch eligible queued jobs; conditional updates coordinate schedulers."""
    if retry_after_seconds < 1:
        raise ValueError("retry_after_seconds must be greater than zero")
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")

    retry_before = timezone.now() - timedelta(seconds=retry_after_seconds)
    eligible = TransferJob.objects.filter(
        status=TransferJob.Status.QUEUED,
    ).filter(
        Q(dispatch_attempted_at__isnull=True)
        | Q(dispatch_attempted_at__lte=retry_before)
    ).order_by("created_at")
    job_ids = list(eligible.values_list("pk", flat=True)[:batch_size])

    if dry_run:
        return {"eligible": len(job_ids), "dispatched": 0, "failed": 0}

    dispatched = 0
    failed = 0
    for job_id in job_ids:
        if dispatch_transfer_job(
            job_id,
            retry_after_seconds=retry_after_seconds,
        ):
            dispatched += 1
        else:
            failed += 1

    return {"eligible": len(job_ids), "dispatched": dispatched, "failed": failed}


def recover_stale_transfers(*, older_than_minutes=60, dry_run=False):
    """Requeue stale jobs only when their Spotify side effects can be reconciled."""
    if older_than_minutes < 1:
        raise ValueError("older_than_minutes must be greater than zero")

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

    if dry_run:
        return {
            "stale": len(recoverable_ids) + len(failed_ids),
            "resumable": len(recoverable_ids),
            "failed": len(failed_ids),
            "resumed": 0,
            "dispatched": 0,
            "dispatch_failed": 0,
        }

    failed = TransferJob.objects.filter(pk__in=failed_ids).update(
        status=TransferJob.Status.FAILED,
        error=(
            "Задача прервана: worker перестал отправлять heartbeat. "
            "Перед повтором проверь целевой плейлист Spotify — часть треков могла уже добавиться."
        ),
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

    return {
        "stale": len(recoverable_ids) + len(failed_ids),
        "resumable": len(recoverable_ids),
        "failed": failed,
        "resumed": resumed,
        "dispatched": dispatched,
        "dispatch_failed": max(0, resumed - dispatched),
    }
