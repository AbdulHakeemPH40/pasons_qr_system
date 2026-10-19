"""
WhatsApp code reporting for the staff panel.

The client asked one question: how many codes did we send, how many arrived,
who did they go to, and per branch. That sentence needs four different cuts of
the same table, so the arithmetic lives here and the view only passes a
scoped queryset in.

Design rules:

  * Counts are read-time aggregates over PhoneOTP. Nothing is pre-computed,
    so a code that fails at 14:59 is in today's number at 15:00 with no job.
  * Three numbers, kept separate on purpose. `sent` is every attempt,
    `delivered` is what WhatsApp accepted, `verified` is what a guest typed
    back correctly. A page that shows one number would hide the difference
    between "the provider is failing" and "the guests are not finishing".
  * Windows are calendar windows in the restaurant's timezone, not rolling
    24-hour blocks: "today" at 00:30 must be one code, not yesterday's total.
  * No money figures. The client chose counts only, so nothing here guesses
    a rate or a currency.
  * Branch attribution comes from the QR page the guest was on, captured at
    send time. Rows written before that column existed stay "Not recorded":
    guessing them from a guest's later profile would move a real number to
    the wrong branch.
"""

import re
from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.panel_permissions import is_head_office, scoped_brands, scoped_outlets

from .models import GuestProfile, PhoneOTP
from .phone import COUNTRIES, FLAG_DIR

_DIGITS = re.compile(r"\D+")

# Dial codes sorted longest first, so +971 never matches as +9 and +1 does
# not swallow +971. Built once at import; the table is a constant.
_DIALS = sorted(COUNTRIES, key=lambda row: len(row[0]), reverse=True)
_ISO_BY_DIAL = {dial: iso.upper() for dial, _name, iso in COUNTRIES}


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------
def scoped_codes(user):
    """Every code this person may see.

    Head office: everything, including rows written before branches were
    recorded. A manager: the codes of their own branches, plus the codes of
    their brand's own (branch-less) page. Scoping on the outlet alone would
    hide the brand page; scoping on the brand alone would show a branch
    manager the whole chain.
    """
    qs = PhoneOTP.objects.select_related("brand", "outlet")
    if is_head_office(user):
        return qs
    outlets = scoped_outlets(user)
    brand_ids = list(outlets.values_list("brand_id", flat=True).distinct())
    return qs.filter(Q(outlet__in=outlets) | Q(outlet__isnull=True, brand_id__in=brand_ids))


def branch_choices(user):
    """Branches for the filter, inside the user's own scope."""
    return scoped_outlets(user).select_related("brand").order_by("brand__name_en", "official_name")


def brand_choices(user):
    return scoped_brands(user).order_by("name_en")


def filter_by_branch(qs, user, outlet_id):
    """Narrow to one branch the user may already see. Unknown ids are ignored."""
    if not outlet_id:
        return qs
    allowed = scoped_outlets(user).filter(pk=outlet_id).first()
    if allowed is None:
        return qs
    return qs.filter(outlet=allowed)


def _number_variants(text):
    """The digit shapes a staff member might type for one number.

    Numbers are stored as E.164 ("+971507778888") but people read them off a
    receipt or hear them on the phone ("050 777 8888", "00971 50 777 8888").
    Matching only the typed string would make the search look broken for the
    most common shape, so the trunk zero and the international prefix are
    tried as well.
    """
    digits = _DIGITS.sub("", text or "")
    if not digits:
        return []
    out = {digits}
    if digits.startswith("00"):
        out.add(digits[2:])
    if digits.startswith("0"):
        out.add(digits[1:])
        out.add("971" + digits[1:])
    return [value for value in out if len(value) >= 6]


