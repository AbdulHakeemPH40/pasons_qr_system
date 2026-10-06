"""
QR scan analytics & tap tracking — spec section 24, 50.

Raw event rows recorded at redirect/landing time, aggregated
at read time for management KPIs.
"""

from django.db import models

from apps.core.models import Brand, Campaign, Outlet, QrCode


class ScanEvent(models.Model):
    qr_code = models.ForeignKey(
        QrCode, on_delete=models.CASCADE, related_name="scan_events"
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.CASCADE, related_name="scan_events"
    )
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True,
        related_name="scan_events",
    )
    campaign = models.ForeignKey(
        Campaign, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scan_events",
    )
    scanned_at = models.DateTimeField(auto_now_add=True, db_index=True)
    language = models.CharField(max_length=8, blank=True)
    user_agent = models.CharField(max_length=240, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    referrer = models.CharField(max_length=255, blank=True)
    device_class = models.CharField(max_length=20, default="mobile", blank=True)
    ip_hash = models.CharField(
        max_length=64, blank=True,
        help_text="Salted hash only — raw IPs are never stored",
    )

    class Meta:
        verbose_name = "Scan Event"
        verbose_name_plural = "Scan Events"
        ordering = ["-scanned_at"]
        indexes = [
            models.Index(fields=["outlet", "scanned_at"]),
            models.Index(fields=["qr_code", "scanned_at"]),
        ]

    def __str__(self):
        return f"{self.qr_code.qr_code_name} @ {self.scanned_at:%Y-%m-%d %H:%M}"


class TapEvent(models.Model):
    """Tracks customer interaction taps on the 5 landing window options and info strip."""

    class ActionType(models.TextChoices):
        SPECIALS = "specials", "Specials"
        MENU = "menu", "Menu"
        REVIEW = "review", "Google Review"
        INSTAGRAM = "instagram", "Instagram"
        GAME = "game", "Play Game"
        DIRECTIONS = "directions", "Directions"
        CALL = "call", "Call"
        ORDER = "order", "Order Online"

    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, related_name="tap_events", null=True, blank=True
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.CASCADE, related_name="tap_events"
    )
    qr_code = models.ForeignKey(
        QrCode, on_delete=models.CASCADE, null=True, blank=True, related_name="tap_events"
    )
    action = models.CharField(max_length=32, choices=ActionType.choices)
    session_key = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Tap Event"
        verbose_name_plural = "Tap Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["outlet", "action", "created_at"]),
            models.Index(fields=["brand", "action", "created_at"]),
        ]

    def __str__(self):
        target = self.outlet.official_name if self.outlet else self.brand.name_en
        return f"{self.action} on {target} at {self.created_at:%Y-%m-%d %H:%M}"
