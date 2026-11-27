# ruff: noqa: I001
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .services import SpotifyClient, TransferError, execute_transfer
from .services.credential_service import get_access_token
from .models import TransferJob

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def run_transfer(self, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        logger.warning("Transfer job %s does not exist", job_id)
        return

    # Claim atomically: duplicate Celery deliveries must never run the same job twice.
    started_at = timezone.now()
    claimed = TransferJob.objects.filter(
        pk=job_id,
        status=TransferJob.Status.QUEUED,
    ).update(
        status=TransferJob.Status.RUNNING,
        started_at=started_at,
        heartbeat_at=started_at,
    )
    if claimed != 1:
        return

    try:
        spotify = SpotifyClient(
            settings.SPOTIFY_CLIENT_ID,
            settings.SPOTIFY_CLIENT_SECRET,
            settings.SPOTIFY_REDIRECT_URI,
        )

        def spotify_token():
            return get_access_token(job.session_fingerprint, "spotify", spotify)[0]

        def update_progress(values):
            update_values = dict(values)
            update_values["heartbeat_at"] = timezone.now()
            TransferJob.objects.filter(
                pk=job.pk,
                status=TransferJob.Status.RUNNING,
            ).update(**update_values)

        result = execute_transfer(
            vk_version=settings.VK_API_VERSION,
            spotify=spotify,
            spotify_token=spotify_token(),
            token_provider=spotify_token,
            source_url=job.source_url,
            target_playlist=job.target_playlist or None,
            progress_callback=update_progress,
        )

        finished_at = timezone.now()
        updated = TransferJob.objects.filter(
            pk=job.pk,
            status=TransferJob.Status.RUNNING,
        ).update(
            status=TransferJob.Status.SUCCEEDED,
            progress=100,
            total=result["total"],
            matched=result["matched"],
            not_found=result["not_found"],
            ambiguous=result["ambiguous"],
            result=result,
            finished_at=finished_at,
            heartbeat_at=finished_at,
        )
        if updated != 1:
            logger.warning(
                "Transfer job %s changed state before completion; preserving its current state",
                job_id,
            )
    except TransferError as exc:
        finished_at = timezone.now()
        updated = TransferJob.objects.filter(
            pk=job.pk,
            status=TransferJob.Status.RUNNING,
        ).update(
            status=TransferJob.Status.FAILED,
            error=str(exc)[:500],
            finished_at=finished_at,
            heartbeat_at=finished_at,
        )
        if updated != 1:
            logger.warning(
                "Transfer job %s changed state before failure handling; preserving its current state",
                job_id,
            )
    except Exception:
        logger.exception("Transfer job %s failed unexpectedly", job_id)
        finished_at = timezone.now()
        updated = TransferJob.objects.filter(
            pk=job.pk,
            status=TransferJob.Status.RUNNING,
        ).update(
            status=TransferJob.Status.FAILED,
            error="Перенос не выполнен. Подробности сохранены в серверном журнале.",
            finished_at=finished_at,
            heartbeat_at=finished_at,
        )
        if updated != 1:
            logger.warning(
                "Transfer job %s changed state before unexpected-failure handling; preserving its current state",
                job_id,
            )


@shared_task(ignore_result=True)
def dispatch_queued_transfers():
    """Recover PostgreSQL queued jobs whose Redis message was lost or unavailable."""
    from .services.transfer_dispatch import dispatch_pending_transfers

    result = dispatch_pending_transfers()
    logger.info(
        "Queued transfer dispatch completed: eligible=%s dispatched=%s failed=%s",
        result["eligible"],
        result["dispatched"],
        result["failed"],
    )
    return result
