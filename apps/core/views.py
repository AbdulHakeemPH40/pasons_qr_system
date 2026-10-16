"""
Public views — Smart Pages (spec sections 9-11) and the dynamic QR
redirect engine (spec section 23).

Flow per scan:
    QR -> /q/<redirect_key>/ -> resolve -> record ScanEvent
       -> apply brand/outlet/campaign/language rules -> open destination.
"""

import hashlib
import json

from django.conf import settings
from django.db.models import Avg, Count
from django.http import HttpResponseGone, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from django.core.cache import cache
from apps.analytics.models import ScanEvent, TapEvent
from apps.engagement.models import Feedback
from apps.menu.models import MenuCategory, items_for

from .models import Brand, Campaign, QrCode, SmartPage
from .review_assist import suggest_variants
from .templatetags.social_tags import circle_links, ig_handle

# Guest identity sheet context (apps/guests). Imported here because this
# module owns the landing-window context; the sheet itself lives in that app.
from apps.guests.context import guest_wallet, sheet_context

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()


def _language(request):
    """Phase 1 language rule (spec section 20): ?lang= override, else default."""
    lang = request.GET.get("lang", "en")
    return "ar" if lang == "ar" else "en"


def _menu_groups(brand, outlet):
    """Menu grouped by category, with outlet overrides applied (spec 6/10)."""
    visible = items_for(brand, outlet)
    by_category = {}
    for item in visible:
        by_category.setdefault(item.category_id, []).append(item)
    groups = []
    for category in MenuCategory.objects.filter(
        brand=brand, active=True
    ).order_by("sort_order"):
        if category.id in by_category:
            groups.append(
                {"category": category, "items": by_category.pop(category.id)}
            )
    for leftover in by_category.values():  # outlet-only items in uncached categories
        groups.append({"category": leftover[0].category, "items": leftover})
    return groups


def _remember_shop(request, slug):
    """Remember the shop this browser last opened, so / can reopen it."""
    request.session["last_shop"] = slug


def _open_remembered_shop(request):
    """The shop this browser last opened, if that page is still published."""
    slug = request.session.get("last_shop")
    if not slug:
        return None
    page = (
        SmartPage.objects.select_related("brand", "outlet")
        .filter(slug=slug, published=True, brand__status="active")
        .first()
    )
    if page is None or (page.outlet and not page.outlet.active):
        return None
    qr = _landing_qr(page.brand, page.outlet)
    if qr is None:
        return None
    return render(
        request,
        "outlet_landing.html",
        _landing_context(request, page.brand, page.outlet, qr),
    )


@require_GET
def home(request):
    """
    Public entry is the shop this browser last opened, not a brand directory.

    Opening /p/<slug>/ or scanning /q/<token>/ remembers that shop. The next
    visit to / reopens that same window. A first visit, with nothing
    remembered, uses the most recently scanned active QR.
    """
    remembered = _open_remembered_shop(request)
    if remembered is not None:
        return remembered
    qr = (
        QrCode.objects.filter(active=True, brand__status="active")
        .select_related("brand", "outlet", "destination_page")
        .order_by("-last_scanned_at", "-id")
        .first()
    )
    if qr is None:
        return render(request, "404.html", status=404)
    if qr.destination_page_id and qr.destination_page.published:
        _remember_shop(request, qr.destination_page.slug)
    return qr_redirect(request, qr.redirect_key)


@require_http_methods(["GET", "POST"])
def smart_page(request, slug):
    page = get_object_or_404(
        SmartPage.objects.select_related("brand", "outlet"), slug=slug, published=True
    )
    brand, outlet = page.brand, page.outlet

    if request.method == "POST":
        # Feedback capture (spec section 19)
        Feedback.objects.create(
            brand=brand,
            outlet=outlet,
            rating=int(request.POST.get("rating", 5)),
            category=request.POST.get("category", "other"),
            message=request.POST.get("message", ""),
            customer_name=request.POST.get("customer_name", ""),
            customer_phone=request.POST.get("customer_phone", ""),
        )
        query = {"thanks": "1"}
        if request.GET.get("lang"):
            query["lang"] = request.GET["lang"]
        return redirect(
            reverse("smart_page", args=[slug], query=query, fragment="feedback")
        )

    # Old printed /p/<slug>/ links open the same shop window a scan opens.
    # The location picker is not a customer page, so this is the only GET path.
    _remember_shop(request, slug)
    return render(
        request,
        "outlet_landing.html",
        _landing_context(request, brand, outlet, _landing_qr(brand, outlet)),
    )


