"""Public KidsPlay pages under /t/."""

from django.urls import path

from apps.kidsplay.views import public

app_name = "kidsplay"

urlpatterns = [
    path("<slug:table_code>/", public.landing, name="landing"),
    path("<slug:table_code>/phone/", public.otp_request, name="otp_request"),
    path("<slug:table_code>/verify/", public.otp_verify, name="otp_verify"),
    path("<slug:table_code>/kids/", public.kids, name="kids"),
    path("<slug:table_code>/hub/", public.hub, name="hub"),
    path("<slug:table_code>/play/<slug:slug>/", public.play, name="play"),
    path("<slug:table_code>/rewards/", public.rewards_page, name="rewards"),
    path("<slug:table_code>/delete/", public.delete_family, name="delete"),
]
