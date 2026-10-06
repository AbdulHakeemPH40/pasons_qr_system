"""
Read-time aggregation helpers for the management dashboard
(spec sections 24, 25 and 50).

Raw ScanEvent rows are never mutated — every KPI is computed at read
time from the event log (plan decision 3). All helpers accept an
optional queryset so the dashboard can scope every number to one brand
(spec section 25 "Brand view").
"""

from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone

from apps.core.models import Brand, Campaign, Outlet, QrCode
from apps.engagement.models import Feedback, Lead

from .models import ScanEvent


def _base(qs):
    return ScanEvent.objects.all() if qs is None else qs


def scans_by_day(days=14, qs=None):
    """
    Zero-filled daily scan counts for the last `days` days (spec 25).

    Returns oldest-first rows: {"date", "label", "count", "pct"} where
    pct is the bar height relative to the busiest day (min 6% when > 0
    so a single scan is still visible on the chart).
    """
    qs = _base(qs)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        qs.filter(scanned_at__date__gte=start)
        .values("scanned_at__date")
        .annotate(n=Count("id"))
    )
    lookup = {r["scanned_at__date"]: r["n"] for r in rows}
    peak = max(lookup.values(), default=0)
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        count = lookup.get(day, 0)
        if peak and count:
            pct = max(6, round(100 * count / peak))
        else:
            pct = 0
        out.append(
            {
                "date": day,
                "label": day.strftime("%a")[0],  # M T W T F S S
                "full_label": day.strftime("%a %d %b"),
                "count": count,
                "pct": pct,
            }
        )
    return out


def scans_by_outlet(qs=None):
    """
    Scans grouped by outlet, brand-level scans (outlet = NULL) labelled
    as the brand's own page (spec 6/25: outlets optional).
    """
    rows = (
        _base(qs)
        .values("outlet_id", "outlet__official_name", "brand__name_en")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    out = []
    for r in rows:
        label = r["outlet__official_name"] or f"{r['brand__name_en']} — brand page"
        out.append({"label": label, "count": r["n"], "outlet_id": r["outlet_id"]})
    return _with_pct(out)


def _with_pct(rows):
    """Attach a 0-100 pct (relative to the busiest row) for bar widths."""
    peak = max((r["count"] for r in rows), default=0)
    for r in rows:
        r["pct"] = round(100 * r["count"] / peak) if peak else 0
    return rows


SOURCE_LABELS = dict(QrCode.SourceType.choices)


def scans_by_source(qs=None):
    """Scans grouped by QR source type — entrance, table, flyer... (spec 22/24)."""
    rows = (
        _base(qs)
        .values("qr_code__source_type")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return _with_pct(
        [
            {
                "label": SOURCE_LABELS.get(r["qr_code__source_type"], "Unknown"),
                "count": r["n"],
            }
            for r in rows
        ]
    )


def top_placements(limit=8, qs=None):
    """
    Top-performing QR placements (spec 25/50): the printed codes that
    drive the most scans, with their physical location.
    """
    rows = (
        _base(qs)
        .values(
            "qr_code__qr_code_name",
            "qr_code__source_location",
            "qr_code__source_type",
            "qr_code__active",
        )
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "name": r["qr_code__qr_code_name"],
            "location": r["qr_code__source_location"],
            "source": SOURCE_LABELS.get(r["qr_code__source_type"], "—"),
            "active": r["qr_code__active"],
            "count": r["n"],
        }
        for r in rows
    ]


def group_summary(qs=None, brand=None):
    """
    KPI tile data (spec 25 Group Summary / spec 50 Adoption +
    Conversion): scans today, 30-day scans, active campaigns,
    enquiries, feedback, and the top performer.
    """
    now = timezone.now()
    today = timezone.localdate()
    qs = _base(qs)

    campaigns = Campaign.objects.filter(
        status__in=[Campaign.Status.SCHEDULED, Campaign.Status.LIVE],
        start_at__lte=now,
        end_at__gte=now,
    )
    leads = Lead.objects.all()
    feedback = Feedback.objects.all()
    if brand is not None:
        campaigns = campaigns.filter(brand=brand)
        leads = leads.filter(brand=brand)
        feedback = feedback.filter(brand=brand)

    open_leads = leads.exclude(status="closed").count()

    feedback_count = feedback.count()
    feedback_avg = None
    if feedback_count:
        feedback_avg = feedback.aggregate(avg=Avg("rating"))["avg"]

    month_ago = today - timedelta(days=30)
    monthly = qs.filter(scanned_at__date__gte=month_ago).count()

    # top performer: brand at group scope, outlet inside a brand scope
    if brand is None:
        top = (
            qs.filter(scanned_at__date__gte=month_ago)
            .values("brand__name_en")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        top_label = top["brand__name_en"] if top else "—"
        top_note = "by scans, 30 days"
    else:
        top = (
            qs.filter(scanned_at__date__gte=month_ago, outlet__isnull=False)
            .values("outlet__official_name")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        top_label = top["outlet__official_name"] if top else "No outlet scans"
        top_note = "by scans, 30 days"

    return [
        {
            "key": "scans_today",
            "label": "Scans today",
            "value": qs.filter(scanned_at__date=today).count(),
            "note": "midnight to now",
        },
        {
            "key": "scans_month",
            "label": "Scans, 30 days",
            "value": monthly,
            "note": "all placements",
        },
        {
            "key": "campaigns",
            "label": "Active campaigns",
            "value": campaigns.count(),
            "note": "inside their window",
        },
        {
            "key": "enquiries",
            "label": "Enquiries",
            "value": leads.count(),
            "note": f"{open_leads} open" if open_leads else "all handled",
        },
        {
            "key": "feedback",
            "label": "Feedback",
            "value": feedback_count,
            "note": (
                f"avg {feedback_avg:.1f} / 5" if feedback_avg else "no ratings yet"
            ),
        },
        {
            "key": "top",
            "label": "Top outlet" if brand is not None else "Top performing brand",
            "value": top_label,
            "text": True,
            "note": top_note,
        },
    ]


def adoption(brand=None):
    """Spec 50 Adoption strip: active brands / outlets / QR sources."""
    brands = Brand.objects.filter(status="active")
    outlets = Outlet.objects.filter(active=True)
    qrs = QrCode.objects.filter(active=True)
    if brand is not None:
        brands = brands.filter(pk=brand.pk)
        outlets = outlets.filter(brand=brand)
        qrs = qrs.filter(brand=brand)
    return [
        {"label": "Active brands", "count": brands.count()},
        {"label": "Active outlets", "count": outlets.count()},
        {"label": "Active QR sources", "count": qrs.count()},
    ]
