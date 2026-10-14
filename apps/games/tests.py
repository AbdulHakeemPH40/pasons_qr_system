"""
Games Zone acceptance suite (vendored open-source model).

The four games are open-source projects vendored under static/games/vendor/
and run inside a same-origin iframe (memory-match and chess-master carry
documented Pasons extensions, see their CHANGES.md); the shell reads score and
game-over through per-game bridge selectors (registry.py). These tests lock
the public contract:

  /q/<key>/game/   logs the Play tap and redirects to the hub (old QR sheets)
  /games/          lists the enabled games with licence chips and credits
  /games/<slug>/   embeds the vendored page + bridge JSON, no offer copy
  /games/event/    records played / finished GameEvent rows, rejects junk
  landing          shows the PLAY A GAME card promising "Win a discount or dessert"
                   (client copy 2026-10-14, honoured by staff)
"""

from pathlib import Path
import os

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage

from .models import GameEvent
from .registry import enabled_games


def _hours_open_all_day():
    return {
        d: {"open": "00:00", "close": "23:59", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class GamesZoneFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Restaurant",
            code="KINGCHEF-GAMES",
            description="Games zone fixture brand.",
            default_phone="04 220 0001",
            google_review_url="https://g.page/r/kingchef-brand/review",
            google_place_id="ChIJ-games-fixture-brand",
            status="active",
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-GAMES-INTL",
            slug="games-international-city",
            official_name="King Chef — International City",
            brand=cls.brand,
            city="International City",
            address="Italy Cluster, International City, Dubai",
            phone="04 220 0011",
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.page = SmartPage.objects.create(
            brand=cls.brand,
            outlet=cls.outlet,
            slug="games-intlcity",
            page_title="King Chef — International City",
            published=True,
            published_at=timezone.now(),
        )
        cls.qr = QrCode.objects.create(
            brand=cls.brand,
            outlet=cls.outlet,
            destination_page=cls.page,
            source_type="table",
            label="Table 1",
            qr_code_name="KINGCHEF-GAMES-TABLE-001",
            redirect_key="kcgames-table-001",
        )


class GamesZoneRoutesTests(GamesZoneFixtures):
    def test_entry_logs_tap_and_redirects_to_hub(self):
        response = self.client.get(
            reverse("qr_game", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("games_hub"), response["Location"])
        self.assertIn(f"back=/q/{self.qr.redirect_key}/", response["Location"])
        # the Play tap lands in the existing analytics funnel
        from apps.analytics.models import TapEvent

        self.assertTrue(
            TapEvent.objects.filter(
                qr_code=self.qr, action=TapEvent.ActionType.GAME
            ).exists()
        )

    def test_entry_unknown_key_is_404(self):
        self.assertEqual(
            self.client.get("/q/no-such-key/game/").status_code, 404
        )

    def test_hub_lists_enabled_games_with_licence_and_credit(self):
        response = self.client.get(
            reverse("games_hub") + f"?back=/q/{self.qr.redirect_key}/"
        )
        self.assertEqual(response.status_code, 200)
        for game in enabled_games():
            self.assertContains(response, game.name)
            self.assertContains(response, game.license)
        self.assertContains(response, "Open-source classics")

    def test_play_page_embeds_vendored_frame_and_bridge(self):
        for game in enabled_games():
            response = self.client.get(
                reverse("games_play", args=[game.slug])
                + f"?back=/q/{self.qr.redirect_key}/"
            )
            self.assertEqual(response.status_code, 200, game.slug)
            self.assertContains(response, game.embed)
            self.assertContains(response, "game-frame")
            # bridge config reaches the shell as JSON
            self.assertContains(response, game.bridge["score"]["kind"])

    def test_play_page_renders_no_literal_template_comments(self):
        """Django's hash comment tag is single-line only: a multiline one
        stops being a comment and renders as literal text on the page, where
        it became a phantom flex item that stole 144px from the game card
        (2026-10-14). Use the comment-block tag for multiline notes and lock
        the rendered output here."""
        for game in enabled_games():
            response = self.client.get(
                reverse("games_play", args=[game.slug])
                + f"?back=/q/{self.qr.redirect_key}/"
            )
            self.assertEqual(response.status_code, 200, game.slug)
            html = response.content.decode()
            self.assertNotIn("{#", html, game.slug)
            self.assertNotIn("{% comment %}", html, game.slug)

    def test_visible_credits_removed_but_licence_attribution_retained(self):
        """Client request (2026-10-14): no visible credit line on the play
        page. Removing it is licence-safe ONLY if the attribution stays in
        the Source form (Apache-2.0 4(c); MIT's notice clause). This locks
        both halves: the credit is not rendered for guests, and the required
        attribution records still exist in the source tree."""
        from .registry import get_game

        # 1. The visible credit line is gone from the rendered play page.
        for game in enabled_games():
            response = self.client.get(
                reverse("games_play", args=[game.slug])
                + f"?back=/q/{self.qr.redirect_key}/"
            )
            self.assertNotContains(response, "game-credit")
            self.assertNotContains(response, game.credit)

        # 2. Attribution is retained in the source form (registry).
        flappy = get_game("flappy-burger")
        self.assertIn("Nebez", flappy.credit)
        self.assertIn("Apache-2.0", flappy.credit)
        self.assertEqual(flappy.license, "Apache-2.0")

        # 3. Each vendored folder keeps its licence file (4(a) / MIT notice).
        vendor = Path(settings.BASE_DIR) / "static" / "games" / "vendor"
        for game in enabled_games():
            lic = vendor / Path(game.embed).parent.name
            self.assertTrue(
                any(lic.glob("LICENSE*")),
                f"{game.slug} is missing its LICENSE file",
            )

        # 4. CREDITS.md + the vendored page still carry the attribution, and
        #    the flappy footer is retained as a source comment (4(c)).
        self.assertTrue((vendor / "CREDITS.md").exists())
        page = (vendor / "flappy-burger" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Nebez", page)
        self.assertIn("Dong Nguyen", page)
        # ...but it must not be a visible footer any more.
        self.assertNotIn('id="footer"', page)

    def test_play_unknown_slug_is_404(self):
        self.assertEqual(
            self.client.get(reverse("games_play", args=["not-a-game"]))
            .status_code,
            404,
        )

    def test_back_param_is_sanitised(self):
        evil = self.client.get(
            reverse("games_hub") + "?back=//evil.example.com/"
        )
        self.assertEqual(evil.status_code, 200)
        self.assertNotContains(evil, "//evil.example.com/")

        absolute = self.client.get(
            reverse("games_hub") + "?back=https://evil.example.com/x"
        )
        self.assertNotContains(absolute, "https://evil.example.com")

        good = self.client.get(
            reverse("games_hub") + f"?back=/q/{self.qr.redirect_key}/"
        )
        self.assertContains(good, f"/q/{self.qr.redirect_key}/")

    def test_no_offer_or_discount_copy_anywhere(self):
        """Hub and play pages stay offer-free: the perk promise lives only on
        the landing card, never inside the games zone pages themselves."""
        hub = self.client.get(reverse("games_hub"))
        play = self.client.get(reverse("games_play", args=["2048"]))
        for response in (hub, play):
            body = response.content.decode().lower()
            for word in ("discount", "coupon", "reward", "win a"):
                self.assertNotIn(word, body)


class GamesEventBeaconTests(GamesZoneFixtures):
    def test_beacon_records_played_and_finished(self):
        for kind, score in (("played", 0), ("finished", 42)):
            response = self.client.post(
                reverse("games_event"),
                {
                    "slug": "2048",
                    "kind": kind,
                    "score": str(score),
                    "qr": self.qr.redirect_key,
                },
            )
            self.assertEqual(response.status_code, 200)
        event = GameEvent.objects.filter(
            game_slug="2048", kind="finished"
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.score, 42)
        self.assertEqual(event.qr_code, self.qr)
        self.assertEqual(event.brand, self.brand)

    def test_beacon_rejects_unknown_slug_kind_and_get(self):
        self.assertEqual(
            self.client.post(
                reverse("games_event"),
                {"slug": "nope", "kind": "played", "score": "1"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                reverse("games_event"),
                {"slug": "2048", "kind": "hacked", "score": "1"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(reverse("games_event")).status_code, 405
        )

    def test_beacon_clamps_absurd_scores(self):
        self.client.post(
            reverse("games_event"),
            {
                "slug": "memory-match",
                "kind": "finished",
                "score": "99999999999",
            },
        )
        event = GameEvent.objects.filter(game_slug="memory-match").first()
        self.assertEqual(event.score, 10_000_000)

    def test_removed_games_are_gone(self):
        """Hextris and Snake were removed by request (2026-10-13)."""
        from .registry import get_game

        self.assertIsNone(get_game("hextris"))
        self.assertIsNone(get_game("snake"))
        self.assertEqual(
            {game.slug for game in enabled_games()},
            {"2048", "flappy-burger", "memory-match", "chess-master"},
        )
        for slug in ("hextris", "snake"):
            self.assertEqual(
                self.client.get(reverse("games_play", args=[slug])).status_code,
                404,
                slug,
            )
        hub = self.client.get(reverse("games_hub"))
        self.assertNotContains(hub, "Hextris")
        self.assertNotContains(hub, "Snake")

    def test_memory_match_bridge_reads_points_display(self):
        """Pasons points/timeout extension: the shell score comes from the
        game's #memory--points element (bare digits), and game-over is still
        the end-game modal — shown by BOTH the win and the timeout path."""
        from .registry import get_game

        game = get_game("memory-match")
        self.assertEqual(
            game.bridge["score"], {"kind": "text", "sel": "#memory--points"}
        )
        self.assertEqual(
            game.bridge["over"],
            {"kind": "class", "sel": "#memory--end-game-modal", "cls": "show"},
        )

        # The bridge selectors must exist in the vendored page itself,
        # otherwise the HUD silently sticks at zero.
        page_path = (
            Path(settings.BASE_DIR) / "static" / game.embed.replace("/", os.sep)
        )
        page = page_path.read_text(encoding="utf-8")
        self.assertIn('id="memory--points"', page)
        self.assertIn('id="memory--timer"', page)
        self.assertIn('id="memory--end-game-modal"', page)

    def test_flappy_bridge_reads_final_score_from_scoreboard(self):
        """Flappy Burger erases its in-flight score display at game-over:
        showScore() calls setBigScore(true) and re-renders the total as
        #currentscore digits on the scoreboard. The bridge must carry
        overSel="#currentscore" so the shell submits the real total; without
        it the shell reads the emptied #bigscore as 0, and a submitted 0
        never beats the stored best, so "Best" stays empty forever."""
        from .registry import get_game

        game = get_game("flappy-burger")
        self.assertEqual(
            game.bridge["score"],
            {"kind": "digits", "sel": "#bigscore", "overSel": "#currentscore"},
        )
        self.assertEqual(
            game.bridge["over"], {"kind": "visible", "sel": "#scoreboard"}
        )

        # The bridge selectors must exist in the vendored page itself,
        # otherwise the HUD silently sticks at zero.
        page_path = (
            Path(settings.BASE_DIR) / "static" / game.embed.replace("/", os.sep)
        )
        page = page_path.read_text(encoding="utf-8")
        self.assertIn('id="bigscore"', page)
        self.assertIn('id="currentscore"', page)
        self.assertIn('id="scoreboard"', page)

        # ...and the engine must really move the score at game-over,
        # otherwise overSel points at a dead element.
        engine = (page_path.parent / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn("setBigScore(true)", engine)

        # The shell must read the final score through overSel at submit time.
        shell = (
            Path(settings.BASE_DIR) / "static" / "games" / "core" / "shell.js"
        ).read_text(encoding="utf-8")
        self.assertIn("overSel", shell)
        self.assertIn("storage.submit(slug, score)", shell)

    def test_shell_reattaches_game_doc_outside_load_event(self):
        """The bridge reads the game through the iframe's contentDocument,
        but attaching it ONLY on the frame's load event loses the race with
        a cached game page: the page can finish loading before shell.js
        boots, the listener registers too late, never fires, and the poll
        stays dark forever (HUD frozen, no game-over, best never saved).
        The shell must also attach at boot and on every poll tick."""
        shell = (
            Path(settings.BASE_DIR) / "static" / "games" / "core" / "shell.js"
        ).read_text(encoding="utf-8")

        # idempotent attach helper
        self.assertIn("function attachDoc()", shell)
        # wired to the load event (the handler itself must call it) ...
        # rsplit: restart() registers its own one-shot load listener first
        self.assertIn('frame.addEventListener("load"', shell)
        load_handler = shell.rsplit('frame.addEventListener("load"', 1)[1].split("});", 1)[0]
        self.assertIn("attachDoc()", load_handler)
        # ... and re-run at boot and inside the interval
        poll = shell.split("window.setInterval(", 1)[1]
        self.assertIn("attachDoc();", poll.split("}, 250);", 1)[0])

    def test_shell_never_finishes_on_a_stale_or_half_loaded_document(self):
        """Live play-test catch (2026-10-14, Chess Master): after "Play
        again" the overlay came back with a bogus "Game over 0" while the
        fresh setup modal showed underneath. Two holes, both locked here:

        1. The 250ms poll kept running against the OLD document during the
           restart() reload gap and re-fired finish() on its still-visible
           game-over marker.
        2. A half-parsed fresh document reports game-over modals as
           "visible": a .hidden class is not display:none until the game's
           stylesheet applies, so the visibility reader saw the modal's
           layout box mid-load.

        The shell must pause polling while a reload is in flight and until
        the document is no longer loading."""
        shell = (
            Path(settings.BASE_DIR) / "static" / "games" / "core" / "shell.js"
        ).read_text(encoding="utf-8")

        # restart() arms the reload guard ...
        restart = shell.split("function restart()", 1)[1].split("function ", 1)[0]
        self.assertIn("reloading = true", restart)
        # ... attachDoc() disarms it when the NEW document lands ...
        attach = shell.split("function attachDoc()", 1)[1].split("function ", 1)[0]
        self.assertIn("reloading = false", attach)
        # ... and the poll honours it.
        poll = shell.split("window.setInterval(", 1)[1].split("}, 250);", 1)[0]
        self.assertIn("reloading", poll)
        # Half-loaded documents are ignored (stylesheet-not-yet-applied
        # lie: .hidden elements keep their layout box).
        self.assertIn('readyState === "loading"', poll)

    def test_memory_match_shows_time_budgets_before_start(self):
        """Timeout budgets are telegraphed on the difficulty options so a
        guest sees the clock commitment before starting a round."""
        from .registry import get_game

        game = get_game("memory-match")
        page_path = (
            Path(settings.BASE_DIR) / "static" / game.embed.replace("/", os.sep)
        )
        page = page_path.read_text(encoding="utf-8")
        self.assertIn("Easy &mdash; 1:00", page)
        self.assertIn("Medium &mdash; 1:45", page)
        self.assertIn("Hard &mdash; 2:45", page)
        self.assertIn("Don't do it! &mdash; 3:45", page)


class ChessMasterTests(GamesZoneFixtures):
    """Chess Master (2026-10-14): the Electron app ported to the Games Zone.

    Client brief: mobile only, vs Stockfish only (no friend mode, no LLM
    mode), difficulty levels 3-6 only (tough game), same colours and assets.
    """

    def _vendor(self):
        from .registry import get_game

        game = get_game("chess-master")
        return game, (
            Path(settings.BASE_DIR) / "static" / game.embed.replace("/", os.sep)
        )

    def test_bridge_reads_score_chip_and_gameover_modal(self):
        """The shell reads the Pasons score extension (#chess--score, bare
        digits rendered by js/score.js) and detects game over through the
        #gameover-modal visibility. Both selectors must exist in the page,
        otherwise the HUD silently sticks at zero / never finishes."""
        from .registry import get_game

        game = get_game("chess-master")
        self.assertEqual(
            game.bridge["score"], {"kind": "text", "sel": "#chess--score"}
        )
        self.assertEqual(
            game.bridge["over"], {"kind": "visible", "sel": "#gameover-modal"}
        )

        game, page_path = self._vendor()
        page = page_path.read_text(encoding="utf-8")
        self.assertIn('id="chess--score"', page)
        self.assertIn('id="gameover-modal"', page)

        # The score renderer really writes bare digits into the chip.
        score_js = (page_path.parent / "js" / "score.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("chess--score", score_js)
        self.assertIn("String(this.total())", score_js)
        # Result bonus scales with the engine level (tough game: levels 3-6).
        self.assertIn("200 * level", score_js)
        self.assertIn("50 * level", score_js)

    def test_stockfish_only_no_friend_or_llm_modes(self):
        """Client brief: only vs Stockfish. The Electron app's friend and
        LLM (API-key) modes must not ship in the port. Comments may describe
        the removals, so the scan runs over CODE with comments stripped."""
        import re as _re

        def code_only(text):
            text = _re.sub(r"/\*.*?\*/", "", text, flags=_re.S)
            text = _re.sub(r"^\s*//.*$", "", text, flags=_re.M)
            return text

        game, page_path = self._vendor()
        page = page_path.read_text(encoding="utf-8")
        self.assertNotIn("vs Friend", page)
        self.assertNotIn("vs AI Model", page)
        self.assertNotIn("data-mode=", page)
        self.assertNotIn("settings-modal", page)

        for name in ("app.js", "ui.js", "engine.js", "score.js"):
            js = code_only(
                (page_path.parent / "js" / name).read_text(encoding="utf-8")
            )
            self.assertNotIn("LLM", js, name)
            self.assertNotIn("api.openai.com", js, name)
            self.assertNotIn("openrouter", js, name)

        # The LLM engine module must not exist in the vendored folder at all.
        self.assertFalse((page_path.parent / "js" / "llm-engine.js").exists())

    def test_difficulty_levels_are_3_to_6_only(self):
        """Client brief: high/tough game only. The setup modal offers exactly
        levels 3, 4, 5, 6 and the engine preset list carries no softer entry
        to fall back to."""
        game, page_path = self._vendor()
        page = page_path.read_text(encoding="utf-8")

        for level in ("3", "4", "5", "6"):
            self.assertIn(f'data-diff="{level}"', page)
        for level in ("1", "2"):
            self.assertNotIn(f'data-diff="{level}"', page)

        engine = (page_path.parent / "js" / "engine.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("export const DIFFICULTY_LEVELS", engine)
        for level in ("3", "4", "5", "6"):
            self.assertIn(f"id: {level}", engine)
        for level in ("1", "2"):
            self.assertNotIn(f"id: {level},", engine)

    def test_level_labels_show_1_to_4_over_engine_3_to_6(self):
        """UI-only renumbering (client request): the guest reads Level 1-4
        while the engine keeps its difficulty ids 3-6 (display 1 = Club
        ~1600 through display 4 = Master ~3000+, the same Stockfish
        hardness as before). The visible label must stay paired with the
        engine id in the markup, and every rendered "Lv N" must go through
        ui.js levelLabel so the mapping exists in exactly one place."""
        game, page_path = self._vendor()
        page = page_path.read_text(encoding="utf-8")

        # Modal buttons: visible display label 1-4 paired with engine 3-6.
        for display, engine_id in ((1, 3), (2, 4), (3, 5), (4, 6)):
            self.assertRegex(
                page,
                rf'data-diff="{engine_id}"[^>]*>\s*{display}\s*</button>',
            )

        # The mapping lives in exactly one helper and every "Lv" label is
        # rendered through it; no raw engine id may reach the guest's eye.
        ui_js = (page_path.parent / "js" / "ui.js").read_text(encoding="utf-8")
        app_js = (page_path.parent / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("export function levelLabel", ui_js)
        self.assertNotIn("Lv ${difficulty}", ui_js)
        self.assertNotIn("Lv ${this.ui.selectedDifficulty}", app_js)
        self.assertIn("Lv ${levelLabel(", ui_js)
        self.assertIn("Lv ${levelLabel(", app_js)

    def test_cancel_new_game_never_a_dead_control(self):
        """Regression (2026-10-14): the setup-modal Cancel button did nothing
        on the start screen because its handler was gated behind
        ``if (this.gameStarted)`` and no game runs there yet. A Cancel that
        ignores taps is a broken control. It must dismiss the modal every time:
        mid-game that returns to the running game, on the start screen it
        reveals the idle board (status "Set up a game to start") with the
        persistent New Game button ready to reopen the dialog."""
        import re as _re

        game, page_path = self._vendor()
        app_js = (page_path.parent / "js" / "app.js").read_text(encoding="utf-8")

        # The button is wired to a handler...
        self.assertIn("btn-cancel-newgame", app_js)
        cancel_at = app_js.index("btn-cancel-newgame")
        handler = app_js[cancel_at : cancel_at + 300]
        # ...and that handler dismisses the setup modal.
        self.assertIn("hideNewGame()", handler)
        # It must never gate the dismiss behind "a game is already running".
        self.assertIsNone(
            _re.search(
                r"if\s*\(\s*this\.gameStarted\s*\)\s*this\.ui\.hideNewGame\(\)",
                app_js,
            ),
            "Cancel must dismiss the setup modal unconditionally",
        )
        # Dismissing on the start screen is safe because the idle board is
        # honestly labelled and New Game is always available to reopen.
        self.assertIn("Set up a game to start", app_js)

    def test_stockfish_engine_ships_locally_with_no_external_calls(self):
        """House rule: no external network calls from guest pages. The
        Stockfish WASM engine is vendored and loads from our own static
        folder; the engine module resolves the Worker URL module-relative so
        it cannot point outside the game folder."""
        game, page_path = self._vendor()

        self.assertTrue(
            (page_path.parent / "lib" / "stockfish" / "stockfish.js").exists()
        )
        self.assertTrue(
            (page_path.parent / "lib" / "stockfish" / "stockfish.wasm").exists()
        )
        self.assertTrue((page_path.parent / "lib" / "chess.js").exists())

        engine = (page_path.parent / "js" / "engine.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("import.meta.url", engine)
        # piece art ships in the folder (same assets as the Electron app)
        pieces = list((page_path.parent / "assets" / "pieces").glob("*.svg"))
        self.assertEqual(len(pieces), 12)

        # rules lib keeps its BSD-2 attribution (source-form licence duty)
        chess_js = (page_path.parent / "lib" / "chess.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("Jeff Hlywa", chess_js)

    def test_play_page_and_hub_render_chess_master(self):
        response = self.client.get(
            reverse("games_play", args=["chess-master"])
            + f"?back=/q/{self.qr.redirect_key}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chess-master/index.html")
        self.assertContains(response, "chess--score")

        hub = self.client.get(reverse("games_hub"))
        self.assertContains(hub, "Chess Master")
        self.assertContains(hub, "GPL-3.0")


class LandingPlayCardTests(GamesZoneFixtures):
    def test_landing_card_promises_discount_or_dessert(self):
        """Client copy 2026-10-14 (via user): the card advertises the perk
        "Win a discount or dessert", honoured by staff. Supersedes the
        2026-10-10 play-only card copy. Coupon language stays out."""
        response = self.client.get(
            reverse("qr_landing", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PLAY A GAME")
        self.assertContains(response, "Win a discount or dessert")
        self.assertContains(
            response, reverse("qr_game", args=[self.qr.redirect_key])
        )
        self.assertNotIn("coupon", response.content.decode().lower())
