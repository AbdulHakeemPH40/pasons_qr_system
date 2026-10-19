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
    # WhatsApp one time code: send a fresh code, then check what was typed.
    # Both answer JSON and are called by the sheet's script.
    path(
        "q/<slug:key>/identity/otp/send/",
        views.otp_send,
        name="guest_otp_send",
    ),
    path(
        "q/<slug:key>/identity/otp/check/",
        views.otp_check,
        name="guest_otp_check",
    ),
    path(
        "q/<slug:key>/profile/",
        views.guest_profile_page,
        name="guest_profile_page",
    ),
    # Sign out forgets this browser only. POST, because a prefetched or
    # crawled link must never log a guest out.
    path(
        "q/<slug:key>/profile/signout/",
        views.guest_signout,
        name="guest_signout",
    ),
]
