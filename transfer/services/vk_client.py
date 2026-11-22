"""VK ID OAuth and VK API client implementations."""
import base64
import hashlib
import re
import secrets
from urllib.parse import urlencode, urlparse

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
            raise TransferError(f"VK API вернул ошибку {error.get('error_code', 'unknown')}.")
        return payload

    def fetch_playlist(self, url):
        owner, playlist_id, access_key = parse_vk_playlist_url(url)
        entity_id = f"{owner}_{playlist_id}" + (f"_{access_key}" if access_key else "")
        requests_batch = [
            {"id": "13", "method": "audio.getPlaylistById", "params": {
                "owner_id": owner, "playlist_id": playlist_id, "access_key": access_key,
                "extra_fields": "owner,duration",
            }},
            {"id": "14", "method": "audio.getIdsBySource", "params": {
                "source": "playlist", "entity_id": entity_id,
            }},
        ]
        payload = self.post("batch.call", json_body={"requests": requests_batch})
        rows = payload.get("response", {}).get("responses", payload.get("responses", []))
        indexed = {str(row.get("id")): row.get("body", {}) for row in rows}
        metadata = indexed.get("13", {}).get("response", {})
        id_data = indexed.get("14", {}).get("response", {})
        ids = [str(row["audio_id"]) for row in id_data.get("audios", []) if row.get("audio_id")]
        if not ids:
            raise TransferError("Плейлист VK пуст или недоступен.")
        tracks = {}
        for offset in range(0, len(ids), 20):
            response = self.post("audio.getById", data={"audios": ",".join(ids[offset:offset + 20])}).get("response", [])
            if isinstance(response, dict):
                response = response.get("items", response.get("audios", []))
            for item in response:
                try:
                    track = VKTrack(int(item["owner_id"]), int(item["id"]), str(item.get("artist") or "").strip(),
                                    str(item.get("title") or "").strip(), int(item.get("duration") or 0))
                    tracks[f"{track.owner_id}_{track.track_id}"] = track
                except (KeyError, TypeError, ValueError):
                    continue
        ordered = [tracks["_".join(audio_id.split("_")[:2])] for audio_id in ids
                   if "_".join(audio_id.split("_")[:2]) in tracks]
        if not ordered:
            raise TransferError("VK не вернул метаданные композиций.")
        return metadata.get("title") or metadata.get("name") or "VK playlist", ordered

    def fetch_track(self, url):
        owner_id, track_id = parse_vk_track_url(url)
        payload = self.post("audio.getById", data={"audios": f"{owner_id}_{track_id}"}).get("response", [])
        if isinstance(payload, dict):
            payload = payload.get("items", payload.get("audios", []))
        if not payload:
            raise TransferError("VK не вернул аудиозапись. Возможно, она недоступна.")
        item = payload[0]
        try:
            return VKTrack(int(item["owner_id"]), int(item["id"]), str(item.get("artist") or "").strip(), str(item.get("title") or "").strip(), int(item.get("duration") or 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferError("VK вернул некорректные данные аудиозаписи.") from exc
