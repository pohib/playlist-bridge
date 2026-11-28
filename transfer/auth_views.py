import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import AccountCreationForm, AccountLoginForm
from .services.account_workspace import attach_anonymous_workspace
from .services.credential_service import get_session_fingerprint
from .services.login_throttle import (
    clear_login_failures,
    login_is_throttled,
    record_login_failure,
)

logger = logging.getLogger(__name__)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AccountCreationForm(request.POST)
        if form.is_valid():
            previous_fingerprint = get_session_fingerprint(request)
            user = form.save()
            login(request, user)
            attach_anonymous_workspace(
                user=user,
                previous_fingerprint=previous_fingerprint,
                current_fingerprint=get_session_fingerprint(request),
            )
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
        username = request.POST.get("username", "")
        try:
            throttled = login_is_throttled(request, username)
        except Exception:
            logger.exception("Login throttling backend is unavailable")
            form.add_error(None, "Авторизация временно недоступна. Попробуй немного позже.")
            return render(request, "transfer/auth/login.html", {"form": form}, status=503)

        if throttled:
            form.add_error(
                None,
                "Слишком много неудачных попыток входа. Попробуй снова через 15 минут.",
            )
        elif form.is_valid():
            previous_fingerprint = get_session_fingerprint(request)
            user = form.get_user()
            try:
                clear_login_failures(request, username)
            except Exception:
                logger.exception("Unable to clear login failure counter")
            login(request, user)
            attach_anonymous_workspace(
                user=user,
                previous_fingerprint=previous_fingerprint,
                current_fingerprint=get_session_fingerprint(request),
            )
            logger.info("User signed in: user_id=%s", user.pk)
            return redirect("dashboard")
        else:
            try:
                record_login_failure(request, username)
            except Exception:
                logger.exception("Unable to record login failure")
                form.add_error(None, "Авторизация временно недоступна. Попробуй немного позже.")
                return render(request, "transfer/auth/login.html", {"form": form}, status=503)
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
