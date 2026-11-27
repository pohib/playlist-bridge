"""HTTP endpoints for creating and inspecting transfer jobs."""
import json
import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from ..credentials import get_session_fingerprint
from ..oauth_views import encryption_key_is_valid
from ..services import parse_vk_playlist_url
from ..services.api_transfer_service import (
    create_or_reuse_transfer_job,
    get_transfer_job_for_session,
    get_transfer_report_for_session,
    has_spotify_connection,
)
from .common import api_error
from .serializers import serialize_job


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
    if not has_spotify_connection(fingerprint):
        return api_error("Сначала подключи Spotify.", 401)
    job, status, error = create_or_reuse_transfer_job(
        session_fingerprint=fingerprint,
        source_url=source_url,
        target_playlist=normalized_target,
    )
    if error:
        return api_error(error, status)
    return JsonResponse({"job": serialize_job(job)}, status=status)


@never_cache
@require_GET
def api_transfer_detail(request, job_id):
    job = get_transfer_job_for_session(
        job_id=job_id,
        session_fingerprint=get_session_fingerprint(request),
    )
    if not job:
        return api_error("Задача не найдена.", 404)
    return JsonResponse({"job": serialize_job(job)})


@never_cache
@require_GET
def api_transfer_report(request, job_id):
    result = get_transfer_report_for_session(
        job_id=job_id,
        session_fingerprint=get_session_fingerprint(request),
    )
    if result is None:
        return api_error("Задача не найдена.", 404)
    job, report = result
    if job.status != "succeeded":
        return api_error("Отчёт появится после завершения переноса.", 409)
    return JsonResponse({"report": report})
