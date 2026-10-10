"""
Games Zone models — GAMES_ZONE_PLAN.md section 4.

GameEvent        our own analytics for the play funnel (played / finished
                 with score). The QR entry tap keeps using the existing
                 TapEvent GAME action so panel tap stats stay continuous.
BrandGameSetting per-brand enable toggle behind the panel Games page;
                 absence of a row means "registry default".
"""

from django.db import models

from apps.core.models import Brand, Outlet, QrCode


class GameEvent(models.Model):
    """One row per played / finished beacon from a play page."""

    class Kind(models.TextChoices):
        PLAYED = "played", "Played"
        FINISHED = "finished", "Finished"

    game_slug = models.CharField(max_length=40, db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    score = models.IntegerField(null=True, blank=True)
    brand = models.ForeignKey(
        Brand, on_delete=models.CASCADE, related_name="game_events",
        null=True, blank=True,
    )
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, related_name="game_events",
        null=True, blank=True,
    )
    qr_code = models.ForeignKey(
        QrCode, on_delete=models.SET_NULL, related_name="game_events",
        null=True, blank=True,
    )
    session_key = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Game Event"
        verbose_name_plural = "Game Events"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["game_slug", "kind", "created_at"])]

    def __str__(self):
        return f"{self.kind} {self.game_slug} score={self.score}"


class BrandGameSetting(models.Model):
    """Head-office toggle: enable/disable one game for one brand."""

    brand = models.ForeignKey(
        Brand, on_delete=models.CASCADE, related_name="game_settings"
    )
    game_slug = models.CharField(max_length=40)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Brand Game Setting"
        verbose_name_plural = "Brand Game Settings"
        unique_together = ("brand", "game_slug")
        ordering = ["brand__name_en", "game_slug"]

    def __str__(self):
        state = "on" if self.enabled else "off"
        return f"{self.brand.name_en}: {self.game_slug} {state}"
