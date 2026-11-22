# ruff: noqa: I001
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


class VKClient:
    BASE = "https://web.api.vk.ru/method"

    def __init__(self, token, version, client_id):
        if not token:
            raise TransferError("VK access token отсутствует. Подключи VK через OAuth.")
        self.token, self.version, self.client_id = token, version, client_id
        self.http = requests.Session()

    def post(self, method, *, data=None, json_body=None):
        try:
            response = self.http.post(
                f"{self.BASE}/{method}",
                params={"v": self.version, "client_id": self.client_id},
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                data=data, json=json_body, timeout=(5, 30),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError(f"Не удалось получить данные VK ({method}).") from exc
        if payload.get("error"):
            error = payload["error"]
            code = error.get("error_code", "unknown")
            message = error.get("error_msg", "")
            if code in {5, 15, 18, 203}:
                raise TransferError(
                    "VK не разрешил чтение этого плейлиста. Проверь, что он публичный "
                    "и доступен аккаунту, подключённому через VK ID."
                )
            raise TransferError(f"VK API вернул ошибку {code}: {message[:180]}")
        return payload

    @staticmethod
    def _response_items(payload):
        response = payload.get("response", [])
        if isinstance(response, dict):
            items = response.get("items", response.get("audios", []))
            count = response.get("count", len(items))
            return items, count
        if isinstance(response, list):
            return response, len(response)
        return [], 0

    def fetch_playlist(self, url):
        owner, playlist_id, access_key = parse_vk_playlist_url(url)
        params = {"owner_id": owner, "playlist_id": playlist_id}
        if access_key:
            params["access_key"] = access_key

        metadata_payload = self.post("audio.getPlaylistById", data=params)
        metadata = metadata_payload.get("response", {})
        if isinstance(metadata, list):
            metadata = metadata[0] if metadata else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("playlist"), dict):
            metadata = metadata["playlist"]

        tracks = []
        offset = 0
        page_size = 1000
        total = None
        while total is None or offset < total:
            page_params = {
                "owner_id": owner,
                "album_id": playlist_id,
                "count": page_size,
                "offset": offset,
            }
            if access_key:
                page_params["access_key"] = access_key
            page, page_total = self._response_items(self.post("audio.get", data=page_params))
            if total is None:
                total = page_total
            if not page:
                break
            for item in page:
                try:
                    track = VKTrack(
                        int(item["owner_id"]),
                        int(item["id"]),
                        str(item.get("artist") or "").strip(),
                        str(item.get("title") or "").strip(),
                        int(item.get("duration") or 0),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                tracks.append(track)
            offset += len(page)
            if len(page) < page_size:
                break

        if not tracks:
            raise TransferError(
                "VK вернул плейлист без доступных аудиозаписей. Возможно, VK ограничил "
                "доступ к аудио через API или плейлист действительно пуст."
            )
        title = metadata.get("title") or metadata.get("name") or "VK playlist"
        return title, tracks

    def fetch_track(self, url):
        owner_id, track_id = parse_vk_track_url(url)
        payload = self.post("audio.getById", data={"audios": f"{owner_id}_{track_id}"})
        items, _ = self._response_items(payload)
        if not items:
            raise TransferError("VK не вернул аудиозапись. Возможно, она недоступна.")
        item = items[0]
        try:
            return VKTrack(
                int(item["owner_id"]), int(item["id"]),
                str(item.get("artist") or "").strip(),
                str(item.get("title") or "").strip(),
                int(item.get("duration") or 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferError("VK вернул некорректные данные аудиозаписи.") from exc
