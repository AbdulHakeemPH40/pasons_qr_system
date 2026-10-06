"""KidsPlay JSON endpoints under /api/kidsplay/."""

from django.urls import path

from apps.kidsplay.views import api

urlpatterns = [
    path("game/start", api.game_start, name="kidsplay_game_start"),
    path("game/finish", api.game_finish, name="kidsplay_game_finish"),
    path("me", api.me, name="kidsplay_me"),
]
