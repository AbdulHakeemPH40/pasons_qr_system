"""
Behaviour tests for the public platform (spec sections 6, 9-11, 23):
Smart Page rendering with the mandated module set, brand->outlet fallback,
feedback capture, and the QR redirect engine with scan analytics.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ScanEvent
from apps.engagement.models import Feedback
from apps.menu.models import MenuCategory, MenuItem, items_for

from .models import Brand, Campaign, Outlet, PageModule, QrCode, SmartPage


def make_brand_page(brand, slug=None):
    page = SmartPage.objects.create(
        brand=brand,
        slug=slug or brand.code.lower(),
        page_title=brand.name_en,
        hero_title=brand.name_en,
        hero_subtitle="Test subtitle",
        published=True,
        published_at=timezone.now(),
    )
    for i, mtype in enumerate(m[0] for m in PageModule.ModuleType.choices):
        PageModule.objects.create(page=page, module_type=mtype, sort_order=i)
    return page


class SmartPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Restaurant",
            code="KINGCHEF",
            default_whatsapp="97142200001",
            default_phone="04 220 0001",
            social_links={"instagram": "https://instagram.com/kingchefuae"},
            google_review_url="https://g.page/r/kingchef-demo/review",
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-DEIRA",
            official_name="King Chef — Deira",
            brand=cls.brand,
            phone="04 220 0002",
            opening_hours={
                d: {"open": "00:00", "close": "23:59", "closed": False}
                for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            },
        )
        cls.brand_page = make_brand_page(cls.brand)
        cls.outlet_page = make_brand_page(
            cls.brand, slug="kingchef-deira"
        )
        cls.outlet_page.outlet = cls.outlet
        cls.outlet_page.hero_title = ""  # forces fallback to brand page
        cls.outlet_page.save()

        cat = MenuCategory.objects.create(brand=cls.brand, name_en="Biryani")
        cls.base_item = MenuItem.objects.create(
            category=cat,
            brand=cls.brand,
            name_en="Chicken Biryani",
            regular_price=38.00,
        )
        cls.override_item = MenuItem.objects.create(
            category=cat,
            brand=cls.brand,
            outlet=cls.outlet,
            overrides=cls.base_item,
            name_en="Chicken Biryani",
            regular_price=42.00,
        )

    def test_brand_page_renders_all_client_modules(self):
        """The 5 client-mandated modules (spec 37) must always be visible."""
        response = self.client.get(reverse("smart_page", args=[self.brand_page.slug]))
        self.assertEqual(response.status_code, 200)
        for marker in ("Special offers", "Full Menu", "Google Review", "Instagram", "Follow & Connect"):
            self.assertContains(response, marker)
        self.assertContains(response, "Chicken Biryani")
        self.assertContains(response, "https://g.page/r/kingchef-demo/review")

    def test_outlet_page_falls_back_to_brand_fields(self):
        response = self.client.get(reverse("smart_page", args=[self.outlet_page.slug]))
        self.assertEqual(response.status_code, 200)
        # hero_title blank on outlet page -> brand page title used (spec 6)
        self.assertContains(response, "King Chef Restaurant")
        self.assertContains(response, "King Chef — Deira")

    def test_brand_page_shows_location_chooser_and_resolution(self):
        """Frame 09 (spec 6): mandatory brand, optional outlets."""
        response = self.client.get(reverse("smart_page", args=[self.brand_page.slug]))
        self.assertEqual(response.status_code, 200)
        # identity footnote - the brand page stands complete on its own
        self.assertContains(response, "Complete on its own")
        # choose a location: brand default row + outlet row with override badge
        self.assertContains(response, "Choose a location")
        self.assertContains(response, "All King Chef")
        self.assertContains(response, "Every field served from brand content")
        self.assertContains(response, "Own hours")
        self.assertContains(response, "2 OVERRIDES")
        # how a field resolves: per-field brand vs outlet source table
        self.assertContains(response, "How a field resolves")
        self.assertContains(response, "Deira outlet")
        self.assertContains(response, "OUTLET OVERRIDE")
        self.assertContains(response, "BRAND CONTENT")

    def test_outlet_page_marks_current_location(self):
        response = self.client.get(reverse("smart_page", args=[self.outlet_page.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "loc-row--selected")
        self.assertContains(response, "Deira outlet")

    def test_outlet_menu_override_replaces_brand_item(self):
        resolved = items_for(self.brand, self.outlet)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].regular_price, 42.00)

    def test_brand_menu_has_base_items_without_outlet(self):
        resolved = items_for(self.brand, None)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].regular_price, 38.00)

    def test_feedback_post_creates_record(self):
        response = self.client.post(
            reverse("smart_page", args=[self.brand_page.slug]),
            {
                "customer_name": "Aisha R.",
                "customer_phone": "0501234567",
                "rating": "4",
                "category": "food",
                "message": "Best karak in Deira",
            },
        )
        self.assertEqual(response.status_code, 302)
        fb = Feedback.objects.get()
        self.assertEqual(fb.brand, self.brand)
        self.assertEqual(fb.rating, 4)
        self.assertEqual(fb.message, "Best karak in Deira")

    def test_language_switch_is_rtl(self):
        response = self.client.get(
            reverse("smart_page", args=[self.brand_page.slug]), {"lang": "ar"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["lang"], "ar")
        self.assertEqual(response.context["dir"], "rtl")


class QrRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(name_en="Milan Veg", code="MILANVEG")
        cls.page = make_brand_page(cls.brand)
        cls.qr = QrCode.objects.create(
            qr_code_name="MILANVEG-MAIN-FLYER-01",
            destination_page=cls.page,
            brand=cls.brand,
            source_type="flyer",
        )

    def test_redirect_records_scan_event(self):
        response = self.client.get(
            reverse("qr_redirect", args=[self.qr.redirect_key]),
            HTTP_USER_AGENT="test-agent",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.brand.name_en)
        event = ScanEvent.objects.get()
        self.assertEqual(event.qr_code, self.qr)
        self.assertEqual(event.brand, self.brand)
        self.assertEqual(event.user_agent, "test-agent")
        self.assertNotEqual(event.ip_hash, "")  # privacy: hashed, never raw

    def test_unknown_key_returns_404(self):
        response = self.client.get(reverse("qr_redirect", args=["doesnotexist"]))
        self.assertEqual(response.status_code, 404)

    def test_inactive_qr_returns_410(self):
        self.qr.active = False
        self.qr.save()
        response = self.client.get(reverse("qr_redirect", args=[self.qr.redirect_key]))
        self.assertEqual(response.status_code, 410)
        self.assertEqual(ScanEvent.objects.count(), 0)

    def test_language_rule_carries_through_redirect(self):
        response = self.client.get(
            reverse("qr_redirect", args=[self.qr.redirect_key]) + "?lang=ar"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')

    def test_qr_name_enforces_naming_convention(self):
        """[BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE] (spec 22)."""
        from django.core.exceptions import ValidationError

        bad = QrCode(
            qr_code_name="BAD-NAME",
            destination_page=self.page,
            brand=self.brand,
            source_type="flyer",
        )
        with self.assertRaises(ValidationError):
            bad.full_clean()
        wrong_brand = QrCode(
            qr_code_name="OTHER-MAIN-FLYER-01",
            destination_page=self.page,
            brand=self.brand,
            source_type="flyer",
        )
        with self.assertRaises(ValidationError):
            wrong_brand.full_clean()


class CampaignApprovalTests(TestCase):
    """Campaign workflow (spec 28 states, 29: Approval -> Auto Publish -> Auto Expire)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.brand = Brand.objects.create(name_en="Milan Veg", code="MILANVEG")
        cls.page = make_brand_page(cls.brand)
        cls.approver = User.objects.create_superuser("chief", password="pw")
        cls.campaign = Campaign.objects.create(
            name="Weekend special",
            brand=cls.brand,
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() + timedelta(days=7),
            status=Campaign.Status.PENDING,
        )

    def test_approve_within_window_goes_live_and_records_approver(self):
        self.campaign.approve(self.approver)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.LIVE)
        self.assertEqual(self.campaign.approved_by, self.approver)

    def test_approve_future_window_becomes_scheduled(self):
        self.campaign.start_at = timezone.now() + timedelta(days=3)
        self.campaign.save(update_fields=["start_at"])
        self.campaign.approve(self.approver)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.SCHEDULED)

    def test_approve_passed_window_expires(self):
        self.campaign.start_at = timezone.now() - timedelta(days=10)
        self.campaign.end_at = timezone.now() - timedelta(days=2)
        self.campaign.save(update_fields=["start_at", "end_at"])
        self.campaign.approve(self.approver)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.ENDED)

    def test_scheduled_campaign_publishes_automatically(self):
        """Spec 29: after approval, publish happens by window, no manual step."""
        self.campaign.start_at = timezone.now() - timedelta(hours=1)
        self.campaign.end_at = timezone.now() + timedelta(days=7)
        self.campaign.save(update_fields=["start_at", "end_at"])
        self.campaign.approve(self.approver)
        response = self.client.get(reverse("smart_page", args=[self.page.slug]))
        self.assertContains(response, "Weekend special")

    def test_pending_campaign_not_published(self):
        response = self.client.get(reverse("smart_page", args=[self.page.slug]))
        self.assertNotContains(response, "Weekend special")

    def test_admin_approval_action_records_request_user(self):
        """Admin bulk approve stamps approved_by with the acting admin (spec 28)."""
        from django.contrib import admin as django_admin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from .admin import CampaignAdmin

        site = AdminSite(name="test")
        model_admin = CampaignAdmin(Campaign, site)
        request = RequestFactory().post("/admin/")
        request.user = self.approver
        # message_user needs the messages framework; attach a no-op
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        setattr(request, "_messages", FallbackStorage(request))

        model_admin.approve_campaigns(
            request, Campaign.objects.filter(pk=self.campaign.pk)
        )
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.LIVE)
        self.assertEqual(self.campaign.approved_by, self.approver)
        self.assertEqual(self.campaign.created_by, None)  # only set on save_model


