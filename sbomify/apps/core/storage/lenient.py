import posixpath

from django.conf import settings
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class LenientManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """
    A subclass of ManifestStaticFilesStorage that does not raise
    an error if a referenced static file is missing from the manifest.
    If the manifest lookup fails, it falls back to using the original
    file path rather than raising ValueError.
    """

    manifest_strict = False

    def url(self, name, *args, **kwargs):
        try:
            return super().url(name, *args, **kwargs)
        except Exception:
            base = settings.STATIC_URL.rstrip("/")
            return posixpath.join(base, name.lstrip("/"))
