"""
Core data model — spec section 21.

Hierarchy (spec section 5-6): Group -> Brand (mandatory) -> Outlet (optional).
A brand-level page is always complete on its own; outlets are field-level
overrides. No loyalty/points/stamp models exist anywhere in this platform.
"""

import uuid

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Group(TimeStampedModel):
    """Pasons Group — the owning group. Not a brand (plan change 2026-10-02)."""

    name = models.CharField(max_length=120)
    legal_name = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to="group/", blank=True)
    primary_domain = models.CharField(max_length=200, blank=True)
    default_language = models.CharField(max_length=8, default="en")
    supported_languages = models.JSONField(
        default=list, blank=True, help_text='e.g. ["en", "ar"]'
    )
    corporate_phone = models.CharField(max_length=40, blank=True)
    corporate_email = models.EmailField(blank=True)
    corporate_address = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="active")

    class Meta:
        verbose_name = "Group"
        verbose_name_plural = "Groups"

    def __str__(self):
        return self.name


class Brand(TimeStampedModel):
    """Restaurant brand — mandatory owner of all content (spec section 21)."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    name_en = models.CharField(max_length=120)
    name_ar = models.CharField(max_length=120, blank=True)
    code = models.SlugField(
        max_length=20, unique=True, help_text="e.g. KINGCHEF (used in QR naming §22)"
    )
    logo = models.ImageField(upload_to="brands/", blank=True)
    brand_colors = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"primary": "#7FA06B"}'
    )
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    default_whatsapp = models.CharField(max_length=40, blank=True)
    default_phone = models.CharField(max_length=40, blank=True)
    default_menu_url = models.URLField(blank=True)
    default_ordering_url = models.URLField(blank=True)
    social_links = models.JSONField(
        default=dict,
        blank=True,
        help_text="instagram, facebook, youtube, tiktok, x, linkedin",
    )
    google_place_id = models.CharField(
        max_length=120, blank=True, help_text="Used when no outlet places exist"
    )
    google_review_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, default="active")

    class Meta:
        verbose_name = "Brand"
        verbose_name_plural = "Brands"
        ordering = ["name_en"]

    def __str__(self):
        return f"{self.name_en} ({self.code})"


class Outlet(TimeStampedModel):
    """Optional outlet/branch — every outlet belongs to exactly one brand."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=30, unique=True, help_text="e.g. KINGCHEF-DEIRA")
    slug = models.SlugField(max_length=60, blank=True, help_text="e.g. international-city")
    official_name = models.CharField(max_length=160)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="outlets")
    city = models.CharField(max_length=80, blank=True)
    emirate = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="UAE")
    address = models.TextField(blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    google_maps_url = models.URLField(blank=True)
    google_place_id = models.CharField(max_length=120, blank=True)
    google_review_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    menu_url = models.URLField(blank=True)
    ordering_url = models.URLField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    whatsapp = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"mon": {"open": "10:00", "close": "23:00", "closed": false}}',
    )
    active = models.BooleanField(default=True)
    launch_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Outlet"
        verbose_name_plural = "Outlets"
        ordering = ["brand__name_en", "official_name"]
        unique_together = [["brand", "slug"]]

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.official_name) or self.code.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.official_name} [{self.brand.code}]"

    # --- resolution: outlet fields fall back to brand fields (spec section 6)
    def resolved(self, field):
        """Return the outlet value for `field`, or the brand default when empty."""
        value = getattr(self, field, "")
        if value:
            return value
        return getattr(self.brand, f"default_{field}", "") or ""

    def is_open_now(self, now=None):
        """Compute open/closed from opening_hours JSON (spec section 9)."""
        now = now or timezone.localtime()
        day = now.strftime("%a").lower()[:3]
        hours = (self.opening_hours or {}).get(day)
        if not hours or hours.get("closed"):
            return False
        try:
            current = now.hour * 60 + now.minute
            oh, om = (int(x) for x in hours["open"].split(":"))
            ch, cm = (int(x) for x in hours["close"].split(":"))
            return oh * 60 + om <= current <= ch * 60 + cm
        except (KeyError, ValueError):
            return False


