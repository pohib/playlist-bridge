"""HTTP adapter for library profile management."""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .library_support import _profile
from .services.library_management import LibraryManagementError
from .services.library_management import update_profile as update_profile_service


@require_POST
def update_profile(request):
    try:
        update_profile_service(
            _profile(request), request.POST.get("display_name")
        )
    except LibraryManagementError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Профиль обновлён.")
    return redirect("library")
