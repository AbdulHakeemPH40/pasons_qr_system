"""
Games Zone views (GAMES_ZONE_PLAN.md sections 4 and 6).

Three public surfaces:
  /q/<key>/game/   entry from printed QR and the landing card; logs the tap
                   and hands over to the hub (URL name kept for old sheets)
  /games/          hub listing the enabled games in the outlet's brand colours
  /games/<slug>/   full-screen play page with Exit back to the QR page

Games are pure play: no rewards, no discounts, no personal data. The only
server-side record is the existing TapEvent analytics row.
"""

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.analytics.models import TapEvent
from apps.core.models import Brand, Outlet, QrCode

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


def _brand_context(back):
    """Resolve (brand, outlet) from the sanitised back path for theming."""
    if back.startswith("/q/"):
        key = back[3:].strip("/")
        qr = (
            QrCode.objects.select_related("brand", "outlet")
            .filter(redirect_key=key)
            .first()
        )
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
    brand, outlet = _brand_context(back)
    qr_key = ""
    if back.startswith("/q/"):
        qr_key = back[3:].strip("/")
    return render(
        request,
        "games/play.html",
        {
            "game": game,
            "back": back,
            "brand": brand,
            "outlet": outlet,
            "qr_key": qr_key,
            "theme_payload": _theme_payload(brand),
            "bridge_payload": game.bridge,
            "place_name": _place_name(brand, outlet),
        },
    )


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
    GameEvent.objects.create(
        game_slug=slug,
        kind=kind,
        score=score,
        brand=qr.brand if qr else None,
        outlet=qr.outlet if qr else None,
        qr_code=qr,
        session_key=request.session.session_key or "",
    )
    return JsonResponse({"ok": True})
