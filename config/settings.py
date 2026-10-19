"""
Django settings for the Pasons Restaurant Smart QR platform.

Stack (spec section 0): Django + DRF + PostgreSQL (production),
SQLite for local development. Frontend is server-rendered
HTML/CSS/JS with a glassmorphism design system (spec 0.1-0.5).
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Stdlib only (no python-dotenv dependency). The .env file is
    authoritative for every key it sets with a real value: it overwrites
    whatever is in the environment, so the dev autoreloader (which passes
    its environment down to every restarted child) never keeps a stale
    value after the file is edited. Blank values are placeholders and only
    fill a missing variable. Lines starting with '#' and blank lines are
    ignored.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if not key:
            continue
        value = value.strip()
        if value:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, "")


_load_env_file(BASE_DIR / ".env")

# Editing .env should restart the dev server automatically, like a code
# change (runserver only watches code otherwise).
try:
    from django.utils.autoreload import autoreload_started

    def _watch_env_file(sender, **kwargs):
        sender.extra_files.add(BASE_DIR / ".env")

    autoreload_started.connect(_watch_env_file, dispatch_uid="pasons_watch_env_file")
except Exception:  # pragma: no cover - autoreload only exists under runserver
    pass

# --- security ------------------------------------------------------------
# The placeholder below is public: it is written in .env.example and in every
# checkout. It is safe only while DEBUG is on.
INSECURE_DEV_SECRET = "django-insecure-dev-only-key-change-in-production"

SECRET_KEY = os.environ.get("SECRET_KEY", INSECURE_DEV_SECRET)

DEBUG = os.environ.get("DEBUG", "1") == "1"

# Fail closed instead of starting a public server on a key anybody can read.
# Session cookies, the signed guest cookie, password reset tokens and the
# round tokens are all derived from SECRET_KEY. A deployment that forgets to
# set a real one must stop at boot, not run with a known value.
if not DEBUG and (SECRET_KEY == INSECURE_DEV_SECRET or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured(
        "SECRET_KEY is missing, too short, or still the development "
        "placeholder while DEBUG is off. Generate one on the server with "
        "python3 -c \"import secrets; print(secrets.token_urlsafe(64))\" "
        "and put it in .env."
    )

# The public address this project answers on. Any absolute link built with no
# request in hand (printed QR images, exports run from a shell) uses it,
# because a host list cannot tell a phone-friendly address from a tunnel name.
# Override it in .env for a staging host.
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://qr-system.pasons.group"
).rstrip("/")

# The host part of that address, kept in ALLOWED_HOSTS by default so the site
# answers on its own domain even when .env lists only an address. Without this
# every request arrives as "Invalid HTTP_HOST header" after a fresh deploy.
PUBLIC_HOST = PUBLIC_BASE_URL.split("://", 1)[-1].split("/")[0]

ALLOWED_HOSTS = [
    h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h
]

if PUBLIC_HOST and PUBLIC_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(PUBLIC_HOST)

# Hosts added on top of ALLOWED_HOSTS for sharing the dev server through a
# tunnel (ngrok, cloudflared, localtunnel...). Kept as a *separate* key because
# .env is authoritative for the keys it sets, so an ALLOWED_HOSTS override on
# the command line would be discarded when .env loads.
ALLOWED_HOSTS += [h for h in os.environ.get("ALLOWED_HOSTS_EXTRA", "").split(",") if h]

# Origins trusted for unsafe (POST) requests arriving through a tunnel, e.g.
# https://<name>.ngrok-free.dev . A tunnel terminates HTTPS and forwards plain
# HTTP, so without this the panel login and the analytics/game beacons are
# rejected with 403 (CSRF origin mismatch).
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# Tell Django the request is really HTTPS when it arrives behind a proxy that
# sets X-Forwarded-Proto (ngrok does). Only enabled when asked via the env, so
# local runs are unaffected.
if os.environ.get("USE_X_FORWARDED_PROTO", "") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- dev tunnel (ngrok, cloudflared, localtunnel) -------------------------
# A free ngrok URL is random and changes on every restart, so pinning one host
# in ALLOWED_HOSTS means editing .env and restarting the server each time the
# tunnel reconnects. In DEBUG the well-known tunnel domains are trusted by
# wildcard instead: any "<name>.ngrok-free.app" is accepted without a config
# change. The suffix list is overridable, and none of this applies when DEBUG
# is off, so a production deploy still needs an explicit ALLOWED_HOSTS.
TUNNEL_HOST_SUFFIXES = [
    s.strip().lstrip(".")
    for s in os.environ.get(
        "TUNNEL_HOST_SUFFIXES",
        "ngrok-free.app,ngrok-free.dev,ngrok.io,ngrok.app,"
        "trycloudflare.com,loca.lt",
    ).split(",")
    if s.strip()
]


def tunnel_trusted_hosts(debug, suffixes):
    """ALLOWED_HOSTS entries for tunnel domains; empty unless DEBUG.

    A leading dot matches the domain and every subdomain of it, so one entry
    covers every random name a provider hands out.
    """
    if not debug:
        return []
    return ["." + s for s in suffixes]


def tunnel_trusted_origins(debug, suffixes):
    """CSRF_TRUSTED_ORIGINS entries for tunnel domains; empty unless DEBUG.

    Django reads a "*" in an origin as a subdomain pattern, and the scheme is
    part of the match, so both schemes are listed for each suffix.
    """
    if not debug:
        return []
    return [
        f"{scheme}://*.{suffix}"
        for suffix in suffixes
        for scheme in ("https", "http")
    ]


ALLOWED_HOSTS += tunnel_trusted_hosts(DEBUG, TUNNEL_HOST_SUFFIXES)

for _origin in tunnel_trusted_origins(DEBUG, TUNNEL_HOST_SUFFIXES):
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

# A tunnel terminates TLS and forwards plain HTTP to runserver. Without this,
# request.is_secure() is False, so Django computes the good origin as
# "http://<tunnel-host>" while the browser sent "https://<tunnel-host>", and
# every POST (panel login, analytics and game beacons) is rejected with a 403
# CSRF failure. runserver never sets X-Forwarded-Proto itself, so plain
# localhost runs are unaffected.
if DEBUG and TUNNEL_HOST_SUFFIXES:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- production hardening ------------------------------------------------
# Everything here is off unless the server environment turns it on, so local
# development over http:// behaves exactly as before. The deployment notes:
#
#   SECURE_SSL_REDIRECT=1, SESSION_COOKIE_SECURE=1 and CSRF_COOKIE_SECURE=1
#   are only correct when the site is served over HTTPS. Turn them on once a
#   domain answers on https:// (nginx + a certificate). With a bare IP over
#   plain http:// they stay off, otherwise every request is redirected to a
#   port that is not listening.
#
#   SECURE_HSTS_SECONDS=31536000 pins HTTPS for a year. Only set it after the
#   HTTPS setup has been verified, because a wrong HSTS value is hard to undo.
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "0") == "1"

# The guest identity cookie (apps/guests) follows the session flag. It must
# NOT follow DEBUG: a Secure cookie is silently dropped by the browser over
# plain http, and the site is served that way until a domain has a
# certificate. Deriving it from DEBUG made every live visit a brand new
# guest, so nobody could keep a coupon. One switch, both cookies.
GUEST_COOKIE_SECURE = os.environ.get(
    "GUEST_COOKIE_SECURE", "1" if SESSION_COOKIE_SECURE else "0"
) == "1"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0") or "0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- guest identity: Google sign-in --------------------------------------
# The guest identity sheet renders "Continue with Google" ONLY when a client
# id is set here, so local development and the test suite never load Google's
# script. The secret is not used by the ID-token flow (the token is verified
# server-side against Google) and is kept for a future code-exchange flow.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

# --- guest identity: WhatsApp OTP -----------------------------------------
# The guest sheet verifies a mobile number by sending a 6 digit code through
# Meta's WhatsApp Cloud API, using the APPROVED authentication template
# `pasons_otp` (see Docs/WHATSAPP_OTP_SETUP.md).
#
# Two switches matter:
#
#   WHATSAPP_OTP_DEBUG  when on, NO network call happens: the code is logged
#                       and returned to the browser. Forced on while the test
#                       suite runs so a test can never send a real message
#                       and bill the client.
#   (no token)          delivery reports `not_configured` and the sheet falls
#                       back to the same debug behaviour for development.
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_WABA_ID = os.environ.get("WHATSAPP_WABA_ID", "").strip()
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v25.0").strip()
WHATSAPP_OTP_TEMPLATE = os.environ.get("WHATSAPP_OTP_TEMPLATE", "pasons_otp").strip()
WHATSAPP_OTP_LANGUAGE = os.environ.get("WHATSAPP_OTP_LANGUAGE", "en").strip()
WHATSAPP_TIMEOUT_SECONDS = int(os.environ.get("WHATSAPP_TIMEOUT_SECONDS", "10") or "10")

# `manage.py test` must never talk to Meta. sys.argv is inspected once here
# rather than in the views, so the belt cannot be forgotten by a new test.
WHATSAPP_OTP_DEBUG = (
    os.environ.get("WHATSAPP_OTP_DEBUG", "0") == "1" or "test" in sys.argv
)

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
    "apps.games",
    "apps.guests",
    "apps.rewards",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Guest identity: attaches a lazy request.guest and sets the signed
    # pq_guest cookie when a view creates a profile. Costs zero queries on a
    # request that has no cookie or never looks at identity (apps/guests).
    "apps.guests.middleware.GuestIdentityMiddleware",
    "apps.core.middleware.PanelCapabilityMiddleware",
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
                "apps.core.context_processors.panel_context",
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
# Staff sign in with their email address OR their username. The email backend
# runs first; ModelBackend after it keeps plain username logins working, so no
# existing account is affected.
AUTHENTICATION_BACKENDS = [
    "apps.core.auth_backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

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

# Media uploads (dish photos, menu PDFs) are written at runtime, so they
# cannot be collected into STATIC_ROOT. Development serves them through
# Django. A server with nginx in front serves /media/ itself (SERVE_MEDIA=0);
# without nginx, set SERVE_MEDIA=1 and Django serves them from the WSGI app.
SERVE_MEDIA = os.environ.get("SERVE_MEDIA", "1" if DEBUG else "0") == "1"

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

# Same-origin framing (needed by same-origin games iframes and multi-outlet preview walls)
X_FRAME_OPTIONS = "SAMEORIGIN"

# --- DRF -----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