def filter_by_search(qs, text):
    """Match a phone number, or a guest name, in whatever shape was typed."""
    text = (text or "").strip()
    if not text:
        return qs
    variants = _number_variants(text) or [text]
    condition = Q(phone__icontains=text)
    for variant in variants:
        condition |= Q(phone__icontains=variant)
    names = (
        GuestProfile.objects.filter(
            Q(first_name__icontains=text)
            | Q(last_name__icontains=text)
            | Q(phone__icontains=variants[0])
        )
        .values_list("phone", flat=True)
        .distinct()[:300]
    )
    phones = [p for p in names if p]
    if phones:
        condition |= Q(phone__in=phones)
    return qs.filter(condition)


# --------------------------------------------------------------------------
# the six windows the client named
# --------------------------------------------------------------------------
def _at(day, hour=0):
    """Aware datetime for a local calendar day."""
    naive = datetime.combine(day, time(hour=hour))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _first_of_month(day, offset=0):
    month = day.month - offset
    year = day.year
    while month <= 0:
        month += 12
        year -= 1
    return day.replace(year=year, month=month, day=1)


def periods(now=None):
    """Today, yesterday, 7 days, 30 days, this month, last month.

    Each entry carries a start (inclusive) and an end (exclusive) so two
    neighbouring windows can never count the same code twice. The range
    label is what the panel prints under the name, so a manager reading
    "Last 30 days" also sees the dates it actually covers.
    """
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    month_start = today.replace(day=1)
    last_month_start = _first_of_month(today, offset=1)

    def label(start, end):
        last = (end - timedelta(seconds=1)).date()
        if start.date() == last:
            return start.strftime("%d %b %Y")
        return f"{start:%d %b} - {last:%d %b %Y}"

    spec = [
        ("today", "Today", today, today + timedelta(days=1)),
        ("yesterday", "Yesterday", today - timedelta(days=1), today),
        ("week", "Last 7 days", today - timedelta(days=6), today + timedelta(days=1)),
        ("month30", "Last 30 days", today - timedelta(days=29), today + timedelta(days=1)),
        ("this_month", "This month", month_start, today + timedelta(days=1)),
        ("last_month", "Last month", last_month_start, month_start),
    ]
    rows = []
    for key, name, start, end in spec:
        start_at = _at(start)
        end_at = _at(end)
        rows.append(
            {
                "key": key,
                "label": name,
                "range": label(start_at, end_at),
                "start": start_at,
                "end": end_at,
            }
        )
    return rows


def counts(qs, start, end):
    """Sent, delivered and verified inside one window."""
    row = qs.filter(created_at__gte=start, created_at__lt=end).aggregate(
        sent=Count("id"),
        delivered=Count("id", filter=Q(delivered=True)),
        verified=Count("id", filter=Q(verified_at__isnull=False)),
        guests=Count("phone", distinct=True),
    )
    return {
        "sent": row["sent"] or 0,
        "delivered": row["delivered"] or 0,
        "verified": row["verified"] or 0,
        "guests": row["guests"] or 0,
    }


def _percent(part, whole):
    if not whole:
        return 0
    return round(100 * part / whole)


def period_rows(qs, now=None):
    """The six windows, each with its own counts and rates."""
    out = []
    for window in periods(now=now):
        numbers = counts(qs, window["start"], window["end"])
        numbers["delivery_pct"] = _percent(numbers["delivered"], numbers["sent"])
        numbers["verified_pct"] = _percent(numbers["verified"], numbers["delivered"])
        out.append({**window, **numbers})
    return out


