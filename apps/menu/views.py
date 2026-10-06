"""
Customer views for Specials & Menu (Spec Part C.1 & C.2).
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.db.models import Q

from apps.core.models import QrCode
from apps.menu.models import SpecialItem, MenuSource
from apps.analytics.models import TapEvent


@require_GET
def customer_specials(request, key):
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True)
    brand = qr.brand
    outlet = qr.outlet

    # Record TapEvent for Analytics
    TapEvent.objects.create(
        outlet=outlet,
        brand=brand,
        qr_code=qr,
        action=TapEvent.ActionType.SPECIALS,
        session_key=request.session.session_key or ""
    )

    now = timezone.now()
    base_specials = SpecialItem.objects.filter(
        brand=brand, active=True
    ).filter(
        (Q(start_at__isnull=True) | Q(start_at__lte=now)) & (Q(end_at__isnull=True) | Q(end_at__gte=now))
    ).select_related("replaces", "outlet")

    signatures = resolve_specials_group(base_specials, SpecialItem.Kind.SIGNATURE, outlet)
    weekends = resolve_specials_group(base_specials, SpecialItem.Kind.WEEKEND, outlet)
    offers = resolve_specials_group(base_specials, SpecialItem.Kind.OFFER, outlet)

    lang = request.GET.get("lang", "en")
    dir_rtl = (lang == "ar")

    context = {
        "qr": qr,
        "brand": brand,
        "outlet": outlet,
        "signatures": signatures,
        "weekends": weekends,
        "weekend": weekends,
        "offers": offers,
        "lang": lang,
        "dir": "rtl" if dir_rtl else "ltr",
        "brand_colors": brand.brand_colors or {},
    }
    return render(request, "customer_specials.html", context)


@require_GET
def customer_menu(request, key):
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), redirect_key=key, active=True)
    brand = qr.brand
    outlet = qr.outlet

    # Record TapEvent
    TapEvent.objects.create(
        outlet=outlet,
        brand=brand,
        qr_code=qr,
        action=TapEvent.ActionType.MENU,
        session_key=request.session.session_key or ""
    )

    menu_source = None
    if outlet:
        menu_source = MenuSource.objects.filter(outlet=outlet, active=True).prefetch_related("pages").first()
    if not menu_source:
        menu_source = MenuSource.objects.filter(brand=brand, outlet__isnull=True, active=True).prefetch_related("pages").first()

    ordering_url = ""
    if menu_source and menu_source.ordering_url:
        ordering_url = menu_source.ordering_url
    elif outlet and outlet.ordering_url:
        ordering_url = outlet.ordering_url
    elif brand.default_ordering_url:
        ordering_url = brand.default_ordering_url

    if menu_source:
        if menu_source.menu_type == MenuSource.MenuType.EXTERNAL_URL and menu_source.menu_url:
            return redirect(menu_source.menu_url)
        if menu_source.menu_type == MenuSource.MenuType.PDF and menu_source.menu_file:
            return redirect(menu_source.menu_file.url)

    if not menu_source:
        direct_url = (outlet.menu_url if outlet else "") or brand.default_menu_url
        if direct_url:
            return redirect(direct_url)

    pages = menu_source.pages.all().order_by("page_number") if menu_source else []

    lang = request.GET.get("lang", "en")
    dir_rtl = (lang == "ar")

    context = {
        "qr": qr,
        "brand": brand,
        "outlet": outlet,
        "menu_source": menu_source,
        "pages": pages,
        "ordering_url": ordering_url,
        "lang": lang,
        "dir": "rtl" if dir_rtl else "ltr",
        "brand_colors": brand.brand_colors or {},
    }
    return render(request, "customer_menu.html", context)


def resolve_specials_group(qs, kind, outlet):
    brand_items = [i for i in qs if i.kind == kind and i.outlet is None]
    if not outlet:
        return brand_items

    outlet_items = [i for i in qs if i.kind == kind and i.outlet_id == outlet.id]

    replaces_ids = {o.replaces_id for o in outlet_items if o.replaces_id}
    outlet_titles = {o.title_en.lower() for o in outlet_items}

    result = []
    for b in brand_items:
        if b.id in replaces_ids or b.title_en.lower() in outlet_titles:
            continue
        result.append(b)

    result.extend(outlet_items)
    result.sort(key=lambda x: (x.display_order, x.id))

    if kind == SpecialItem.Kind.OFFER:
        valid_offers = []
        for o in result:
            if o.original_price and o.offer_price and o.offer_price < o.original_price:
                valid_offers.append(o)
        return valid_offers

    # Weekend specials are title + photo only. A stored price must not hide the dish.
    if kind == SpecialItem.Kind.WEEKEND:
        for item in result:
            item.original_price = None
            item.offer_price = None
            item.discount_label = ""

    return result

