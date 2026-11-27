"""Application service for creating and enqueueing API transfer jobs.

HTTP parsing and response formatting stay in api_views; this module owns
persistence, idempotent reuse of active jobs, and Celery dispatch.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import TransferJob

logger = logging.getLogger(__name__)


def create_or_reuse_transfer_job(*, session_fingerprint, source_url, target_playlist=""):
    """Return (job, HTTP status, optional error message)."""
    active = TransferJob.objects.filter(
        session_fingerprint=session_fingerprint,
        status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
    ).first()
    if active:
        return active, 202, None

    try:
        with transaction.atomic():
            job = TransferJob.objects.create(
                session_fingerprint=session_fingerprint,
                source_url=source_url,
                target_playlist=target_playlist,
            )
    except IntegrityError:
        # The database constraint is the final guard against concurrent POSTs.
        active = TransferJob.objects.filter(
            session_fingerprint=session_fingerprint,
            status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
        ).first()
        if active:
            return active, 202, None
        raise

    try:
        from ..tasks import run_transfer

        run_transfer.delay(str(job.pk))
    except Exception:
        logger.exception("Could not enqueue transfer job %s", job.pk)
        job.status = TransferJob.Status.FAILED
        job.error = "Очередь задач недоступна. Проверь Redis и Celery worker."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return job, 503, job.error

    return job, 202, None