# --------------------------------------------------------------------------
# trends
# --------------------------------------------------------------------------
def monthly_trend(qs, months=6, now=None):
    """Six calendar months, oldest first, zero filled.

    A bar chart with missing months is a lie about the shape of the data, so
    every month in the range appears even when it sent nothing.
    """
    now = timezone.localtime(now or timezone.now())
    first = timezone.make_aware(
        datetime.combine(
            _first_of_month(now.date(), offset=months - 1), time.min
        ),
        timezone.get_current_timezone(),
    )
    rows = (
        qs.filter(created_at__gte=first)
        .values("created_at__year", "created_at__month")
        .annotate(
            sent=Count("id"),
            delivered=Count("id", filter=Q(delivered=True)),
            verified=Count("id", filter=Q(verified_at__isnull=False)),
        )
        .order_by("created_at__year", "created_at__month")
    )
    lookup = {(r["created_at__year"], r["created_at__month"]): r for r in rows}

    out = []
    for step in range(months - 1, -1, -1):
        month_start = _first_of_month(now.date(), offset=step)
        row = lookup.get((month_start.year, month_start.month), {})
        sent = row.get("sent", 0) or 0
        delivered = row.get("delivered", 0) or 0
        out.append(
            {
                "key": f"{month_start:%Y-%m}",
                "label": month_start.strftime("%b"),
                "long_label": month_start.strftime("%B %Y"),
                "sent": sent,
                "delivered": delivered,
                # The template cannot subtract, so the refused slice is
                # computed here rather than faked with an `add` filter.
                "failed": max(0, sent - delivered),
                "verified": row.get("verified", 0) or 0,
            }
        )
    peak = max((m["sent"] for m in out), default=0)
    for month in out:
        # A month with one code must still show a visible bar, or the chart
        # reads as empty and the manager thinks nothing was sent.
        month["pct"] = max(6, round(100 * month["sent"] / peak)) if peak and month["sent"] else 0
    return out


# --------------------------------------------------------------------------
# cuts by branch and by destination country
# --------------------------------------------------------------------------
def by_branch(qs, start, end):
    """One row per branch, busiest first, with unattributed rows last."""
    rows = (
        qs.filter(created_at__gte=start, created_at__lt=end)
        .values("outlet_id", "outlet__official_name", "brand__name_en")
        .annotate(
            sent=Count("id"),
            delivered=Count("id", filter=Q(delivered=True)),
            verified=Count("id", filter=Q(verified_at__isnull=False)),
        )
        .order_by("-sent")
    )
    out = []
    for row in rows:
        if row["outlet_id"]:
            label = row["outlet__official_name"]
            kind = "branch"
        elif row["brand__name_en"]:
            label = row["brand__name_en"]
            kind = "brand"
        else:
            label = "Not recorded"
            kind = "unknown"
        out.append(
            {
                "label": label,
                "kind": kind,
                "sent": row["sent"] or 0,
                "delivered": row["delivered"] or 0,
                "verified": row["verified"] or 0,
                "delivery_pct": _percent(row["delivered"] or 0, row["sent"] or 0),
            }
        )
    # Keep "Not recorded" at the bottom whatever its count: it is a data gap,
    # not a branch, and sorting it among real branches invites a wrong read.
    out.sort(key=lambda r: (r["kind"] == "unknown", -r["sent"]))
    return out


def dial_code(phone):
    """The country dial code of an E.164 number, longest match first."""
    digits = _DIGITS.sub("", phone or "")
    for dial, _name, _iso in _DIALS:
        if digits.startswith(dial):
            return dial
    return ""


def by_country(qs, start, end, limit=8):
    """Destination countries, because that is what a message bill follows."""
    phones = list(
        qs.filter(created_at__gte=start, created_at__lt=end).values_list(
            "phone", "delivered", "verified_at"
        )
    )
    tally = {}
    for phone, delivered, verified in phones:
        dial = dial_code(phone)
        iso = _ISO_BY_DIAL.get(dial, "")
        bucket = tally.setdefault(
            dial,
            {
                "dial": dial,
                "iso": iso,
                "flag": f"{FLAG_DIR}/{iso.lower()}.png" if iso else "",
                "sent": 0,
                "delivered": 0,
                "verified": 0,
            },
        )
        bucket["sent"] += 1
        if delivered:
            bucket["delivered"] += 1
        if verified:
            bucket["verified"] += 1
    rows = sorted(tally.values(), key=lambda r: (-r["sent"], r["dial"]))
    for row in rows:
        row["delivery_pct"] = _percent(row["delivered"], row["sent"])
    return rows[:limit]


