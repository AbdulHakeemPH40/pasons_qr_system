"""
Panel surface for collected guest contacts.

The client runs campaigns on a separate platform, so this page is a read and
export view: who told us who they are, whether they agreed to be marketed to,
and a CSV file the campaign team can import.

Every value is labelled at its true strength, because the difference matters
when someone acts on it:

  * mobile   -- proved with a WhatsApp one time code before it is stored as
                verified (`GuestProfile.phone_verified`). The page reports
                codes sent, delivered and verified separately, because those
                three numbers answer three different questions.
  * email    -- only "verified" when a Google sign-in proved it
  * Instagram follow -- SELF-DECLARED; Meta exposes no follow check, so this
    is the guest's word, and the panel says so

Scoping uses the same helpers as the rest of the panel: Head Office sees every
contact, a brand or branch manager sees only their own.
"""

import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.panel_permissions import (
    brand_for_manager,
    is_brand_manager,
    is_head_office,
    scoped_brands,
    scoped_outlets,
)

from . import reporting
from .models import GuestProfile

# The hand-off to the campaign platform, one column per field, written once
# here so the header row and the data rows cannot drift apart.
EXPORT_COLUMNS = (
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("phone", "Mobile"),
    ("email", "Email"),
    ("email_verified", "Email verified"),
    ("ig_follow_claimed", "Instagram follow claimed"),
    ("consent_marketing", "Marketing consent"),
    ("brand", "First brand"),
    ("outlet", "First branch"),
    ("coupons", "Coupons won"),
    ("created_at", "First seen"),
    ("updated_at", "Last seen"),
)


def scoped_guests(user):
    """Guest profiles this user may see, with their first visit resolved.

    A guest who arrived before any outlet was chosen has no first_outlet, so
    the fallback matches them on their first brand.
    """
    profiles = GuestProfile.objects.select_related("first_brand", "first_outlet")
    if is_head_office(user):
        return profiles
    return profiles.filter(
        Q(first_outlet__in=scoped_outlets(user))
        | Q(first_outlet__isnull=True, first_brand__in=scoped_brands(user))
    )


@login_required
@require_GET
def panel_guests(request):
    """Contacts collected from the guest QR pages."""
    profiles = scoped_guests(request.user)

    # Anonymous device rows (no name, no email, no number) are not contacts.
    # They stay in the database and are hidden here by default, because a page
    # of empty rows helps nobody.
    identified = (request.GET.get("identified") or "1") == "1"
    if identified:
        profiles = profiles.exclude(
            first_name="", last_name="", email="", phone=""
        )

    if (request.GET.get("consented") or "") == "1":
        profiles = profiles.filter(consent_marketing=True)

    search = (request.GET.get("q") or "").strip()
    if search:
        profiles = profiles.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    profiles = profiles.annotate(coupon_count=Count("coupons", distinct=True))

    context = {
        "title": "Guest Contacts",
        "nav_active": "guests",
        "profiles": profiles.order_by("-updated_at")[:300],
        "identified": identified,
        "consented": (request.GET.get("consented") or "") == "1",
        "search": search,
        "identified_count": _identified(scoped_guests(request.user)).count(),
        "consented_count": _identified(scoped_guests(request.user))
        .filter(consent_marketing=True)
        .count(),
        "with_mobile_count": _identified(scoped_guests(request.user))
        .exclude(phone="")
        .count(),
    }
    return render(request, "panel/guests_list.html", context)


def _identified(profiles):
    """Only rows we can act on: a name, an email or a mobile number."""
    return profiles.exclude(first_name="", last_name="", email="", phone="")


