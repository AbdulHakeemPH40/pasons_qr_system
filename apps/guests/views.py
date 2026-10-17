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
from .context import DRAFT_KEY, PHONE_HINT, guest_wallet, sheet_context
from .google import profile_fields_from_claims, verify_id_token
from .phone import normalise_phone

# Post-submit destinations we accept. A guest-supplied `next` that is not one
# of our own paths is an open-redirect hole, so anything else falls back to
# this QR's landing page. /games/ is here because the play page renders the
# same sheet in place: a guest who signs in mid-game must come back to that
# game, not be thrown out to the QR page.
_ALLOWED_NEXT_PREFIXES = ("/q/", "/p/", "/games/")

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
        # The play page returns to itself with its own query string
        # (/games/<slug>/?back=/q/<key>/), so a second '?' would swallow the
        # flags into the `back` value and drop them. Append, never re-ask.
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"
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


PROFILE_ERROR_TEXT = {
    "missing_name": "Please enter your first name.",
    "bad_phone": "That mobile number does not look right. Try 050 123 4567.",
    "phone_monthly_limit": "You can only change your mobile number once per month.",
}


@require_http_methods(["GET", "POST"])
def guest_profile_page(request, key):
    """Dedicated guest profile page: edit name anytime, mobile number once per month,
    and view brand-scoped reward coupons.
    """
    qr = _qr(key)
    if qr is None:
        return render(request, "404.html", status=404)

    landing = _landing_url(qr)
    handle = getattr(request, "guest", None)
    profile = handle.profile if handle is not None else None
    if profile is None or not profile.is_identified:
        return redirect(landing)

    now = timezone.now()
    error_code = ""
    saved = request.GET.get("saved") == "1"
    phone_updated = request.GET.get("phone_updated") == "1"

    form_first_name = profile.first_name
    form_last_name = profile.last_name
    form_phone = profile.phone

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()[:80]
        last_name = (request.POST.get("last_name") or "").strip()[:80]
        typed_phone = (request.POST.get("phone") or "").strip()[:40]

        form_first_name = first_name
        form_last_name = last_name
        form_phone = typed_phone or profile.phone

        if not first_name:
            error_code = "missing_name"
        else:
            # If the guest submitted a phone field, normalise and compare;
            # if omitted (e.g. locked input), keep their existing number.
            if "phone" in request.POST and typed_phone:
                normalised_phone = normalise_phone(typed_phone)
            elif "phone" in request.POST and not typed_phone:
                normalised_phone = ""
            else:
                normalised_phone = profile.phone

            phone_is_changing = normalised_phone != profile.phone

            if not normalised_phone:
                error_code = "bad_phone"
            elif phone_is_changing and not profile.can_change_phone(now=now):
                error_code = "phone_monthly_limit"
                form_phone = profile.phone
            else:
                profile.first_name = first_name
                profile.last_name = last_name
                fields = ["first_name", "last_name", "updated_at"]
                if phone_is_changing:
                    was_blank = not profile.phone
                    profile.phone = normalised_phone
                    fields.append("phone")
                    if not was_blank:
                        profile.phone_changed_at = now
                        fields.append("phone_changed_at")
                profile.save(update_fields=fields)
                params = {"saved": "1"}
                if phone_is_changing:
                    params["phone_updated"] = "1"
                return _bounce(
                    reverse("guest_profile_page", args=[qr.redirect_key]),
                    **params,
                )

    wallet = guest_wallet(request, qr.brand)
    can_change_phone = profile.can_change_phone(now=now)
    next_phone_date = profile.next_phone_change_date(now=now)

    context = {
        "qr": qr,
        "brand": qr.brand,
        "outlet": qr.outlet,
        "back_url": landing,
        "guest_wallet": wallet,
        "profile": profile,
        "form_first_name": form_first_name,
        "form_last_name": form_last_name,
        "form_phone": form_phone,
        "phone_hint": PHONE_HINT,
        "can_change_phone": can_change_phone,
        "next_phone_date": next_phone_date,
        "saved": saved,
        "phone_updated": phone_updated,
        "error_code": error_code,
        "error_text": PROFILE_ERROR_TEXT.get(error_code, ""),
    }
    return render(request, "guests/profile.html", context)

