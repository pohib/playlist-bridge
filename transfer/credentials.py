import hashlib
import hmac
import json
import time

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from .core import ReauthorizationRequired, TransferError
from .models import OAuthCredential


def get_session_fingerprint(request):
    for legacy_key in ("spotify_token", "vk_token", "vk_access_token", "spotify_access_token", "spotify_refresh_token"):
        request.session.pop(legacy_key, None)
    if not request.session.session_key:
        request.session.save()
    return hmac.new(
        settings.SECRET_KEY.encode(),
        request.session.session_key.encode(),
        hashlib.sha256,
    ).hexdigest()


def _fernet():
    try:
        return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
    except (ValueError, AttributeError) as exc:
        raise TransferError("Шифрование OAuth-токенов не настроено на сервере.") from exc


def encrypt_payload(payload):
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_payload(value):
    try:
        payload = json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransferError("Не удалось расшифровать OAuth-токен. Переподключи аккаунт.") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise TransferError("Сохранённые OAuth-данные повреждены. Переподключи аккаунт.")
    return payload


def store_credential(fingerprint, provider, payload, external_user_id=""):
    stored = dict(payload)
    stored.setdefault("obtained_at", time.time())
    if provider == "spotify":
        stored.setdefault("authorized_at", time.time())
    credential, _ = OAuthCredential.objects.update_or_create(
        session_fingerprint=fingerprint,
        provider=provider,
        defaults={
            "encrypted_payload": encrypt_payload(stored),
            "external_user_id": str(external_user_id or ""),
        },
    )
    return credential


def delete_credential(fingerprint, provider):
    OAuthCredential.objects.filter(session_fingerprint=fingerprint, provider=provider).delete()


def load_payload(fingerprint, provider):
    credential = OAuthCredential.objects.filter(
        session_fingerprint=fingerprint, provider=provider
    ).first()
    if not credential:
        raise TransferError(f"Сначала подключи {provider.capitalize()}.")
    return credential, decrypt_payload(credential.encrypted_payload)


def get_access_token(fingerprint, provider, client):
    credential, payload = load_payload(fingerprint, provider)
    now = time.time()

    if provider == "spotify":
        try:
            authorized_at = float(payload.get("authorized_at", credential.created_at.timestamp()))
        except (TypeError, ValueError):
            authorized_at = credential.created_at.timestamp()
        # Spotify refresh tokens expire six months after the original authorization.
        # Access-token refreshes do not extend this lifetime.
        if now >= authorized_at + 180 * 24 * 60 * 60:
            delete_credential(fingerprint, provider)
            raise ReauthorizationRequired(
                "Разрешение Spotify старше шести месяцев. Подключи Spotify повторно."
            )

    expires_at = float(payload.get("obtained_at", 0)) + int(payload.get("expires_in", 3600))
    if now >= expires_at - 90:
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            delete_credential(fingerprint, provider)
            raise ReauthorizationRequired(
                f"Сессия {provider.capitalize()} истекла. Подключи аккаунт повторно."
            )
        try:
            if provider == "spotify":
                renewed = client.refresh_token(refresh_token)
            elif provider == "vk":
                renewed = client.refresh_token(refresh_token, payload.get("device_id", ""))
            else:
                raise TransferError("Неизвестный OAuth-провайдер.")
        except ReauthorizationRequired:
            delete_credential(fingerprint, provider)
            raise
        renewed["refresh_token"] = renewed.get("refresh_token", refresh_token)
        renewed["obtained_at"] = now
        if provider == "vk":
            renewed["device_id"] = payload.get("device_id", "")
        payload.update(renewed)
        credential.encrypted_payload = encrypt_payload(payload)
        credential.save(update_fields=["encrypted_payload", "updated_at"])
    return payload["access_token"], payload
