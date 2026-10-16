"""
Game rewards -- the climb that pays a dessert or a discount.

Client decision 2026-10-16, second pass:

  * MERELY PLAYING NEVER PAYS. Not a coupon, not a dessert, in any game.
  * PAY FOR A CLIMB, NOT FOR A SCORE. A reward is the top of a ladder that
    has to be climbed in order, or the end of a run of genuine rounds.
  * A GUEST HAS TO BE VERIFIED TO BE PAID (GuestProfile.is_verified: first
    name, last name and mobile, or Google). Playing is completely open and
    is never gated.

Per game, as the client specified:

  chess-master   four rungs, Level 1 to Level 4. Win rung N to unlock rung
                 N+1. Level 1 and Level 2 pay NOTHING. A Level 3 win pays
                 the free dessert. A Level 4 win pays the 10% discount.
  memory-match   never a coupon. A free dessert only, after 5 qualifying
                 rounds inside 7 days.
  2048           pure play. Pays nothing at all.
  flappy-burger  a free dessert when one real round clears 25 pipes. Never a
                 coupon.

Why the rules live in the database as well as in the games registry:

  apps/games/registry.py carries the per-game defaults (the effort floors and
  the rung prizes). A RewardRule row for the same game and tier OVERRIDES
  the default, which is how staff retune the win bar from the panel without a
  code change. With no rows at all the registry defaults apply, so the engine
  still works on a fresh database.

Honest limits, stated once so nobody has to rediscover them:

  * Scores, durations and action counts all arrive from the browser and a
    determined guest can fake any of them. Nothing here is proof of a real
    win. What these rules buy is EFFORT: a bot has to play a round of real
    length, climb the chess ladder rung by rung, repeat genuine rounds over
    days, and hand over a name and a mobile number to be paid.
  * The real defence is ONE DESSERT AND ONE DISCOUNT PER MOBILE NUMBER PER
    CALENDAR MONTH (clearing cookies does not start a fresh allowance) plus
    the per-brand monthly cap. A signed, short-lived round token
    (apps/rewards/services.py) is a speed bump on top, not proof.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import Brand, Outlet, TimeStampedModel
from apps.guests.models import GuestProfile

# Score lines. Ordered high first everywhere, because the HIGH tier must win
# when a score clears both lines ("two tiers, one reward").
class RewardTier(models.TextChoices):
    GOOD = "good", "Good win"
    HIGH = "high", "High win"


class RewardType(models.TextChoices):
    DESSERT = "dessert", "Free dessert"
    PERCENT = "percent", "Percentage discount"


class RewardRule(TimeStampedModel):
    """The win bar for one game and one tier. Overrides the registry default."""

    game_slug = models.CharField(max_length=40, db_index=True)
    tier = models.CharField(max_length=8, choices=RewardTier.choices)
    min_score = models.PositiveIntegerField(
        help_text="In that game's own scoring units"
    )
    reward_type = models.CharField(
        max_length=12,
        choices=RewardType.choices,
        default=RewardType.DESSERT,
    )
    percent = models.PositiveSmallIntegerField(
        default=0, help_text="Discount percentage. Ignored for a dessert."
    )
    cooldown_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="One reward per guest in this many days, across every game",
    )
    valid_days = models.PositiveSmallIntegerField(
        default=14, help_text="How long an issued coupon stays redeemable"
    )
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Reward Rule"
        verbose_name_plural = "Reward Rules"
        unique_together = (("game_slug", "tier"),)
        ordering = ["game_slug", "-min_score"]

    def __str__(self):
        return f"{self.game_slug} {self.tier} >= {self.min_score} -> {self.label}"

    @property
    def label(self):
        return coupon_label(self.reward_type, self.percent)


class BrandRewardSettings(TimeStampedModel):
    """Per-brand switch and monthly budget for issued coupons."""

    brand = models.OneToOneField(
        Brand, on_delete=models.CASCADE, related_name="reward_settings"
    )
    is_active = models.BooleanField(default=True)
    monthly_coupon_cap = models.PositiveIntegerField(
        default=0, help_text="0 means no cap"
    )

    class Meta:
        verbose_name = "Brand Reward Settings"
        verbose_name_plural = "Brand Reward Settings"

    def __str__(self):
        state = "on" if self.is_active else "off"
        return f"{self.brand.name_en}: {state}"


class RewardCoupon(TimeStampedModel):
    """A won reward. Staff redeem it from the panel; redeeming flips it once."""

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        REDEEMED = "redeemed", "Redeemed"
        EXPIRED = "expired", "Expired"
        VOID = "void", "Void"

    code = models.CharField(max_length=16, unique=True)
    profile = models.ForeignKey(
        GuestProfile, on_delete=models.CASCADE, related_name="coupons"
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.CASCADE, related_name="coupons", null=True, blank=True
    )
    outlet = models.ForeignKey(
        Outlet, on_delete=models.SET_NULL, related_name="coupons", null=True, blank=True
    )
    game_slug = models.CharField(max_length=40)
    tier = models.CharField(max_length=8, choices=RewardTier.choices)
    score = models.PositiveIntegerField(default=0)
    reward_type = models.CharField(max_length=12, choices=RewardType.choices)
    percent = models.PositiveSmallIntegerField(default=0)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ISSUED, db_index=True
    )
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        related_name="coupons_redeemed",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Reward Coupon"
        verbose_name_plural = "Reward Coupons"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["profile", "-issued_at"]),
            models.Index(fields=["brand", "status"]),
        ]

    def __str__(self):
        return f"{self.code} {self.label}"

    @property
    def label(self):
        return coupon_label(self.reward_type, self.percent)

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_usable(self):
        """True only while it can still be handed to staff."""
        return self.status == self.Status.ISSUED and not self.is_expired

    def mark_expired(self):
        """Lazily retire an expired coupon so the panel list stays truthful."""
        if self.status == self.Status.ISSUED and self.is_expired:
            self.status = self.Status.EXPIRED
            self.save(update_fields=["status", "updated_at"])
        return self.status


def coupon_label(reward_type, percent):
    """Guest-facing text for a reward, kept in one place."""
    if reward_type == RewardType.PERCENT:
        return f"{int(percent or 0)}% off"
    return "Free dessert"


class RoundResult(models.TextChoices):
    WIN = "win", "Won"
    DRAW = "draw", "Drawn"
    LOSS = "loss", "Lost"
    NONE = "", "Not applicable"


class RewardRound(TimeStampedModel):
    """One finished round, recorded against the guest who played it.

    This is the rung-by-rung audit trail behind the two earning rules:

      * the chess ladder reads `level` and `result` to decide whether a rung
        was cleared,
      * the Memory Match rule counts `qualified` rows inside a window.

    GameEvent (apps/games) still records every round for the play funnel and
    deliberately carries no guest. This table is the opposite: it exists only
    for rounds that came with a claim, so it holds the guest, and it is what
    the cooldown and the window counts are read from.
    """

    profile = models.ForeignKey(
        GuestProfile, on_delete=models.CASCADE, related_name="reward_rounds"
    )
    game_slug = models.CharField(max_length=40, db_index=True)
    score = models.PositiveIntegerField(default=0)
    # Proof of play, as reported by the guest's browser. Not proof, see the
    # module docstring: an effort floor, nothing more.
    duration_seconds = models.PositiveIntegerField(default=0)
    actions = models.PositiveIntegerField(default=0)
    level = models.PositiveSmallIntegerField(
        default=0, help_text="Chess rung 1-4. 0 for games with no levels."
    )
    result = models.CharField(
        max_length=8, choices=RoundResult.choices, default=RoundResult.NONE
    )
    # True when this round counts towards a run of rounds: it was really
    # played (effort floor) and it cleared the game's quality line.
    qualified = models.BooleanField(default=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        related_name="reward_rounds",
        null=True,
        blank=True,
    )
    outlet = models.ForeignKey(
        Outlet,
        on_delete=models.SET_NULL,
        related_name="reward_rounds",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Reward Round"
        verbose_name_plural = "Reward Rounds"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["profile", "game_slug", "-created_at"]),
            models.Index(fields=["game_slug", "qualified", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.game_slug} score={self.score} level={self.level}"


class RewardProgress(TimeStampedModel):
    """Where one guest stands on one game's ladder.

    Only chess uses `rung` today (1-4, the highest level unlocked). Memory
    Match reads its run of rounds from RewardRound instead, so the single
    column stays meaningful rather than becoming a scratch pad.
    """

    profile = models.ForeignKey(
        GuestProfile, on_delete=models.CASCADE, related_name="reward_progress"
    )
    game_slug = models.CharField(max_length=40)
    rung = models.PositiveSmallIntegerField(
        default=1, help_text="Highest level unlocked. 1 on a fresh profile."
    )

    class Meta:
        verbose_name = "Reward Progress"
        verbose_name_plural = "Reward Progress"
        unique_together = (("profile", "game_slug"),)
        ordering = ["profile_id", "game_slug"]

    def __str__(self):
        return f"{self.game_slug} rung {self.rung}"
