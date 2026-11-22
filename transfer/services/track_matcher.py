# ruff: noqa: I001
"""Provider-independent track normalization and matching scores."""
import re
from difflib import SequenceMatcher

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
