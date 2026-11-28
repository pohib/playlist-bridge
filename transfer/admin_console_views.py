"""Staff-only, permission-scoped Playlist Bridge control panel."""
import ipaddress
import logging
import re
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, connection, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AdminAuditEvent,
    LibraryPlaylist,
    LibraryProfile,
    ProviderIntegrationEvent,
    TransferJob,
    UserAccountBan,
    UserIPBan,
    UserSecurityEvent,
)

logger = logging.getLogger(__name__)


_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|passwd|authorization|proxy-authorization|cookie|set-cookie|api[_-]?key)\b(\s*[:=]\s*)(?:Bearer\s+\S+|Basic\s+\S+|[^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*")
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|client_secret|api_key|key)=)[^&#\s]+"
)


def _safe_admin_error(error):
    """Redact common credential formats before showing provider errors to staff."""
    if not error:
        return "—"
    safe_error = str(error)
    safe_error = _SECRET_VALUE_PATTERN.sub(r"\1\2[скрыто]", safe_error)
    safe_error = _BEARER_PATTERN.sub(r"\1 [скрыто]", safe_error)
    safe_error = _SENSITIVE_QUERY_PATTERN.sub(r"\1[скрыто]", safe_error)
    return safe_error[:500]

def _staff(view):
    @wraps(view)
    @staff_member_required(login_url="login")
    def wrapped(request, *args, **kwargs):
        return view(request, *args, **kwargs)
    return never_cache(wrapped)


@_staff
@require_GET
def console_dashboard(request):
    permissions = {
        "can_view_users": request.user.has_perm("auth.view_user"),
        "can_view_library": request.user.has_perm("transfer.view_libraryprofile"),
        "can_view_jobs": request.user.has_perm("transfer.view_transferjob"),
        "can_view_audit": request.user.has_perm("transfer.view_adminevent"),
    }
    if not any(permissions.values()):
        raise PermissionDenied
    context = {
        **permissions,
        "user_count": get_user_model().objects.count() if permissions["can_view_users"] else None,
        "profile_count": LibraryProfile.objects.count() if permissions["can_view_library"] else None,
        "playlist_count": LibraryPlaylist.objects.count() if permissions["can_view_library"] else None,
        "queued_count": TransferJob.objects.filter(status=TransferJob.Status.QUEUED).count() if permissions["can_view_jobs"] else None,
        "running_count": TransferJob.objects.filter(status=TransferJob.Status.RUNNING).count() if permissions["can_view_jobs"] else None,
        "failed_count": TransferJob.objects.filter(status=TransferJob.Status.FAILED).count() if permissions["can_view_jobs"] else None,
        "recent_jobs": TransferJob.objects.only(
            "id", "status", "progress", "total", "created_at", "error"
        )[:8] if permissions["can_view_jobs"] else [],
        "recent_events": AdminAuditEvent.objects.select_related("actor")[:6] if permissions["can_view_audit"] else [],
        "can_view_operational_analytics": request.user.is_superuser,
        "request_error_counts": None,
        "top_error_routes": [],
        "recent_request_errors": [],
    }
    if request.user.is_superuser:
        day_ago = timezone.now() - timedelta(hours=24)
        week_ago = timezone.now() - timedelta(days=7)
        audited_requests = UserSecurityEvent.objects.filter(
            event_type=UserSecurityEvent.EventType.USER_ACTIVITY
        )
        errors_24h = audited_requests.filter(created_at__gte=day_ago, response_status__gte=400)
        errors_7d = audited_requests.filter(created_at__gte=week_ago, response_status__gte=400)
        context["request_error_counts"] = {
            "total_24h": errors_24h.count(),
            "server_24h": errors_24h.filter(response_status__gte=500).count(),
            "total_7d": errors_7d.count(),
            "server_7d": errors_7d.filter(response_status__gte=500).count(),
        }
        context["top_error_routes"] = list(
            errors_7d.values("route_name").annotate(total=Count("id"))
            .order_by("-total", "route_name")[:5]
        )
        context["recent_request_errors"] = errors_24h.select_related("user")[:8]
    return render(request, "transfer/admin_console/dashboard.html", context)


def _system_check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            detail = "Подключение и простой запрос выполняются."
            status = "ok"
            if connection.vendor == "postgresql":
                cursor.execute(
                    "SELECT current_setting('max_connections')::int, "
                    "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database())"
                )
                max_connections, used_connections = cursor.fetchone()
                detail = f"PostgreSQL: занято {used_connections} из {max_connections} подключений."
                if max_connections and used_connections / max_connections >= 0.8:
                    status = "warning"
                    detail += " Лимит близок к исчерпанию."
        return {
            "status": status,
            "label": "База данных",
            "detail": detail,
        }
    except DatabaseError:
        logger.exception("Admin system health check: database probe failed")
        return {
            "status": "error",
            "label": "База данных",
            "detail": "Не удалось выполнить проверочный запрос.",
        }


def _system_check_cache():
    from uuid import uuid4

    key = f"control:health:{uuid4().hex}"
    try:
        cache.set(key, "ok", timeout=5)
        if cache.get(key) != "ok":
            raise RuntimeError("Cache read-after-write check failed")
        return {
            "status": "ok",
            "label": "Redis / кэш",
            "detail": "Запись и чтение тестового значения работают.",
        }
    except Exception:
        logger.exception("Admin system health check: cache probe failed")
        return {
            "status": "error",
            "label": "Redis / кэш",
            "detail": "Проверка записи или чтения завершилась ошибкой.",
        }


def _system_check_celery_broker():
    try:
        from config.celery import app as celery_app

        with celery_app.connection_for_read(connect_timeout=1) as broker_connection:
            broker_connection.ensure_connection(max_retries=0)
        return {
            "status": "ok",
            "label": "Celery broker",
            "detail": "Соединение с брокером установлено.",
        }
    except Exception:
        logger.exception("Admin system health check: Celery broker probe failed")
        return {
            "status": "error",
            "label": "Celery broker",
            "detail": "Не удалось подключиться к брокеру задач.",
        }


def _system_check_celery_workers():
    try:
        from config.celery import app as celery_app

        workers = celery_app.control.ping(timeout=1)
        if workers:
            names = ", ".join(sorted(item["worker"] for item in workers if item.get("worker")))
            return {
                "status": "ok",
                "label": "Celery workers",
                "detail": f"Отвечают: {names}.",
            }
        return {
            "status": "warning",
            "label": "Celery workers",
            "detail": "Брокер не сообщил об активных worker-процессах.",
        }
    except Exception:
        logger.exception("Admin system health check: Celery worker probe failed")
        return {
            "status": "warning",
            "label": "Celery workers",
            "detail": "Не удалось получить ответ от worker-процессов.",
        }


