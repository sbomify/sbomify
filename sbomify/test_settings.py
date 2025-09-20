# Configure Dramatiq to use StubBroker for tests
import dramatiq
from dramatiq.brokers.stub import StubBroker
from dramatiq.results import Results
from dramatiq.results.backends.stub import StubBackend

# Set up the StubBroker with a StubBackend for results
stub_broker = StubBroker()
stub_backend = StubBackend()
stub_broker.add_middleware(Results(backend=stub_backend))
dramatiq.set_broker(stub_broker)

# Mock Stripe settings for testing - set these before any other imports
import os

os.environ["STRIPE_API_KEY"] = "sk_test_dummy_key_for_ci"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy_key_for_ci"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_dummy_key_for_ci"
os.environ["STRIPE_BILLING_URL"] = "https://billing.stripe.com/test"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_webhook_secret_key"

# Mock trial period settings
os.environ["TRIAL_PERIOD_DAYS"] = "14"
os.environ["TRIAL_ENDING_NOTIFICATION_DAYS"] = "3"

# Mock email settings
os.environ["DEFAULT_FROM_EMAIL"] = "test@sbomify.com"
EMAIL_SUBJECT_PREFIX = "[sbomify] "

import json

# Import settings in a way that ensures they are loaded immediately
from django.conf import settings as django_settings

from .settings import *  # NOQA
from .settings import BASE_DIR  # Import BASE_DIR explicitly

# Ensure allauth apps are included in INSTALLED_APPS
if "allauth" not in INSTALLED_APPS:
    INSTALLED_APPS.extend(["allauth", "allauth.account", "allauth.socialaccount", "allauth.socialaccount.providers.openid_connect"])

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",  # Use in-memory SQLite for faster tests
        "ATOMIC_REQUESTS": True,
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Override signed URL salt for testing (required)
SIGNED_URL_SALT = "test-signed-url-salt-unique-per-installation"

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
AWS_DOCUMENTS_ACCESS_KEY_ID = "test-key"  # nosec B105
AWS_DOCUMENTS_SECRET_ACCESS_KEY = "test-secret"  # nosec B105
AWS_DOCUMENTS_STORAGE_BUCKET_NAME = "test-documents-bucket"
AWS_DOCUMENTS_STORAGE_BUCKET_URL = "http://test-s3.localhost/test-documents-bucket"

APP_BASE_URL = "http://localhost:8001"

# Static files configuration
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Add WhiteNoise compression for test similarity
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Django Vite test settings
DJANGO_VITE = {
    "default": {
        "dev_mode": False,  # Always False for tests
        "dev_server_host": "127.0.0.1",
        "dev_server_port": 5170,
        "manifest_path": str(STATIC_ROOT / "manifest.json"),
    }
}

# Ensure staticfiles directory exists
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

# Create manifest in the static directory
manifest = {
    "sbomify/apps/core/js/main.ts": {
        "file": "assets/main.js",
        "src": "sbomify/apps/core/js/main.ts",
        "isEntry": True,
        "css": ["assets/main.css"]
    },
    "sbomify/apps/teams/js/main.ts": {
        "file": "assets/teams.js",
        "src": "sbomify/apps/teams/js/main.ts",
        "isEntry": True,
        "css": ["assets/teams.css"]
    },
    "sbomify/apps/billing/js/main.ts": {
        "file": "assets/billing.js",
        "src": "sbomify/apps/billing/js/main.ts",
        "isEntry": True,
        "css": ["assets/billing.css"]
    },
    "sbomify/apps/core/js/django-messages.ts": {
        "file": "assets/django-messages.js",
        "src": "sbomify/apps/core/js/django-messages.ts",
        "isEntry": True
    },
    "sbomify/apps/core/js/alerts-global.ts": {
        "file": "assets/alerts-global.js",
        "src": "sbomify/apps/core/js/alerts-global.ts",
        "isEntry": True
    },
    "sbomify/apps/sboms/js/main.ts": {
        "file": "assets/sboms.js",
        "src": "sbomify/apps/sboms/js/main.ts",
        "isEntry": True,
        "css": ["assets/sboms.css"]
    },
    "sbomify/apps/vulnerability_scanning/js/main.ts": {
        "file": "assets/vulnerability_scanning.js",
        "src": "sbomify/apps/vulnerability_scanning/js/main.ts",
        "isEntry": True,
        "css": ["assets/vulnerability_scanning.css"]
    },
    "sbomify/apps/documents/js/main.ts": {
        "file": "assets/documents.js",
        "src": "sbomify/apps/documents/js/main.ts",
        "isEntry": True,
        "css": ["assets/documents.css"]
    }
}

# Create manifest file in the static directory
with open(STATIC_ROOT / "manifest.json", "w") as f:
    json.dump(manifest, f)

# Ensure WhiteNoise is configured
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# Add debug toolbar middleware if DEBUG is True
if DEBUG:
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

SITE_URL = "http://testserver"

INVITATION_EXPIRY_DAYS = 7

# Use local memory cache for testing
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

TESTING = True
