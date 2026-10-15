"""
Capability gate for the staff panel.

A department limits which sections a Head Office user may open. That rule is
applied here, in one place, instead of trusting roughly thirty views to each
remember it: the resolved view name selects a capability and
``require_capability`` raises ``PermissionDenied`` when the user's role or
department does not include it.

The table is keyed by view name so ``PanelCapabilityCoverageTests`` can walk
the URL configuration and fail when a panel view is missing from the map. A
new panel view therefore cannot silently ship ungated.
"""

from django.urls import Resolver404, resolve

from apps.core.panel_permissions import require_capability

# Login and logout must stay reachable before the user holds any role.
# These are the real URL names in config/urls.py (name="login" / name="logout").
CAPABILITY_EXEMPT_VIEWS = frozenset({"login", "logout"})

# Resolved view name -> capability key. Keep in step with config/urls.py;
# PanelCapabilityCoverageTests enforces that.
VIEW_CAPABILITIES = {
    "panel_dashboard": "dashboard",
    "panel_brands": "brands",
    "panel_brand_add": "brands",
    "panel_brand_edit": "brands",
    "panel_outlets": "outlets",
    "panel_outlet_add": "outlets",
    "panel_outlet_edit": "outlets",
    "panel_qrcodes": "qrcodes",
    "panel_qr_generate": "qrcodes",
    "panel_qr_download": "qrcodes",
    "panel_qr_print": "qrcodes",
    "panel_qr_regenerate": "qrcodes",
    "panel_specials": "specials",
    "panel_special_add": "specials",
    "panel_special_edit": "specials",
    "panel_special_toggle": "specials",
    "panel_menus": "menus",
    "panel_menu_pdf_replace": "menus",
    "panel_menu_pdf_delete": "menus",
    "panel_menu_items": "menus",
    "panel_menu_item_add": "menus",
    "panel_menu_item_edit": "menus",
    "panel_menu_item_toggle": "menus",
    "panel_menu_item_delete": "menus",
    "panel_menu_item_override": "menus",
    "panel_leads": "leads",
    "panel_lead_update": "leads",
    "panel_feedback": "feedback",
    "panel_feedback_update": "feedback",
    "panel_users": "users",
    "panel_user_add": "users",
    "panel_user_edit": "users",
    "panel_analytics": "analytics",
    "panel_changelog": "changelog",
}

# Kept so a future staff route outside /panel/ can declare its own gate
# without being flagged as ungated. Empty today: /dashboard/ redirects into
# the panel, and panel_analytics is gated with the rest of the shell.
INLINE_GATED_VIEWS = {}


class PanelCapabilityMiddleware:
    """Deny a panel view when the user's role or department lacks it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            capability = VIEW_CAPABILITIES.get(self._view_name(request))
            if capability is not None:
                require_capability(user, capability)
        return self.get_response(request)

    @staticmethod
    def _view_name(request):
        try:
            return resolve(request.path_info).view_name
        except Resolver404:
            return None
