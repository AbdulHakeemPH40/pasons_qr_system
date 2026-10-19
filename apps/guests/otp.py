"""
One time codes for guest mobile numbers: issue, resist abuse, check.

The guest types a number, WhatsApp delivers six digits, the guest types them
back, and only then does the profile say `phone_verified`. This module owns
every rule in that sentence. The view layer only translates the reason codes
below into English, so the limits cannot drift between the two.

The rules, and why each one exists:

  lifetime      5 minutes, the same number the message prints on the phone.
                A longer server window would accept a code the guest's own
                message calls expired.
  attempts      5 wrong guesses kill the code. Six digits is a million
                possibilities; five guesses is one in 200,000 per code.
  resend        60 seconds between sends to one number, and the older code
                dies the moment a new one is issued.
  per hour      3 codes per number, 10 per day. Stops a script from using a
                guest's number as a free SMS gateway.
  per IP        12 sends an hour from one address. Cheap protection against
                someone cycling through numbers.
  hashing       PBKDF2 (Django's default hasher) with a per-row salt. The
                digits are never stored, so a database copy is not a list of
                live codes.

Nothing here trusts the browser: the phone is normalised by the caller from
the country picker, and the proof that a number was verified lives in the
server session, not in a hidden form field.
"""

import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from . import whatsapp
from .models import PhoneOTP

CODE_LENGTH = 6
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_HOUR = 3
MAX_SENDS_PER_DAY = 10
MAX_SENDS_PER_IP_PER_HOUR = 12

# How long a verified number stays good for the form that follows it. Long
# enough to fix a misspelled name, short enough that a walked-away phone does
# not vouch for a stranger.
PROOF_MAX_AGE_SECONDS = 30 * 60
SESSION_KEY = "pq_guest_phone_proof"


class Reason:
    """Stable reason codes. The view maps these; tests assert on these."""

    OK = "ok"
    COOLDOWN = "cooldown"
    HOURLY_LIMIT = "hourly_limit"
    DAILY_LIMIT = "daily_limit"
    IP_LIMIT = "too_many_requests"
    SEND_FAILED = "send_failed"
    BAD_PHONE = "bad_phone"
    NO_CODE = "no_code"
    EXPIRED = "expired"
    WRONG = "wrong"
    LOCKED = "locked"


@dataclass
class Outcome:
    ok: bool
    reason: str = Reason.OK
    retry_after: int = 0
    attempts_left: int = 0
    debug_code: str = ""
    phone: str = ""
    # True when the profile was already verified for this exact number, so no
    # message was sent and the guest goes straight through.
    skipped: bool = False


def _ceil_seconds(delta):
    return max(0, int(math.ceil(delta.total_seconds())))


def _seconds_until_slot(rows, limit, window, now):
    """Seconds until the oldest of `rows` leaves `window`, freeing a slot."""
    if len(rows) < limit:
        return 0
    oldest = rows[-1]
    return _ceil_seconds(oldest.created_at + window - now)


