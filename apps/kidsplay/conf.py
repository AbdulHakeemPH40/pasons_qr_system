"""Tunable KidsPlay numbers. Override any key in settings.KIDSPLAY."""

from django.conf import settings


DEFAULTS = {
    "VISIT_DURATION_MINUTES": 120,
    "GAME_TOKEN_MAX_AGE_SECONDS": 900,
    "MAX_POINTS_PER_GAME_PER_VISIT": 60,
    "MAX_POINTS_PER_VISIT": 150,
    "MAX_POINTS_PER_DAY": 200,
    "MAX_GAMES_PER_MINUTE": 4,
    "MAX_KIDS_PER_FAMILY": 5,
    "BILL_BONUS_POINTS": 50,
    "REDEMPTION_EXPIRY_MINUTES": 30,
    "OTP_LENGTH": 6,
    "OTP_TTL_SECONDS": 300,
    "OTP_MAX_ATTEMPTS": 5,
    "OTP_RESEND_COOLDOWN_SECONDS": 60,
    "OTP_PROVIDER": "apps.kidsplay.providers.console.ConsoleOTPProvider",
    "PARTICIPATION_POINTS_NO_SCORE_GAMES": 5,
}


def get(key: str):
    """Return one KidsPlay setting, falling back to the spec default."""
    overrides = getattr(settings, "KIDSPLAY", {}) or {}
    if key in overrides:
        return overrides[key]
    return DEFAULTS[key]
