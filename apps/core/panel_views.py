"""
Custom Management Panel views (/panel/) — Spec Part D.
Role-based: Head Office vs Outlet Manager.
Full QR lifecycle, Specials, Menus, Vouchers, Auditing.
"""

import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import Brand, ChangeLog, Department, Outlet, OutletManager, QrCode, SmartPage
from apps.core.panel_permissions import (
    actor_may_edit_user,
    apply_role_to_user,
    brand_for_manager,
    can_manage_staff,
    can_manage_structure,
    check_outlet_permission,
    is_brand_manager,
    is_head_office,
    log_change,
    role_label,
    scoped_brands,
    scoped_outlets,
    staff_rows_for,
)
from apps.core.qr_utils import generate_qr_png_bytes, generate_qr_svg_bytes, get_qr_url
from apps.engagement.models import Feedback, Lead
from apps.menu.models import MenuCategory, MenuItem, MenuPage, MenuSource, SpecialItem
from apps.menu.top_picks import TOP_DRINK_CATEGORY, TOP_FOOD_CATEGORY


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
                whatsapp=(request.POST.get("whatsapp") or "").strip(),
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
        outlet.whatsapp = request.POST.get("whatsapp", outlet.whatsapp)
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


BRANCH_QR_SOURCE = "branch"


def branch_qr_name(outlet):
    """One printed code per branch. The name has no table number."""
    outlet_code = outlet.code.split("-", 1)[-1]
    return f"{outlet.brand.code}-{outlet_code}-BRANCH-01"


def active_branch_qr(outlet):
    return (
        QrCode.objects.filter(outlet=outlet, active=True)
        .order_by("id")
        .first()
    )


