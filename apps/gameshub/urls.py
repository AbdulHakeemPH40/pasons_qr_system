"""Games Hub routes.

    /games/                    card menu
    /games/catch-the-burger    one game screen
    /games/memory-match
    /games/stack-the-burger

The slug list is whitelisted rather than captured freely, so a path that only
looks like a game never reaches the view. An optional trailing slash keeps each
game URL working in both forms.
"""

from django.urls import path, re_path

from . import views

app_name = "gameshub"

urlpatterns = [
    path("", views.hub, name="hub"),
    re_path(
        r"^(?P<slug>catch-the-burger|memory-match|stack-the-burger)/?$",
        views.play,
        name="play",
    ),
]
