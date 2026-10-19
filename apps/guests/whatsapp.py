"""
WhatsApp Cloud API delivery for the guest one time code.

One job: hand Meta the six digits and report whether the message was
accepted. Nothing here decides whether a code is allowed (that is
apps.guests.otp) and nothing here stores anything.

The template is an APPROVED Authentication template named `pasons_otp`
(Docs/WHATSAPP_OTP_SETUP.md). Meta builds Authentication templates with two
places the code must appear:

    body    "{{1}} is your verification code."
    button  the URL button's link ends in  code=otp{{1}}

Sending the body alone is refused with (#131008) Required parameter is
missing, so both components are always sent. This was learned the hard way
against the live API, not from the docs.

Safety rules baked in here:

  * The access token is read from settings on every call and is never
    logged, never returned and never put in an error string.
  * WHATSAPP_OTP_DEBUG (forced on during `manage.py test`) skips the network
    entirely and says so in the log. A test must never bill the client.
  * A server with no token FAILS CLOSED. It is tempting to fall back to
    debug delivery when the token is missing, because that keeps a fresh
    machine working. It is also a hole: in production the debug code comes
    back to the browser, so anyone could "verify" any number they liked.
    With no token the send is refused, the guest is asked to try again, and
    the operator sees `not_configured` in the log.
  * Failures are reported as short codes for the view to translate, so an
    API error message cannot leak into a guest-facing page.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.facebook.com"


@dataclass(frozen=True)
class Delivery:
    """Result of a send attempt.

    `debug_code` is filled ONLY in debug mode, so the browser can show the
    code while developing without a WhatsApp account. It is always empty in
    production because the send branch is never taken then.
    """

    ok: bool
    error: str = ""
    debug_code: str = ""


def configured():
    """True when a token and a phone number id are both present."""
    return bool(
        getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
        and getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    )


def debug_mode():
    """True when delivery must not touch the network.

    Only an EXPLICIT `WHATSAPP_OTP_DEBUG` counts. A missing token no longer
    counts, because that would hand the code to the browser in production.
    """
    return bool(getattr(settings, "WHATSAPP_OTP_DEBUG", False))


def _payload(phone, code):
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_OTP_TEMPLATE,
            "language": {"code": settings.WHATSAPP_OTP_LANGUAGE},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": code}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": code}],
                },
            ],
        },
    }


def send_otp(phone, code):
    """Send the code on WhatsApp. Never raises."""
    if not phone or not code:
        return Delivery(False, "bad_input")

    if debug_mode():
        # Readable in runserver output so a developer can finish the flow
        # without a WhatsApp account, and quiet about everything else.
        # Logged at WARNING because Django's default config prints only
        # WARNING and above, and a code nobody can read is no help at all.
        logger.warning("WhatsApp OTP DEBUG for %s: %s", phone, code)
        return Delivery(True, debug_code=code)

    if not configured():
        # FAIL CLOSED. Without this branch the smart-looking fallback would
        # be "pretend it was delivered", which returns the code to the
        # browser and makes verification meaningless on a misconfigured
        # server. Refusing is honest: nothing was sent, so nothing verifies.
        logger.warning(
            "WhatsApp OTP refused: WHATSAPP_ACCESS_TOKEN or "
            "WHATSAPP_PHONE_NUMBER_ID is empty, so no code was sent to %s",
            phone,
        )
        return Delivery(False, "not_configured")

    url = (
        f"{GRAPH_ROOT}/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(_payload(phone, code)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.WHATSAPP_TIMEOUT_SECONDS
        ) as response:
            response.read()
        return Delivery(True)
    except urllib.error.HTTPError as exc:
        # The body carries Meta's error code and message. Useful in the log,
        # useless (and alarming) on a guest's screen, so it stops here.
        try:
            body = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # pragma: no cover - defensive
            body = ""
        logger.warning("WhatsApp OTP send failed: HTTP %s %s", exc.code, body)
        return Delivery(False, f"http_{exc.code}")
    except urllib.error.URLError as exc:
        logger.warning("WhatsApp OTP send failed: network %s", exc.reason)
        return Delivery(False, "network")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("WhatsApp OTP send failed: %s", type(exc).__name__)
        return Delivery(False, "unknown")
