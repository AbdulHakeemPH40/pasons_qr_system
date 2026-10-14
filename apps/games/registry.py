"""
Games Zone registry (GAMES_ZONE_PLAN.md section 3, vendored model).

The games are open-source projects vendored under
static/games/vendor/<slug>/ (see static/games/vendor/CREDITS.md for licences
and credits). We do not rebuild them: each game runs UNMODIFIED inside a
same-origin iframe, and the shared shell reads score / game-over straight out
of the iframe DOM (or its window globals) using the `bridge` selectors below.

Because of that model every entry carries:
  embed   static path of the vendored game page loaded in the iframe
  licence short licence id shown on the hub card
  credit  attribution line shown on the play page
  bridge  how the shell observes score and game-over without touching the
          game code:
            score kinds: text   -> parseInt(element.textContent)
                           digits -> join alt attrs of child imgs
                           objects-> count a global array's truthy named prop
                                     (dot path in name), divided by divisor
            over  kinds: class   -> element carries class cls
                           visible-> any match has a layout box

Games are pure play: no rewards, no discounts, no personal data. Best scores
live on the guest's own device.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Game:
    slug: str
    name: str
    tagline: str
    howto: str
    glyph: str          # icon_tags name rendered on the hub card
    tint: str           # css modifier for the glyph tile
    embed: str          # static path of the vendored game page
    license: str        # short licence id for the hub chip
    credit: str         # attribution line for the play page
    bridge: dict = field(default_factory=dict)
    enabled: bool = True


GAMES = (
    Game(
        slug="2048",
        name="2048",
        tagline="Slide and merge the tiles",
        howto="Swipe or use arrow keys to merge tiles",
        glyph="grid",
        tint="gold",
        embed="games/vendor/2048/index.html",
        license="MIT",
        credit="2048 by Gabriele Cirulli, MIT licence",
        bridge={
            "score": {"kind": "text", "sel": ".score-container"},
            "over": {"kind": "class", "sel": ".game-message", "cls": "game-over"},
            # 2048 resumes the last board from this key on load; clear it so
            # "Play again" starts fresh. Its own bestScore key is left alone.
            "resetKeys": ["gameState"],
        },
    ),
    Game(
        slug="flappy-burger",
        name="Flappy Burger",
        tagline="Tap to fly through the gaps",
        howto="Tap anywhere to flap",
        glyph="burger",
        tint="red",
        embed="games/vendor/flappy-burger/index.html",
        license="Apache-2.0",
        credit="Flappy-style engine by Nebez Felkner, Apache-2.0, Pasons art",
        bridge={
            "score": {"kind": "digits", "sel": "#bigscore"},
            "over": {"kind": "visible", "sel": "#scoreboard"},
        },
    ),
    Game(
        slug="memory-match",
        name="Memory Match",
        tagline="Flip the cards, find the pairs",
        howto="Tap two cards at a time",
        glyph="memory",
        tint="pink",
        embed="games/vendor/memory-match/index.html",
        license="MIT",
        credit="Memory Game by mmenavas, MIT licence",
        bridge={
            # memory-match keeps matched cards in the DOM (it never removes
            # them, so a children count can't see progress) and shows an empty
            # board behind a difficulty modal until the guest starts. Its model
            # global is exact: MemoryGame.cards[i].isRevealed is true for cards
            # face up, i.e. 2 x matched pairs (plus at most one card mid-flip,
            # which floor() drops). The model clears a mismatch immediately, so
            # the score never sticks high while two wrong cards are still shown.
            "score": {
                "kind": "objects",
                "name": "MemoryGame.cards",
                "prop": "isRevealed",
                "divisor": 2,
            },
            "over": {
                "kind": "class",
                "sel": "#memory--end-game-modal",
                "cls": "show",
            },
        },
    ),
)

GAME_BY_SLUG = {game.slug: game for game in GAMES}


def get_game(slug):
    """Return the Game for slug, or None when unknown."""
    return GAME_BY_SLUG.get(slug)


def enabled_games():
    """Games shown in the hub and allowed to load on the play page."""
    return [game for game in GAMES if game.enabled]
