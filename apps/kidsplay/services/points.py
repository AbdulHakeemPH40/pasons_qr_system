"""Append-only points. Balance is the sum of the ledger, cached on the kid."""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.kidsplay import conf
from apps.kidsplay.models import GameSession, KidProfile, PointsLedger, TableVisit


def balance(kid: KidProfile) -> int:
    total = kid.ledger.aggregate(total=Sum("delta"))["total"] or 0
    return int(total)


def _today_earned(kid: KidProfile) -> int:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    total = kid.ledger.filter(created_at__gte=start, delta__gt=0).aggregate(total=Sum("delta"))["total"] or 0
    return int(total)


def _visit_earned(visit: TableVisit) -> int:
    session_ids = [str(pk) for pk in visit.sessions.values_list("pk", flat=True)]
    total = PointsLedger.objects.filter(
        reason=PointsLedger.Reason.GAME, ref_id__in=session_ids, delta__gt=0
    ).aggregate(total=Sum("delta"))["total"] or 0
    bonus = PointsLedger.objects.filter(
        reason=PointsLedger.Reason.BILL_BONUS, ref_id=str(visit.pk), delta__gt=0
    ).aggregate(total=Sum("delta"))["total"] or 0
    return int(total) + int(bonus)


def _game_visit_earned(visit: TableVisit, game_id: int) -> int:
    session_ids = [
        str(pk) for pk in visit.sessions.filter(game_id=game_id).values_list("pk", flat=True)
    ]
    total = PointsLedger.objects.filter(
        reason=PointsLedger.Reason.GAME, ref_id__in=session_ids, delta__gt=0
    ).aggregate(total=Sum("delta"))["total"] or 0
    return int(total)


def award(
    kid: KidProfile,
    delta: int,
    reason: str,
    ref_type: str,
    ref_id: str,
    created_by=None,
) -> int:
    """Write one ledger row and refresh the cached balance. Returns the new balance."""
    if delta == 0:
        return balance(kid)
    with transaction.atomic():
        locked = KidProfile.objects.select_for_update().get(pk=kid.pk)
        current = balance(locked)
        if delta < 0 and current + delta < 0:
            raise ValueError("negative_balance")
        PointsLedger.objects.create(
            kid=locked,
            delta=delta,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            created_by=created_by,
        )
        locked.points_balance = current + delta
        locked.save(update_fields=["points_balance"])
        kid.points_balance = locked.points_balance
        return locked.points_balance


def capped_award(session: GameSession, raw_points: int) -> tuple[int, bool]:
    """Apply per-game, per-visit, then per-day caps. Returns (awarded, cap_hit)."""
    if raw_points <= 0:
        return 0, False
    game_left = conf.get("MAX_POINTS_PER_GAME_PER_VISIT") - _game_visit_earned(session.visit, session.game_id)
    visit_left = conf.get("MAX_POINTS_PER_VISIT") - _visit_earned(session.visit)
    day_left = conf.get("MAX_POINTS_PER_DAY") - _today_earned(session.kid)
    awarded = max(0, min(raw_points, game_left, visit_left, day_left))
    return awarded, awarded < raw_points
