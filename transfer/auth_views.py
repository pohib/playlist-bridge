import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .credentials import get_session_fingerprint
from .forms import AccountCreationForm, AccountLoginForm
from .models import LibraryProfile, OAuthCredential, TransferJob

logger = logging.getLogger(__name__)


def _attach_anonymous_workspace(request, previous_fingerprint):
    current_fingerprint = get_session_fingerprint(request)
    if previous_fingerprint == current_fingerprint:
        return

    with transaction.atomic():
        anonymous_profile = LibraryProfile.objects.filter(
            session_fingerprint=previous_fingerprint,
            user__isnull=True,
        ).first()
        account_profile = LibraryProfile.objects.filter(user=request.user).first()

        if anonymous_profile:
            if account_profile:
                anonymous_profile.playlists.update(profile=account_profile)
                anonymous_profile.transfers.update(profile=account_profile)
                anonymous_profile.delete()
            else:
                anonymous_profile.user = request.user
                anonymous_profile.session_fingerprint = current_fingerprint
                anonymous_profile.save(update_fields=["user", "session_fingerprint", "updated_at"])

        for credential in OAuthCredential.objects.filter(session_fingerprint=previous_fingerprint):
            duplicate = OAuthCredential.objects.filter(
                session_fingerprint=current_fingerprint,
                provider=credential.provider,
            ).exclude(pk=credential.pk).exists()
            if duplicate:
                credential.delete()
            else:
                credential.session_fingerprint = current_fingerprint
                credential.save(update_fields=["session_fingerprint", "updated_at"])

        # Preserve finished reports; avoid violating the one-active-job-per-owner constraint.
        active_exists = TransferJob.objects.filter(
            session_fingerprint=current_fingerprint,
            status__in=(TransferJob.Status.QUEUED, TransferJob.Status.RUNNING),
        ).exists()
        old_jobs = TransferJob.objects.filter(session_fingerprint=previous_fingerprint)
        if active_exists:
            old_jobs.exclude(status__in=(TransferJob.Status.QUEUED, TransferJob.Status.RUNNING)).update(
                session_fingerprint=current_fingerprint
            )
        else:
            old_jobs.update(session_fingerprint=current_fingerprint)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AccountCreationForm(request.POST)
        if form.is_valid():
            previous_fingerprint = get_session_fingerprint(request)
            user = form.save()
            login(request, user)
            _attach_anonymous_workspace(request, previous_fingerprint)
            logger.info("New user account created: user_id=%s", user.pk)
            messages.success(request, "Аккаунт создан. Твоя библиотека теперь привязана к профилю.")
            return redirect("dashboard")
    else:
        form = AccountCreationForm()
    return render(request, "transfer/auth/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AccountLoginForm(request, data=request.POST)
        if form.is_valid():
            previous_fingerprint = get_session_fingerprint(request)
            user = form.get_user()
            login(request, user)
            _attach_anonymous_workspace(request, previous_fingerprint)
            logger.info("User signed in: user_id=%s", user.pk)
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("dashboard")
    else:
        form = AccountLoginForm(request)
    return render(request, "transfer/auth/login.html", {"form": form})


@require_POST
def sign_out(request):
    user_id = request.user.pk if request.user.is_authenticated else None
    logout(request)
    if user_id is not None:
        logger.info("User signed out: user_id=%s", user_id)
    messages.success(request, "Ты вышел из аккаунта.")
    return redirect("home")