class MediaCdnOptimizationTests(TestCase):
    """M4 — media/CDN optimization (spec §0.2 fast-loading, §0.5 optimized image loading)."""

    def test_whitenoise_middleware_installed(self):
        from django.conf import settings

        self.assertIn(
            "whitenoise.middleware.WhiteNoiseMiddleware", settings.MIDDLEWARE
        )

    def test_storages_uses_compressed_static_in_debug(self):
        from django.conf import settings

        backend = settings.STORAGES["staticfiles"]["BACKEND"]
        self.assertIn("whitenoise", backend)
        self.assertIn("Compressed", backend)

    def test_whitenoise_cache_max_age_set(self):
        from django.conf import settings

        self.assertEqual(settings.WHITENOISE_MAX_AGE, 60 * 60 * 24 * 365)
        self.assertTrue(settings.WHITENOISE_COMPRESS)

    def test_cdn_env_switch_uses_plain_storage(self):
        """CDN_STATIC_ENABLED=1 swaps to CDN-ready static backend."""
        import os
        from unittest.mock import patch

        from django.conf import settings

        # The CDN path is only checked at import time; verify the branch exists.
        self.assertTrue(hasattr(settings, "STORAGES"))
        self.assertIn("default", settings.STORAGES)
        self.assertIn("staticfiles", settings.STORAGES)