@_staff
@require_GET
def console_integrations(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    now = timezone.now()
    events = ProviderIntegrationEvent.objects.select_related("transfer_job")
    provider = (request.GET.get("provider") or "").strip()
    category = (request.GET.get("category") or "").strip()
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()
    query = (request.GET.get("q") or "").strip()[:100]
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)

    valid_providers = {value for value, _label in ProviderIntegrationEvent.Provider.choices}
    valid_categories = {value for value, _label in ProviderIntegrationEvent.Category.choices}
    if provider in valid_providers:
        events = events.filter(provider=provider)
    else:
        provider = ""
    if category in valid_categories:
        events = events.filter(category=category)
    else:
        category = ""
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)
    if query:
        events = events.filter(Q(message__icontains=query) | Q(operation__icontains=query))

    summary = ProviderIntegrationEvent.objects.aggregate(
        total=Count("id"),
        last_24h=Count("id", filter=Q(created_at__gte=now - timedelta(hours=24))),
        errors_24h=Count("id", filter=Q(
            created_at__gte=now - timedelta(hours=24),
            severity=ProviderIntegrationEvent.Severity.ERROR,
        )),
        spotify=Count("id", filter=Q(provider=ProviderIntegrationEvent.Provider.SPOTIFY)),
        vk=Count("id", filter=Q(provider=ProviderIntegrationEvent.Provider.VK)),
        soundcloud=Count("id", filter=Q(provider=ProviderIntegrationEvent.Provider.SOUNDCLOUD)),
    )
    page = Paginator(events, 30).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/integrations.html", {
        "page": page,
        "summary": summary,
        "provider": provider,
        "category": category,
        "providers": ProviderIntegrationEvent.Provider.choices,
        "categories": ProviderIntegrationEvent.Category.choices,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
        "query": query,
    })


@_staff
@require_GET
def console_system(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    checks = [_system_check_database(), _system_check_cache(), _system_check_celery_broker(), _system_check_celery_workers()]
    spotify_configured = bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET)
    soundcloud_configured = bool(
        settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET
    )
    integrations = [
        {
            "name": "Spotify · поиск по каталогу",
            "configured": spotify_configured,
            "state_label": "Реквизиты заданы" if spotify_configured else "Не настроено",
            "detail": (
                "Client ID и Secret заданы. Фактический доступ подтверждается только "
                "успешным запросом Spotify API; HTTP 403 означает ограничение на стороне Spotify."
                if spotify_configured
                else "Задай SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET в окружении сервера."
            ),
        },
        {
            "name": "SoundCloud · поиск по каталогу",
            "configured": soundcloud_configured,
            "state_label": "Реквизиты заданы" if soundcloud_configured else "Не настроено",
            "detail": (
                "App-level Client ID и Secret заданы; поиск работает без OAuth-подключения пользователя."
                if soundcloud_configured
                else "Задай SOUNDCLOUD_CLIENT_ID и SOUNDCLOUD_CLIENT_SECRET в окружении сервера."
            ),
        },
        {
            "name": "YouTube Music",
            "configured": False,
            "state_label": "Только ссылка",
            "detail": "Открывается поисковая страница. Официальный публичный API каталога YouTube Music не подключён.",
        },
        {
            "name": "Apple Music",
            "configured": False,
            "state_label": "Только ссылка",
            "detail": "Открывается поисковая страница. Для поиска по каталогу нужна интеграция Apple Music API и developer token.",
        },
        {
            "name": "VK",
            "configured": bool(settings.VK_API_VERSION),
            "state_label": "Настроено" if settings.VK_API_VERSION else "Не настроено",
            "detail": "Версия API задана." if settings.VK_API_VERSION else "Не задана версия API.",
        },
        {
            "name": "Шифрование токенов",
            "configured": bool(settings.TOKEN_ENCRYPTION_KEY),
            "state_label": "Настроено" if settings.TOKEN_ENCRYPTION_KEY else "Не настроено",
            "detail": "Ключ шифрования задан." if settings.TOKEN_ENCRYPTION_KEY else "Ключ шифрования не задан.",
        },
    ]
    database_backend = {"postgresql": "PostgreSQL", "sqlite": "SQLite"}.get(connection.vendor, connection.vendor)
    return render(request, "transfer/admin_console/system.html", {"checks": checks, "integrations": integrations, "debug_enabled": settings.DEBUG, "secure_redirect": settings.SECURE_SSL_REDIRECT, "database_backend": database_backend, "database_backend_is_sqlite": connection.vendor == "sqlite"})


@_staff
@permission_required("auth.view_user", raise_exception=True)
@require_GET
def console_users(request):
    query = (request.GET.get("q") or "").strip()[:100]
    status = (request.GET.get("status") or "").strip()
    access = (request.GET.get("access") or "").strip()
    users = get_user_model().objects.all().order_by("-date_joined")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    if status in {"active", "inactive"}:
        users = users.filter(is_active=(status == "active"))
    else:
        status = ""
    if access == "staff":
        users = users.filter(is_staff=True)
    elif access == "users":
        users = users.filter(is_staff=False)
    else:
        access = ""
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/users.html", {
        "page": page,
        "query": query,
        "status": status,
        "access": access,
        "can_change_users": request.user.has_perm("auth.change_user"),
    })

