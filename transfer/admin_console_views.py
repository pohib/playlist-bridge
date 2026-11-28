"""Staff-only, permission-scoped Playlist Bridge control panel."""
from functools import wraps
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AdminAuditEvent, LibraryPlaylist, LibraryProfile, TransferJob


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


@_staff
@permission_required("auth.view_user", raise_exception=True)
@require_GET
def console_users(request):
    query = (request.GET.get("q") or "").strip()[:100]
    users = get_user_model().objects.all().order_by("-date_joined")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/users.html", {
        "page": page,
        "query": query,
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
    }
    for event in audit_events:
        event.action_label = action_labels.get(event.action, "Системное действие")
    can_change_users = request.user.has_perm("auth.change_user")
    return render(request, "transfer/admin_console/user_detail.html", {
        "account": account,
        "groups": account.groups.all().order_by("name"),
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
        target_type="auth.User",
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
@permission_required("transfer.view_libraryprofile", raise_exception=True)
@require_GET
def console_library(request):
    profiles = LibraryProfile.objects.select_related("user").annotate(
        playlists_count=Count("playlists", distinct=True),
        tracks_count=Count("playlists__tracks", distinct=True),
    ).order_by("-updated_at")
    page = Paginator(profiles, 25).get_page(request.GET.get("page"))
    return render(request, "transfer/admin_console/library.html", {"page": page})


@_staff
@permission_required("transfer.view_adminevent", raise_exception=True)
@require_GET
def console_audit(request):
    page = Paginator(
        AdminAuditEvent.objects.select_related("actor"), 50
    ).get_page(request.GET.get("page"))
    action_labels = {
        "user.activated": "Пользователь активирован",
        "user.deactivated": "Пользователь отключён",
    }
    for event in page.object_list:
        event.action_label = action_labels.get(event.action, "Системное действие")
    return render(request, "transfer/admin_console/audit.html", {"page": page})
