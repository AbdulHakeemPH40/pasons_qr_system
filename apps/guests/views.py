"""
Guest identity capture (plan 2026-10-16, task 2).

Two routes, both hung under a QR key so a new profile records where it was
born (first_brand / first_outlet):

  GET  /q/<key>/instagram/thanks/  the fallback page. Same sheet, opened
                                   straight at the follow question. Its real
                                   job is to be a stable link the client can
                                   put in an Instagram bio: "already follow
                                   us? claim your gift here".
  POST /q/<key>/identity/          the single WRITE in this whole flow: first
                                   name, last name, mobile, consent. Bounces
                                   back to the page the guest came from.

Instagram cannot confirm a follow (Meta exposes no such check), so the Yes
answer is stored as SELF-DECLARED and the panel labels it that way.

The mobile number is stored UNVERIFIED (client decision 2026-10-16: no OTP).
Only its shape is checked, in apps.guests.phone.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.models import QrCode

from . import identity
from .context import DRAFT_KEY, sheet_context
from .google import profile_fields_from_claims, verify_id_token
from .phone import normalise_phone

# Post-submit destinations we accept. A guest-supplied `next` that is not one
# of our own paths is an open-redirect hole, so anything else falls back to
# this QR's landing page.
_ALLOWED_NEXT_PREFIXES = ("/q/", "/p/")

# Consent checkboxes post a value; these spellings all mean "ticked".
_TRUE_VALUES = frozenset({"1", "on", "true", "yes"})


def _qr(key):
    return (
        QrCode.objects.select_related("brand", "outlet")
        .filter(redirect_key=key)
        .first()
    )


def _landing_url(qr):
    return reverse("qr_landing", args=[qr.redirect_key])


def _safe_next(value, fallback):
    candidate = (value or "").strip()[:200]
    if candidate.startswith(_ALLOWED_NEXT_PREFIXES) and not candidate.startswith("//"):
        return candidate
    return fallback


def _bounce(url, **params):
    if params:
        url = f"{url}?{urlencode(params)}"
    return redirect(url)


def _park_draft(request, first_name, last_name, phone, ig_follow):
    """Keep a failed submit's input server-side, for the next render only."""
    request.session[DRAFT_KEY] = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "ig_follow": ig_follow,
    }


@require_GET
def instagram_thanks(request, key):
    """Fallback page for the follow question (see the module docstring)."""
    qr = _qr(key)
    if qr is None:
        return render(request, "404.html", status=404)

    context = sheet_context(
        request, qr, next_path=_landing_url(qr), base="ask"
    )
    context.update({"qr": qr, "brand": qr.brand, "outlet": qr.outlet})
    return render(request, "guests/instagram_thanks.html", context)


@require_http_methods(["POST"])
def identity_submit(request, key):
    """Save the guest's name and mobile onto the cookie's profile."""
    qr = _qr(key)
    if qr is None:
        return render(request, "404.html", status=404)

    back = _safe_next(request.POST.get("next"), _landing_url(qr))

    first_name = (request.POST.get("first_name") or "").strip()[:80]
    last_name = (request.POST.get("last_name") or "").strip()[:80]
    typed_phone = (request.POST.get("phone") or "").strip()[:40]
    phone = normalise_phone(typed_phone)
    consent = (request.POST.get("consent") or "").lower() in _TRUE_VALUES
    ig_follow = request.POST.get("ig_follow") == "1"

    error = ""
    if not first_name:
        error = "missing_name"
    elif not phone:
        error = "bad_phone"
    elif not consent:
        error = "no_consent"
    if error:
        _park_draft(request, first_name, last_name, typed_phone, ig_follow)
        return _bounce(back, identity_error=error)

    profile, _created = identity.ensure_profile(
        request, brand=qr.brand, outlet=qr.outlet
    )
    now = timezone.now()

    profile.first_name = first_name
    profile.last_name = last_name
    profile.phone = phone
    fields = ["first_name", "last_name", "phone", "updated_at"]

    # Consent is stamped once, so a later visit cannot silently backdate it.
    if not profile.consent_at:
        profile.consent_marketing = True
        profile.consent_at = now
        fields += ["consent_marketing", "consent_at"]

    # A follow claim is kept once made: answering "not yet" later must not
    # erase the claim that earned the draw entry.
    if ig_follow and not profile.ig_claimed_at:
        profile.ig_follow_claimed = True
        profile.ig_claimed_at = now
        fields += ["ig_follow_claimed", "ig_claimed_at"]

    profile.save(update_fields=fields)

    request.session.pop(DRAFT_KEY, None)
    return _bounce(back, joined="1")


@require_POST
def identity_google(request, key):
    """Verify a Google ID token and pre-fill the guest's name and email.

    Called by the sheet's JavaScript with the credential the Google button
    returned. Answers JSON so the sheet can fill the fields in place and move
    on to the mobile step, which Google cannot supply.

    This is used INSTEAD of a login: no auth.User row is created, and the
    guest never gets a session they could confuse with a staff login.
    """
    qr = _qr(key)
    if qr is None:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if not settings.GOOGLE_CLIENT_ID:
        return JsonResponse({"ok": False, "error": "not_configured"}, status=400)

    credential = (request.POST.get("credential") or "").strip()[:4096]
    claims, error = verify_id_token(credential, settings.GOOGLE_CLIENT_ID)
    if claims is None:
        return JsonResponse({"ok": False, "error": error}, status=400)

    profile, _created = identity.ensure_profile(
        request, brand=qr.brand, outlet=qr.outlet
    )
    fields = profile_fields_from_claims(claims)

    updated = ["updated_at"]
    if fields["first_name"]:
        profile.first_name = fields["first_name"]
        updated.append("first_name")
    if fields["last_name"]:
        profile.last_name = fields["last_name"]
        updated.append("last_name")
    if fields["email"]:
        profile.email = fields["email"]
        profile.email_verified = True
        profile.google_sub = fields["google_sub"]
        updated += ["email", "email_verified", "google_sub"]
    profile.save(update_fields=updated)

    return JsonResponse(
        {
            "ok": True,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
        }
    )
