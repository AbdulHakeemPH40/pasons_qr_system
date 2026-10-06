"""Issue a one-time play token and accept a finished score. Points are decided here."""

import secrets

from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import transaction
from django.utils import timezone

from apps.kidsplay import conf
from apps.kidsplay.models import Family, GameSession, KidProfile, PlayGame, PointsLedger, TableVisit
from apps.kidsplay.services import points, visits

SIGNER_SALT = "kidsplay.game"


def _signer() -> signing.TimestampSigner:
    return signing.TimestampSigner(salt=SIGNER_SALT)


def start_game(family: Family, kid: KidProfile, slug: str) -> tuple[dict | None, str]:
    """Open a session. Returns (payload, error)."""
    if family.is_blocked:
        return None, "blocked"
    visit = visits.active_visit(family)
    if visit is None:
        return None, "no_active_visit"
    game = PlayGame.objects.filter(slug=slug, is_active=True).first()
    if game is None:
        return None, "game_unavailable"
    window = timezone.now() - timezone.timedelta(seconds=60)
    recent = GameSession.objects.filter(kid=kid, started_at__gte=window).count()
    if recent >= conf.get("MAX_GAMES_PER_MINUTE"):
        return None, "rate_limited"
    nonce = secrets.token_hex(8)
    session = GameSession.objects.create(
        kid=kid, visit=visit, game=game, token_nonce=nonce
    )
    token = _signer().sign(f"{session.pk}:{nonce}")
    return {
        "token": token,
        "session_id": str(session.pk),
        "config": {"round_seconds": 60},
    }, ""


def _reject(session: GameSession, reason: str, score: int, duration_ms: int) -> dict:
    session.status = GameSession.Status.REJECTED
    session.reject_reason = reason
    session.reported_score = score
    session.reported_duration_ms = duration_ms
    session.finished_at = timezone.now()
    session.points_awarded = 0
    session.save()
    return {
        "score": score,
        "points_awarded": 0,
        "cap_reached": False,
        "balance": session.kid.points_balance,
    }


def finish_game(kid: KidProfile, token: str, score, duration_ms) -> dict:
    """Validate a finish. A failed check still returns 200-shaped data with 0 points."""
    try:
        raw = _signer().unsign(token, max_age=conf.get("GAME_TOKEN_MAX_AGE_SECONDS"))
        session_id, nonce = raw.split(":", 1)
    except (BadSignature, SignatureExpired, ValueError):
        return {"score": 0, "points_awarded": 0, "cap_reached": False, "balance": kid.points_balance}

    try:
        score = int(score)
        duration_ms = int(duration_ms)
    except (TypeError, ValueError):
        score, duration_ms = -1, 0

    with transaction.atomic():
        session = (
            GameSession.objects.select_for_update()
            .select_related("game", "visit", "kid")
            .filter(pk=session_id, token_nonce=nonce)
            .first()
        )
        if session is None or session.kid_id != kid.pk or session.status != GameSession.Status.STARTED:
            return {"score": max(score, 0), "points_awarded": 0, "cap_reached": False, "balance": kid.points_balance}

        game = session.game
        if score < 0 or score > game.max_score:
            return _reject(session, "score", score, duration_ms)
        if duration_ms < game.min_duration_ms or duration_ms > game.max_duration_ms:
            return _reject(session, "duration", score, duration_ms)
        elapsed_ms = (timezone.now() - session.started_at).total_seconds() * 1000
        if elapsed_ms < duration_ms - 3000:
            return _reject(session, "elapsed", score, duration_ms)
        seconds = max(duration_ms / 1000, 0.001)
        if score / seconds > game.max_score_per_second:
            return _reject(session, "rate", score, duration_ms)
        visit = TableVisit.objects.select_for_update().get(pk=session.visit_id)
        if not visit.is_active():
            return _reject(session, "visit", score, duration_ms)

        tier = game.tiers.filter(min_score__lte=score).order_by("-min_score").first()
        raw_points = tier.points if tier else 0
        awarded, capped = points.capped_award(session, raw_points)
        session.status = GameSession.Status.FINISHED
        session.reported_score = score
        session.reported_duration_ms = duration_ms
        session.finished_at = timezone.now()
        session.points_awarded = awarded
        session.save()
        if awarded:
            points.award(session.kid, awarded, PointsLedger.Reason.GAME, "GameSession", str(session.pk))
        return {
            "score": score,
            "points_awarded": awarded,
            "cap_reached": capped,
            "balance": session.kid.points_balance,
        }
