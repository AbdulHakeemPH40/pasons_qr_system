from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.kidsplay.models import Family, GameSession, KidProfile, PlayGame, PointsLedger, TableVisit
from apps.kidsplay.services import games, points


class PointsCapTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name_en="Milan Veg", code="MILANVEG")
        outlet = Outlet.objects.create(brand=brand, official_name="Milan Veg Karama", code="MILANVEG-KARAMA")
        page = SmartPage.objects.create(brand=brand, outlet=outlet, slug="milanveg-karama", page_title="Milan Veg")
        qr = QrCode.objects.create(
            qr_code_name="MILANVEG-KARAMA-TABLE-001",
            destination_page=page,
            source_type=QrCode.SourceType.TABLE,
            brand=brand,
            outlet=outlet,
            redirect_key="kp-caps",
        )
        self.family = Family.objects.create(phone="+971502020202", consent_at=timezone.now())
        self.kid = KidProfile.objects.create(family=self.family, nickname="Omar", avatar="taco")
        self.visit = TableVisit.objects.create(
            family=self.family, qr_code=qr, outlet=outlet, expires_at=timezone.now() + timedelta(hours=2)
        )
        self.game = PlayGame.objects.get(slug="burger-stack")

    def _finish(self, score, nonce):
        session = GameSession.objects.create(
            kid=self.kid, visit=self.visit, game=self.game, token_nonce=nonce
        )
        GameSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(seconds=40))
        token = games._signer().sign(f"{session.pk}:{nonce}")
        return games.finish_game(self.kid, token, score, 30000)

    def test_tier_selection(self):
        self.assertEqual(self._finish(9, "t1")["points_awarded"], 5)
        self.assertEqual(self._finish(50, "t2")["points_awarded"], 30)

    def test_per_game_cap(self):
        PointsLedger.objects.create(
            kid=self.kid, delta=50, reason=PointsLedger.Reason.GAME, ref_type="GameSession", ref_id="old"
        )
        GameSession.objects.create(
            kid=self.kid, visit=self.visit, game=self.game, token_nonce="spent",
            status=GameSession.Status.FINISHED, points_awarded=50,
        )
        # The cap counts ledger rows tied to this visit's sessions, so attach the spend.
        PointsLedger.objects.filter(ref_id="old").update(ref_id=str(GameSession.objects.get(token_nonce="spent").pk))
        result = self._finish(50, "over")
        self.assertEqual(result["points_awarded"], 10)
        self.assertTrue(result["cap_reached"])

    def test_balance_is_sum(self):
        self._finish(10, "b1")
        self.kid.refresh_from_db()
        self.assertEqual(points.balance(self.kid), self.kid.points_balance)
        self.assertEqual(self.kid.points_balance, 10)
