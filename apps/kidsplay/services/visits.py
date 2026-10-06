"""Open and close a table visit. Points are allowed only while one is active."""

from datetime import timedelta

from django.utils import timezone

from apps.core.models import QrCode
from apps.kidsplay import conf
from apps.kidsplay.models import Family, TableVisit


def find_table(code: str) -> QrCode | None:
    """A playable table is an active printed QR."""
    return QrCode.objects.filter(redirect_key=code, active=True).select_related("outlet", "brand").first()


def open_visit(family: Family, qr: QrCode) -> TableVisit:
    """Start a visit and close any other open visit for this family."""
    now = timezone.now()
    TableVisit.objects.filter(family=family, closed_at__isnull=True).update(closed_at=now)
    return TableVisit.objects.create(
        family=family,
        qr_code=qr,
        outlet=qr.outlet,
        started_at=now,
        expires_at=now + timedelta(minutes=conf.get("VISIT_DURATION_MINUTES")),
    )


def active_visit(family: Family) -> TableVisit | None:
    visit = (
        TableVisit.objects.filter(family=family, closed_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    if visit is None or not visit.is_active():
        return None
    return visit


def close_visit(visit: TableVisit) -> None:
    if visit.closed_at is None:
        visit.closed_at = timezone.now()
        visit.save(update_fields=["closed_at"])