class SmartPage(TimeStampedModel):
    """
    Smart Page — brand-level (outlet=null) or outlet-level (spec section 9).
    Outlet pages resolve field-by-field to the brand page when empty.
    """

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="pages")
    outlet = models.ForeignKey(
        Outlet,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pages",
        help_text="Null = brand-level page (always required and complete)",
    )
    template_id = models.CharField(max_length=40, default="smart_v1")
    slug = models.SlugField(max_length=120, unique=True)
    page_title = models.CharField(max_length=160)
    hero_title = models.CharField(max_length=160, blank=True)
    hero_subtitle = models.CharField(max_length=240, blank=True)
    hero_image = models.ImageField(upload_to="pages/", blank=True)
    default_language = models.CharField(max_length=8, default="en")
    enabled_languages = models.JSONField(default=list, blank=True)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    # Smart Page fields that fall back to the brand page when blank
    FALLBACK_FIELDS = ("page_title", "hero_title", "hero_subtitle", "hero_image")

    class Meta:
        verbose_name = "Smart Page"
        verbose_name_plural = "Smart Pages"
        ordering = ["brand__name_en", "outlet__official_name"]

    def __str__(self):
        scope = self.outlet.official_name if self.outlet_id else "brand-level"
        return f"{self.slug} ({scope})"

    def publish(self):
        self.published = True
        self.published_at = self.published_at or timezone.now()
        self.save(update_fields=["published", "published_at", "updated_at"])

    @property
    def brand_page(self):
        """The mandatory brand-level page backing this page."""
        if self.outlet_id is None:
            return self
        return SmartPage.objects.filter(brand=self.brand, outlet__isnull=True).first()

    def resolved(self, field):
        """Field-by-field fallback: outlet page -> brand page (spec section 6)."""
        value = getattr(self, field)
        if value or self.outlet_id is None:
            return value
        base = self.brand_page
        return getattr(base, field) if base else value


class PageModule(TimeStampedModel):
    """Content module on a Smart Page (spec sections 11, 37)."""

    class ModuleType(models.TextChoices):
        IDENTITY = "identity", "Brand / outlet identity"
        HOURS = "hours", "Open/closed status & timings"
        CAMPAIGN = "campaign", "Current campaign"
        OFFERS = "offers", "Special offers"
        MENU = "menu", "Full menu"
        GOOGLE_REVIEW = "google_review", "Google review"
        INSTAGRAM = "instagram", "Instagram"
        SOCIAL = "social", "Other social links"
        ORDER = "order", "Order / Enquire"
        WHATSAPP = "whatsapp", "WhatsApp"
        CALL = "call", "Call"
        DIRECTIONS = "directions", "Directions"
        FEEDBACK = "feedback", "Feedback"
        FOOTER = "footer", "Footer"
        GAME = "game", "Play a game & win a discount"

    page = models.ForeignKey(
        SmartPage, on_delete=models.CASCADE, related_name="modules"
    )
    module_type = models.CharField(max_length=24, choices=ModuleType.choices)
    title = models.CharField(max_length=160, blank=True)
    subtitle = models.CharField(max_length=240, blank=True)
    content = models.JSONField(default=dict, blank=True)
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.URLField(blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=100)
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Page Module"
        verbose_name_plural = "Page Modules"
        ordering = ["sort_order", "priority", "id"]

    def __str__(self):
        return f"{self.get_module_type_display()} @ {self.page.slug}"

    def is_live(self, now=None):
        now = now or timezone.now()
        if not self.enabled:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True


class Campaign(TimeStampedModel):
    """Marketing campaign / offer (spec section 21)."""

    class CampaignType(models.TextChoices):
        OFFER = "offer", "Special offer"
        PROMO = "promo", "Promotion"
        EVENT = "event", "Event"
        SEASONAL = "seasonal", "Seasonal"

    class OutletScope(models.TextChoices):
        ALL = "all_outlets", "All outlets"
        SELECTED = "selected_outlets", "Selected outlets"
        BRAND_ONLY = "brand_only", "Brand-level only"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Approval"
        SCHEDULED = "scheduled", "Scheduled"
        LIVE = "live", "Live"
        ENDED = "ended", "Ended"

    name = models.CharField(max_length=160)
    campaign_type = models.CharField(
        max_length=16, choices=CampaignType.choices, default=CampaignType.OFFER
    )
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="campaigns")
    outlets = models.ManyToManyField(
        Outlet, blank=True, related_name="campaigns",
        help_text="Used when outlet_scope = selected_outlets",
    )
    outlet_scope = models.CharField(
        max_length=20, choices=OutletScope.choices, default=OutletScope.ALL
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    hero_image = models.ImageField(upload_to="campaigns/", blank=True)
    cta_label = models.CharField(max_length=80, blank=True)
    cta_target = models.URLField(blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns_created",
    )
    approved_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns_approved",
    )

    class Meta:
        verbose_name = "Campaign"
        verbose_name_plural = "Campaigns"
        ordering = ["-start_at"]

    def __str__(self):
        return f"{self.name} [{self.brand.code}]"

    def is_live(self, now=None):
        now = now or timezone.now()
        return self.status in (self.Status.LIVE, self.Status.SCHEDULED) and (
            self.start_at <= now <= self.end_at
        )

    def approve(self, user=None):
        """
        Campaign workflow (spec section 29): Approval -> Automatically
        Publish -> Automatically Expire. The window decides whether the
        campaign becomes SCHEDULED (start in the future) or LIVE now;
        an already-passed window expires it. Approval is recorded on
        approved_by (spec section 28 data model).
        """
        now = timezone.now()
        if now < self.start_at:
            self.status = self.Status.SCHEDULED
        elif now <= self.end_at:
            self.status = self.Status.LIVE
        else:
            self.status = self.Status.ENDED
        if user is not None:
            self.approved_by = user
        self.save(update_fields=["status", "approved_by", "updated_at"])
        return self


