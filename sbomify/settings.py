"""
Django settings for sbomify project.

Generated by 'django-admin startproject' using Django 5.0.4.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
import sentry_sdk
from django.contrib import messages
from dotenv import find_dotenv, load_dotenv

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Define IN_DOCKER early
IN_DOCKER = bool(int(os.environ["AM_I_IN_DOCKER_CONTAINER"])) if "AM_I_IN_DOCKER_CONTAINER" in os.environ else False

API_VERSION = "v1"

# This is used for the SBOM analysis results cache
OSV_SCANNER_RAW_RESULT_EXPIRY_SECONDS = int(os.environ.get("OSV_SCANNER_RAW_RESULT_EXPIRY_SECONDS", 7 * 24 * 3600))

# OSV Scanner subprocess timeout in seconds (default: 5 minutes, less than Dramatiq's 6-minute time limit)
OSV_SCANNER_TIMEOUT_SECONDS = int(os.environ.get("OSV_SCANNER_TIMEOUT_SECONDS", 300))

# Vulnerability scanning cache TTL in seconds (default: 1 hour)
VULNERABILITY_SCAN_CACHE_TTL = int(os.environ.get("VULNERABILITY_SCAN_CACHE_TTL", 3600))

# Dependency Track processing delay in seconds (default: 5 seconds)
# Time to wait after SBOM upload before retrieving results to allow DT to process
DT_PROCESSING_DELAY_SECONDS = int(os.environ.get("DT_PROCESSING_DELAY_SECONDS", 5))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", "")

# Signing salt for signed URLs (should be unique per installation)
SIGNED_URL_SALT = os.environ.get("SIGNED_URL_SALT", "django-insecure-signed-url-salt-CHANGE-ME!")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "False") == "True"

if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Append 'APP_HOSTNAME' value if defined
if os.environ.get("APP_BASE_URL", False):
    ALLOWED_HOSTS.append(urlparse(os.environ.get("APP_BASE_URL")).netloc)

AUTH_USER_MODEL = "core.User"

# Make Django work behind reverse proxy
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_extensions",
    "django_vite",
    "ninja",
    "widget_tweaks",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "core",
    "teams",
    "sboms",
    "documents",
    "access_tokens",
    "billing",
    "notifications",
    "vulnerability_scanning",
    "health_check",
    "health_check.db",
    "anymail",
    "licensing",
]


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


if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

INTERNAL_IPS = [
    "127.0.0.1",
]

ROOT_URLCONF = "sbomify.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.version_context",
            ],
        },
    },
]

WSGI_APPLICATION = "sbomify.wsgi.application"


MESSAGE_TAGS = {
    messages.constants.DEBUG: "alert-info",
    messages.constants.INFO: "alert-info",
    messages.constants.SUCCESS: "alert-success",
    messages.constants.WARNING: "alert-warning",
    messages.constants.ERROR: "alert-danger",
}

# Filter out login success messages
MESSAGE_LEVEL = messages.constants.INFO  # Only show messages of INFO level and above


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Django Vite
DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "dev_server_host": "127.0.0.1",
        "dev_server_port": 5170,
        "manifest_path": str(STATIC_ROOT / "manifest.json"),
    }
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Database


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

# DATABASES = {
#     "default": {
#         "ENGINE": os.environ["SQL_ENGINE"],
#         "NAME": os.environ["SQL_DATABASE"],
#         "USER": os.environ["SQL_USER"],
#         "PASSWORD": os.environ["SQL_PASSWORD"],
#         "HOST": os.environ["SQL_HOST"],
#         "PORT": os.environ["SQL_PORT"],
#     }
# }

# DB_URL = os.environ.get("DATABASE_URL", "")
if "DATABASE_URL" in os.environ:
    db_config_dict = dj_database_url.parse(os.environ["DATABASE_URL"])
else:
    db_config_dict = {}
    DATABASE_USER = os.environ.get("DATABASE_USER", "")
    DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "")
    DATABASE_PORT = os.environ.get("DATABASE_PORT", "")

    if IN_DOCKER:
        DATABASE_HOST = os.environ.get("DOCKER_DATABASE_HOST", "")
    else:
        DATABASE_HOST = os.environ.get("DATABASE_HOST", "")

    db_config_dict = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DATABASE_NAME,
        "USER": DATABASE_USER,
        "PASSWORD": DATABASE_PASSWORD,
        "HOST": DATABASE_HOST,
        "PORT": DATABASE_PORT,
    }


DATABASES = {"default": db_config_dict}

# Redis Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")  # Base URL without db

# Construct specific URLs for cache and worker, both pointing to database 0
REDIS_CACHE_URL = f"{REDIS_URL}/0"
REDIS_WORKER_URL = f"{REDIS_URL}/0"  # Also points to /0

# Cache Configuration
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,  # Use cache-specific URL
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "RETRY_ON_TIMEOUT": True,
            "MAX_CONNECTIONS": 1000,
            "CONNECTION_POOL_KWARGS": {"max_connections": 100},
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Logging config
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s:%(name)s:%(levelname)s:%(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "sbomify": {
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "allauth": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "allauth.socialaccount": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        # "teams": {
        #     "handlers": ["console"],
        #     "level": os.getenv("LOG_LEVEL", "INFO"),
        #     "propagate": False,
        # },
    },
}


# Feature flags
USE_KEYCLOAK = os.environ.get("USE_KEYCLOAK", "").lower() in ("true", "1", "yes")

# Authentication settings
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# AllAuth settings
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_STORE_TOKENS = True
SOCIALACCOUNT_ADAPTER = "core.adapters.CustomSocialAccountAdapter"

# Modern AllAuth configuration
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None

# Keycloak settings
KEYCLOAK_SERVER_URL = os.environ.get("KEYCLOAK_SERVER_URL", "http://keycloak:8080/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "sbomify")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "sbomify")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_ADMIN_USERNAME = os.environ.get("KEYCLOAK_ADMIN_USERNAME", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin")
KEYCLOAK_WEBHOOK_SECRET = os.environ.get("KEYCLOAK_WEBHOOK_SECRET", "")

SOCIALACCOUNT_PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": "keycloak",
                "name": "Keycloak",
                "client_id": KEYCLOAK_CLIENT_ID,
                "secret": KEYCLOAK_CLIENT_SECRET,
                "settings": {
                    "server_url": f"{KEYCLOAK_SERVER_URL}realms/{KEYCLOAK_REALM}/.well-known/openid-configuration",
                },
            }
        ]
    }
}

LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
LOGIN_URL = "/login"

APP_BASE_URL = os.environ.get("APP_BASE_URL", "")
WEBSITE_BASE_URL = os.environ.get("WEBSITE_BASE_URL", APP_BASE_URL)

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Email settings
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@sbomify.com")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)  # For system-generated emails
EMAIL_SUBJECT_PREFIX = "[sbomify] "

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    traces_sample_rate=1.0,
    # Set profiles_sample_rate to 1.0 to profile 100%
    # of sampled transactions.
    # We recommend adjusting this value in production.
    profiles_sample_rate=1.0,
)


# Teams app related config
TEAMS_SUPPORTED_ROLES = [("owner", "Owner"), ("admin", "Admin"), ("guest", "Guest")]
INVITATION_EXPIRY_DAYS = 7  # 7 days


JWT_ISSUER = os.environ.get("JWT_ISSUER", "sbomify")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "sbomify")

# Localstack and AWS/S3 related settings
AWS_REGION = os.environ.get("AWS_REGION", "")
AWS_ENDPOINT_URL_S3 = os.environ.get("AWS_ENDPOINT_URL_S3", "")

AWS_MEDIA_ACCESS_KEY_ID = os.environ.get("AWS_MEDIA_ACCESS_KEY_ID", "")
AWS_MEDIA_SECRET_ACCESS_KEY = os.environ.get("AWS_MEDIA_SECRET_ACCESS_KEY", "")
AWS_MEDIA_STORAGE_BUCKET_NAME = os.environ.get("AWS_MEDIA_STORAGE_BUCKET_NAME", "")
AWS_MEDIA_STORAGE_BUCKET_URL = os.environ.get("AWS_MEDIA_STORAGE_BUCKET_URL", "")

AWS_SBOMS_ACCESS_KEY_ID = os.environ.get("AWS_SBOMS_ACCESS_KEY_ID", "")
AWS_SBOMS_SECRET_ACCESS_KEY = os.environ.get("AWS_SBOMS_SECRET_ACCESS_KEY", "")
AWS_SBOMS_STORAGE_BUCKET_NAME = os.environ.get("AWS_SBOMS_STORAGE_BUCKET_NAME", "")
AWS_SBOMS_STORAGE_BUCKET_URL = os.environ.get("AWS_SBOMS_STORAGE_BUCKET_URL", "")

# Documents S3 settings - fallback to SBOMS bucket if not configured
AWS_DOCUMENTS_ACCESS_KEY_ID = os.environ.get("AWS_DOCUMENTS_ACCESS_KEY_ID", AWS_SBOMS_ACCESS_KEY_ID)
AWS_DOCUMENTS_SECRET_ACCESS_KEY = os.environ.get("AWS_DOCUMENTS_SECRET_ACCESS_KEY", AWS_SBOMS_SECRET_ACCESS_KEY)
AWS_DOCUMENTS_STORAGE_BUCKET_NAME = os.environ.get("AWS_DOCUMENTS_STORAGE_BUCKET_NAME", AWS_SBOMS_STORAGE_BUCKET_NAME)
AWS_DOCUMENTS_STORAGE_BUCKET_URL = os.environ.get("AWS_DOCUMENTS_STORAGE_BUCKET_URL", AWS_SBOMS_STORAGE_BUCKET_URL)

if DEBUG:
    # CSRF settings for development
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

STRIPE_API_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_SECRET_KEY = STRIPE_API_KEY
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_BILLING_URL = os.environ.get("STRIPE_BILLING_URL", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Trial period settings
TRIAL_PERIOD_DAYS = int(os.environ.get("TRIAL_PERIOD_DAYS", "14"))
TRIAL_ENDING_NOTIFICATION_DAYS = int(os.environ.get("TRIAL_ENDING_NOTIFICATION_DAYS", "3"))

# Enable specific notification providers
NOTIFICATION_PROVIDERS = [
    "billing.notifications.get_notifications",
    # "core.notifications.get_notifications",  # For future system-wide notifications
]

# Optionally override refresh interval
NOTIFICATION_REFRESH_INTERVAL = 60 * 1000  # 1 minute

# Billing settings
BILLING = os.getenv("BILLING", "True").lower() == "true"

SITE_ID = 1

# Cloudflare Turnstile settings
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
