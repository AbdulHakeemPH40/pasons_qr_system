"""
Games and Rewards data models (Spec Part C.5).
Game: memory match / puzzle config, limits, probability, voucher specs.
Reward: allocated discount vouchers tied strictly to an outlet.
"""

import uuid
import secrets
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, TimeStampedModel


class Game(TimeStampedModel):
    class GameType(models.TextChoices):
        MEMORY = "memory", "Memory Match"
        PUZZLE = "puzzle", "Slide Puzzle"
        TAP = "tap", "Tap Timing"

    class RewardType(models.TextChoices):
        PERCENT = "percent", "Percentage Discount"
        AMOUNT = "amount", "Fixed AED Amount"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="games")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True,
        related_name="games", help_text="Null = brand-wide default game; set = outlet-specific override"
    )
    title = models.CharField(max_length=120, default="Dish Match & Win!")
    game_type = models.CharField(max_length=16, choices=GameType.choices, default=GameType.MEMORY)
    configuration = models.JSONField(
        default=dict, blank=True,
        help_text='{"pairs": 6, "time_limit_sec": 90, "icons": ["biryani", "grill", "tea", "cake", "salad", "burger"]}'
    )
    enabled = models.BooleanField(default=True)
    win_probability = models.FloatField(
        default=0.85, help_text="Probability (0.0 - 1.0) of issuing a reward when game is successfully completed"
    )
    reward_type = models.CharField(
        max_length=12, choices=RewardType.choices, default=RewardType.PERCENT
    )
    discount_percent = models.PositiveSmallIntegerField(
        default=10, help_text="e.g. 5, 10, or 15%"
    )
    coupon_amount = models.DecimalField(
        max_digits=6, decimal_places=2, default=10.00, help_text="e.g. 10.00 AED"
    )
    coupon_prefix = models.CharField(max_length=10, default="KC")
    max_winners = models.PositiveIntegerField(
        default=500, help_text="Total cap of rewards issued"
    )
    daily_limit = models.PositiveIntegerField(
        default=25, help_text="Maximum winners per calendar day"
    )
    per_device_daily_limit = models.PositiveSmallIntegerField(
        default=1, help_text="Maximum rewards per device hash per calendar day"
    )
    voucher_valid_days = models.PositiveSmallIntegerField(
        default=7, help_text="Number of days reward is valid after issuance"
    )
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Game"
        verbose_name_plural = "Games"
        ordering = ["-id"]

    def __str__(self):
        scope = self.outlet.official_name if self.outlet else f"All {self.brand.name_en}"
        return f"{self.title} ({scope})"

    @property
    def is_live(self):
        if not self.enabled:
            return False
        now = timezone.now()
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True


class Reward(TimeStampedModel):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        REDEEMED = "redeemed", "Redeemed"
        EXPIRED = "expired", "Expired"
        VOID = "void", "Void"

    class RewardType(models.TextChoices):
        PERCENT = "percent", "Percentage Discount"
        AMOUNT = "amount", "Fixed AED Amount"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rewards")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, related_name="rewards",
        help_text="Outlet where the QR was scanned (mandatory)"
    )
    qr_code = models.ForeignKey(
        QrCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="rewards"
    )
    reward_type = models.CharField(max_length=12, choices=RewardType.choices)
    reward_value = models.CharField(max_length=30, help_text="e.g. '10% OFF' or '10 AED OFF'")
    coupon_code = models.CharField(max_length=32, unique=True, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    device_hash = models.CharField(max_length=64, blank=True, db_index=True)
    session_key = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ISSUED, db_index=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rewards_redeemed"
    )

    class Meta:
        verbose_name = "Reward"
        verbose_name_plural = "Rewards"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["outlet", "status"]),
            models.Index(fields=["game", "issued_at"]),
        ]

    def __str__(self):
        return f"{self.coupon_code} ({self.reward_value} @ {self.outlet.official_name})"

    @classmethod
    def generate_code(cls, prefix="WIN"):
        random_part = secrets.token_hex(3).upper()
        return f"{prefix}-{random_part}"
