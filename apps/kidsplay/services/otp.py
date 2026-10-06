"""Phone OTP: issue, throttle, and verify. Delivery is a pluggable provider."""

import hashlib
import secrets
from datetime import timedelta
from importlib import import_module

from django.utils import timezone

from apps.kidsplay import conf
from apps.kidsplay.models import OTPChallenge


def normalize_phone(raw: str) -> str:
    """Keep a leading plus and digits. UAE local numbers become +971."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "971" + digits[1:]
    if len(digits) < 8 or len(digits) > 15:
        return ""
    return f"+{digits}"


def _hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def _provider():
    path = conf.get("OTP_PROVIDER")
    module_name, class_name = path.rsplit(".", 1)
    return getattr(import_module(module_name), class_name)()


def request_code(phone: str, ip: str | None = None) -> tuple[bool, str]:
    """Send a code unless the phone is inside the resend cooldown."""
    phone = normalize_phone(phone)
    if not phone:
        return False, "invalid_phone"
    now = timezone.now()
    cooldown = timedelta(seconds=conf.get("OTP_RESEND_COOLDOWN_SECONDS"))
    recent = OTPChallenge.objects.filter(phone=phone, created_at__gte=now - cooldown).exists()
    if recent:
        return False, "cooldown"
    length = conf.get("OTP_LENGTH")
    code = "".join(secrets.choice("0123456789") for _ in range(length))
    OTPChallenge.objects.create(
        phone=phone,
        code_hash=_hash(phone, code),
        expires_at=now + timedelta(seconds=conf.get("OTP_TTL_SECONDS")),
        ip=ip,
    )
    _provider().send(phone, code)
    return True, "sent"


def verify_code(phone: str, code: str) -> tuple[bool, str]:
    """Check the newest live challenge. Wrong guesses count toward the cap."""
    phone = normalize_phone(phone)
    now = timezone.now()
    challenge = (
        OTPChallenge.objects.filter(phone=phone, consumed_at__isnull=True, expires_at__gt=now)
        .order_by("-created_at")
        .first()
    )
    if challenge is None:
        return False, "expired"
    if challenge.attempts >= conf.get("OTP_MAX_ATTEMPTS"):
        return False, "max_attempts"
    if _hash(phone, code.strip()) != challenge.code_hash:
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        if challenge.attempts >= conf.get("OTP_MAX_ATTEMPTS"):
            return False, "max_attempts"
        return False, "wrong_code"
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    return True, "ok"
