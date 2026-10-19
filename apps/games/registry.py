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
            defer -> true when the game ships a real end screen of its own
                     and the board behind it is worth studying. The shell
                     then keeps its own result sheet CLOSED and waits in a
                     small dock at the bottom edge; the guest opens the sheet
                     when they are done reviewing (chess-master).

Games pages carry no offer copy and no personal data. Best scores live on
the guest's own device. The landing card promises a gift and leaves the
prize to management (client copy 2026-10-16); the win itself is issued by
apps/rewards and is honoured by staff, not by this code.
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
    # What a REAL round of this game looks like, used by apps/rewards as an
    # effort floor. Below either number the round is treated as a throwaway
    # and counts for nothing. These are floors, not proof: the values arrive
    # from the guest's browser and a bot can fake them. What they buy is
    # effort, not security.
    effort: dict = field(default_factory=dict)
    # HOW this game pays, if it pays at all (client rules 2026-10-16):
    #   mode "none"    pure play. The game is entertainment and pays nothing.
    #   mode "ladder"  levels that must be won in order. Only the rungs named
    #                  in `paying_rungs` pay, and they pay the rule for the
    #                  tier named there (good = the dessert, high = the
    #                  discount). Lower rungs are the cost of entry.
    #   mode "streak"  a run of qualifying rounds. Only `prize_tier` pays,
    #                  and only once `rounds` of them land inside
    #                  `window_days` days. Never more than one prize.
    #   mode "threshold"  one scoring round. `prize_tier` pays when that
    #                  round clears the tier's line in `reward`, and never
    #                  otherwise. Never more than one prize.
    earn: dict = field(default_factory=dict)
    # Reward lines, in that game's own scoring units. These are the DEFAULT
    # lines: a RewardRule row for the same game and tier overrides the value,
    # which is how staff retune the bar without a code change. Under the
    # ladder rule `min_score` is a floor a round must also clear; under the
    # streak rule it is the line that makes a single round QUALIFY. Empty
    # dict = this game pays nothing.
    reward: dict = field(default_factory=dict)


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
        # THE TILE (client 2026-10-16, fourth pass). Reaching the 2048 tile
        # pays. The first reach pays the free dessert. Once that guest has
        # five real reaches stored against their name and mobile, the next
        # reach pays 10% off, and never another dessert. A high score that
        # never made the tile pays nothing. The result span is written by the
        # vendored actuator only when the tile is actually merged.
        effort={"min_seconds": 60, "min_actions": 20},
        earn={"mode": "reaches", "need": 5, "first_tier": "good", "later_tier": "high"},
        reward={"good": 2048, "high": 2048},
        bridge={
            "score": {"kind": "text", "sel": ".score-container"},
            "result": {"kind": "text", "sel": "#tiles--result"},
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
        # DESSERT AT 25 (client 2026-10-16, third pass). Flappy Burger pays a
        # FREE DESSERT when a real round clears 25 pipes, and never a coupon
        # and never the 10% discount. The `good` line below is both the
        # threshold a round must clear and the value staff retune with a
        # RewardRule row. The weekly cooldown is what keeps this from being
        # easy: one dessert per mobile per calendar month.
        effort={"min_seconds": 25, "min_actions": 15},
        earn={"mode": "threshold", "prize_tier": "good"},
        reward={"good": 25},
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
        # NEVER A COUPON (client 2026-10-16): Memory Match pays a free
        # dessert and nothing else, and only after five real rounds inside a
        # week. The `good` line below is what makes a single round QUALIFY;
        # five throwaway games must not buy a dessert.
        effort={"min_seconds": 45, "min_actions": 8},
        earn={"mode": "streak", "rounds": 5, "window_days": 7, "prize_tier": "good"},
        reward={"good": 400},
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
        # THE LADDER (client 2026-10-16). Four rungs, Level 1 to Level 4,
        # mapped onto the four difficulties. Win rung N to unlock rung N+1.
        # Level 1 and Level 2 pay NOTHING: they are the cost of entry. A
        # Level 3 win pays the free dessert (tier "good"); a Level 4 win pays
        # the 10% discount (tier "high"). "level" is the guest-facing level
        # 1-4, which the Pasons score extension renders into #chess--level
        # as `difficulty - 2` (see js/score.js and CHANGES.md).
        effort={"min_seconds": 90, "min_actions": 12},
        earn={"mode": "ladder", "levels": 4, "paying_rungs": {3: "good", 4: "high"}},
        reward={"good": 300, "high": 600},
        bridge={
            # Pasons score extension (chess-master/js/score.js): the human's
            # capture points (10/30/30/50/90) climb during play, and a result
            # bonus lands at game over (win 200x level, draw 50x level). The
            # total is rendered as bare digits into #chess--score, and unlike
            # flappy nothing erases it at game over, so no overSel is needed.
            # Game-over is the setup-independent #gameover-modal (display:none
            # until the game ends, so the "visible" reader sees a layout box
            # only then).
            # `level` and `result` are read at game over so the ladder can be
            # advanced server side: the rung has to be climbed in order, and
            # only a WIN climbs it.
            "score": {"kind": "text", "sel": "#chess--score"},
            "level": {"kind": "text", "sel": "#chess--level"},
            "result": {"kind": "text", "sel": "#chess--result"},
            "over": {"kind": "visible", "sel": "#gameover-modal"},
            # DEFERRED RESULT (client 2026-10-19). Chess ships a real end
            # screen of its own: who won, by what, and a "Review Board"
            # button. The board behind it is the thing the guest wants to
            # look at after a loss. So the shell does NOT throw its dark
            # result sheet over the game the instant the game ends: it keeps
            # the sheet closed behind a small dock at the bottom edge, and
            # the guest opens it once they are done reviewing. "Game over"
            # arriving before the guest could even see the final position
            # was the complaint.
            "defer": True,
            # Rung locking, applied by the shell into the setup modal. The
            # guest-facing level is `levelAttr` minus `levelOffset`
            # (data-diff 3-6 is shown as Level 1-4, see CHANGES.md), and any
            # button above the guest's unlocked rung is disabled. The server
            # enforces this again at claim time: the UI is a courtesy.
            "lock": {
                "sel": "#difficulty-row .diff-option",
                "levelAttr": "data-diff",
                "levelOffset": 2,
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
