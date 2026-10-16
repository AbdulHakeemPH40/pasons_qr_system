"""
Wire format for the guest identity cookie, and the lazy accessor views use.

Two things are deliberate here.

1. The cookie is SIGNED, not a bare token. `guest_id` is what decides whose
   coupons and history a request can reach, so a value the client can invent
   would be an account-takeover primitive. django.core.signing plus a max_age
   means a tampered or stale cookie simply resolves to "no guest".

2. Resolution is LAZY. `request.guest.profile` runs at most one indexed query,
   on first access. A page that does not care about identity (menu, specials,
   panel, static files) never touches it, and a request with no cookie never
   queries at all. This middleware runs on every request, so that matters.
"""

import secrets

from django.conf import settings
from django.core import signing

from .models import GuestProfile

COOKIE_NAME = "pq_guest"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # one year
_SIGNING_SALT = "pasons.guest.identity"


# --------------------------------------------------------------------------
# cookie value wire format
# --------------------------------------------------------------------------

def sign_guest_id(guest_id):
    """Signed cookie value for a guest id."""
    return signing.dumps(guest_id, salt=_SIGNING_SALT, compress=True)


def unsign_guest_id(raw):
    """Guest id from a cookie value, or "" when tampered, stale or malformed."""
    if not raw:
        return ""
    try:
        return signing.loads(raw, salt=_SIGNING_SALT, max_age=COOKIE_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired, ValueError, TypeError):
        return ""


def set_guest_cookie(response, guest_id):
    """Attach the identity cookie to a response."""
    response.set_cookie(
        COOKIE_NAME,
        sign_guest_id(guest_id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        # Secure would stop the cookie working on plain http dev servers.
        secure=not settings.DEBUG,
        path="/",
    )
    return response


# --------------------------------------------------------------------------
# lazy per-request handle
# --------------------------------------------------------------------------

class GuestHandle:
    """`request.guest` -- resolves the profile once, on first attribute use."""

    __slots__ = ("_request", "_resolved", "_profile")

    def __init__(self, request):
        self._request = request
        self._resolved = False
        self._profile = None

    @property
    def profile(self):
        if not self._resolved:
            self._resolved = True
            self._profile = self._load()
        return self._profile

    def adopt(self, profile):
        """Record a profile created or found during this request."""
        self._resolved = True
        self._profile = profile
        return profile

    def _load(self):
        raw = self._request.COOKIES.get(COOKIE_NAME)
        if not raw:
            return None
        guest_id = unsign_guest_id(raw)
        if not guest_id:
            return None
        return GuestProfile.objects.filter(guest_id=guest_id).first()

    def __bool__(self):
        return self.profile is not None


def attach(request):
    """Attach a handle to the request (called by the middleware)."""
    handle = GuestHandle(request)
    request.guest = handle
    return handle


# --------------------------------------------------------------------------
# creating and updating the profile
# --------------------------------------------------------------------------

def _stamp_origin(profile, brand, outlet):
    """Fill first_brand / first_outlet once, without a write when unchanged."""
    updates = []
    if brand is not None and profile.first_brand_id is None:
        profile.first_brand = brand
        updates.append("first_brand")
    if outlet is not None and profile.first_outlet_id is None:
        profile.first_outlet = outlet
        updates.append("first_outlet")
    if updates:
        # updated_at is auto_now: it only persists when named explicitly.
        profile.save(update_fields=updates + ["updated_at"])
    return profile


def ensure_profile(request, brand=None, outlet=None):
    """Return (profile, created), creating the row and the cookie when needed.

    Called by the views that capture identity, never by ordinary page views,
    so an anonymous browse of the menu does not write anything.
    """
    handle = getattr(request, "guest", None)
    if handle is not None:
        existing = handle.profile
        if existing is not None:
            return _stamp_origin(existing, brand, outlet), False

    profile = GuestProfile.objects.create(
        guest_id=secrets.token_urlsafe(18),
        first_brand=brand,
        first_outlet=outlet,
    )
    if handle is not None:
        handle.adopt(profile)
    # Queued for the middleware's response phase: a view may create the
    # profile and then return a redirect, so the cookie is set in one place.
    request._guest_cookie_to_set = profile.guest_id
    return profile, True
