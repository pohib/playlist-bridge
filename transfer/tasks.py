import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .core import SpotifyClient, TransferError, VKIDClient, execute_transfer
from .credentials import get_access_token
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
    claimed = TransferJob.objects.filter(
        pk=job_id,
        status=TransferJob.Status.QUEUED,
    ).update(status=TransferJob.Status.RUNNING, started_at=timezone.now())
    if claimed != 1:
        return
    job.refresh_from_db()
    try:
        spotify = SpotifyClient(
            settings.SPOTIFY_CLIENT_ID,
            settings.SPOTIFY_CLIENT_SECRET,
            settings.SPOTIFY_REDIRECT_URI,
        )
        vk = VKIDClient(
            settings.VK_ID_CLIENT_ID,
            settings.VK_ID_REDIRECT_URI,
            settings.VK_ID_SERVICE_TOKEN,
        )

        def spotify_token():
            return get_access_token(job.session_fingerprint, "spotify", spotify)[0]

        def vk_token():
            return get_access_token(job.session_fingerprint, "vk", vk)[0]

        def update_progress(values):
            TransferJob.objects.filter(pk=job.pk, status=TransferJob.Status.RUNNING).update(**values)

        result = execute_transfer(
            vk_token=vk_token(),
            vk_version=settings.VK_API_VERSION,
            vk_client_id=settings.VK_ID_CLIENT_ID,
            spotify=spotify,
            spotify_token=spotify_token(),
            token_provider=spotify_token,
            source_url=job.source_url,
            target_playlist=job.target_playlist or None,
            progress_callback=update_progress,
        )
        job.refresh_from_db()
        job.status = TransferJob.Status.SUCCEEDED
        job.progress = 100
        job.total = result["total"]
        job.matched = result["matched"]
        job.not_found = result["not_found"]
        job.ambiguous = result["ambiguous"]
        job.result = result
        job.finished_at = timezone.now()
        job.save()
    except TransferError as exc:
        job.status = TransferJob.Status.FAILED
        job.error = str(exc)[:500]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
    except Exception:
        logger.exception("Transfer job %s failed unexpectedly", job_id)
        job.status = TransferJob.Status.FAILED
        job.error = "Перенос не выполнен. Подробности сохранены в серверном журнале."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