@_staff
@permission_required("auth.view_user", raise_exception=True)
@require_GET
def console_user_detail(request, user_id):
    user_model = get_user_model()
    account = get_object_or_404(
        user_model.objects.prefetch_related("groups", "user_permissions__content_type"),
        pk=user_id,
    )
    audit_events = AdminAuditEvent.objects.filter(
        target_type=user_model._meta.label,
        target_id=str(account.pk),
    ).select_related("actor")[:20]
    action_labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
        "user.groups_updated": "Группы пользователя изменены",
        "auth.login_failed": "Неудачная попытка входа сотрудника",
        "auth.login_throttled": "Попытка входа заблокирована ограничителем",
        "auth.login_succeeded": "Сотрудник вошёл в систему",
        "security.user_events_viewed": "Просмотрена история безопасности пользователя",
        "security.events_viewed": "Просмотрен журнал безопасности",
        "security.ip_banned": "IP-адрес заблокирован",
        "security.ip_ban_revoked": "Блокировка IP снята",
        "user.account_banned": "Учётная запись заблокирована",
        "user.account_ban_revoked": "Ограничение учётной записи снято",
        "privilege.updated": "Изменены привилегии пользователя",
    }
    for event in audit_events:
        event.action_label = action_labels.get(event.action, "Системное действие")
    can_change_users = request.user.has_perm("auth.change_user")
    current_groups = list(account.groups.prefetch_related("permissions__content_type").order_by("name"))
    has_unsafe_groups = any(not _is_safe_group(group) for group in current_groups)
    for group in current_groups:
        group.is_safe_role = _is_safe_group(group)
        for permission in group.permissions.all():
            _present_permission(permission)
    can_manage_groups = (
        can_change_users
        and request.user.has_perm("auth.view_group")
        and account.pk != request.user.pk
        and not account.is_superuser
        and not has_unsafe_groups
    )
    safe_groups = Group.objects.prefetch_related("permissions__content_type").order_by("name")
    safe_groups = [group for group in safe_groups if _is_safe_group(group)]
    for group in safe_groups:
        for permission in group.permissions.all():
            _present_permission(permission)
    security_events = []
    security_page = None
    security_filters = {
        "activity_type": "",
        "activity_ip": "",
        "activity_route": "",
        "activity_status": "",
        "activity_date_from": request.GET.get("activity_date_from", ""),
        "activity_date_to": request.GET.get("activity_date_to", ""),
    }
    security_summary = None
    if request.user.is_superuser:
        recent_activity = UserSecurityEvent.objects.filter(
            user=account, created_at__gte=timezone.now() - timedelta(days=30)
        )
        security_summary = recent_activity.aggregate(
            successful_logins=Count("id", filter=Q(event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED)),
            failed_logins=Count("id", filter=Q(event_type=UserSecurityEvent.EventType.LOGIN_FAILED)),
            throttled_logins=Count("id", filter=Q(event_type=UserSecurityEvent.EventType.LOGIN_THROTTLED)),
            user_actions=Count("id", filter=Q(event_type=UserSecurityEvent.EventType.USER_ACTIVITY)),
            failed_requests=Count(
                "id",
                filter=Q(event_type=UserSecurityEvent.EventType.USER_ACTIVITY, response_status__gte=400),
            ),
            server_errors=Count(
                "id",
                filter=Q(event_type=UserSecurityEvent.EventType.USER_ACTIVITY, response_status__gte=500),
            ),
        )
        activity_queryset = UserSecurityEvent.objects.filter(user=account)
        valid_event_types = {value for value, _label in UserSecurityEvent.EventType.choices}
        activity_type = (request.GET.get("activity_type") or "").strip()
        if activity_type in valid_event_types:
            activity_queryset = activity_queryset.filter(event_type=activity_type)
            security_filters["activity_type"] = activity_type
        activity_ip = (request.GET.get("activity_ip") or "").strip()[:45]
        if activity_ip:
            activity_queryset = activity_queryset.filter(ip_address=activity_ip)
            security_filters["activity_ip"] = activity_ip
        activity_route = (request.GET.get("activity_route") or "").strip()[:100]
        if activity_route:
            activity_queryset = activity_queryset.filter(
                event_type=UserSecurityEvent.EventType.USER_ACTIVITY,
                route_name=activity_route,
            )
            security_filters["activity_route"] = activity_route
        raw_activity_status = (request.GET.get("activity_status") or "").strip()
        activity_status = None
        if raw_activity_status.isdigit():
            candidate_status = int(raw_activity_status)
            if 100 <= candidate_status <= 599:
                activity_status = candidate_status
                activity_queryset = activity_queryset.filter(
                    event_type=UserSecurityEvent.EventType.USER_ACTIVITY,
                    response_status=activity_status,
                )
                security_filters["activity_status"] = str(activity_status)
        activity_date_from = parse_date(security_filters["activity_date_from"])
        activity_date_to = parse_date(security_filters["activity_date_to"])
        if activity_date_from:
            activity_queryset = activity_queryset.filter(created_at__date__gte=activity_date_from)
        if activity_date_to:
            activity_queryset = activity_queryset.filter(created_at__date__lte=activity_date_to)
        security_page = Paginator(activity_queryset, 20).get_page(request.GET.get("activity_page"))
        security_events = list(security_page.object_list)
        security_filters["activity_count"] = security_page.paginator.count
        security_filters["event_types"] = UserSecurityEvent.EventType.choices
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="security.user_events_viewed",
            target_type=user_model._meta.label,
            target_id=str(account.pk),
            metadata={
                "event_count": len(security_events),
                "filters_applied": bool(
                    security_filters["activity_type"] or security_filters["activity_ip"]
                    or security_filters["activity_route"] or security_filters["activity_status"]
                    or activity_date_from or activity_date_to
                ),
            },
        )
    individual_permissions = list(account.user_permissions.all().order_by(
        "content_type__app_label", "codename"
    ))
    for permission in individual_permissions:
        _present_permission(permission)
    return render(request, "transfer/admin_console/user_detail.html", {
        "account": account,
        "account_bans": UserAccountBan.objects.filter(user=account).select_related("created_by", "revoked_by")[:30],
        "can_manage_account_bans": request.user.has_perm("auth.change_user") and account.pk != request.user.pk and not account.is_superuser,
        "security_events": security_events,
        "security_page": security_page,
        "security_filters": security_filters,
        "security_summary": security_summary,
        "ip_bans": UserIPBan.objects.filter(revoked_at__isnull=True).order_by("-created_at")[:50] if request.user.is_superuser else [],
        "can_manage_ip_bans": request.user.is_superuser,
        "can_view_security": request.user.is_superuser,
        "groups": current_groups,
        "safe_groups": safe_groups,
        "has_unsafe_groups": has_unsafe_groups,
        "can_manage_groups": can_manage_groups,
        "permissions": individual_permissions,
        "audit_events": audit_events,
        "can_toggle_account": (
            can_change_users and account.pk != request.user.pk and not account.is_superuser
        ),
    })


@_staff
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_toggle_user(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk or target.is_superuser:
        raise PermissionDenied("Нельзя менять состояние собственной или superuser-учётной записи.")
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="user.activated" if target.is_active else "user.deactivated",
        target_type=get_user_model()._meta.label,
        target_id=str(target.pk),
        metadata={"username": target.get_username(), "is_active": target.is_active},
    )
    messages.success(
        request,
        f"Учётная запись {target.get_username()} "
        f"{'активирована' if target.is_active else 'деактивирована'}.",
    )
    return redirect("admin_console_users")




