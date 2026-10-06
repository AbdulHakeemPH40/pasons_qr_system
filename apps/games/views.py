"""
Games views (Part C.5):
Interactive game interface and server-side submission endpoint.
"""

import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.core.models import QrCode
from apps.games.engine import resolve_active_game, evaluate_game_submission, get_device_hash
from apps.analytics.models import TapEvent


@ensure_csrf_cookie
@require_GET
def customer_game(request, key):
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True)
    brand = qr.brand
    outlet = qr.outlet

    # Record TapEvent for Analytics
    TapEvent.objects.create(
        outlet=outlet,
        brand=brand,
        qr_code=qr,
        action=TapEvent.ActionType.GAME,
        session_key=request.session.session_key or ""
    )

    game = resolve_active_game(brand, outlet)
    if not game:
        return redirect(reverse("qr_landing", args=[key]))

    lang = request.GET.get("lang", "en")
    dir_rtl = (lang == "ar")

    config = game.configuration or {}
    icons = config.get("icons", ["🍲", "🍗", "☕", "🍨", "🥗", "🍔"])
    time_limit = config.get("time_limit_sec", 60)

    context = {
        "qr": qr,
        "brand": brand,
        "outlet": outlet,
        "game": game,
        "lang": lang,
        "dir": "rtl" if dir_rtl else "ltr",
        "brand_colors": brand.brand_colors or {},
        "game_config_json": json.dumps({
            "icons": icons,
            "timeLimit": time_limit,
            "resultUrl": reverse("customer_game_result", args=[key]),
        })
    }
    return render(request, "customer_game.html", context)


@require_POST
def customer_game_result(request, key):
    qr = QrCode.objects.select_related("outlet", "brand").filter(redirect_key=key, active=True).first()
    if not qr:
        return JsonResponse({"error": "Invalid or inactive QR code"}, status=404)

    # Session check verification
    session_qr_pk = request.session.get("qr")
    if session_qr_pk and session_qr_pk != qr.pk:
        return JsonResponse({"error": "Session mismatch with QR token"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
        moves = int(data.get("moves", 0))
        time_seconds = int(data.get("time_seconds", 0))
    except (ValueError, TypeError, KeyError):
        return HttpResponseBadRequest("Invalid payload")

    brand = qr.brand
    outlet = qr.outlet

    if not outlet:
        return JsonResponse({"error": "Reward must be tied to an outlet"}, status=400)

    game = resolve_active_game(brand, outlet)
    if not game:
        return JsonResponse({"error": "No active game found"}, status=400)

    device_hash = get_device_hash(request)
    won, reward, message = evaluate_game_submission(
        game=game,
        outlet=outlet,
        qr_code=qr,
        moves=moves,
        time_seconds=time_seconds,
        device_hash=device_hash,
        session_key=request.session.session_key or ""
    )

    if won and reward:
        return JsonResponse({
            "won": True,
            "coupon_code": reward.coupon_code,
            "discount": reward.reward_value,
            "outlet_name": outlet.official_name,
            "expires_at": reward.expires_at.strftime("%b %d, %Y"),
            "message": message
        })
    else:
        return JsonResponse({
            "won": False,
            "message": message
        })
