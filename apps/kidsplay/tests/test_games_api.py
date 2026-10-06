import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.kidsplay.models import Family, GameSession, KidProfile, OTPChallenge, PlayGame, TableVisit
from apps.kidsplay.services import games, otp


class GameAPITests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name_en="King Chef Restaurant", code="KINGCHEF2")
        outlet = Outlet.objects.create(brand=brand, official_name="King Chef IC", code="KINGCHEF-IC2")
        page = SmartPage.objects.create(brand=brand, outlet=outlet, slug="kingchef-ic2", page_title="King Chef")
        self.qr = QrCode.objects.create(
            qr_code_name="KINGCHEF-IC2-TABLE-001",
            destination_page=page,
            source_type=QrCode.SourceType.TABLE,
            brand=brand,
            outlet=outlet,
            redirect_key="kp-table",
        )
        self.client.get("/t/kp-table/")
        self.client.post("/t/kp-table/phone/", {"phone": "0509998877"})
        OTPChallenge.objects.update(code_hash=otp._hash("+971509998877", "123456"))
        self.client.post("/t/kp-table/verify/", {"code": "123456", "consent": "1"})
        self.client.post("/t/kp-table/kids/", {"nickname": "Noor", "avatar": "pizza"})
        self.game = PlayGame.objects.get(slug="burger-stack")

    def _start(self):
        response = self.client.post(
            "/api/kidsplay/game/start",
            data=json.dumps({"game": "burger-stack"}),
            content_type="application/json",
        )
        return response

    def test_start_requires_visit(self):
        TableVisit.objects.update(closed_at=timezone.now())
        response = self._start()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "no_active_visit")

    def test_start_and_finish(self):
        started = self._start()
        self.assertEqual(started.status_code, 200)
        token = started.json()["token"]
        GameSession.objects.update(started_at=timezone.now() - timedelta(seconds=30))
        finished = self.client.post(
            "/api/kidsplay/game/finish",
            data=json.dumps({"token": token, "score": 27, "duration_ms": 20000}),
            content_type="application/json",
        )
        body = finished.json()
        self.assertEqual(body["points_awarded"], 20)
        self.assertEqual(body["balance"], 20)

    def test_tampered_score_awards_nothing(self):
        token = self._start().json()["token"]
        GameSession.objects.update(started_at=timezone.now() - timedelta(seconds=30))
        finished = self.client.post(
            "/api/kidsplay/game/finish",
            data=json.dumps({"token": token, "score": 99999, "duration_ms": 20000}),
            content_type="application/json",
        )
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()["points_awarded"], 0)

    def test_token_is_single_use(self):
        token = self._start().json()["token"]
        GameSession.objects.update(started_at=timezone.now() - timedelta(seconds=30))
        payload = json.dumps({"token": token, "score": 12, "duration_ms": 20000})
        first = self.client.post("/api/kidsplay/game/finish", data=payload, content_type="application/json")
        second = self.client.post("/api/kidsplay/game/finish", data=payload, content_type="application/json")
        self.assertGreater(first.json()["points_awarded"], 0)
        self.assertEqual(second.json()["points_awarded"], 0)

    def test_wrong_kid_cannot_finish(self):
        token = self._start().json()["token"]
        other = KidProfile.objects.create(family=Family.objects.get(), nickname="Sam", avatar="juice")
        result = games.finish_game(other, token, 12, 20000)
        self.assertEqual(result["points_awarded"], 0)

    def test_rate_limit(self):
        for _ in range(4):
            self.assertEqual(self._start().status_code, 200)
        self.assertEqual(self._start().status_code, 429)