def _review_url(brand, outlet):
    """Google review link. Contract: leave Review URL empty and the link is
    built from the Place ID. Outlet review URL -> Outlet Place ID ->
    Brand review URL -> Brand Place ID -> Google search fallback."""
    if outlet and outlet.google_review_url:
        return outlet.google_review_url
    if outlet and outlet.google_place_id:
        return f"https://search.google.com/local/writereview?placeid={outlet.google_place_id}"
    if brand.google_review_url:
        return brand.google_review_url
    if brand.google_place_id:
        return f"https://search.google.com/local/writereview?placeid={brand.google_place_id}"
    return f"https://www.google.com/search?q={brand.name_en}"


def _maps_url(brand, outlet):
    """Directions link: explicit maps URL first, else built from the Place ID."""
    if outlet and outlet.google_maps_url:
        return outlet.google_maps_url
    if outlet and outlet.google_place_id:
        return f"https://www.google.com/maps/search/?api=1&query_place_id={outlet.google_place_id}"
    if brand.google_place_id:
        return f"https://www.google.com/maps/search/?api=1&query_place_id={brand.google_place_id}"
    return ""


def _h12(value):
    """"23:00" -> "11 PM" (frame 02 identity: "Closes 11 PM")."""
    try:
        hour, minute = (int(x) for x in str(value).split(":")[:2])
    except (TypeError, ValueError):
        return str(value)
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}" if minute else f"{hour12} {suffix}"


class _PageKey:
    """A page with no printed QR still needs a key the action cards can use.

    Menu, specials and games resolve the shop from QrCode.redirect_key, so
    the key has to be a real code for this brand and this outlet only.
    """

    def __init__(self, qr):
        self.redirect_key = qr.redirect_key
        self.pk = qr.pk


def _landing_qr(brand, outlet):
    """The printed QR whose window /p/<slug>/ must show.

    Prefer the entrance code for this exact outlet (or the brand, when the
    page has no outlet). Fall back to any code for the same place, then
    mint one so the cards never point at another shop.
    """
    qs = QrCode.objects.filter(brand=brand, outlet=outlet)
    found = (
        qs.filter(active=True, source_type=QrCode.SourceType.ENTRANCE).order_by("id").first()
        or qs.filter(active=True).order_by("id").first()
        or qs.order_by("id").first()
    )
    if found is not None:
        return _PageKey(found)
    page = (
        SmartPage.objects.filter(brand=brand, outlet=outlet, published=True).order_by("id").first()
        or SmartPage.objects.filter(brand=brand, outlet__isnull=True, published=True).order_by("id").first()
    )
    if page is None:
        return None
    scope = (outlet.code.split("-", 1)[-1] if outlet else "MAIN")
    qr = QrCode(
        qr_code_name=f"{brand.code}-{scope}-FLYER-PAGE",
        destination_page=page,
        brand=brand,
        outlet=outlet,
        source_type=QrCode.SourceType.FLYER,
    )
    qr.save()
    return _PageKey(qr)


def _identity_next(request):
    """Where the identity sheet comes back to: the page the guest is on.

    Only our own /q/ and /p/ paths are returned; the submit view allow-lists
    them again, so this is belt and braces against an open redirect.
    """
    path = request.path or ""
    if path.startswith(("/q/", "/p/")):
        return path
    return "/"


