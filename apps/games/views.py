"""
Games Zone views (GAMES_ZONE_PLAN.md sections 4 and 6).

Three public surfaces:
  /q/<key>/game/   entry from printed QR and the landing card; logs the tap
                   and hands over to the hub (URL name kept for old sheets)
  /games/          hub listing the enabled games in the outlet's brand colours
  /games/<slug>/   full-screen play page with Exit back to the QR page

The games pages themselves carry no offer copy and no personal data, and the
only record of a plain round is the TapEvent / GameEvent analytics row.

A FINISHED round can win a real reward (see apps/rewards), but only through
visible hard work. The play page embeds a short-lived round token, the shell
posts it with the final score plus how the round was played, and
`games_event` decides whether a coupon is issued. Playing is never gated: a
guest without login plays any game at any level with no restriction. Being
VERIFIED (name and mobile, or Google) is only ever the gate on being PAID.

Scores, durations and action counts all arrive from the browser, so the
per-guest cooldown keyed on the mobile number and the per-brand monthly cap
are the real limits, never the score itself.
"""

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.analytics.models import TapEvent
from apps.core.models import Brand, Outlet, QrCode
from apps.guests.context import sheet_context
from apps.guests.identity import ensure_profile
from apps.rewards.services import (
    REASON_TEXT,
    Reason,
    evaluate_round,
    progress_payload,
    sign_round_token,
    verify_round_token,
)

from .models import GameEvent
from .registry import enabled_games, get_game

# The `back` parameter is guest-supplied and rendered into links, so it is
# allow-listed to our own QR and smart-page paths. Anything else (absolute
# URLs, protocol-relative URLs, other paths) falls back to the home page.
_BACK_PREFIXES = ("/q/", "/p/")
_DEFAULT_BACK = "/"

# Fallback palette when a brand has no colours configured; mirrors the
# :root defaults in base.html so the canvas matches the page chrome.
_DEFAULT_COLORS = {
    "primary": "#7FA06B",
    "secondary": "#5E7F52",
    "accent": "#D9A83C",
    "dark": "#1F3726",
}


def safe_back(value):
    """Return value only when it is a same-site /q/ or /p/ path."""
    if not value:
        return _DEFAULT_BACK
    value = value[:200]
    if value == "/":
        return value
    if not value.startswith("/") or value.startswith("//"):
        return _DEFAULT_BACK
    if not value.startswith(_BACK_PREFIXES):
        return _DEFAULT_BACK
    return value


def _qr_from_back(back):
    """The QR a game page was opened from, or None.

    The play page needs the ROW, not just its key: the guest identity sheet
    posts to that QR (so a new profile records where it was born) and comes
    back to the game afterwards. Resolved once per request, so the theming
    and the sheet share the same lookup.
    """
    if not back.startswith("/q/"):
        return None
    key = back[3:].strip("/")
    if not key:
        return None
    return (
        QrCode.objects.select_related("brand", "outlet")
        .filter(redirect_key=key)
        .first()
    )


def _brand_context(back, qr=None):
    """Resolve (brand, outlet) from the sanitised back path for theming."""
    if back.startswith("/q/"):
        if qr is None:
            qr = _qr_from_back(back)
        if qr:
            return qr.brand, qr.outlet
    elif back.startswith("/p/"):
        slug = back[3:].strip("/")
        outlet = Outlet.objects.select_related("brand").filter(slug=slug).first()
        if outlet:
            return outlet.brand, outlet
        brand = Brand.objects.filter(slug=slug).first()
        if brand:
            return brand, None
    return None, None


def _theme_payload(brand):
    colors = getattr(brand, "brand_colors", None) or {}
    return {key: colors.get(key) or fallback for key, fallback in _DEFAULT_COLORS.items()}


def qr_game(request, key):
    """
    Entry point for printed QR sheets and the landing card. Keeps the old
    URL name alive (plan section 2: this URL must never 404 for a live code),
    logs the Play Game tap, then opens the hub for that outlet.
    """
    qr = (
        QrCode.objects.select_related("outlet", "brand")
        .filter(redirect_key=key)
        .first()
    )
    if qr is None:
        return render(request, "404.html", status=404)
    if not qr.active or (qr.outlet and not qr.outlet.active) or qr.brand.status != "active":
        return render(request, "410.html", status=410)

    TapEvent.objects.create(
        outlet=qr.outlet,
        brand=qr.brand,
        qr_code=qr,
        action=TapEvent.ActionType.GAME,
        session_key=request.session.session_key or "",
    )
    return redirect(f"{reverse('games_hub')}?back=/q/{key}/")


def _place_name(brand, outlet):
    """One safe display name for captions/titles (brand or outlet may be None)."""
    if outlet is not None:
        return outlet.official_name or (brand.name_en if brand else "Pasons Group")
    if brand is not None:
        return brand.name_en
    return "Pasons Group"


def games_hub(request):
    back = safe_back(request.GET.get("back", ""))
    brand, outlet = _brand_context(back)
    return render(
        request,
        "games/hub.html",
        {
            "games": enabled_games(),
            "back": back,
            "brand": brand,
            "outlet": outlet,
            "place_name": _place_name(brand, outlet),
        },
    )


