"""
Context builder for the guest identity sheet.

The sheet is ONE component rendered in two places, so its context is built in
one place:

  * the QR landing page  (templates/outlet_landing.html), opened by the
    Instagram card or by a won game
  * the Instagram fallback page (templates/guests/instagram_thanks.html),
    for a guest who reaches the question without the landing page state

What the sheet needs, and why:

  id_base        which panel a card tap or a return-from-Instagram opens
                 ("entry" on the landing page, "ask" on the fallback page)
  id_state       the panel the SERVER rendered open (form after a validation
                 error, "done" after a successful submit)
  id_open        whether to open on load at all (landing page: no)
  id_error_text  a human sentence for the last failed submit
  id_next        where to come back to after a successful submit (allow-listed
                 by the view, never trusted straight from the form)

A failed submit keeps what the guest typed in a one-shot SESSION draft rather
than in the query string: a mobile number must never end up in a URL, where it
would land in browser history and Referer headers. The draft is read and
cleared here, on the very next render of the sheet.
"""

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.rewards.models import RewardCoupon

# Error codes the submit view bounces back with, mapped to guest-facing copy.
ERROR_TEXT = {
    "missing_name": "Please tell us your first name.",
    "bad_phone": "That mobile number does not look right. Try 050 123 4567.",
    "no_consent": "Please tick the box so we can send your offer.",
}

# Where a half-typed form is parked between the failed POST and the re-render.
DRAFT_KEY = "guest_identity_draft"

# Placeholder that shows the expected shape of a UAE mobile number.
PHONE_HINT = "050 123 4567"


def _take_draft(request):
    """Read and clear the parked draft, if any. Never creates a session."""
    session = getattr(request, "session", None)
    if session is None:
        return {}
    draft = session.pop(DRAFT_KEY, None)
    return draft if isinstance(draft, dict) else {}


def sheet_context(request, qr, next_path, base="entry"):
    """Return the sheet's template context for this request."""
    get = request.GET
    error = (get.get("identity_error") or "").strip()
    joined = get.get("joined") == "1"
    draft = _take_draft(request)

    # Which panel the server renders open, and whether the sheet opens at all.
    if joined:
        open_now, open_state = True, "done"
    elif error or draft:
        open_now, open_state = True, "form"
    elif base == "ask":
        open_now, open_state = True, "ask"
    else:
        open_now, open_state = False, base

    profile = None
    handle = getattr(request, "guest", None)
    if handle is not None:
        profile = handle.profile

    return {
        "id_sheet": True,
        "id_action": reverse("guest_identity_submit", args=[qr.redirect_key]),
        "id_qr_key": qr.redirect_key,
        "id_next": next_path,
        "id_base": base,
        "id_state": open_state,
        "id_open": open_now,
        "id_error_text": ERROR_TEXT.get(error, ""),
        "id_ig_follow": "1" if draft.get("ig_follow") else "0",
        "id_phone_hint": PHONE_HINT,
        # Blank unless a Google OAuth client is configured. The sheet hides
        # the Google button when this is empty, so dev and tests never load
        # Google's script.
        "id_google_client_id": settings.GOOGLE_CLIENT_ID,
        "id_first_name": draft.get("first_name", ""),
        "id_last_name": draft.get("last_name", ""),
        "id_phone": draft.get("phone", ""),
        "id_greet": (profile.first_name if (joined and profile) else ""),
    }


def guest_wallet(request, brand):
    """The saved profile and its coupons, for the landing-page profile button.

    Returns None when this browser has no saved profile, so the button stays
    off the page for a first visit. Coupons are this guest's only, and only
    for the brand whose QR they scanned, so a King Chef win never appears on
    a Paramount page.

    An issued coupon past its date reads as expired here without a write.
    The panel is what retires the row.
    """
    handle = getattr(request, "guest", None)
    profile = handle.profile if handle is not None else None
    if profile is None or not profile.is_identified:
        return None

    now = timezone.now()
    rows = []
    if brand is not None:
        coupons = (
            RewardCoupon.objects.filter(profile=profile, brand=brand)
            .select_related("outlet")
            .order_by("-issued_at")[:20]
        )
        for coupon in coupons:
            if coupon.status == RewardCoupon.Status.ISSUED and coupon.expires_at <= now:
                state = "expired"
            else:
                state = coupon.status
            rows.append({"coupon": coupon, "state": state})

    return {
        "profile": profile,
        "coupons": rows,
        "ready": sum(1 for row in rows if row["state"] == RewardCoupon.Status.ISSUED),
        "can_change_phone": profile.can_change_phone(now=now),
        "next_phone_change_date": profile.next_phone_change_date(now=now),
    }

