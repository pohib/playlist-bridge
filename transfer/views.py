# ruff: noqa: I001
import json
import logging
import re
import secrets
import time

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .services import SoundCloudClient, SpotifyClient, TransferError, parse_vk_playlist_url
from .credentials import (
    delete_credential,
    get_access_token,
    get_session_fingerprint,
    store_credential,
)
from .models import LibraryProfile, OAuthCredential, TransferJob

logger = logging.getLogger(__name__)


def encryption_key_is_valid():
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        return True
    except (ValueError, AttributeError):
        return False


def spotify_client():
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        raise TransferError("Spotify OAuth не настроен на сервере.")
    return SpotifyClient(
        settings.SPOTIFY_CLIENT_ID,
        settings.SPOTIFY_CLIENT_SECRET,
        settings.SPOTIFY_REDIRECT_URI,
    )


def soundcloud_client():
    if not settings.SOUNDCLOUD_CLIENT_ID or not settings.SOUNDCLOUD_CLIENT_SECRET:
        raise TransferError("SoundCloud OAuth не настроен на сервере.")
    return SoundCloudClient(settings.SOUNDCLOUD_CLIENT_ID, settings.SOUNDCLOUD_CLIENT_SECRET, settings.SOUNDCLOUD_REDIRECT_URI)


def rotate_session_binding(request):
    old_fingerprint = get_session_fingerprint(request)
    request.session.cycle_key()
    new_fingerprint = get_session_fingerprint(request)
    OAuthCredential.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)
    TransferJob.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)
    LibraryProfile.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)


def connected_providers(request):
    fingerprint = get_session_fingerprint(request)
    providers = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint)
        .values_list("provider", flat=True)
    )
    return "spotify" in providers, False, "soundcloud" in providers


@never_cache
@require_GET
def home(request):
    return render(request, "transfer/landing.html")


@never_cache
@require_GET
def healthz(request):
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def spotify_login(request):
    try:
        state = secrets.token_urlsafe(32)
        request.session["spotify_oauth_state"] = state
        return redirect(spotify_client().authorization_url(state))
    except TransferError as exc:
        request.session["oauth_error"] = str(exc)
        return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def spotify_callback(request):
    expected = request.session.pop("spotify_oauth_state", None)
    received = request.GET.get("state", "")
    if request.GET.get("error") or not expected or not secrets.compare_digest(expected, received):
        request.session["oauth_error"] = "Авторизация Spotify отменена или OAuth state недействителен."
        return redirect("connections" if request.user.is_authenticated else "home")
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "Spotify не вернул код авторизации."
        return redirect("connections" if request.user.is_authenticated else "home")
    try:
        client = spotify_client()
        token = client.exchange_code(code)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(get_session_fingerprint(request), "spotify", token, profile.get("id", ""))
        request.session["oauth_success"] = "Spotify успешно подключён. Токены сохранены в зашифрованном виде."
    except TransferError as exc:
        logger.warning("Spotify OAuth callback failed: %s", exc)
        request.session["oauth_error"] = "Не удалось завершить авторизацию Spotify."
    return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def soundcloud_login(request):
    try:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        request.session["soundcloud_oauth_state"] = state
        request.session["soundcloud_code_verifier"] = verifier
        return redirect(soundcloud_client().authorization_url(state, verifier))
    except TransferError as exc:
        request.session["oauth_error"] = str(exc)
        return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def soundcloud_callback(request):
    expected = request.session.pop("soundcloud_oauth_state", None)
    verifier = request.session.pop("soundcloud_code_verifier", None)
    received = request.GET.get("state", "")
    if request.GET.get("error") or not expected or not verifier or not secrets.compare_digest(expected, received):
        request.session["oauth_error"] = "Авторизация SoundCloud отменена или OAuth state недействителен."
        return redirect("connections" if request.user.is_authenticated else "home")
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "SoundCloud не вернул код авторизации."
        return redirect("connections" if request.user.is_authenticated else "home")
    try:
        client = soundcloud_client()
        token = client.exchange_code(code, verifier)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(get_session_fingerprint(request), "soundcloud", token, str(profile.get("id", "")))
        request.session["oauth_success"] = "SoundCloud успешно подключён. Токены сохранены в зашифрованном виде."
    except TransferError as exc:
        logger.warning("SoundCloud OAuth callback failed: %s", exc)
        request.session["oauth_error"] = "Не удалось завершить авторизацию SoundCloud."
    return redirect("connections" if request.user.is_authenticated else "home")


@require_POST
def disconnect_soundcloud(request):
    fingerprint = get_session_fingerprint(request)
    try:
        client = soundcloud_client()
        token, _ = get_access_token(fingerprint, "soundcloud", client)
        client.disconnect(token)
    except TransferError:
        logger.info("SoundCloud disconnect revocation could not be confirmed")
    delete_credential(fingerprint, "soundcloud")
    request.session["oauth_success"] = "SoundCloud отключён."
    return redirect("connections" if request.user.is_authenticated else "home")


@require_POST
def disconnect_spotify(request):
    delete_credential(get_session_fingerprint(request), "spotify")
    request.session["oauth_success"] = "Spotify отключён."
    return redirect("connections" if request.user.is_authenticated else "home")


@require_POST
def transfer_playlist(request):
    return JsonResponse({"error": "Используй POST /api/v1/transfers/."}, status=410)


@require_GET
def download_report(request):
    return HttpResponse("Отчёт доступен через API задачи.", status=410)


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
        "vk_configured": bool(settings.VK_ID_CLIENT_ID and settings.VK_ANON_CLIENT_SECRET),
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
    if not settings.VK_ID_CLIENT_ID or not settings.VK_ANON_CLIENT_SECRET:
        return api_error("Анонимный доступ VK не настроен на сервере.", 503)
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
                "description": "Требует браузерную сессию, подключения обоих провайдеров и CSRF-токен.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["source_url"], "properties": {
                        "source_url": {"type": "string", "format": "uri"},
                        "target_playlist": {"type": "string"},
                    },
                }}}},
                "responses": {"202": {"description": "Задача поставлена в очередь"}, "400": {"description": "Ошибка запроса"}},
            }},
            "/transfers/{job_id}/": {"get": {"summary": "Получить прогресс задачи", "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Состояние задачи"}}}},
            "/transfers/{job_id}/report/": {"get": {"summary": "Получить отчёт", "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Отчёт в JSON"}}}},
        },
    }
    return JsonResponse(schema)
