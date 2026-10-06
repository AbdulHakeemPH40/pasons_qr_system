"""
Tests for the management dashboard (spec 25) and read-time analytics
aggregation (spec 24/50): staff gating, KPI rendering, brand scoping,
day/outlet/source breakdowns, and top QR placements.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Brand, QrCode, SmartPage
from apps.core.tests import make_brand_page

from . import aggregates
from .models import ScanEvent


def make_brand(code, name):
    brand = Brand.objects.create(name_en=name, code=code)
    page = SmartPage.objects.create(
        brand=brand,
        slug=code.lower(),
        page_title=name,
        hero_title=name,
        hero_subtitle=f"{name} — test",
        published=True,
        published_at=timezone.now(),
    )
    return brand, page


class DashboardAccessTests(TestCase):
    def test_anonymous_redirects_to_admin_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_non_staff_forbidden(self):
        User.objects.create_user("viewer", password="pw")
        self.client.login(username="viewer", password="pw")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_staff_sees_dashboard(self):
        User.objects.create_superuser("admin", password="pw")
        self.client.login(username="admin", password="pw")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Management Dashboard")
        # Group Summary tiles (spec 25)
        for label in (
            "Scans today", "Active campaigns", "Enquiries",
            "Feedback", "Top performing brand",
        ):
            self.assertContains(response, label)


class DashboardDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand, cls.page = make_brand("KINGCHEF", "King Chef Restaurant")
        cls.other, cls.other_page = make_brand("DONARIST", "Donar Istanbul")
        cls.qr = QrCode.objects.create(
            qr_code_name="KINGCHEF-MAIN-FLYER-01",
            destination_page=cls.page,
            brand=cls.brand,
            source_type="flyer",
            source_location="Deira entrance",
        )
        cls.qr2 = QrCode.objects.create(
            qr_code_name="DONARIST-MAIN-TABLE-01",
            destination_page=cls.other_page,
            brand=cls.other,
            source_type="table",
        )
        cls.user = User.objects.create_superuser("admin", password="pw")

    def _scan(self, qr, brand, hours_ago=0):
        event = ScanEvent.objects.create(qr_code=qr, brand=brand)
        if hours_ago:
            ScanEvent.objects.filter(pk=event.pk).update(
                scanned_at=timezone.now() - timedelta(hours=hours_ago)
            )
        return event

    def test_kpis_count_scans_and_campaigns(self):
        from apps.core.models import Campaign

        self._scan(self.qr, self.brand)
        self._scan(self.qr, self.brand, hours_ago=2)
        Campaign.objects.create(
            name="Live offer",
            brand=self.brand,
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() + timedelta(days=7),
            status=Campaign.Status.LIVE,
        )
        self.client.login(username="admin", password="pw")
        response = self.client.get(reverse("dashboard"))
        kpis = {k["key"]: k for k in response.context["kpis"]}
        self.assertEqual(kpis["scans_today"]["value"], 2)
        self.assertEqual(kpis["scans_month"]["value"], 2)
        self.assertEqual(kpis["campaigns"]["value"], 1)
        self.assertEqual(kpis["top"]["value"], "King Chef Restaurant")

    def test_brand_scoping_filters_everything(self):
        self._scan(self.qr, self.brand)
        self._scan(self.qr2, self.other)
        self.client.login(username="admin", password="pw")
        response = self.client.get(reverse("dashboard"), {"brand": "DONARIST"})
        self.assertEqual(response.context["brand"], self.other)
        kpis = {k["key"]: k for k in response.context["kpis"]}
        self.assertEqual(kpis["scans_month"]["value"], 1)  # only DONARIST
        # outlets of the scoped brand only
        self.assertEqual(
            [row["count"] for row in response.context["by_outlet"]], [1]
        )

    def test_unknown_brand_code_falls_back_to_group(self):
        self.client.login(username="admin", password="pw")
        response = self.client.get(reverse("dashboard"), {"brand": "NOPE"})
        self.assertIsNone(response.context["brand"])

    def test_scans_by_day_zero_fills(self):
        self._scan(self.qr, self.brand)
        rows = aggregates.scans_by_day(days=14)
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[-1]["count"], 1)  # today
        self.assertEqual(sum(r["count"] for r in rows), 1)
        self.assertEqual(rows[0]["pct"], 0)

    def test_scans_by_day_bars_scale_to_peak(self):
        self._scan(self.qr, self.brand, hours_ago=26)  # yesterday
        self._scan(self.qr, self.brand)
        self._scan(self.qr, self.brand)
        rows = aggregates.scans_by_day(days=7)
        self.assertEqual(rows[-1]["count"], 2)
        self.assertEqual(rows[-1]["pct"], 100)  # busiest day = full bar
        self.assertEqual(rows[-2]["count"], 1)
        self.assertEqual(rows[-2]["pct"], 50)

    def test_brand_level_scan_labelled_brand_page(self):
        """Outlet optional (spec 6): scans without outlet show brand page."""
        self._scan(self.qr, self.brand)
        rows = aggregates.scans_by_outlet()
        self.assertEqual(rows[0]["label"], "King Chef Restaurant — brand page")

    def test_top_placements_ranked_with_metadata(self):
        self._scan(self.qr, self.brand)
        self._scan(self.qr, self.brand)
        self._scan(self.qr2, self.other)
        rows = aggregates.top_placements()
        self.assertEqual(rows[0]["name"], "KINGCHEF-MAIN-FLYER-01")
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["location"], "Deira entrance")
        self.assertEqual(rows[0]["source"], "Flyer")
        self.assertTrue(rows[0]["active"])

    def test_scans_by_source_uses_human_labels(self):
        self._scan(self.qr, self.brand)
        self._scan(self.qr2, self.other)
        rows = aggregates.scans_by_source()
        labels = [r["label"] for r in rows]
        self.assertIn("Flyer", labels)
        self.assertIn("Table", labels)
        # both have equal counts -> each is 100% of the peak
        self.assertTrue(all(r["pct"] == 100 for r in rows))
