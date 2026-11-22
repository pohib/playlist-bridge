import base64
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlencode, urlparse

import requests


class TransferError(Exception):
    """Expected, user-safe transfer error."""


@dataclass(frozen=True)
class VKTrack:
    owner_id: int
    track_id: int
    artist: str
    title: str
    duration: int


def parse_vk_playlist_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Ссылка на плейлист VK слишком длинная или некорректная.")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"vk.ru", "vk.com", "www.vk.com", "m.vk.com"}:
        raise ValueError("Укажи ссылку на плейлист VK.")
    match = re.fullmatch(r"/music/playlist/(-?\d+)_(\d+)(?:_([A-Za-z0-9]+))?/?", parsed.path)
    if not match:
        raise ValueError("Формат ссылки на плейлист VK не распознан.")
    owner, playlist, key = match.groups()
    return int(owner), int(playlist), key or ""


def normalize_track_text(value):
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"\([^)]*(?:remaster|ремастер|version|версия|feat\.?)[^)]*\)", " ", value)
    value = re.sub(r"\[[^]]*\]", " ", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def score_candidate(source, candidate):
    title_score = SequenceMatcher(None, normalize_track_text(source.title), normalize_track_text(candidate.get("name", ""))).ratio()
    artists = [x.get("name", "") for x in candidate.get("artists", [])]
    artist_score = max((SequenceMatcher(None, normalize_track_text(source.artist), normalize_track_text(x)).ratio() for x in artists), default=0)
    duration = candidate.get("duration_ms")
    duration_score = max(0.0, 1 - abs(duration - source.duration * 1000) / 15000) if isinstance(duration, int) else 0.0
    return title_score * .58 + artist_score * .32 + duration_score * .10


class VKClient:
    BASE = "https://web.api.vk.ru/method"

    def __init__(self, token, version, client_id):
        if not token:
            raise TransferError("VK API token не настроен.")
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
        try:
            response = self.http.post(f"{self.ACCOUNTS}/api/token", data=data,
                headers={"Authorization": f"Basic {credentials}"}, timeout=(5, 20))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Не удалось получить OAuth-токен Spotify.") from exc

    def exchange_code(self, code):
        return self.token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri})

    def refresh_token(self, refresh_token):
        return self.token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def api(self, method, path, token, *, params=None, body=None):
        try:
            response = self.http.request(method, f"{self.API}{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=(5, 30))
            if response.status_code == 429:
                raise TransferError("Spotify ограничил частоту запросов. Повтори перенос позже.")
            response.raise_for_status()
            return response.json() if response.content else {}
        except TransferError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise TransferError("Spotify API вернул ошибку. Проверь доступ и разрешения аккаунта.") from exc

    def search(self, token, artist, title):
        data = self.api("GET", "/search", token, params={
            "q": f'track:"{title[:100]}" artist:"{artist[:100]}"', "type": "track", "limit": 10,
        })
        return data.get("tracks", {}).get("items", [])

    def current_user(self, token):
        return self.api("GET", "/me", token)

    def create_playlist(self, token, name):
        result = self.api("POST", "/me/playlists", token, body={
            "name": name[:100], "description": "Imported from VK", "public": False,
        })
        if not result.get("id"):
            raise TransferError("Spotify не вернул ID созданного плейлиста.")
        return result["id"]

    def verify_playlist_access(self, token, playlist_id, user_id):
        playlist = self.api("GET", f"/playlists/{playlist_id}", token)
        if (playlist.get("owner") or {}).get("id") != user_id:
            raise TransferError("Можно добавлять композиции только в плейлист владельца подключённого аккаунта.")
        return playlist

    def add_items(self, token, playlist_id, uris):
        for offset in range(0, len(uris), 100):
            self.api("POST", f"/playlists/{playlist_id}/items", token, body={"uris": uris[offset:offset + 100]})


def execute_transfer(*, vk_token, vk_version, vk_client_id, spotify, spotify_token, source_url, target_playlist=None):
    playlist_name, tracks = VKClient(vk_token, vk_version, vk_client_id).fetch_playlist(source_url)
    user = spotify.current_user(spotify_token)
    if target_playlist:
        parsed = urlparse(target_playlist) if "://" in target_playlist else None
        if parsed:
            parts = [part for part in parsed.path.split("/") if part]
            if parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"} or len(parts) < 2 or parts[-2] != "playlist":
                raise TransferError("Укажи корректную ссылку на плейлист Spotify.")
            target_playlist = parts[-1]
        if not re.fullmatch(r"[A-Za-z0-9]{10,64}", target_playlist):
            raise TransferError("ID плейлиста Spotify имеет неверный формат.")
        spotify.verify_playlist_access(spotify_token, target_playlist, user.get("id"))
    else:
        target_playlist = spotify.create_playlist(spotify_token, playlist_name)
    uris, report = [], []
    for index, track in enumerate(tracks, 1):
        ranked = sorted(((score_candidate(track, item), item) for item in spotify.search(spotify_token, track.artist, track.title)),
                        key=lambda pair: pair[0], reverse=True)
        if not ranked or ranked[0][0] < .82:
            status, selected, score = "not_found", None, ranked[0][0] if ranked else 0.0
        elif len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .045:
            status, selected, score = "ambiguous", None, ranked[0][0]
        else:
            score, selected = ranked[0]
            status = "matched" if selected.get("uri") else "not_found"
        if status == "matched":
            uris.append(selected["uri"])
        report.append({"index": index, "artist": track.artist, "title": track.title, "status": status,
                       "spotify_name": selected.get("name", "") if selected else "", "score": round(score, 3)})
    spotify.add_items(spotify_token, target_playlist, uris)
    return {"playlist_name": playlist_name, "target_playlist_id": target_playlist, "total": len(tracks),
            "matched": len(uris), "not_found": sum(x["status"] == "not_found" for x in report),
            "ambiguous": sum(x["status"] == "ambiguous" for x in report), "report": report}
