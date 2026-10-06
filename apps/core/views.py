"""
Public views — Smart Pages (spec sections 9-11) and the dynamic QR
redirect engine (spec section 23).

Flow per scan:
    QR -> /q/<redirect_key>/ -> resolve -> record ScanEvent
       -> apply brand/outlet/campaign/language rules -> open destination.
"""

import hashlib

from django.conf import settings
from django.db.models import Avg, Count
from django.http import HttpResponseGone, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from django.core.cache import cache
from apps.analytics.models import ScanEvent, TapEvent
from apps.engagement.models import Feedback
from apps.menu.models import MenuCategory, items_for

from .models import Brand, Campaign, QrCode, SmartPage
from .templatetags.social_tags import circle_links, ig_handle

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


@require_GET
def home(request):
    """
    Public entry is the scanned shop, not a brand directory.

    A table QR always lands on /q/<token>/ (that outlet's five actions).
    Opening / with no token uses the most recently scanned active QR so
    the same window is what a person sees, never the four-brand list.
    """
    qr = (
        QrCode.objects.filter(active=True, brand__status="active")
        .select_related("brand", "outlet")
        .order_by("-last_scanned_at", "-id")
        .first()
    )
    if qr is None:
        return render(request, "404.html", status=404)
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

    modules = set(
        page.modules.filter(enabled=True).values_list("module_type", flat=True)
    )
    live_campaign = (
        # auto-publish/auto-expire by window (spec 29): SCHEDULED flips to
        # effective the moment start_at passes, LIVE expires at end_at
        Campaign.objects.filter(
            brand=brand,
            status__in=[Campaign.Status.LIVE, Campaign.Status.SCHEDULED],
        )
        .filter(start_at__lte=timezone.now(), end_at__gte=timezone.now())
        .order_by("-start_at")
        .first()
    )
    offers = [
        item
        for item in items_for(brand, outlet)
        if item.offer_price is not None and item.available
    ]

    # brand pages describe the primary outlet's place + hours (frame 02/09)
    active_qs = list(brand.outlets.filter(active=True).order_by("id"))
    primary_outlet = outlet or (active_qs[0] if active_qs else None)

    # hours resolve outlet -> brand content (spec section 6, frame 09 table)
    hours_owner = outlet if (outlet and outlet.opening_hours) else None
    if hours_owner is None:
        hours_owner = next((o for o in active_qs if o.opening_hours), None)

    today_key = DAY_KEYS[timezone.localtime().weekday()]
    hours = (hours_owner.opening_hours if hours_owner else {}) or {}
    today_hours = hours.get(today_key) or None

    location_label = ""
    if primary_outlet:
        location_label = ", ".join(
            dict.fromkeys(
                p for p in (primary_outlet.city, primary_outlet.emirate) if p
            )
        ) or primary_outlet.official_name
    closing_label = ""
    if today_hours and not today_hours.get("closed") and today_hours.get("close"):
        closing_label = f"Closes {_h12(today_hours['close'])}"

    menu_groups = _menu_groups(brand, outlet)

    lang = _language(request)
    social = brand.social_links or {}

    # client modules 4/5 (spec 37): Instagram handle + ordered social dots.
    # Instagram comes from the brand social dict; the WA dot is injected from
    # the click-to-chat number so it always renders on a live page.
    instagram_handle = ig_handle(social.get("instagram", ""))
    social_links = circle_links(social, whatsapp_url=_wa_link(
        (outlet.whatsapp if outlet else "") or brand.default_whatsapp
    ))

    # guest rating summary for the identity + Google review modules
    feedback_agg = Feedback.objects.filter(brand=brand, outlet=outlet).aggregate(
        avg=Avg("rating"), n=Count("id")
    )
    review_avg = round(feedback_agg["avg"], 1) if feedback_agg["avg"] else None

    # frame 09 (spec section 6) — mandatory brand, optional outlets:
    # location chooser rows + per-field resolution for the focus outlet
    locations = []
    if active_qs:
        base = page.brand_page
        locations.append(
            {
                "name": f"All {_brand_short(brand)}",
                "initial": _brand_short(brand)[:1].upper(),
                "sub": "Every field served from brand content",
                "badge": "BRAND",
                "url": reverse("smart_page", args=[base.slug]) if base else "",
                "selected": outlet is None,
            }
        )
        locations.extend(_location_rows(brand, outlet))
    focus_outlet = outlet or (active_qs[0] if active_qs else None)
    resolve_rows = _resolve_rows(focus_outlet) if focus_outlet else []
    resolve_label = f"{_outlet_short(focus_outlet)} outlet" if focus_outlet else ""
    chooser_label = (
        f"{_outlet_short(outlet)} outlet" if outlet else "Brand default"
    ) if active_qs else ""

    # frame 09 brand identity meta: "<desc> · N outlets · EN + AR"
    brand_meta = ""
    if outlet is None and active_qs:
        desc = (brand.description or "").split("\u2014")[0].strip() or page.resolved(
            "hero_subtitle"
        )
        parts = [p for p in (desc,) if p]
        parts.append(f"{len(active_qs)} outlet{'' if len(active_qs) == 1 else 's'}")
        langs = " + ".join(str(l).upper() for l in (page.enabled_languages or []))
        if langs:
            parts.append(langs)
        brand_meta = " \u00b7 ".join(parts)

    context = {
        "page": page,
        "brand": brand,
        "outlet": outlet,
        "modules": modules,
        "title": page.resolved("page_title"),
        "hero_title": page.resolved("hero_title"),
        "hero_subtitle": page.resolved("hero_subtitle"),
        "location_label": location_label,
        "closing_label": closing_label,
        "brand_meta": brand_meta,
        "locations": locations,
        "chooser_label": chooser_label,
        "resolve_rows": resolve_rows,
        "resolve_label": resolve_label,
        "is_open": (hours_owner.is_open_now() if hours_owner else True),
        "today_hours": today_hours if today_hours and not today_hours.get("closed") else None,
        "review_avg": review_avg,
        "review_count": feedback_agg["n"],
        "campaign": live_campaign,
        "offers": offers,
        "menu": menu_groups,
        "menu_count": sum(len(g["items"]) for g in menu_groups),
        "google_review_url": (
            (outlet.google_review_url if outlet else "") or brand.google_review_url
        ),
        "social": social,
        "instagram_handle": instagram_handle,
        "social_links": social_links,
        "whatsapp_url": _wa_link(
            (outlet.whatsapp if outlet else "") or brand.default_whatsapp
        ),
        "phone": (outlet.phone if outlet else "") or brand.default_phone,
        "maps_url": (outlet.google_maps_url if outlet else "") or "",
        "thanks": request.GET.get("thanks") == "1",
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
    }
    return render(request, "smart_page.html", context)


