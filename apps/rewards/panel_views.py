"""
Panel surface for won rewards: the coupon list and the once-only redeem.

The workflow this supports is the one staff actually perform: a guest shows a
code on their phone, a member of staff types it in, and the coupon is honoured
once. Redeeming records who did it and when, so a second attempt cannot pay the
same code out again and the audit trail names the person responsible.

Scoping comes from apps.core.panel_permissions, the same helpers the rest of
the panel uses: Head Office sees every coupon, a brand manager sees their
brand, a branch manager sees their own branches.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.panel_permissions import (
    is_head_office,
    log_change,
    scoped_brands,
    scoped_outlets,
)
from apps.guests.models import GuestProfile
from apps.guests.phone import normalise_phone

from .models import RewardCoupon, RewardType


def scoped_coupons(user):
    """Coupons this user may see, newest first.

    A brand-wide win has no outlet, so the fallback matches it on brand. The
    two halves are OR'd rather than nested so the SQL stays a single query.
    """
    coupons = RewardCoupon.objects.select_related(
        "brand", "outlet", "profile", "redeemed_by"
    )
    if is_head_office(user):
        return coupons
    return coupons.filter(
        Q(outlet__in=scoped_outlets(user))
        | Q(outlet__isnull=True, brand__in=scoped_brands(user))
    )


def _retire_expired():
    """Lazily flip any issued coupon that has run out of time.

    Cheaper and more truthful than computing expiry in the template: the list
    and the CSV then agree, and a coupon cannot look redeemable on screen
    after its own expiry date. Scoped to ISSUED rows only, so a redeemed
    coupon is never rewritten.
    """
    return RewardCoupon.objects.filter(
        status=RewardCoupon.Status.ISSUED, expires_at__lte=timezone.now()
    ).update(status=RewardCoupon.Status.EXPIRED, updated_at=timezone.now())


def allowance_totals(coupons):
    """How much this scope has actually given away.

    Counts redeemed coupons only. An issued coupon is a promise, not a cost,
    and a voided one was never handed over. Desserts are a count. Discounts
    are a count plus the percentage points given (a 10% coupon adds 10).
    """
    redeemed = coupons.filter(status=RewardCoupon.Status.REDEEMED)
    desserts = redeemed.filter(reward_type=RewardType.DESSERT).count()
    discounts = redeemed.filter(reward_type=RewardType.PERCENT)
    return {
        "desserts_redeemed": desserts,
        "discounts_redeemed": discounts.count(),
        "discount_points": discounts.aggregate(total=Sum("percent"))["total"] or 0,
    }


def find_guest_by_mobile(raw):
    """The profiles that share the number staff typed, or none.

    Staff type whatever the guest says ("050 123 4567"). Storage is E.164, so
    the lookup normalises first and only then matches. A number that cannot
    be a phone returns no profiles rather than a loose text search, which
    would otherwise match a fragment of someone else's number.
    """
    phone = normalise_phone(raw)
    if not phone:
        return GuestProfile.objects.none(), ""
    return GuestProfile.objects.filter(phone=phone), phone


@login_required
@require_GET
def panel_rewards(request):
    """Coupon list, with the "type the code the guest showed you" filter."""
    _retire_expired()

    coupons = scoped_coupons(request.user)

    status = (request.GET.get("status") or RewardCoupon.Status.ISSUED).strip()
    valid_statuses = {choice.value for choice in RewardCoupon.Status}
    if status != "all" and status in valid_statuses:
        coupons = coupons.filter(status=status)
    else:
        status = "all"

    code = (request.GET.get("code") or "").strip().upper()
    if code:
        coupons = coupons.filter(code__icontains=code)

    # Mobile lookup is the till workflow: the guest gives their number, staff
    # type it, and only that guest's coupons in THIS scope come back. A branch
    # manager therefore cannot see, or redeem, a win from another branch.
    mobile = (request.GET.get("mobile") or "").strip()
    looked_up = None
    mobile_normalised = ""
    if mobile:
        profiles, mobile_normalised = find_guest_by_mobile(mobile)
        profile_ids = list(profiles.values_list("pk", flat=True))
        coupons = coupons.filter(profile_id__in=profile_ids)
        # Name the guest only when this scope actually holds one of their
        # coupons. Otherwise a branch manager who types a number learns that
        # a guest exists at another brand, which is the leak this page must
        # not have.
        if coupons.exists():
            looked_up = profiles.order_by("-updated_at").first()

    visible = scoped_coupons(request.user)
    context = {
        "title": "Rewards",
        "nav_active": "rewards",
        "coupons": coupons.order_by("-issued_at")[:200],
        "statuses": RewardCoupon.Status.choices,
        "active_status": status,
        "code_query": code,
        "mobile_query": mobile,
        "mobile_normalised": mobile_normalised,
        "looked_up": looked_up,
        "issued_count": visible.filter(status=RewardCoupon.Status.ISSUED).count(),
        "redeemed_count": visible.filter(status=RewardCoupon.Status.REDEEMED).count(),
        "expired_count": visible.filter(status=RewardCoupon.Status.EXPIRED).count(),
    }
    context.update(allowance_totals(visible))
    return render(request, "panel/rewards_list.html", context)


@login_required
@require_POST
def panel_coupon_redeem(request, pk):
    """Hand the reward over, once. A second attempt is refused, not overridden."""
    coupon = get_object_or_404(scoped_coupons(request.user), pk=pk)

    if not coupon.is_usable:
        # Say which state blocked it, so staff can tell "already used" from
        # "expired" without reading the table.
        coupon.mark_expired()
        coupon.refresh_from_db()
        messages.error(
            request,
            f"{coupon.code} cannot be redeemed: it is "
            f"{coupon.get_status_display().lower()}.",
        )
        return redirect("panel_rewards")

    coupon.status = RewardCoupon.Status.REDEEMED
    coupon.redeemed_at = timezone.now()
    coupon.redeemed_by = request.user
    coupon.save(
        update_fields=["status", "redeemed_at", "redeemed_by", "updated_at"]
    )

    log_change(
        request.user,
        "reward_redeem",
        coupon,
        brand=coupon.brand,
        outlet=coupon.outlet,
        details={"code": coupon.code, "reward": coupon.label},
    )
    messages.success(request, f"{coupon.code} redeemed. Hand over {coupon.label}.")
    return redirect("panel_rewards")