@login_required
@require_GET
def panel_qrcodes(request):
    user = request.user
    outlets = scoped_outlets(user).select_related("brand").order_by("brand__name_en", "official_name")
    codes = {
        qr.outlet_id: qr
        for qr in QrCode.objects.filter(outlet__in=outlets, active=True)
        .select_related("brand", "outlet")
        .order_by("id")
    }
    rows = [{"outlet": outlet, "qr": codes.get(outlet.id)} for outlet in outlets]
    context = {
        "nav_active": "qrcodes",
        "is_head_office": is_head_office(user),
        "rows": rows,
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
        existing = active_branch_qr(outlet)
        if existing is not None:
            messages.info(
                request,
                f"{outlet.official_name} already has its QR code. Print that one for every table.",
            )
            return redirect("panel_qrcodes")

        dest_page = SmartPage.objects.filter(brand=outlet.brand, outlet=outlet).first()
        if not dest_page:
            dest_page = SmartPage.objects.filter(brand=outlet.brand, outlet__isnull=True).first()
        if dest_page is None:
            messages.error(request, "This branch has no page yet, so a QR code cannot be made.")
            return redirect("panel_qr_generate")

        qr = QrCode.objects.create(
            brand=outlet.brand,
            outlet=outlet,
            destination_page=dest_page,
            source_type=BRANCH_QR_SOURCE,
            label=outlet.official_name,
            qr_code_name=branch_qr_name(outlet),
            redirect_key=secrets.token_urlsafe(9),
        )

        log_change(user, "QR_GENERATE", qr.qr_code_name, outlet.brand, outlet)
        messages.success(
            request,
            f"QR code for {outlet.official_name} is ready. Print it and place the same card on every table.",
        )
        return redirect("panel_qrcodes")

    context = {
        "nav_active": "qrcodes",
        "is_head_office": is_head_office(user),
        "brands": brands,
        "outlets": outlets.select_related("brand"),
        "selected_outlet": request.GET.get("outlet", ""),
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
    """A branch has one printed code. Replacing it would break the cards already on the tables."""
    get_object_or_404(QrCode, pk=pk)
    messages.info(
        request,
        "This branch already has its QR code. Print the same card for every table.",
    )
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


def _special_form_context(user):
    outlets = scoped_outlets(user)
    brands = scoped_brands(user)
    return outlets, brands


@login_required
@require_http_methods(["GET", "POST"])
def panel_special_add(request):
    """Create one promo card (photo upload, optional price/offer)."""
    from apps.menu.forms import SpecialItemForm

    user = request.user
    outlets, brands = _special_form_context(user)
    if request.method == "POST":
        # Cross-scope submissions 404 instead of leaking a validation error.
        outlet_id = request.POST.get("outlet")
        if outlet_id and not outlets.filter(pk=outlet_id).exists():
            raise Http404("Outlet is out of scope.")
    form = SpecialItemForm(
        request.POST or None, request.FILES or None,
        brands=brands, outlets=outlets.select_related("brand"),
    )
    if request.method == "POST" and form.is_valid():
        special = form.save()
        log_change(user, "SPECIAL_CREATE", special.title_en, special.brand, special.outlet)
        messages.success(request, f"Special “{special.title_en}” added.")
        return redirect("panel_specials")

    return render(request, "panel/special_form.html", {
        "nav_active": "specials",
        "is_head_office": is_head_office(user),
        "form": form,
        "mode": "add",
        "special": None,
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_special_edit(request, pk):
    """Update one promo card — staff refresh cards dynamically as needed."""
    from apps.menu.forms import SpecialItemForm

    user = request.user
    outlets, brands = _special_form_context(user)
    special = get_object_or_404(
        SpecialItem.objects.filter(models_Q_outlet_or_brand(user, outlets)), pk=pk
    )
    form = SpecialItemForm(
        request.POST or None, request.FILES or None,
        instance=special, brands=brands, outlets=outlets.select_related("brand"),
    )
    if request.method == "POST" and form.is_valid():
        special = form.save()
        log_change(user, "SPECIAL_UPDATE", special.title_en, special.brand, special.outlet)
        messages.success(request, f"Special “{special.title_en}” updated.")
        return redirect("panel_specials")

    return render(request, "panel/special_form.html", {
        "nav_active": "specials",
        "is_head_office": is_head_office(user),
        "form": form,
        "mode": "edit",
        "special": special,
    })


@login_required
@require_POST
def panel_special_toggle(request, pk):
    """Publish / unpublish a promo card without deleting it."""
    user = request.user
    outlets = scoped_outlets(user)
    special = get_object_or_404(
        SpecialItem.objects.filter(models_Q_outlet_or_brand(user, outlets)), pk=pk
    )
    special.active = not special.active
    special.save(update_fields=["active", "updated_at"])
    log_change(
        user,
        "SPECIAL_ACTIVE" if special.active else "SPECIAL_HIDDEN",
        special.title_en, special.brand, special.outlet,
    )
    state = "live" if special.active else "hidden"
    messages.success(request, f"Special “{special.title_en}” is now {state}.")
    return redirect("panel_specials")


def _menu_pdf_or_error(upload):
    """A menu file must be a PDF. Returns an error sentence, or None."""
    if upload is None:
        return None
    name = (upload.name or "").lower()
    content_type = (getattr(upload, "content_type", "") or "").lower()
    if not name.endswith(".pdf") or (
        content_type and content_type not in ("application/pdf", "application/x-pdf")
    ):
        return "The menu file must be a PDF document."
    if upload.size > 20 * 1024 * 1024:
        return "That PDF is larger than 20 MB. Upload a smaller file."
    return None


def _menu_source_for(user, pk):
    """The one menu row this person may change, or 404 if it is out of scope."""
    outlets = scoped_outlets(user)
    return get_object_or_404(
        MenuSource.objects.filter(models_Q_outlet_or_brand(user, outlets)),
        pk=pk,
    )


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
        elif not (is_head_office(user) or is_brand_manager(user)):
            raise PermissionDenied(
                "A branch manager can change the menu for their own branches. "
                "The brand-wide menu is set by the brand manager."
            )
        upload = request.FILES.get("menu_file")
        error = _menu_pdf_or_error(upload)
        if error:
            messages.error(request, error)
            return redirect("panel_menus")
        if not upload:
            messages.error(request, "Choose a PDF to add.")
            return redirect("panel_menus")
        source, created = MenuSource.objects.update_or_create(
            brand=brand,
            outlet=outlet,
            defaults={"menu_type": MenuSource.MenuType.PDF, "active": True},
        )
        if source.menu_file:
            source.menu_file.delete(save=False)
        source.menu_file = upload
        source.menu_type = MenuSource.MenuType.PDF
        source.active = True
        source.save(update_fields=["menu_file", "menu_type", "active", "updated_at"])
        log_change(user, "MENU_PDF", str(source), brand, outlet)
        where = outlet.official_name if outlet else brand.name_en
        verb = "added" if created else "replaced"
        messages.success(request, f"Menu PDF {verb} for {where}.")
        return redirect("panel_menus")

    sources = MenuSource.objects.filter(
        models_Q_outlet_or_brand(user, outlets)
    ).select_related("brand", "outlet")
    return render(request, "panel/menus_list.html", {
        "nav_active": "menus",
        "can_set_brand_pdf": is_head_office(user) or is_brand_manager(user),
        "sources": sources,
        "brands": brands,
        "outlets": outlets.select_related("brand"),
    })


@login_required
@require_POST
def panel_menu_pdf_replace(request, pk):
    """Swap the PDF on a row this person already covers. The old file is deleted."""
    source = _menu_source_for(request.user, pk)
    upload = request.FILES.get("menu_file")
    error = _menu_pdf_or_error(upload)
    if error or not upload:
        messages.error(request, error or "Choose a PDF to replace the current one.")
        return redirect("panel_menus")
    if source.menu_file:
        source.menu_file.delete(save=False)
    source.menu_file = upload
    source.menu_type = MenuSource.MenuType.PDF
    source.active = True
    source.save(update_fields=["menu_file", "menu_type", "active", "updated_at"])
    log_change(request.user, "MENU_PDF", str(source), source.brand, source.outlet)
    where = source.outlet.official_name if source.outlet else source.brand.name_en
    messages.success(request, f"Menu PDF replaced for {where}.")
    return redirect("panel_menus")


@login_required
@require_POST
def panel_menu_pdf_delete(request, pk):
    """Remove a menu row and its file. Guests then fall back to the brand PDF."""
    source = _menu_source_for(request.user, pk)
    where = source.outlet.official_name if source.outlet else source.brand.name_en
    if source.menu_file:
        source.menu_file.delete(save=False)
    log_change(request.user, "MENU_PDF_REMOVED", str(source), source.brand, source.outlet)
    source.delete()
    messages.success(request, f"Menu PDF removed for {where}.")
    return redirect("panel_menus")


# ---------------------------------------------------------------------------
# Staff users
# Django admin / Head Office creates brand users.
# A brand user creates branch managers for their own brand from this dashboard.
# A branch manager never opens this section.
# ---------------------------------------------------------------------------

def _require_staff_manager(user):
    if not can_manage_staff(user):
        raise PermissionDenied("Only a brand manager can assign branch users.")


def _outlets_for_staff_form(user):
    """Branches this person may assign. A brand user cannot leave their brand."""
    if is_head_office(user):
        return Outlet.objects.select_related("brand").order_by("official_name")
    return scoped_outlets(user).select_related("brand").order_by("official_name")


def _clean_assigned_outlets(user, posted_ids):
    """Keep only branches the actor may assign. Drop anything outside scope."""
    allowed = _outlets_for_staff_form(user)
    return allowed.filter(pk__in=posted_ids)


def _password_error(password, user=None):
    """None when the password meets the project rules, otherwise the reason.

    Django's validators are the same rules the admin uses. The custom
    dashboard used to accept any string, including a one-character password.
    """
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


@login_required
@require_GET
def panel_users(request):
    _require_staff_manager(request.user)
    users = staff_rows_for(request.user)
    rows = [{"u": u, "role_label": role_label(u)} for u in users]
    return render(request, "panel/users_list.html", {
        "nav_active": "users",
        "is_head_office": is_head_office(request.user),
        "is_brand_manager": is_brand_manager(request.user),
        "rows": rows,
    })


def _email_taken(email, exclude_pk=None):
    """True when another account already uses this email (case-insensitive).

    auth.User.email is not unique in Django, so duplicates are possible at the
    database level. The superuser may sign in with an email, so a shared
    address would make that login ambiguous. This keeps one address tied to
    one account. Brand and branch users do not sign in with email.
    """
    email = (email or "").strip()
    if not email:
        return False
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


@login_required
@require_http_methods(["GET", "POST"])
def panel_user_add(request):
    _require_staff_manager(request.user)
    actor_is_brand = is_brand_manager(request.user)

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        email = (request.POST.get("email") or "").strip()
        role = request.POST.get("role") or "outlet_manager"
        # A brand user may only create branch managers. Brand users themselves
        # are created by Django admin / Head Office.
        if actor_is_brand:
            role = "outlet_manager"
        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif (password_error := _password_error(password)) is not None:
            messages.error(request, password_error)
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username {username} is already in use.")
        elif email and _email_taken(email):
            messages.error(request, f"Email {email} is already used by another account.")
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                first_name=(request.POST.get("first_name") or "").strip(),
                last_name=(request.POST.get("last_name") or "").strip(),
            )
            brand = None if actor_is_brand else Brand.objects.filter(
                pk=request.POST.get("brand")
            ).first()
            outlets = _clean_assigned_outlets(request.user, request.POST.getlist("outlets"))
            department = None if actor_is_brand else Department.objects.filter(
                pk=request.POST.get("department")
            ).first()
            if role == "outlet_manager" and not outlets.exists():
                messages.error(request, "Select at least one branch for a branch manager.")
                user.delete()
                return redirect("panel_user_add")
            if role == "brand_manager" and not brand:
                messages.error(request, "Select the brand this brand user will manage.")
                user.delete()
                return redirect("panel_user_add")
            apply_role_to_user(user, role, brand, list(outlets), department)
            log_change(user=request.user, action="USER_CREATE",
                       object_repr=f"{username} ({role})",
                       brand=brand if role == "brand_manager" else brand_for_manager(request.user))
            messages.success(request, f"User {username} created.")
            return redirect("panel_users")

    own_brand = brand_for_manager(request.user)
    return render(request, "panel/user_form.html", {
        "nav_active": "users",
        "is_head_office": is_head_office(request.user),
        "is_brand_manager": actor_is_brand,
        "target": None,
        "brands": Brand.objects.all().order_by("name_en"),
        "outlets": _outlets_for_staff_form(request.user),
        "departments": Department.objects.filter(is_active=True).order_by("name_en"),
        "locked_brand": own_brand,
    })


@login_required
@require_http_methods(["GET", "POST"])
def panel_user_edit(request, pk):
    _require_staff_manager(request.user)
    target = get_object_or_404(User, pk=pk)
    if not actor_may_edit_user(request.user, target):
        raise PermissionDenied("You can only manage branch users of your own brand.")
    profile = getattr(target, "outlet_manager_profile", None)
    actor_is_brand = is_brand_manager(request.user)

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
        # The form always posts the email. Only overwrite it when the key is
        # present, so a partial POST cannot silently blank a login address.
        if "email" in request.POST:
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
        if actor_is_brand:
            role = "outlet_manager"
        brand = None if actor_is_brand else Brand.objects.filter(pk=request.POST.get("brand")).first()
        outlets = _clean_assigned_outlets(request.user, request.POST.getlist("outlets"))
        department = None if actor_is_brand else Department.objects.filter(
            pk=request.POST.get("department")
        ).first()
        if target.email and _email_taken(target.email, exclude_pk=target.pk):
            messages.error(request, f"Email {target.email} is already used by another account.")
        elif role == "outlet_manager" and not outlets.exists():
            messages.error(request, "Select at least one branch for an outlet manager.")
        else:
            target.save()
            apply_role_to_user(target, role, brand, list(outlets), department)
            new_password = request.POST.get("password") or ""
            if new_password:
                password_error = _password_error(new_password, user=target)
                if password_error:
                    messages.error(request, password_error)
                    return redirect("panel_user_edit", pk=target.pk)
                target.set_password(new_password)
                target.save()
            log_change(user=request.user, action="USER_EDIT", object_repr=f"{target.username} ({role})",
                       brand=brand if role == "brand_manager" else None)
            messages.success(request, f"User {target.username} updated.")
            return redirect("panel_users")

    current_role = "outlet_manager"
    current_brand = None
    current_outlets = []
    current_department = getattr(profile, "department", None)
    if is_head_office(target):
        current_role = "head_office"
    elif profile:
        current_role = "brand_manager" if profile.role == OutletManager.Role.BRAND else "outlet_manager"
        current_brand = profile.brand
        current_outlets = list(profile.outlets.values_list("pk", flat=True))

    return render(request, "panel/user_form.html", {
        "nav_active": "users",
        "is_head_office": is_head_office(request.user),
        "is_brand_manager": actor_is_brand,
        "target": target,
        "current_role": current_role,
        "current_brand": current_brand,
        "current_outlets": current_outlets,
        "current_department": current_department,
        "brands": Brand.objects.all().order_by("name_en"),
        "outlets": _outlets_for_staff_form(request.user),
        "departments": Department.objects.filter(is_active=True).order_by("name_en"),
        "locked_brand": brand_for_manager(request.user),
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
    """
    The guest cards are brand lists, not a per-branch dump. The panel shows
    those brand rows. A branch copy (photo or price for one branch) stays
    visible so the manager who made it can still edit it.
    """
    brands = scoped_brands(user)
    return (
        Q(outlet__isnull=True, brand__in=brands)
        | Q(outlet__in=outlets)
    )


def _check_menu_item_permission(user, item):
    """Brand dishes belong to Head Office and the brand manager.

    A branch manager can upload a photo, but cannot change the brand dish
    itself. A branch copy stays with the manager of that branch.
    """
    if item.outlet_id is None and not (is_head_office(user) or is_brand_manager(user)):
        raise PermissionDenied("Only Head Office or a brand manager can edit a brand dish.")
    if item.outlet_id is not None:
        check_outlet_permission(user, item.outlet)


@login_required
@require_GET
def panel_menu_items(request):
    user = request.user
    outlets = scoped_outlets(user)
    items = MenuItem.objects.filter(
        _menu_item_q(user, outlets),
        outlet__isnull=True,
        category__name_en__in=(TOP_FOOD_CATEGORY, TOP_DRINK_CATEGORY),
    ).select_related("brand", "outlet", "category")

    brand_id = request.GET.get("brand", "")
    brands = scoped_brands(user).order_by("name_en")
    if brand_id:
        items = items.filter(brand_id=brand_id)

    ordered = list(items.order_by("brand__name_en", "category__sort_order", "sort_order", "id"))
    groups = []
    by_brand = {}
    for item in ordered:
        group = by_brand.get(item.brand_id)
        if group is None:
            group = {"brand": item.brand, "food": [], "drinks": [], "other": []}
            by_brand[item.brand_id] = group
            groups.append(group)
        if item.category.name_en == TOP_FOOD_CATEGORY:
            group["food"].append(item)
        elif item.category.name_en == TOP_DRINK_CATEGORY:
            group["drinks"].append(item)
        else:
            group["other"].append(item)

    context = {
        "nav_active": "menu_items",
        "is_head_office": is_head_office(user),
        "can_edit": is_head_office(user) or is_brand_manager(user),
        "groups": groups,
        "item_count": len(ordered),
        "brands": brands,
        "active_brand": brand_id,
        "outlets": outlets.select_related("brand"),
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
    item.description_ar = (request.POST.get("description_ar") or "").strip()
    # Blank means no price. The guest card stays nameless of money until
    # a manager types one. A bad value is a form error, not a 500.
    raw_price = (request.POST.get("regular_price") or "").strip()
    try:
        item.regular_price = raw_price or 0
    except (TypeError, ValueError, ValidationError):
        item.regular_price = 0
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
        elif not (is_head_office(user) or is_brand_manager(user)):
            raise PermissionDenied("Only Head Office or a brand manager can add a brand dish.")
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
    # Client 2026-10-15: outlet managers may upload or replace the photo on
    # brand-level items too (the Top 10 lists are brand-level rows). Structure
    # (name, price, category, delete) stays Head Office only, so for managers
    # this form degrades to a photo-only editor and only the image is written.
    photo_only = item.outlet_id is None and not (
        is_head_office(user) or is_brand_manager(user)
    )
    if not photo_only:
        _check_menu_item_permission(user, item)

    if request.method == "POST":
        if photo_only:
            image = request.FILES.get("image")
            if image:
                item.image = image
                item.save(update_fields=["image", "updated_at"])
                log_change(user, "MENU_ITEM_PHOTO", item.name_en, item.brand, None)
                messages.success(request, f"Photo updated for “{item.name_en}”.")
            else:
                messages.error(request, "Choose a photo to upload.")
            return redirect("panel_menu_items")
        brand = get_object_or_404(scoped_brands(user), pk=request.POST.get("brand"))
        outlet = item.outlet
        item = _menu_item_from_post(request, item, brand, outlet)
        log_change(user, "MENU_ITEM_EDIT", item.name_en, item.brand, item.outlet)
        messages.success(request, f"Menu item “{item.name_en}” updated.")
        return redirect("panel_menu_items")

    context = _menu_item_form_context(user, item)
    context["photo_only"] = photo_only
    return render(request, "panel/menu_item_form.html", context)


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
def panel_menu_item_delete(request, pk):
    """Remove a menu item (staff-managed menus: delete is a normal operation)."""
    user = request.user
    outlets = scoped_outlets(user)
    item = get_object_or_404(
        MenuItem.objects.filter(_menu_item_q(user, outlets)), pk=pk
    )
    _check_menu_item_permission(user, item)
    name = item.name_en
    log_change(user, "MENU_ITEM_DELETE", name, item.brand, item.outlet)
    item.delete()
    messages.success(request, f"“{name}” removed from the menu.")
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
