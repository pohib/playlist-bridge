"""Generic, non-disclosing HTML and JSON error handlers."""
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from .api.common import api_error


def _is_api_request(request):
    return request.path == "/api" or request.path.startswith("/api/")


@never_cache
def page_not_found(request, exception=None):
    if _is_api_request(request):
        return api_error("API endpoint not found.", 404)
    return render(
        request,
        "transfer/errors/error.html",
        {
            "status_code": 404,
            "title": "Страница не найдена",
            "description": "Возможно, адрес изменился или страница больше недоступна.",
            "home_url": "/",
        },
        status=404,
    )


@never_cache
def permission_denied(request, exception=None):
    if _is_api_request(request):
        return api_error("Permission denied.", 403)
    return render(
        request,
        "transfer/errors/error.html",
        {
            "status_code": 403,
            "title": "Недостаточно прав",
            "description": "У вашей учётной записи нет доступа к запрошенному ресурсу.",
            "home_url": "/",
        },
        status=403,
    )


@never_cache
def server_error(request):
    if _is_api_request(request):
        return api_error("Internal server error.", 500)
    return render(
        request,
        "transfer/errors/error.html",
        {
            "status_code": 500,
            "title": "Внутренняя ошибка",
            "description": "Не удалось обработать запрос. Попробуйте повторить попытку позже.",
            "home_url": "/",
        },
        status=500,
    )


@never_cache
def bad_request(request, exception=None):
    if _is_api_request(request):
        return api_error("Bad request.", 400)
    return render(
        request,
        "transfer/errors/error.html",
        {
            "status_code": 400,
            "title": "Некорректный запрос",
            "description": "Проверьте адрес и параметры запроса.",
            "home_url": "/",
        },
        status=400,
    )