# --------------------------------------------------------------------------
# who the codes went to
# --------------------------------------------------------------------------
def profiles_for(phones):
    """phone -> the best profile we hold for it, in one query.

    One number can sit on more than one profile (a returning guest who
    cleared cookies). Verified wins over unverified, newest wins otherwise.
    """
    phones = [p for p in set(phones) if p]
    if not phones:
        return {}
    rows = GuestProfile.objects.filter(phone__in=phones).order_by(
        "-phone_verified", "-created_at"
    )
    out = {}
    for profile in rows:
        out.setdefault(profile.phone, profile)
    return out


def _name(profile):
    if profile is None:
        return ""
    return profile.full_name


def recent_rows(qs, start, end, limit=25):
    """The last codes sent, newest first, with the guest behind each."""
    rows = list(
        qs.filter(created_at__gte=start, created_at__lt=end)
        .select_related("outlet", "brand")
        .order_by("-created_at")[:limit]
    )
    profiles = profiles_for(row.phone for row in rows)
    out = []
    for row in rows:
        profile = profiles.get(row.phone)
        if row.verified_at:
            status, tone = "Verified", "ok"
        elif row.delivered:
            status, tone = "Delivered", "sent"
        else:
            status, tone = "Not delivered", "fail"
        out.append(
            {
                "when": timezone.localtime(row.created_at),
                "phone": row.phone,
                "name": _name(profile),
                "branch": row.outlet.official_name if row.outlet_id else (
                    row.brand.name_en if row.brand_id else ""
                ),
                "status": status,
                "tone": tone,
                "error": row.delivery_error,
            }
        )
    return out


def guest_rows(qs, start, end, limit=100):
    """One row per number in the window: who, and how it went."""
    rows = list(
        qs.filter(created_at__gte=start, created_at__lt=end)
        .values("phone")
        .annotate(
            sent=Count("id"),
            delivered=Count("id", filter=Q(delivered=True)),
            verified=Count("id", filter=Q(verified_at__isnull=False)),
        )
    )
    phones = [row["phone"] for row in rows]
    profiles = profiles_for(phones)

    last_seen = {}
    for phone, created in qs.filter(
        created_at__gte=start, created_at__lt=end, phone__in=phones
    ).values_list("phone", "created_at"):
        if phone not in last_seen or created > last_seen[phone]:
            last_seen[phone] = created

    out = []
    for row in rows:
        profile = profiles.get(row["phone"])
        out.append(
            {
                "phone": row["phone"],
                "first_name": getattr(profile, "first_name", ""),
                "last_name": getattr(profile, "last_name", ""),
                "known": bool(profile and profile.full_name),
                "sent": row["sent"] or 0,
                "delivered": row["delivered"] or 0,
                "verified": row["verified"] or 0,
                "last_at": timezone.localtime(last_seen.get(row["phone"]) or timezone.now()),
            }
        )
    out.sort(key=lambda r: r["last_at"], reverse=True)
    return out[:limit]


def summary(qs):
    """Headline numbers for the top of the page."""
    all_rows = qs.aggregate(
        sent=Count("id"),
        delivered=Count("id", filter=Q(delivered=True)),
        verified=Count("id", filter=Q(verified_at__isnull=False)),
        numbers=Count("phone", distinct=True),
    )
    first = qs.order_by("created_at").values_list("created_at", flat=True).first()
    sent = all_rows["sent"] or 0
    delivered = all_rows["delivered"] or 0
    return {
        "sent": sent,
        "delivered": delivered,
        "failed": max(0, sent - delivered),
        "verified": all_rows["verified"] or 0,
        "numbers": all_rows["numbers"] or 0,
        "delivery_pct": _percent(delivered, sent),
        "verified_pct": _percent(all_rows["verified"] or 0, delivered),
        "since": timezone.localtime(first) if first else None,
    }
