"""
Role and scope enforcement for /panel/ (Spec Part D).
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from apps.core.models import Outlet, Brand, OutletManager, ChangeLog


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