def _landing_context(request, brand, outlet, qr):
    """The scanned-shop window. /q/<key>/ and old /p/<slug>/ links share it."""
    hours_owner = outlet if (outlet and outlet.opening_hours) else None
    if not hours_owner:
        active_outlets = list(brand.outlets.filter(active=True))
        hours_owner = next((o for o in active_outlets if o.opening_hours), None)

    today_key = DAY_KEYS[timezone.localtime().weekday()]
    hours = (hours_owner.opening_hours if hours_owner else {}) or {}
    today_hours = hours.get(today_key) or None

    is_open = hours_owner.is_open_now() if hours_owner else True
    today_close_str = ""
    if today_hours and not today_hours.get("closed") and today_hours.get("close"):
        today_close_str = _h12(today_hours["close"])

    address_line = (outlet.address if outlet else "") or getattr(brand, "corporate_address", "")
    lang = _language(request)
    context = {
        "qr": qr,
        "brand": brand,
        "outlet": outlet,
        "outlet_title": f"{_brand_short(brand)} - Restaurant",
        "subtitle": brand.description.split("—")[0].strip() if brand.description else "Authentic Dining Experience",
        "is_open": is_open,
        "today_close_str": today_close_str,
        "address_line": address_line,
        "address": address_line,
        "maps_url": _maps_url(brand, outlet),
        "phone_number": (outlet.phone if outlet else "") or brand.default_phone,
        "whatsapp_url": _wa_link((outlet.whatsapp if outlet else "") or brand.default_whatsapp),
        "brand_colors": brand.brand_colors or {},
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "has_specials": True,
        "has_menu": True,
        "has_review": True,
        "has_instagram": True,
        # Saved guest: the profile circle next to Call / WhatsApp / Instagram.
        # None on a first visit, so the circle is not rendered at all.
        "guest_wallet": guest_wallet(request, brand),
    }

    # Guest identity sheet (apps/guests): the follow question and the name +
    # mobile form. It needs a QR key to post to, and /p/<slug>/ can reach this
    # window with no code at all, so the sheet is simply left out when there
    # is no key to hang the form on.
    if qr is not None:
        context.update(
            sheet_context(request, qr, next_path=_identity_next(request))
        )
    else:
        context["id_sheet"] = False

    return context


def _wa_link(number):
    if not number:
        return ""
    digits = "".join(c for c in number if c.isdigit())
    return f"https://wa.me/{digits}"


def _outlet_short(outlet):
    """"King Chef \u2014 Deira" -> "Deira" (frame 09 location rows)."""
    return outlet.official_name.split("\u2014")[-1].strip() or outlet.official_name


def _brand_short(brand):
    """"King Chef Restaurant" -> "King Chef" (frame 09 row: "All King Chef")."""
    return brand.name_en.replace(" Restaurant", "").strip() or brand.name_en


def _override_labels(outlet):
    """Spec section 6: which fields this outlet overrides instead of inheriting."""
    labels = []
    if outlet.opening_hours:
        labels.append("hours")
    if outlet.phone or outlet.whatsapp:
        labels.append("phone")
    if outlet.google_maps_url or outlet.google_place_id:
        labels.append("map")
    return labels


def _location_rows(brand, current_outlet=None):
    """Frame 09 'Choose a location' — one row per active outlet."""
    pages = {
        p.outlet_id: p
        for p in SmartPage.objects.filter(brand=brand, published=True, outlet__isnull=False)
    }
    rows = []
    for outlet in brand.outlets.filter(active=True).order_by("id"):
        labels = _override_labels(outlet)
        n = len(labels)
        if n == 0:
            sub, badge = "Everything inherited from brand", "INHERITS ALL"
        elif n == 1:
            sub, badge = f"Own {labels[0]} only", "1 OVERRIDE"
        else:
            sub, badge = f"Own {' \u00b7 '.join(labels)}", f"{n} OVERRIDES"
        page = pages.get(outlet.id)
        rows.append(
            {
                "name": _outlet_short(outlet),
                "initial": "\u00b7",
                "sub": sub,
                "badge": badge,
                "url": reverse("smart_page", args=[page.slug]) if page else "",
                "selected": current_outlet is not None and current_outlet.id == outlet.id,
            }
        )
    return rows


