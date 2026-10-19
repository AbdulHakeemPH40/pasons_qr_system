"""
UAE-friendly mobile number normalisation.

The guest types a number in whatever shape is natural ("050 123 4567",
"+971 50 123 4567", "00971501234567"). The campaign platform needs one
consistent shape, so everything is stored as E.164 ("+971501234567").

Two entry points:

  normalise_phone(raw)              the guest typed the whole number, or the
                                    country is unknown
  normalise_with_country(dial, n)   the sheet's country picker supplies the
                                    dial code and the guest types the local
                                    part, so no country guessing is needed

The shape is only half of it now: since the WhatsApp OTP step (2026-10-19)
a number is stored as VERIFIED only after the guest enters the code that was
sent to it. See apps/guests/otp.py.
"""

import re

# Anything that is not a digit is decoration: spaces, dashes, brackets, dots.
_NON_DIGITS = re.compile(r"\D+")

DEFAULT_COUNTRY_CODE = "971"
_MIN_DIGITS = 8
_MAX_DIGITS = 15

# (dial code, English name, ISO 3166-1 alpha-2)
#
# The picker in the guest sheet shows a FLAG and the dial code only. The name
# is never printed: a column of country names is the thing guests scroll past
# and pick wrong, and the flag plus +971 already says which country it is.
# The name still travels in the markup, because search needs it and because a
# screen reader announcing "a flag and 971" is not an accessible name.
#
# UAE first because almost every guest is local, then the Gulf, then the
# countries most of the workforce comes from.
COUNTRIES = (
    ("971", "United Arab Emirates", "ae"),
    ("966", "Saudi Arabia", "sa"),
    ("974", "Qatar", "qa"),
    ("968", "Oman", "om"),
    ("965", "Kuwait", "kw"),
    ("973", "Bahrain", "bh"),
    ("20", "Egypt", "eg"),
    ("962", "Jordan", "jo"),
    ("961", "Lebanon", "lb"),
    ("963", "Syria", "sy"),
    ("970", "Palestine", "ps"),
    ("967", "Yemen", "ye"),
    ("964", "Iraq", "iq"),
    ("212", "Morocco", "ma"),
    ("216", "Tunisia", "tn"),
    ("213", "Algeria", "dz"),
    ("249", "Sudan", "sd"),
    ("91", "India", "in"),
    ("92", "Pakistan", "pk"),
    ("880", "Bangladesh", "bd"),
    ("94", "Sri Lanka", "lk"),
    ("977", "Nepal", "np"),
    ("63", "Philippines", "ph"),
    ("62", "Indonesia", "id"),
    ("90", "Turkey", "tr"),
    ("98", "Iran", "ir"),
    ("44", "United Kingdom", "gb"),
    ("1", "United States", "us"),
    ("33", "France", "fr"),
    ("49", "Germany", "de"),
    ("61", "Australia", "au"),
    ("7", "Russia", "ru"),
    ("86", "China", "cn"),
    ("251", "Ethiopia", "et"),
    ("254", "Kenya", "ke"),
    ("27", "South Africa", "za"),
)

# Words guests actually type into the picker's search box. The name alone is
# not enough: "uae" is not inside "United Arab Emirates", nobody types
# "United States", and the Gulf is called the Gulf.
COUNTRY_ALIASES = {
    "971": "uae emirates dubai abu dhabi sharjah ajman",
    "966": "ksa saudi riyadh jeddah",
    "974": "qatar doha",
    "968": "oman muscat",
    "965": "kuwait",
    "973": "bahrain manama",
    "20": "egypt cairo",
    "962": "jordan amman",
    "961": "lebanon beirut",
    "963": "syria damascus",
    "970": "palestine gaza ramallah",
    "967": "yemen sanaa",
    "964": "iraq baghdad erbil",
    "212": "morocco casablanca",
    "216": "tunisia tunis",
    "213": "algeria algiers",
    "249": "sudan khartoum",
    "91": "india mumbai delhi kerala hyderabad",
    "92": "pakistan karachi lahore islamabad",
    "880": "bangladesh dhaka",
    "94": "sri lanka colombo",
    "977": "nepal kathmandu",
    "63": "philippines manila",
    "62": "indonesia jakarta bali",
    "90": "turkey turkiye istanbul",
    "98": "iran tehran",
    "44": "uk gb britain england scotland london",
    "1": "usa us america",
    "33": "france paris",
    "49": "germany berlin",
    "61": "australia sydney",
    "7": "russia moscow",
    "86": "china beijing",
    "251": "ethiopia addis",
    "254": "kenya nairobi",
    "27": "south africa johannesburg",
}

DIAL_CODES = frozenset(dial for dial, _name, _iso in COUNTRIES)

# Where the sheet's flag images live, relative to STATIC_URL. The 36 files in
# static/img/flags/ are the 80px PNGs from flagcdn.com (public domain flags,
# the site states no attribution is required), pulled once and served from our
# own static folder so the sheet makes no third party request at runtime and
# works offline. A flag only needs replacing when a country is added or its
# flag changes.
FLAG_DIR = "img/flags"


def picker_countries():
    """The rows the sheet's country picker renders, in display order.

    `search` is one lower-case haystack holding the dial code, the ISO code,
    the English name and the aliases, so a single substring test answers
    "971", "uae", "india" and "91" without the browser doing anything clever.

    `label` is the accessible name for the row. The visible row is a flag and
    a dial code, so without this a screen reader would only say "971".
    """
    rows = []
    for dial, name, iso in COUNTRIES:
        haystack = " ".join(
            part for part in (dial, iso, name.lower(), COUNTRY_ALIASES.get(dial, "")) if part
        )
        rows.append(
            {
                "dial": dial,
                "iso": iso,
                "flag": f"{FLAG_DIR}/{iso}.png",
                "label": f"{name} +{dial}",
                "search": haystack,
            }
        )
    return rows


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


def normalise_with_country(dial_code, national):
    """E.164 from the sheet's country picker plus the national part.

    The picker supplies the country, so the trunk zero the guest types is
    simply dropped: 971 + 050 123 4567 -> +971501234567. A guest who pastes a
    full international number into the national box is still understood, which
    is what people do when the number is saved in their phone.
    """
    raw = str(national or "").strip()
    if not raw:
        return ""

    dial = _NON_DIGITS.sub("", str(dial_code or ""))
    if not dial:
        return normalise_phone(raw)

    # A pasted full number wins over the picker: it carries its own country.
    if raw.startswith("+") or raw.startswith("00"):
        return normalise_phone(raw, default_country=dial)

    digits = _NON_DIGITS.sub("", raw)
    if not digits:
        return ""
    digits = digits.lstrip("0")
    if not digits:
        return ""

    candidate = dial + digits
    if not (_MIN_DIGITS <= len(candidate) <= _MAX_DIGITS):
        return ""
    return "+" + candidate
