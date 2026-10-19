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

The mobile number is proved before it is trusted: the sheet sends a six
digit code on WhatsApp (apps.guests.otp) and this view refuses a submit whose
number was not verified in this browser. That is the only defence that stops
one person from entering another person's number, so it is not optional.
"""

import json
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.models import QrCode

from . import identity, otp
from .context import DRAFT_KEY, PHONE_HINT, guest_wallet, sheet_context
from .google import profile_fields_from_claims, verify_id_token
from .phone import normalise_phone, normalise_with_country

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


def _park_draft(request, first_name, last_name, phone, ig_follow, country=""):
    """Keep a failed submit's input server-side, for the next render only."""
    request.session[DRAFT_KEY] = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "ig_follow": ig_follow,
        "country": country,
    }


# --------------------------------------------------------------------------
# WhatsApp one time code (apps.guests.otp)
# --------------------------------------------------------------------------

# Guest-facing wording for every reason the OTP service can answer with. The
# service speaks in codes; English lives here so the two can never drift.
OTP_TEXT = {
    otp.Reason.BAD_PHONE: "That mobile number does not look right.",
    otp.Reason.COOLDOWN: "Please wait a moment before asking for another code.",
    otp.Reason.HOURLY_LIMIT: "You have asked for a few codes already. Try again in a little while.",
    otp.Reason.DAILY_LIMIT: "Too many codes today. Please try again tomorrow.",
    otp.Reason.IP_LIMIT: "Too many requests from this connection. Please try again later.",
    otp.Reason.SEND_FAILED: "We could not send the code. Check the number and try again.",
    otp.Reason.NO_CODE: "Ask for a code first.",
    otp.Reason.EXPIRED: "That code has expired. Send a new one.",
    otp.Reason.WRONG: "That code is not right.",
    otp.Reason.LOCKED: "Too many tries. Send a new code.",
}


def _payload(request):
    """POST body as a dict, from JSON or from a normal form."""
    if (request.content_type or "").startswith("application/json"):
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST


def _posted_phone(data):
    """E.164 from the picker plus the national part, or "" when unusable."""
    country = str(data.get("country") or "").strip()[:8]
    typed = str(data.get("phone") or "").strip()[:40]
    if country:
        return normalise_with_country(country, typed)
    return normalise_phone(typed)


def _client_ip(request):
    """Best-effort caller address for the per-IP send limit.

    Behind the ngrok or nginx tunnel REMOTE_ADDR is the proxy, so the first
    forwarded hop is used when it parses. This is a rate-limit hint, not an
    identity: a spoofed header can only spend someone else's allowance.
    """
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    candidate = forwarded or request.META.get("REMOTE_ADDR") or ""
    return candidate[:45] or None


def _otp_json(outcome, status=200, **extra):
    body = {
        "ok": outcome.ok,
        "reason": outcome.reason,
        "message": "" if outcome.ok else OTP_TEXT.get(outcome.reason, ""),
    }
    if outcome.phone:
        body["phone"] = outcome.phone
    if outcome.retry_after:
        body["retry_after"] = outcome.retry_after
    if outcome.attempts_left:
        body["attempts_left"] = outcome.attempts_left
    if outcome.debug_code:
        body["debug_code"] = outcome.debug_code
    if outcome.skipped:
        body["already_verified"] = True
    body.update(extra)
    return JsonResponse(body, status=status)


@require_POST
def otp_send(request, key):
    """Send a code to the number in the sheet. Answers JSON, never redirects."""
    qr = _qr(key)
    if qr is None:
        return JsonResponse({"ok": False, "reason": "not_found"}, status=404)

    phone = _posted_phone(_payload(request))
    if not phone:
        return JsonResponse(
            {
                "ok": False,
                "reason": otp.Reason.BAD_PHONE,
                "message": OTP_TEXT[otp.Reason.BAD_PHONE],
            },
            status=400,
        )

    # A guest who already proved this exact number on this device does not
    # need another message. Re-verifying the same number is friction with no
    # security value, so it is skipped and the proof is refreshed.
    handle = getattr(request, "guest", None)
    profile = handle.profile if handle is not None else None
    if profile is not None and profile.phone_verified and profile.phone == phone:
        otp.remember(request, phone)
        return _otp_json(
            otp.Outcome(True, otp.Reason.OK, phone=phone, skipped=True),
            resend_after=0,
        )

    outcome = otp.issue(phone, ip=_client_ip(request))
    status = 200
    if not outcome.ok:
        status = 429 if outcome.retry_after else 400
        # The caller needs the number on every refusal too: a cooldown means
        # a code is already on its way to THIS number, and the sheet sends
        # the guest back to the code field rather than to a dead end.
        return _otp_json(outcome, status=status, resend_after=outcome.retry_after, phone=phone)
    return _otp_json(outcome, status=status, resend_after=outcome.retry_after)


@require_POST
def otp_check(request, key):
    """Check a typed code and remember the verified number for this session."""
    qr = _qr(key)
    if qr is None:
        return JsonResponse({"ok": False, "reason": "not_found"}, status=404)

    data = _payload(request)
    phone = _posted_phone(data)
    outcome = otp.verify(phone, data.get("code"))

    if outcome.ok:
        row = (
            otp.PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=False)
            .order_by("-consumed_at")
            .first()
        )
        otp.remember(request, phone, row.pk if row else None)
        return _otp_json(outcome)

    status = 400
    if outcome.reason in (otp.Reason.LOCKED,):
        status = 429
    return _otp_json(outcome, status=status)


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
    country = (request.POST.get("country") or "").strip()[:8]
    typed_phone = (request.POST.get("phone") or "").strip()[:40]
    phone = (
        normalise_with_country(country, typed_phone)
        if country
        else normalise_phone(typed_phone)
    )
    consent = (request.POST.get("consent") or "").lower() in _TRUE_VALUES
    ig_follow = request.POST.get("ig_follow") == "1"

    error = ""
    if not first_name:
        error = "missing_name"
    elif not phone:
        error = "bad_phone"
    elif not consent:
        error = "no_consent"
    elif not otp.consume(request, phone):
        # The number was never proved in this browser, or the proof is for a
        # different number than the one being submitted. Either way the value
        # is only a claim, so it must not be stored as the guest's own.
        error = "phone_unverified"
    if error:
        _park_draft(
            request, first_name, last_name, typed_phone, ig_follow, country
        )
        return _bounce(back, identity_error=error)

    profile, _created = identity.ensure_profile(
        request, brand=qr.brand, outlet=qr.outlet
    )
    now = timezone.now()

    profile.first_name = first_name
    profile.last_name = last_name
    profile.phone = phone
    fields = ["first_name", "last_name", "phone", "updated_at"]

    # The proof was consumed above, so this number is now proved for this
    # profile. That is the only place phone_verified is ever set.
    if not profile.phone_verified:
        profile.phone_verified = True
        fields.append("phone_verified")

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
                    # A number edited later on the profile page has not been
                    # proved, so the tick must go with the old number. Without
                    # this reset a guest could verify once and then swap in
                    # any number while still counting as verified.
                    if profile.phone_verified:
                        profile.phone_verified = False
                        fields.append("phone_verified")
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