@_staff
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_create_account_ban(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk or target.is_superuser:
        raise PermissionDenied("Нельзя блокировать собственную или superuser-учётную запись.")
    reason = (request.POST.get("reason") or "").strip()[:240]
    if not reason:
        messages.error(request, "Укажите причину блокировки.")
        return redirect("admin_console_user_detail", user_id=target.pk)
    raw_hours = (request.POST.get("duration_hours") or "").strip()
    expires_at = None
    if raw_hours:
        try:
            hours = int(raw_hours)
            if not 1 <= hours <= 8760:
                raise ValueError
            expires_at = timezone.now() + timedelta(hours=hours)
        except ValueError:
            messages.error(request, "Срок блокировки должен быть от 1 до 8760 часов.")
            return redirect("admin_console_user_detail", user_id=target.pk)
    ban = UserAccountBan.objects.create(user=target, reason=reason, created_by=request.user, expires_at=expires_at)
    AdminAuditEvent.objects.create(actor=request.user, action="user.account_banned", target_type=get_user_model()._meta.label, target_id=str(target.pk), metadata={"ban_id": str(ban.pk), "expires_at": expires_at.isoformat() if expires_at else None})
    messages.success(request, f"Доступ для {target.get_username()} ограничен.")
    return redirect("admin_console_user_detail", user_id=target.pk)


@_staff
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_revoke_account_ban(request, user_id, ban_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk or target.is_superuser:
        raise PermissionDenied("Нельзя изменять собственную или superuser-учётную запись.")
    ban = get_object_or_404(UserAccountBan, pk=ban_id, user=target, revoked_at__isnull=True)
    ban.revoked_at, ban.revoked_by = timezone.now(), request.user
    ban.save(update_fields=["revoked_at", "revoked_by"])
    AdminAuditEvent.objects.create(actor=request.user, action="user.account_ban_revoked", target_type=get_user_model()._meta.label, target_id=str(target.pk), metadata={"ban_id": str(ban.pk)})
    messages.success(request, "Ограничение снято.")
    return redirect("admin_console_user_detail", user_id=target.pk)

@_staff
@require_POST
def console_ban_ip(request, user_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    target = get_object_or_404(get_user_model(), pk=user_id)
    try:
        address = str(ipaddress.ip_address((request.POST.get("ip_address") or "").strip()))
    except ValueError:
        messages.error(request, "Укажите корректный IP-адрес.")
        return redirect("admin_console_user_detail", user_id=target.pk)
    reason = (request.POST.get("reason") or "").strip()[:240]
    if not reason:
        messages.error(request, "Укажите причину блокировки.")
        return redirect("admin_console_user_detail", user_id=target.pk)
    raw_hours = (request.POST.get("duration_hours") or "").strip()
    expires_at = None
    if raw_hours:
        try:
            hours = int(raw_hours)
            if not 1 <= hours <= 8760:
                raise ValueError
            expires_at = timezone.now() + timedelta(hours=hours)
        except ValueError:
            messages.error(request, "Срок блокировки должен быть от 1 до 8760 часов.")
            return redirect("admin_console_user_detail", user_id=target.pk)
    ban = UserIPBan.objects.create(ip_address=address, reason=reason, created_by=request.user, expires_at=expires_at)
    AdminAuditEvent.objects.create(actor=request.user, action="security.ip_banned", target_type="transfer.UserIPBan", target_id=str(ban.pk), metadata={"ip_address": address, "user_id": target.pk})
    messages.success(request, f"IP-адрес {address} заблокирован.")
    return redirect("admin_console_user_detail", user_id=target.pk)


@_staff
@require_POST
def console_revoke_ip_ban(request, user_id, ban_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    target = get_object_or_404(get_user_model(), pk=user_id)
    ban = get_object_or_404(UserIPBan, pk=ban_id, revoked_at__isnull=True)
    ban.revoked_at, ban.revoked_by = timezone.now(), request.user
    ban.save(update_fields=["revoked_at", "revoked_by"])
    AdminAuditEvent.objects.create(actor=request.user, action="security.ip_ban_revoked", target_type="transfer.UserIPBan", target_id=str(ban.pk), metadata={"ip_address": str(ban.ip_address), "user_id": target.pk})
    messages.success(request, f"Блокировка IP {ban.ip_address} снята.")
    return redirect("admin_console_user_detail", user_id=target.pk)



@_staff
@require_GET
def console_ip_bans(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    query = (request.GET.get("q") or "").strip()[:100]
    status = (request.GET.get("status") or "active").strip()
    now = timezone.now()
    bans = UserIPBan.objects.select_related("created_by", "revoked_by")
    active_filter = Q(revoked_at__isnull=True) & (
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    expired_filter = Q(revoked_at__isnull=True, expires_at__lte=now)
    if status == "active":
        bans = bans.filter(active_filter)
    elif status == "expired":
        bans = bans.filter(expired_filter)
    elif status == "revoked":
        bans = bans.filter(revoked_at__isnull=False)
    else:
        status = "all"
    if query:
        bans = bans.filter(
            Q(ip_address__icontains=query)
            | Q(reason__icontains=query)
            | Q(created_by__username__icontains=query)
            | Q(revoked_by__username__icontains=query)
        )
    page = Paginator(bans.order_by("-created_at"), 30).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "query": query,
        "status": status,
        "now": now,
        "active_count": UserIPBan.objects.filter(active_filter).count(),
        "expired_count": UserIPBan.objects.filter(expired_filter).count(),
        "revoked_count": UserIPBan.objects.filter(revoked_at__isnull=False).count(),
    }
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.ip_bans_viewed",
        target_type="transfer.UserIPBan",
        metadata={"result_count": page.paginator.count, "status": status, "search": bool(query)},
    )
    return render(request, "transfer/admin_console/ip_bans.html", context)


@_staff
@require_POST
def console_create_ip_ban(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    try:
        address = str(ipaddress.ip_address((request.POST.get("ip_address") or "").strip()))
    except ValueError:
        messages.error(request, "Укажите корректный IP-адрес.")
        return redirect("admin_console_ip_bans")
    reason = (request.POST.get("reason") or "").strip()[:240]
    if not reason:
        messages.error(request, "Укажите причину блокировки.")
        return redirect("admin_console_ip_bans")
    raw_hours = (request.POST.get("duration_hours") or "").strip()
    expires_at = None
    if raw_hours:
        try:
            hours = int(raw_hours)
            if not 1 <= hours <= 8760:
                raise ValueError
            expires_at = timezone.now() + timedelta(hours=hours)
        except ValueError:
            messages.error(request, "Срок блокировки должен быть от 1 до 8760 часов.")
            return redirect("admin_console_ip_bans")
    ban = UserIPBan.objects.create(
        ip_address=address,
        reason=reason,
        created_by=request.user,
        expires_at=expires_at,
    )
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.ip_banned",
        target_type="transfer.UserIPBan",
        target_id=str(ban.pk),
        metadata={"ip_address": address, "source": "ip_ban_registry", "created": True},
    )
    messages.success(request, f"IP-адрес {address} заблокирован.")
    return redirect("admin_console_ip_bans")


@_staff
@require_POST
def console_revoke_ip_ban_global(request, ban_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    ban = get_object_or_404(UserIPBan, pk=ban_id, revoked_at__isnull=True)
    ban.revoked_at, ban.revoked_by = timezone.now(), request.user
    ban.save(update_fields=["revoked_at", "revoked_by"])
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.ip_ban_revoked",
        target_type="transfer.UserIPBan",
        target_id=str(ban.pk),
        metadata={"ip_address": str(ban.ip_address), "source": "ip_ban_registry"},
    )
    messages.success(request, f"Блокировка IP {ban.ip_address} снята.")
    return redirect("admin_console_ip_bans")


@_staff
@permission_required("transfer.view_transferjob", raise_exception=True)
@require_GET
def console_jobs(request):
    status = (request.GET.get("status") or "").strip()
    query = (request.GET.get("q") or "").strip()[:100]
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=5)
    dispatch_retry_cutoff = now - timedelta(seconds=120)
    all_jobs = TransferJob.objects.all()
    job_summary = all_jobs.aggregate(
        queued=Count("id", filter=Q(status=TransferJob.Status.QUEUED)),
        running=Count("id", filter=Q(status=TransferJob.Status.RUNNING)),
        succeeded=Count("id", filter=Q(status=TransferJob.Status.SUCCEEDED)),
        failed=Count("id", filter=Q(status=TransferJob.Status.FAILED)),
        stale_running=Count(
            "id",
            filter=Q(status=TransferJob.Status.RUNNING) & (
                Q(heartbeat_at__lt=stale_cutoff)
                | Q(heartbeat_at__isnull=True, started_at__lt=stale_cutoff)
            ),
        ),
        awaiting_dispatch=Count(
            "id",
            filter=Q(status=TransferJob.Status.QUEUED) & (
                Q(dispatch_attempted_at__isnull=True)
                | Q(dispatch_attempted_at__lte=dispatch_retry_cutoff)
            ),
        ),
        failed_24h=Count(
            "id",
            filter=Q(
                status=TransferJob.Status.FAILED,
                finished_at__gte=now - timedelta(hours=24),
            ),
        ),
    )
    jobs = all_jobs
    valid_statuses = {value for value, _label in TransferJob.Status.choices}
    if status in valid_statuses:
        jobs = jobs.filter(status=status)
    else:
        status = ""
    if query:
        jobs = jobs.filter(Q(source_url__icontains=query) | Q(error__icontains=query))
    page = Paginator(jobs, 25).get_page(request.GET.get("page"))
    for job in page.object_list:
        job.source_host = urlsplit(job.source_url).hostname or "—"
        job.admin_error = _safe_admin_error(job.error)
    return render(request, "transfer/admin_console/jobs.html", {
        "page": page, "status": status, "query": query,
        "statuses": TransferJob.Status.choices,
        "job_summary": job_summary,
    })


@_staff
@permission_required("transfer.view_transferjob", raise_exception=True)
@require_GET
def console_job_detail(request, job_id):
    job = get_object_or_404(TransferJob, pk=job_id)
    profile = LibraryProfile.objects.filter(
        session_fingerprint=job.session_fingerprint
    ).select_related("user").first()
    activity_at = job.heartbeat_at or job.started_at
    stale = bool(
        job.status == TransferJob.Status.RUNNING
        and activity_at
        and activity_at < timezone.now() - timedelta(minutes=5)
    )
    return render(request, "transfer/admin_console/job_detail.html", {
        "job": job, "profile": profile,
        "source_host": urlsplit(job.source_url).hostname or "—",
        "display_error": _safe_admin_error(job.error),
        "stale": stale,
    })


@_staff
@permission_required("transfer.view_libraryprofile", raise_exception=True)
@require_GET
def console_library(request):
    query = (request.GET.get("q") or "").strip()[:100]
    profiles = LibraryProfile.objects.select_related("user").annotate(
        playlists_count=Count("playlists", distinct=True),
        tracks_count=Count("playlists__tracks", distinct=True),
    ).order_by("-updated_at")
    if query:
        profiles = profiles.filter(
            Q(display_name__icontains=query) | Q(user__username__icontains=query)
        )
    page = Paginator(profiles, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/library.html", {
        "page": page, "query": query,
    })


@_staff
@permission_required("transfer.view_libraryprofile", raise_exception=True)
@require_GET
def console_library_detail(request, profile_id):
    profile = get_object_or_404(
        LibraryProfile.objects.select_related("user"), pk=profile_id
    )
    playlists = profile.playlists.annotate(
        tracks_count=Count("tracks", distinct=True)
    ).prefetch_related("tracks").order_by("-updated_at")
    transfers = profile.transfers.select_related(
        "source_playlist", "target_playlist"
    ).order_by("-created_at")[:30]
    return render(request, "transfer/admin_console/library_detail.html", {
        "profile": profile, "playlists": playlists, "transfers": transfers,
        "playlist_count": playlists.count(),
        "track_count": LibraryPlaylist.objects.filter(
            profile=profile
        ).aggregate(total=Count("tracks"))["total"] or 0,
    })


@_staff
@permission_required("transfer.view_adminevent", raise_exception=True)
@require_GET
def console_audit(request):
    query = (request.GET.get("q") or "").strip()[:100]
    action = (request.GET.get("action") or "").strip()[:100]
    date_from = parse_date((request.GET.get("date_from") or "").strip())
    date_to = parse_date((request.GET.get("date_to") or "").strip())
    events = AdminAuditEvent.objects.select_related("actor")
    if query:
        events = events.filter(
            Q(actor__username__icontains=query)
            | Q(target_id__icontains=query)
            | Q(target_type__icontains=query)
            | Q(action__icontains=query)
        )
    if action:
        events = events.filter(action=action)
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    action_labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
        "role.created": "Роль создана",
        "role.updated": "Роль изменена",
        "user.groups_updated": "Группы пользователя изменены",
        "auth.login_failed": "Неудачная попытка входа сотрудника",
        "auth.login_throttled": "Попытка входа заблокирована ограничителем",
        "auth.login_succeeded": "Сотрудник вошёл в систему",
        "security.user_events_viewed": "Просмотрена история безопасности пользователя",
        "security.events_viewed": "Просмотрен журнал безопасности",
        "privilege.updated": "Изменены привилегии пользователя",
    }
    for event in page.object_list:
        event.action_label = action_labels.get(event.action, "Системное действие")
    return render(request, "transfer/admin_console/audit.html", {
        "page": page, "query": query, "action": action,
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "actions": AdminAuditEvent.objects.order_by().values_list("action", flat=True).distinct(),
    })



@_staff
@require_GET
def console_security(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    query = (request.GET.get("q") or "").strip()[:100]
    event_type = (request.GET.get("event_type") or "").strip()
    raw_response_status = (request.GET.get("response_status") or "").strip()
    response_status = None
    if raw_response_status.isdigit():
        candidate_status = int(raw_response_status)
        if 100 <= candidate_status <= 599:
            response_status = candidate_status
        else:
            raw_response_status = ""
    else:
        raw_response_status = ""
    date_from = parse_date((request.GET.get("date_from") or "").strip())
    date_to = parse_date((request.GET.get("date_to") or "").strip())
    events = UserSecurityEvent.objects.select_related("user")
    valid_types = {value for value, _label in UserSecurityEvent.EventType.choices}
    if event_type in valid_types:
        events = events.filter(event_type=event_type)
    else:
        event_type = ""
    if response_status is not None:
        events = events.filter(
            event_type=UserSecurityEvent.EventType.USER_ACTIVITY,
            response_status=response_status,
        )
    if query:
        search_filter = (
            Q(username_snapshot__icontains=query)
            | Q(ip_address__icontains=query)
            | Q(user_agent__icontains=query)
            | Q(route_name__icontains=query)
            | Q(object_id__icontains=query)
        )
        try:
            search_filter |= Q(request_id=UUID(query))
        except (TypeError, ValueError, AttributeError):
            pass
        events = events.filter(search_filter)
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.events_viewed",
        target_type="transfer.UserSecurityEvent",
        metadata={"event_count": len(page.object_list), "filters_applied": bool(query or event_type or response_status or date_from or date_to)},
    )
    return render(request, "transfer/admin_console/security.html", {
        "page": page, "query": query, "event_type": event_type,
        "response_status": raw_response_status,
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "event_types": UserSecurityEvent.EventType.choices,
    })



@_staff
@require_GET
def console_events(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    now = timezone.now()
    stale_before = now - timedelta(minutes=5)
    acknowledged_keys = set(
        AdminAuditEvent.objects.filter(
            action="events.acknowledged",
            target_type__in=("security", "transfer"),
        ).values_list("target_type", "target_id")
    )
    events = []
    labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
        "role.created": "Роль создана",
        "role.updated": "Роль изменена",
        "user.groups_updated": "Группы пользователя изменены",
        "privilege.updated": "Изменены привилегии пользователя",
        "events.acknowledged": "Событие подтверждено",
    }
    user_label = get_user_model()._meta.label
    for item in (
        AdminAuditEvent.objects.exclude(action="events.center_viewed")
        .select_related("actor")
        .order_by("-created_at")[:300]
    ):
        target_url = (
            reverse("admin_console_user_detail", args=[item.target_id])
            if item.target_type == user_label and item.target_id.isdigit()
            else ""
        )
        events.append({
            "occurred_at": item.created_at,
            "category": "admin",
            "category_label": "Администрирование",
            "severity": "info",
            "severity_label": "Информация",
            "title": labels.get(item.action, "Системное действие"),
            "actor": item.actor.get_username() if item.actor else "Система",
            "target": f"{item.target_type} · {item.target_id}".strip(" ·") or "—",
            "target_url": target_url,
            "detail": "Изменение записано в журнал аудита.",
            "acknowledgeable": False,
            "is_acknowledged": False,
        })

    security_labels = {
        UserSecurityEvent.EventType.LOGIN_SUCCEEDED: ("Успешный вход", "info", "Информация"),
        UserSecurityEvent.EventType.LOGIN_FAILED: ("Неудачная попытка входа", "warning", "Предупреждение"),
        UserSecurityEvent.EventType.LOGIN_THROTTLED: ("Попытка входа ограничена", "danger", "Высокий риск"),
    }
    for item in UserSecurityEvent.objects.exclude(
        event_type=UserSecurityEvent.EventType.USER_ACTIVITY
    ).select_related("user").order_by("-created_at")[:300]:
        title, severity, severity_label = security_labels.get(
            item.event_type,
            ("Событие безопасности", "warning", "Предупреждение"),
        )
        acknowledgeable = item.event_type in {
            UserSecurityEvent.EventType.LOGIN_FAILED,
            UserSecurityEvent.EventType.LOGIN_THROTTLED,
        }
        events.append({
            "occurred_at": item.created_at,
            "category": "security",
            "category_label": "Безопасность",
            "severity": severity,
            "severity_label": severity_label,
            "title": title,
            "actor": item.username_snapshot or "Неизвестный пользователь",
            "target": item.user.get_username() if item.user else "Удалённая учётная запись",
            "target_url": reverse("admin_console_user_detail", args=[item.user_id]) if item.user_id else "",
            "detail": "Событие авторизации. Подробности доступны в журнале безопасности.",
            "acknowledgeable": acknowledgeable,
            "is_acknowledged": ("security", str(item.pk)) in acknowledged_keys,
            "event_type": "security",
            "event_id": str(item.pk),
        })

    failed_jobs = TransferJob.objects.filter(
        status=TransferJob.Status.FAILED
    ).order_by("-finished_at", "-created_at")[:150]
    stale_jobs = TransferJob.objects.filter(status=TransferJob.Status.RUNNING).filter(
        Q(heartbeat_at__lt=stale_before)
        | Q(heartbeat_at__isnull=True, started_at__lt=stale_before)
    ).order_by("heartbeat_at", "started_at")[:150]
    for item in failed_jobs:
        events.append({
            "occurred_at": item.finished_at or item.created_at,
            "category": "transfer",
            "category_label": "Переносы",
            "severity": "danger",
            "severity_label": "Ошибка",
            "title": "Перенос завершился ошибкой",
            "actor": "Система",
            "target": str(item.pk),
            "target_url": reverse("admin_console_job_detail", args=[item.pk]),
            "detail": "Откройте карточку задачи для безопасной диагностики.",
            "acknowledgeable": True,
            "is_acknowledged": ("transfer", str(item.pk)) in acknowledged_keys,
            "event_type": "transfer",
            "event_id": str(item.pk),
        })
    for item in stale_jobs:
        events.append({
            "occurred_at": item.heartbeat_at or item.started_at or item.created_at,
            "category": "transfer",
            "category_label": "Переносы",
            "severity": "warning",
            "severity_label": "Требует внимания",
            "title": "Возможно, задача зависла",
            "actor": "Система",
            "target": str(item.pk),
            "target_url": reverse("admin_console_job_detail", args=[item.pk]),
            "detail": "Нет обновления состояния более пяти минут.",
            "acknowledgeable": True,
            "is_acknowledged": ("transfer", str(item.pk)) in acknowledged_keys,
            "event_type": "transfer",
            "event_id": str(item.pk),
        })

    category = (request.GET.get("category") or "").strip()
    severity = (request.GET.get("severity") or "").strip()
    state = (request.GET.get("state") or "").strip()
    query = (request.GET.get("q") or "").strip()[:100]
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)
    if category in {"admin", "security", "transfer"}:
        events = [event for event in events if event["category"] == category]
    else:
        category = ""
    if severity in {"info", "warning", "danger"}:
        events = [event for event in events if event["severity"] == severity]
    else:
        severity = ""
    if state == "open":
        events = [
            event for event in events
            if event["acknowledgeable"] and not event["is_acknowledged"]
        ]
    elif state == "acknowledged":
        events = [
            event for event in events
            if event["acknowledgeable"] and event["is_acknowledged"]
        ]
    else:
        state = ""
    if query:
        needle = query.casefold()
        events = [
            event for event in events
            if needle in " ".join((
                event["title"], event["actor"], event["target"], event["detail"]
            )).casefold()
        ]
    if date_from:
        events = [
            event for event in events
            if timezone.localtime(event["occurred_at"]).date() >= date_from
        ]
    if date_to:
        events = [
            event for event in events
            if timezone.localtime(event["occurred_at"]).date() <= date_to
        ]
    events.sort(key=lambda event: event["occurred_at"], reverse=True)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="events.center_viewed",
        target_type="transfer.AdminEventFeed",
        metadata={
            "result_count": len(events),
            "filters_applied": bool(category or severity or state or query or date_from or date_to),
        },
    )
    return render(request, "transfer/admin_console/events.html", {
        "page": page,
        "query": query,
        "category": category,
        "severity": severity,
        "state": state,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
    })


