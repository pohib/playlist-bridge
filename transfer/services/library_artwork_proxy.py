"""Safe, bounded fetching of provider artwork for the authenticated proxy."""

from urllib.parse import urljoin, urlsplit

import requests


ALLOWED_ARTWORK_DOMAINS = (
    "userapi.com", "mycdn.me", "vk.com", "vk.ru", "vk.me",
    "vkuserphoto.ru", "vkuseraudio.net", "okcdn.ru", "scdn.co",
    "sndcdn.com", "spotifycdn.com", "spotify.com",
)
MAX_ARTWORK_BYTES = 6 * 1024 * 1024
MAX_ARTWORK_REDIRECTS = 8


class ArtworkProxyError(Exception):
    """Expected, user-safe failure while retrieving artwork."""

    def __init__(self, message, status_code=404):
        super().__init__(message)
        self.status_code = status_code


def is_allowed_artwork_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and bool(host)
        and not parsed.username
        and not parsed.password
        and any(
            host == domain or host.endswith("." + domain)
            for domain in ALLOWED_ARTWORK_DOMAINS
        )
    )


def _detected_image_type(body):
    if body.startswith(bytes.fromhex("FFD8FF")):
        return "image/jpeg"
    if body.startswith(bytes.fromhex("89504E470D0A1A0A")):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if len(body) >= 12 and body[4:8] == b"ftyp" and body[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    return ""


def fetch_provider_artwork(source_url):
    """Return validated image bytes and MIME type, never following untrusted redirects."""
    if not is_allowed_artwork_url(source_url):
        raise ArtworkProxyError("Artwork source is not supported.")

    current_url = source_url
    for _ in range(MAX_ARTWORK_REDIRECTS):
        if not is_allowed_artwork_url(current_url):
            raise ArtworkProxyError("Unsupported artwork redirect.", 400)
        try:
            upstream = requests.get(
                current_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/126.0 Safari/537.36 "
                        "PlaylistBridge/1.0"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://vk.ru/",
                    "Origin": "https://vk.ru",
                },
                timeout=(5, 15),
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ArtworkProxyError("Artwork is temporarily unavailable.") from exc

        if upstream.status_code in {301, 302, 303, 307, 308}:
            location = upstream.headers.get("Location")
            upstream.close()
            if not location:
                raise ArtworkProxyError("Artwork redirect is invalid.")
            current_url = urljoin(current_url, location)
            continue
        if upstream.status_code != 200:
            upstream.close()
            raise ArtworkProxyError("Artwork is unavailable.")

        content_length = upstream.headers.get("Content-Length", "")
        if content_length.isdigit() and int(content_length) > MAX_ARTWORK_BYTES:
            upstream.close()
            raise ArtworkProxyError("Artwork is too large.", 400)

        body = bytearray()
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > MAX_ARTWORK_BYTES:
                    raise ArtworkProxyError("Artwork is too large.", 400)
        except requests.RequestException as exc:
            raise ArtworkProxyError("Artwork is temporarily unavailable.") from exc
        finally:
            upstream.close()

        detected_type = _detected_image_type(body)
        if not detected_type:
            raise ArtworkProxyError("Artwork response is not a supported image.")
        return bytes(body), detected_type

    raise ArtworkProxyError("Too many artwork redirects.")
