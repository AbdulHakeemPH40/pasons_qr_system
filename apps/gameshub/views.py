"""Games Hub views.

Deliberately model-free: the hub renders the game list and the play screen
hosts a canvas. All game logic and score calculation stay in the browser, so a
later scoring service can be dropped in without touching these views.

Routes are self-contained (no reverse() into other apps, no shared context
processors) so the whole hub can move to its own domain later.
"""

from urllib.parse import quote

from django.http import Http404
from django.shortcuts import render

from .conf import GAMES, THEMES, get_game, get_theme


def _back_context(request):
    """Where "Exit" should return to, when a caller linked in with ?back=.

    Only a plain local path is ever accepted: it must start with a single
    slash (so never ``//host``, which browsers read as a protocol-relative
    URL), contain no backslash, and stay short. Anything else is dropped and
    the exit falls back to the home page. This keeps the hub independent of
    the Smart Page routes while still letting it hand customers back.
    """
    back = request.GET.get("back", "")
    safe = (
        back.startswith("/")
        and not back.startswith("//")
        and "\\" not in back
        and len(back) <= 200
    )
    back = back if safe else ""
    return {
        "back_url": back,
        # safe="" so a return path containing & or ? survives the round trip.
        "back_qs": f"?back={quote(back, safe='')}" if back else "",
    }


def hub(request):
    """Card menu of the three games, plus the demo background pack picker."""
    return render(
        request,
        "gameshub/hub.html",
        {
            "games": GAMES,
            "themes": THEMES,
            "active_theme": get_theme(request.GET.get("theme")),
            **_back_context(request),
        },
    )


def play(request, slug):
    """One game screen: title, one rule, canvas, score, pause and restart."""
    game = get_game(slug)
    if game is None:
        raise Http404("No such game")

    return render(
        request,
        "gameshub/play.html",
        {
            "game": game,
            "themes": THEMES,
            "active_theme": get_theme(request.GET.get("theme")),
            **_back_context(request),
        },
    )
