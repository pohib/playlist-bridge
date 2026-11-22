# ruff: noqa: I001
"""Spotify Web API client and OAuth implementation."""
import base64
import re
import time
from urllib.parse import urlencode

import requests

from .common import ReauthorizationRequired, TransferError

class SpotifyClient:
    API = "https://api.spotify.com/v1"
    ACCOUNTS = "https://accounts.spotify.com"
    SCOPES = "user-read-private playlist-read-private playlist-modify-private playlist-modify-public"

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self.http = requests.Session()

    def authorization_url(self, state):
        params = {"response_type": "code", "client_id": self.client_id, "scope": self.SCOPES,
                  "redirect_uri": self.redirect_uri, "state": state}
        return f"{self.ACCOUNTS}/authorize?{urlencode(params)}"

    def token_request(self, data):
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = None
        try:
            response = self.http.post(
                f"{self.ACCOUNTS}/api/token",
                data=data,
                headers={"Authorization": f"Basic {credentials}"},
                timeout=(5, 20),
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
                    "Срок действия или разрешение Spotify истекло. Подключи Spotify повторно."
                ) from exc
            raise TransferError("Не удалось получить OAuth-токен Spotify.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить OAuth-токен Spotify.") from exc

    def exchange_code(self, code):
        return self.token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri})

    def refresh_token(self, refresh_token):
        return self.token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    @staticmethod
    def _api_destination(operation, playlist_id=None):
        """Resolve a closed Spotify operation set to a fixed API origin."""
        fixed_destinations = {
            "search": ("GET", f"{SpotifyClient.API}/search"),
            "current_user": ("GET", f"{SpotifyClient.API}/me"),
            "create_playlist": ("POST", f"{SpotifyClient.API}/me/playlists"),
            "my_playlists": ("GET", f"{SpotifyClient.API}/me/playlists"),
        }
        if operation in fixed_destinations:
            if playlist_id is not None:
                raise TransferError("ID плейлиста не ожидается для этой операции.")
            return fixed_destinations[operation]

        if operation in {"playlist_details", "playlist_items", "get_playlist_items"}:
            if not isinstance(playlist_id, str) or not re.fullmatch(r"[A-Za-z0-9]{22}", playlist_id):
                raise TransferError("ID плейлиста Spotify имеет неверный формат.")
            suffix = "/items" if operation in {"playlist_items", "get_playlist_items"} else ""
            method = "POST" if operation == "playlist_items" else "GET"
            # The host and route prefix are constants; the only variable segment
            # is restricted to Spotify's 22-character base62 playlist identifier.
            return method, f"{SpotifyClient.API}/playlists/{playlist_id}{suffix}"

        raise TransferError("Недопустимая операция Spotify API.")

    def api(self, operation, token, *, playlist_id=None, params=None, body=None):
        method, api_url = self._api_destination(operation, playlist_id)
        safe_method = method == "GET"
        for attempt in range(3 if safe_method else 1):
            try:
                response = self.http.request(
                    method,
                    api_url,
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=(5, 30),
                    allow_redirects=False,
                )
                if 300 <= response.status_code < 400:
                    raise TransferError("Spotify API вернул неожиданный HTTP redirect.")
                if response.status_code == 429:
                    try:
                        error = response.json().get("error", {})
                    except ValueError:
                        error = {}
                    if error.get("reason") == "QUOTA_EXCEEDED":
                        raise TransferError(
                            "Исчерпана квота Spotify Development Mode. Повтори попытку позже."
                        )
                    retry_after = response.headers.get("Retry-After", "1")
                    try:
                        delay = max(1, int(float(retry_after)))
                    except (TypeError, ValueError):
                        delay = 1
                    if safe_method and attempt < 2 and delay <= 20:
                        time.sleep(delay)
                        continue
                    raise TransferError(
                        "Spotify ограничил частоту запросов. Повтори перенос позже."
                    )
                response.raise_for_status()
                return response.json() if response.content else {}
            except TransferError:
                raise
            except (requests.RequestException, ValueError) as exc:
                raise TransferError(
                    "Spotify API вернул ошибку. Проверь доступ и разрешения аккаунта."
                ) from exc
        raise TransferError("Spotify временно ограничил частоту запросов. Повтори перенос позже.")

    def search(self, token, artist, title):
        data = self.api("search", token, params={
            "q": f'track:"{title[:100]}" artist:"{artist[:100]}"', "type": "track", "limit": 10,
        })
        return data.get("tracks", {}).get("items", [])

    def search_tracks(self, token, query):
        data = self.api("search", token, params={
            "q": query[:180],
            "type": "track",
            "limit": 10,
        })
        return data.get("tracks", {}).get("items", [])

    def current_user(self, token):
        return self.api("current_user", token)

    def create_playlist(self, token, name):
        result = self.api("create_playlist", token, body={
            "name": name[:100], "description": "Imported from VK", "public": False,
        })
        if not result.get("id"):
            raise TransferError("Spotify не вернул ID созданного плейлиста.")
        return result["id"]

    def verify_playlist_access(self, token, playlist_id, user_id):
        playlist = self.api("playlist_details", token, playlist_id=playlist_id)
        if (playlist.get("owner") or {}).get("id") != user_id:
            raise TransferError("Можно добавлять композиции только в плейлист владельца подключённого аккаунта.")
        return playlist

    def add_items(self, token, playlist_id, uris, position=None):
        if not uris or any(
            not isinstance(uri, str) or not re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", uri)
            for uri in uris
        ):
            raise TransferError("Список содержит некорректный Spotify track URI.")
        for offset in range(0, len(uris), 100):
            body = {"uris": uris[offset:offset + 100]}
            if position is not None:
                body["position"] = position + offset
            self.api("playlist_items", token, playlist_id=playlist_id, body=body)


    def my_playlists(self, token):
        items = []
        for offset in range(0, 1000, 50):
            page = self.api("my_playlists", token, params={"limit": 50, "offset": offset})
            items.extend(page.get("items", []))
            if not page.get("next") or len(items) >= page.get("total", 0):
                break
        return items

    def get_playlist_items(self, token, playlist_id):
        items = []
        for offset in range(0, 10000, 50):
            page = self.api(
                "get_playlist_items", token, playlist_id=playlist_id,
                params={"limit": 50, "offset": offset},
            )
            items.extend(page.get("items", []))
            if not page.get("next"):
                break
        return items

    def track_details(self, token, track_id):
        if not isinstance(track_id, str) or not re.fullmatch(r"[A-Za-z0-9]{22}", track_id):
            raise TransferError("ID трека Spotify имеет неверный формат.")
        try:
            response = self.http.get(
                f"{self.API}/tracks/{track_id}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=(5, 25),
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise TransferError("Spotify API вернул неожиданный HTTP redirect.")
            response.raise_for_status()
            return response.json()
        except TransferError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить данные трека Spotify.") from exc
