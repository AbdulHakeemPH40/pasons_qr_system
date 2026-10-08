"""
Django settings for the Pasons Restaurant Smart QR platform.

Stack (spec section 0): Django + DRF + PostgreSQL (production),
SQLite for local development. Frontend is server-rendered
HTML/CSS/JS with a glassmorphism design system (spec 0.1-0.5).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- security ------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-key-change-in-production",
)

DEBUG = os.environ.get("DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h
]

# --- applications --------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    # Pasons apps
    "apps.core",
    "apps.menu",
    "apps.engagement",
    "apps.analytics",
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
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- database ------------------------------------------------------------
# Production: PostgreSQL via DATABASE_URL-style env vars (spec section 0).
# Development: SQLite (no local PostgreSQL required).
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "pasons"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --- auth ----------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n ----------------------------------------------------------------
# Phase 1 ships English (LTR); structure is RTL-ready for Arabic (spec 0.5, 20).
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("ar", "Arabic"),
]
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True

# --- static / media (CDN-ready) ------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Django 4.2+ STORAGES dict — WhiteNoise serves compressed, cache-fingerprinted
# static files without a separate web server. Swap the static backend for a
# CDN (S3 + CloudFront) in production by setting CDN_STATIC_ENABLED=1.
# Dev/test: CompressedStaticFilesStorage (no manifest needed).
# Production: CompressedManifestStaticFilesStorage (hashed filenames + 1yr cache).
if os.environ.get("CDN_STATIC_ENABLED") == "1":
    # Production: static assets served from a CDN origin (S3/GCS).
    # Requires django-storages + the relevant cloud SDK in requirements.
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
elif DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# WhiteNoise: serve immutable, content-hashed static files with long-lived
# cache headers (spec §0.2 "fast-loading" / §32 performance budget).
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year — filenames are hashed
WHITENOISE_COMPRESS = True  # gzip + brotli fallback for modern browsers

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "panel_dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- DRF -----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
