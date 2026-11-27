import json
import logging
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .credentials import get_session_fingerprint
from .models import OAuthCredential, TransferJob
from .oauth_views import connected_providers, encryption_key_is_valid
from .services import parse_vk_playlist_url

logger = logging.getLogger(__name__)


def api_error(message, status=400):
    return JsonResponse({"error": {"message": message}}, status=status)


def serialize_job(job):
    return {
        "id": str(job.pk),
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "matched": job.matched,
        "not_found": job.not_found,
        "ambiguous": job.ambiguous,
        "error": job.error or None,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "target_playlist_id": job.result.get("target_playlist_id") if job.status == TransferJob.Status.SUCCEEDED else None,
    }


@never_cache
@require_GET
def api_status(request):
    spotify_connected, vk_connected, soundcloud_connected = connected_providers(request)
    return JsonResponse({
        "api_version": "1",
        "spotify_connected": spotify_connected,
        "vk_connected": vk_connected,
        "soundcloud_connected": soundcloud_connected,
        "soundcloud_configured": bool(settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET),
        "spotify_configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET),
        "vk_configured": True,
        "encryption_key_configured": encryption_key_is_valid(),
    })


@require_POST
def api_create_transfer(request):
    if not request.content_type or "application/json" not in request.content_type:
        return api_error("Используй Content-Type: application/json.", 415)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return api_error("Тело запроса содержит некорректный JSON.")
    if not isinstance(payload, dict):
        return api_error("Ожидается JSON-объект.")
    source_url = payload.get("source_url", "")
    target = payload.get("target_playlist", "")
    if not isinstance(source_url, str) or len(source_url) > 2048:
        return api_error("Поле source_url обязательно и должно быть строкой длиной до 2048 символов.")
    if target is not None and (not isinstance(target, str) or len(target) > 2048):
        return api_error("Поле target_playlist должно быть строкой длиной до 2048 символов.")
    normalized_target = (target or "").strip() if isinstance(target, str) or target is None else ""
    if normalized_target and not re.fullmatch(r"[A-Za-z0-9]{22}", normalized_target):
        return api_error("Поле target_playlist должно содержать корректный Spotify ID плейлиста.")
    try:
        URLValidator(schemes=["http", "https"])(source_url)
        parse_vk_playlist_url(source_url)
    except (ValidationError, ValueError):
        return api_error("Укажи корректную ссылку на плейлист VK.")
    if not encryption_key_is_valid():
        return api_error("Шифрование OAuth-токенов не настроено на сервере.", 503)
    fingerprint = get_session_fingerprint(request)
    connected = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint)
        .values_list("provider", flat=True)
    )
    if "spotify" not in connected:
        return api_error("Сначала подключи Spotify.", 401)
    active = TransferJob.objects.filter(
        session_fingerprint=fingerprint,
        status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
    ).first()
    if active:
        return JsonResponse({"job": serialize_job(active)}, status=202)

    try:
        with transaction.atomic():
            job = TransferJob.objects.create(
                session_fingerprint=fingerprint,
                source_url=source_url,
                target_playlist=normalized_target,
            )
    except IntegrityError:
        # The partial unique constraint closes the race between simultaneous POSTs.
        active = TransferJob.objects.filter(
            session_fingerprint=fingerprint,
            status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
        ).first()
        if active:
            return JsonResponse({"job": serialize_job(active)}, status=202)
        raise
    try:
        from .tasks import run_transfer
        run_transfer.delay(str(job.pk))
    except Exception:
        logger.exception("Could not enqueue transfer job %s", job.pk)
        job.status = TransferJob.Status.FAILED
        job.error = "Очередь задач недоступна. Проверь Redis и Celery worker."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return api_error(job.error, 503)
    return JsonResponse({"job": serialize_job(job)}, status=202)


@never_cache
@require_GET
def api_transfer_detail(request, job_id):
    job = TransferJob.objects.filter(
        pk=job_id,
        session_fingerprint=get_session_fingerprint(request),
    ).first()
    if not job:
        return api_error("Задача не найдена.", 404)
    return JsonResponse({"job": serialize_job(job)})


@never_cache
@require_GET
def api_transfer_report(request, job_id):
    job = TransferJob.objects.filter(
        pk=job_id,
        session_fingerprint=get_session_fingerprint(request),
    ).first()
    if not job:
        return api_error("Задача не найдена.", 404)
    if job.status != TransferJob.Status.SUCCEEDED:
        return api_error("Отчёт появится после завершения переноса.", 409)
    return JsonResponse({"report": job.result.get("report", [])})


@never_cache
@require_GET
def api_openapi(request):
    schema = {
        "openapi": "3.1.0",
        "info": {"title": "VK to Spotify API", "version": "1.1.0"},
        "servers": [{"url": "/api/v1"}],
        "paths": {
            "/status/": {"get": {"summary": "Состояние подключений", "responses": {"200": {"description": "Connection state"}}}},
            "/transfers/": {"post": {
                "summary": "Запустить перенос",
                "description": "Требует браузерную сессию, подключённый Spotify и CSRF-токен; источник VK должен быть публичным.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["source_url"], "properties": {
                        "source_url": {"type": "string", "format": "uri"},
                        "target_playlist": {"type": "string"},
                    },
                }}}},
                "responses": {
                    "202": {"description": "Задача поставлена в очередь или уже выполняется"},
                    "400": {"description": "Ошибка запроса"},
                    "401": {"description": "Spotify не подключён для текущей сессии"},
                    "415": {"description": "Требуется Content-Type application/json"},
                    "503": {"description": "Сервис временно недоступен или не настроено шифрование credentials"}
                },
            }},
            "/transfers/{job_id}/": {"get": {"summary": "Получить прогресс задачи", "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Состояние задачи"}}}},
            "/transfers/{job_id}/report/": {"get": {"summary": "Получить отчёт", "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Отчёт в JSON"}}}},
        },
    }
    return JsonResponse(schema)


@never_cache
@require_GET
def api_docs(request):
    """Render the safe, user-facing API guide."""
    return render(request, "transfer/api_docs.html")


def api_not_found(request, exception=None):
    """Keep unknown API routes on the JSON error contract."""
    if request.path == "/api/v1" or request.path.startswith("/api/v1/"):
        return api_error("API endpoint not found.", 404)
    return HttpResponseNotFound("Not found")
