"""
Acceptance tests for the restaurant QR flows (Parts A–D).

Covers King Chef International City and Al Nahda fixtures:
QR landing, retired tokens, review fallback, specials, menu redirect,
and panel scope.
"""

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import Brand, ChangeLog, Outlet, OutletManager, QrCode, SmartPage
from apps.core.panel_permissions import check_outlet_permission
from apps.menu.models import MenuSource, SpecialItem


def _hours_open_all_day():
    return {
        d: {"open": "00:00", "close": "23:59", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class AcceptanceFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Restaurant",
            name_ar="مطعم كينج شيف",
            code="KINGCHEF",
            description="Multi-branch family restaurant.",
            default_phone="04 220 0001",
            google_review_url="https://g.page/r/kingchef-brand/review",
            google_place_id="ChIJ-kingchef-brand",
            social_links={"instagram": "https://instagram.com/kingchefuae"},
            status="active",
        )
        cls.brand_page = SmartPage.objects.create(
            brand=cls.brand,
            slug="kingchef",
            page_title="King Chef Restaurant",
            hero_title="King Chef Restaurant",
            published=True,
            published_at=timezone.now(),
        )
        cls.intl = Outlet.objects.create(
            code="KINGCHEF-INTLCITY",
            slug="international-city",
            official_name="King Chef — International City",
            brand=cls.brand,
            city="International City",
            address="France Cluster, International City, Dubai",
            phone="04 220 0011",
            google_place_id="ChIJ-kingchef-intl-city-demo",
            google_review_url="https://search.google.com/local/writereview?placeid=ChIJ-kingchef-intl-city-demo",
            instagram_url="https://instagram.com/kingchef.internationalcity",
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.nahda = Outlet.objects.create(
            code="KINGCHEF-ALNAHDA",
            slug="al-nahda",
            official_name="King Chef — Al Nahda",
            brand=cls.brand,
            city="Al Nahda",
            address="Al Nahda 2, Dubai",
            phone="04 220 0012",
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.intl_page = SmartPage.objects.create(
            brand=cls.brand, outlet=cls.intl, slug="kingchef-intlcity",
            page_title="King Chef — International City", published=True,
            published_at=timezone.now(),
        )
        cls.nahda_page = SmartPage.objects.create(
            brand=cls.brand, outlet=cls.nahda, slug="kingchef-alnahda",
            page_title="King Chef — Al Nahda", published=True,
            published_at=timezone.now(),
        )
        cls.qr_intl = QrCode.objects.create(
            brand=cls.brand, outlet=cls.intl, destination_page=cls.intl_page,
            source_type="table", label="Table 1",
            qr_code_name="KINGCHEF-INTLCITY-TABLE-001",
            redirect_key="kcic-table-001",
        )
        cls.qr_nahda = QrCode.objects.create(
            brand=cls.brand, outlet=cls.nahda, destination_page=cls.nahda_page,
            source_type="entrance", label="Entrance",
            qr_code_name="KINGCHEF-ALNAHDA-ENTRANCE-001",
            redirect_key="kcnahda-entrance",
        )
        cls.retired = QrCode.objects.create(
            brand=cls.brand, outlet=cls.intl, destination_page=cls.intl_page,
            source_type="table", qr_code_name="KINGCHEF-INTLCITY-TABLE-099",
            redirect_key="kcic-retired", active=False,
        )
        MenuSource.objects.create(
            brand=cls.brand, outlet=cls.intl,
            menu_type=MenuSource.MenuType.EXTERNAL_URL,
            menu_url="https://menu.kingchef.example/international-city",
            active=True,
        )
        SpecialItem.objects.create(
            brand=cls.brand, outlet=cls.intl, kind=SpecialItem.Kind.SIGNATURE,
            title_en="International City Mandi", original_price=49, active=True,
        )
        SpecialItem.objects.create(
            brand=cls.brand, outlet=cls.intl, kind=SpecialItem.Kind.WEEKEND,
            title_en="Friday Grill Platter", original_price=80, offer_price=60,
            active=True,
        )
        SpecialItem.objects.create(
            brand=cls.brand, outlet=cls.intl, kind=SpecialItem.Kind.OFFER,
            title_en="Family Biryani Bucket", original_price=89, offer_price=69,
            active=True,
        )
        cls.head = User.objects.create_user("headoffice", password="pass-head", is_staff=True)
        cls.manager = User.objects.create_user("ic-manager", password="pass-ic")
        profile = OutletManager.objects.create(user=cls.manager, can_edit_contact=True)
        profile.outlets.add(cls.intl)


class QrFlowTests(AcceptanceFixtures):
    def test_unknown_token_is_404(self):
        response = self.client.get("/q/does-not-exist/")
        self.assertEqual(response.status_code, 404)

    def test_retired_token_is_410(self):
        response = self.client.get(reverse("qr_landing", args=[self.retired.redirect_key]))
        self.assertEqual(response.status_code, 410)
        self.assertEqual(ScanEvent.objects.filter(qr_code=self.retired).count(), 0)

    def test_token_urlsafe_underscore_keys_route_correctly(self):
        # secrets.token_urlsafe() mints keys that may contain "_". The format
        # guard must accept them or the landing 404s instead of rendering /
        # returning 410 for retired codes (regression: flaky
        # test_head_office_generates_and_retires_qr).
        active = QrCode.objects.create(
            brand=self.brand, outlet=self.intl, destination_page=self.intl_page,
            source_type="table", label="Table U",
            qr_code_name="KINGCHEF-INTLCITY-TABLE-050",
            redirect_key="kcic_table_U-50",
        )
        response = self.client.get(reverse("qr_landing", args=[active.redirect_key]))
        self.assertEqual(response.status_code, 200)

        active.active = False
        active.save(update_fields=["active"])
        retired_page = self.client.get(reverse("qr_landing", args=[active.redirect_key]))
        self.assertEqual(retired_page.status_code, 410)

    def test_active_token_renders_outlet_and_records_scan(self):
        response = self.client.get(reverse("qr_landing", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "International City")
        self.assertContains(response, "SPECIALS")
        self.assertContains(response, "CHECKOUT OUR MENU")
        self.assertContains(response, "REVIEW US ON GOOGLE")
        self.assertEqual(ScanEvent.objects.filter(qr_code=self.qr_intl).count(), 1)
        self.qr_intl.refresh_from_db()
        self.assertEqual(self.qr_intl.scan_count, 1)
        self.assertEqual(self.client.session["qr"], self.qr_intl.pk)

    def test_game_button_stays_and_game_page_shows_coming_soon(self):
        """The "Play a Game & Win a Discount" button is permanent customer UI."""
        landing = self.client.get(reverse("qr_landing", args=["kcic-table-001"]))
        self.assertContains(landing, "Play a Game")
        game_page = self.client.get(reverse("qr_game", args=["kcic-table-001"]))
        self.assertEqual(game_page.status_code, 200)
        self.assertContains(game_page, "coming soon")
        # Unknown keys still 404.
        self.assertEqual(
            self.client.get(reverse("qr_game", args=["does-not-exist"])).status_code, 404
        )

    def test_arabic_query_sets_rtl(self):
        response = self.client.get(reverse("qr_landing", args=["kcic-table-001"]) + "?lang=ar")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')

    def test_review_uses_outlet_link_then_brand_fallback(self):
        intl = self.client.get(reverse("qr_review_redirect", args=["kcic-table-001"]))
        self.assertEqual(intl.status_code, 302)
        self.assertIn("intl-city-demo", intl["Location"])

        nahda = self.client.get(reverse("qr_review_redirect", args=["kcnahda-entrance"]))
        self.assertEqual(nahda.status_code, 302)
        self.assertIn("kingchef-brand", nahda["Location"])
        self.assertEqual(
            TapEvent.objects.filter(action=TapEvent.ActionType.REVIEW).count(), 2
        )

    def test_instagram_prefers_outlet_url(self):
        response = self.client.get(reverse("qr_instagram_redirect", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("kingchef.internationalcity", response["Location"])

    def test_specials_page_hides_weekend_price(self):
        response = self.client.get(reverse("customer_specials", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "International City Mandi")
        self.assertContains(response, "Friday Grill Platter")
        self.assertContains(response, "Family Biryani Bucket")
        self.assertContains(response, "69")
        body = response.content.decode()
        platter_at = body.index("Friday Grill Platter")
        window = body[platter_at:platter_at + 400]
        self.assertNotIn("80", window)
        self.assertEqual(
            TapEvent.objects.filter(qr_code=self.qr_intl, action="specials").count(), 1
        )

    def test_menu_external_source_redirects(self):
        response = self.client.get(reverse("customer_menu", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://menu.kingchef.example/international-city")


class PanelScopeTests(AcceptanceFixtures):
    def test_anonymous_panel_redirects_to_login(self):
        response = self.client.get(reverse("panel_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/panel/login/", response["Location"])

    def test_manager_sees_only_assigned_outlet(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_outlets"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "International City")
        self.assertNotContains(response, "Al Nahda")

    def test_manager_cannot_edit_other_outlet(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_outlet_edit", args=[self.nahda.pk]))
        self.assertEqual(response.status_code, 403)
        with self.assertRaises(PermissionDenied):
            check_outlet_permission(self.manager, self.nahda)

    def test_manager_can_update_own_outlet_review_link(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_outlet_edit", args=[self.intl.pk]), {
            "phone": "04 220 0099",
            "google_review_url": "https://g.page/r/intl-updated/review",
            "google_place_id": "ChIJ-updated",
            "instagram_url": "https://instagram.com/kingchef.internationalcity",
            "menu_url": "",
        })
        self.assertEqual(response.status_code, 302)
        self.intl.refresh_from_db()
        self.assertEqual(self.intl.phone, "04 220 0099")
        self.assertTrue(ChangeLog.objects.filter(action="OUTLET_EDIT", outlet=self.intl).exists())

    def test_head_office_adds_outlet_and_sees_review_warning(self):
        self.client.login(username="headoffice", password="pass-head")
        listing = self.client.get(reverse("panel_outlets"))
        self.assertContains(listing, "Al Nahda")
        self.assertContains(listing, "Brand Fallback")

        created = self.client.post(reverse("panel_outlet_add"), {
            "brand": self.brand.pk,
            "official_name": "King Chef — Karama",
            "code": "KINGCHEF-KARAMA",
            "city": "Karama",
            "emirate": "Dubai",
            "address": "Karama, Dubai",
            "phone": "04 220 0020",
        })
        self.assertEqual(created.status_code, 302)
        outlet = Outlet.objects.get(code="KINGCHEF-KARAMA")
        self.assertTrue(SmartPage.objects.filter(outlet=outlet, published=True).exists())

    def test_head_office_generates_and_retires_qr(self):
        self.client.login(username="headoffice", password="pass-head")
        before = QrCode.objects.filter(outlet=self.intl, active=True).count()
        response = self.client.post(reverse("panel_qr_generate"), {
            "outlet": self.intl.pk,
            "source_type": "counter",
            "label": "Counter 1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(QrCode.objects.filter(outlet=self.intl, active=True).count(), before + 1)
        created = QrCode.objects.get(label="Counter 1")
        self.assertTrue(created.qr_code_name.startswith("KINGCHEF-INTLCITY-COUNTER-"))

        regen = self.client.get(reverse("panel_qr_regenerate", args=[created.pk]))
        self.assertEqual(regen.status_code, 302)
        created.refresh_from_db()
        self.assertFalse(created.active)
        retired_page = self.client.get(reverse("qr_landing", args=[created.redirect_key]))
        self.assertEqual(retired_page.status_code, 410)

    def test_manager_cannot_generate_qr(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_qr_generate"))
        self.assertEqual(response.status_code, 403)

    def test_special_add_is_scoped(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_special_add"), {
            "brand": self.brand.pk,
            "outlet": self.intl.pk,
            "kind": "signature",
            "title_en": "Counter Karak",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SpecialItem.objects.filter(title_en="Counter Karak", outlet=self.intl).exists())

        cross = self.client.post(reverse("panel_special_add"), {
            "brand": self.brand.pk,
            "outlet": self.nahda.pk,
            "kind": "signature",
            "title_en": "Should Not Land",
        })
        self.assertEqual(cross.status_code, 404)
        self.assertFalse(SpecialItem.objects.filter(title_en="Should Not Land").exists())