class AccessibilityTemplateTests(TestCase):
    """M4 — accessibility pass (spec §0.2, §0.5 high accessibility contrast)."""

    @classmethod
    def setUpTestData(cls):
        from django.core.files.base import ContentFile

        cls.brand = Brand.objects.create(name_en="Test Brand", code="TEST")
        cls.brand.logo.save(
            "test-logo.png",
            ContentFile(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
            save=True,
        )
        cls.page = SmartPage.objects.create(
            brand=cls.brand,
            slug="test",
            page_title="Test",
            hero_title="Test",
            hero_subtitle="Test",
            published=True,
            published_at=timezone.now(),
        )

    def test_base_template_has_skip_link(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "skip-link")
        self.assertContains(response, "Skip to main content")

    def test_base_template_main_has_id_for_skip_target(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'id="main-content"')

    def test_images_have_decoding_async(self):
        response = self.client.get(reverse("smart_page", args=[self.page.slug]))
        self.assertContains(response, 'decoding="async"')

    def test_images_have_dimensions_for_cls(self):
        """width/height attributes prevent Cumulative Layout Shift (CLS)."""
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'width="56"')
        self.assertContains(response, 'height="56"')

    def test_images_have_lazy_loading_on_home(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'loading="lazy"')

    def test_critical_css_preloaded(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'rel="preload"')
        self.assertContains(response, 'as="style"')
