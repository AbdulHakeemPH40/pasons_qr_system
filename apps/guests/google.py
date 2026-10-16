"""
Server-side verification of a Google ID token (JWT).

Chosen over django-allauth deliberately. allauth brings a full account system
(sign-up, email verification, password reset, socialaccount tables), pulls in
django.contrib.sites and SITE_ID, and adds several packages on Django 6.1.1.
This project needs identity CAPTURE for a campaign list, not accounts, so the
Google Identity Services button plus one verification call is the smaller and
safer tool.

Verification uses the stdlib only (urllib), because the venv has no `requests`
and no `google-auth`. Google's tokeninfo endpoint validates the signature and
the expiry for us and hands back the claims; the checks below then confirm the
token was minted for THIS application.

Three things the caller must never skip, all enforced here:

  aud              the token must belong to our own OAuth client, or a token
                   minted for any other site would be accepted
  iss              Google's own issuer value
  email_verified   an unverified address is not an identity worth storing

The GUEST STILL GIVES A MOBILE NUMBER afterwards: Google never returns one, so
this only fills the name and proves the email.
"""

import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

# Both spellings Google has used for the issuer claim.
_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

# Truthy spellings of email_verified in the claims payload.
_TRUE = frozenset({"true", "1"})

DEFAULT_TIMEOUT = 5


def verify_id_token(credential, client_id, timeout=DEFAULT_TIMEOUT):
    """Return (claims, error). `claims` is None whenever the token is not ours.

    Error codes: not_configured, malformed, rejected, unreachable,
    wrong_audience, wrong_issuer, email_unverified.
    """
    if not client_id:
        return None, "not_configured"
    # A JWT has exactly three dot-separated segments; reject junk before
    # spending a network round trip on it.
    if not credential or credential.count(".") != 2:
        return None, "malformed"

    url = f"{TOKENINFO_URL}?{urlencode({'id_token': credential})}"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
        claims = json.loads(payload)
    except HTTPError:
        # Google answers 400 for an expired, revoked or unknown token.
        return None, "rejected"
    except Exception:
        # Offline, DNS failure, timeout, unparseable body. The guest falls
        # back to the manual form, so this is never fatal.
        return None, "unreachable"

    if not isinstance(claims, dict):
        return None, "rejected"
    if claims.get("aud") != client_id:
        return None, "wrong_audience"
    if claims.get("iss") not in _ISSUERS:
        return None, "wrong_issuer"
    if str(claims.get("email_verified", "")).lower() not in _TRUE:
        return None, "email_unverified"
    if not claims.get("sub"):
        return None, "rejected"
    return claims, ""


def profile_fields_from_claims(claims):
    """Map Google claims onto GuestProfile fields.

    given_name / family_name can be absent (some Workspace accounts), so fall
    back to splitting the display name rather than storing nothing.
    """
    first = (claims.get("given_name") or "").strip()
    last = (claims.get("family_name") or "").strip()
    if not first and not last:
        display = (claims.get("name") or "").strip()
        if display:
            head, _, tail = display.partition(" ")
            first, last = head, tail.strip()
    return {
        "first_name": first[:80],
        "last_name": last[:80],
        "email": (claims.get("email") or "").strip()[:254],
        "google_sub": (claims.get("sub") or "").strip()[:64],
    }
