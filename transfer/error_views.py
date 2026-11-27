"""Generic, non-disclosing HTML and JSON error handlers."""
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache

from .api.common import api_error


def _is_api_request(request):
    return request.path == "/api" or request.path.startswith("/api/")


def _html_error(status_code, title, description):
    # Deliberately omit the request from template rendering: error pages must
    # remain renderable when sessions or the database are unavailable.
    content = render_to_string(
        "transfer/errors/error.html",
        {
            "status_code": status_code,
            "title": title,
            "description": description,
            "home_url": "/",
        },
    )
    return HttpResponse(content, status=status_code, content_type="text/html; charset=utf-8")


@never_cache
def page_not_found(request, exception=None):
    if _is_api_request(request):
        return api_error("API endpoint not found.", 404)
    return _html_error(
        404,
        "Страница не найдена",
        "Возможно, адрес изменился или страница больше недоступна.",
    )


@never_cache
def permission_denied(request, exception=None):
    if _is_api_request(request):
        return api_error("Permission denied.", 403)
    return _html_error(
        403,
        "Недостаточно прав",
        "У вашей учётной записи нет доступа к запрошенному ресурсу.",
    )


@never_cache
def server_error(request):
    if _is_api_request(request):
        return api_error("Internal server error.", 500)
    return _html_error(
        500,
        "Внутренняя ошибка",
        "Не удалось обработать запрос. Попробуйте повторить попытку позже.",
    )


@never_cache
def bad_request(request, exception=None):
    if _is_api_request(request):
        return api_error("Bad request.", 400)
    return _html_error(
        400,
        "Некорректный запрос",
        "Проверьте адрес и параметры запроса.",
    )