def _resolve_rows(outlet):
    """Frame 09 'How a field resolves' — per-field brand vs outlet source."""

    def src(own):
        return "OUTLET OVERRIDE" if own else "BRAND CONTENT"

    return [
        ("Opening hours", src(bool(outlet.opening_hours))),
        ("Phone number", src(bool(outlet.phone or outlet.whatsapp))),
        ("Google Place ID", src(bool(outlet.google_place_id or outlet.google_maps_url))),
        ("Full menu", "BRAND CONTENT"),
        ("Special offers", "BRAND CONTENT"),
        ("Instagram & social", "BRAND CONTENT"),
    ]


def _rate_limit_check(request):
    """Rate limit per hashed IP: max 60 requests/minute using cache."""
    ip_hash = _hash_ip(request.META.get("REMOTE_ADDR", ""))
    cache_key = f"rl:qr:{ip_hash}"
    count = cache.get(cache_key, 0)
    if count >= 60:
        return False
    cache.set(cache_key, count + 1, timeout=60)
    return True


@require_GET
def qr_redirect(request, key):
    """
    Permanent QR routing (Meta-Prompt Part A & Spec Section 23):
    1. Validates token format
    2. Enforces IP rate-limiting (429)
    3. Unknown -> 404, Inactive/retired -> 410
    4. Records ScanEvent and sets request.session["qr"] = qr.pk
    5. Directly renders the outlet landing window (outlet_landing.html)
    """
    # Keys are minted with secrets.token_urlsafe() (panel generate/regenerate),
    # whose alphabet is [A-Za-z0-9_-] — accept it in full, or ~17% of minted
    # keys would 404 here before the retired-410 check below.
    if len(key) > 64 or not key.replace("-", "").replace("_", "").isalnum():
        return render(request, "404.html", status=404)

    if not _rate_limit_check(request):
        return render(request, "429.html", status=429)

    qr = QrCode.objects.select_related(
        "destination_page", "brand", "outlet", "campaign"
    ).filter(redirect_key=key).first()

    if qr is None:
        return render(request, "404.html", status=404)

    if not qr.active or (qr.outlet and not qr.outlet.active) or qr.brand.status != "active":
        return render(request, "410.html", status=410)

    # User agent device class determination
    ua = request.META.get("HTTP_USER_AGENT", "").lower()
    device_class = "mobile"
    if "tablet" in ua or "ipad" in ua:
        device_class = "tablet"
    elif "windows" in ua or "macintosh" in ua or "linux" in ua:
        if "mobile" not in ua:
            device_class = "desktop"

    # Record ScanEvent with session key, referrer, device class
    ScanEvent.objects.create(
        qr_code=qr,
        brand=qr.brand,
        outlet=qr.outlet,
        campaign=qr.campaign,
        language=request.GET.get("lang", ""),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:240],
        referrer=request.META.get("HTTP_REFERER", "")[:250],
        device_class=device_class,
        session_key=request.session.session_key or "",
        ip_hash=_hash_ip(request.META.get("REMOTE_ADDR", "")),
    )

    # Denormalized scan update if field exists
    QrCode.objects.filter(pk=qr.pk).update(
        scan_count=qr.scan_count + 1,
        last_scanned_at=timezone.now()
    )

    # Store resolved context in signed session (source of truth)
    request.session["qr"] = qr.pk
    if qr.destination_page_id:
        _remember_shop(request, qr.destination_page.slug)

    return render(
        request,
        "outlet_landing.html",
        _landing_context(request, qr.brand, qr.outlet, qr),
    )


@require_GET
def qr_review_redirect(request, key):
    """
    Logs tap event, then 302 redirects to outlet Google review link (Part C.3).
    Outlet review link -> Place ID -> Brand review link -> Brand Place ID
    """
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True)
    outlet = qr.outlet
    brand = qr.brand

    TapEvent.objects.create(
        outlet=outlet,
        brand=brand,
        qr_code=qr,
        action=TapEvent.ActionType.REVIEW,
        session_key=request.session.session_key or ""
    )

    review_url = _review_url(brand, outlet)

    return redirect(review_url)


# --------------------------------------------------------------------------
# Review composer (spec section 39) — write here, get AI-polished variants,
# copy one, then post it on Google. Google has no API to post reviews on a
# guest's behalf, so the final post always happens on Google itself.
# --------------------------------------------------------------------------

