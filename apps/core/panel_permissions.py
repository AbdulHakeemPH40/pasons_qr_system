"""
Role and scope enforcement for /panel/ (Spec Part D).
"""

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from apps.core.models import Outlet, Brand, OutletManager, ChangeLog


# --- capabilities ---------------------------------------------------------
# One key per panel section. A role or a department grants a set of these, and
# both the URL gate (apps.core.middleware.PanelCapabilityMiddleware) and the
# sidebar read the same set, so a hidden link and a blocked URL cannot
# disagree.
CAP_DASHBOARD = "dashboard"
CAP_BRANDS = "brands"
CAP_OUTLETS = "outlets"
CAP_QRCODES = "qrcodes"
CAP_SPECIALS = "specials"
CAP_MENUS = "menus"
CAP_LEADS = "leads"
CAP_FEEDBACK = "feedback"
CAP_ANALYTICS = "analytics"
CAP_USERS = "users"
CAP_CHANGELOG = "changelog"

# Branch managers run their assigned outlets. They do not create staff or
# change platform structure.
OUTLET_MANAGER_CAPABILITIES = frozenset({
    CAP_DASHBOARD, CAP_OUTLETS, CAP_QRCODES, CAP_SPECIALS, CAP_MENUS,
    CAP_LEADS, CAP_FEEDBACK, CAP_ANALYTICS, CAP_CHANGELOG,
})

# Brand managers use the same dashboard, plus Users, so they can create the
# branch managers for their own brand. Brands and branches stay with Django
# admin / Head Office.
BRAND_MANAGER_CAPABILITIES = OUTLET_MANAGER_CAPABILITIES | frozenset({CAP_USERS})

# Kept so older imports still name the branch-manager set.
MANAGER_CAPABILITIES = OUTLET_MANAGER_CAPABILITIES

# What each Head Office department may open, keyed by Department.code. An
# unknown code grants nothing (fail closed), so adding a department row
# without adding it here restricts rather than over-grants.
DEPARTMENT_CAPABILITIES = {
    "MARKETING": frozenset({
        CAP_DASHBOARD, CAP_SPECIALS, CAP_QRCODES, CAP_ANALYTICS,
        CAP_LEADS, CAP_FEEDBACK,
    }),
    "OPERATIONS": frozenset({
        CAP_DASHBOARD, CAP_OUTLETS, CAP_QRCODES, CAP_MENUS,
        CAP_SPECIALS, CAP_LEADS,
    }),
    "FINANCE": frozenset({
        CAP_DASHBOARD, CAP_ANALYTICS,
    }),
    "HR": frozenset({
        CAP_DASHBOARD, CAP_USERS, CAP_CHANGELOG,
    }),
    "IT": frozenset({
        CAP_DASHBOARD, CAP_BRANDS, CAP_OUTLETS, CAP_QRCODES, CAP_SPECIALS,
        CAP_MENUS, CAP_LEADS, CAP_FEEDBACK, CAP_ANALYTICS, CAP_USERS,
        CAP_CHANGELOG,
    }),
}

# Head Office with no department keeps every section (today's behaviour).
ALL_CAPABILITIES = frozenset({
    CAP_DASHBOARD, CAP_BRANDS, CAP_OUTLETS, CAP_QRCODES, CAP_SPECIALS,
    CAP_MENUS, CAP_LEADS, CAP_FEEDBACK, CAP_ANALYTICS, CAP_USERS,
    CAP_CHANGELOG,
})


