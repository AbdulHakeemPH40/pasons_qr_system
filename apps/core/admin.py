from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    Brand, Campaign, Department, Group, Outlet, OutletManager, PageModule,
    QrCode, SmartPage,
)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_domain", "default_language", "status")
    search_fields = ("name", "legal_name")


class OutletManagerInline(admin.StackedInline):
    """Attach the custom-dashboard role to a Django user.

    Superuser sets role to Brand Manager and picks one brand. That person
    then creates branch users from the custom dashboard. A branch user is
    role Outlet Manager plus the branches they may open.

    Saving a brand or branch role clears Staff status. Staff status is
    Head Office, and a brand user with that flag would see every brand.
    """

    model = OutletManager
    fk_name = "user"
    extra = 0
    filter_horizontal = ("outlets",)
    autocomplete_fields = ("brand", "department")


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (OutletManagerInline,)

    def save_formset(self, request, form, formset, change):
        """A brand or branch role cannot also be Staff.

        Staff status means Head Office and opens every brand. The superuser
        form can tick both. This drops Staff when the saved role is a manager,
        so a brand user cannot become Head Office by accident.
        """
        instances = formset.save(commit=False)
        for profile in instances:
            if not isinstance(profile, OutletManager):
                profile.save()
                continue
            if profile.role in (OutletManager.Role.BRAND, OutletManager.Role.OUTLET):
                if profile.user.is_staff or profile.user.is_superuser:
                    profile.user.is_staff = False
                    profile.user.is_superuser = False
                    profile.user.save(update_fields=["is_staff", "is_superuser"])
            profile.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name_en", "code", "is_active")
    search_fields = ("name_en", "code")


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
