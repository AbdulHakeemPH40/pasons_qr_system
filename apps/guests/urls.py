"""
Guest identity routes.

Mounted from config/urls.py next to the other /q/<key>/ routes so the guest
flow keeps one URL shape. The paths are registered by full pattern, so
/q/<key>/instagram/ (the tap-tracked redirect to Instagram) and
/q/<key>/instagram/thanks/ (this app's fallback page) cannot collide.
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "q/<slug:key>/instagram/thanks/",
        views.instagram_thanks,
        name="guest_instagram_thanks",
    ),
    path(
        "q/<slug:key>/identity/",
        views.identity_submit,
        name="guest_identity_submit",
    ),
    # Anchored patterns, so this cannot be swallowed by the route above.
    path(
        "q/<slug:key>/identity/google/",
        views.identity_google,
        name="guest_identity_google",
    ),
    path(
        "q/<slug:key>/profile/",
        views.guest_profile_page,
        name="guest_profile_page",
    ),
]