def is_head_office(user):
    """Head office: is_superuser, is_staff, or member of 'Head office' group."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff or user.groups.filter(name="Head office").exists()


def is_brand_manager(user):
    """Brand manager: manages all outlets of one brand (never structure changes)."""
    if not user.is_authenticated or is_head_office(user):
        return False
    profile = getattr(user, "outlet_manager_profile", None)
    return bool(profile and profile.role == profile.Role.BRAND)


def can_manage_structure(user):
    """
    Creating / editing / modifying brands and branches is reserved for
    Head Office (higher authority). Managers never get this.
    """
    return is_head_office(user)


def role_label(user):
    """Human label for the sidebar and the Users list.

    Returns 'Head Office', 'Brand Manager (brand)', 'Outlet Manager
    (branches)', or 'No access' when the account holds no role. Lives here
    rather than in the views so templates can read it through a context
    processor without importing the views module (which would be circular).
    """
    if not user.is_authenticated:
        return ""
    if is_head_office(user):
        profile = getattr(user, "outlet_manager_profile", None)
        department = getattr(profile, "department", None) if profile else None
        if department is not None:
            return f"Head Office \u00b7 {department.name_en}"
        return "Head Office"
    profile = getattr(user, "outlet_manager_profile", None)
    if not profile:
        return "No access"
    if profile.role == OutletManager.Role.BRAND:
        if profile.brand is None:
            return "Brand Manager \u00b7 All brands"
        return f"Brand Manager \u00b7 {profile.brand.name_en}"
    names = ", ".join(profile.outlets.values_list("official_name", flat=True))
    return f"Outlet Manager \u00b7 {names or 'no branches assigned'}"


def apply_role_to_user(user, role, brand, outlets, department=None):
    """Attach or refresh the manager profile for this role.

    Lives here, beside the scope rules it feeds, so the Users panel and the
    ``seed_staff`` command cannot drift apart: both write a profile through
    this one function, so a seeded account behaves exactly like one created
    in the panel.

    Head Office keeps a profile row even though scoping ignores it (see
    ``scoped_outlets``, which returns everything for head office): the row is
    where the department is stored. A department on a manager role is cleared,
    because departments apply to Head Office staff only.
    """
    user.is_staff = role == "head_office"
    user.is_superuser = False
    user.save(update_fields=["is_staff", "is_superuser"])

    profile, _ = OutletManager.objects.get_or_create(user=user)
    if role == "head_office":
        # Role fields do not matter for head office, but clear them so the
        # profile row stays honest about what it represents.
        profile.role = OutletManager.Role.OUTLET
        profile.brand = None
        profile.outlets.clear()
        profile.department = department
    elif role == "brand_manager":
        # A brand means one brand. No brand means every brand, same dashboard.
        profile.role = OutletManager.Role.BRAND
        profile.brand = brand
        profile.outlets.clear()
        profile.department = None
    else:
        profile.role = OutletManager.Role.OUTLET
        profile.brand = None
        profile.outlets.set(outlets)
        profile.department = None
    profile.save()


def user_capabilities(user):
    """The panel sections this user may open.

    - Head Office with an active department: that department's set.
    - Head Office with no department: every section (unchanged behaviour).
    - Brand or branch manager: the manager set.
    - Anyone else (no profile): nothing at all.
    """
    if not user.is_authenticated:
        return frozenset()
    if is_head_office(user):
        profile = getattr(user, "outlet_manager_profile", None)
        department = getattr(profile, "department", None) if profile else None
        if department is not None and department.is_active:
            caps = DEPARTMENT_CAPABILITIES.get(department.code.upper())
            if caps is None:
                # Unknown code: grant nothing, but keep the dashboard reachable
                # so signing in still lands on a page rather than a 403.
                return frozenset({CAP_DASHBOARD})
            return caps
        return ALL_CAPABILITIES
    profile = getattr(user, "outlet_manager_profile", None)
    if profile is not None:
        if profile.role == OutletManager.Role.BRAND:
            return BRAND_MANAGER_CAPABILITIES
        return OUTLET_MANAGER_CAPABILITIES
    # Authenticated but holding no role: the dashboard stays reachable so
    # signing in lands on a page rather than a 403. It will simply show
    # nothing, because their scope is empty.
    return frozenset({CAP_DASHBOARD})


def require_capability(user, capability):
    """Raise PermissionDenied when the user's role or department lacks this section."""
    if capability not in user_capabilities(user):
        raise PermissionDenied("Your role does not include this section.")