class QrCode(TimeStampedModel):
    """
    Permanent printed QR code (spec sections 22-23).

    The redirect_key never changes; the destination can be re-pointed.
    Naming convention: [BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE] (MAIN if no outlet).
    """

    class SourceType(models.TextChoices):
        ENTRANCE = "entrance", "Entrance"
        TABLE = "table", "Table"
        COUNTER = "counter", "Counter"
        RECEIPT = "receipt", "Receipt"
        TAKEAWAY = "takeaway_bag", "Takeaway bag"
        DELIVERY = "delivery_bag", "Delivery bag"
        FLYER = "flyer", "Flyer"
        WINDOW = "window", "Window / street signage"
        SOCIAL = "social", "Social media"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=60, blank=True, help_text="e.g. KC-IC-001")
    qr_code_name = models.CharField(
        max_length=80, unique=True,
        help_text="[BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE], e.g. KINGCHEF-DEIRA-TABLE-018",
    )
    destination_page = models.ForeignKey(
        SmartPage, on_delete=models.PROTECT, related_name="qr_codes"
    )
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    source_location = models.CharField(max_length=120, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="qr_codes")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True, related_name="qr_codes"
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qr_codes",
    )
    redirect_key = models.SlugField(
        max_length=64, unique=True, editable=False,
        help_text="Permanent public key used in /q/<key>/ (spec section 23)",
    )
    scan_count = models.PositiveIntegerField(default=0)
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "QR Code"
        verbose_name_plural = "QR Codes"
        ordering = ["qr_code_name"]

    def __str__(self):
        return self.label or self.qr_code_name

    def clean(self):
        """Enforce the QR naming convention [BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE]
        (spec section 22); MAIN is used as the outlet segment when none exists.
        A QR belongs to exactly one outlet (outlet is mandatory unless brand has no outlets)."""
        from django.core.exceptions import ValidationError

        super().clean()
        if not self.outlet_id and self.brand_id and self.brand.outlets.exists():
            raise ValidationError(
                {"outlet": "A QR belongs to exactly one outlet for brands with outlets."}
            )
        parts = self.qr_code_name.split("-")
        if len(parts) < 4:
            raise ValidationError(
                {"qr_code_name": "Format: [BRAND]-[OUTLET]-[SOURCE]-[SEQUENCE]"}
            )
        if self.brand_id and parts[0] != self.brand.code:
            raise ValidationError(
                {"qr_code_name": f"First segment must be the brand code {self.brand.code}"}
            )
        if self.outlet_id and not self.qr_code_name.startswith(f"{self.brand.code}-{self.outlet.code.split('-')[-1]}-"):
            raise ValidationError(
                {"qr_code_name": "Outlet segment must match the outlet code"}
            )

    def save(self, *args, **kwargs):
        if not self.redirect_key:
            self.redirect_key = uuid.uuid4().hex[:12]
        super().save(*args, **kwargs)


class OutletManager(TimeStampedModel):
    """
    Manager profile for role-based scoping in /panel/.

    Two roles (brand/branch structural changes stay head-office only):
    - outlet_manager: manages the assigned outlets (branches)
    - brand_manager: manages ALL outlets of one brand
    """

    class Role(models.TextChoices):
        OUTLET = "outlet_manager", "Outlet Manager"
        BRAND = "brand_manager", "Brand Manager"

    user = models.OneToOneField(
        "auth.User", on_delete=models.CASCADE, related_name="outlet_manager_profile"
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.OUTLET
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="managers",
        help_text="Set for brand managers: scope is all outlets of this brand",
    )
    outlets = models.ManyToManyField(Outlet, related_name="managers", blank=True)
    can_edit_contact = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Outlet Manager"
        verbose_name_plural = "Outlet Managers"

    def __str__(self):
        role = "Brand Manager" if self.role == self.Role.BRAND else "Manager"
        return f"{self.user.username} ({role})"

    def managed_outlets(self):
        """Outlets in this manager's scope (all brand outlets for brand managers)."""
        if self.role == self.Role.BRAND and self.brand_id:
            return Outlet.objects.filter(brand_id=self.brand_id)
        return self.outlets.all()


class ChangeLog(models.Model):
    """Audit log of actions taken in the management panel."""

    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, null=True, blank=True)
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, null=True, blank=True)
    action = models.CharField(max_length=40)
    object_repr = models.CharField(max_length=200)
    details = models.JSONField(default=dict, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Change Log"
        verbose_name_plural = "Change Logs"
        ordering = ["-changed_at"]

    def __str__(self):
        user_str = self.user.username if self.user else "System"
        return f"{self.action} by {user_str} at {self.changed_at:%Y-%m-%d %H:%M}"

