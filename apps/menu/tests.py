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
from apps.menu.models import MenuCategory, MenuItem, MenuSource
from apps.menu.top_picks import (
    TOP_DRINK_CATEGORY,
    TOP_FOOD_CATEGORY,
    TOP_PICKS,
    seed_top_picks,
)

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

    def test_menu_pdf_renders_ios26_live_tile_contract(self):
        """The Full menu PDF card renders as an iOS 26 liquid-glass live tile
        while preserving its public contract (class, href, title, subtitle, Open CTA)."""
        response = self.client.get("/q/kcic-table-001/menu/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('class="menu-pdf"', body)
        self.assertIn("Full menu PDF", body)
        self.assertIn("Every page, exactly as printed", body)
        self.assertIn("Digital Booklet", body)
        self.assertIn("menu-pdf-sheet--back", body)
        self.assertIn("menu-pdf-sheet--front", body)
        self.assertIn("menu-pdf-tag", body)
        self.assertIn("menu-pdf-cta-orb", body)
        self.assertIn("Open", body)


class TopPicksSeedTests(TestCase):
    """seed_top_picks() writes the brand-wise Top 10 lists verbatim from
    Docs/Pasons_Restaurants_Top10_Food_Beverages.md (names only, no prices)."""

    @classmethod
    def setUpTestData(cls):
        for code, name in (
            ("KINGCHEF", "King Chef Restaurant"),
            ("MILANVEG", "Milan Veg"),
            ("DONARIST", "Donar Istanbul"),
            ("PARAMOUNT", "Paramount Restaurant"),
        ):
            Brand.objects.create(code=code, name_en=name, status="active")

    def test_seeds_food_and_drink_lists_for_every_brand(self):
        made = seed_top_picks()
        self.assertEqual(len(made), 4)
        for code in ("KINGCHEF", "MILANVEG", "DONARIST", "PARAMOUNT"):
            brand = Brand.objects.get(code=code)
            with self.subTest(code=code):
                food = MenuItem.objects.filter(
                    brand=brand, category__name_en=TOP_FOOD_CATEGORY, outlet__isnull=True
                )
                drinks = MenuItem.objects.filter(
                    brand=brand, category__name_en=TOP_DRINK_CATEGORY, outlet__isnull=True
                )
                self.assertEqual(food.count(), len(TOP_PICKS[code]["food"]))
                self.assertEqual(drinks.count(), len(TOP_PICKS[code]["drinks"]))

    def test_lists_are_brand_wise_from_the_doc(self):
        seed_top_picks()
        kc = Brand.objects.get(code="KINGCHEF")
        milan = Brand.objects.get(code="MILANVEG")
        self.assertTrue(MenuItem.objects.filter(
            brand=kc, category__name_en=TOP_FOOD_CATEGORY,
            name_en="Chicken Biriyani (+ Beef Chilli Biriyani)",
        ).exists())
        self.assertTrue(MenuItem.objects.filter(
            brand=kc, category__name_en=TOP_DRINK_CATEGORY, name_en="Lemon Mint",
        ).exists())
        self.assertTrue(MenuItem.objects.filter(
            brand=milan, category__name_en=TOP_FOOD_CATEGORY,
            name_en="Masala Dosa / Ghee Roast",
        ).exists())
        # a brand's list never leaks into another brand
        self.assertFalse(MenuItem.objects.filter(
            brand=kc, name_en="Masala Dosa / Ghee Roast",
        ).exists())

    def test_no_karak_or_tea_in_beverages_across_all_brands(self):
        """Client 2026-10-15: remove Karak Chai / tea from Top Beverages
        across all brands."""
        seed_top_picks()
        drinks = MenuItem.objects.filter(category__name_en=TOP_DRINK_CATEGORY)
        for item in drinks:
            lowered = item.name_en.lower()
            self.assertNotIn("karak", lowered)
            self.assertNotIn("tea", lowered)
            self.assertNotIn("chai", lowered)

    def test_no_prices_are_seeded(self):
        """Client 2026-10-15: no price on these lists; staff may add prices
        later from the panel."""
        seed_top_picks()
        self.assertFalse(MenuItem.objects.exclude(regular_price=0).exists())

    def test_reseeding_is_idempotent_and_keeps_uploaded_photos(self):
        seed_top_picks()
        expected_total = sum(
            len(v["food"]) + len(v["drinks"]) for v in TOP_PICKS.values()
        )
        item = MenuItem.objects.get(
            brand__code="KINGCHEF", category__name_en=TOP_DRINK_CATEGORY, name_en="Lemon Mint"
        )
        item.image = "menu/items/lemon_mint.png"   # pretend staff uploaded a photo
        item.save(update_fields=["image", "updated_at"])
        seed_top_picks()
        self.assertEqual(MenuItem.objects.count(), expected_total)
        item.refresh_from_db()
        self.assertEqual(item.image.name, "menu/items/lemon_mint.png")


class TopPicksGuestPageTests(TestCase):
    """The guest menu page shows the brand's own Top 10 lists: names only,
    no prices, photo once uploaded and placeholder art until then."""

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
            official_name="King Chef \u2014 International City",
            brand=cls.brand,
            city="International City",
            address="Italy Cluster, International City, Dubai",
            phone="04 220 0011",
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        page = SmartPage.objects.create(
            brand=cls.brand, outlet=cls.outlet, slug="kingchef-intlcity",
            page_title="King Chef \u2014 International City", published=True,
            published_at=timezone.now(),
        )
        cls.qr = QrCode.objects.create(
            brand=cls.brand, outlet=cls.outlet, destination_page=page,
            source_type="table", label="Table 1",
            qr_code_name="KINGCHEF-INTLCITY-TABLE-001",
            redirect_key="kcic-table-001",
        )
        Brand.objects.create(code="MILANVEG", name_en="Milan Veg", status="active")
        seed_top_picks()

    def test_page_shows_own_brand_lists_only(self):
        response = self.client.get("/q/kcic-table-001/menu/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Most Popular", body)
        self.assertIn("Top Beverages", body)
        self.assertIn("Lemon Mint", body)          # King Chef's own list
        self.assertIn("Beef Ularthiyathu", body)
        self.assertNotIn("Karak Chai", body)       # Karak / tea removed from beverages
        self.assertNotIn("Masala Dosa", body)      # Milan Veg's list never leaks

    def test_cards_show_names_only_no_prices(self):
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        self.assertNotIn("menu-price", body)       # no price markup at all
        self.assertNotIn("AED", body)

    def test_placeholder_art_until_staff_upload_a_photo(self):
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        self.assertIn("menu-plate", body)          # placeholder glyph shown
        item = MenuItem.objects.get(
            brand=self.brand, category__name_en=TOP_DRINK_CATEGORY, name_en="Lemon Mint"
        )
        item.image = "menu/items/lemon_mint.png"
        item.save(update_fields=["image", "updated_at"])
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        self.assertIn("/media/menu/items/lemon_mint.png", body)

    def test_each_list_is_capped_at_ten(self):
        food_cat = MenuCategory.objects.get(
            brand=self.brand, name_en=TOP_FOOD_CATEGORY, outlet__isnull=True
        )
        for n in range(5):
            MenuItem.objects.create(
                category=food_cat, brand=self.brand,
                name_en=f"Late addition {n}", regular_price=0, available=True,
                sort_order=10 + n,
            )
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        expected_cards = 10 + len(TOP_PICKS["KINGCHEF"]["drinks"])
        self.assertEqual(body.count('<article class="menu-card'), expected_cards)
        self.assertNotIn("Late addition 4", body)

    def test_lists_are_specials_style_swipeable_rails(self):
        """UI 2026-10-15 (client): the lists render as the specials page
        glass image cards in horizontal snap rails with arrow controls,
        never as a plain vertical stack."""
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        self.assertEqual(body.count('class="snap-row"'), 2)     # one rail per list
        self.assertEqual(body.count("data-row-prev"), 2)        # glass arrows per rail
        self.assertEqual(body.count("data-row-next"), 2)
        self.assertIn('class="menu-card promo-card"', body)     # shared image-card system
        self.assertIn("promo-media", body)                      # photo well on every card
        self.assertIn("specials_carousel.js", body)             # shared rail behaviour

    def test_long_names_never_overflow_the_card(self):
        """A glued 351px dish name once broke the 390px layout; names must be
        clamped to two lines inside the card."""
        body = self.client.get("/q/kcic-table-001/menu/").content.decode()
        self.assertIn("-webkit-line-clamp: 2", self._theme_css())
        self.assertIn("overflow-wrap: anywhere", self._theme_css())

    @staticmethod
    def _theme_css():
        import os
        from django.conf import settings
        path = os.path.join(settings.BASE_DIR, "static", "css", "theme-warm.css")
        with open(path, encoding="utf-8") as fh:
            return fh.read()
