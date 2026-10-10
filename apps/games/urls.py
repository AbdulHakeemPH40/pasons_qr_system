from django.urls import path

from . import views

urlpatterns = [
    path("", views.games_hub, name="games_hub"),
    path("event/", views.games_event, name="games_event"),
    path("<slug:slug>/", views.games_play, name="games_play"),
]
