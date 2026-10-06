"""
KidsPlay data model.

A printed table QR is the existing QrCode (apps.core). KidsPlay does not
create a second table model. Points live only in an append-only ledger.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Outlet, QrCode


class Family(models.Model):
    """A parent account. The phone is the only personal identifier."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, unique=True, help_text="E.164, e.g. +971501234567")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    consent_at = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Family"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.phone


class KidProfile(models.Model):
    """Nickname and avatar only. No real name, age, photo, or school."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="kids")
    nickname = models.CharField(max_length=20)
    avatar = models.CharField(max_length=30)
    points_balance = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kid profile"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.nickname


class TableVisit(models.Model):
    """An in-restaurant session. Points can be earned only while this is active."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="visits")
    qr_code = models.ForeignKey(QrCode, on_delete=models.PROTECT, related_name="kidsplay_visits")
    outlet = models.ForeignKey(
        Outlet, on_delete=models.PROTECT, null=True, blank=True, related_name="kidsplay_visits"
    )
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    bill_ref = models.CharField(max_length=40, blank=True)
    bill_bonus_awarded = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Table visit"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.family.phone} · {self.qr_code}"

    def is_active(self) -> bool:
        """Open, and not past its expiry."""
        if self.closed_at is not None:
            return False
        return timezone.now() < self.expires_at


class PlayGame(models.Model):
    """A playable mini-game. Named PlayGame so it does not clash with apps.games.Game."""

    slug = models.SlugField(max_length=40, unique=True)
    title = models.CharField(max_length=60)
    description = models.CharField(max_length=120)
    icon = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    min_duration_ms = models.PositiveIntegerField(default=5000)
    max_duration_ms = models.PositiveIntegerField(default=600000)
    max_score = models.PositiveIntegerField(default=150)
    max_score_per_second = models.FloatField(default=2.5)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Play game"
        ordering = ["sort_order", "title"]

    def __str__(self) -> str:
        return self.title


class PointsTier(models.Model):
    """Highest tier whose min_score the result reaches is the award."""

    game = models.ForeignKey(PlayGame, on_delete=models.CASCADE, related_name="tiers")
    min_score = models.PositiveIntegerField()
    points = models.PositiveIntegerField()

    class Meta:
        ordering = ["min_score"]
        constraints = [
            models.UniqueConstraint(fields=["game", "min_score"], name="kidsplay_tier_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.game.slug} ≥{self.min_score} → {self.points}"


class GameSession(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        FINISHED = "finished", "Finished"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kid = models.ForeignKey(KidProfile, on_delete=models.CASCADE, related_name="sessions")
    visit = models.ForeignKey(TableVisit, on_delete=models.PROTECT, related_name="sessions")
    game = models.ForeignKey(PlayGame, on_delete=models.PROTECT, related_name="sessions")
    token_nonce = models.CharField(max_length=32, unique=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    reported_score = models.IntegerField(null=True, blank=True)
    reported_duration_ms = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.STARTED)
    reject_reason = models.CharField(max_length=40, blank=True)
    points_awarded = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Game session"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.game.slug} · {self.status}"


class PointsLedger(models.Model):
    """Append-only. Corrections are new rows, never edits."""

    class Reason(models.TextChoices):
        GAME = "game", "Game"
        BILL_BONUS = "bill_bonus", "Bill bonus"
        REDEMPTION = "redemption", "Redemption"
        ADMIN_ADJUST = "admin_adjust", "Admin adjust"
        REVERSAL = "reversal", "Reversal"

    kid = models.ForeignKey(
        KidProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger"
    )
    delta = models.IntegerField()
    reason = models.CharField(max_length=16, choices=Reason.choices)
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kidsplay_ledger",
    )

    class Meta:
        verbose_name = "Points ledger"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.delta:+d} {self.reason}"


class Reward(models.Model):
    title = models.CharField(max_length=80)
    image = models.ImageField(upload_to="kidsplay/rewards/", blank=True)
    cost_points = models.PositiveIntegerField()
    stock = models.PositiveIntegerField(null=True, blank=True, help_text="Blank means unlimited")
    is_active = models.BooleanField(default=True)
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, null=True, blank=True, related_name="kidsplay_rewards"
    )

    class Meta:
        ordering = ["cost_points", "title"]

    def __str__(self) -> str:
        return self.title


class Redemption(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kid = models.ForeignKey(KidProfile, on_delete=models.PROTECT, related_name="redemptions")
    reward = models.ForeignKey(Reward, on_delete=models.PROTECT, related_name="redemptions")
    code = models.CharField(max_length=6)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kidsplay_redemptions",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(status="pending"),
                name="kidsplay_pending_code_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.status}"


class OTPChallenge(models.Model):
    """Short-lived phone code. The code itself is hashed."""

    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.phone
