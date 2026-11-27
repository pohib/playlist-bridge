"""Validation for API transfer creation payloads."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from . import parse_vk_playlist_url


class TransferRequestValidationError(ValueError):
    """A transfer request contains invalid user-supplied fields."""


def validate_transfer_request_payload(payload):
    """Return the source URL and normalized target ID or raise a safe error."""
    if not isinstance(payload, dict):
        raise TransferRequestValidationError("Ожидается JSON-объект.")

    source_url = payload.get("source_url", "")
    target = payload.get("target_playlist", "")
    if not isinstance(source_url, str) or len(source_url) > 2048:
        raise TransferRequestValidationError(
            "Поле source_url обязательно и должно быть строкой длиной до 2048 символов."
        )
    if target is not None and (not isinstance(target, str) or len(target) > 2048):
        raise TransferRequestValidationError(
            "Поле target_playlist должно быть строкой длиной до 2048 символов."
        )

    normalized_target = (target or "").strip() if isinstance(target, str) or target is None else ""
    if normalized_target and not re.fullmatch(r"[A-Za-z0-9]{22}", normalized_target):
        raise TransferRequestValidationError(
            "Поле target_playlist должно содержать корректный Spotify ID плейлиста."
        )

    try:
        URLValidator(schemes=["http", "https"])(source_url)
        parse_vk_playlist_url(source_url)
    except (ValidationError, ValueError) as exc:
        raise TransferRequestValidationError(
            "Укажи корректную ссылку на плейлист VK."
        ) from exc

    return source_url, normalized_target