def issue(phone, ip=None):
    """Create, send and return a new code for `phone`."""
    if not phone:
        return Outcome(False, Reason.BAD_PHONE)

    now = timezone.now()
    recent = PhoneOTP.objects.filter(phone=phone).order_by("-created_at")
    last = recent.first()

    if last is not None:
        elapsed = now - last.created_at
        cooldown = timedelta(seconds=RESEND_COOLDOWN_SECONDS)
        if elapsed < cooldown:
            return Outcome(
                False,
                Reason.COOLDOWN,
                retry_after=_ceil_seconds(cooldown - elapsed),
            )

    hour_rows = list(recent.filter(created_at__gte=now - timedelta(hours=1))[:MAX_SENDS_PER_HOUR])
    if len(hour_rows) >= MAX_SENDS_PER_HOUR:
        return Outcome(
            False,
            Reason.HOURLY_LIMIT,
            retry_after=_seconds_until_slot(
                hour_rows, MAX_SENDS_PER_HOUR, timedelta(hours=1), now
            ),
        )

    day_rows = list(recent.filter(created_at__gte=now - timedelta(days=1))[:MAX_SENDS_PER_DAY])
    if len(day_rows) >= MAX_SENDS_PER_DAY:
        return Outcome(
            False,
            Reason.DAILY_LIMIT,
            retry_after=_seconds_until_slot(
                day_rows, MAX_SENDS_PER_DAY, timedelta(days=1), now
            ),
        )

    if ip:
        per_ip = PhoneOTP.objects.filter(
            sent_ip=ip, created_at__gte=now - timedelta(hours=1)
        ).count()
        if per_ip >= MAX_SENDS_PER_IP_PER_HOUR:
            return Outcome(
                False,
                Reason.IP_LIMIT,
                retry_after=RESEND_COOLDOWN_SECONDS,
            )

    code = f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"
    row = PhoneOTP.objects.create(
        phone=phone,
        code_hash=make_password(code),
        expires_at=now + PhoneOTP.ttl(),
        sent_ip=ip or None,
    )

    delivery = whatsapp.send_otp(phone, code)
    row.delivered = delivery.ok
    row.delivery_error = "" if delivery.ok else delivery.error[:120]
    row.save(update_fields=["delivered", "delivery_error", "updated_at"])

    if not delivery.ok:
        # A failed send must not cost the guest their allowance. The row is
        # removed so the cooldown and the hourly window stay honest.
        row.delete()
        return Outcome(False, Reason.SEND_FAILED, retry_after=RESEND_COOLDOWN_SECONDS)

    # Only the newest code may work. An older, still valid code is spent now.
    PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=True).exclude(
        pk=row.pk
    ).update(consumed_at=now, updated_at=now)

    return Outcome(
        True,
        Reason.OK,
        retry_after=RESEND_COOLDOWN_SECONDS,
        debug_code=delivery.debug_code,
        phone=phone,
    )


def verify(phone, code):
    """Check a typed code. Returns an Outcome; never raises."""
    if not phone:
        return Outcome(False, Reason.BAD_PHONE)

    typed = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not typed:
        return Outcome(False, Reason.WRONG, attempts_left=MAX_ATTEMPTS)

    now = timezone.now()
    row = (
        PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if row is None:
        return Outcome(False, Reason.NO_CODE)

    if row.is_expired(now=now):
        row.spend(now=now)
        return Outcome(False, Reason.EXPIRED)

    if row.attempts >= MAX_ATTEMPTS:
        row.spend(now=now)
        return Outcome(False, Reason.LOCKED)

    if check_password(typed, row.code_hash):
        row.spend(now=now)
        return Outcome(True, Reason.OK, phone=phone)

    row.attempts += 1
    row.save(update_fields=["attempts", "updated_at"])
    left = row.attempts_left(MAX_ATTEMPTS)
    if left <= 0:
        row.spend(now=now)
        return Outcome(False, Reason.LOCKED, attempts_left=0)
    return Outcome(False, Reason.WRONG, attempts_left=left)


# --------------------------------------------------------------------------
# session proof: "this browser verified this number a moment ago"
# --------------------------------------------------------------------------

def remember(request, phone, otp_id=None):
    """Record a verified number for the form submit that follows."""
    session = getattr(request, "session", None)
    if session is None:
        return
    session[SESSION_KEY] = {
        "phone": phone,
        "otp": otp_id or 0,
        "at": timezone.now().isoformat(),
    }


def _fresh(entry, now):
    try:
        stamp = datetime.fromisoformat(entry.get("at", ""))
    except (TypeError, ValueError):
        return False
    if timezone.is_naive(stamp):
        stamp = timezone.make_aware(stamp, timezone.get_current_timezone())
    return (now - stamp).total_seconds() <= PROOF_MAX_AGE_SECONDS


def proof_phone(request):
    """The number this session verified recently, or ""."""
    session = getattr(request, "session", None)
    if session is None:
        return ""
    entry = session.get(SESSION_KEY)
    if not isinstance(entry, dict):
        return ""
    if not _fresh(entry, timezone.now()):
        session.pop(SESSION_KEY, None)
        return ""
    return entry.get("phone") or ""


def consume(request, phone):
    """True once, if this session verified exactly this number and is fresh.

    The proof is popped on success so one verification cannot be replayed
    into two profiles.
    """
    if not phone:
        return False
    session = getattr(request, "session", None)
    if session is None:
        return False
    entry = session.get(SESSION_KEY)
    if not isinstance(entry, dict) or not _fresh(entry, timezone.now()):
        session.pop(SESSION_KEY, None)
        return False
    if entry.get("phone") != phone:
        return False
    session.pop(SESSION_KEY, None)
    return True