def _h12(value):
    """"23:00" -> "11 PM" (frame 02 identity: "Closes 11 PM")."""
    try:
        hour, minute = (int(x) for x in str(value).split(":")[:2])
    except (TypeError, ValueError):
        return str(value)
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}" if minute else f"{hour12} {suffix}"


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
    if len(key) > 64 or not key.replace("-", "").isalnum():
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

    # Prepare Outlet Landing Window directly at /q/<token>/
    brand = qr.brand
    outlet = qr.outlet

    # Determine hours & open status
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

    # Info strip parameters
    address_line = (outlet.address if outlet else "") or getattr(brand, "corporate_address", "")
    maps_url = ""
    if outlet and outlet.google_maps_url:
        maps_url = outlet.google_maps_url
    elif outlet and outlet.google_place_id:
        maps_url = f"https://www.google.com/maps/search/?api=1&query_place_id={outlet.google_place_id}"
    elif brand.google_place_id:
        maps_url = f"https://www.google.com/maps/search/?api=1&query_place_id={brand.google_place_id}"

    phone_number = (outlet.phone if outlet else "") or brand.default_phone

    lang = _language(request)
    dir_rtl = (lang == "ar")

    context = {
        "qr": qr,
        "brand": brand,
        "outlet": outlet,
        "outlet_title": outlet.official_name if outlet else brand.name_en,
        "subtitle": brand.description.split("—")[0].strip() if brand.description else "Authentic Dining Experience",
        "is_open": is_open,
        "today_close_str": today_close_str,
        "address_line": address_line,
        "address": address_line,
        "maps_url": maps_url,
        "phone_number": phone_number,
        "brand_colors": brand.brand_colors or {},
        "lang": lang,
        "dir": "rtl" if dir_rtl else "ltr",
        # Client-mandated modules stay visible; missing links fall back inside each view.
        "has_specials": True,
        "has_menu": True,
        "has_review": True,
        "has_instagram": True,
        "has_game": True,
    }
    return render(request, "outlet_landing.html", context)


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

    review_url = ""
    if outlet and outlet.google_review_url:
        review_url = outlet.google_review_url
    elif outlet and outlet.google_place_id:
        review_url = f"https://search.google.com/local/writereview?placeid={outlet.google_place_id}"
    elif brand.google_review_url:
        review_url = brand.google_review_url
    elif brand.google_place_id:
        review_url = f"https://search.google.com/local/writereview?placeid={brand.google_place_id}"

    if not review_url:
        review_url = f"https://www.google.com/search?q={brand.name_en}"

    return redirect(review_url)


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
        handle = brand.social_links.get("instagram").replace("@", "").strip()
        ig_url = f"https://instagram.com/{handle}"

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

