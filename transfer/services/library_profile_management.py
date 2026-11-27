"""Library profile domain operations."""

from .library_management_errors import LibraryManagementError


def update_profile(profile, display_name):
    display_name = (display_name or "").strip()
    if not display_name or len(display_name) > 60:
        raise LibraryManagementError(
            "Имя профиля должно содержать от 1 до 60 символов."
        )
    profile.display_name = display_name
    profile.save(update_fields=["display_name", "updated_at"])
    return profile
