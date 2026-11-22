"""VK ID OAuth and VK API client implementations."""
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

from .common import TransferError, VKTrack, parse_vk_playlist_url, parse_vk_track_url


class VKIDClient:
    AUTHORIZE_URL = "https://id.vk.ru/authorize"
    OAUTH_EXCHANGE_ENDPOINT = "https://id.vk.ru/oauth2/auth"

    def __init__(self, client_id, redirect_uri, service_token=None):
        self.client_id = str(client_id)
        self.redirect_uri = redirect_uri
        self.service_token = service_token
        self.http = requests.Session()

    def authorization_url(self, state, code_verifier):
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        return f"{self.AUTHORIZE_URL}?{urlencode({
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'state': state,
            'code_challenge': challenge,
            'code_challenge_method': 's256',
            'scope': 'audio',
        })}"

    def _token_request(self, params, body):
        form_data = {**params, **body}
        if self.service_token:
            form_data["service_token"] = self.service_token
        try:
            response = self.http.post(
                self.OAUTH_EXCHANGE_ENDPOINT,
                data=form_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=(5, 20),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить OAuth-токен VK ID.") from exc
        if payload.get("error") or not payload.get("access_token"):
            raise TransferError("VK ID отклонил авторизацию. Проверь приложение и разрешения.")
        return payload

    def exchange_code(self, code, device_id, state, code_verifier):
        params = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
            "device_id": device_id,
            "state": state,
        }
        return self._token_request(params, {"code": code})

    def refresh_token(self, refresh_token, device_id):
        params = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "device_id": device_id,
            "state": secrets.token_urlsafe(24),
        }
        payload = self._token_request(params, {"refresh_token": refresh_token})
        if payload.get("state") != params["state"]:
            raise TransferError("VK ID вернул некорректный OAuth state при обновлении токена.")
        return payload


