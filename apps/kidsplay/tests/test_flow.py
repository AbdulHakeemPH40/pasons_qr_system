from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.kidsplay.models import Family, OTPChallenge, TableVisit
from apps.kidsplay.services import otp


class ParentFlowTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name_en="King Chef Restaurant", code="KINGCHEF")
        outlet = Outlet.objects.create(brand=brand, official_name="King Chef International City", code="KINGCHEF-IC")
        page = SmartPage.objects.create(brand=brand, outlet=outlet, slug="kingchef-ic", page_title="King Chef")
        self.qr = QrCode.objects.create(
            qr_code_name="KINGCHEF-IC-TABLE-001",
            destination_page=page,
            source_type=QrCode.SourceType.TABLE,
            brand=brand,
            outlet=outlet,
            redirect_key="kcic-table-001",
        )

    def test_unknown_table_is_404(self):
        response = self.client.get("/t/not-a-table/")
        self.assertEqual(response.status_code, 404)

    def test_landing_to_hub(self):
        response = self.client.get("/t/kcic-table-001/")
        self.assertContains(response, "Play & Win")
        self.client.post("/t/kcic-table-001/phone/", {"phone": "0501234567"})
        OTPChallenge.objects.update(code_hash=otp._hash("+971501234567", "123456"))
        response = self.client.post("/t/kcic-table-001/verify/", {"code": "123456", "consent": "1"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/t/kcic-table-001/kids/", {"nickname": "Noor", "avatar": "burger"})
        self.assertRedirects(response, "/t/kcic-table-001/hub/", fetch_redirect_response=False)
        hub = self.client.get("/t/kcic-table-001/hub/")
        self.assertContains(hub, "Noor")
        self.assertContains(hub, "Burger Stack")
        self.assertEqual(TableVisit.objects.count(), 1)
        self.assertTrue(TableVisit.objects.get().is_active())

    def test_blocked_nickname(self):
        self.client.get("/t/kcic-table-001/")
        self.client.post("/t/kcic-table-001/phone/", {"phone": "0501234567"})
        OTPChallenge.objects.update(code_hash=otp._hash("+971501234567", "123456"))
        self.client.post("/t/kcic-table-001/verify/", {"code": "123456", "consent": "1"})
        response = self.client.post("/t/kcic-table-001/kids/", {"nickname": "shit", "avatar": "burger"})
        self.assertContains(response, "different nickname")
        self.assertEqual(Family.objects.get().kids.count(), 0)

    def test_closed_visit_is_not_active(self):
        family = Family.objects.create(phone="+971501111111", consent_at=timezone.now())
        visit = TableVisit.objects.create(
            family=family,
            qr_code=self.qr,
            outlet=self.qr.outlet,
            expires_at=timezone.now() + timedelta(hours=1),
            closed_at=timezone.now(),
        )
        self.assertFalse(visit.is_active())
