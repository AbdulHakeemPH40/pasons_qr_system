"""
Management dashboard (spec section 25) — the internal desktop surface
for Pasons teams. Staff-only: any staff/superuser session works, and
anonymous visitors are bounced to the admin login.

Group summary KPIs (scans today, active campaigns, enquiries, feedback,
top performer), scans by day / outlet / source, and top QR placements —
all aggregated read-time from raw ScanEvent rows (spec 24/50).
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.models import Brand, Campaign
from apps.core.panel_permissions import scoped_brands

from . import aggregates
from .models import ScanEvent


@require_GET
@login_required
def dashboard(request):
    """Internal KPI dashboard (spec 25). ?brand=<code> scopes to brand view.

    The panel middleware already checks the analytics capability, so a brand
    or branch login reaches this page the same way it reaches the rest of
    the panel. Numbers stay inside that person's brands.
    """
    allowed = scoped_brands(request.user)
    brand = None
    brand_code = request.GET.get("brand", "")
    if brand_code:
        brand = allowed.filter(code__iexact=brand_code).first()

    events = None
    if brand is not None:
        events = ScanEvent.objects.filter(brand=brand)

    context = {
        "title": "Management Dashboard",
        "nav_active": "analytics",
        "brand": brand,
        "brands": allowed.filter(status="active").order_by("name_en"),
        "kpis": aggregates.group_summary(qs=events, brand=brand),
        "by_day": aggregates.scans_by_day(qs=events),
        "by_outlet": aggregates.scans_by_outlet(qs=events),
        "by_source": aggregates.scans_by_source(qs=events),
        "placements": aggregates.top_placements(qs=events),
        "adoption": aggregates.adoption(brand=brand),
        "pending_campaigns": _pending_campaigns(brand),
        "generated_at": timezone.localtime(),
    }
    return render(request, "panel/analytics.html", context)


def _pending_campaigns(brand):
    """Campaigns awaiting approval (spec 28 states / 29 workflow)."""
    qs = Campaign.objects.filter(
        status=Campaign.Status.PENDING
    ).select_related("brand")
    if brand is not None:
        qs = qs.filter(brand=brand)
    return qs.order_by("start_at")[:5]
