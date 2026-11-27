"""VK anonymous public-audio API client implementation."""

import requests

from .common import (
    TransferError,
    VKTrack,
    parse_vk_playlist_url,
    parse_vk_track_reference,
)
from .vk_anonymous_token import VKAnonymousTokenProvider


class VKClient:
    """VK public-audio client based on anonymous API access."""

    BASE = "https://web.api.vk.ru/method"
    MAX_TRACKS = 5000
    AUDIO_BATCH_SIZE = 50

    def __init__(self, client_id=None, version="5.289"):
        self.client_id = str(client_id or VKAnonymousTokenProvider.CLIENT_ID)
        self.version = str(version)
        self.token_provider = VKAnonymousTokenProvider(client_id)
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
                    **self.token_provider.BROWSER_HEADERS,
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://vk.ru",
                    "Referer": self.token_provider.referer or "https://vk.ru/",
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
    def _cover_from_item(item):
        """Extract album artwork from the different shapes returned by VK."""
        from urllib.parse import urlparse

        preferred_keys = (
            "photo_1200", "photo_1000", "photo_800", "photo_600",
            "photo_540", "photo_500", "photo_400", "photo_300",
            "photo_270", "photo_200", "photo_135", "photo_68", "photo", "photo_url",
            "cover_url", "cover", "cover_uri", "image_url", "image", "thumb_src", "src", "url",
        )
        candidates = []
        seen = set()

        def collect(value, image_context=False):
            if isinstance(value, str):
                candidate = value.strip()
                if image_context and candidate and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
                return
            if isinstance(value, list):
                for entry in value:
                    collect(entry, image_context)
                return
            if not isinstance(value, dict):
                return
            # VK has returned artwork as album.thumb.photo_*, item.thumb,
            # track_covers[], and as direct cover/image URL fields.
            for key in preferred_keys:
                if key in value:
                    collect(value[key], True)
            for key in ("thumb", "track_covers", "covers", "artwork", "album"):
                if key in value:
                    collect(value[key], True)
            # Keep walking nested metadata, but only treat strings as images
            # once they are under a known artwork-related key.
            for key, nested in value.items():
                if (
                    key not in preferred_keys
                    and key not in {"thumb", "track_covers", "covers", "artwork", "album"}
                    and isinstance(nested, (dict, list))
                ):
                    collect(nested, image_context or any(
                        marker in str(key).lower()
                        for marker in ("cover", "thumb", "photo", "image", "artwork")
                    ))

        collect(item)
        for value in candidates:
            if len(value) > 2048:
                continue
            if value.startswith("//"):
                value = "https:" + value
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower().rstrip(".")
            trusted_host = (
                host == "vk.com" or host == "userapi.com" or host == "vkuseraudio.net"
                or host == "vkuserphoto.ru" or host == "okcdn.ru"
                or host.endswith((".vk.com", ".userapi.com", ".vkuseraudio.net", ".vkuserphoto.ru", ".okcdn.ru"))
            )
            try:
                port = parsed.port
            except ValueError:
                continue
            if (
                parsed.scheme == "https"
                and trusted_host
                and not parsed.username
                and not parsed.password
                and port in (None, 443)
            ):
                return value
        return ""

    @staticmethod
    def _track_from_item(item, audio_id=""):
        try:
            return VKTrack(
                int(item["owner_id"]),
                int(item["id"] if item.get("id") is not None else item["audio_id"].split("_")[1]),
                str(item.get("artist") or "").strip(),
                str(item.get("title") or "").strip(),
                max(0, int(item.get("duration") or 0)),
                VKClient._cover_from_item(item),
                str(audio_id or item.get("audio_id") or f"{item['owner_id']}_{item.get('id', '')}")[:200],
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def search_tracks(self, query, count=20):
        """Search public VK audio metadata without using a personal account."""
        query = str(query or "").strip()
        if not query or len(query) > 180:
            raise TransferError("Поисковый запрос VK пуст или слишком длинный.")
        payload = self.post(
            "audio.search",
            data={"q": query, "count": max(1, min(int(count), 50)), "sort": 2, "auto_complete": 0},
        )
        items, _ = self._response_items(payload)
        tracks = []
        for item in items:
            if not isinstance(item, dict):
                continue
            track = self._track_from_item(item)
            if track and track.artist and track.title:
                tracks.append(track)
        return tracks

    def fetch_playlist(self, url):
        owner, playlist_id, access_key = parse_vk_playlist_url(url)
        self.token_provider.referer = url
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
        audio_id_by_track = {"_".join(value.split("_")[:2]): value for value in audio_ids}
        tracks = []
        for start in range(0, len(audio_ids), self.AUDIO_BATCH_SIZE):
            batch = audio_ids[start:start + self.AUDIO_BATCH_SIZE]
            payload = self.post("audio.getById", data={"audios": ",".join(batch)})
            items, _ = self._response_items(payload)
            for item in items:
                if isinstance(item, dict):
                    key = f"{item.get('owner_id')}_{item.get('id')}"
                    track = self._track_from_item(item, audio_id_by_track.get(key, ""))
                    if track and track.artist and track.title:
                        tracks.append(track)
        if not tracks:
            raise TransferError("VK не вернул метаданные аудиозаписей.")
        title = self._fetch_playlist_title(owner, playlist_id, access_key)
        return title, tracks

    def _fetch_playlist_title(self, owner_id, playlist_id, access_key=""):
        """Fetch the source playlist title using VK playlist metadata."""
        data = {"owner_id": owner_id, "playlist_id": playlist_id, "extended": 1}
        if access_key:
            data["access_key"] = access_key
        try:
            payload = self.post("audio.getPlaylistById", data=data)
        except TransferError:
            payload = {}
        response = payload.get("response") if isinstance(payload, dict) else None
        title = response.get("title") if isinstance(response, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()[:120]
        return f"Плейлист VK · {playlist_id}"

    def fetch_track(self, url):
        owner_id, track_id, access_key = parse_vk_track_reference(url)
        self.token_provider.referer = url
        audio_id = f"{owner_id}_{track_id}" + (f"_{access_key}" if access_key else "")
        payload = self.post("audio.getById", data={"audios": audio_id})
        items, _ = self._response_items(payload)
        if not items or not isinstance(items[0], dict):
            raise TransferError("VK не вернул аудиозапись. Возможно, она недоступна.")
        track = self._track_from_item(items[0], audio_id)
        if not track or not track.artist or not track.title:
            raise TransferError("VK вернул некорректные данные аудиозаписи.")
        return track


    def get_track_stream(self, audio_id, stream_format="mp3"):
        """Return a fresh, validated CDN URL for one public VK audio item."""
        import re
        from urllib.parse import urlparse

        audio_id = str(audio_id or "").strip()
        if not re.fullmatch(r"-?\d+_\d+(?:_[A-Za-z0-9]+)?", audio_id):
            raise TransferError("Некорректный идентификатор аудиозаписи VK.")
        if stream_format not in {"mp3", "hls_ts"}:
            raise TransferError("Неподдерживаемый формат аудиопотока.")
        payload = self.post("audio.getById", data={"audios": audio_id})
        items, _ = self._response_items(payload)
        if not items or not isinstance(items[0], dict):
            raise TransferError("VK не вернул аудиозапись. Возможно, она недоступна.")
        item = items[0]
        streams = item.get("audio_streams") or []
        stream = next((
            entry for entry in streams
            if isinstance(entry, dict)
            and entry.get("type") == stream_format
            and isinstance(entry.get("url"), str)
            and entry["url"].strip()
        ), None)
        # Some VK responses expose the fresh MP3 URL in the legacy url field.
        if not stream and stream_format == "mp3":
            direct_url = item.get("url")
            if isinstance(direct_url, str) and direct_url.strip():
                stream = {"url": direct_url.strip()}
        if not stream:
            if item.get("content_restricted"):
                raise TransferError("VK не предоставил аудиопоток для этой композиции (ограничение доступа).")
            raise TransferError(f"VK не предоставил поток в формате {stream_format}.")
        url = str(stream["url"])
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        trusted = host == "okcdn.ru" or host.endswith((".okcdn.ru", ".vkuseraudio.ru", ".vkuseraudio.net", ".userapi.com")) or host in {"vkuseraudio.ru", "vkuseraudio.net"}
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if parsed.scheme != "https" or not trusted or port not in (None, 443) or parsed.username or parsed.password:
            raise TransferError("VK вернул небезопасный адрес аудиопотока.")
        return {"url": url, "format": stream_format}


    def resolve_playlist_audio_id(self, playlist_url, base_audio_id):
        """Recover the exact access-key-bearing audio ID from its public playlist."""
        owner, playlist_id, access_key = parse_vk_playlist_url(playlist_url)
        entity_id = f"{owner}_{playlist_id}" + (f"_{access_key}" if access_key else "")
        self.token_provider.referer = playlist_url
        payload = self.post("audio.getIdsBySource", data={
            "source": "playlist", "entity_id": entity_id, "ref": "",
        })
        response = payload.get("response", {})
        refs = response.get("audios", []) if isinstance(response, dict) else []
        for entry in refs if isinstance(refs, list) else []:
            candidate = entry.get("audio_id") if isinstance(entry, dict) else None
            if isinstance(candidate, str) and "_".join(candidate.split("_")[:2]) == base_audio_id:
                return candidate
        raise TransferError("VK не нашёл эту композицию в исходном плейлисте.")
