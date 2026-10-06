"""Reserve points when a reward is picked. Confirm, cancel, or expire afterwards."""

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.kidsplay import conf
from apps.kidsplay.models import KidProfile, PointsLedger, Redemption, Reward
from apps.kidsplay.services import points


def create_redemption(kid: KidProfile, reward: Reward) -> tuple[Redemption | None, str]:
    if not reward.is_active:
        return None, "out_of_stock"
    if kid.redemptions.filter(status=Redemption.Status.PENDING).exists():
        return None, "pending_exists"
    if reward.stock == 0:
        return None, "out_of_stock"
    if kid.points_balance < reward.cost_points:
        return None, "insufficient_points"
    with transaction.atomic():
        locked = Reward.objects.select_for_update().get(pk=reward.pk)
        if locked.stock == 0:
            return None, "out_of_stock"
        code = f"{secrets.randbelow(1000000):06d}"
        redemption = Redemption.objects.create(
            kid=kid,
            reward=locked,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=conf.get("REDEMPTION_EXPIRY_MINUTES")),
        )
        try:
            points.award(kid, -locked.cost_points, PointsLedger.Reason.REDEMPTION, "Redemption", str(redemption.pk))
        except ValueError:
            redemption.delete()
            return None, "insufficient_points"
        if locked.stock is not None:
            locked.stock -= 1
            locked.save(update_fields=["stock"])
        return redemption, ""


def confirm(code: str, staff) -> tuple[bool, str]:
    with transaction.atomic():
        redemption = Redemption.objects.select_for_update().filter(code=code, status=Redemption.Status.PENDING).first()
        if redemption is None:
            return False, "not_found"
        if timezone.now() >= redemption.expires_at:
            return False, "expired"
        redemption.status = Redemption.Status.CONFIRMED
        redemption.confirmed_by = staff
        redemption.confirmed_at = timezone.now()
        redemption.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        return True, "confirmed"


def refund(redemption: Redemption, staff=None) -> None:
    """Give the reserved points back. Stock returns if it was limited."""
    points.award(
        redemption.kid,
        redemption.reward.cost_points,
        PointsLedger.Reason.REVERSAL,
        "Redemption",
        str(redemption.pk),
        created_by=staff,
    )
    reward = redemption.reward
    if reward.stock is not None:
        reward.stock += 1
        reward.save(update_fields=["stock"])


def cancel(code: str, staff) -> tuple[bool, str]:
    with transaction.atomic():
        redemption = Redemption.objects.select_for_update().select_related("reward", "kid").filter(
            code=code, status=Redemption.Status.PENDING
        ).first()
        if redemption is None:
            return False, "not_found"
        redemption.status = Redemption.Status.CANCELLED
        redemption.confirmed_by = staff
        redemption.confirmed_at = timezone.now()
        redemption.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        refund(redemption, staff)
        return True, "cancelled"


def expire_due() -> int:
    """Expire overdue pending redemptions and refund each one."""
    count = 0
    due = Redemption.objects.filter(status=Redemption.Status.PENDING, expires_at__lte=timezone.now())
    for redemption in due:
        with transaction.atomic():
            locked = Redemption.objects.select_for_update().select_related("reward", "kid").get(pk=redemption.pk)
            if locked.status != Redemption.Status.PENDING:
                continue
            locked.status = Redemption.Status.EXPIRED
            locked.save(update_fields=["status"])
            refund(locked)
            count += 1
    return count