def games_play(request, slug):
    game = get_game(slug)
    if game is None or not game.enabled:
        return render(request, "404.html", status=404)
    back = safe_back(request.GET.get("back", ""))
    qr = _qr_from_back(back)
    brand, outlet = _brand_context(back, qr)
    qr_key = qr.redirect_key if qr is not None else ""

    # The play page needs to know where this guest stands before the game
    # starts: the chess ladder locks the levels above their rung, and an
    # unverified guest sees the sign-in prompt. One indexed lookup, only on
    # this page; the menu and specials never touch identity.
    profile = getattr(request, "guest", None)
    profile = profile.profile if profile is not None else None
    progress = progress_payload(profile, game.slug)

    context = {
        "game": game,
        "back": back,
        "brand": brand,
        "outlet": outlet,
        "qr_key": qr_key,
        "theme_payload": _theme_payload(brand),
        "bridge_payload": game.bridge,
        # Claimed once when the round ends. See apps/rewards/services.py.
        "round_token": sign_round_token(game.slug),
        "place_name": _place_name(brand, outlet),
        # Ladder / streak state and whether this guest can be paid.
        "game_progress": progress,
        "guest_verified": progress.get("verified", False),
    }

    # The identity sheet, so "Sign in to earn" opens the form HERE instead
    # of walking the guest back to the QR landing page and losing the game.
    # `next_path` is this exact page, so a submit returns the guest to the
    # game with the confirmation panel open. Without a QR there is nothing
    # to hang the form on, so the sheet is left out and the prompt hides.
    if qr is not None:
        context.update(
            sheet_context(
                request,
                qr,
                next_path=request.get_full_path()[:200],
                # Straight to the name + mobile form: this guest tapped "Sign
                # in to earn" during a game, so the Instagram follow story is
                # the wrong story here. mode="game" swaps that copy only.
                base="form",
                mode="game",
            )
        )
    else:
        context["id_sheet"] = False

    return render(request, "games/play.html", context)


def games_event(request):
    """
    Play-funnel beacon for the vendored games (GameEvent rows).

    POSTed by core/shell.js with FormData: slug, kind (played|finished),
    score and the optional qr key so the row lands on the right outlet and
    brand. Scores are clamped; unknown slugs and kinds are rejected.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    slug = (request.POST.get("slug") or "")[:40]
    kind = (request.POST.get("kind") or "")[:16]
    game = get_game(slug)
    if game is None or not game.enabled:
        return JsonResponse({"ok": False}, status=400)
    if kind not in ("played", "finished"):
        return JsonResponse({"ok": False}, status=400)
    try:
        score = int(request.POST.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(score, 10_000_000))

    qr = None
    key = (request.POST.get("qr") or "")[:80]
    if key:
        qr = QrCode.objects.filter(redirect_key=key).first()
    brand = qr.brand if qr else None
    outlet = qr.outlet if qr else None
    GameEvent.objects.create(
        game_slug=slug,
        kind=kind,
        score=score,
        brand=brand,
        outlet=outlet,
        qr_code=qr,
        session_key=request.session.session_key or "",
    )

    payload = {"ok": True, "reward": None, "identified": False}
    if kind == "finished":
        payload.update(_reward_for_round(request, slug, score, brand, outlet))
    return JsonResponse(payload)


def _reward_for_round(request, slug, score, brand, outlet):
    """Decide what a finished round earned, if anything.

    A missing, forged or stale round token means no coupon. The analytics row
    above is still written, so a plain POST to this endpoint can never mint a
    reward on its own.

    The extra fields (`level`, `result`, `duration`, `actions`) are what turn
    a score into a claim: the ladder has to know which rung was played and
    whether it was won, and the effort floor has to know the round was really
    played. All of them come from the browser and none of them are proof.
    """
    token = (request.POST.get("token") or "")[:512]

    def _refusal(reason):
        """Same shape as a real answer, so the shell can always explain why."""
        return {
            "reward": None,
            "identified": False,
            "verified": False,
            "reason": reason,
            "message": REASON_TEXT.get(reason, ""),
            "progress": progress_payload(None, slug),
        }

    if not verify_round_token(token, slug):
        return _refusal(Reason.TOKEN)

    profile, _created = ensure_profile(request, brand=brand, outlet=outlet)
    if profile is None:
        return _refusal(Reason.NO_PROFILE)

    def _int(name):
        try:
            return int(request.POST.get(name) or 0)
        except (TypeError, ValueError):
            return 0

    outcome = evaluate_round(
        profile,
        slug,
        score,
        brand=brand,
        outlet=outlet,
        level=_int("level"),
        result=(request.POST.get("result") or "")[:8],
        duration=_int("duration"),
        actions=_int("actions"),
    )

    reward = None
    if outcome.coupon is not None:
        reward = {
            "code": outcome.coupon.code,
            "label": outcome.coupon.label,
            "expires_at": outcome.coupon.expires_at.isoformat(),
            # The two facts the win ticket needs to pick its face: a dessert
            # shows the prize words, a percentage shows the number.
            "kind": outcome.coupon.reward_type,
            "percent": int(outcome.coupon.percent or 0),
        }
    # Being verified is the gate on being PAID, never on playing. The name
    # and mobile form stays an invitation to everyone else (client rule
    # 2026-10-16: a guest without login plays any game at any level with no
    # restriction, they simply do not earn anything).
    return {
        "reward": reward,
        "identified": bool(profile.phone),
        "verified": profile.is_verified,
        "reason": outcome.reason,
        "message": outcome.message,
        "progress": outcome.progress,
    }
