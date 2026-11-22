import logging

from celery import shared_task
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from .core import SpotifyClient, TransferError, execute_transfer
from .models import TransferJob

logger = logging.getLogger(__name__)


def decrypt_token(value):
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise TransferError("TOKEN_ENCRYPTION_KEY не настроен. Добавь ключ в .env.")
    try:
        return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise TransferError("Не удалось расшифровать токен Spotify. Переподключи аккаунт.") from exc


@shared_task(bind=True, max_retries=0)
def run_transfer(self, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        logger.warning("Transfer job %s does not exist", job_id)
        return
    if job.status != TransferJob.Status.QUEUED:
        return

    job.status = TransferJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])
    try:
        token = decrypt_token(job.encrypted_spotify_token)
        spotify = SpotifyClient(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET, settings.SPOTIFY_REDIRECT_URI)

        def update_progress(values):
            TransferJob.objects.filter(pk=job.pk, status=TransferJob.Status.RUNNING).update(**values)

        result = execute_transfer(
            vk_token=settings.VK_API_TOKEN,
            vk_version=settings.VK_API_VERSION,
            vk_client_id=settings.VK_CLIENT_ID,
            spotify=spotify,
            spotify_token=token,
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
        job.encrypted_spotify_token = ""
        job.save()
    except TransferError as exc:
        job.status = TransferJob.Status.FAILED
        job.error = str(exc)[:500]
        job.finished_at = timezone.now()
        job.encrypted_spotify_token = ""
        job.save(update_fields=["status", "error", "finished_at", "encrypted_spotify_token"])
    except Exception:
        logger.exception("Transfer job %s failed unexpectedly", job_id)
        job.status = TransferJob.Status.FAILED
        job.error = "Перенос не выполнен. Подробности сохранены в серверном журнале."
        job.finished_at = timezone.now()
        job.encrypted_spotify_token = ""
        job.save(update_fields=["status", "error", "finished_at", "encrypted_spotify_token"])
