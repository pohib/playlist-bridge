"""Byte-signature checks for supported audio upload formats."""

SOUNDCLOUD_AUDIO_EXTENSIONS = frozenset({
    ".mp3",
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
    ".ogg",
    ".aac",
    ".amr",
    ".wma",
    ".mp2",
})


def has_audio_file_signature(uploaded, extension):
    """Check file bytes instead of trusting the browser-supplied MIME type."""
    signatures = {
        ".wav": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE",
        ".flac": lambda data: data.startswith(b"fLaC"),
        ".aiff": lambda data: len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"},
        ".aif": lambda data: len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"},
        ".ogg": lambda data: data.startswith(b"OggS"),
        ".amr": lambda data: data.startswith(b"#!AMR"),
        ".wma": lambda data: data.startswith(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")),
        ".aac": lambda data: len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0,
        ".mp3": lambda data: data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        ),
        ".mp2": lambda data: len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0,
    }
    checker = signatures.get(extension)
    if checker is None:
        return False
    try:
        header = uploaded.read(16)
        uploaded.seek(0)
    except (AttributeError, OSError):
        return False
    return checker(header)
