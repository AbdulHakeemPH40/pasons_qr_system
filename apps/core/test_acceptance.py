"""
Acceptance tests for the restaurant QR flows (Parts A–D).

Covers King Chef International City and Al Nahda fixtures:
QR landing, retired tokens, review fallback, specials, menu redirect,
and panel scope.
"""

import json
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ScanEvent, TapEvent
from apps.core.models import (
    Brand,
    ChangeLog,
    Department,
    Outlet,
    OutletManager,
    PageModule,
    QrCode,
    SmartPage,
)
from apps.core.panel_permissions import (
    check_outlet_permission,
    scoped_brands,
    scoped_outlets,
)
from apps.engagement.models import Feedback, Lead
from apps.menu.models import MenuCategory, MenuItem, MenuSource, SpecialItem
from apps.menu.top_picks import TOP_FOOD_CATEGORY, TOP_DRINK_CATEGORY


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
            address="Italy Cluster, International City, Dubai",
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
        cls.head = User.objects.create_user(
            "headoffice", password="pass-head", is_staff=True,
            email="admin@pasonsgrp.com",
        )
        cls.manager = User.objects.create_user(
            "ic-manager", password="pass-ic",
            email="om.kingchef-intlcity@pasonsgrp.com",
        )
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

    def test_landing_shows_play_card_with_perk_promise(self):
        """Client copy 2026-10-14 (via user): the card advertises the perk
        'Win a discount or dessert', honoured by staff. Supersedes the
        2026-10-10 play-only decision for the landing card copy."""
        landing = self.client.get(reverse("qr_landing", args=["kcic-table-001"]))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "PLAY A GAME")
        self.assertContains(landing, "Win a discount or dessert")
        self.assertContains(landing, reverse("qr_game", args=["kcic-table-001"]))
        # The promise is perk-only: no coupon language.
        self.assertNotIn("coupon", landing.content.decode().lower())
        # The printed-sheet URL keeps working and opens the games hub.
        entry = self.client.get("/q/kcic-table-001/game/")
        self.assertEqual(entry.status_code, 302)
        self.assertIn(reverse("games_hub"), entry["Location"])

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

    def test_instagram_card_promises_gift_with_lucky_draw_popup(self):
        """Client copy 2026-10-14 (via user): the Instagram card sub-line
        reads 'Follow and win a special gift' and tapping the card opens a
        lucky-draw popup ('You are entered in the lucky draw!'). Instagram
        never reports who followed, so the tap-tracked redirect stays the
        single draw-entry log: the popup's CTA must point at it, and the
        card keeps its href as the no-JS fallback."""
        landing = self.client.get(reverse("qr_landing", args=["kcic-table-001"]))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "Follow and win a special gift")
        self.assertNotIn("New plates and stories", landing.content.decode())
        # the popup celebrates the entry and is hidden until the card tap
        self.assertContains(landing, "You are entered in the lucky draw")
        self.assertContains(landing, 'id="ig-draw-popup" hidden')
        # one entry log only: the three Instagram links (contact circle,
        # card as no-JS fallback, popup CTA) all use the same redirect, so
        # every tap is one TapEvent and the draw list never doubles.
        tracked = reverse("qr_instagram_redirect", args=["kcic-table-001"])
        self.assertEqual(landing.content.decode().count(f'href="{tracked}"'), 3)
        self.assertEqual(
            TapEvent.objects.filter(
                qr_code=self.qr_intl, action=TapEvent.ActionType.INSTAGRAM
            ).count(),
            0,
        )

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


