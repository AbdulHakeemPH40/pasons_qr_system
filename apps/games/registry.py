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
                    overSel -> optional selector holding the FINAL score at
                               game-over, for games that erase their on-field
                               score display when the scoreboard appears
                               (flappy-burger empties #bigscore and re-renders
                               the total into #currentscore)
            over  kinds: class   -> element carries class cls
                           visible-> any match has a layout box

Games pages carry no offer copy and no personal data. Best scores live on
the guest's own device. The landing card's "Win a discount or dessert" perk
(client copy 2026-10-14) is honoured by staff, not by this code.
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
            # Flappy Burger erases #bigscore when the scoreboard appears
            # (showScore() -> setBigScore(true)) and re-renders the final
            # total as #currentscore digits, so the shell takes its final
            # reading from overSel before submitting the best score.
            "score": {
                "kind": "digits",
                "sel": "#bigscore",
                "overSel": "#currentscore",
            },
            "over": {"kind": "visible", "sel": "#scoreboard"},
        },
    ),
    Game(
        slug="memory-match",
        name="Memory Match",
        tagline="Find the pairs before the clock runs out",
        howto="Match pairs, beat the clock",
        glyph="memory",
        tint="pink",
        embed="games/vendor/memory-match/index.html",
        license="MIT",
        credit="Memory Game by mmenavas, MIT licence",
        bridge={
            # Pasons extension: the game keeps its own points clock
            # (match +100 with a streak bonus, -25 per miss, +15 per second
            # left on a win). It renders the running total into
            # #memory--points as bare digits, so the plain "text" reader
            # picks it up. The timeout and win paths both show the
            # end-game modal, so "over" is unchanged.
            "score": {"kind": "text", "sel": "#memory--points"},
            "over": {
                "kind": "class",
                "sel": "#memory--end-game-modal",
                "cls": "show",
            },
        },
    ),
    Game(
        slug="chess-master",
        name="Chess Master",
        tagline="Beat Stockfish at tough levels",
        howto="Tap a piece, then tap a square",
        glyph="chess",
        tint="green",
        embed="games/vendor/chess-master/index.html",
        license="GPL-3.0",
        credit=(
            "Stockfish.js engine GPLv3 (nmrugg/stockfish.js), chess.js by "
            "Jeff Hlywa (BSD-2), Pasons mobile port"
        ),
        bridge={
            # Pasons score extension (chess-master/js/score.js): the human's
            # capture points (10/30/30/50/90) climb during play, and a result
            # bonus lands at game over (win 200x level, draw 50x level). The
            # total is rendered as bare digits into #chess--score, and unlike
            # flappy nothing erases it at game over, so no overSel is needed.
            # Game-over is the setup-independent #gameover-modal (display:none
            # until the game ends, so the "visible" reader sees a layout box
            # only then).
            "score": {"kind": "text", "sel": "#chess--score"},
            "over": {"kind": "visible", "sel": "#gameover-modal"},
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
