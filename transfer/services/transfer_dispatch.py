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
    except Exception:
        logger.exception("Could not dispatch queued transfer job %s", job_id)
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
