from django.contrib import admin

from .models import Brand, Campaign, Group, Outlet, PageModule, QrCode, SmartPage


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_domain", "default_language", "status")
    search_fields = ("name", "legal_name")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name_en", "code", "default_phone", "google_place_id", "status")
    list_filter = ("status",)
    search_fields = ("name_en", "name_ar", "code")
    prepopulated_fields = {"code": ("name_en",)}


@admin.register(Outlet)
class OutletAdmin(admin.ModelAdmin):
    list_display = (
        "official_name", "brand", "code", "city", "emirate", "phone", "active",
    )
    list_filter = ("brand", "active", "city")
    search_fields = ("official_name", "code", "city")
    prepopulated_fields = {"code": ("official_name",)}


class PageModuleInline(admin.TabularInline):
    model = PageModule
    extra = 0
    ordering = ("sort_order", "priority")
    fields = (
        "module_type", "title", "subtitle", "cta_label", "cta_url",
        "sort_order", "priority", "enabled",
    )


@admin.register(SmartPage)
class SmartPageAdmin(admin.ModelAdmin):
    list_display = (
        "slug", "brand", "outlet", "page_title", "published", "updated_at",
    )
    list_filter = ("brand", "published")
    search_fields = ("slug", "page_title", "hero_title")
    inlines = [PageModuleInline]
    actions = ["publish_pages"]

    @admin.action(description="Publish selected Smart Pages")
    def publish_pages(self, request, queryset):
        for page in queryset:
            page.publish()


@admin.register(QrCode)
class QrCodeAdmin(admin.ModelAdmin):
    list_display = (
        "qr_code_name", "brand", "outlet", "source_type",
        "destination_page", "redirect_key", "active",
    )
    list_filter = ("brand", "source_type", "active")
    search_fields = ("qr_code_name", "redirect_key")
    readonly_fields = ("redirect_key", "created_at", "updated_at")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name", "brand", "campaign_type", "outlet_scope",
        "start_at", "end_at", "status", "created_by", "approved_by",
    )
    list_filter = ("brand", "campaign_type", "status")
    search_fields = ("name",)
    filter_horizontal = ("outlets",)
    actions = ["approve_campaigns", "return_to_draft"]
    readonly_fields = ("approved_by", "created_by", "created_at", "updated_at")

    @admin.action(description="Approve selected campaigns (publishes per schedule)")
    def approve_campaigns(self, request, queryset):
        """Spec section 29: Approval -> Automatically Publish -> Automatically Expire."""
        for campaign in queryset:
            campaign.approve(request.user)
        self.message_user(
            request, f"{queryset.count()} campaign(s) approved by {request.user.username}."
        )

    @admin.action(description="Return selected campaigns to draft")
    def return_to_draft(self, request, queryset):
        updated = queryset.update(status=Campaign.Status.DRAFT, approved_by=None)
        self.message_user(request, f"{updated} campaign(s) returned to draft.")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user  # spec 28: created by / approved by
        super().save_model(request, obj, form, change)