class BrandManagerScopeTests(AcceptanceFixtures):
    """Locks the Brand Manager tier: confined to its own brand, on every screen.

    The shared fixture holds a single brand, so this class adds a competing
    brand (Paramount) with one special, lead and feedback that live only on it.
    The contract locked here matches the live views exactly:

      - panel_outlet_edit calls check_outlet_permission, so a foreign outlet
        is a 403.
      - special / lead / feedback detail views filter the row out of the
        queryset, so a foreign row is a 404.
      - Both mean "blocked". 200 would be the bug this guards against.

    This tier had no test coverage before; the outlet-manager tier is covered
    separately in PanelScopeTests.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_brand = Brand.objects.create(
            name_en="Paramount Restaurant", code="PARAMOUNT", status="active",
        )
        cls.other_outlet = Outlet.objects.create(
            code="PARAMOUNT-QUSAIS", slug="paramount-qusais",
            official_name="Paramount \u2014 Al Qusais", brand=cls.other_brand,
            city="Al Qusais", active=True,
        )
        cls.bm = User.objects.create_user("bm-kingchef", password="pass-bm")
        OutletManager.objects.create(
            user=cls.bm, role=OutletManager.Role.BRAND, brand=cls.brand,
        )
        cls.other_special = SpecialItem.objects.create(
            brand=cls.other_brand, outlet=cls.other_outlet,
            kind=SpecialItem.Kind.OFFER, title_en="Paramount Only Deal",
            original_price=50, active=True,
        )
        cls.other_lead = Lead.objects.create(
            brand=cls.other_brand, outlet=cls.other_outlet,
            customer_name="Paramount Hall Booking",
        )
        cls.other_feedback = Feedback.objects.create(
            brand=cls.other_brand, outlet=cls.other_outlet,
            rating=2, category=Feedback.Category.SERVICE,
            message="Paramount slow service",
        )
        cls.own_lead = Lead.objects.create(
            brand=cls.brand, outlet=cls.intl, customer_name="King Chef Booking",
        )
        cls.own_feedback = Feedback.objects.create(
            brand=cls.brand, outlet=cls.intl, rating=5,
            category=Feedback.Category.FOOD, message="Great mandi",
        )

    def setUp(self):
        self.client.login(username="bm-kingchef", password="pass-bm")

    def test_brand_manager_sees_own_brand_outlets_only(self):
        response = self.client.get(reverse("panel_outlets"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "International City")
        self.assertNotContains(response, "Paramount")

    def test_brand_manager_blocked_from_other_brand_outlet(self):
        response = self.client.get(
            reverse("panel_outlet_edit", args=[self.other_outlet.pk])
        )
        self.assertEqual(response.status_code, 403)
        with self.assertRaises(PermissionDenied):
            check_outlet_permission(self.bm, self.other_outlet)

    def test_brand_manager_cannot_open_other_brand_special(self):
        response = self.client.get(
            reverse("panel_special_edit", args=[self.other_special.pk])
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertNotEqual(response.status_code, 200)

    def test_brand_manager_cannot_touch_other_brand_lead(self):
        response = self.client.post(
            reverse("panel_lead_update", args=[self.other_lead.pk]),
            {"status": Lead.Status.CLOSED},
        )
        self.assertIn(response.status_code, (403, 404))
        self.other_lead.refresh_from_db()
        self.assertEqual(self.other_lead.status, Lead.Status.NEW)

    def test_brand_manager_cannot_touch_other_brand_feedback(self):
        response = self.client.post(
            reverse("panel_feedback_update", args=[self.other_feedback.pk]),
            {"status": Feedback.Status.RESOLVED},
        )
        self.assertIn(response.status_code, (403, 404))
        self.other_feedback.refresh_from_db()
        self.assertEqual(self.other_feedback.status, Feedback.Status.NEW)

    def test_brand_manager_lists_hide_other_brand_rows(self):
        leads = self.client.get(reverse("panel_leads"))
        self.assertContains(leads, "King Chef Booking")
        self.assertNotContains(leads, "Paramount Hall Booking")

        feedback = self.client.get(reverse("panel_feedback"))
        self.assertContains(feedback, "Great mandi")
        self.assertNotContains(feedback, "Paramount slow service")

    def test_brand_manager_can_reach_own_brand_outlet(self):
        # Sanity: the same URL that 403s on a foreign outlet works on an own one.
        response = self.client.get(reverse("panel_outlet_edit", args=[self.intl.pk]))
        self.assertEqual(response.status_code, 200)


class NoProfileScopeTests(AcceptanceFixtures):
    """Locks the dangerous failure mode: a login with no profile must get an
    EMPTY scope, never every outlet or brand. An unscoped account that sees
    everything is the leak this guard exists to catch."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.orphan = User.objects.create_user("no-profile", password="pass-none")

    def setUp(self):
        self.client.login(username="no-profile", password="pass-none")

    def test_scope_helpers_return_empty(self):
        self.assertFalse(scoped_outlets(self.orphan).exists())
        self.assertFalse(scoped_brands(self.orphan).exists())

    def test_outlets_list_reveals_nothing(self):
        # Phase 3 tightened this: a login with no role now gets 403 on the
        # outlets screen rather than an empty list. The security intent is
        # unchanged and the check is stricter, so assert the block directly.
        # NB: assertNotContains defaults to expecting status 200, so the 403
        # must be declared or it fails on the status rather than the content.
        response = self.client.get(reverse("panel_outlets"))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "International City", status_code=403)
        self.assertNotContains(response, "Al Nahda", status_code=403)