def scoped_outlets(user):
    """
    Returns queryset of Outlets that the user is authorized to manage.
    Head office: all outlets.
    Brand manager: all outlets of the assigned brand.
    Outlet manager: only assigned outlets in OutletManager profile.
    Others: empty queryset.
    """
    if not user.is_authenticated:
        return Outlet.objects.none()
    if is_head_office(user):
        return Outlet.objects.all()

    profile = getattr(user, "outlet_manager_profile", None)
    if profile:
        return profile.managed_outlets()
    return Outlet.objects.none()


def scoped_brands(user):
    """
    Returns queryset of Brands visible to user.
    Head office: all brands.
    Outlet manager: brands owning their scoped outlets.
    """
    if not user.is_authenticated:
        return Brand.objects.none()
    if is_head_office(user):
        return Brand.objects.all()

    outlets = scoped_outlets(user)
    brand_ids = outlets.values_list("brand_id", flat=True).distinct()
    return Brand.objects.filter(id__in=brand_ids)


def check_outlet_permission(user, outlet):
    """Raises PermissionDenied if user cannot manage this outlet."""
    if not is_head_office(user):
        allowed = scoped_outlets(user).filter(pk=outlet.pk).exists()
        if not allowed:
            raise PermissionDenied("You do not have access to this outlet.")


def brand_for_manager(user):
    """The one brand a brand manager may staff, or None.

    An empty brand means every brand (the all-brands manager). Head Office
    and branch managers return None here; callers check the role first.
    """
    profile = getattr(user, "outlet_manager_profile", None)
    if not profile or profile.role != OutletManager.Role.BRAND:
        return None
    return profile.brand


def can_manage_staff(user):
    """Django admin / Head Office, or a brand manager on the custom dashboard."""
    return is_head_office(user) or is_brand_manager(user)


def staff_rows_for(user):
    """Accounts this person may see on the Users page.

    Head Office sees everyone. A brand manager sees only the branch managers
    of their brand, never other brands, never Head Office, never themselves
    as a peer brand account.
    """
    users = (
        User.objects.all()
        .select_related("outlet_manager_profile__brand", "outlet_manager_profile__department")
        .prefetch_related("outlet_manager_profile__outlets")
        .order_by("username")
    )
    if is_head_office(user):
        return users
    brand = brand_for_manager(user)
    if brand is None and is_brand_manager(user):
        return users.filter(
            outlet_manager_profile__role=OutletManager.Role.OUTLET,
        )
    if brand is None:
        return User.objects.none()
    return users.filter(
        outlet_manager_profile__role=OutletManager.Role.OUTLET,
        outlet_manager_profile__outlets__brand=brand,
    ).distinct()


def actor_may_edit_user(actor, target):
    """True when actor may open or change this account.

    A brand manager may only touch branch managers whose branches are all
    inside their brand. They cannot promote someone, edit Head Office, edit
    another brand manager, or reach a branch of another brand.
    """
    if not actor.is_authenticated or actor.pk == getattr(target, "pk", None):
        return False
    if is_head_office(actor):
        return True
    if not is_brand_manager(actor):
        return False
    if is_head_office(target):
        return False
    profile = getattr(target, "outlet_manager_profile", None)
    if profile is None or profile.role != OutletManager.Role.OUTLET:
        return False
    brand = brand_for_manager(actor)
    outlets = profile.outlets.all()
    if not outlets.exists():
        return False
    if brand is None:
        return True
    return not outlets.exclude(brand=brand).exists()


def log_change(user, action, object_repr, brand=None, outlet=None, details=None):
    """Record an audit trail event in ChangeLog."""
    ChangeLog.objects.create(
        user=user if user.is_authenticated else None,
        brand=brand,
        outlet=outlet,
        action=action,
        object_repr=str(object_repr)[:200],
        details=details or {}
    )
