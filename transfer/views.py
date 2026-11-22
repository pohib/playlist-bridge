import csv
import io
import logging
import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .core import SpotifyClient, TransferError, execute_transfer

logger = logging.getLogger(__name__)


def csv_safe_cell(value):
    """Prevent spreadsheet formula execution in exported untrusted metadata."""
    if isinstance(value, str) and value.lstrip()[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value

def spotify_client():
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        raise TransferError("Spotify OAuth credentials не настроены.")
    return SpotifyClient(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET, settings.SPOTIFY_REDIRECT_URI)

@require_GET
def home(request):
    return render(request, "transfer/home.html", {"connected": bool(request.session.get("spotify_token")), "result": request.session.pop("transfer_result", None)})

@require_GET
def healthz(request):
    return JsonResponse({"status": "ok"})

@require_GET
def spotify_login(request):
    try:
        request.session.cycle_key()
        state = secrets.token_urlsafe(32)
        request.session["spotify_oauth_state"] = state
        return redirect(spotify_client().authorization_url(state))
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("home")

@require_GET
def spotify_callback(request):
    expected = request.session.pop("spotify_oauth_state", None)
    received = request.GET.get("state", "")
    if request.GET.get("error") or not expected or not secrets.compare_digest(expected, received):
        messages.error(request, "Авторизация Spotify отменена или OAuth state недействителен.")
        return redirect("home")
    code = request.GET.get("code", "")
    if not code:
        messages.error(request, "Spotify не вернул код авторизации.")
        return redirect("home")
    try:
        token = spotify_client().exchange_code(code)
        token["obtained_at"] = time.time()
        request.session["spotify_token"] = token
        messages.success(request, "Spotify успешно подключён.")
    except TransferError:
        logger.exception("Spotify OAuth callback failed")
        messages.error(request, "Не удалось завершить авторизацию Spotify.")
    return redirect("home")

def get_access_token(request):
    token = request.session.get("spotify_token")
    if not token:
        raise TransferError("Сначала подключи Spotify.")
    if time.time() >= token.get("obtained_at", 0) + token.get("expires_in", 3600) - 60:
        refresh = token.get("refresh_token")
        if not refresh:
            request.session.pop("spotify_token", None)
            raise TransferError("Сессия Spotify истекла. Подключи аккаунт повторно.")
        renewed = spotify_client().refresh_token(refresh)
        renewed["refresh_token"] = renewed.get("refresh_token", refresh)
        renewed["obtained_at"] = time.time()
        request.session["spotify_token"] = renewed
        token = renewed
    return token["access_token"]

@require_POST
def transfer_playlist(request):
    try:
        if not settings.VK_API_TOKEN:
            raise TransferError("VK_API_TOKEN не задан в .env.")
        source = request.POST.get("source_url", "").strip()
        target = request.POST.get("target_playlist", "").strip()
        result = execute_transfer(
            vk_token=settings.VK_API_TOKEN,
            vk_version=settings.VK_API_VERSION,
            vk_client_id=settings.VK_CLIENT_ID,
            spotify=spotify_client(),
            spotify_token=get_access_token(request),
            source_url=source,
            target_playlist=target or None,
        )
        request.session["transfer_result"] = result
        messages.success(request, f"Перенесено {result['matched']} из {result['total']} треков.")
    except TransferError as exc:
        messages.error(request, str(exc))
    except Exception:
        logger.exception("Unexpected playlist transfer failure")
        messages.error(request, "Перенос не выполнен. Подробности сохранены в серверном журнале.")
    return redirect("home")

@require_GET
def download_report(request):
    rows = request.session.get("transfer_result", {}).get("report", [])
    if not rows:
        return HttpResponse("Отчёт отсутствует.", status=404)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_safe_cell(value) for key, value in row.items()})
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="transfer-report.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


import hashlib
import hmac
import json

from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .models import TransferJob


def session_fingerprint(request):
    if not request.session.session_key:
        request.session.save()
    return hmac.new(
        settings.SECRET_KEY.encode(),
        request.session.session_key.encode(),
        hashlib.sha256,
    ).hexdigest()


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


