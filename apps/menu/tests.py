"""
Outlet menu PDF wiring (spec section 10).

Staff keep one menu PDF per outlet in media/PDF/<OUTLET-CODE>.pdf. The seed
wires each file to its outlet as an active PDF MenuSource, and the guest menu
page (/q/<key>/menu/) serves that outlet's own PDF. These tests lock the
file-name to outlet-code mapping so a renamed code or a missing file fails
loudly instead of leaving guests on a dead link.
"""

from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.menu.models import MenuSource

PDF_DIR = settings.BASE_DIR / "media" / "PDF"


def _hours_open_all_day():
    return {
        d: {"open": "00:00", "close": "23:59", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class OutletMenuPdfWiringTests(TestCase):
    """seed_demo must wire every media/PDF/<CODE>.pdf to its outlet."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def _pdf_files(self):
        return sorted(p.stem for p in PDF_DIR.glob("*.pdf"))

    def test_every_menu_pdf_file_is_wired_to_its_outlet(self):
        codes = self._pdf_files()
        self.assertTrue(codes, "no menu PDFs found in media/PDF/")
        for code in codes:
            with self.subTest(code=code):
                outlet = Outlet.objects.get(code=code)
                source = MenuSource.objects.get(outlet=outlet, active=True)
                self.assertEqual(source.menu_type, MenuSource.MenuType.PDF)
                self.assertEqual(source.menu_file.name, f"PDF/{code}.pdf")

    def test_every_outlet_has_a_menu_pdf(self):
        # The client's requirement is outlet-based menus for all branches, so
        # outlet codes and PDF file names must stay in step one-to-one.
        outlet_codes = set(Outlet.objects.values_list("code", flat=True))
        self.assertEqual(outlet_codes, set(self._pdf_files()))

    def test_every_wired_outlet_pdf_exists_on_disk(self):
        sources = MenuSource.objects.filter(
            menu_type=MenuSource.MenuType.PDF, outlet__isnull=False
        )
        self.assertTrue(sources.exists())
        for source in sources:
            with self.subTest(code=source.outlet.code):
                self.assertTrue(
                    (Path(settings.MEDIA_ROOT) / source.menu_file.name).is_file(),
                    f"menu file missing on disk: {source.menu_file.name}",
                )


class CustomerMenuPdfTests(TestCase):
    """The guest menu page serves the outlet's own PDF."""

    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            code="KINGCHEF",
            name_en="King Chef Restaurant",
            description="Multi-branch family restaurant.",
            default_phone="04 220 0001",
            status="active",
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-INTLCITY",
            slug="kingchef-intlcity",
            official_name="King Chef — International City",
            brand=cls.brand,
            city="International City",
            address="Italy Cluster, International City, Dubai",
            phone="04 220 0011",
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        page = SmartPage.objects.create(
            brand=cls.brand, outlet=cls.outlet, slug="kingchef-intlcity",
            page_title="King Chef — International City", published=True,
            published_at=timezone.now(),
        )
        cls.qr = QrCode.objects.create(
            brand=cls.brand, outlet=cls.outlet, destination_page=page,
            source_type="table", label="Table 1",
            qr_code_name="KINGCHEF-INTLCITY-TABLE-001",
            redirect_key="kcic-table-001",
        )
        MenuSource.objects.create(
            brand=cls.brand, outlet=cls.outlet,
            menu_type=MenuSource.MenuType.PDF,
            menu_file="PDF/KINGCHEF-INTLCITY.pdf",
            active=True,
        )

    def test_menu_page_links_the_outlets_own_pdf(self):
        response = self.client.get("/q/kcic-table-001/menu/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/media/PDF/KINGCHEF-INTLCITY.pdf"')

    def test_outlet_pdf_wins_over_brand_level_source(self):
        MenuSource.objects.create(
            brand=self.brand, outlet=None,
            menu_type=MenuSource.MenuType.PDF,
            menu_file="PDF/BRAND-DEFAULT.pdf",
            active=True,
        )
        response = self.client.get("/q/kcic-table-001/menu/")
        self.assertContains(response, 'href="/media/PDF/KINGCHEF-INTLCITY.pdf"')
        self.assertNotContains(response, "BRAND-DEFAULT.pdf")