@_staff
@require_POST
def console_acknowledge_event(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    event_type = (request.POST.get("event_type") or "").strip()
    raw_event_id = (request.POST.get("event_id") or "").strip()
    try:
        event_id = UUID(raw_event_id)
    except (TypeError, ValueError, AttributeError):
        messages.error(request, "Не удалось определить событие для подтверждения.")
        return redirect("admin_console_events")

    with transaction.atomic():
        if event_type == "security":
            event = get_object_or_404(
                UserSecurityEvent.objects.select_for_update(),
                pk=event_id,
            )
            if event.event_type not in {
                UserSecurityEvent.EventType.LOGIN_FAILED,
                UserSecurityEvent.EventType.LOGIN_THROTTLED,
            }:
                messages.error(request, "Это событие не требует подтверждения.")
                return redirect("admin_console_events")
            target_type = "security"
        elif event_type == "transfer":
            event = get_object_or_404(
                TransferJob.objects.select_for_update(),
                pk=event_id,
            )
            activity_at = event.heartbeat_at or event.started_at
            stale = bool(
                event.status == TransferJob.Status.RUNNING
                and activity_at
                and activity_at < timezone.now() - timedelta(minutes=5)
            )
            if event.status != TransferJob.Status.FAILED and not stale:
                messages.error(request, "Задача больше не требует подтверждения.")
                return redirect("admin_console_events")
            target_type = "transfer"
        else:
            messages.error(request, "Неизвестный тип события.")
            return redirect("admin_console_events")

        already_acknowledged = AdminAuditEvent.objects.filter(
            action="events.acknowledged",
            target_type=target_type,
            target_id=str(event.pk),
        ).exists()
        if already_acknowledged:
            messages.info(request, "Это событие уже подтверждено.")
        else:
            AdminAuditEvent.objects.create(
                actor=request.user,
                action="events.acknowledged",
                target_type=target_type,
                target_id=str(event.pk),
                metadata={"source_event_type": event_type},
            )
            messages.success(request, "Событие отмечено как проверенное.")

    return redirect("admin_console_events")

@_staff
@require_GET
def console_privileges(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    user_model = get_user_model()
    accounts = user_model.objects.all().order_by("-is_superuser", "-is_staff", "username")
    page = Paginator(accounts, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/privileges.html", {
        "page": page,
        "active_superuser_count": user_model.objects.filter(
            is_superuser=True, is_active=True
        ).count(),
    })


@_staff
@require_POST
def console_update_privilege(request, user_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    user_model = get_user_model()
    privilege = (request.POST.get("privilege") or "").strip()
    enabled = request.POST.get("enabled") == "true"
    confirmation = (request.POST.get("confirmation") or "").strip()
    password = request.POST.get("password") or ""
    if privilege not in {"staff", "superuser"}:
        messages.error(request, "Выбран неизвестный тип привилегии.")
        return redirect("admin_console_privileges")
    if not check_password(password, request.user.password):
        messages.error(request, "Не удалось подтвердить пароль суперпользователя.")
        return redirect("admin_console_privileges")
    if privilege == "superuser" and confirmation != "ПОДТВЕРЖДАЮ":
        messages.error(request, "Для изменения прав суперпользователя введи фразу «ПОДТВЕРЖДАЮ».")
        return redirect("admin_console_privileges")
    if str(user_id) == str(request.user.pk):
        messages.error(request, "Нельзя изменять собственные привилегии.")
        return redirect("admin_console_privileges")

    with transaction.atomic():
        list(user_model.objects.select_for_update().filter(is_superuser=True, is_active=True))
        target = get_object_or_404(user_model.objects.select_for_update(), pk=user_id)
        before = {"is_staff": target.is_staff, "is_superuser": target.is_superuser}
        if privilege == "staff" and not enabled and target.is_superuser:
            messages.error(request, "Сначала сними права суперпользователя. Активный суперпользователь должен иметь доступ сотрудника.")
            return redirect("admin_console_privileges")
        if privilege == "staff":
            target.is_staff = enabled
        elif enabled:
            target.is_superuser = True
            target.is_staff = True
        else:
            active_superusers = user_model.objects.filter(
                is_superuser=True, is_active=True
            ).count()
            if target.is_active and target.is_superuser and active_superusers <= 1:
                messages.error(request, "Нельзя снять права: в системе должен остаться хотя бы один активный суперпользователь.")
                return redirect("admin_console_privileges")
            target.is_superuser = False
        after = {"is_staff": target.is_staff, "is_superuser": target.is_superuser}
        if before == after:
            messages.info(request, "Указанные привилегии уже имеют выбранное состояние.")
            return redirect("admin_console_privileges")
        target.save(update_fields=["is_staff", "is_superuser"])
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="privilege.updated",
            target_type=user_model._meta.label,
            target_id=str(target.pk),
            metadata={
                "username": target.get_username(),
                "privilege": privilege,
                "before": before,
                "after": after,
            },
        )
    messages.success(request, f"Привилегии пользователя {target.get_username()} обновлены.")
    return redirect("admin_console_privileges")



_PERMISSION_LABELS = {
    "auth.view_user": (
        "Просмотр учётных записей",
        "Просмотр списка пользователей и карточек аккаунтов. Не позволяет изменять учётные записи.",
    ),
    "transfer.view_libraryprofile": (
        "Просмотр профилей библиотек",
        "Просмотр пользовательских библиотек и связанных профилей. Не даёт доступа к секретам OAuth.",
    ),
    "transfer.view_libraryplaylist": (
        "Просмотр плейлистов",
        "Просмотр названий, состава и метаданных плейлистов.",
    ),
    "transfer.view_transferjob": (
        "Просмотр заданий переноса",
        "Просмотр очереди переносов, их статусов и диагностических сведений.",
    ),
    "transfer.view_adminevent": (
        "Просмотр журнала действий",
        "Просмотр записей об административных действиях без права изменять журнал.",
    ),
}

_PERMISSION_MODEL_LABELS = {
    "user": "учётные записи",
    "group": "группы доступа",
    "permission": "разрешения",
    "libraryprofile": "профили библиотек",
    "libraryplaylist": "плейлисты",
    "librarytrack": "музыкальные композиции",
    "librarytransfer": "переносы библиотек",
    "librarytransferitem": "элементы переноса",
    "transferjob": "задания переноса",
    "adminevent": "записи журнала действий",
    "usersecurityevent": "события безопасности",
    "useripban": "блокировки IP-адресов",
    "usereqpreset": "пользовательские пресеты эквалайзера",
    "oauthcredential": "данные подключения сервисов",
}
_PERMISSION_ACTION_LABELS = {
    "add": "Создание",
    "change": "Изменение",
    "delete": "Удаление",
    "view": "Просмотр",
}


def _present_permission(permission):
    """Attach a Russian, human-readable description without changing its actual grant."""
    key = f"{permission.content_type.app_label}.{permission.codename}"
    known = _PERMISSION_LABELS.get(key)
    if known:
        permission.display_name, permission.display_description = known
        return permission

    action, separator, model = permission.codename.partition("_")
    action_label = _PERMISSION_ACTION_LABELS.get(action)
    model_label = _PERMISSION_MODEL_LABELS.get(model)
    if separator and action_label and model_label:
        permission.display_name = f"{action_label}: {model_label}"
        permission.display_description = (
            f"Разрешает действие «{action_label.lower()}» для объекта «{model_label}»."
        )
    else:
        permission.display_name = "Специальное разрешение"
        permission.display_description = (
            "Разрешение приложения. Перед назначением требуется отдельная проверка его назначения."
        )
    return permission


def _safe_role_permissions():
    """Only expose read-only permissions for explicitly supported admin sections."""
    return Permission.objects.filter(
        content_type__app_label__in=("auth", "transfer"),
        content_type__model__in=(
            "user", "libraryprofile", "libraryplaylist", "transferjob", "adminevent"
        ),
        codename__startswith="view_",
    ).select_related("content_type").order_by(
        "content_type__app_label", "content_type__model", "name"
    )


@_staff
@permission_required("auth.view_group", raise_exception=True)
@require_GET
def console_groups(request):
    from django.contrib.auth.models import Group

    groups = list(Group.objects.annotate(
        members_count=Count("user", distinct=True)
    ).prefetch_related("permissions__content_type").order_by("name"))
    for group in groups:
        group.is_safe_role = _is_safe_group(group)
        for permission in group.permissions.all():
            _present_permission(permission)
    safe_permissions = [_present_permission(item) for item in _safe_role_permissions()]
    return render(request, "transfer/admin_console/groups.html", {
        "groups": groups,
        "safe_permissions": safe_permissions,
        "can_create_groups": request.user.has_perm("auth.add_group"),
        "can_edit_groups": request.user.has_perm("auth.change_group"),
    })


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.add_group", raise_exception=True)
@require_POST
def console_create_group(request):
    from django.contrib.auth.models import Group

    name = (request.POST.get("name") or "").strip()[:150]
    selected_ids = request.POST.getlist("permissions")
    if not name:
        messages.error(request, "Укажите название роли.")
        return redirect("admin_console_groups")
    if Group.objects.filter(name__iexact=name).exists():
        messages.error(request, "Роль с таким названием уже существует.")
        return redirect("admin_console_groups")
    allowed = _safe_role_permissions()
    selected = allowed.filter(pk__in=selected_ids)
    if (
        not selected_ids
        or any(not value.isdecimal() for value in selected_ids)
        or selected.count() != len(set(selected_ids))
    ):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")
    group = Group.objects.create(name=name)
    group.permissions.set(selected)
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="role.created",
        target_type=Group._meta.label,
        target_id=str(group.pk),
        metadata={"name": group.name, "permission_count": selected.count()},
    )
    messages.success(request, f"Роль «{group.name}» создана.")
    return redirect("admin_console_groups")



