"""
Seed data for the Pasons Restaurant Smart QR platform.

Idempotent — safe to run multiple times. Creates:
  - Pasons Group + the 4 restaurant brands (plan change 2026-10-02)
  - the 13 real branches (Google Place IDs document, 2026-10-09):
    King Chef x8, Milan Veg x3, Paramount x1, Donar Istanbul x1 —
    each with its verified Google Place ID and an empty Review URL
    (the review link is built from the Place ID)
  - brand-level Smart Pages + outlet Smart Pages, with the full
    14-module set in the recommended order (spec sections 9-11)
  - demo menus (Milan Veg vegetarian, Donar Istanbul grill-oriented)
  - live offer campaigns
  - QR codes following the naming convention (spec section 22)
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Brand, Campaign, Group, Outlet, PageModule, QrCode, SmartPage
from apps.menu.models import MenuCategory, MenuItem, MenuSource, SpecialItem

WEEK_HOURS = {
    day: {"open": "10:00", "close": "23:00", "closed": False}
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}
WEEK_HOURS["fri"] = {"open": "14:00", "close": "23:30", "closed": False}

# Smart Page module order — spec section 11
MODULE_ORDER = [
    ("identity", "Brand / outlet identity", ""),
    ("hours", "Open / Closed & Timings", ""),
    ("campaign", "Current Campaign", ""),
    ("offers", "Special Offers", "View offers"),
    ("menu", "Full Menu", "View full menu"),
    ("google_review", "Google Review", "Review us on Google"),
    ("instagram", "Instagram", "Follow us"),
    ("social", "Social Links", ""),
    ("order", "Order / Enquire", "Order or enquire"),
    ("whatsapp", "WhatsApp", "Chat on WhatsApp"),
    ("call", "Call", "Call now"),
    ("directions", "Directions", "Get directions"),
    ("feedback", "Feedback", "Share feedback"),
    ("footer", "Pasons Group", ""),
]

BRANDS = [
    {
        "code": "KINGCHEF",
        # Tandoori warmth: maroon buttons and type. Waves stay deep green.
        "colors": {
            "primary": "#C0553C",
            "secondary": "#E0A189",
            "accent": "#C2A24B",
            "dark": "#6B2418",
        },
        "name_en": "King Chef Restaurant",
        "name_ar": "مطعم كينج شيف",
        "description": "Multi-branch family restaurant — biryani, grill and karak favourites.",
        "whatsapp": "97142200001",
        "phone": "04 220 0001",
        "social": {
            "instagram": "https://instagram.com/kingchefuae",
            "instagram_followers": "12.4K",
            "facebook": "https://facebook.com/kingchefuae",
            "tiktok": "https://tiktok.com/@kingchefuae",
            "youtube": "https://youtube.com/@kingchefuae",
            "x": "https://x.com/kingchefuae",
        },
        # Real branch Place IDs verified 2026-10-09 (Google Place IDs –
        # Restaurant Branches.md). Review URL stays empty: the review link is
        # built from the Place ID. A brand-level Place ID can be added later in
        # the panel (Brands screen) and acts as the fallback.
        "review": "",
        "outlets": [
            {
                "code": "KINGCHEF-INTLCITY",
                "slug": "international-city",
                "official_name": "King Chef — International City",
                "city": "International City",
                "emirate": "Dubai",
                "address": "France Cluster, International City, Dubai",
                "maps": "",
                "phone": "04 220 0011",
                "whatsapp": "97142200011",
                "google_place_id": "ChIJDX8qpTRnXz4RmYFym3s39bA",
                "google_review_url": "",
                "instagram_url": "https://instagram.com/kingchef.internationalcity",
            },
            {
                "code": "KINGCHEF-MUHAISINAH",
                "slug": "muhaisinah",
                "official_name": "King Chef — Muhaisinah",
                "city": "Muhaisinah",
                "emirate": "Dubai",
                "address": "Muhaisinah, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJz3xD_CdcXz4RpwFnb5EOOMc",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-QUSAIS",
                "slug": "al-qusais",
                "official_name": "King Chef — Al Qusais – Lomi Hamed",
                "city": "Al Qusais",
                "emirate": "Dubai",
                "address": "Al Qusais Industrial 3, Dubai",
                "maps": "",
                "phone": "04 220 0013",
                "whatsapp": "97142200013",
                "google_place_id": "ChIJ2zV-3g9dXz4RX60t4_6MqKo",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-ALQUOZ-IND2",
                "slug": "al-quoz-ind-2",
                "official_name": "King Chef — Al Quoz Ind-2",
                "city": "Al Quoz",
                "emirate": "Dubai",
                "address": "Al Quoz Industrial 2, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJXRPz825pXz4RPqjf3zvWWbk",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-ALQUOZ-PARSONS",
                "slug": "al-quoz-pasons-building",
                "official_name": "King Chef — Al Quoz – Pasons Building",
                "city": "Al Quoz",
                "emirate": "Dubai",
                "address": "Pasons Building, Al Quoz, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJX1SyzPFpXz4RRPHZ9lrVcPk",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-ALQUOZ",
                "slug": "al-quoz",
                "official_name": "King Chef — Al Quoz",
                "city": "Al Quoz",
                "emirate": "Dubai",
                "address": "Street 8, Al Quoz Industrial 1, Dubai",
                "maps": "",
                "phone": "04 220 0003",
                "whatsapp": "97142200003",
                "google_place_id": "ChIJdUuEQIlpXz4RlwdRP3gfv04",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-SHAJARAT-DIP2",
                "slug": "shajarat-dip-2",
                "official_name": "King Chef — Shajarat – DIP-2",
                "city": "Dubai Investment Park 2",
                "emirate": "Dubai",
                "address": "Shajarat, Dubai Investment Park 2 (DIP-2), Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJjR76pQpzXz4RR3qeYf_Za3w",
                "google_review_url": "",
            },
            {
                "code": "KINGCHEF-PARSONS-DIP2",
                "slug": "pasons-dip-2",
                "official_name": "King Chef — Pasons – DIP-2",
                "city": "Dubai Investment Park 2",
                "emirate": "Dubai",
                "address": "Pasons, Dubai Investment Park 2 (DIP-2), Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJk1l3QUJyXz4RwMWZT5oCABY",
                "google_review_url": "",
            },
        ],
        "menu": {
            "Starters": [
                ("Hummus with Bread", "حمص بالخبز", 22.00, None, "veg", "none"),
                ("Crispy Chicken Bites", "قطع دجاج مقرمشة", 28.00, None, "non_veg", "mild"),
            ],
            "Biryani": [
                ("Chicken Biryani", "برياني دجاج", 38.00, 32.00, "non_veg", "medium"),
                ("Mutton Biryani", "برياني لحم", 46.00, None, "non_veg", "medium"),
            ],
            "Main Course": [
                ("Butter Chicken", "دجاج بالزبدة", 42.00, None, "non_veg", "mild"),
                ("Dal Fry", "دال فراي", 26.00, None, "veg", "mild"),
            ],
            "Beverages": [
                ("Karak Chai", "شاي كرك", 8.00, None, "veg", "none"),
                ("Fresh Lime Mint", "ليمون بالنعناع", 14.00, None, "veg", "none"),
            ],
        },
    },
    {
        "code": "PARAMOUNT",
        # Premium dining: wine buttons and type. Waves stay deep green.
        "colors": {
            "primary": "#A8435C",
            "secondary": "#C98697",
            "accent": "#C2A24B",
            "dark": "#4A1B2A",
        },
        "name_en": "Paramount Restaurant",
        "name_ar": "مطعم باراماونت",
        "description": "Arabic and continental cuisine in a premium family setting.",
        "whatsapp": "97143300001",
        "phone": "04 330 0001",
        "social": {
            "instagram": "https://instagram.com/paramountuae",
            "instagram_followers": "8.9K",
            "facebook": "https://facebook.com/paramountuae",
            "youtube": "https://youtube.com/@paramountuae",
        },
        "review": "",
        "outlets": [
            {
                "code": "PARAMOUNT-QUSAIS",
                "slug": "al-qusais",
                "official_name": "Paramount — Al Qusais",
                "city": "Al Qusais",
                "emirate": "Dubai",
                "address": "Al Qusais, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJj5xHF1ddXz4RefV0z65m-SQ",
                "google_review_url": "",
            },
        ],
        "menu": {
            "Starters": [
                ("Shawarma Rolls", "شاورما رولز", 26.00, None, "non_veg", "mild"),
                ("Tabbouleh Salad", "تبولة", 24.00, None, "veg", "none"),
            ],
            "Main Course": [
                ("Paramount Kabsa", "كبسة باراماونت", 45.00, 39.00, "non_veg", "medium"),
                ("Grilled Hammour", "هامور مشوي", 58.00, None, "non_veg", "none"),
            ],
            "Desserts": [
                ("Umm Ali", "أم علي", 24.00, None, "veg", "none"),
                ("Baklava Selection", "بقلاوة مشكلة", 22.00, None, "veg", "none"),
            ],
        },
    },
    {
        "code": "MILANVEG",
        # Pure veg: garden green buttons and type. Waves stay deep green.
        "colors": {
            "primary": "#7FA06B",
            "secondary": "#9DB18C",
            "accent": "#C2A24B",
            "dark": "#2E5B3E",
        },
        "name_en": "Milan Veg",
        "name_ar": "ميلان فيج",
        "description": "Pure vegetarian kitchen — Indian and continental veg favourites.",
        "whatsapp": "97144400001",
        "phone": "04 440 0001",
        "social": {
            "instagram": "https://instagram.com/milanveguae",
            "instagram_followers": "5.2K",
            "facebook": "https://facebook.com/milanveguae",
        },
        "review": "",
        "outlets": [
            {
                "code": "MILANVEG-MUHAISNAH",
                "slug": "muhaisnah",
                "official_name": "Milan Veg — Muhaisnah",
                "city": "Muhaisnah",
                "emirate": "Dubai",
                "address": "Muhaisnah, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJt9zECeBfXz4Rgl9KfRnfPLk",
                "google_review_url": "",
            },
            {
                "code": "MILANVEG-QUSAIS",
                "slug": "al-qusais",
                "official_name": "Milan Veg — Al Qusais",
                "city": "Al Qusais",
                "emirate": "Dubai",
                "address": "Al Qusais, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJPesrN31dXz4RauFPfS7AFxE",
                "google_review_url": "",
            },
            {
                "code": "MILANVEG-KARAMA",
                "slug": "karama",
                "official_name": "Milan Veg — Karama",
                "city": "Karama",
                "emirate": "Dubai",
                "address": "Karama, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJTfp6HtdCXz4RALlvr6801HQ",
                "google_review_url": "",
            },
        ],  # real branches per the Place ID document
        "menu": {
            "Vegetarian": [
                ("Paneer Tikka Masala", "بانير تكا مسالا", 34.00, None, "veg", "medium"),
                ("Dal Tadka", "دال تدكا", 28.00, None, "veg", "mild"),
                ("Veg Biryani", "برياني خضار", 32.00, 27.00, "veg", "medium"),
            ],
            "Starters": [
                ("Paneer Tikka", "بانير تكا", 30.00, None, "veg", "mild"),
                ("Veg Spring Rolls", "سبرينغ رول خضار", 22.00, None, "veg", "none"),
            ],
            "Beverages": [
                ("Mango Lassi", "لاسي مانجو", 16.00, None, "veg", "none"),
                ("Masala Chaas", "مسالا تشاس", 12.00, None, "veg", "none"),
            ],
        },
    },
    {
        "code": "DONARIST",
        # Turkish grill: teal buttons and type. Waves stay deep green.
        "colors": {
            "primary": "#2E7D74",
            "secondary": "#7FB3AC",
            "accent": "#C2A24B",
            "dark": "#16454B",
        },
        "name_en": "Donar Istanbul",
        "name_ar": "دونار اسطنبول",
        "description": "Turkish grill house — donar, kebabs and mezze.",
        "whatsapp": "97145500001",
        "phone": "04 550 0001",
        "social": {
            "instagram": "https://instagram.com/donaristanbuluae",
            "instagram_followers": "6.7K",
            "tiktok": "https://tiktok.com/@donaristanbuluae",
            "facebook": "https://facebook.com/donaristanbuluae",
        },
        "review": "",
        "outlets": [
            {
                "code": "DONARIST-LULU",
                "slug": "lulu-village",
                "official_name": "Donar Istanbul — Lulu Center – Lulu Village",
                "city": "Lulu Village",
                "emirate": "Dubai",
                "address": "Lulu Center, Lulu Village, Dubai",
                "maps": "",
                "phone": "",
                "whatsapp": "",
                "google_place_id": "ChIJv-MPcKhfXz4RCNoMBOq6O6U",
                "google_review_url": "",
            },
        ],  # real branch per the Place ID document
        "menu": {
            "Grill": [
                ("Donar Kebab Plate", "طبق دونار كباب", 42.00, None, "non_veg", "mild"),
                ("Adana Kebab", "أضنة كباب", 48.00, 41.00, "non_veg", "medium"),
                ("Mixed Grill for Two", "مشويات مششخصة لشخصين", 95.00, None, "non_veg", "medium"),
            ],
            "Starters": [
                ("Hummus", "حمص", 20.00, None, "veg", "none"),
                ("Haydari", "هايداري", 18.00, None, "veg", "none"),
            ],
            "Desserts": [
                ("Kunafa", "كنافة", 26.00, None, "veg", "none"),
                ("Turkish Delight", "حلوى تركية", 14.00, None, "veg", "none"),
            ],
        },
    },
]


class Command(BaseCommand):
    help = "Seed Pasons Group, the 4 brands, demo outlets, menus, campaigns, pages and QR codes."

    def handle(self, *args, **options):
        now = timezone.now()

        group, _ = Group.objects.update_or_create(
            name="Pasons Group",
            defaults={
                "legal_name": "Pasons Group of Restaurants",
                "primary_domain": "{{PRIMARY_DOMAIN}}",
                "default_language": "en",
                "supported_languages": ["en", "ar"],
                "corporate_phone": "04 100 0000",
                "corporate_email": "info@pasons.example",
                "corporate_address": "Dubai, United Arab Emirates",
                "status": "active",
            },
        )
        self.stdout.write(f"Group: {group.name}")

        for spec in BRANDS:
            brand, _ = Brand.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "name_en": spec["name_en"],
                    "name_ar": spec["name_ar"],
                    "description": spec["description"],
                    "default_whatsapp": spec["whatsapp"],
                    "default_phone": spec["phone"],
                    "social_links": spec["social"],
                    "google_review_url": spec["review"],
                    "brand_colors": spec["colors"],
                    "status": "active",
                },
            )
            self.stdout.write(f"  Brand: {brand.name_en} ({brand.code})")

            # menus — brand-level is the mandatory base
            MenuCategory.objects.filter(brand=brand, outlet__isnull=True).delete()
            for sort, (cat_name, items) in enumerate(spec["menu"].items()):
                category = MenuCategory.objects.create(
                    brand=brand, name_en=cat_name, sort_order=sort
                )
                for i, (en, ar, price, offer, diet, spice) in enumerate(items):
                    MenuItem.objects.create(
                        category=category,
                        brand=brand,
                        name_en=en,
                        name_ar=ar,
                        description_en=f"{en} — freshly prepared.",
                        description_ar=ar,
                        regular_price=price,
                        offer_price=offer,
                        currency="AED",
                        dietary_type=diet,
                        spice_level=spice,
                        allergens=["nuts"] if "Baklava" in en or "Kunafa" in en else [],
                        available=True,
                        featured=offer is not None,
                        sort_order=i,
                    )

            # live offer campaign
            Campaign.objects.update_or_create(
                name=f"{brand.name_en} — Live Offers",
                brand=brand,
                defaults={
                    "campaign_type": "offer",
                    "outlet_scope": "all_outlets",
                    "start_at": now - timedelta(days=7),
                    "end_at": now + timedelta(days=30),
                    "cta_label": "See today's offers",
                    "status": "live",
                },
            )

            # brand-level Smart Page (mandatory, always complete)
            brand_page = self._make_page(
                brand=brand,
                outlet=None,
                slug=brand.code.lower(),
                title=brand.name_en,
                hero_title=brand.name_en,
                hero_subtitle=brand.description,
            )

            # outlet pages (optional overrides)
            for out_spec in spec["outlets"]:
                outlet, _ = Outlet.objects.update_or_create(
                    code=out_spec["code"],
                    defaults={
                        "official_name": out_spec["official_name"],
                        "slug": out_spec.get("slug", ""),
                        "brand": brand,
                        "city": out_spec["city"],
                        "emirate": out_spec["emirate"],
                        "country": "UAE",
                        "address": out_spec["address"],
                        "google_maps_url": out_spec["maps"],
                        "google_place_id": out_spec.get("google_place_id", ""),
                        "google_review_url": out_spec.get("google_review_url", ""),
                        "instagram_url": out_spec.get("instagram_url", ""),
                        "phone": out_spec["phone"],
                        "whatsapp": out_spec["whatsapp"],
                        "opening_hours": WEEK_HOURS,
                        "active": True,
                    },
                )
                self._make_page(
                    brand=brand,
                    outlet=outlet,
                    slug=out_spec["code"].lower(),
                    title=f"{brand.name_en} — {outlet.official_name.split('—')[-1].strip()}",
                    hero_title=outlet.official_name,
                    hero_subtitle=f"{brand.description} Open daily at {out_spec['address']}.",
                )

            # QR codes — naming convention [BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE] (§22)
            if spec["outlets"]:
                first = Outlet.objects.get(code=spec["outlets"][0]["code"])
                first_page = SmartPage.objects.get(slug=spec["outlets"][0]["code"].lower())
                self._make_qr(
                    f"{brand.code}-{first.code.split('-')[-1]}-ENTRANCE-01",
                    brand, first, first_page, "entrance", "Main entrance",
                )
                self._make_qr(
                    f"{brand.code}-{first.code.split('-')[-1]}-TABLE-018",
                    brand, first, first_page, "table", "Table 18",
                )
            else:
                self._make_qr(
                    f"{brand.code}-MAIN-FLYER-01",
                    brand, None, brand_page, "flyer", "Printed flyer",
                )
                self._make_qr(
                    f"{brand.code}-MAIN-INSTAGRAM-01",
                    brand, None, brand_page, "social", "Instagram bio link",
                )

            if spec["code"] == "KINGCHEF":
                self._seed_kingchef_fixtures(brand, now)

        self.stdout.write(self.style.SUCCESS("Seed complete — 4 brands ready."))

    def _seed_kingchef_fixtures(self, brand, now):
        """Acceptance fixtures: International City and Al Qusais."""
        intl = Outlet.objects.get(code="KINGCHEF-INTLCITY")
        qusais = Outlet.objects.get(code="KINGCHEF-QUSAIS")
        intl_page = SmartPage.objects.get(outlet=intl)
        qusais_page = SmartPage.objects.get(outlet=qusais)

        self._make_qr(
            "KINGCHEF-INTLCITY-TABLE-001",
            brand, intl, intl_page, "table", "Table 1",
            redirect_key="kcic-table-001",
        )
        self._make_qr(
            "KINGCHEF-QUSAIS-TABLE-004",
            brand, qusais, qusais_page, "table", "Table 4",
            redirect_key="kcqusais-table-004",
        )

        MenuSource.objects.update_or_create(
            brand=brand, outlet=None,
            defaults={
                "menu_type": MenuSource.MenuType.EXTERNAL_URL,
                "menu_url": "https://menu.kingchef.example/brand",
                "active": True,
            },
        )
        MenuSource.objects.update_or_create(
            brand=brand, outlet=intl,
            defaults={
                "menu_type": MenuSource.MenuType.EXTERNAL_URL,
                "menu_url": "https://menu.kingchef.example/international-city",
                "ordering_url": "https://order.kingchef.example/international-city",
                "active": True,
            },
        )

        SpecialItem.objects.update_or_create(
            brand=brand, outlet=None, title_en="House Chicken Biryani",
            defaults={
                "kind": SpecialItem.Kind.SIGNATURE,
                "description": "Slow-cooked dum biryani, brand signature.",
                "original_price": 38,
                "active": True,
                "display_order": 1,
            },
        )
        SpecialItem.objects.update_or_create(
            brand=brand, outlet=intl, title_en="International City Mandi",
            defaults={
                "kind": SpecialItem.Kind.SIGNATURE,
                "description": "Outlet-only mandi, served Friday to Sunday.",
                "original_price": 49,
                "active": True,
                "display_order": 1,
            },
        )
        SpecialItem.objects.update_or_create(
            brand=brand, outlet=intl, title_en="Friday Grill Platter",
            defaults={
                "kind": SpecialItem.Kind.WEEKEND,
                "description": "Photo and title only — price is never shown.",
                "active": True,
                "display_order": 2,
            },
        )
        SpecialItem.objects.update_or_create(
            brand=brand, outlet=intl, title_en="Family Biryani Bucket",
            defaults={
                "kind": SpecialItem.Kind.OFFER,
                "original_price": 89,
                "offer_price": 69,
                "discount_label": "22% OFF",
                "active": True,
                "display_order": 3,
            },
        )

    # ------------------------------------------------------------------ helpers
    def _make_page(self, brand, outlet, slug, title, hero_title, hero_subtitle):
        page, _ = SmartPage.objects.update_or_create(
            slug=slug,
            defaults={
                "brand": brand,
                "outlet": outlet,
                "template_id": "smart_v1",
                "page_title": title,
                "hero_title": hero_title,
                "hero_subtitle": hero_subtitle,
                "default_language": "en",
                "enabled_languages": ["en", "ar"],
                "published": True,
                "published_at": timezone.now(),
            },
        )
        if not page.modules.exists():
            PageModule.objects.bulk_create(
                [
                    PageModule(
                        page=page,
                        module_type=mtype,
                        title=heading,
                        cta_label=cta,
                        sort_order=i,
                        enabled=True,
                    )
                    for i, (mtype, heading, cta) in enumerate(MODULE_ORDER)
                ]
            )
        return page

    def _make_qr(self, name, brand, outlet, page, source_type, source_location, redirect_key=None):
        defaults = {
            "destination_page": page,
            "source_type": source_type,
            "source_location": source_location,
            "brand": brand,
            "outlet": outlet,
            "active": True,
        }
        qr, _ = QrCode.objects.update_or_create(qr_code_name=name, defaults=defaults)
        if redirect_key and qr.redirect_key != redirect_key:
            QrCode.objects.filter(pk=qr.pk).update(redirect_key=redirect_key)
        self.stdout.write(f"    QR: {name}")
