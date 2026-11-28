"""Staff-only, permission-scoped Playlist Bridge control panel."""
import logging
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

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
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AdminAuditEvent, LibraryPlaylist, LibraryProfile, TransferJob, UserSecurityEvent

logger = logging.getLogger(__name__)


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
    }
    return render(request, "transfer/admin_console/dashboard.html", context)


def _system_check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {
            "status": "ok",
            "label": "База данных",
            "detail": "Подключение и простой запрос выполняются.",
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
def console_system(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    checks = [_system_check_database(), _system_check_cache(), _system_check_celery_broker(), _system_check_celery_workers()]
    integrations = [
        {"name": "Spotify", "configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET), "detail": "OAuth-реквизиты заданы." if settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET else "Не заданы Client ID и/или Client Secret."},
        {"name": "SoundCloud", "configured": bool(settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET), "detail": "OAuth-реквизиты заданы." if settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET else "Не заданы Client ID и/или Client Secret."},
        {"name": "VK", "configured": bool(settings.VK_API_VERSION), "detail": "Версия API задана." if settings.VK_API_VERSION else "Не задана версия API."},
        {"name": "Шифрование токенов", "configured": bool(settings.TOKEN_ENCRYPTION_KEY), "detail": "Ключ шифрования задан." if settings.TOKEN_ENCRYPTION_KEY else "Ключ шифрования не задан."},
    ]
    return render(request, "transfer/admin_console/system.html", {"checks": checks, "integrations": integrations, "debug_enabled": settings.DEBUG, "secure_redirect": settings.SECURE_SSL_REDIRECT})


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
        "privilege.updated": "Изменены привилегии пользователя",
    }
    for event in audit_events:
        event.action_label = action_labels.get(event.action, "Системное действие")
    can_change_users = request.user.has_perm("auth.change_user")
    current_groups = list(account.groups.prefetch_related("permissions__content_type").order_by("name"))
    has_unsafe_groups = any(not _is_safe_group(group) for group in current_groups)
    for group in current_groups:
        group.is_safe_role = _is_safe_group(group)
    can_manage_groups = (
        can_change_users
        and request.user.has_perm("auth.view_group")
        and account.pk != request.user.pk
        and not account.is_superuser
        and not has_unsafe_groups
    )
    safe_groups = Group.objects.prefetch_related("permissions__content_type").order_by("name")
    safe_groups = [group for group in safe_groups if _is_safe_group(group)]
    security_events = []
    if request.user.is_superuser:
        security_events = list(UserSecurityEvent.objects.filter(user=account)[:30])
        AdminAuditEvent.objects.create(
            actor=request.user,
            action="security.user_events_viewed",
            target_type=user_model._meta.label,
            target_id=str(account.pk),
            metadata={"event_count": len(security_events)},
        )
    return render(request, "transfer/admin_console/user_detail.html", {
        "account": account,
        "security_events": security_events,
        "can_view_security": request.user.is_superuser,
        "groups": current_groups,
        "safe_groups": safe_groups,
        "has_unsafe_groups": has_unsafe_groups,
        "can_manage_groups": can_manage_groups,
        "permissions": account.user_permissions.all().order_by(
            "content_type__app_label", "codename"
        ),
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
@permission_required("transfer.view_transferjob", raise_exception=True)
@require_GET
def console_jobs(request):
    status = (request.GET.get("status") or "").strip()
    query = (request.GET.get("q") or "").strip()[:100]
    jobs = TransferJob.objects.all()
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
    return render(request, "transfer/admin_console/jobs.html", {
        "page": page, "status": status, "query": query,
        "statuses": TransferJob.Status.choices,
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
    date_from = parse_date((request.GET.get("date_from") or "").strip())
    date_to = parse_date((request.GET.get("date_to") or "").strip())
    events = UserSecurityEvent.objects.select_related("user")
    valid_types = {value for value, _label in UserSecurityEvent.EventType.choices}
    if event_type in valid_types:
        events = events.filter(event_type=event_type)
    else:
        event_type = ""
    if query:
        events = events.filter(
            Q(username_snapshot__icontains=query)
            | Q(ip_address__icontains=query)
            | Q(user_agent__icontains=query)
        )
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    AdminAuditEvent.objects.create(
        actor=request.user,
        action="security.events_viewed",
        target_type="transfer.UserSecurityEvent",
        metadata={"event_count": len(page.object_list), "filters_applied": bool(query or event_type or date_from or date_to)},
    )
    return render(request, "transfer/admin_console/security.html", {
        "page": page, "query": query, "event_type": event_type,
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "event_types": UserSecurityEvent.EventType.choices,
    })



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
    return render(request, "transfer/admin_console/groups.html", {
        "groups": groups,
        "safe_permissions": _safe_role_permissions(),
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