class EmailLoginTests(AcceptanceFixtures):
    """Phase 1: staff sign in with their email address OR their username.

    Identity matching is case-insensitive because email addresses are, and
    the backend refuses rather than guesses when an address is ambiguous.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.email_user = User.objects.create_user(
            "bm-email", password="pass-email", email="bm.kingchef@pasonsgrp.com",
        )
        OutletManager.objects.create(
            user=cls.email_user, role=OutletManager.Role.BRAND, brand=cls.brand,
        )

    def test_login_with_email_address(self):
        self.assertTrue(
            self.client.login(
                username="bm.kingchef@pasonsgrp.com", password="pass-email"
            )
        )

    def test_login_with_email_is_case_insensitive(self):
        self.assertTrue(
            self.client.login(
                username="BM.KingChef@PasonsGrp.com", password="pass-email"
            )
        )

    def test_login_with_username_still_works(self):
        self.assertTrue(self.client.login(username="bm-email", password="pass-email"))

    def test_login_with_unknown_email_fails(self):
        self.assertFalse(
            self.client.login(username="nobody@pasonsgrp.com", password="pass-email")
        )

    def test_login_with_email_and_wrong_password_fails(self):
        self.assertFalse(
            self.client.login(
                username="bm.kingchef@pasonsgrp.com", password="wrong-password"
            )
        )

    def test_login_page_offers_email_or_username(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Email or username")

    def test_email_login_reaches_the_right_scope(self):
        self.client.login(username="bm.kingchef@pasonsgrp.com", password="pass-email")
        listing = self.client.get(reverse("panel_outlets"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "International City")


class StaffEmailValidationTests(AcceptanceFixtures):
    """Phase 1: an email is required and unique, because it is a login identity."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.taken = User.objects.create_user(
            "has-email", password="pass-x", email="taken@pasonsgrp.com",
        )

    def setUp(self):
        self.client.login(username="headoffice", password="pass-head")

    def test_add_user_without_email_is_rejected(self):
        response = self.client.post(reverse("panel_user_add"), {
            "username": "noemail",
            "password": "Str0ng-Pass!42",
            "role": "outlet_manager",
            "outlets": [self.intl.pk],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="noemail").exists())

    def test_add_user_with_duplicate_email_is_rejected(self):
        response = self.client.post(reverse("panel_user_add"), {
            "username": "dupe",
            "password": "Str0ng-Pass!42",
            "email": "TAKEN@pasonsgrp.com",  # same address, different case
            "role": "outlet_manager",
            "outlets": [self.intl.pk],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="dupe").exists())

    def test_add_user_with_unique_email_succeeds(self):
        response = self.client.post(reverse("panel_user_add"), {
            "username": "fresh",
            "password": "Str0ng-Pass!42",
            "email": "fresh@pasonsgrp.com",
            "role": "outlet_manager",
            "outlets": [self.intl.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="fresh").exists())

    def test_edit_user_to_a_taken_email_is_rejected(self):
        response = self.client.post(
            reverse("panel_user_edit", args=[self.manager.pk]),
            {
                "action": "save",
                "email": "taken@pasonsgrp.com",
                "role": "outlet_manager",
                "outlets": [self.intl.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.manager.refresh_from_db()
        self.assertNotEqual(self.manager.email, "taken@pasonsgrp.com")

    def test_edit_user_email_stays_when_the_field_is_absent(self):
        # A partial POST must not silently blank an existing login address.
        original = self.manager.email
        response = self.client.post(
            reverse("panel_user_edit", args=[self.manager.pk]),
            {
                "action": "save",
                "role": "outlet_manager",
                "outlets": [self.intl.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.email, original)


class SidebarRoleLabelTests(AcceptanceFixtures):
    """Phase 2: the sidebar names the real role, and the nav is role-correct.

    The bug this fixes: every non head office account was labelled "Outlet
    Manager", so a brand manager and an account with no role at all both read
    as a branch manager. Assertions use the 'username <middle dot> label'
    form, which only the sidebar produces.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bm = User.objects.create_user(
            "bm-sidebar", password="pass-bm", email="bm.sidebar@pasonsgrp.com",
        )
        OutletManager.objects.create(
            user=cls.bm, role=OutletManager.Role.BRAND, brand=cls.brand,
        )
        cls.orphan = User.objects.create_user(
            "orphan-sidebar", password="pass-none", email="orphan@pasonsgrp.com",
        )

    def test_head_office_label(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(response, "headoffice \u00b7 Head Office")

    def test_outlet_manager_label_names_the_branch(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(
            response,
            "ic-manager \u00b7 Outlet Manager \u00b7 King Chef \u2014 International City",
        )

    def test_brand_manager_label_names_the_brand(self):
        self.client.login(username="bm-sidebar", password="pass-bm")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(
            response, "bm-sidebar \u00b7 Brand Manager \u00b7 King Chef Restaurant"
        )
        self.assertNotContains(response, "bm-sidebar \u00b7 Outlet Manager")

    def test_account_without_role_is_not_called_outlet_manager(self):
        self.client.login(username="orphan-sidebar", password="pass-none")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(response, "orphan-sidebar \u00b7 No access")
        self.assertNotContains(response, "orphan-sidebar \u00b7 Outlet Manager")

    def test_outlet_manager_nav_hides_head_office_only_links(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertNotContains(response, reverse("panel_users"))
        self.assertNotContains(response, reverse("panel_brands"))
        self.assertNotContains(response, reverse("panel_changelog"))
        self.assertContains(response, reverse("panel_outlets"))

    def test_brand_manager_nav_hides_head_office_only_links(self):
        self.client.login(username="bm-sidebar", password="pass-bm")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertNotContains(response, reverse("panel_users"))
        self.assertNotContains(response, reverse("panel_brands"))
        self.assertContains(response, reverse("panel_outlets"))

    def test_head_office_nav_shows_structure_links(self):
        self.client.login(username="headoffice", password="pass-head")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(response, reverse("panel_users"))
        self.assertContains(response, reverse("panel_brands"))
        self.assertContains(response, reverse("panel_changelog"))


class DepartmentCapabilityTests(AcceptanceFixtures):
    """Phase 3: a department limits which panel sections a Head Office user
    may open.

    Head Office with no department keeps every section, so nothing changes for
    existing accounts. An unknown department code grants nothing (fail closed),
    so adding a Department row without mapping it restricts rather than
    over-grants.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # get_or_create: migration 0007 seeds these five codes, so the test food
        # database may already hold them.
        cls.marketing, _ = Department.objects.get_or_create(
            code="MARKETING", defaults={"name_en": "Marketing"}
        )
        cls.finance, _ = Department.objects.get_or_create(
            code="FINANCE", defaults={"name_en": "Finance"}
        )
        cls.it, _ = Department.objects.get_or_create(
            code="IT", defaults={"name_en": "IT and Admin"}
        )
        cls.legal, _ = Department.objects.get_or_create(
            code="LEGAL", defaults={"name_en": "Legal"}
        )  # deliberately unmapped in DEPARTMENT_CAPABILITIES

        def ho(username, department):
            user = User.objects.create_user(
                username, password="pw-ho", email=f"{username}@pasonsgrp.com",
                is_staff=True,
            )
            OutletManager.objects.create(user=user, department=department)
            return user

        cls.ho_marketing = ho("ho-marketing", cls.marketing)
        cls.ho_finance = ho("ho-finance", cls.finance)
        cls.ho_it = ho("ho-it", cls.it)
        cls.ho_legal = ho("ho-legal", cls.legal)
        # Head Office with no department: full access (the existing behaviour).
        cls.ho_full = User.objects.create_user(
            "ho-full", password="pw-ho", email="ho.full@pasonsgrp.com", is_staff=True,
        )

    def _login(self, username):
        self.client.login(username=username, password="pw-ho")

    # -- marketing: specials, QR, analytics, leads, feedback ----------------

    def test_marketing_may_open_its_own_sections(self):
        self._login("ho-marketing")
        for url in (
            reverse("panel_dashboard"),
            reverse("panel_specials"),
            reverse("panel_qrcodes"),
            reverse("panel_analytics"),
            reverse("panel_leads"),
            reverse("panel_feedback"),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_marketing_is_blocked_from_users_brands_and_outlets(self):
        self._login("ho-marketing")
        for url in (
            reverse("panel_users"),
            reverse("panel_user_add"),
            reverse("panel_brands"),
            reverse("panel_outlets"),
            reverse("panel_menus"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    # -- finance: analytics only -------------------------------------------

    def test_finance_may_open_analytics_only(self):
        self._login("ho-finance")
        self.assertEqual(self.client.get(reverse("panel_analytics")).status_code, 200)
        for url in (
            reverse("panel_specials"),
            reverse("panel_outlets"),
            reverse("panel_users"),
            reverse("panel_leads"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    # -- IT: everything -----------------------------------------------------

    def test_it_may_open_everything(self):
        self._login("ho-it")
        for url in (
            reverse("panel_brands"),
            reverse("panel_outlets"),
            reverse("panel_users"),
            reverse("panel_specials"),
            reverse("panel_menus"),
            reverse("panel_leads"),
            reverse("panel_feedback"),
            reverse("panel_analytics"),
            reverse("panel_changelog"),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    # -- unmapped department code fails closed ------------------------------

    def test_unmapped_department_can_only_reach_the_dashboard(self):
        self._login("ho-legal")
        self.assertEqual(self.client.get(reverse("panel_dashboard")).status_code, 200)
        for url in (
            reverse("panel_users"),
            reverse("panel_brands"),
            reverse("panel_specials"),
            reverse("panel_outlets"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    # -- head office without a department is unchanged ----------------------

    def test_head_office_without_department_keeps_full_access(self):
        self._login("ho-full")
        for url in (
            reverse("panel_users"),
            reverse("panel_brands"),
            reverse("panel_outlets"),
            reverse("panel_specials"),
            reverse("panel_changelog"),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    # -- the label and the nav follow the department ------------------------

    def test_label_names_the_department(self):
        self._login("ho-marketing")
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(response, "ho-marketing \u00b7 Head Office \u00b7 Marketing")

    def _nav_html(self, response):
        """The sidebar nav block only.

        Page bodies also link to panel URLs (the dashboard's outlet rows link
        to /panel/outlets/<pk>/edit/), so a whole-page search would report the
        nav as leaking when it is not.
        """
        html = response.content.decode()
        start = html.find('<nav class="panel-nav">')
        self.assertNotEqual(start, -1, "sidebar nav not found in the response")
        end = html.find("</nav>", start)
        return html[start:end]

    def test_nav_hides_sections_the_department_lacks(self):
        self._login("ho-marketing")
        nav = self._nav_html(self.client.get(reverse("panel_dashboard")))
        self.assertIn(reverse("panel_specials"), nav)
        self.assertNotIn(reverse("panel_users"), nav)
        self.assertNotIn(reverse("panel_brands"), nav)
        self.assertNotIn(reverse("panel_outlets"), nav)

    def test_dashboard_stays_reachable_for_an_unroled_account(self):
        # A login with no role must still land somewhere after sign-in.
        User.objects.create_user(
            "no-role-cap", password="pw-ho", email="norole@pasonsgrp.com",
        )
        self._login("no-role-cap")
        self.assertEqual(self.client.get(reverse("panel_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel_specials")).status_code, 403)


class DepartmentFormTests(AcceptanceFixtures):
    """Phase 3: Head Office can assign a department on the Users form."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.marketing, _ = Department.objects.get_or_create(
            code="MARKETING", defaults={"name_en": "Marketing"}
        )

    def setUp(self):
        self.client.login(username="headoffice", password="pass-head")

    def test_create_head_office_user_with_department(self):
        response = self.client.post(reverse("panel_user_add"), {
            "username": "ho-mkt",
            "password": "Str0ng-Pass!42",
            "email": "ho.mkt@pasonsgrp.com",
            "role": "head_office",
            "department": self.marketing.pk,
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="ho-mkt")
        self.assertTrue(user.is_staff)
        self.assertEqual(user.outlet_manager_profile.department, self.marketing)

    def test_create_head_office_user_without_department_is_full_access(self):
        response = self.client.post(reverse("panel_user_add"), {
            "username": "ho-nodep",
            "password": "Str0ng-Pass!42",
            "email": "ho.nodep@pasonsgrp.com",
            "role": "head_office",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="ho-nodep")
        self.assertIsNone(user.outlet_manager_profile.department)

    def test_switching_to_brand_manager_clears_the_department(self):
        user = User.objects.create_user(
            "ho-switch", password="pw", email="ho.switch@pasonsgrp.com", is_staff=True,
        )
        OutletManager.objects.create(user=user, department=self.marketing)
        response = self.client.post(reverse("panel_user_edit", args=[user.pk]), {
            "action": "save",
            "email": "ho.switch@pasonsgrp.com",
            "role": "brand_manager",
            "brand": self.brand.pk,
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertIsNone(user.outlet_manager_profile.department)


class PanelCapabilityCoverageTests(TestCase):
    """Phase 3: the gate cannot be forgotten.

    Every panel route must either declare a capability or be an explicit
    exemption (login / logout). Adding a new panel view without mapping it
    fails this test rather than shipping an ungated screen.
    """

    @staticmethod
    def _url_names():
        from django.urls import get_resolver

        names = set()

        def walk(patterns):
            for pattern in patterns:
                if hasattr(pattern, "url_patterns"):
                    walk(pattern.url_patterns)
                elif pattern.name:
                    names.add(pattern.name)

        walk(get_resolver().url_patterns)
        return names

    def test_every_panel_view_is_gated_or_exempt(self):
        from apps.core.middleware import (
            CAPABILITY_EXEMPT_VIEWS,
            INLINE_GATED_VIEWS,
            VIEW_CAPABILITIES,
        )

        names = self._url_names()
        panel_names = {n for n in names if n.startswith("panel_")}
        declared = set(VIEW_CAPABILITIES) | set(INLINE_GATED_VIEWS)
        unmapped = panel_names - declared - set(CAPABILITY_EXEMPT_VIEWS)
        self.assertEqual(
            unmapped, set(),
            f"Panel views with no capability declared: {sorted(unmapped)}",
        )

    def test_the_bare_dashboard_route_is_also_gated(self):
        # /dashboard/ is not under /panel/, so it must be declared as inline
        # gated or it would silently escape the department gate.
        from apps.core.middleware import INLINE_GATED_VIEWS

        self.assertIn("dashboard", self._url_names())
        self.assertIn("dashboard", INLINE_GATED_VIEWS)

    def test_capability_keys_are_real(self):
        from apps.core import panel_permissions as perms
        from apps.core.middleware import VIEW_CAPABILITIES

        unknown = {v for v in VIEW_CAPABILITIES.values() if v not in perms.ALL_CAPABILITIES}
        self.assertEqual(unknown, set(), f"Unknown capability keys: {sorted(unknown)}")

    def test_exempt_views_are_auth_endpoints_only(self):
        from apps.core.middleware import CAPABILITY_EXEMPT_VIEWS

        self.assertEqual(CAPABILITY_EXEMPT_VIEWS, {"panel_login", "panel_logout"})


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
            "email": "om.kingchef-alnahda@pasonsgrp.com",
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
            "email": "bm.kingchef@pasonsgrp.com",
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

    def test_manager_gets_photo_only_form_for_brand_item(self):
        """Client 2026-10-15: outlet managers may upload photos on brand-level
        items (the Top 10 lists are brand-level), so the form opens — but only
        the photo editor; structure stays Head Office."""
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.get(
            reverse("panel_menu_item_edit", args=[self.base_item.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload photo")
        self.assertNotContains(response, 'name="name_en"')
        self.assertNotContains(response, 'name="regular_price"')

    def test_manager_uploads_photo_on_brand_item(self):
        self.client.login(username="ic-manager", password="pass-ic")
        photo = SimpleUploadedFile("dish.png", b"\x89PNG fake dish", content_type="image/png")
        response = self.client.post(
            reverse("panel_menu_item_edit", args=[self.base_item.pk]),
            {"image": photo},
        )
        self.assertEqual(response.status_code, 302)
        self.base_item.refresh_from_db()
        self.assertTrue(self.base_item.image)
        self.assertEqual(self.base_item.name_en, "Hummus")   # structure untouched

    def test_manager_cannot_change_brand_item_details(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(
            reverse("panel_menu_item_edit", args=[self.base_item.pk]),
            {
                "brand": self.brand.pk, "category": self.category.pk,
                "name_en": "Hacked", "regular_price": "1.00",
            },
        )
        self.assertEqual(response.status_code, 302)   # photo-only path: no image, no write
        self.base_item.refresh_from_db()
        self.assertEqual(self.base_item.name_en, "Hummus")
        self.assertEqual(self.base_item.regular_price, 8)

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


class MenuCardPageTests(AcceptanceFixtures):
    """
    The guest menu page renders dish cards and an uploaded PDF in-platform.
    Only a genuine external URL may send guests off-site (the reserved
    example-domain placeholder used to produce a DNS error in browsers).
    """

    PDF = SimpleUploadedFile("menu.pdf", b"%PDF-1.4 test menu", content_type="application/pdf")

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category = MenuCategory.objects.create(brand=cls.brand, name_en=TOP_FOOD_CATEGORY)
        cls.dish = MenuItem.objects.create(
            category=cls.category, brand=cls.brand, name_en="Chicken mandi",
            description_en="Slow-cooked rice, smoked chicken.",
            regular_price=42, offer_price=36, featured=True, available=True,
        )
        cls.sold_out = MenuItem.objects.create(
            category=cls.category, brand=cls.brand, name_en="Sold out kebab",
            regular_price=50, available=False,
        )

    def _in_platform_source(self, menu_type):
        source = MenuSource.objects.get(outlet=self.intl)
        source.menu_type = menu_type
        source.menu_url = ""
        source.menu_file = SimpleUploadedFile(
            "menu.pdf", b"%PDF-1.4 test menu", content_type="application/pdf"
        )
        source.save()
        return source

    def test_customer_menu_renders_dish_cards_and_pdf(self):
        self._in_platform_source(MenuSource.MenuType.PAGES)
        response = self.client.get(reverse("customer_menu", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Most Popular", body)         # curated list label
        self.assertIn("Chicken mandi", body)        # dish name shown
        self.assertIn("/media/menu/pdf/", body)      # PDF card links the upload
        self.assertNotIn("Sold out kebab", body)     # unavailable dishes stay hidden
        self.assertNotIn("Save 14%", body)           # name-only cards: no offer chips
        self.assertNotIn("Chef's pick", body)        # name-only cards: no badges
        self.assertNotIn("menu-price", body)         # names only: no prices

    def test_menu_page_shows_the_top_lists_not_the_full_menu(self):
        """Client 2026-10-15: the brand's Top 10 food and Top 10 beverages
        only (Docs/Pasons_Restaurants_Top10_Food_Beverages.md), each capped
        at ten — never a full-menu dump."""
        self._in_platform_source(MenuSource.MenuType.PAGES)
        drinks_cat = MenuCategory.objects.create(brand=self.brand, name_en=TOP_DRINK_CATEGORY)
        for n in range(15):
            MenuItem.objects.create(
                category=self.category, brand=self.brand,
                name_en=f"Extra dish {n}", regular_price=10 + n, available=True,
            )
            MenuItem.objects.create(
                category=drinks_cat, brand=self.brand,
                name_en=f"Extra drink {n}", regular_price=5 + n, available=True,
            )
        response = self.client.get(reverse("customer_menu", args=["kcic-table-001"]))
        body = response.content.decode()
        cards = body.count('<article class="menu-card')
        self.assertEqual(cards, 20)                  # 10 food + 10 beverages
        self.assertNotIn("Extra dish 14", body)      # tail of the list never dumps
        self.assertNotIn("Extra drink 14", body)

    def test_pdf_source_stays_in_platform(self):
        self._in_platform_source(MenuSource.MenuType.PDF)
        response = self.client.get(reverse("customer_menu", args=["kcic-table-001"]))
        self.assertEqual(response.status_code, 200)  # no blind redirect to a raw file
        self.assertIn("Full menu PDF", response.content.decode())

    def test_manager_uploads_menu_pdf_from_panel(self):
        self.client.login(username="ic-manager", password="pass-ic")
        response = self.client.post(reverse("panel_menus"), {
            "brand": self.brand.pk,
            "outlet": self.intl.pk,
            "menu_type": "pages",
            "menu_file": self.PDF,
        })
        self.assertEqual(response.status_code, 302)
        source = MenuSource.objects.get(outlet=self.intl)
        self.assertTrue(source.menu_file)
        self.assertTrue(source.menu_file.name.endswith(".pdf"))

    def test_panel_rejects_non_pdf_menu_file(self):
        self.client.login(username="ic-manager", password="pass-ic")
        png = SimpleUploadedFile("menu.png", b"\x89PNG fake", content_type="image/png")
        response = self.client.post(reverse("panel_menus"), {
            "brand": self.brand.pk,
            "outlet": self.intl.pk,
            "menu_type": "pages",
            "menu_file": png,
        })
        self.assertEqual(response.status_code, 302)
        source = MenuSource.objects.get(outlet=self.intl)
        self.assertFalse(source.menu_file)


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
        # The old link opens the shop window. Place ID links live on the
        # composer and the directions target, not on a location picker.
        self.assertContains(response, "REVIEW US ON GOOGLE")
        self.assertNotContains(response, "Choose a location")


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
        # The shop window's review card opens the composer for this outlet.
        self.assertContains(response, "/review/write/")
        self.assertNotContains(response, "Choose a location")

    def test_smart_composer_google_button_opens_review_url(self):
        response = self.client.get(
            reverse("smart_review_write", args=["kingchef-intlcity"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "writereview?placeid=ChIJ-kingchef-intl-city-demo")


class SeedStaffCommandTests(TestCase):
    """seed_staff must be idempotent, must never touch a password twice, and
    must give each role exactly the scope its account should have."""

    @classmethod
    def setUpTestData(cls):
        cls.brand_a = Brand.objects.create(
            code="BRANDA", name_en="Brand A", status="active"
        )
        cls.brand_b = Brand.objects.create(
            code="BRANDB", name_en="Brand B", status="active"
        )
        Outlet.objects.create(
            code="BRANDA-ONE", official_name="Brand A One", brand=cls.brand_a,
            slug="branda-one", active=True,
        )
        Outlet.objects.create(
            code="BRANDA-TWO", official_name="Brand A Two", brand=cls.brand_a,
            slug="branda-two", active=True,
        )
        Outlet.objects.create(
            code="BRANDB-ONE", official_name="Brand B One", brand=cls.brand_b,
            slug="brandb-one", active=True,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("seed_staff", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self._run("--dry-run")
        self.assertFalse(User.objects.exists(), "a dry run created a user")
        self.assertIn("bm.branda", output)
        self.assertIn("Dry run", output)

    def test_run_creates_two_brand_three_outlet_and_three_head_office(self):
        self._run("--password", "pw-123456")
        self.assertEqual(User.objects.count(), 8)
        roles = {u.username: u.outlet_manager_profile.role for u in User.objects.all()}
        self.assertEqual(roles["bm.branda"], OutletManager.Role.BRAND)
        self.assertEqual(roles["om.branda-one"], OutletManager.Role.OUTLET)

    def test_brand_manager_scope_is_the_whole_brand(self):
        self._run("--password", "pw-123456")
        bm = User.objects.get(username="bm.branda")
        self.assertEqual(
            set(scoped_outlets(bm).values_list("code", flat=True)),
            {"BRANDA-ONE", "BRANDA-TWO"},
        )

    def test_outlet_manager_scope_is_one_branch_and_never_staff(self):
        self._run("--password", "pw-123456")
        om = User.objects.get(username="om.branda-one")
        self.assertEqual(scoped_outlets(om).count(), 1)
        # is_staff would make is_head_office true and open everything (risk R1).
        self.assertFalse(om.is_staff)

    def test_head_office_account_gets_its_department(self):
        self._run("--password", "pw-123456")
        head = User.objects.get(username="ho.marketing")
        self.assertTrue(head.is_staff)
        self.assertEqual(head.outlet_manager_profile.department.code, "MARKETING")
        self.assertEqual(head.email, "marketing@pasonsgrp.com")

    def test_marketing_department_cannot_open_users(self):
        self._run("--password", "pw-123456")
        self.assertTrue(
            self.client.login(username="ho.marketing", password="pw-123456")
        )
        self.assertEqual(self.client.get(reverse("panel_users")).status_code, 403)

    def test_second_run_creates_nothing_and_keeps_the_password(self):
        self._run("--password", "first-pass")
        before = User.objects.get(username="bm.branda").password
        output = self._run()
        self.assertEqual(User.objects.count(), 8)
        self.assertEqual(User.objects.get(username="bm.branda").password, before)
        self.assertIn("refreshed 8", output)
        self.assertTrue(self.client.login(username="bm.branda", password="first-pass"))

    def test_brands_filter_leaves_a_brand_out(self):
        self._run("--password", "pw-123456", "--brands", "BRANDA")
        self.assertTrue(User.objects.filter(username="bm.branda").exists())
        self.assertFalse(User.objects.filter(username="bm.brandb").exists())
        self.assertFalse(User.objects.filter(username="om.brandb-one").exists())

    def test_email_domain_is_configurable(self):
        self._run("--password", "pw-123456", "--domain", "example.test")
        self.assertEqual(
            User.objects.get(username="bm.branda").email, "bm.branda@example.test"
        )

    def test_style_b_uses_the_manager_prefix(self):
        self._run("--password", "pw-123456", "--style", "b")
        self.assertTrue(User.objects.filter(username="manager.branda").exists())
        self.assertTrue(User.objects.filter(username="manager.branda_one").exists())
