from django.contrib import admin

from .models import ScanEvent


@admin.register(ScanEvent)
class ScanEventAdmin(admin.ModelAdmin):
    list_display = ("scanned_at", "qr_code", "brand", "outlet", "campaign", "language")
    list_filter = ("brand", "qr_code__source_type", "language")
    date_hierarchy = "scanned_at"
    search_fields = ("qr_code__qr_code_name",)
    readonly_fields = ("qr_code", "brand", "outlet", "campaign",
                       "scanned_at", "language", "user_agent", "ip_hash")

    @admin.display(description="Source type")
    def source_type(self, obj):
        return obj.qr_code.get_source_type_display()

    def has_add_permission(self, request):
        return False  # scans are recorded by the redirect engine only

    def has_change_permission(self, request, obj=None):
        return False