def _is_safe_group(group):
    """A role is manageable only when every attached permission is allowlisted."""
    allowed_ids = _safe_role_permissions().values("pk")
    return not group.permissions.exclude(pk__in=allowed_ids).exists()


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.change_group", raise_exception=True)
@require_POST
def console_update_group(request, group_id):
    group = get_object_or_404(Group.objects.prefetch_related("permissions__content_type"), pk=group_id)
    if not _is_safe_group(group):
        raise PermissionDenied("Роль содержит права, которыми нельзя управлять через эту панель.")

    name = (request.POST.get("name") or "").strip()[:150]
    selected_ids = request.POST.getlist("permissions")
    if not name:
        messages.error(request, "Укажите название роли.")
        return redirect("admin_console_groups")
    if Group.objects.filter(name__iexact=name).exclude(pk=group.pk).exists():
        messages.error(request, "Роль с таким названием уже существует.")
        return redirect("admin_console_groups")
    if any(not value.isdecimal() for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")

    selected = _safe_role_permissions().filter(pk__in=selected_ids)
    if selected.count() != len(selected_ids):
        messages.error(request, "Выберите только разрешённые права чтения.")
        return redirect("admin_console_groups")

    before = {
        "name": group.name,
        "permissions": sorted(
            f"{item.content_type.app_label}.{item.codename}"
            for item in group.permissions.all()
        ),
    }
    with transaction.atomic():
        group.name = name
        group.save(update_fields=["name"])
        group.permissions.set(selected)
        after = {
            "name": group.name,
            "permissions": sorted(
                f"{item.content_type.app_label}.{item.codename}"
                for item in selected.select_related("content_type")
            ),
        }
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="role.updated",
            target_type=Group._meta.label,
            target_id=str(group.pk),
            metadata={"before": before, "after": after},
        )
    messages.success(request, f"Роль «{group.name}» обновлена.")
    return redirect("admin_console_groups")