class VKAnonymousTokenProvider:
    """Fetch and cache an anonymous VK API token without user cookies."""

    TOKEN_ENDPOINT = "https://login.vk.ru/"
    SCOPES = "audio_anonymous,video_anonymous,photos_anonymous,profile_anonymous"

    def __init__(self, client_id, client_secret, http=None):
        if not client_id or not client_secret:
            raise TransferError("Не настроены параметры анонимного доступа VK.")
        self.client_id = str(client_id)
        self.client_secret = client_secret
        self.http = http or requests.Session()
        self._token = ""
        self._expires_at = 0

    def get_token(self):
        import time

        if self._token and time.time() < self._expires_at - 60:
            return self._token
        try:
            response = self.http.post(
                self.TOKEN_ENDPOINT,
                params={"act": "get_anonym_token"},
                data={
                    "client_secret": self.client_secret,
                    "client_id": self.client_id,
                    "scopes": self.SCOPES,
                    "isApiOauthAnonymEnabled": "false",
                    "version": "1",
                    "app_id": self.client_id,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://vk.ru",
                    "Referer": "https://vk.ru/",
                },
                timeout=(5, 20),
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить анонимный токен VK.") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        token = data.get("access_token") if isinstance(data, dict) else None
        expires_at = data.get("expired_at", data.get("expires")) if isinstance(data, dict) else None
        if payload.get("type") != "okay" or not isinstance(token, str) or not token.startswith("anonym."):
            raise TransferError("VK не выдал анонимный токен. Проверь настройки приложения и доступность публичного API.")
        try:
            self._expires_at = int(expires_at)
        except (TypeError, ValueError) as exc:
            raise TransferError("VK вернул некорректный срок действия анонимного токена.") from exc
        self._token = token
        return self._token


class VKClient:
    """VK public-audio client based on anonymous API access."""

    BASE = "https://web.api.vk.ru/method"
    MAX_TRACKS = 5000
    AUDIO_BATCH_SIZE = 50

    def __init__(self, client_id, client_secret, version="5.289"):
        self.client_id = str(client_id)
        self.version = str(version)
        self.token_provider = VKAnonymousTokenProvider(client_id, client_secret)
        self.http = requests.Session()

    def post(self, method, *, data=None):
        form_data = dict(data or {})
        form_data["access_token"] = self.token_provider.get_token()
        try:
            response = self.http.post(
                f"{self.BASE}/{method}",
                params={"v": self.version, "client_id": self.client_id},
                data=form_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://vk.ru",
                    "Referer": "https://vk.ru/",
                },
                timeout=(5, 30),
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError(f"Не удалось получить данные VK ({method}).") from exc
        if not isinstance(payload, dict):
            raise TransferError("VK вернул ответ неизвестного формата.")
        if payload.get("error"):
            error = payload["error"]
            code = error.get("error_code", "unknown") if isinstance(error, dict) else "unknown"
            if code in {5, 15, 18, 203}:
                raise TransferError("VK не разрешил доступ к аудио. Проверь, что плейлист публичный.")
            raise TransferError(f"VK API вернул ошибку {code}.")
        return payload

    @staticmethod
    def _response_items(payload):
        response = payload.get("response", [])
        if isinstance(response, dict):
            items = response.get("items", response.get("audios", []))
            count = response.get("count", len(items))
            return items if isinstance(items, list) else [], count
        if isinstance(response, list):
            return response, len(response)
        return [], 0

    @staticmethod
    def _track_from_item(item):
        try:
            return VKTrack(
                int(item["owner_id"]),
                int(item.get("id", item.get("audio_id", "").split("_")[1])),
                str(item.get("artist") or "").strip(),
                str(item.get("title") or "").strip(),
                max(0, int(item.get("duration") or 0)),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def fetch_playlist(self, url):
        owner, playlist_id, access_key = parse_vk_playlist_url(url)
        entity_id = f"{owner}_{playlist_id}" + (f"_{access_key}" if access_key else "")
        ids_payload = self.post(
            "audio.getIdsBySource",
            data={"source": "playlist", "entity_id": entity_id, "ref": ""},
        )
        response = ids_payload.get("response", {})
        audio_refs = response.get("audios", []) if isinstance(response, dict) else []
        if not isinstance(audio_refs, list):
            raise TransferError("VK вернул некорректный список аудиозаписей.")
        if len(audio_refs) > self.MAX_TRACKS:
            raise TransferError(f"Плейлист превышает ограничение импорта ({self.MAX_TRACKS} треков).")
        audio_ids = [
            item.get("audio_id")
            for item in audio_refs
            if isinstance(item, dict)
            and isinstance(item.get("audio_id"), str)
            and len(item["audio_id"]) <= 200
        ]
        if not audio_ids:
            raise TransferError("VK не вернул доступные композиции. Проверь публичность плейлиста.")
        tracks = []
        for start in range(0, len(audio_ids), self.AUDIO_BATCH_SIZE):
            batch = audio_ids[start:start + self.AUDIO_BATCH_SIZE]
            payload = self.post("audio.getById", data={"audios": ",".join(batch)})
            items, _ = self._response_items(payload)
            for item in items:
                if isinstance(item, dict):
                    track = self._track_from_item(item)
                    if track and track.artist and track.title:
                        tracks.append(track)
        if not tracks:
            raise TransferError("VK не вернул метаданные аудиозаписей.")
        # getIdsBySource currently returns ordered IDs but not playlist title.
        return "VK playlist", tracks

    def fetch_track(self, url):
        owner_id, track_id = parse_vk_track_url(url)
        payload = self.post("audio.getById", data={"audios": f"{owner_id}_{track_id}"})
        items, _ = self._response_items(payload)
        if not items or not isinstance(items[0], dict):
            raise TransferError("VK не вернул аудиозапись. Возможно, она недоступна.")
        track = self._track_from_item(items[0])
        if not track or not track.artist or not track.title:
            raise TransferError("VK вернул некорректные данные аудиозаписи.")
        return track
