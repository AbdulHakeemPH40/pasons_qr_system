"""
Custom Management Panel views (/panel/) — Spec Part D.
Role-based: Head Office vs Outlet Manager.
Full QR lifecycle, Specials, Menus, Vouchers, Auditing.
"""

import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import Brand, ChangeLog, Outlet, OutletManager, QrCode, SmartPage
from apps.core.panel_permissions import (
    can_manage_structure,
    check_outlet_permission,
    is_head_office,
    log_change,
    scoped_brands,
    scoped_outlets,
)
from apps.core.qr_utils import generate_qr_png_bytes, generate_qr_svg_bytes, get_qr_url
from apps.engagement.models import Feedback, Lead
from apps.menu.models import MenuCategory, MenuItem, MenuPage, MenuSource, SpecialItem


@login_required
@require_GET
def panel_dashboard(request):
    user = request.user
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)

    qr_qs = QrCode.objects.filter(outlet__in=outlets, active=True)
    total_scans = sum(qr_qs.values_list("scan_count", flat=True))

    context = {
        "nav_active": "dashboard",
        "is_head_office": is_head_office(user),
        "outlet_count": outlets.count(),
        "brand_count": brands.count(),
        "qr_count": qr_qs.count(),
        "total_scans": total_scans,
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
            logo = request.FILES.get("logo")
            if logo:
                brand.logo = logo
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
        # Structural fields (name/code/city/address/brand) are Head Office only.
        if can_manage_structure(user):
            official_name = (request.POST.get("official_name") or "").strip()
            code = (request.POST.get("code") or "").strip().upper()
            if official_name:
                outlet.official_name = official_name
            if code and code != outlet.code:
                if Outlet.objects.filter(code=code).exclude(pk=outlet.pk).exists():
                    messages.error(request, f"Outlet code {code} is already in use.")
                    return redirect("panel_outlet_edit", pk=outlet.pk)
                outlet.code = code
            outlet.city = (request.POST.get("city") or "").strip()
            outlet.emirate = (request.POST.get("emirate") or "").strip()
            outlet.address = (request.POST.get("address") or "").strip()
            brand_id = request.POST.get("brand")
            if brand_id:
                brand = Brand.objects.filter(pk=brand_id).first()
                if brand:
                    outlet.brand = brand

        # Contact/promotion fields: managers may edit their own branch.
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
        "can_manage_structure": can_manage_structure(user),
        "outlet": outlet,
        "brands": Brand.objects.all().order_by("name_en"),
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
    outlets = scoped_outlets(user)
    if not outlets.exists():
        raise PermissionDenied("You do not have any branch to generate QR codes for.")
    brands = Brand.objects.filter(id__in=outlets.values_list("brand_id", flat=True))

    if request.method == "POST":
        outlet_id = request.POST.get("outlet")
        outlet = get_object_or_404(outlets, pk=outlet_id)
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
        "is_head_office": is_head_office(user),
        "brands": brands,
        "outlets": outlets.select_related("brand"),
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
        brand = get_object_or_404(brands, pk=request.POST.get("brand"))
        outlet = None
        outlet_id = request.POST.get("outlet")
        if outlet_id:
            outlet = get_object_or_404(outlets, pk=outlet_id, brand=brand)
        elif not is_head_office(user):
            raise PermissionDenied(
                "Only Head Office can change the brand-wide menu. "
                "Select your branch to edit its menu."
            )
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


# ---------------------------------------------------------------------------
# Staff users management (Head Office only — higher authority)
# ---------------------------------------------------------------------------

def _user_role_label(user):
    if is_head_office(user):
        return "Head Office"
    profile = getattr(user, "outlet_manager_profile", None)
    if not profile:
        return "No access"
    if profile.role == OutletManager.Role.BRAND:
        return f"Brand Manager · {profile.brand.name_en if profile.brand else '—'}"
    names = ", ".join(profile.outlets.values_list("official_name", flat=True)) or "—"
    return f"Outlet Manager · {names}"


@login_required
@require_GET
def panel_users(request):
    if not is_head_office(request.user):
        raise PermissionDenied("Only Head Office can manage users.")
    users = (
        User.objects.all()
        .select_related("outlet_manager_profile__brand")
        .prefetch_related("outlet_manager_profile__outlets")
        .order_by("username")
    )
    rows = [{"u": u, "role_label": _user_role_label(u)} for u in users]
    return render(request, "panel/users_list.html", {
        "nav_active": "users",
        "is_head_office": True,
        "rows": rows,
    })


def _apply_role_to_user(user, role, brand, outlets):
    """Attach/refresh the manager profile for a non-head-office role."""
    if role == "head_office":
        user.is_staff = True
        user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])
        OutletManager.objects.filter(user=user).delete()
        return
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["is_staff", "is_superuser"])
    profile, _ = OutletManager.objects.get_or_create(user=user)
    if role == "brand_manager":
        profile.role = OutletManager.Role.BRAND
        profile.brand = brand
        profile.outlets.clear()
    else:
        profile.role = OutletManager.Role.OUTLET
        profile.brand = None
        profile.outlets.set(outlets)
    profile.save()


