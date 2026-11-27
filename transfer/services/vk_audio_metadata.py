"""Pure normalization helpers for VK audio metadata payloads."""

from urllib.parse import urlparse

from .common import VKTrack


def cover_from_item(item):
    """Extract the first trusted HTTPS artwork URL from a VK payload."""
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
        for key in preferred_keys:
            if key in value:
                collect(value[key], True)
        for key in ("thumb", "track_covers", "covers", "artwork", "album"):
            if key in value:
                collect(value[key], True)
        for key, nested in value.items():
            if (
                key not in preferred_keys
                and key not in {"thumb", "track_covers", "covers", "artwork", "album"}
                and isinstance(nested, (dict, list))
            ):
                collect(
                    nested,
                    image_context or any(
                        marker in str(key).lower()
                        for marker in ("cover", "thumb", "photo", "image", "artwork")
                    ),
                )

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
            or host.endswith((
                ".vk.com", ".userapi.com", ".vkuseraudio.net",
                ".vkuserphoto.ru", ".okcdn.ru",
            ))
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


def track_from_item(item, audio_id=""):
    """Normalize one VK audio object into the internal immutable track type."""
    try:
        return VKTrack(
            int(item["owner_id"]),
            int(item["id"] if item.get("id") is not None else item["audio_id"].split("_")[1]),
            str(item.get("artist") or "").strip(),
            str(item.get("title") or "").strip(),
            max(0, int(item.get("duration") or 0)),
            cover_from_item(item),
            str(audio_id or item.get("audio_id") or f"{item['owner_id']}_{item.get('id', '')}")[:200],
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None