@login_required
@require_GET
def panel_guests_export(request):
    """CSV of messageable guests, one row per mobile number.

    This is the campaign hand-off, so it is deliberately strict about what
    makes a usable row:

      * only guests with a mobile number are exported, since that is what the
        campaign platform messages;
      * the number is the dedupe key and the newest profile wins, because the
        same person can legitimately appear twice after clearing cookies;
      * marketing consent travels as a column, and ``?consented=1`` narrows
        the file to consented guests only. The consent column is present in
        both cases so the campaign team never has to guess who agreed.
    """
    consented_only = (request.GET.get("consented") or "") == "1"

    profiles = (
        scoped_guests(request.user)
        .exclude(phone="")
        .annotate(coupon_count=Count("coupons", distinct=True))
        .order_by("-updated_at")
    )
    if consented_only:
        profiles = profiles.filter(consent_marketing=True)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    stamp = timezone.localdate().isoformat()
    suffix = "-consented" if consented_only else ""
    response["Content-Disposition"] = (
        f'attachment; filename="pasons-guests{suffix}-{stamp}.csv"'
    )
    # A BOM so Excel opens the Arabic names in the file correctly.
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow([label for _key, label in EXPORT_COLUMNS])

    seen_numbers = set()
    for profile in profiles.iterator():
        number = (profile.phone or "").strip()
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        writer.writerow(
            [_cell(profile, key) for key, _label in EXPORT_COLUMNS]
        )
    return response


def _cell(profile, key):
    """One CSV value, rendered plainly so a spreadsheet reads it back."""
    if key in ("created_at", "updated_at"):
        moment = timezone.localtime(getattr(profile, key))
        return moment.strftime("%Y-%m-%d %H:%M")
    if key == "brand":
        return profile.first_brand.name_en if profile.first_brand else ""
    if key == "outlet":
        return profile.first_outlet.official_name if profile.first_outlet else ""
    if key == "coupons":
        return profile.coupon_count
    if key in ("email_verified", "ig_follow_claimed", "consent_marketing"):
        return "yes" if getattr(profile, key) else "no"
    return getattr(profile, key) or ""


# --------------------------------------------------------------------------
# WhatsApp verification report
# --------------------------------------------------------------------------
@login_required
@require_GET
def panel_otp(request):
    """Codes sent, delivered and verified, per window and per branch.

    The client asked for six windows at once (today, yesterday, 7 days,
    30 days, this month, last month) plus the branch breakdown and the guest
    behind each number. The arithmetic lives in ``reporting``; this view only
    scopes it to the person reading and passes the labels through.

    No money figure is printed. The partner chose counts only, and a guessed
    rate would be worse than no rate: the panel would show a cost the invoice
    does not match.
    """
    user = request.user
    codes = reporting.scoped_codes(user)

    branch_id = (request.GET.get("branch") or "").strip()
    codes = reporting.filter_by_branch(codes, user, branch_id)

    search = (request.GET.get("q") or "").strip()
    codes = reporting.filter_by_search(codes, search)

    windows = reporting.period_rows(codes)
    by_key = {row["key"]: row for row in windows}

    # Detail sections share one window so the numbers below the fold agree
    # with the row a manager just read. 30 days is the useful working span.
    detail = by_key["month30"]
    start, end = detail["start"], detail["end"]

    scope_outlets = reporting.branch_choices(user)
    scope_brands = reporting.brand_choices(user)
    if is_head_office(user):
        scope_label = "All branches"
    elif is_brand_manager(user) and brand_for_manager(user) is None:
        # The all-brands manager holds no single brand, so their scope is the
        # whole group even though they are not head office.
        scope_label = "All branches"
    elif scope_brands.count() == 1:
        scope_label = scope_brands.first().name_en
    else:
        scope_label = "Your branches"

    context = {
        "title": "WhatsApp Verification",
        "nav_active": "otp",
        "summary": reporting.summary(codes),
        "windows": windows,
        "detail": detail,
        "trend": reporting.monthly_trend(codes),
        "branches": reporting.by_branch(codes, start, end),
        "countries": reporting.by_country(codes, start, end),
        "recent": reporting.recent_rows(codes, start, end, limit=25),
        "guests": reporting.guest_rows(codes, start, end, limit=100),
        "branch_options": scope_outlets,
        "branch_id": branch_id,
        "search": search,
        "scope_label": scope_label,
        "brand_count": scope_brands.count(),
        "outlet_count": scope_outlets.count(),
        "generated_at": timezone.localtime(),
    }
    return render(request, "panel/otp_report.html", context)