@require_GET
def api_status(request):
    return JsonResponse({
        "api_version": "1",
        "spotify_connected": bool(request.session.get("spotify_token")),
        "spotify_configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET),
        "vk_configured": bool(settings.VK_API_TOKEN),
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
    try:
        URLValidator(schemes=["http", "https"])(source_url)
        from .core import parse_vk_playlist_url
        parse_vk_playlist_url(source_url)
    except (ValidationError, ValueError):
        return api_error("Укажи корректную ссылку на плейлист VK.")
    if not settings.VK_API_TOKEN:
        return api_error("VK_API_TOKEN не настроен на сервере.", 503)
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        return api_error("Spotify OAuth не настроен: проверь SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET.", 503)
    if not settings.TOKEN_ENCRYPTION_KEY:
        return api_error("TOKEN_ENCRYPTION_KEY не настроен на сервере.", 503)
    token_data = request.session.get("spotify_token")
    if not token_data:
        return api_error("Сначала подключи Spotify.", 401)
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        access_token = get_access_token(request)
        encrypted = Fernet(settings.TOKEN_ENCRYPTION_KEY.encode()).encrypt(access_token.encode()).decode()
    except (ValueError, TransferError) as exc:
        return api_error(str(exc), 503)

    fingerprint = session_fingerprint(request)
    active = TransferJob.objects.filter(
        session_fingerprint=fingerprint,
        status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
    ).first()
    if active:
        return JsonResponse({"job": serialize_job(active)}, status=202)

    job = TransferJob.objects.create(
        session_fingerprint=fingerprint,
        source_url=source_url,
        target_playlist=(target or "").strip(),
        encrypted_spotify_token=encrypted,
    )
    try:
        from .tasks import run_transfer
        run_transfer.delay(str(job.pk))
    except Exception:
        logger.exception("Could not enqueue transfer job %s", job.pk)
        job.status = TransferJob.Status.FAILED
        job.error = "Очередь задач недоступна. Проверь Redis и Celery worker."
        job.finished_at = timezone.now()
        job.encrypted_spotify_token = ""
        job.save(update_fields=["status", "error", "finished_at", "encrypted_spotify_token"])
        return api_error(job.error, 503)
    return JsonResponse({"job": serialize_job(job)}, status=202)


@require_GET
def api_transfer_detail(request, job_id):
    job = TransferJob.objects.filter(pk=job_id, session_fingerprint=session_fingerprint(request)).first()
    if not job:
        return api_error("Задача не найдена.", 404)
    return JsonResponse({"job": serialize_job(job)})


@require_GET
def api_transfer_report(request, job_id):
    job = TransferJob.objects.filter(pk=job_id, session_fingerprint=session_fingerprint(request)).first()
    if not job:
        return api_error("Задача не найдена.", 404)
    if job.status != TransferJob.Status.SUCCEEDED:
        return api_error("Отчёт появится после завершения переноса.", 409)
    return JsonResponse({"report": job.result.get("report", [])})


@require_GET
def api_openapi(request):
    schema = {
        "openapi": "3.1.0",
        "info": {"title": "VK to Spotify API", "version": "1.0.0"},
        "servers": [{"url": "/api/v1"}],
        "paths": {
            "/status/": {"get": {"summary": "Состояние подключений", "responses": {"200": {"description": "Connection state"}}}},
            "/transfers/": {"post": {
                "summary": "Запустить перенос",
                "description": "Требует браузерную сессию и CSRF-токен.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["source_url"], "properties": {
                        "source_url": {"type": "string", "format": "uri"},
                        "target_playlist": {"type": "string"},
                    },
                }}}},
                "responses": {"202": {"description": "Задача поставлена в очередь"}, "400": {"description": "Ошибка запроса"}},
            }},
            "/transfers/{job_id}/": {"get": {"summary": "Получить прогресс задачи", "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}], "responses": {"200": {"description": "Состояние задачи"}}}},
            "/transfers/{job_id}/report/": {"get": {"summary": "Получить отчёт", "responses": {"200": {"description": "Отчёт в JSON"}}}},
        },
    }
    return JsonResponse(schema)