@login_required
@require_http_methods(["GET", "POST"])
def panel_user_add(request):
    if not is_head_office(request.user):
        raise PermissionDenied("Only Head Office can manage users.")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        role = request.POST.get("role") or "outlet_manager"
        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username {username} is already in use.")
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                email=(request.POST.get("email") or "").strip(),
                first_name=(request.POST.get("first_name") or "").strip(),
                last_name=(request.POST.get("last_name") or "").strip(),
            )
            brand = Brand.objects.filter(pk=request.POST.get("brand")).first()
            outlets = Outlet.objects.filter(pk__in=request.POST.getlist("outlets"))
            if role == "brand_manager" and brand is None:
                messages.error(request, "Select a brand for a brand manager.")
                user.delete()
                return redirect("panel_user_add")
            if role == "outlet_manager" and not outlets.exists():
                messages.error(request, "Select at least one branch for an outlet manager.")
                user.delete()
                return redirect("panel_user_add")
            _apply_role_to_user(user, role, brand, list(outlets))
            log_change(user=request.user, action="USER_CREATE",
                       object_repr=f"{username} ({role})",
                       brand=brand if role == "brand_manager" else None)
            messages.success(request, f"User {username} created.")
            return redirect("panel_users")

    return render(request, "panel/user_form.html", {
        "nav_active": "users",
        "is_head_office": True,
        "target": None,
        "brands": Brand.objects.all().order_by("name_en"),
        "outlets": Outlet.objects.select_related("brand").order_by("official_name"),
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_user_edit(request, pk):
    if not is_head_office(request.user):
        raise PermissionDenied("Only Head Office can manage users.")
    target = get_object_or_404(User, pk=pk)
    profile = getattr(target, "outlet_manager_profile", None)

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        if action == "delete":
            if target == request.user:
                messages.error(request, "You cannot delete your own account.")
            else:
                username = target.username
                target.delete()
                log_change(user=request.user, action="USER_DELETE", object_repr=username)
                messages.success(request, f"User {username} deleted.")
            return redirect("panel_users")

        target.first_name = (request.POST.get("first_name") or "").strip()
        target.last_name = (request.POST.get("last_name") or "").strip()
        target.email = (request.POST.get("email") or "").strip()
        if action == "toggle_active":
            if target == request.user:
                messages.error(request, "You cannot deactivate your own account.")
                return redirect("panel_user_edit", pk=target.pk)
            target.is_active = not target.is_active
            target.save()
            log_change(user=request.user, action="USER_ACTIVE" if target.is_active else "USER_DEACTIVATE",
                       object_repr=target.username)
            messages.success(request, f"User {target.username} is now "
                                      f"{'active' if target.is_active else 'inactive'}.")
            return redirect("panel_users")

        role = request.POST.get("role") or "outlet_manager"
        brand = Brand.objects.filter(pk=request.POST.get("brand")).first()
        outlets = Outlet.objects.filter(pk__in=request.POST.getlist("outlets"))
        if role == "brand_manager" and brand is None:
            messages.error(request, "Select a brand for a brand manager.")
        elif role == "outlet_manager" and not outlets.exists():
            messages.error(request, "Select at least one branch for an outlet manager.")
        else:
            target.save()
            _apply_role_to_user(target, role, brand, list(outlets))
            new_password = request.POST.get("password") or ""
            if new_password:
                target.set_password(new_password)
                target.save()
            log_change(user=request.user, action="USER_EDIT", object_repr=f"{target.username} ({role})",
                       brand=brand if role == "brand_manager" else None)
            messages.success(request, f"User {target.username} updated.")
            return redirect("panel_users")

    current_role = "outlet_manager"
    current_brand = None
    current_outlets = []
    if is_head_office(target):
        current_role = "head_office"
    elif profile:
        current_role = "brand_manager" if profile.role == OutletManager.Role.BRAND else "outlet_manager"
        current_brand = profile.brand
        current_outlets = list(profile.outlets.values_list("pk", flat=True))

    return render(request, "panel/user_form.html", {
        "nav_active": "users",
        "is_head_office": True,
        "target": target,
        "current_role": current_role,
        "current_brand": current_brand,
        "current_outlets": current_outlets,
        "brands": Brand.objects.all().order_by("name_en"),
        "outlets": Outlet.objects.select_related("brand").order_by("official_name"),
    })


# ---------------------------------------------------------------------------
# CRM: Leads / Enquiries and Feedback (scoped to the user's branches)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def panel_leads(request):
    user = request.user
    outlets = scoped_outlets(user)
    qs = Lead.objects.filter(
        models_Q_outlet_or_brand(user, outlets)
    ).select_related("brand", "outlet", "source_qr", "assigned_to")

    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    outlet_id = request.GET.get("outlet", "")
    if outlet_id:
        qs = qs.filter(outlet_id=outlet_id)

    context = {
        "nav_active": "leads",
        "is_head_office": is_head_office(user),
        "leads": qs.order_by("-created_at")[:200],
        "statuses": Lead.Status.choices,
        "active_status": status,
        "outlets": outlets.select_related("brand"),
        "active_outlet": outlet_id,
    }
    return render(request, "panel/leads_list.html", context)


@login_required
@require_POST
def panel_lead_update(request, pk):
    user = request.user
    outlets = scoped_outlets(user)
    lead = get_object_or_404(
        Lead.objects.filter(models_Q_outlet_or_brand(user, outlets)), pk=pk
    )
    status = request.POST.get("status")
    if status in dict(Lead.Status.choices):
        lead.status = status
    notes = request.POST.get("notes")
    if notes is not None:
        lead.notes = notes
    lead.save()
    log_change(user, "LEAD_UPDATE", f"{lead.customer_name} → {lead.get_status_display()}",
               lead.brand, lead.outlet)
    messages.success(request, f"Lead for {lead.customer_name} updated.")
    return redirect("panel_leads")


@login_required
@require_GET
def panel_feedback(request):
    user = request.user
    outlets = scoped_outlets(user)
    qs = Feedback.objects.filter(
        models_Q_outlet_or_brand(user, outlets)
    ).select_related("brand", "outlet", "source_qr", "assigned_to")

    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    outlet_id = request.GET.get("outlet", "")
    if outlet_id:
        qs = qs.filter(outlet_id=outlet_id)

    context = {
        "nav_active": "feedback",
        "is_head_office": is_head_office(user),
        "feedback_rows": qs.order_by("-created_at")[:200],
        "statuses": Feedback.Status.choices,
        "active_status": status,
        "outlets": outlets.select_related("brand"),
        "active_outlet": outlet_id,
    }
    return render(request, "panel/feedback_list.html", context)


@login_required
@require_POST
def panel_feedback_update(request, pk):
    user = request.user
    outlets = scoped_outlets(user)
    fb = get_object_or_404(
        Feedback.objects.filter(models_Q_outlet_or_brand(user, outlets)), pk=pk
    )
    status = request.POST.get("status")
    if status in dict(Feedback.Status.choices):
        fb.status = status
    resolution = request.POST.get("resolution")
    if resolution is not None:
        fb.resolution = resolution
    fb.save()
    log_change(user, "FEEDBACK_UPDATE", f"{fb.rating}★ → {fb.get_status_display()}",
               fb.brand, fb.outlet)
    messages.success(request, "Feedback updated.")
    return redirect("panel_feedback")


# ---------------------------------------------------------------------------
# Menu items management (brand items = Head Office; branch items = their manager)
# ---------------------------------------------------------------------------

def _menu_item_q(user, outlets):
    """Menu items in the user's scope: branch items + brand-level base items."""
    return Q(outlet__in=outlets) | (Q(outlet__isnull=True) & Q(brand__in=scoped_brands(user)))


def _check_menu_item_permission(user, item):
    """Brand-level items are structural content — Head Office only."""
    if item.outlet_id is None and not is_head_office(user):
        raise PermissionDenied("Only Head Office can edit brand-level menu items.")
    if item.outlet_id is not None:
        check_outlet_permission(user, item.outlet)


@login_required
@require_GET
def panel_menu_items(request):
    user = request.user
    outlets = scoped_outlets(user)
    items = MenuItem.objects.filter(
        _menu_item_q(user, outlets)
    ).select_related("brand", "outlet", "category")

    outlet_id = request.GET.get("outlet", "")
    if outlet_id:
        items = items.filter(outlet_id=outlet_id)

    context = {
        "nav_active": "menu_items",
        "is_head_office": is_head_office(user),
        "items": items.order_by("category__sort_order", "sort_order", "id")[:300],
        "outlets": outlets.select_related("brand"),
        "active_outlet": outlet_id,
    }
    return render(request, "panel/menu_items_list.html", context)


def _menu_item_form_context(user, item=None):
    outlets = scoped_outlets(user).select_related("brand")
    brands = Brand.objects.filter(id__in=outlets.values_list("brand_id", flat=True))
    categories = MenuCategory.objects.filter(
        Q(brand__in=brands) & (Q(outlet__isnull=True) | Q(outlet__in=outlets))
    ).select_related("brand", "outlet")
    return {
        "nav_active": "menu_items",
        "is_head_office": is_head_office(user),
        "item": item,
        "brands": brands,
        "outlets": outlets,
        "categories": categories,
        "dietary_types": MenuItem.DietaryType.choices,
        "spice_levels": MenuItem.SpiceLevel.choices,
    }


def _menu_item_from_post(request, item, brand, outlet):
    category = get_object_or_404(
        MenuCategory.objects.filter(brand=brand),
        pk=request.POST.get("category"),
    )
    new_category_name = (request.POST.get("new_category") or "").strip()
    if new_category_name:
        category = MenuCategory.objects.create(
            brand=brand, outlet=outlet, name_en=new_category_name
        )
    item.category = category
    item.brand = brand
    item.outlet = outlet
    item.name_en = (request.POST.get("name_en") or "").strip()
    item.name_ar = (request.POST.get("name_ar") or "").strip()
    item.description_en = (request.POST.get("description_en") or "").strip()
    item.regular_price = request.POST.get("regular_price") or 0
    offer_price = (request.POST.get("offer_price") or "").strip()
    item.offer_price = offer_price or None
    item.dietary_type = request.POST.get("dietary_type") or MenuItem.DietaryType.NON_VEG
    item.spice_level = request.POST.get("spice_level") or MenuItem.SpiceLevel.NONE
    item.available = request.POST.get("available") == "on"
    item.featured = request.POST.get("featured") == "on"
    image = request.FILES.get("image")
    if image:
        item.image = image
    item.save()
    return item


@login_required
@require_http_methods(["GET", "POST"])
def panel_menu_item_add(request):
    user = request.user
    outlets = scoped_outlets(user)
    if request.method == "POST":
        brand = get_object_or_404(scoped_brands(user), pk=request.POST.get("brand"))
        outlet = None
        outlet_id = request.POST.get("outlet")
        if outlet_id:
            outlet = get_object_or_404(outlets, pk=outlet_id, brand=brand)
        elif not is_head_office(user):
            raise PermissionDenied("Only Head Office can add brand-level menu items.")
        item = _menu_item_from_post(request, MenuItem(available=True), brand, outlet)
        log_change(user, "MENU_ITEM_CREATE", item.name_en, brand, outlet)
        messages.success(request, f"Menu item “{item.name_en}” added.")
        return redirect("panel_menu_items")

    return render(request, "panel/menu_item_form.html", _menu_item_form_context(user))


@login_required
@require_http_methods(["GET", "POST"])
def panel_menu_item_edit(request, pk):
    user = request.user
    outlets = scoped_outlets(user)
    item = get_object_or_404(
        MenuItem.objects.filter(_menu_item_q(user, outlets)).select_related("brand", "outlet", "category"),
        pk=pk,
    )
    _check_menu_item_permission(user, item)

    if request.method == "POST":
        brand = get_object_or_404(scoped_brands(user), pk=request.POST.get("brand"))
        outlet = item.outlet
        item = _menu_item_from_post(request, item, brand, outlet)
        log_change(user, "MENU_ITEM_EDIT", item.name_en, item.brand, item.outlet)
        messages.success(request, f"Menu item “{item.name_en}” updated.")
        return redirect("panel_menu_items")

    return render(request, "panel/menu_item_form.html", _menu_item_form_context(user, item))


@login_required
@require_POST
def panel_menu_item_toggle(request, pk):
    user = request.user
    outlets = scoped_outlets(user)
    item = get_object_or_404(
        MenuItem.objects.filter(_menu_item_q(user, outlets)), pk=pk
    )
    _check_menu_item_permission(user, item)
    item.available = not item.available
    item.save(update_fields=["available", "updated_at"])
    log_change(user, "MENU_ITEM_TOGGLE", f"{item.name_en} → {'on' if item.available else 'off'}",
               item.brand, item.outlet)
    messages.success(request, f"“{item.name_en}” is now "
                              f"{'available' if item.available else 'unavailable'}.")
    return redirect("panel_menu_items")


@login_required
@require_POST
def panel_menu_item_override(request, pk):
    """Copy a brand-level item into a branch as its outlet override."""
    user = request.user
    outlets = scoped_outlets(user)
    base = get_object_or_404(
        MenuItem.objects.filter(outlet__isnull=True, brand__in=scoped_brands(user)),
        pk=pk,
    )
    outlet = get_object_or_404(outlets, pk=request.POST.get("outlet"), brand=base.brand)
    existing = MenuItem.objects.filter(outlet=outlet, overrides=base).first()
    if existing:
        messages.info(request, f"“{base.name_en}” already has a branch version.")
        return redirect("panel_menu_item_edit", pk=existing.pk)
    override = MenuItem.objects.create(
        category=base.category, brand=base.brand, outlet=outlet, overrides=base,
        name_en=base.name_en, name_ar=base.name_ar, description_en=base.description_en,
        description_ar=base.description_ar, image=base.image,
        regular_price=base.regular_price, offer_price=base.offer_price,
        currency=base.currency, dietary_type=base.dietary_type,
        spice_level=base.spice_level, allergens=base.allergens,
        available=base.available, featured=base.featured, sort_order=base.sort_order,
    )
    log_change(user, "MENU_ITEM_OVERRIDE", base.name_en, base.brand, outlet)
    messages.success(request, f"Branch version of “{base.name_en}” created. Edit it now.")
    return redirect("panel_menu_item_edit", pk=override.pk)
