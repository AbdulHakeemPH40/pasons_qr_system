from django.contrib import admin

from apps.kidsplay.models import (
    Family,
    GameSession,
    KidProfile,
    OTPChallenge,
    PlayGame,
    PointsLedger,
    PointsTier,
    Redemption,
    Reward,
    TableVisit,
)


class KidInline(admin.TabularInline):
    model = KidProfile
    extra = 0
    fields = ("nickname", "avatar", "points_balance", "created_at")
    readonly_fields = ("points_balance", "created_at")


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("phone", "is_blocked", "consent_at", "last_seen_at")
    list_filter = ("is_blocked",)
    search_fields = ("phone",)
    inlines = [KidInline]


@admin.register(KidProfile)
class KidProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "family", "avatar", "points_balance")
    search_fields = ("nickname", "family__phone")


@admin.register(TableVisit)
class TableVisitAdmin(admin.ModelAdmin):
    list_display = ("family", "qr_code", "outlet", "started_at", "expires_at", "closed_at")
    list_filter = ("outlet",)
    search_fields = ("family__phone", "qr_code__redirect_key", "qr_code__label")


class TierInline(admin.TabularInline):
    model = PointsTier
    extra = 0


@admin.register(PlayGame)
class PlayGameAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("slug", "title")
    inlines = [TierInline]


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ("game", "kid", "status", "reported_score", "points_awarded", "started_at")
    list_filter = ("status", "game")
    search_fields = ("kid__nickname", "token_nonce")
    readonly_fields = ("token_nonce", "started_at")


@admin.register(PointsLedger)
class PointsLedgerAdmin(admin.ModelAdmin):
    list_display = ("kid", "delta", "reason", "ref_type", "created_at", "created_by")
    list_filter = ("reason",)
    search_fields = ("kid__nickname", "kid__family__phone", "ref_id")
    readonly_fields = ("kid", "delta", "reason", "ref_type", "ref_id", "created_at", "created_by")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ("title", "cost_points", "stock", "is_active", "outlet")
    list_filter = ("is_active", "outlet")
    search_fields = ("title",)


@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    list_display = ("code", "kid", "reward", "status", "created_at", "confirmed_by")
    list_filter = ("status",)
    search_fields = ("code", "kid__nickname", "kid__family__phone")


@admin.register(OTPChallenge)
class OTPChallengeAdmin(admin.ModelAdmin):
    list_display = ("phone", "created_at", "expires_at", "attempts", "consumed_at")
    search_fields = ("phone",)
    readonly_fields = ("code_hash",)
