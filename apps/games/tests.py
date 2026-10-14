"""
Games Zone acceptance suite (vendored open-source model).

The three games are open-source projects vendored under static/games/vendor/
and run unmodified inside a same-origin iframe; the shell reads score and
game-over through per-game bridge selectors (registry.py). These tests lock
the public contract:

  /q/<key>/game/   logs the Play tap and redirects to the hub (old QR sheets)
  /games/          lists the enabled games with licence chips and credits
  /games/<slug>/   embeds the vendored page + bridge JSON, no offer copy
  /games/event/    records played / finished GameEvent rows, rejects junk
  landing          shows the PLAY A GAME card with zero discount promises
"""

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
            self.assertContains(response, game.credit)
            # bridge config reaches the shell as JSON
            self.assertContains(response, game.bridge["score"]["kind"])

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
        """Client rule: games are pure play, never a reward surface."""
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
            {"2048", "flappy-burger", "memory-match"},
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


class LandingPlayCardTests(GamesZoneFixtures):
    def test_landing_card_points_at_entry_without_offer_promise(self):
        response = self.client.get(
            reverse("qr_landing", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PLAY A GAME")
        self.assertContains(
            response, reverse("qr_game", args=[self.qr.redirect_key])
        )
        body = response.content.decode().lower()
        for word in ("discount", "coupon", "win a"):
            self.assertNotIn(word, body)
