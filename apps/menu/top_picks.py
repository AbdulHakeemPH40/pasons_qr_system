"""
Brand-wise Top 10 Food & Beverages.

Source: Docs/Pasons_Restaurants_Top10_Food_Beverages.md (compiled Oct 2026
from the 13 printed outlet menus). Each brand's guest menu page shows its own
two lists: "Most Popular" (food) and "Top Beverages". The printed menu stays
behind the Full menu PDF card.

Client rules (2026-10-15):
- Names are the dishes' real menu names; variant notes from the printed menus
  are kept verbatim in brackets. No invented names.
- No prices are seeded or shown ("no need price"). Staff can add prices from
  the panel later; regular_price stays 0.00 until then.
- Images are placeholders until staff upload photos from the panel (outlet
  managers included).
"""

from apps.core.models import Brand
from apps.menu.models import MenuCategory, MenuItem

# Category names double as the guest page section titles. Items placed in
# these categories (brand-level, or outlet versions of them) are what the
# guest menu page shows, so staff fully control the lists from the panel.
TOP_FOOD_CATEGORY = "Most Popular"
TOP_DRINK_CATEGORY = "Top Beverages"

TOP_PICKS = {
    "KINGCHEF": {
        "food": [
            "Chicken Biriyani (+ Beef Chilli Biriyani)",
            "Charcoal Chicken (King Chef Special / Peri Peri)",
            "Beef Ularthiyathu",
            "Kerala Poratta + Kizhi / Kothu Poratta",
            "Butter Chicken (Boneless)",
            "Chilli Chicken / Chicken Manchurian",
            "Fish Pollichathu / Kanthari Tawa",
            "Kerala Fish Curry Meals / Pothichoru",
            "Dynamite / LPG Chicken (Starters)",
            "Zinker Club Sandwich / Shawarma",
        ],
        "drinks": [
            "Lemon Mint",
            "Avil Milk",
            "Falooda / Real Falooda",
            "Mango Juice",
            "Avocado Juice",
            "King Chef Special Juice",
            "Kulukki Sarbath",
            "Mango Lassi",
            "Oreo / KitKat Milkshake",
        ],
    },
    "MILANVEG": {
        "food": [
            "Masala Dosa / Ghee Roast",
            "Mini Tiffin with Filter Coffee",
            "Idly Vada Set",
            "South / North Indian Thali (Lunch)",
            "Paneer Butter Masala",
            "Gobi Manchurian",
            "Pani Puri / Dahi Aloo Puri",
            "Special Pav Bhaji",
            "Veg / Hyderabadi Biriyani",
            "Paneer Tikka (Tandoori)",
        ],
        "drinks": [
            "Filter Coffee",
            "Falooda / Royal Falooda",
            "Lemon Mint",
            "Mango Milkshake",
            "Oreo Milkshake",
            "Butter Milk",
            "Milan Special (Avocado, Mango, Ice Cream)",
            "Nannari Sarbath",
        ],
    },
    "DONARIST": {
        "food": [
            "Doner Box Shawarma",
            "Chicken Shawarma Sandwich",
            "Doner Istanbul Mixed Grill / Mixed Grill Plate",
            "Iskender Kebab (Meat / Chicken)",
            "Beyti Kebab",
            "Ali Nazik",
            "Mandi \u2013 Chicken / Mutton",
            "Hummus / Pink Sultan",
            "Turkish Delight Breakfast",
            "Kunafa Profit Roll / San Sebasti\u00e1n Cake",
        ],
        "drinks": [
            "Turkish Coffee",
            "Piscado Delight (Avocado + Pistachio)",
            "Fruits Cocktail",
            "Fresh Orange",
            "Avocado Juice",
            "Lemon Mint",
            "Laban Ayran",
            "Dry Cloud",
            "Classic Mojito",
            "Oreo Milkshake",
        ],
    },
    "PARAMOUNT": {
        "food": [
            "Thalassery / Lagoon Chicken Biriyani",
            "Paramount Fried Chicken",
            "Charcoal Chicken / Mix Grill",
            "Kerala Paratha + Beef Fry",
            "Fish Malabar Tawa / Pollichathu",
            "Butter Chicken (Boneless)",
            "Chilli Chicken",
            "Special Pothichoru / Pothi Biriyani",
            "Dynamite Prawns / Chicken",
            "Chicken Club / Saj Shawarma",
        ],
        "drinks": [
            "Chiratta Falooda",
            "Kulukki Sarbath",
            "Mojitos (Lemon / Passion Fruit / Strawberry)",
            "Kannur Cocktail",
            "Mangala Sarbath",
            "Lemon Juice / Lemon Mint",
            "Mango Lassi",
            "Milk Sarbath",
            "Oreo / Galaxy Milkshake",
            "Royal Falooda",
        ],
    },
}

# Milan Veg is a pure vegetarian brand; the others are non-vegetarian menus.
_BRAND_DIET = {
    "MILANVEG": MenuItem.DietaryType.VEG,
}


def seed_top_picks():
    """
    Create or refresh the two top-pick lists for every brand in TOP_PICKS.

    Idempotent: re-running updates existing rows in place (matched by
    category + brand + name) and never touches outlet-level rows, uploaded
    photos, or any other category.
    """
    made = {}
    for code, lists in TOP_PICKS.items():
        brand = Brand.objects.filter(code=code).first()
        if brand is None:
            continue
        diet = _BRAND_DIET.get(code, MenuItem.DietaryType.NON_VEG)
        counts = []
        for cat_name, names, sort in (
            (TOP_FOOD_CATEGORY, lists["food"], 0),
            (TOP_DRINK_CATEGORY, lists["drinks"], 1),
        ):
            category, _ = MenuCategory.objects.get_or_create(
                brand=brand,
                outlet=None,
                name_en=cat_name,
                defaults={"sort_order": sort},
            )
            for rank, name in enumerate(names):
                MenuItem.objects.update_or_create(
                    category=category,
                    brand=brand,
                    outlet=None,
                    name_en=name,
                    defaults={
                        "regular_price": 0,
                        "offer_price": None,
                        "currency": "AED",
                        "dietary_type": diet,
                        "spice_level": MenuItem.SpiceLevel.NONE,
                        "available": True,
                        "featured": True,
                        "sort_order": rank,
                    },
                )
            MenuItem.objects.filter(
                category=category,
                brand=brand,
                outlet=None,
            ).exclude(name_en__in=names).delete()
            counts.append((cat_name, len(names)))
        made[brand.name_en] = counts
    return made
