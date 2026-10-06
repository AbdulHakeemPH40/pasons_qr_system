"""
Customer engagement — leads/enquiries and feedback (spec section 21, 19).
"""

from django.db import models

from apps.core.models import Brand, Campaign, Outlet, QrCode, TimeStampedModel


class Lead(TimeStampedModel):
    class LeadType(models.TextChoices):
        GROUP_BOOKING = "group_booking", "Group booking"
        EVENT = "event", "Event"
        BULK_ORDER = "bulk_order", "Bulk order"
        GENERAL = "general", "General"

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        CLOSED = "closed", "Closed"

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="leads")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True, related_name="leads"
    )
    lead_type = models.CharField(
        max_length=16, choices=LeadType.choices, default=LeadType.GENERAL
    )
    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    source_qr = models.ForeignKey(
        QrCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    campaign = models.ForeignKey(
        Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEW
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads_assigned",
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Lead / Enquiry"
        verbose_name_plural = "Leads / Enquiries"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer_name} — {self.get_lead_type_display()}"


class Feedback(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"

    class Category(models.TextChoices):
        FOOD = "food", "Food quality"
        SERVICE = "service", "Service"
        CLEANLINESS = "cleanliness", "Cleanliness"
        VALUE = "value", "Value for money"
        OTHER = "other", "Other"

    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="feedback")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True, related_name="feedback"
    )
    rating = models.PositiveSmallIntegerField(
        default=5, help_text="1 = poor, 5 = excellent"
    )
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.OTHER
    )
    message = models.TextField()
    customer_name = models.CharField(max_length=120, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    source_qr = models.ForeignKey(
        QrCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedback"
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEW
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_assigned",
    )
    resolution = models.TextField(blank=True)

    class Meta:
        verbose_name = "Feedback"
        verbose_name_plural = "Feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}★ — {self.get_category_display()} ({self.brand.code})"
