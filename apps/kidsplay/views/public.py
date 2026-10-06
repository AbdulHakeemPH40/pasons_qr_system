"""QR landing, parent phone check, kid profile, and the game hub."""

from django.db import models
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.kidsplay import conf
from apps.kidsplay.models import Family, KidProfile, PlayGame, Reward
from apps.kidsplay.services import rewards as reward_service
from apps.kidsplay.services import nicknames, otp, privacy, visits

AVATARS = [
    "burger", "fries", "icecream", "pizza",
    "taco", "donut", "cupcake", "juice",
]


def _family(request) -> Family | None:
    family_id = request.session.get("kidsplay_family")
    if not family_id:
        return None
    return Family.objects.filter(pk=family_id, is_blocked=False).first()


def _kid(request, family: Family) -> KidProfile | None:
    kid_id = request.session.get("kidsplay_kid")
    if not kid_id:
        return None
    return family.kids.filter(pk=kid_id).first()


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@require_http_methods(["GET", "POST"])
def delete_family(request, table_code):
    qr = visits.find_table(table_code)
    family = _family(request)
    if qr is None or family is None:
        raise Http404("Start from the table QR")
    if request.method == "POST" and request.POST.get("confirm") == "delete":
        privacy.delete_family(family)
        request.session.flush()
        return redirect("kidsplay:landing", table_code=qr.redirect_key)
    return render(request, "kidsplay/delete.html", {"table_code": qr.redirect_key})


def landing(request, table_code):
    qr = visits.find_table(table_code)
    if qr is None:
        raise Http404("Unknown or inactive table")
    request.session["kidsplay_table"] = qr.redirect_key
    place = qr.outlet.official_name if qr.outlet_id else qr.brand.name_en
    family = _family(request)
    return render(request, "kidsplay/landing.html", {
        "place": place,
        "table_code": qr.redirect_key,
        "known": family is not None,
    })


@require_http_methods(["GET", "POST"])
def otp_request(request, table_code):
    qr = visits.find_table(table_code)
    if qr is None:
        raise Http404("Unknown or inactive table")
    error = ""
    phone = ""
    if request.method == "POST":
        phone = request.POST.get("phone", "")
        ok, reason = otp.request_code(phone, _client_ip(request))
        if ok:
            request.session["kidsplay_phone"] = otp.normalize_phone(phone)
            return redirect("kidsplay:otp_verify", table_code=qr.redirect_key)
        error = reason
    return render(request, "kidsplay/otp_request.html", {"error": error, "phone": phone, "table_code": qr.redirect_key})


@require_http_methods(["GET", "POST"])
def otp_verify(request, table_code):
    qr = visits.find_table(table_code)
    phone = request.session.get("kidsplay_phone", "")
    if qr is None or not phone:
        raise Http404("Start from the table QR")
    error = ""
    if request.method == "POST":
        if not request.POST.get("consent"):
            error = "consent"
        else:
            ok, reason = otp.verify_code(phone, request.POST.get("code", ""))
            if ok:
                family, _ = Family.objects.get_or_create(phone=phone)
                family.last_seen_at = timezone.now()
                if family.consent_at is None:
                    family.consent_at = timezone.now()
                family.save(update_fields=["last_seen_at", "consent_at"])
                request.session["kidsplay_family"] = str(family.pk)
                visits.open_visit(family, qr)
                return redirect("kidsplay:kids", table_code=qr.redirect_key)
            error = reason
    return render(request, "kidsplay/otp_verify.html", {"error": error, "phone": phone, "table_code": qr.redirect_key})


@require_http_methods(["GET", "POST"])
def kids(request, table_code):
    qr = visits.find_table(table_code)
    family = _family(request)
    if qr is None or family is None:
        raise Http404("Start from the table QR")
    if visits.active_visit(family) is None:
        visits.open_visit(family, qr)
    error = ""
    if request.method == "POST":
        chosen = request.POST.get("kid")
        if chosen:
            kid = family.kids.filter(pk=chosen).first()
            if kid:
                request.session["kidsplay_kid"] = str(kid.pk)
                return redirect("kidsplay:hub", table_code=qr.redirect_key)
            error = "missing"
        else:
            name, reason = nicknames.clean_nickname(request.POST.get("nickname", ""))
            avatar = request.POST.get("avatar", "")
            if reason:
                error = reason
            elif avatar not in AVATARS:
                error = "bad_avatar"
            elif not nicknames.can_add_kid(family):
                error = "too_many"
            else:
                kid = KidProfile.objects.create(family=family, nickname=name, avatar=avatar)
                request.session["kidsplay_kid"] = str(kid.pk)
                return redirect("kidsplay:hub", table_code=qr.redirect_key)
    return render(request, "kidsplay/kid_select.html", {
        "kids": family.kids.all(),
        "avatars": AVATARS,
        "error": error,
        "table_code": qr.redirect_key,
        "can_add": nicknames.can_add_kid(family),
        "max_kids": conf.get("MAX_KIDS_PER_FAMILY"),
    })


def rewards_page(request, table_code):
    qr = visits.find_table(table_code)
    family = _family(request)
    if qr is None or family is None:
        raise Http404("Start from the table QR")
    kid = _kid(request, family)
    if kid is None:
        return redirect("kidsplay:kids", table_code=qr.redirect_key)
    error = ""
    redemption = kid.redemptions.filter(status="pending").select_related("reward").first()
    if request.method == "POST" and redemption is None:
        reward = Reward.objects.filter(pk=request.POST.get("reward"), is_active=True).first()
        if reward and reward.outlet_id not in (None, qr.outlet_id):
            reward = None
        if reward is None:
            error = "out_of_stock"
        else:
            redemption, error = reward_service.create_redemption(kid, reward)
            kid.refresh_from_db()
    available = Reward.objects.filter(is_active=True).filter(
        models.Q(outlet__isnull=True) | models.Q(outlet=qr.outlet)
    )
    return render(request, "kidsplay/rewards.html", {
        "kid": kid,
        "rewards": available,
        "redemption": redemption,
        "error": error,
        "table_code": qr.redirect_key,
    })


def play(request, table_code, slug):
    qr = visits.find_table(table_code)
    family = _family(request)
    if qr is None or family is None:
        raise Http404("Start from the table QR")
    kid = _kid(request, family)
    if kid is None:
        return redirect("kidsplay:kids", table_code=qr.redirect_key)
    game = PlayGame.objects.filter(slug=slug, is_active=True).first()
    if game is None:
        raise Http404("Game not available")
    return render(request, "kidsplay/play.html", {
        "game": game,
        "kid": kid,
        "table_code": qr.redirect_key,
    })


def hub(request, table_code):
    qr = visits.find_table(table_code)
    family = _family(request)
    if qr is None or family is None:
        raise Http404("Start from the table QR")
    kid = _kid(request, family)
    if kid is None:
        return redirect("kidsplay:kids", table_code=qr.redirect_key)
    visit = visits.active_visit(family)
    return render(request, "kidsplay/hub.html", {
        "kid": kid,
        "visit": visit,
        "games": PlayGame.objects.filter(is_active=True),
        "table_code": qr.redirect_key,
        "place": qr.outlet.official_name if qr.outlet_id else qr.brand.name_en,
    })
