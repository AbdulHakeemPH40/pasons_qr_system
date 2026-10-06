"""
Custom Management Panel views (/panel/) — Spec Part D.
Role-based: Head Office vs Outlet Manager.
Full QR lifecycle, Specials, Menus, Vouchers, Auditing.
"""

import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import Brand, ChangeLog, Outlet, QrCode, SmartPage
from apps.core.panel_permissions import (
    check_outlet_permission,
    is_head_office,
    log_change,
    scoped_brands,
    scoped_outlets,
)
from apps.core.qr_utils import generate_qr_png_bytes, generate_qr_svg_bytes, get_qr_url
from apps.games.models import Game, Reward
from apps.menu.models import MenuPage, MenuSource, SpecialItem


@login_required
@require_GET
def panel_dashboard(request):
    user = request.user
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)

    qr_qs = QrCode.objects.filter(outlet__in=outlets, active=True)
    total_scans = sum(qr_qs.values_list("scan_count", flat=True))
    rewards_issued = Reward.objects.filter(outlet__in=outlets).count()

    context = {
        "nav_active": "dashboard",
        "is_head_office": is_head_office(user),
        "outlet_count": outlets.count(),
        "brand_count": brands.count(),
        "qr_count": qr_qs.count(),
        "total_scans": total_scans,
        "rewards_issued": rewards_issued,
        "outlets": outlets[:20],
    }
    return render(request, "panel/dashboard.html", context)


