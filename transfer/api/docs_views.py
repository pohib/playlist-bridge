"""Public API documentation, OpenAPI schema and API fallback views."""
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .common import api_error


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
                    "503": {"description": "Сервис временно недоступен или не настроено шифрование credentials"},
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