@_staff
@permission_required("auth.view_group", raise_exception=True)
@permission_required("auth.change_user", raise_exception=True)
@require_POST
def console_update_user_groups(request, user_id):
    user_model = get_user_model()
    account = get_object_or_404(
        user_model.objects.prefetch_related("groups__permissions__content_type"),
        pk=user_id,
    )
    if account.pk == request.user.pk or account.is_superuser:
        raise PermissionDenied("Нельзя изменять собственные роли или роли суперпользователя.")
    if any(not _is_safe_group(group) for group in account.groups.all()):
        raise PermissionDenied("У пользователя есть роль с расширенными правами. Требуется отдельная проверка.")

    selected_ids = request.POST.getlist("groups")
    if any(not value.isdecimal() for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        messages.error(request, "Выберите только разрешённые роли.")
        return redirect("admin_console_user_detail", user_id=account.pk)

    selected = list(
        Group.objects.filter(pk__in=selected_ids).prefetch_related("permissions__content_type").order_by("name")
    )
    if len(selected) != len(selected_ids) or any(not _is_safe_group(group) for group in selected):
        messages.error(request, "Нельзя назначить роль с расширенными правами.")
        return redirect("admin_console_user_detail", user_id=account.pk)

    before = sorted(
        ({"id": group.pk, "name": group.name} for group in account.groups.all()),
        key=lambda item: item["id"],
    )
    after = sorted(
        ({"id": group.pk, "name": group.name} for group in selected),
        key=lambda item: item["id"],
    )
    with transaction.atomic():
        account.groups.set(selected)
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="user.groups_updated",
            target_type=user_model._meta.label,
            target_id=str(account.pk),
            metadata={"before": before, "after": after},
        )
    messages.success(request, f"Группы пользователя {account.get_username()} обновлены.")
    return redirect("admin_console_user_detail", user_id=account.pk)
