# ruff: noqa: I001
"""SoundCloud OAuth and API client implementation."""
import base64
import hashlib
import re
from urllib.parse import urlencode, urlparse

import requests

from .common import ReauthorizationRequired, TransferError

class SoundCloudClient:
    API = "https://api.soundcloud.com"
    AUTH = "https://secure.soundcloud.com"

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = requests.Session()

    def authorization_url(self, state, verifier):
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        return f"{self.AUTH}/authorize?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        })

    def token_request(self, data):
        response = None
        try:
            response = self.http.post(
                f"{self.AUTH}/oauth/token",
                data={
                    **data,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=(5, 25),
                allow_redirects=False,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            try:
                error = response.json().get("error")
            except (AttributeError, ValueError):
                error = None
            if error == "invalid_grant":
                raise ReauthorizationRequired(
                    "Разрешение SoundCloud истекло. Подключи SoundCloud повторно."
                ) from exc
            raise TransferError("Не удалось получить OAuth-токен SoundCloud.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить OAuth-токен SoundCloud.") from exc

    def exchange_code(self, code, verifier):
        return self.token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        })

    def refresh_token(self, refresh_token):
        return self.token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def _request(self, method, path_or_url, token, *, params=None, json_body=None, files=None, data=None):
        if path_or_url.startswith("/"):
            url = f"{self.API}{path_or_url}"
        else:
            parsed = urlparse(path_or_url)
            if parsed.scheme != "https" or parsed.hostname != "api.soundcloud.com":
                raise TransferError("SoundCloud вернул недопустимый адрес следующей страницы.")
            url = path_or_url
        try:
            response = self.http.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
                timeout=(5, 60),
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise TransferError("SoundCloud API вернул неожиданный HTTP redirect.")
            response.raise_for_status()
            return response.json() if response.content else {}
        except TransferError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Ошибка обращения к SoundCloud API. Проверь доступ и разрешения.") from exc

    def current_user(self, token):
        return self._request("GET", "/me", token)

    def _collection(self, path, token):
        url = path
        items = []
        for _ in range(100):
            payload = self._request("GET", url, token, params={"linked_partitioning": "true", "limit": 200} if url == path else None)
            if isinstance(payload, list):
                items.extend(payload)
                break
            items.extend(payload.get("collection", []))
            next_href = payload.get("next_href")
            if not next_href:
                break
            url = next_href
        return items

    def my_playlists(self, token):
        return self._collection("/me/playlists", token)

    def resolve(self, token, permalink):
        return self._request("GET", "/resolve", token, params={"url": permalink})

    def playlist_tracks(self, token, playlist_id):
        if not re.fullmatch(r"[0-9]+", str(playlist_id)):
            raise TransferError("Некорректный идентификатор плейлиста SoundCloud.")
        return self._collection(f"/playlists/{playlist_id}/tracks", token)

    def search_tracks(self, token, query):
        payload = self._request(
            "GET", "/tracks", token,
            params={"q": query[:180], "limit": 20, "linked_partitioning": "true"},
        )
        return payload.get("collection", []) if isinstance(payload, dict) else payload

    def create_playlist(self, token, title, tracks, description=""):
        if len(tracks) > 100 or any(not re.fullmatch(r"[0-9]+", str(track_id)) for track_id in tracks):
            raise TransferError("Список композиций SoundCloud содержит некорректные ID или превышает лимит.")
        payload = self._request(
            "POST", "/playlists", token,
            json_body={"playlist": {
                "title": title[:100],
                "description": description[:1000],
                "sharing": "private",
                "tracks": [{"id": int(track_id)} for track_id in tracks],
            }},
        )
        if not payload.get("id"):
            raise TransferError("SoundCloud не вернул ID созданного плейлиста.")
        return payload

    def update_playlist_tracks(self, token, playlist_id, track_ids):
        if not re.fullmatch(r"[0-9]+", str(playlist_id)):
            raise TransferError("Некорректный идентификатор плейлиста SoundCloud.")
        if not track_ids or len(track_ids) > 100:
            raise TransferError("Список композиций SoundCloud пуст или превышает лимит.")
        normalized = []
        for track_id in track_ids:
            if not re.fullmatch(r"[0-9]+", str(track_id)):
                raise TransferError("Некорректный идентификатор композиции SoundCloud.")
            normalized.append({"id": int(track_id)})
        return self._request(
            "PUT",
            f"/playlists/{playlist_id}",
            token,
            json_body={"playlist": {"tracks": normalized}},
        )

    def upload_track(self, token, uploaded_file, title, artist, description=""):
        try:
            response = self.http.post(
                f"{self.API}/tracks",
                headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
                data={
                    "track[title]": title[:100],
                    "track[artist]": artist[:100],
                    "track[description]": description[:4000],
                    "track[sharing]": "private",
                },
                files={"track[asset_data]": (
                    uploaded_file.name,
                    uploaded_file.file,
                    uploaded_file.content_type or "application/octet-stream",
                )},
                timeout=(10, 300),
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise TransferError("SoundCloud API вернул неожиданный HTTP redirect.")
            response.raise_for_status()
            result = response.json()
        except TransferError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось загрузить аудиофайл в SoundCloud.") from exc
        if not result.get("id"):
            raise TransferError("SoundCloud не подтвердил загрузку аудиофайла.")
        return result


    def disconnect(self, token):
        self._request("POST", "/disconnect", token)
