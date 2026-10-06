"""Staff KidsPlay pages under /staff/kidsplay/."""

from django.urls import path

from apps.kidsplay.views import staff

urlpatterns = [
    path("visits", staff.visit_list, name="kidsplay_staff_visits"),
    path("redeem/", staff.redeem_page, name="kidsplay_staff_redeem"),
    path("redeem/confirm", staff.redeem_confirm, name="kidsplay_redeem_confirm"),
    path("redeem/cancel", staff.redeem_cancel, name="kidsplay_redeem_cancel"),
    path("visit/<uuid:visit_id>/close", staff.visit_close, name="kidsplay_visit_close"),
    path("visit/<uuid:visit_id>/bill", staff.visit_bill, name="kidsplay_visit_bill"),
]
