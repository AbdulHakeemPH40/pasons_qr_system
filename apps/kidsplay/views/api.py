"""JSON game endpoints. The client sends a score, never a point value."""

import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from apps.kidsplay.models import Family, KidProfile
from apps.kidsplay.services import games, visits


def _error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code, "message": message}, status=status)


def _session_kid(request) -> tuple[Family | None, KidProfile | None]:
    family_id = request.session.get("kidsplay_family")
    kid_id = request.session.get("kidsplay_kid")
    family = Family.objects.filter(pk=family_id, is_blocked=False).first() if family_id else None
    kid = family.kids.filter(pk=kid_id).first() if family and kid_id else None
    return family, kid


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


@require_POST
def game_start(request):
    family, kid = _session_kid(request)
    if family is None or kid is None:
        return _error("no_session", "Scan the table QR and pick a player.", 403)
    payload, error = games.start_game(family, kid, _body(request).get("game", ""))
    if error == "no_active_visit":
        return _error(error, "Scan your table QR to play.", 403)
    if error == "game_unavailable":
        return _error(error, "That game is not available.", 404)
    if error == "rate_limited":
        return _error(error, "Slow down a moment.", 429)
    if error:
        return _error(error, "Can't start that game.", 403)
    return JsonResponse(payload)


@require_POST
def game_finish(request):
    family, kid = _session_kid(request)
    if family is None or kid is None:
        return _error("no_session", "Scan the table QR and pick a player.", 403)
    body = _body(request)
    result = games.finish_game(kid, body.get("token", ""), body.get("score"), body.get("duration_ms"))
    return JsonResponse(result)


@require_GET
def me(request):
    family, kid = _session_kid(request)
    if family is None or kid is None:
        return _error("no_session", "Scan the table QR and pick a player.", 403)
    visit = visits.active_visit(family)
    return JsonResponse({
        "nickname": kid.nickname,
        "avatar": kid.avatar,
        "balance": kid.points_balance,
        "visit_expires_at": visit.expires_at.isoformat() if visit else None,
    })
