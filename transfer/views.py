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
