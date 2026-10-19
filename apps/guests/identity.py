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
from django.db import transaction

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
        # Follows the site-wide HTTPS switch, not DEBUG (see settings). A
        # Secure cookie is dropped without a word over plain http, which
        # silently turns every visit into a new guest.
        secure=getattr(settings, "GUEST_COOKIE_SECURE", False),
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


# --------------------------------------------------------------------------
# sign out, and coming back to the same account
# --------------------------------------------------------------------------
#
# The cookie is a SESSION, not the account. The account is the mobile number,
# because that is the only thing the WhatsApp code actually proves. So:
#
#   sign out   forgets this browser. The row and its coupons stay put.
#   sign in    with a number that a verified account already owns hands this
#              browser that account back, coupons and ladder included.
#
# Without the second half, clearing cookies (or signing out and back in) made
# a second account, and the guest's coupons looked lost. The reward engine
# already treated the number as the person (see rewards.services
# ._profiles_sharing_a_phone); this is the same rule applied to the account.


def clear_guest_cookie(response):
    """Forget this device. The account itself is never deleted."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _merge_into(target, source):
    """Move everything one profile owns onto another, then delete the empty row.

    Only the rows a guest would notice are moved: coupons, the round history,
    and the ladder. Everything else is a fact about the person, and the target
    already holds the authoritative copy, so a blank is filled from the source
    and a value is never overwritten.
    """
    if source.pk == target.pk:
        return target

    # Imported here rather than at module level: apps.rewards imports this
    # app's models, and a top-level import would tie the two modules to a
    # load order that neither of them controls.
    from apps.rewards.models import RewardCoupon, RewardProgress, RewardRound

    with transaction.atomic():
        RewardCoupon.objects.filter(profile=source).update(profile=target)
        RewardRound.objects.filter(profile=source).update(profile=target)

        for row in RewardProgress.objects.filter(profile=source):
            mine = RewardProgress.objects.filter(
                profile=target, game_slug=row.game_slug
            ).first()
            if mine is None:
                row.profile = target
                row.save(update_fields=["profile", "updated_at"])
            else:
                # Two runs on the same ladder: the higher rung wins, because
                # progress is never taken away from a guest.
                if row.rung > mine.rung:
                    mine.rung = row.rung
                    mine.save(update_fields=["rung", "updated_at"])
                row.delete()

        filled = []
        for name in ("first_name", "last_name", "email", "google_sub"):
            if not getattr(target, name) and getattr(source, name):
                setattr(target, name, getattr(source, name))
                filled.append(name)
        for name in ("first_brand_id", "first_outlet_id"):
            if not getattr(target, name) and getattr(source, name):
                setattr(target, name, getattr(source, name))
                filled.append(name)
        if not target.email_verified and source.email_verified:
            target.email_verified = True
            filled.append("email_verified")
        if not target.consent_at and source.consent_at:
            target.consent_marketing = source.consent_marketing
            target.consent_at = source.consent_at
            filled += ["consent_marketing", "consent_at"]
        if not target.ig_claimed_at and source.ig_claimed_at:
            target.ig_follow_claimed = source.ig_follow_claimed
            target.ig_claimed_at = source.ig_claimed_at
            filled += ["ig_follow_claimed", "ig_claimed_at"]
        # The phone lock is "once per calendar month", so the LATER change is
        # the one that counts when two rows are folded together.
        if source.phone_changed_at and (
            target.phone_changed_at is None
            or source.phone_changed_at > target.phone_changed_at
        ):
            target.phone_changed_at = source.phone_changed_at
            filled.append("phone_changed_at")
        if filled:
            target.save(update_fields=filled + ["updated_at"])

        source.delete()
    return target


def number_belongs_to_another(profile, phone):
    """True when a DIFFERENT verified account already holds this number.

    Used by the profile page before it will move an account onto a number.
    One number is one account (the rule `adopt_account` enforces), so a
    second account cannot take it over quietly. The guest is told, and can
    sign in with that number deliberately instead.
    """
    if profile is None or not phone:
        return False
    return (
        GuestProfile.objects.filter(phone=phone, phone_verified=True)
        .exclude(pk=profile.pk)
        .exists()
    )


def adopt_account(request, phone):
    """Point this browser at the account that already owns `phone`.

    Called after a code is verified, which is the moment the guest proved the
    number is theirs. Returns the account, or None when the number is new.

    Never called with an unproved number: that would let a typed number pick
    somebody else's coupons.
    """
    if not phone:
        return None

    handle = getattr(request, "guest", None)
    current = handle.profile if handle is not None else None

    if current is not None and current.phone == phone and current.phone_verified:
        return current

    accounts = list(
        GuestProfile.objects.filter(phone=phone, phone_verified=True).order_by(
            "created_at", "pk"
        )
    )
    if not accounts:
        return None

    # Oldest first, so the surviving row is the account the guest has had
    # longest. Any older duplicates with this same proved number are the same
    # person by the rule the client chose, so they are folded in rather than
    # left behind holding coupons.
    target = accounts[0]
    folded = {row.pk for row in accounts}
    for other in accounts[1:]:
        target = _merge_into(target, other)

    if current is not None and current.pk not in folded:
        if not current.phone_verified:
            # Anonymous history on this device (a game played, an Instagram
            # claim) belongs to whoever just proved the number.
            target = _merge_into(target, current)
        # A row proved with a DIFFERENT number is somebody else's account on a
        # shared phone or tablet. It is left alone, so they can sign back in.

    if handle is not None:
        handle.adopt(target)
    request._guest_cookie_to_set = target.guest_id
    return target
