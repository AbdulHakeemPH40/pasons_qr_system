"""
Template context for the /panel/ shell.

Exposes the signed-in user's role to every panel template so the sidebar can
name the real role, and so no individual view has to remember to pass it. The
values are read from the same helpers the views use, so the sidebar and the
access checks can never disagree.
"""

from apps.core.panel_permissions import is_head_office, role_label, user_capabilities


def panel_context(request):
    """Add 'is_head_office', 'role_label' and 'nav_caps' to panel templates.

    'nav_caps' is the set of panel sections this user may open. The sidebar
    reads it so the links shown and the URLs the gate allows come from one
    source and cannot drift apart.

    Returns an empty dict for anonymous requests, so the login page and any
    other public template are untouched.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {
        "is_head_office": is_head_office(user),
        "role_label": role_label(user),
        "nav_caps": user_capabilities(user),
    }
