"""
UAE-friendly mobile number normalisation.

The guest types a number in whatever shape is natural ("050 123 4567",
"+971 50 123 4567", "00971501234567"). The campaign platform needs one
consistent shape, so everything is stored as E.164 ("+971501234567").

There is deliberately NO verification step here (client decision
2026-10-16): this only checks the shape. A wrong-but-well-formed number is
stored as unverified, which is why GuestProfile.phone_verified exists.
"""

import re

# Anything that is not a digit is decoration: spaces, dashes, brackets, dots.
_NON_DIGITS = re.compile(r"\D+")

DEFAULT_COUNTRY_CODE = "971"
_MIN_DIGITS = 8
_MAX_DIGITS = 15


def normalise_phone(raw, default_country=DEFAULT_COUNTRY_CODE):
    """Return an E.164 number, or "" when the input cannot be a number.

    Accepted shapes:
        +971501234567   already E.164
        00971501234567  international prefix
        971501234567    country code, no plus
        0501234567      local, leading zero
        501234567       local, no leading zero
    """
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return ""

    explicit_plus = value.startswith("+")
    digits = _NON_DIGITS.sub("", value)
    if not digits:
        return ""

    if explicit_plus:
        candidate = digits
    elif digits.startswith("00"):
        candidate = digits[2:]
    elif digits.startswith("0"):
        # local, with the national trunk zero
        candidate = default_country + digits[1:]
    elif digits.startswith(default_country) and len(digits) > len(default_country) + 7:
        # already carries the country code ("971501234567")
        candidate = digits
    elif _MIN_DIGITS <= len(digits) <= 10:
        # local, trunk zero already dropped ("501234567" is a UAE mobile).
        # A longer run of digits with no + and no country code is treated as
        # a foreign number below, not force-fitted into the local country.
        candidate = default_country + digits
    else:
        candidate = digits

    if not (_MIN_DIGITS <= len(candidate) <= _MAX_DIGITS):
        return ""
    # A national trunk zero must never survive into E.164.
    if candidate.startswith("0"):
        return ""
    return "+" + candidate
