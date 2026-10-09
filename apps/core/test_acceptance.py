"""
Acceptance tests for the restaurant QR flows (Parts A–D).

Covers King Chef International City and Al Nahda fixtures:
QR landing, retired tokens, review fallback, specials, menu redirect,
and panel scope.
"""

import json
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import (
    Brand,
    ChangeLog,
    Outlet,
    OutletManager,
    PageModule,
    QrCode,
    SmartPage,
)
from apps.core.panel_permissions import check_outlet_permission
from apps.engagement.models import Feedback, Lead
from apps.menu.models import MenuCategory, MenuItem, MenuSource, SpecialItem


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

    def test_manager_can_generate_qr_for_own_branch_only(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_qr_generate"))
        self.assertEqual(response.status_code, 200)

        created = self.client.post(reverse("panel_qr_generate"), {
            "outlet": self.intl.pk,
            "source_type": "counter",
            "label": "Manager Counter",
        })
        self.assertEqual(created.status_code, 302)
        self.assertTrue(
            QrCode.objects.filter(label="Manager Counter", outlet=self.intl).exists()
        )

        cross = self.client.post(reverse("panel_qr_generate"), {
            "outlet": self.nahda.pk,
            "source_type": "counter",
            "label": "Should Not Land",
        })
        self.assertEqual(cross.status_code, 404)
        self.assertFalse(QrCode.objects.filter(label="Should Not Land").exists())

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


class UsersPanelTests(AcceptanceFixtures):
    def test_manager_cannot_open_users_panel(self):
        self.client.login(username="ic-manager", password="pass-ic")
        for url in (
            reverse("panel_users"),
            reverse("panel_user_add"),
            reverse("panel_user_edit", args=[self.head.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_head_office_opens_users_panel(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.get(reverse("panel_users"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ic-manager")

    def test_head_office_creates_outlet_manager(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.post(reverse("panel_user_add"), {
            "username": "nahda-manager",
            "password": "pass-nahda",
            "role": "outlet_manager",
            "outlets": [self.nahda.pk],
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="nahda-manager")
        self.assertFalse(user.is_staff)
        self.assertEqual(
            list(user.outlet_manager_profile.managed_outlets()), [self.nahda]
        )

        self.client.logout()
        self.client.login(username="nahda-manager", password="pass-nahda")
        listing = self.client.get(reverse("panel_outlets"))
        self.assertContains(listing, "Al Nahda")
        self.assertNotContains(listing, "International City")

    def test_head_office_creates_brand_manager_for_whole_brand(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.post(reverse("panel_user_add"), {
            "username": "kc-brand",
            "password": "pass-brand",
            "role": "brand_manager",
            "brand": self.brand.pk,
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="kc-brand")
        self.assertEqual(user.outlet_manager_profile.role, OutletManager.Role.BRAND)

        self.client.logout()
        self.client.login(username="kc-brand", password="pass-brand")
        listing = self.client.get(reverse("panel_outlets"))
        self.assertContains(listing, "International City")
        self.assertContains(listing, "Al Nahda")

    def test_head_office_resets_password_and_deletes_user(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.post(
            reverse("panel_user_edit", args=[self.manager.pk]),
            {
                "action": "save",
                "role": "outlet_manager",
                "outlets": [self.intl.pk],
                "password": "new-pass-123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.check_password("new-pass-123"))

        response = self.client.post(
            reverse("panel_user_edit", args=[self.manager.pk]),
            {"action": "delete"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="ic-manager").exists())


class StructureLockTests(AcceptanceFixtures):
    def test_manager_cannot_add_outlet(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_outlet_add"), {
            "brand": self.brand.pk,
            "official_name": "King Chef — Sneaky",
            "code": "KINGCHEF-SNEAKY",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Outlet.objects.filter(code="KINGCHEF-SNEAKY").exists())

    def test_manager_cannot_edit_brand(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_brand_add"), {
            "name_en": "Sneaky Brand",
            "code": "SNEAKY",
        })
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("panel_brand_edit", args=[self.brand.pk]),
            {"name_en": "Hijacked Name"},
        )
        self.assertEqual(response.status_code, 403)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.name_en, "King Chef Restaurant")

    def test_manager_cannot_change_branch_identity(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(
            reverse("panel_outlet_edit", args=[self.intl.pk]),
            {
                "official_name": "Hijacked Branch",
                "code": "KINGCHEF-HIJACKED",
                "phone": "04 220 0077",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.intl.refresh_from_db()
        self.assertEqual(self.intl.phone, "04 220 0077")
        self.assertEqual(self.intl.official_name, "King Chef — International City")
        self.assertEqual(self.intl.code, "KINGCHEF-INTLCITY")

    def test_head_office_can_change_branch_identity(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.post(
            reverse("panel_outlet_edit", args=[self.nahda.pk]),
            {
                "official_name": "King Chef — Al Nahda 24h",
                "code": "KINGCHEF-ALNAHDA",
                "city": "Al Nahda",
                "emirate": "Dubai",
                "address": "Al Nahda 2, Dubai",
                "brand": self.brand.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.nahda.refresh_from_db()
        self.assertEqual(self.nahda.official_name, "King Chef — Al Nahda 24h")


class MenuEditTests(AcceptanceFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category = MenuCategory.objects.create(brand=cls.brand, name_en="Starters")
        cls.base_item = MenuItem.objects.create(
            category=cls.category, brand=cls.brand, name_en="Hummus",
            regular_price=8, available=True,
        )
        cls.intl_item = MenuItem.objects.create(
            category=cls.category, brand=cls.brand, outlet=cls.intl,
            name_en="Intl Kebab", regular_price=45, available=True,
        )

    def test_manager_sets_menu_source_for_own_branch(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_menus"), {
            "brand": self.brand.pk,
            "outlet": self.intl.pk,
            "menu_type": "external_url",
            "menu_url": "https://menu.kingchef.example/intl",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MenuSource.objects.filter(
                outlet=self.intl, menu_url="https://menu.kingchef.example/intl"
            ).exists()
        )

    def test_manager_cannot_set_brand_menu_source(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_menus"), {
            "brand": self.brand.pk,
            "outlet": "",
            "menu_type": "external_url",
            "menu_url": "https://menu.kingchef.example/brand",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MenuSource.objects.filter(outlet__isnull=True).exists())

    def test_manager_adds_and_toggles_branch_menu_item(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_menu_item_add"), {
            "brand": self.brand.pk,
            "outlet": self.intl.pk,
            "category": self.category.pk,
            "name_en": "Intl Special",
            "regular_price": "35.00",
            "available": "on",
        })
        self.assertEqual(response.status_code, 302)
        item = MenuItem.objects.get(name_en="Intl Special")
        self.assertEqual(item.outlet, self.intl)

        self.client.post(reverse("panel_menu_item_toggle", args=[item.pk]))
        item.refresh_from_db()
        self.assertFalse(item.available)

    def test_manager_cannot_add_brand_level_item(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_menu_item_add"), {
            "brand": self.brand.pk,
            "outlet": "",
            "category": self.category.pk,
            "name_en": "Sneaky Base Item",
            "regular_price": "10.00",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MenuItem.objects.filter(name_en="Sneaky Base Item").exists())

    def test_manager_cannot_edit_brand_level_item(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(
            reverse("panel_menu_item_edit", args=[self.base_item.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_manager_creates_branch_override_of_brand_item(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(
            reverse("panel_menu_item_override", args=[self.base_item.pk]),
            {"outlet": self.intl.pk},
        )
        self.assertEqual(response.status_code, 302)
        override = MenuItem.objects.get(outlet=self.intl, overrides=self.base_item)
        self.assertEqual(override.name_en, "Hummus")
        self.assertEqual(override.regular_price, self.base_item.regular_price)


class CrmTests(AcceptanceFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lead_intl = Lead.objects.create(
            brand=cls.brand, outlet=cls.intl,
            lead_type=Lead.LeadType.GROUP_BOOKING,
            customer_name="Saeed Al Mansoori", phone="050 111 2233",
            message="Table for 20 on Friday.",
        )
        cls.lead_nahda = Lead.objects.create(
            brand=cls.brand, outlet=cls.nahda,
            lead_type=Lead.LeadType.EVENT,
            customer_name="Mariam Hassan", message="Birthday setup.",
        )
        cls.fb_intl = Feedback.objects.create(
            brand=cls.brand, outlet=cls.intl, rating=5,
            category=Feedback.Category.SERVICE,
            message="Fast service, great mandi.",
        )

    def test_manager_sees_only_own_branch_leads(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_leads"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saeed Al Mansoori")
        self.assertNotContains(response, "Mariam Hassan")

    def test_manager_updates_own_lead_status(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(
            reverse("panel_lead_update", args=[self.lead_intl.pk]),
            {"status": "closed", "notes": "Booked for Friday."},
        )
        self.assertEqual(response.status_code, 302)
        self.lead_intl.refresh_from_db()
        self.assertEqual(self.lead_intl.status, Lead.Status.CLOSED)
        self.assertEqual(self.lead_intl.notes, "Booked for Friday.")

    def test_manager_cannot_touch_other_branch_lead(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(
            reverse("panel_lead_update", args=[self.lead_nahda.pk]),
            {"status": "closed"},
        )
        self.assertEqual(response.status_code, 404)
        self.lead_nahda.refresh_from_db()
        self.assertEqual(self.lead_nahda.status, Lead.Status.NEW)

    def test_feedback_list_and_resolution_update(self):
        self.client.login(username="ic-manager", password="pass-ic")
        listing = self.client.get(reverse("panel_feedback"))
        self.assertContains(listing, "Fast service, great mandi.")

        response = self.client.post(
            reverse("panel_feedback_update", args=[self.fb_intl.pk]),
            {"status": "resolved", "resolution": "Thanked the team."},
        )
        self.assertEqual(response.status_code, 302)
        self.fb_intl.refresh_from_db()
        self.assertEqual(self.fb_intl.status, Feedback.Status.RESOLVED)

    def test_head_office_sees_everything(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.get(reverse("panel_leads"))
        self.assertContains(response, "Saeed Al Mansoori")
        self.assertContains(response, "Mariam Hassan")


class PlaceIdLinkTests(AcceptanceFixtures):
    """Google Place ID contract (Google Place IDs document): when Review URL
    and maps URL are left empty, the links are built from the Place ID."""

    def setUp(self):
        # Mirror production module config (seed_demo MODULE_ORDER): the review
        # card and the Maps button render only when their modules are enabled.
        PageModule.objects.bulk_create(
            [
                PageModule(page=self.intl_page, module_type="google_review"),
                PageModule(page=self.intl_page, module_type="directions"),
            ]
        )

    def test_review_link_built_from_place_id_when_review_url_empty(self):
        Outlet.objects.filter(pk=self.intl.pk).update(google_review_url="")
        response = self.client.get(reverse("qr_review_redirect", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://search.google.com/local/writereview?placeid=ChIJ-kingchef-intl-city-demo",
        )

    def test_smart_page_review_button_and_maps_use_place_id(self):
        Outlet.objects.filter(pk=self.intl.pk).update(
            google_review_url="", google_maps_url=""
        )
        response = self.client.get(reverse("smart_page", args=["kingchef-intlcity"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "writereview?placeid=ChIJ-kingchef-intl-city-demo")
        self.assertContains(response, "query_place_id=ChIJ-kingchef-intl-city-demo")


class ReviewComposerTests(AcceptanceFixtures):
    """Review composer (spec section 39): write on the smart page, get
    polished variants, copy one, then post it on Google."""

    def setUp(self):
        # The smart-page review module renders only when enabled (spec §11).
        PageModule.objects.bulk_create(
            [
                PageModule(page=self.intl_page, module_type="google_review"),
                PageModule(page=self.intl_page, module_type="directions"),
            ]
        )

    def test_landing_review_card_opens_composer(self):
        response = self.client.get(reverse("qr_landing", args=["kcic-table-001"]))
        self.assertContains(response, reverse("qr_review_write", args=["kcic-table-001"]))

    def test_qr_composer_renders_and_google_button_is_tap_tracked(self):
        response = self.client.get(reverse("qr_review_write", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suggest improved versions")
        self.assertContains(response, "Open Google &amp; post my review")
        # the composer's Google button goes through the tap-tracked redirect
        self.assertContains(response, reverse("qr_review", args=["kcic-table-001"]))
        handoff = self.client.get(reverse("qr_review", args=["kcic-table-001"]))
        self.assertEqual(handoff.status_code, 302)
        self.assertEqual(
            handoff["Location"],
            "https://search.google.com/local/writereview?placeid=ChIJ-kingchef-intl-city-demo",
        )

    def test_composer_404_for_unknown_key(self):
        response = self.client.get(reverse("qr_review_write", args=["no-such-key"]))
        self.assertEqual(response.status_code, 404)

    def test_composer_is_single_box_flow(self):
        """Simplified composer (client feedback 2026-10-09): ONE review box,
        suggestions load straight into it, one primary Google hand-off."""
        response = self.client.get(reverse("qr_review_write", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="review-draft"')   # the one box
        self.assertNotContains(response, 'id="review-final"')  # no second box
        self.assertContains(response, 'id="variants"')        # tap-to-use rows
        self.assertContains(response, 'id="suggest-btn"')
        self.assertContains(response, 'id="google-open"')
        # Copy sits beside Suggest, on its left, right under the box
        # (client feedback 2026-10-09: "copy button & suggest button side by side")
        page = response.content.decode()
        self.assertIn('id="copy-btn"', page)
        self.assertLess(page.index('id="copy-btn"'), page.index('id="suggest-btn"'))

    def test_shows_only_three_suggestions(self):
        """Client feedback 2026-10-09: show at most 3 suggestions."""
        js = (
            settings.BASE_DIR / "static" / "js" / "review_composer.js"
        ).read_text(encoding="utf-8")
        self.assertIn("slice(0, 3)", js)

    def test_assist_api_asks_llm_and_returns_plain_unlabeled_strings(self):
        """Suggestions come from the LLM as plain strings: no tone labels,
        no emojis, no canned sentences (client feedback, 2026-10-09)."""
        fake_content = json.dumps([
            "Nice food, fresh and tasty every time.",
            "Nice food! Loved the mixed grill \U0001F60B",
            {"label": "Warm", "text": "Nice food. Friendly and quick service."},
            "Nice food. Portions are generous.",
            "Nice food, we will come back again.",
            "Nice food. Good tea and fresh bread.",
        ])
        with mock.patch.dict("os.environ", {"MIMO_API_KEY": "test-key"}):
            with mock.patch("apps.core.review_assist._post_json") as post:
                post.return_value = {
                    "choices": [{"message": {"content": fake_content}}]
                }
                response = self.client.post(
                    reverse("review_assist"), {"text": "nice food"}
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "mimo")
        self.assertEqual(len(payload["variants"]), 6)
        for variant in payload["variants"]:
            self.assertIsInstance(variant, str)  # plain text, no {"label": ...}
            self.assertNotIn("\U0001F60B", variant)  # emoji stripped
        # the guest's draft is what went to the model
        sent = post.call_args[0][1]["messages"][1]["content"]
        self.assertIn("nice food", sent)
        # the real MiMo endpoint, not a canned generator
        self.assertIn("xiaomimimo.com", post.call_args[0][0])

    def test_assist_api_falls_back_to_token_plan_endpoint(self):
        """MiMo's token-plan endpoint (token-plan-sgp) is tried when the
        main API fails — client request 2026-10-09."""
        ok = {"choices": [{"message": {"content": json.dumps(
            ["v one", "v two", "v three", "v four", "v five", "v six"])}}]}
        calls = []

        def fake_post(url, payload, headers=None):
            calls.append(url)
            if "token-plan-sgp" not in url:
                raise OSError("main endpoint down")
            return ok

        with mock.patch.dict("os.environ", {"MIMO_API_KEY": "test-key"}):
            with mock.patch("apps.core.review_assist._post_json",
                            side_effect=fake_post):
                response = self.client.post(
                    reverse("review_assist"), {"text": "nice food"}
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "mimo")
        self.assertEqual(payload["variants"][0], "v one")
        # main API was tried first, then the token-plan endpoint answered
        self.assertIn("api.xiaomimimo.com", calls[0])
        self.assertIn("token-plan-sgp.xiaomimimo.com", calls[-1])

    def test_assist_api_token_plan_key_alone_enables_mimo(self):
        """A dedicated token-plan key (no main key) is enough to use MiMo."""
        ok = {"choices": [{"message": {"content": json.dumps(
            ["Nice food.", "Nice food, fresh and tasty.",
             "Nice food. Friendly service.", "Nice food, we will return.",
             "Nice food. Generous portions.", "Nice food and good tea."])}}]}
        with mock.patch.dict("os.environ",
                             {"MIMO_API_KEY": "",
                              "MIMO_TOKEN_PLAN_API_KEY": "plan-key"}):
            with mock.patch("apps.core.review_assist._post_json",
                            return_value=ok) as post:
                response = self.client.post(
                    reverse("review_assist"), {"text": "nice food"}
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "mimo")
        self.assertIn("token-plan-sgp.xiaomimimo.com", post.call_args[0][0])
        self.assertEqual(
            post.call_args[1]["headers"]["Authorization"], "Bearer plan-key"
        )

    def test_assist_api_without_key_tidies_own_words_only(self):
        """No key configured: the guest's own words are tidied — nothing invented."""
        with mock.patch("apps.core.review_assist._has_key", return_value=False):
            response = self.client.post(
                reverse("review_assist"),
                {"text": "food was amazing i loved the mandi"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "local")
        self.assertEqual(payload["variants"], ["Food was amazing I loved the mandi."])

    def test_assist_api_rejects_bad_input(self):
        url = reverse("review_assist")
        self.assertEqual(self.client.post(url, {"text": "  "}).status_code, 400)
        self.assertEqual(self.client.post(url, {"text": "x" * 2500}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_smart_page_cta_opens_composer_and_keeps_direct_google_link(self):
        response = self.client.get(reverse("smart_page", args=["kingchef-intlcity"]))
        self.assertContains(
            response, reverse("smart_review_write", args=["kingchef-intlcity"])
        )
        # Place ID contract preserved: the direct Google link is still rendered
        self.assertContains(response, "writereview?placeid=ChIJ-kingchef-intl-city-demo")

    def test_smart_composer_google_button_opens_review_url(self):
        response = self.client.get(
            reverse("smart_review_write", args=["kingchef-intlcity"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "writereview?placeid=ChIJ-kingchef-intl-city-demo")
