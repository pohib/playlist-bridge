from whitenoise.storage import CompressedManifestStaticFilesStorage


class StrictnessDisabledCompressedManifestStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
