from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.kidsplay.models import Family, GameSession, KidProfile, PlayGame, TableVisit
from apps.kidsplay.services import games


class AntiCheatTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name_en="Paramount Restaurant", code="PARAMOUNT")
        outlet = Outlet.objects.create(brand=brand, official_name="Paramount Deira", code="PARAMOUNT-DEIRA")
        page = SmartPage.objects.create(brand=brand, outlet=outlet, slug="paramount-deira", page_title="Paramount")
        qr = QrCode.objects.create(
            qr_code_name="PARAMOUNT-DEIRA-TABLE-001",
            destination_page=page,
            source_type=QrCode.SourceType.TABLE,
            brand=brand,
            outlet=outlet,
            redirect_key="kp-anti",
        )
        self.family = Family.objects.create(phone="+971501010101", consent_at=timezone.now())
        self.kid = KidProfile.objects.create(family=self.family, nickname="Lina", avatar="fries")
        self.visit = TableVisit.objects.create(
            family=self.family,
            qr_code=qr,
            outlet=outlet,
            expires_at=timezone.now() + timedelta(hours=2),
        )
        self.game = PlayGame.objects.get(slug="burger-stack")

    def _session(self, started_ago=30):
        session = GameSession.objects.create(
            kid=self.kid, visit=self.visit, game=self.game, token_nonce="abc123"
        )
        GameSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(seconds=started_ago))
        token = games._signer().sign(f"{session.pk}:abc123")
        return token

    def test_negative_score(self):
        result = games.finish_game(self.kid, self._session(), -3, 20000)
        self.assertEqual(result["points_awarded"], 0)

    def test_too_fast(self):
        result = games.finish_game(self.kid, self._session(), 10, 1000)
        self.assertEqual(result["points_awarded"], 0)
        self.assertEqual(GameSession.objects.get().reject_reason, "duration")

    def test_too_long(self):
        result = games.finish_game(self.kid, self._session(started_ago=700), 10, 700000)
        self.assertEqual(GameSession.objects.get().reject_reason, "duration")

    def test_rate_too_high(self):
        result = games.finish_game(self.kid, self._session(), 100, 10000)
        self.assertEqual(GameSession.objects.get().reject_reason, "rate")

    def test_claimed_duration_longer_than_elapsed(self):
        result = games.finish_game(self.kid, self._session(started_ago=5), 4, 20000)
        self.assertEqual(GameSession.objects.get().reject_reason, "elapsed")

    def test_tampered_token(self):
        token = self._session() + "x"
        result = games.finish_game(self.kid, token, 20, 20000)
        self.assertEqual(result["points_awarded"], 0)
        self.assertEqual(GameSession.objects.get().status, GameSession.Status.STARTED)
