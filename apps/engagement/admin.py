from django.contrib import admin

from .models import Feedback, Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "customer_name", "lead_type", "brand", "outlet",
        "status", "created_at", "assigned_to",
    )
    list_filter = ("brand", "lead_type", "status")
    search_fields = ("customer_name", "phone", "email", "message")


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "rating", "category", "brand", "outlet", "customer_name",
        "status", "created_at",
    )
    list_filter = ("brand", "category", "status", "rating")
    search_fields = ("message", "customer_name", "customer_phone")