@login_required
@require_GET
def panel_brands(request):
    user = request.user
    if not is_head_office(user):
        raise PermissionDenied("Only Head Office can manage brands.")
    brands = Brand.objects.all().order_by("name_en")
    return render(request, "panel/brands_list.html", {
        "nav_active": "brands",
        "is_head_office": True,
        "brands": brands,
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_brand_edit(request, pk=None):
    user = request.user
    if not is_head_office(user):
        raise PermissionDenied("Only Head Office can manage brands.")

    brand = get_object_or_404(Brand, pk=pk) if pk else None
    if request.method == "POST":
        name_en = (request.POST.get("name_en") or "").strip()
        code = (request.POST.get("code") or "").strip().upper()
        if not name_en or not code:
            messages.error(request, "Brand name and code are required.")
        elif Brand.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f"Brand code {code} is already in use.")
        else:
            if brand is None:
                brand = Brand(code=code)
            brand.name_en = name_en
            brand.name_ar = (request.POST.get("name_ar") or "").strip()
            brand.code = code
            brand.description = (request.POST.get("description") or "").strip()
            brand.default_phone = (request.POST.get("default_phone") or "").strip()
            brand.default_whatsapp = (request.POST.get("default_whatsapp") or "").strip()
            brand.google_review_url = (request.POST.get("google_review_url") or "").strip()
            brand.google_place_id = (request.POST.get("google_place_id") or "").strip()
            brand.status = request.POST.get("status") or "active"
            brand.save()
            log_change(user, "BRAND_EDIT" if pk else "BRAND_CREATE", brand.name_en, brand)
            messages.success(request, f"Saved brand {brand.name_en}.")
            return redirect("panel_brands")

    return render(request, "panel/brand_edit.html", {
        "nav_active": "brands",
        "is_head_office": True,
        "brand": brand,
    })


@login_required
@require_GET
def panel_outlets(request):
    user = request.user
    outlets = scoped_outlets(user).select_related("brand")
    context = {
        "nav_active": "outlets",
        "is_head_office": is_head_office(user),
        "outlets": outlets,
    }
    return render(request, "panel/outlets_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def panel_outlet_add(request):
    user = request.user
    if not is_head_office(user):
        raise PermissionDenied("Only Head Office can add outlets.")

    brands = Brand.objects.filter(status="active")
    if request.method == "POST":
        brand = get_object_or_404(Brand, pk=request.POST.get("brand"))
        official_name = (request.POST.get("official_name") or "").strip()
        code = (request.POST.get("code") or "").strip().upper()
        if not official_name or not code:
            messages.error(request, "Outlet name and code are required.")
        elif Outlet.objects.filter(code=code).exists():
            messages.error(request, f"Outlet code {code} is already in use.")
        else:
            outlet = Outlet.objects.create(
                brand=brand,
                code=code,
                official_name=official_name,
                city=(request.POST.get("city") or "").strip(),
                emirate=(request.POST.get("emirate") or "").strip() or "Dubai",
                address=(request.POST.get("address") or "").strip(),
                phone=(request.POST.get("phone") or "").strip(),
                google_review_url=(request.POST.get("google_review_url") or "").strip(),
                google_place_id=(request.POST.get("google_place_id") or "").strip(),
                instagram_url=(request.POST.get("instagram_url") or "").strip(),
                active=True,
            )
            slug = slugify(code) or f"outlet-{outlet.pk}"
            if not SmartPage.objects.filter(slug=slug).exists():
                SmartPage.objects.create(
                    brand=brand,
                    outlet=outlet,
                    slug=slug,
                    page_title=official_name,
                    hero_title=official_name,
                    published=True,
                    published_at=timezone.now(),
                )
            log_change(user, "OUTLET_CREATE", outlet.official_name, brand, outlet)
            messages.success(request, f"Outlet {outlet.official_name} created.")
            return redirect("panel_outlets")

    return render(request, "panel/outlet_add.html", {
        "nav_active": "outlets",
        "is_head_office": True,
        "brands": brands,
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_outlet_edit(request, pk):
    user = request.user
    outlet = get_object_or_404(Outlet, pk=pk)
    check_outlet_permission(user, outlet)

    if request.method == "POST":
        outlet.phone = request.POST.get("phone", outlet.phone)
        outlet.google_review_url = request.POST.get("google_review_url", outlet.google_review_url)
        outlet.google_place_id = request.POST.get("google_place_id", outlet.google_place_id)
        outlet.instagram_url = request.POST.get("instagram_url", outlet.instagram_url)
        outlet.menu_url = request.POST.get("menu_url", outlet.menu_url)
        outlet.save()

        log_change(user, "OUTLET_EDIT", outlet.official_name, outlet.brand, outlet)
        messages.success(request, f"Updated details for {outlet.official_name}.")
        return redirect("panel_outlets")

    context = {
        "nav_active": "outlets",
        "is_head_office": is_head_office(user),
        "outlet": outlet,
    }
    return render(request, "panel/outlet_edit.html", context)


@login_required
@require_GET
def panel_qrcodes(request):
    user = request.user
    outlets = scoped_outlets(user)
    qr_codes = QrCode.objects.filter(outlet__in=outlets).select_related("brand", "outlet").order_by("-id")
    context = {
        "nav_active": "qrcodes",
        "is_head_office": is_head_office(user),
        "qr_codes": qr_codes,
    }
    return render(request, "panel/qrcodes_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def panel_qr_generate(request):
    user = request.user
    if not is_head_office(user):
        raise PermissionDenied("Only Head Office can generate new QR codes.")

    brands = Brand.objects.filter(status="active")
    outlets = Outlet.objects.filter(active=True).select_related("brand")

    if request.method == "POST":
        outlet_id = request.POST.get("outlet")
        outlet = get_object_or_404(Outlet, pk=outlet_id)
        source_type = request.POST.get("source_type", "table")
        label = request.POST.get("label", "")

        dest_page = SmartPage.objects.filter(brand=outlet.brand, outlet=outlet).first()
        if not dest_page:
            dest_page = SmartPage.objects.filter(brand=outlet.brand, outlet__isnull=True).first()

        seq = QrCode.objects.filter(outlet=outlet).count() + 1
        outlet_code = outlet.code.split("-")[-1]
        qr_name = f"{outlet.brand.code}-{outlet_code}-{source_type.upper()}-{seq:03d}"

        qr = QrCode.objects.create(
            brand=outlet.brand,
            outlet=outlet,
            destination_page=dest_page,
            source_type=source_type,
            label=label or f"{outlet_code} #{seq}",
            qr_code_name=qr_name,
            redirect_key=secrets.token_urlsafe(9)
        )

        log_change(user, "QR_GENERATE", qr.qr_code_name, outlet.brand, outlet)
        messages.success(request, f"QR code {qr.qr_code_name} generated successfully.")
        return redirect("panel_qrcodes")

    context = {
        "nav_active": "qrcodes",
        "is_head_office": True,
        "brands": brands,
        "outlets": outlets,
        "source_types": QrCode.SourceType.choices,
    }
    return render(request, "panel/qr_generate.html", context)


@login_required
@require_GET
def panel_qr_download(request, pk, fmt):
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), pk=pk)
    check_outlet_permission(request.user, qr.outlet) if qr.outlet else None

    url = get_qr_url(qr.redirect_key, request)

    if fmt == "svg":
        data = generate_qr_svg_bytes(url)
        response = HttpResponse(data, content_type="image/svg+xml")
        response["Content-Disposition"] = f'attachment; filename="{qr.qr_code_name}.svg"'
        return response
    else:
        data = generate_qr_png_bytes(url)
        response = HttpResponse(data, content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="{qr.qr_code_name}.png"'
        return response


@login_required
@require_GET
def panel_qr_print(request, pk):
    qr = get_object_or_404(QrCode.objects.select_related("outlet", "brand"), pk=pk)
    if qr.outlet:
        check_outlet_permission(request.user, qr.outlet)
    context = {"qr": qr}
    return render(request, "panel/qr_print.html", context)


@login_required
def panel_qr_regenerate(request, pk):
    user = request.user
    if not is_head_office(user):
        raise PermissionDenied("Only Head Office can regenerate QR codes.")

    old_qr = get_object_or_404(QrCode, pk=pk)
    if not old_qr.active:
        messages.error(request, "Cannot regenerate an already retired QR code.")
        return redirect("panel_qrcodes")

    # Retire the printed token, but free the unique label for the replacement.
    retired_label = old_qr.label
    old_qr.active = False
    old_qr.label = f"{old_qr.label} (retired)"[:120]
    old_qr.save(update_fields=["active", "label"])

    new_qr = QrCode.objects.create(
        brand=old_qr.brand,
        outlet=old_qr.outlet,
        destination_page=old_qr.destination_page,
        source_type=old_qr.source_type,
        label=retired_label,
        qr_code_name=f"{old_qr.qr_code_name}-R",
        redirect_key=secrets.token_urlsafe(9)
    )

    log_change(user, "QR_REGENERATE", f"Replaced {old_qr.qr_code_name} with {new_qr.qr_code_name}", old_qr.brand, old_qr.outlet)
    messages.warning(request, f"Old QR {old_qr.qr_code_name} retired (410). New QR {new_qr.qr_code_name} active.")
    return redirect("panel_qrcodes")


@login_required
@require_GET
def panel_specials(request):
    user = request.user
    outlets = scoped_outlets(user)
    specials = SpecialItem.objects.filter(
        models_Q_outlet_or_brand(user, outlets)
    ).select_related("outlet", "brand").order_by("kind", "display_order")

    context = {
        "nav_active": "specials",
        "is_head_office": is_head_office(user),
        "specials": specials,
    }
    return render(request, "panel/specials_list.html", context)


@login_required
@require_GET
def panel_rewards(request):
    user = request.user
    outlets = scoped_outlets(user)
    query = request.GET.get("q", "").strip()

    qs = Reward.objects.filter(outlet__in=outlets).select_related("outlet", "game", "redeemed_by")
    if query:
        qs = qs.filter(coupon_code__icontains=query)

    context = {
        "nav_active": "games",
        "is_head_office": is_head_office(user),
        "rewards": qs[:50],
        "search_query": query,
    }
    return render(request, "panel/rewards_list.html", context)


@login_required
@require_POST
def panel_reward_redeem(request, pk):
    reward = get_object_or_404(Reward, pk=pk)
    check_outlet_permission(request.user, reward.outlet)

    if reward.status == Reward.Status.ISSUED:
        reward.status = Reward.Status.REDEEMED
        reward.redeemed_at = timezone.now()
        reward.redeemed_by = request.user
        reward.save(update_fields=["status", "redeemed_at", "redeemed_by"])

        log_change(request.user, "REWARD_REDEEM", reward.coupon_code, reward.outlet.brand, reward.outlet)
        messages.success(request, f"Coupon {reward.coupon_code} marked as REDEEMED.")
    else:
        messages.warning(request, f"Coupon {reward.coupon_code} is {reward.get_status_display()}.")

    return redirect("panel_rewards")


@login_required
@require_GET
def panel_changelog(request):
    user = request.user
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)

    if is_head_office(user):
        qs = ChangeLog.objects.all()
    else:
        from django.db.models import Q
        qs = ChangeLog.objects.filter(Q(outlet__in=outlets) | (Q(outlet__isnull=True) & Q(brand__in=brands)))

    qs = qs.select_related("user", "brand", "outlet").order_by("-changed_at")[:100]

    context = {
        "nav_active": "changelog",
        "is_head_office": is_head_office(user),
        "changelogs": qs,
    }
    return render(request, "panel/changelog.html", context)


def models_Q_outlet_or_brand(user, outlets):
    if is_head_office(user):
        return Q()
    brands = scoped_brands(user)
    return Q(outlet__in=outlets) | (Q(outlet__isnull=True) & Q(brand__in=brands))


@login_required
@require_http_methods(["GET", "POST"])
def panel_special_add(request):
    user = request.user
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)
    if request.method == "POST":
        title = (request.POST.get("title_en") or "").strip()
        kind = request.POST.get("kind") or SpecialItem.Kind.SIGNATURE
        brand = get_object_or_404(brands, pk=request.POST.get("brand"))
        outlet = None
        outlet_id = request.POST.get("outlet")
        if outlet_id:
            outlet = get_object_or_404(outlets, pk=outlet_id, brand=brand)
        if not title:
            messages.error(request, "A title is required.")
        else:
            special = SpecialItem(
                brand=brand,
                outlet=outlet,
                kind=kind,
                title_en=title,
                title_ar=(request.POST.get("title_ar") or "").strip(),
                description=(request.POST.get("description") or "").strip(),
                discount_label=(request.POST.get("discount_label") or "").strip(),
                active=True,
            )
            if kind != SpecialItem.Kind.WEEKEND:
                if request.POST.get("original_price"):
                    special.original_price = request.POST.get("original_price")
                if request.POST.get("offer_price"):
                    special.offer_price = request.POST.get("offer_price")
            special.save()
            log_change(user, "SPECIAL_CREATE", special.title_en, brand, outlet)
            messages.success(request, f"Special “{special.title_en}” added.")
            return redirect("panel_specials")

    return render(request, "panel/special_add.html", {
        "nav_active": "specials",
        "is_head_office": is_head_office(user),
        "brands": brands,
        "outlets": outlets.select_related("brand"),
        "kinds": SpecialItem.Kind.choices,
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_menus(request):
    user = request.user
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)
    if request.method == "POST":
        if not is_head_office(user):
            raise PermissionDenied("Only Head Office can change menu sources.")
        brand = get_object_or_404(brands, pk=request.POST.get("brand"))
        outlet = None
        outlet_id = request.POST.get("outlet")
        if outlet_id:
            outlet = get_object_or_404(outlets, pk=outlet_id, brand=brand)
        menu_type = request.POST.get("menu_type") or MenuSource.MenuType.EXTERNAL_URL
        source, _ = MenuSource.objects.update_or_create(
            brand=brand,
            outlet=outlet,
            defaults={
                "menu_type": menu_type,
                "menu_url": (request.POST.get("menu_url") or "").strip(),
                "ordering_url": (request.POST.get("ordering_url") or "").strip(),
                "active": True,
            },
        )
        log_change(user, "MENU_SOURCE", str(source), brand, outlet)
        messages.success(request, "Menu source saved.")
        return redirect("panel_menus")

    sources = MenuSource.objects.filter(
        models_Q_outlet_or_brand(user, outlets)
    ).select_related("brand", "outlet")
    return render(request, "panel/menus_list.html", {
        "nav_active": "menus",
        "is_head_office": is_head_office(user),
        "sources": sources,
        "brands": brands,
        "outlets": outlets.select_related("brand"),
        "menu_types": MenuSource.MenuType.choices,
    })
