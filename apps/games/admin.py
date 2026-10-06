from django.contrib import admin
from .models import Game, Reward

@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["title", "brand", "outlet", "game_type", "reward_type", "enabled"]
    list_filter = ["brand", "enabled", "reward_type"]
    search_fields = ["title", "brand__name_en", "outlet__official_name"]

@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ["coupon_code", "outlet", "reward_value", "status", "issued_at", "expires_at"]
    list_filter = ["status", "outlet__brand", "reward_type"]
    search_fields = ["coupon_code", "outlet__official_name"]
    readonly_fields = ["coupon_code", "issued_at", "device_hash"]
