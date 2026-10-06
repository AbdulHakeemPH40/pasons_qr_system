"""Route-level checks for the Games Hub.

The hub has no models and no server-side scoring, so there is nothing to unit
test below the URL layer: everything else lives in the browser. These tests
pin the contract the templates and the JS rely on — every game screen exists,
unknown slugs are refused, and the hub ships the background pack list the
client scripts read.
"""

from django.test import TestCase
from django.urls import reverse

from .conf import GAMES, THEMES


class HubRouteTests(TestCase):
    def test_hub_renders_with_all_three_games(self):
        response = self.client.get("/games/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Play while you wait", count=1)
        for game in GAMES:
            self.assertContains(response, game["title"])

    def test_hub_works_with_and_without_trailing_slash(self):
        self.assertEqual(self.client.get("/games/").status_code, 200)
        self.assertEqual(self.client.get("/games").status_code, 200)

    def test_every_game_screen_renders(self):
        for game in GAMES:
            with self.subTest(game=game["slug"]):
                url = f"/games/{game['slug']}"
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, game["title"])
                self.assertContains(response, "data-game-host", count=1)

    def test_unknown_game_is_a_404(self):
        self.assertEqual(self.client.get("/games/not-a-game").status_code, 404)

    def test_play_view_passes_the_background_packs_to_the_client(self):
        response = self.client.get("/games/memory-match")
        self.assertContains(response, 'id="gh-themes"', count=1)
        self.assertContains(response, 'id="gh-theme-default"', count=1)
        for theme in THEMES:
            self.assertContains(response, theme["name"])

    def test_named_routes_resolve(self):
        self.assertEqual(reverse("gameshub:hub"), "/games/")
        for game in GAMES:
            # The trailing slash is optional in the pattern, so accept either form.
            resolved = reverse("gameshub:play", args=[game["slug"]])
            self.assertEqual(resolved.rstrip("/"), f"/games/{game['slug']}")

    def test_unknown_slug_is_refused_by_the_url_pattern_too(self):
        # The pattern whitelists slugs, so a path that only looks like a game
        # never even reaches the view.
        response = self.client.get("/games/catch-the-burgers")
        self.assertEqual(response.status_code, 404)

    def test_hub_does_not_touch_other_apps_routes(self):
        """The hub must stay independent so it can move to its own domain."""
        response = self.client.get("/games/")
        self.assertTemplateUsed(response, "gameshub/hub.html")
        # No reverse() into the Smart Page, panel or kidsplay namespaces.
        self.assertNotContains(response, "/panel/")
        self.assertNotContains(response, "/t/")
        self.assertNotContains(response, "/q/")

    def test_exit_returns_to_the_caller_when_back_is_a_local_path(self):
        """The Smart Page links in with ?back= so Exit hands customers back."""
        response = self.client.get("/games/", {"back": "/q/demo-key/"})
        self.assertContains(response, 'href="/q/demo-key/"')
        # The return path rides along on every game card too.
        self.assertContains(response, "?back=%2Fq%2Fdemo-key%2F")

    def test_play_screen_threads_the_back_link(self):
        response = self.client.get("/games/memory-match", {"back": "/q/demo-key/"})
        self.assertContains(response, 'href="/games/?back=%2Fq%2Fdemo-key%2F"')

    def test_hostile_back_values_are_dropped(self):
        """Only a plain local path is echoed into href; anything else -> '/'."""
        bad_values = [
            "//evil.example",
            "https://evil.example",
            "javascript:alert(1)",
            "/q/a\\b",
            "/q/" + "x" * 300,
        ]
        for bad in bad_values:
            with self.subTest(back=bad):
                response = self.client.get("/games/", {"back": bad})
                self.assertContains(response, 'href="/"')
                self.assertNotContains(response, "evil.example")
                self.assertNotContains(response, "javascript:")
