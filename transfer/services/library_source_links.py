"""Safe outbound links to supported music-provider source pages."""

from urllib.parse import urlsplit


_PROVIDER_HOSTS = {
    "vk": {"vk.com", "www.vk.com", "m.vk.com", "vk.ru"},
    "spotify": {"open.spotify.com", "www.open.spotify.com"},
    "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
    "youtube_music": {"music.youtube.com", "www.youtube.com", "youtube.com"},
    "apple_music": {"music.apple.com"},
}


def safe_provider_source_url(value, provider):
    """Return a provider URL only when its origin matches the provider allowlist."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return ""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""

    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or host not in _PROVIDER_HOSTS.get(provider, set())
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return ""

    return value