def _composer_context(request, brand, outlet, back_url, open_url):
    lang = _language(request)
    return {
        "brand": brand,
        "outlet": outlet,
        "back_url": back_url,
        "google_open_url": open_url,
        "assist_url": reverse("review_assist"),
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
    }


@require_GET
def qr_review_write(request, key):
    """Composer page for a scanned QR. The final button goes through
    qr_review_redirect, so the Google tap stays tracked as before."""
    qr = get_object_or_404(
        QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True
    )
    context = _composer_context(
        request, qr.brand, qr.outlet,
        back_url=reverse("qr_landing", args=[qr.redirect_key]),
        open_url=reverse("qr_review", args=[qr.redirect_key]),
    )
    return render(request, "review_composer.html", context)


@require_GET
def smart_review_write(request, slug):
    """Same composer reached from a Smart Page (brand or outlet)."""
    page = get_object_or_404(
        SmartPage.objects.select_related("brand", "outlet"), slug=slug, published=True
    )
    brand, outlet = page.brand, page.outlet
    context = _composer_context(
        request, brand, outlet,
        back_url=reverse("smart_page", args=[slug]),
        open_url=_review_url(brand, outlet),
    )
    return render(request, "review_composer.html", context)


@require_POST
def api_review_assist(request):
    """POST {"text": "<half review>"} -> 6 improved versions (spec section 39).

    Versions come from the LLM (MiMo first, then DeepSeek / Gemini) as plain
    strings — no tone labels, no emojis. Without a key the draft is returned
    lightly tidied (the guest's own words only). Light per-IP throttle.
    """
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            payload = {}
    else:
        payload = request.POST
    text = (payload.get("text") or "").strip()

    if len(text) < 3 or len(text) > 2000:
        return JsonResponse(
            {"error": "Write at least a few words (max 2000 characters)."},
            status=400,
        )

    bucket = f"review-assist:{request.META.get('REMOTE_ADDR', '')}"
    hits = cache.get(bucket, 0)
    if hits >= 12:
        return JsonResponse(
            {"error": "Too many suggestions right now — try again in a minute."},
            status=429,
        )
    cache.set(bucket, hits + 1, 60)

    return JsonResponse(suggest_variants(text))


@require_GET
def qr_instagram_redirect(request, key):
    """
    Logs tap event, then 302 redirects to outlet/brand Instagram (Part C.4).
    """
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True)
    outlet = qr.outlet
    brand = qr.brand

    TapEvent.objects.create(
        outlet=outlet,
        brand=brand,
        qr_code=qr,
        action=TapEvent.ActionType.INSTAGRAM,
        session_key=request.session.session_key or ""
    )

    ig_url = ""
    if outlet and outlet.instagram_url:
        ig_url = outlet.instagram_url
    elif brand.social_links and brand.social_links.get("instagram"):
        value = brand.social_links.get("instagram").replace("@", "").strip()
        # social_links stores full URLs; a bare handle is also tolerated
        if value.startswith(("http://", "https://")):
            ig_url = value
        elif value.startswith(("instagram.com", "www.instagram.com")):
            ig_url = f"https://{value}"
        else:
            ig_url = f"https://instagram.com/{value}"

    if not ig_url:
        ig_url = "https://instagram.com"

    return redirect(ig_url)


@require_http_methods(["POST"])
def tap_beacon(request, key):
    """
    navigator.sendBeacon endpoint for in-page sub-views & buttons (Call, Directions, Order).
    """
    qr = QrCode.objects.select_related("outlet", "brand").filter(redirect_key=key).first()
    if not qr:
        return JsonResponse({"error": "not found"}, status=404)

    action = request.POST.get("action")
    if action in TapEvent.ActionType.values:
        TapEvent.objects.create(
            outlet=qr.outlet,
            brand=qr.brand,
            qr_code=qr,
            action=action,
            session_key=request.session.session_key or ""
        )
        return JsonResponse({"ok": True})
    return JsonResponse({"error": "invalid action"}, status=400)

