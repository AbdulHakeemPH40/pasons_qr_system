"""
URL configuration — Pasons Restaurant Smart QR platform.

Public routes:
    /            scanned shop window (same five actions as a QR)
    /p/<slug>/   Smart Page — brand or outlet (spec section 9)
    /q/<key>/    permanent QR redirect (spec section 23)

Internal (staff) routes:
    /dashboard/  management KPI dashboard (spec section 25)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from apps.analytics import views as analytics_views
from apps.core import views
from apps.menu import views as menu_views
from apps.games import views as game_views

from django.contrib.auth import views as auth_views
from apps.core import panel_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("restaurants/", views.home, name="restaurants"),
    path("p/<slug:slug>/", views.smart_page, name="smart_page"),

    # QR and Customer Flow routes (Spec Part A, B, C)
    path("q/<slug:key>/", views.qr_redirect, name="qr_landing"),
    path("q/<slug:key>/", views.qr_redirect, name="qr_redirect"),
    path("q/<slug:key>/specials/", menu_views.customer_specials, name="customer_specials"),
    path("q/<slug:key>/specials/", menu_views.customer_specials, name="qr_specials"),
    path("q/<slug:key>/menu/", menu_views.customer_menu, name="customer_menu"),
    path("q/<slug:key>/menu/", menu_views.customer_menu, name="qr_menu"),
    path("q/<slug:key>/review/", views.qr_review_redirect, name="qr_review_redirect"),
    path("q/<slug:key>/review/", views.qr_review_redirect, name="qr_review"),
    path("q/<slug:key>/instagram/", views.qr_instagram_redirect, name="qr_instagram_redirect"),
    path("q/<slug:key>/instagram/", views.qr_instagram_redirect, name="qr_instagram"),
    path("q/<slug:key>/game/", game_views.customer_game, name="customer_game"),
    path("q/<slug:key>/game/", game_views.customer_game, name="qr_game"),
    path("q/<slug:key>/game/result/", game_views.customer_game_result, name="customer_game_result"),
    path("q/<slug:key>/game/result/", game_views.customer_game_result, name="qr_game_result"),
    path("q/<slug:key>/tap/", views.tap_beacon, name="tap_beacon"),

    # Custom Panel routes (Spec Part D)
    path("panel/login/", auth_views.LoginView.as_view(template_name="panel/login.html"), name="login"),
    path("panel/logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("panel/", panel_views.panel_dashboard, name="panel_dashboard"),
    path("panel/brands/", panel_views.panel_brands, name="panel_brands"),
    path("panel/brands/add/", panel_views.panel_brand_edit, name="panel_brand_add"),
    path("panel/brands/<int:pk>/edit/", panel_views.panel_brand_edit, name="panel_brand_edit"),
    path("panel/outlets/", panel_views.panel_outlets, name="panel_outlets"),
    path("panel/outlets/add/", panel_views.panel_outlet_add, name="panel_outlet_add"),
    path("panel/outlets/<int:pk>/edit/", panel_views.panel_outlet_edit, name="panel_outlet_edit"),
    path("panel/qrcodes/", panel_views.panel_qrcodes, name="panel_qrcodes"),
    path("panel/qrcodes/generate/", panel_views.panel_qr_generate, name="panel_qr_generate"),
    path("panel/qrcodes/<int:pk>/download/<str:fmt>/", panel_views.panel_qr_download, name="panel_qr_download"),
    path("panel/qrcodes/<int:pk>/print/", panel_views.panel_qr_print, name="panel_qr_print"),
    path("panel/qrcodes/<int:pk>/regenerate/", panel_views.panel_qr_regenerate, name="panel_qr_regenerate"),
    path("panel/specials/", panel_views.panel_specials, name="panel_specials"),
    path("panel/specials/add/", panel_views.panel_special_add, name="panel_special_add"),
    path("panel/menus/", panel_views.panel_menus, name="panel_menus"),
    path("panel/games/", panel_views.panel_rewards, name="panel_games"),
    path("panel/rewards/", panel_views.panel_rewards, name="panel_rewards"),
    path("panel/rewards/<int:pk>/redeem/", panel_views.panel_reward_redeem, name="panel_reward_redeem"),
    path("panel/analytics/", analytics_views.dashboard, name="panel_analytics"),
    path("panel/changelog/", panel_views.panel_changelog, name="panel_changelog"),

    path("dashboard/", analytics_views.dashboard, name="dashboard"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
