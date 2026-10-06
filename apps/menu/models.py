"""
Restaurant digital menu, specials & booklet — spec section 10, meta-prompt parts B & C.

Specials (Signature dishes, Weekend specials, Offers),
MenuSource (Booklet pages, PDF, or External URL), MenuPage.
"""

import uuid
from django.db import models
from django.utils import timezone

from apps.core.models import Brand, Outlet, TimeStampedModel


class MenuCategory(TimeStampedModel):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="categories")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True,
        related_name="categories",
        help_text="Null = brand-level category (mandatory base)",
    )
    name_en = models.CharField(max_length=80)
    name_ar = models.CharField(max_length=80, blank=True)
    image = models.ImageField(upload_to="menu/categories/", blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Menu Category"
        verbose_name_plural = "Menu Categories"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.name_en} — {self.brand.code}"


class MenuItem(TimeStampedModel):
    class DietaryType(models.TextChoices):
        VEG = "veg", "Vegetarian"
        NON_VEG = "non_veg", "Non-vegetarian"
        VEGAN = "vegan", "Vegan"

    class SpiceLevel(models.TextChoices):
        NONE = "none", "Not spicy"
        MILD = "mild", "Mild"
        MEDIUM = "medium", "Medium"
        HOT = "hot", "Hot"
        EXTRA_HOT = "extra_hot", "Extra hot"

    category = models.ForeignKey(
        MenuCategory, on_delete=models.CASCADE, related_name="items"
    )
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="menu_items")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True,
        related_name="menu_items",
        help_text="Null = brand-level item (mandatory base)",
    )
    overrides = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True,
        related_name="outlet_versions",
        help_text="Outlet item that overrides this brand-level item",
    )
    name_en = models.CharField(max_length=120)
    name_ar = models.CharField(max_length=120, blank=True)
    description_en = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    image = models.ImageField(upload_to="menu/items/", blank=True)
    regular_price = models.DecimalField(max_digits=8, decimal_places=2)
    offer_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="AED")
    dietary_type = models.CharField(
        max_length=8, choices=DietaryType.choices, default=DietaryType.NON_VEG
    )
    spice_level = models.CharField(
        max_length=12, choices=SpiceLevel.choices, default=SpiceLevel.NONE
    )
    allergens = models.JSONField(default=list, blank=True)
    available = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Menu Item"
        verbose_name_plural = "Menu Items"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.name_en} — {self.brand.code}"

    @property
    def effective_price(self):
        return self.offer_price if self.offer_price is not None else self.regular_price

    @property
    def discount_pct(self):
        """Rounded discount percentage for offer chips (0 when not on offer)."""
        if self.offer_price is None or not self.regular_price:
            return 0
        if self.offer_price >= self.regular_price:
            return 0
        return round((1 - self.offer_price / self.regular_price) * 100)


def items_for(brand, outlet=None):
    """
    Resolve the visible menu for a brand or outlet (spec section 6/10):
    brand-level rows, with outlet overrides replacing their base item,
    plus any outlet-only additions. Returned in category order.
    """
    base = MenuItem.objects.filter(brand=brand, outlet__isnull=True).select_related(
        "category"
    )
    if outlet is None:
        return list(base)

    overrides = {
        o.overrides_id: o
        for o in MenuItem.objects.filter(outlet=outlet, overrides__isnull=False)
    }
    extra = list(MenuItem.objects.filter(outlet=outlet, overrides__isnull=True))
    resolved = [overrides.get(item.id, item) for item in base]
    return resolved + extra


class SpecialItem(TimeStampedModel):
    """
    Special items for customer landing:
    1. Signature Dishes (photo, title, optional description, optional price)
    2. Weekend Specials (photo, title only — never price)
    3. Offers (photo, title, original_price struck through, offer_price, discount_label)
    """

    class Kind(models.TextChoices):
        SIGNATURE = "signature", "Signature Dish"
        WEEKEND = "weekend", "Weekend Special"
        OFFER = "offer", "Special Offer"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="specials")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True, related_name="specials",
        help_text="Null = whole brand; set = specific outlet",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SIGNATURE)
    title_en = models.CharField(max_length=140)
    title_ar = models.CharField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="menu/specials/", blank=True)
    original_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    offer_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=3, default="AED")
    discount_label = models.CharField(max_length=60, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    replaces = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="outlet_replacements",
        help_text="Brand-level special item that this outlet special replaces",
    )

    class Meta:
        verbose_name = "Special Item"
        verbose_name_plural = "Special Items"
        ordering = ["display_order", "id"]

    def __str__(self):
        scope = self.outlet.official_name if self.outlet else "Brand-wide"
        return f"{self.title_en} ({self.get_kind_display()}) [{scope}]"

    def is_live(self, now=None):
        now = now or timezone.now()
        if not self.active:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True

    @property
    def discount_pct(self):
        if self.offer_price is None or not self.original_price:
            return 0
        if self.offer_price >= self.original_price:
            return 0
        return round((1 - float(self.offer_price) / float(self.original_price)) * 100)

    def save(self, *args, **kwargs):
        if self.kind == self.Kind.OFFER and not self.discount_label and self.discount_pct > 0:
            self.discount_label = f"{self.discount_pct}% OFF"
        super().save(*args, **kwargs)


class MenuSource(TimeStampedModel):
    """
    Configures digital menu source per brand or per outlet.
    Priority: Outlet MenuSource -> Brand MenuSource -> Outlet.menu_url -> Brand.default_menu_url
    """

    class MenuType(models.TextChoices):
        PAGES = "pages", "Booklet (Page Images)"
        PDF = "pdf", "PDF Document"
        EXTERNAL_URL = "external_url", "External Website Link"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="menu_sources")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True,
        related_name="menu_sources",
        help_text="Null = brand-level menu source",
    )
    menu_type = models.CharField(
        max_length=16, choices=MenuType.choices, default=MenuType.PAGES
    )
    menu_file = models.FileField(upload_to="menu/pdf/", blank=True)
    menu_url = models.URLField(blank=True, help_text="Used when menu_type is external_url")
    ordering_url = models.URLField(blank=True, help_text="Optional outbound 'Order Online' link")
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Menu Source"
        verbose_name_plural = "Menu Sources"
        ordering = ["-id"]

    def __str__(self):
        scope = self.outlet.official_name if self.outlet else "Brand-wide"
        return f"{self.brand.name_en} Menu ({self.get_menu_type_display()}) [{scope}]"


class MenuPage(TimeStampedModel):
    """Single page image of a physical menu booklet."""

    menu_source = models.ForeignKey(
        MenuSource, on_delete=models.CASCADE, related_name="pages"
    )
    page_number = models.PositiveSmallIntegerField(default=1)
    image = models.ImageField(upload_to="menu/booklet/")
    width = models.PositiveIntegerField(default=800)
    height = models.PositiveIntegerField(default=1200)

    class Meta:
        verbose_name = "Menu Page"
        verbose_name_plural = "Menu Pages"
        ordering = ["page_number", "id"]
        unique_together = [["menu_source", "page_number"]]

    def __str__(self):
        return f"Page {self.page_number} of {self.menu_source}"
