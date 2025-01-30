import json

from .settings import *  # NOQA
from .settings import BASE_DIR  # Import BASE_DIR explicitly

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

SECRET_KEY = "django-insecure-test-key-do-not-use-in-production"  # nosec B105 - This is a test-only key

# Mock AWS settings for testing
AWS_REGION = "test-region"
AWS_ENDPOINT_URL_S3 = "http://test-s3.localhost"
AWS_MEDIA_ACCESS_KEY_ID = "test-key"  # nosec B105
AWS_MEDIA_SECRET_ACCESS_KEY = "test-secret"  # nosec B105
AWS_MEDIA_STORAGE_BUCKET_NAME = "test-media-bucket"
AWS_MEDIA_STORAGE_BUCKET_URL = "http://test-s3.localhost/test-media-bucket"
AWS_SBOMS_ACCESS_KEY_ID = "test-key"  # nosec B105
AWS_SBOMS_SECRET_ACCESS_KEY = "test-secret"  # nosec B105
AWS_SBOMS_STORAGE_BUCKET_NAME = "test-sboms-bucket"
AWS_SBOMS_STORAGE_BUCKET_URL = "http://test-s3.localhost/test-sboms-bucket"

APP_BASE_URL = "http://localhost:8001"

# Django Vite test settings
DJANGO_VITE = {
    "default": {
        "dev_mode": False,
        "manifest_path": str(BASE_DIR / "staticfiles" / "manifest.json"),
    }
}

# Create staticfiles directory if it doesn't exist
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)

# Create a minimal manifest file for testing
manifest = {
    "core/js/main.ts": {
        "file": "assets/main.js",
        "src": "core/js/main.ts",
        "isEntry": True,
        "css": ["assets/main.css"]
    },
    "sboms/js/main.ts": {
        "file": "assets/sboms.js",
        "src": "sboms/js/main.ts",
        "isEntry": True,
        "css": ["assets/sboms.css"]
    },
    "teams/js/main.ts": {
        "file": "assets/teams.js",
        "src": "teams/js/main.ts",
        "isEntry": True,
        "css": ["assets/teams.css"]
    }
}
with open(STATIC_ROOT / "manifest.json", "w") as f:
    json.dump(manifest, f)
